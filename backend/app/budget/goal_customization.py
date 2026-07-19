"""Curated, cross-client catalogs for goal/group customization.

Storage holds only these string tokens (never raw hex or SF Symbol names) so
the same value renders on iOS (SF Symbols + Theme colors), the web app, and the
copilot. This module is the backend source of truth and validator.
"""

# token -> emoji hint (used by web + the catalog preview; iOS maps token -> SF Symbol locally)
_ICONS: dict[str, str] = {
    "tag": "🏷️", "flame": "🔥", "target": "🎯", "bank": "🏦",
    "card": "💳", "cashflow": "💸", "chart": "📈", "star": "⭐",
    "heart": "❤️", "run": "🏃", "book": "📚", "house": "🏠",
    "car": "🚗", "plane": "✈️", "cart": "🛒", "gift": "🎁",
    "briefcase": "💼", "grad": "🎓", "dumbbell": "🏋️", "food": "🍴",
    "coffee": "☕", "leaf": "🍃", "bolt": "⚡", "trophy": "🏆",
    "flag": "🚩", "calendar": "📅", "bell": "🔔", "moon": "🌙",
    "sun": "☀️", "drop": "💧", "paw": "🐾", "sparkle": "✨",
}

# token -> (light hex, dark hex). First eight mirror Theme.brand/honey/negative + chartScale.
_COLORS: dict[str, tuple[str, str]] = {
    "pine": ("#146B54", "#63D0A8"),
    "honey": ("#B9871F", "#E3BE5E"),
    "copper": ("#B0562F", "#E0906A"),
    "sky": ("#46698C", "#8FB4D9"),
    "plum": ("#7A5586", "#B491C0"),
    "sage": ("#5E7A6E", "#9DB8AC"),
    "rose": ("#8C4658", "#D98FA4"),
    "clay": ("#6E6146", "#C2B08A"),
    "teal": ("#0F6E6A", "#5FC9C2"),
    "slate": ("#4A5A66", "#9BB0BE"),
}

ICON_TOKENS: list[str] = list(_ICONS)
COLOR_TOKENS: list[str] = list(_COLORS)


def is_valid_icon(token: str) -> bool:
    return token in _ICONS


def is_valid_color(token: str) -> bool:
    return token in _COLORS


def validate_icon(token: str | None) -> None:
    if token is not None and token not in _ICONS:
        raise ValueError(f"unknown icon: {token}")


def validate_color(token: str | None) -> None:
    if token is not None and token not in _COLORS:
        raise ValueError(f"unknown color: {token}")


def catalog() -> dict:
    return {
        "icons": [{"token": t, "emoji": e} for t, e in _ICONS.items()],
        "colors": [{"token": t, "light": light, "dark": dark} for t, (light, dark) in _COLORS.items()],
    }
