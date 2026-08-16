#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

INDEX = Path("index.html")
NAV_MARKER = "<!-- ANNUAL_HOLIDAY_EXTREMES_DESKTOP_NAV_V1 -->"
OVERVIEW_MARKER = "<!-- ANNUAL_HOLIDAY_EXTREMES_OVERVIEW_LINKS_V1 -->"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: erwartete genau 1 Fundstelle, gefunden: {count}"
        )
    return text.replace(old, new, 1)


def main() -> int:
    if not INDEX.is_file():
        raise RuntimeError("index.html fehlt")

    text = INDEX.read_text(encoding="utf-8")
    changed = False

    if NAV_MARKER not in text:
        anchor = (
            '          <button class="tab-button" data-nav-group="germany" '
            'onclick="switchTab(\'extremes\')">Deutschland-Kenntage</button>\n'
        )
        addition = anchor + (
            f"{NAV_MARKER}\n"
            '          <button class="tab-button" data-nav-group="germany" '
            'type="button" onclick="window.location.href=\'jahresextremwerte.html\'">'
            'Jahresextreme</button>\n'
            '          <button class="tab-button" data-nav-group="germany" '
            'type="button" onclick="window.location.href=\'dekadenrekorde.html\'">'
            'Dekadenrekorde</button>\n'
            '          <button class="tab-button" data-nav-group="germany" '
            'type="button" onclick="window.location.href=\'feiertagsextremwerte.html\'">'
            'Feiertags-Extreme</button>\n'
        )
        text = replace_once(text, anchor, addition, "Deutschland-Extreme-Navigation")
        changed = True

    if OVERVIEW_MARKER not in text:
        anchor = "<!-- DWD_DECADE_RECORDS_OVERVIEW_LINK_V1 -->"
        addition = (
            f"{OVERVIEW_MARKER}\n"
            '        <button class="overview-quicklink" type="button" '
            'onclick="window.location.href=\'jahresextremwerte.html\'">\n'
            '          <span class="overview-link-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 5h16v15H4z"></path><path d="M8 2v6M16 2v6M7 12h10M7 16h7"></path></svg></span>\n'
            '          <span><span class="overview-link-title">Jahresextreme</span>'
            '<span class="overview-link-copy">TNn, TXx, Kenntage, Niederschlag, Schnee und Wind nach Jahr</span></span>\n'
            '        </button>\n'
            '        <button class="overview-quicklink" type="button" '
            'onclick="window.location.href=\'feiertagsextremwerte.html\'">\n'
            '          <span class="overview-link-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 6h16v14H4z"></path><path d="M8 3v6M16 3v6M4 10h16"></path><path d="M8 14h3M13 14h3M8 17h3"></path></svg></span>\n'
            '          <span><span class="overview-link-title">Feiertags-Extreme</span>'
            '<span class="overview-link-copy">Ostern und Weihnachten · Tmin/Tmax · Deutschland &amp; Bundesländer</span></span>\n'
            '        </button>\n'
            f"{anchor}"
        )
        text = replace_once(text, anchor, addition, "Übersicht-Direkteinstiege")
        changed = True

    if "jahresextremwerte.html" not in text:
        raise RuntimeError("Link zu jahresextremwerte.html fehlt nach Patch")
    if "feiertagsextremwerte.html" not in text:
        raise RuntimeError("Link zu feiertagsextremwerte.html fehlt nach Patch")

    if changed:
        INDEX.write_text(text, encoding="utf-8")
        print("index.html: Jahres- und Feiertagsextreme eingebunden")
    else:
        print("index.html: Navigation bereits aktuell")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
