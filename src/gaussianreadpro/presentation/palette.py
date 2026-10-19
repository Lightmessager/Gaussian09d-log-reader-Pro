"""Validated, cached lavender/sunset tokens shared without importing Qt."""
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json
import re

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_RGBA = re.compile(r"^rgba\((\d{1,3}),(\d{1,3}),(\d{1,3}),(0(?:\.\d+)?|1(?:\.0+)?)\)$")


_THEME_KEYS = frozenset({
    "canvas", "surface", "elevated", "toolbar", "text", "muted", "lavender", "primary",
    "primary_soft", "sunset", "on_sunset", "border", "border_soft", "highlight", "success",
    "warning", "danger", "disabled", "glass_fill", "glass_toolbar", "selection_text",
    "navigation", "navigation_text", "field", "field_hover", "overlay", "glow",
})
_METRIC_KEYS = frozenset({
    "radius_card", "radius_toolbar", "radius_control", "radius_badge", "space_unit", "font_body",
    "font_small", "font_heading", "font_control", "control_height", "row_height", "glass_opacity",
    "glass_toolbar_opacity", "overlay_opacity",
})


@lru_cache(maxsize=1)
def _load():
    resource = files("gaussianreadpro").joinpath("resources", "themes", "lavender_sunset.json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    if type(data) is not dict or data.get("version") != 1:
        raise ValueError("Unsupported lavender/sunset theme resource")
    themes, metrics = data.get("themes"), data.get("metrics")
    profile_themes = data.get("profile_themes")
    if type(themes) is not dict or set(themes) != {"light", "dark"}:
        raise ValueError("Theme resource must define light and dark palettes")
    if type(metrics) is not dict or set(metrics) != _METRIC_KEYS:
        raise ValueError("Theme metrics do not match the supported schema")
    for name, palette in themes.items():
        if type(palette) is not dict or set(palette) != _THEME_KEYS:
            raise ValueError(f"Invalid token set for {name}")
        if any(not isinstance(value, str) or not (_HEX.fullmatch(value) or _RGBA.fullmatch(value))
               for key, value in palette.items() if key != "glow"):
            raise ValueError(f"Invalid colour token in {name}")
        for key in ("glass_fill", "glass_toolbar", "overlay"):
            channels = _RGBA.fullmatch(palette[key])
            if not channels or any(int(channels.group(i)) > 255 for i in (1, 2, 3)):
                raise ValueError(f"Invalid alpha colour token in {name}")
        if (type(palette["glow"]) is not list or len(palette["glow"]) != 2
                or any(not _HEX.fullmatch(value) for value in palette["glow"])):
            raise ValueError(f"Invalid background glow in {name}")
    if any(type(value) not in (int, float) or value <= 0 for value in metrics.values()):
        raise ValueError("Theme metrics must be positive numbers")
    if any(not 0 < metrics[key] <= 1 for key in ("glass_opacity", "glass_toolbar_opacity", "overlay_opacity")):
        raise ValueError("Glass opacity must be within (0, 1]")
    if type(profile_themes) is not dict or set(profile_themes) != {"light", "dark"}:
        raise ValueError("Theme resource must define light and dark profile palettes")
    profile_keys = {"canvas", "header", "sidebar", "panel", "panel_highlight", "border", "grid",
                    "axis", "text", "muted", "path_a", "path_b", "focus", "curve_core"}
    for name, profile in profile_themes.items():
        if type(profile) is not dict or set(profile) != profile_keys:
            raise ValueError(f"Invalid profile token set for {name}")
        if any(not isinstance(value, str) or not (_HEX.fullmatch(value) or _RGBA.fullmatch(value))
               for value in profile.values()):
            raise ValueError(f"Invalid profile colour token in {name}")
    return data


def get_palette(theme="light"):
    """Return a defensive copy of a cached light/dark palette and its design metrics."""
    if theme not in ("light", "dark"):
        raise ValueError("theme must be 'light' or 'dark'")
    data = _load()
    return {"name": theme, "colors": deepcopy(data["themes"][theme]),
            "profile": deepcopy(data["profile_themes"][theme]),
            "metrics": deepcopy(data["metrics"]), "icons": tuple(data["icons"])}
