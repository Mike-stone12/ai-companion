from __future__ import annotations

import json
from typing import Literal, Optional

import pytest

from companion.core.tools import ToolRegistry, ToolResult


def test_schema_types_required_defaults_and_docstrings():
    registry = ToolRegistry()

    def example(
        text: str,
        count: int,
        ratio: float,
        enabled: bool,
        words: list[str],
        numbers: list[int],
        mode: Literal["fast", "slow"],
        nullable: str | None,
        legacy: Optional[int],  # noqa: UP045 -- exercise typing.Optional resolution
        limit: int = 5,
    ):
        """Describe the tool.
        This belongs to the first paragraph.

        More details that should not be the description.

        Args:
            text: Text to process.
            count: Number of repetitions.
            mode: Processing mode.
        """

    registry.register(example)
    assert registry.schemas() == [
        {
            "type": "function",
            "function": {
                "name": "example",
                "description": "Describe the tool.\nThis belongs to the first paragraph.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to process."},
                        "count": {"type": "integer", "description": "Number of repetitions."},
                        "ratio": {"type": "number"},
                        "enabled": {"type": "boolean"},
                        "words": {"type": "array", "items": {"type": "string"}},
                        "numbers": {"type": "array", "items": {"type": "integer"}},
                        "mode": {"type": "string", "enum": ["fast", "slow"], "description": "Processing mode."},
                        "nullable": {"type": "string"},
                        "legacy": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["text", "count", "ratio", "enabled", "words", "numbers", "mode"],
                },
            },
        }
    ]


def test_decorator_forms_preserve_functions_and_registration_order():
    registry = ToolRegistry()

    def original(value: str):
        return value

    assert registry.tool(original) is original
    assert registry.tool(name="alias", description="Explicit description")(original) is original

    @registry.tool
    def bare():
        return "bare"

    @registry.tool(name="custom", description="Custom description")
    def configured():
        return "configured"

    schemas = registry.schemas()
    assert [schema["function"]["name"] for schema in schemas] == ["original", "alias", "bare", "custom"]
    assert schemas[1]["function"]["description"] == "Explicit description"
    assert schemas[2]["function"]["description"] == ""
    assert schemas[3]["function"]["description"] == "Custom description"
    assert not schemas[2]["function"]["parameters"].get("required")
    assert registry.execute("bare", {}) == ToolResult("bare", True, "bare")
    assert registry.execute("custom", "{}") == ToolResult("custom", True, "configured")


@pytest.mark.parametrize(
    "annotation, expected",
    [
        (Literal[1, 2], {"type": "integer", "enum": [1, 2]}),
        (Literal[True, False], {"type": "boolean", "enum": [True, False]}),
        (Literal["auto", 1], {"enum": ["auto", 1]}),
        (list[int] | None, {"type": "array", "items": {"type": "integer"}}),
    ],
)
def test_additional_literal_and_optional_schemas(annotation, expected):
    registry = ToolRegistry()

    def example(value):
        return value

    example.__annotations__["value"] = annotation
    registry.register(example)
    assert registry.schemas()[0]["function"]["parameters"]["properties"]["value"] == expected


def test_empty_description_override_and_no_required_parameters():
    registry = ToolRegistry()

    @registry.tool(description="")
    def example(value: int = 1):
        """Default description."""
        return value

    function = registry.schemas()[0]["function"]
    assert function["description"] == ""
    assert not function["parameters"].get("required")


def test_duplicate_name_does_not_replace_original():
    registry = ToolRegistry()

    def first():
        return "first"

    def second():
        return "second"

    registry.register(first, name="shared")
    with pytest.raises(ValueError, match="shared"):
        registry.register(second, name="shared")
    assert registry.execute("shared", {}) == ToolResult("shared", True, "first")


@pytest.mark.parametrize("annotation", [dict, list, list[dict], set[str], int | str, object, "UnresolvedType"])
def test_unsupported_annotations_are_rejected_atomically(annotation):
    registry = ToolRegistry()

    def invalid(value):
        return value

    invalid.__annotations__["value"] = annotation
    with pytest.raises(TypeError):
        registry.register(invalid)
    assert registry.schemas() == []


def test_missing_annotations_and_variadic_parameters_are_rejected():
    def missing(value):
        return value

    def positional(*args: str):
        return args

    def keyword(**kwargs: int):
        return kwargs

    registry = ToolRegistry()
    for function in (missing, positional, keyword):
        with pytest.raises(TypeError):
            registry.register(function)
    assert registry.schemas() == []


