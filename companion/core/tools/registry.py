"""Build OpenAI-compatible tool schemas without GUI or network dependencies."""

import inspect
import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from types import UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints

_SCALAR_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


@dataclass
class ToolResult:
    name: str
    ok: bool
    content: str


@dataclass
class _Tool:
    func: Callable
    signature: inspect.Signature
    schema: dict
    nullable: set[str]


def _annotation_schema(annotation) -> tuple[dict, bool]:
    """Return the schema and whether an argument can be omitted or null."""
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, UnionType) and type(None) in args:
        remaining = [arg for arg in args if arg is not type(None)]
        if len(remaining) == 1:
            schema, _ = _annotation_schema(remaining[0])
            return schema, True
    if annotation in _SCALAR_TYPES:
        return {"type": _SCALAR_TYPES[annotation]}, False
    if origin is list and len(args) == 1 and args[0] in (str, int):
        return {"type": "array", "items": {"type": _SCALAR_TYPES[args[0]]}}, False
    if origin is Literal and args:
        if any(type(value) not in (*_SCALAR_TYPES, type(None)) for value in args):
            raise TypeError(f"Unsupported annotation: {annotation!r}")
        schema = {"enum": list(args)}
        value_types = {type(value) for value in args}
        if len(value_types) == 1:
            value_type = next(iter(value_types))
            schema["type"] = "null" if value_type is type(None) else _SCALAR_TYPES[value_type]
        return schema, False
    raise TypeError(f"Unsupported annotation: {annotation!r}")


def _parameter_descriptions(docstring: str) -> dict[str, str]:
    """Read simple ``name: text`` entries and indented continuation lines."""
    descriptions = {}
    in_args = False
    current = None
    entry_indent = None
    for line in docstring.splitlines():
        stripped = line.strip()
        if not in_args:
            if stripped == "Args:":
                in_args = True
            continue
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        match = re.match(r"(\w+):\s*(.*)", stripped)
        if match and (entry_indent is None or indent == entry_indent):
            current, description = match.groups()
            descriptions[current] = description
            entry_indent = indent
        elif current is not None and indent > entry_indent:
            descriptions[current] += " " + stripped
    return descriptions


def _matches(value, schema: dict) -> bool:
    if "enum" in schema:
        # Python considers True == 1, but JSON booleans and integers are distinct.
        return any(type(value) is type(choice) and value == choice for choice in schema["enum"])
    match schema["type"]:
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        case "boolean":
            return isinstance(value, bool)
        case "array":
            return isinstance(value, list) and all(_matches(item, schema["items"]) for item in value)
    return False


class ToolRegistry:
    """Register synchronous functions, describe them, and validate calls."""

    def __init__(self):
        self._tools: dict[str, _Tool] = {}

    def register(self, func: Callable, *, name: str | None = None, description: str | None = None) -> None:
        if not inspect.isfunction(func):
            raise TypeError("Tools must be plain Python functions")
        tool_name = func.__name__ if name is None else name
        if tool_name in self._tools:
            raise ValueError(f"Tool already registered: {tool_name}")
        signature = inspect.signature(func)
        try:
            hints = get_type_hints(func, include_extras=True)
        except Exception as exc:
            raise TypeError("Cannot resolve tool type hints") from exc
        docstring = inspect.getdoc(func) or ""
        parameter_descriptions = _parameter_descriptions(docstring)
        properties = {}
        required = []
        nullable = set()
        for parameter in signature.parameters.values():
            if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                raise TypeError(f"Variadic parameter is unsupported: {parameter.name}")
            if parameter.name not in hints:
                raise TypeError(f"Missing annotation for parameter: {parameter.name}")
            schema, optional = _annotation_schema(hints[parameter.name])
            if parameter.name in parameter_descriptions:
                schema["description"] = parameter_descriptions[parameter.name]
            properties[parameter.name] = schema
            if optional:
                nullable.add(parameter.name)
            elif parameter.default is inspect.Parameter.empty:
                required.append(parameter.name)
        function_schema = {
            "name": tool_name,
            "description": re.split(r"\n\s*\n", docstring, maxsplit=1)[0].strip()
            if description is None else description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        }
        self._tools[tool_name] = _Tool(func, signature, {"type": "function", "function": function_schema}, nullable)

    def tool(self, func=None, *, name: str | None = None, description: str | None = None):
        """Decorate with ``@registry.tool`` or ``@registry.tool(name=...)``."""
        def decorate(function):
            self.register(function, name=name, description=description)
            return function

        return decorate if func is None else decorate(func)

    def schemas(self) -> list[dict]:
        """Return independent schema copies in registration order."""
        return [deepcopy(tool.schema) for tool in self._tools.values()]

    def execute(self, name: str, arguments: str | dict) -> ToolResult:
        """Validate and call a tool, returning errors as results.

        Omitted Optional parameters without defaults receive None. Explicit
        Python defaults are preserved. Tool and serialization exceptions are
        reported without exposing a traceback or arbitrary exception text.
        """
        try:
            if name not in self._tools:
                return ToolResult(name, False, "Unknown tool")
            tool = self._tools[name]
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    return ToolResult(name, False, "Invalid JSON arguments")
            if not isinstance(arguments, dict):
                return ToolResult(name, False, "Arguments must be a JSON object")
            parameters = tool.schema["function"]["parameters"]
            properties = parameters["properties"]
            for argument in arguments:
                if argument not in properties:
                    return ToolResult(name, False, f"Unexpected argument: {argument}")
            for required in parameters["required"]:
                if required not in arguments:
                    return ToolResult(name, False, f"Missing required argument: {required}")
            for argument, value in arguments.items():
                if value is None and argument in tool.nullable:
                    continue
                if not _matches(value, properties[argument]):
                    return ToolResult(name, False, f"Invalid type or value for argument: {argument}")

            # BoundArguments also supports positional-only and keyword-only parameters.
            bound = tool.signature.bind_partial()
            bound.arguments.update(arguments)
            for parameter in tool.signature.parameters.values():
                if (parameter.name not in arguments and parameter.name in tool.nullable
                        and parameter.default is inspect.Parameter.empty):
                    bound.arguments[parameter.name] = None
            bound.apply_defaults()
            value = tool.func(*bound.args, **bound.kwargs)
            content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return ToolResult(name, True, content)
        except Exception as exc:
            return ToolResult(name, False, f"Tool execution failed ({type(exc).__name__})")
