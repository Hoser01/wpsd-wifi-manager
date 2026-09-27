from __future__ import annotations

from pathlib import Path

from wpsd_wifi_manager.logs import tail_log
from wpsd_wifi_manager.theme import read_wpsd_theme


def test_wifi_theme_maps_wpsd_css(tmp_path: Path) -> None:
    theme_path = tmp_path / "wpsd-css.ini"
    theme_path.write_text(
        """[Background]
PageColor=#010203
ContentColor=#05090C
BannersColor=#020405
NavPanelColor=#030707
ModeCellActiveColor=#18A558
ModeCellInactiveColor=#A93232
DropdownColor=#070D10
TableRowBgEvenColor=#080E12
TableRowBgOddColor=#04080A

[Text]
TextColor=#EEF7F4
TextSectionColor=#8FE7D2
TextLinkColor=#B58CFF
BannersColor=#E28A1A

[ExtraSettings]
TableBorderColor=#132328
""",
        encoding="utf-8",
    )

    theme = read_wpsd_theme(theme_path)

    assert theme["source"] == "wpsd"
    assert theme["variables"]["--bg"] == "#010203"
    assert theme["variables"]["--panel"] == "#05090c"
    assert theme["variables"]["--accent"] == "#18a558"
    assert theme["variables"]["--accent-2"] == "#e28a1a"


def test_tail_log_returns_recent_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "wifi-manager.log"
    log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    log = tail_log(log_path, lines=2)

    assert log["exists"] is True
    assert log["lines"] == ["two", "three"]


def test_tail_log_handles_missing_file(tmp_path: Path) -> None:
    log = tail_log(tmp_path / "missing.log")

    assert log["exists"] is False
    assert log["lines"] == []