@pytest.fixture
def registry():
    registry = ToolRegistry()

    @registry.tool
    def echo(value: str):
        return value

    return registry


@pytest.mark.parametrize("arguments", [{"value": "你好"}, '{"value": "你好"}'])
def test_execute_string_result(registry, arguments):
    assert registry.execute("echo", arguments) == ToolResult("echo", True, "你好")


@pytest.mark.parametrize("value", [None, 3, 2.5, True, ["你好"], {"text": "你好"}])
def test_execute_serializes_non_string_results(registry, value):
    @registry.tool
    def result():
        return value

    actual = registry.execute("result", {})
    assert actual == ToolResult("result", True, json.dumps(value, ensure_ascii=False))


def test_execute_unknown_tool(registry):
    result = registry.execute("unknown", {})
    assert result.name == "unknown"
    assert not result.ok
    assert "unknown" in result.content.lower()


@pytest.mark.parametrize(
    "arguments, message",
    [
        ("{broken", "json"),
        ("[]", "object"),
        ('"text"', "object"),
        ("null", "object"),
        ("1", "object"),
        ([], "object"),
        (None, "object"),
        ({}, "missing"),
        ({"value": "ok", "extra": 1}, "unexpected"),
        ({"value": 1}, "type"),
        ({"value": None}, "type"),
    ],
)
def test_execute_invalid_arguments(registry, arguments, message):
    result = registry.execute("echo", arguments)
    assert result.name == "echo"
    assert not result.ok
    assert message in result.content.lower()


@pytest.mark.parametrize(
    "annotation, valid, invalid",
    [
        (str, "hello", 1),
        (int, 2, True),
        (int, 2, 2.0),
        (float, 2.5, "2.5"),
        (float, 2, True),
        (bool, True, 1),
        (list[str], ["a"], [1]),
        (list[str], [], "a"),
        (list[int], [1, 2], [True]),
        (Literal["fast", "slow"], "fast", "other"),
        (Literal[1, 2], 1, True),
        (Literal[True, False], True, 1),
        (int | None, None, "wrong"),
    ],
)
def test_execute_validates_types_before_calling(annotation, valid, invalid):
    registry = ToolRegistry()
    calls = []

    def checked(value):
        calls.append(value)
        return "accepted"

    checked.__annotations__["value"] = annotation
    registry.register(checked)
    assert registry.execute("checked", {"value": valid}).ok
    result = registry.execute("checked", {"value": invalid})
    assert not result.ok
    assert "value" in result.content
    assert calls == [valid]


def test_execute_optional_parameters_defaults_and_parameter_kinds():
    registry = ToolRegistry()

    @registry.tool
    def defaults(first: str | None, /, second: int | None, count: int = 7, *, label: str = "default"):
        return [first, second, count, label]

    assert json.loads(registry.execute("defaults", {}).content) == [None, None, 7, "default"]
    arguments = {"first": "a", "second": None, "count": 2, "label": "custom"}
    assert json.loads(registry.execute("defaults", arguments).content) == ["a", None, 2, "custom"]
    assert arguments == {"first": "a", "second": None, "count": 2, "label": "custom"}


def test_execute_preserves_non_none_optional_default():
    registry = ToolRegistry()

    @registry.tool
    def defaults(value: str | None = "fallback"):
        return value

    assert registry.execute("defaults", {}) == ToolResult("defaults", True, "fallback")
    assert registry.execute("defaults", {"value": None}) == ToolResult("defaults", True, "null")


def test_execute_catches_tool_exceptions(registry):
    @registry.tool
    def failing():
        raise RuntimeError("Something failed")

    result = registry.execute("failing", {})
    assert result.name == "failing"
    assert not result.ok
    assert result.content
    assert "Traceback" not in result.content


def test_execute_catches_result_serialization_errors(registry):
    @registry.tool
    def unsupported_result():
        return object()

    result = registry.execute("unsupported_result", {})
    assert not result.ok
    assert result.content
    assert "Traceback" not in result.content


def test_schemas_cannot_mutate_registry_validation(registry):
    schema = registry.schemas()[0]
    schema["function"]["parameters"]["properties"]["value"]["type"] = "integer"
    schema["function"]["parameters"]["required"].clear()
    assert registry.schemas()[0]["function"]["parameters"]["properties"]["value"]["type"] == "string"
    assert not registry.execute("echo", {}).ok
