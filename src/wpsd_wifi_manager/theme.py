from __future__ import annotations

import configparser
import re
from pathlib import Path
from typing import Any


DEFAULT_WPSD_CSS_PATH = "/etc/wpsd-css.ini"
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

FALLBACK_THEME = {
    "source": "fallback",
    "path": "",
    "variables": {
        "--bg": "#050708",
        "--panel": "#0b1012",
        "--panel-2": "#11191c",
        "--line": "#253338",
        "--text": "#edf6f4",
        "--muted": "#98aaa8",
        "--accent": "#00c16a",
        "--accent-2": "#f5a524",
        "--danger": "#ff5c66",
        "--field": "#06090a",
        "--banner": "#020405",
        "--link": "#b58cff",
        "--row-even": "#080e12",
        "--row-odd": "#04080a",
    },
}


def read_wpsd_theme(path: str | Path = DEFAULT_WPSD_CSS_PATH) -> dict[str, Any]:
    theme_path = Path(path)
    if not theme_path.exists():
        return _fallback_theme()

    parser = configparser.ConfigParser()
    parser.optionxform = str
    try:
        parser.read(theme_path, encoding="utf-8")
        variables = dict(FALLBACK_THEME["variables"])
        background = parser["Background"] if parser.has_section("Background") else {}
        text = parser["Text"] if parser.has_section("Text") else {}
        extras = parser["ExtraSettings"] if parser.has_section("ExtraSettings") else {}
        _set_color(variables, "--bg", background.get("PageColor"))
        _set_color(variables, "--panel", background.get("ContentColor"))
        _set_color(variables, "--panel-2", background.get("NavPanelColor"))
        _set_color(variables, "--line", extras.get("TableBorderColor"))
        _set_color(variables, "--text", text.get("TextColor"))
        _set_color(variables, "--muted", text.get("TextSectionColor"))
        _set_color(variables, "--accent", background.get("ModeCellActiveColor"))
        _set_color(variables, "--accent-2", text.get("BannersColor"))
        _set_color(variables, "--danger", background.get("ModeCellInactiveColor"))
        _set_color(variables, "--field", background.get("DropdownColor"))
        _set_color(variables, "--banner", background.get("BannersColor"))
        _set_color(variables, "--link", text.get("TextLinkColor"))
        _set_color(variables, "--row-even", background.get("TableRowBgEvenColor"))
        _set_color(variables, "--row-odd", background.get("TableRowBgOddColor"))
        return {
            "source": "wpsd",
            "path": str(theme_path),
            "variables": variables,
        }
    except Exception as exc:
        theme = _fallback_theme()
        theme["error"] = str(exc)
        return theme


def _fallback_theme() -> dict[str, Any]:
    return {
        "source": FALLBACK_THEME["source"],
        "path": FALLBACK_THEME["path"],
        "variables": dict(FALLBACK_THEME["variables"]),
    }


def _set_color(variables: dict[str, str], css_variable: str, value: str | None) -> None:
    if value and HEX_COLOR_RE.match(value):
        variables[css_variable] = value.lower()
