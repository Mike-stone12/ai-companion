"""Personality parameters that shape how strongly the companion reacts and how it shows it."""

from __future__ import annotations

from dataclasses import asdict, dataclass

# How a clearly felt negative emotion comes out in words.
STYLES = ("direct", "sarcastic", "cold", "pouty")
STYLE_LABELS = {
    "direct": "Says it straight",
    "sarcastic": "Sarcastic",
    "cold": "Goes quiet and cold",
    "pouty": "Sulks and complains cutely",
}
TRAIT_NAMES = ("irritability", "jealousy", "sensitivity", "recovery", "candor")
TRAIT_LABELS = {
    "irritability": "Quick to anger",
    "jealousy": "Jealous / possessive",
    "sensitivity": "Easily hurt",
    "recovery": "Gets over things quickly",
    "candor": "Says what she feels (low = tsundere)",
}


@dataclass(frozen=True, slots=True)
class Traits:
    """All values are 0–1. Defaults suit the childhood-friend persona."""

    irritability: float = 0.3
    jealousy: float = 0.6
    sensitivity: float = 0.5
    recovery: float = 0.6
    candor: float = 0.4
    style: str = "pouty"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Traits:
        """Validate untrusted data; numbers are clamped to 0–1, unknown keys ignored."""
        if not isinstance(data, dict):
            raise ValueError("traits must be an object")
        values: dict[str, object] = {}
        for name in TRAIT_NAMES:
            if name in data:
                value = data[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"trait {name} must be a number")
                values[name] = min(max(float(value), 0.0), 1.0)
        if "style" in data:
            if data["style"] not in STYLES:
                raise ValueError(f"style must be one of {', '.join(STYLES)}")
            values["style"] = data["style"]
        return cls(**values)


DEFAULT_TRAITS = Traits()
