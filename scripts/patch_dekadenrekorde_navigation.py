#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

DESKTOP_MARKER = "<!-- DWD_DECADE_RECORDS_DESKTOP_NAV_V1 -->"
OVERVIEW_MARKER = "<!-- DWD_DECADE_RECORDS_OVERVIEW_LINK_V1 -->"

DESKTOP_INSERT = """<!-- DWD_DECADE_RECORDS_DESKTOP_NAV_V1 -->
          <button class="tab-button" data-nav-group="stations" type="button" onclick="window.location.href='dekadenrekorde.html'">Dekadenrekorde</button>"""

OVERVIEW_INSERT = """<!-- DWD_DECADE_RECORDS_OVERVIEW_LINK_V1 -->
        <button class="overview-quicklink" type="button" onclick="window.location.href='dekadenrekorde.html'">
          <span class="overview-link-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 4h14v16H5z"></path><path d="M8 8h8M8 12h8M8 16h5"></path></svg></span>
          <span><span class="overview-link-title">Dekadenrekorde</span><span class="overview-link-copy">1.–3. Dekade · Deutschland &amp; Bundesländer</span></span>
        </button>"""


def insert_after_match(text: str, pattern: str, addition: str, label: str) -> str:
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL))
    if len(matches) != 1:
        raise RuntimeError(
            f"{label}: genau 1 Einfügeposition erwartet, gefunden: {len(matches)}"
        )
    match = matches[0]
    return text[:match.end()] + "\n" + addition + text[match.end():]


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    # 1) Stationen-Dropdown: direkt hinter dem bestehenden Stationsrekorde-Button.
    if DESKTOP_MARKER not in text:
        station_button_pattern = (
            r'<button\b'
            r'(?=[^>]*\bclass=["\'][^"\']*\btab-button\b[^"\']*["\'])'
            r'(?=[^>]*\bdata-nav-group=["\']stations["\'])'
            r'(?=[^>]*\bonclick=["\']switchTab\(["\']records["\']\)["\'])'
            r'[^>]*>\s*Stationsrekorde\s*</button>'
        )
        text = insert_after_match(
            text,
            station_button_pattern,
            DESKTOP_INSERT,
            "Stationen-Menü / Stationsrekorde",
        )

    # 2) Übersichtsseite: direkt hinter dem bestehenden Stationsrekorde-Schnellzugriff.
    if OVERVIEW_MARKER not in text:
        overview_pattern = (
            r'<button\b'
            r'(?=[^>]*\bclass=["\'][^"\']*\boverview-quicklink\b[^"\']*["\'])'
            r'(?=[^>]*\bonclick=["\']switchTab\(["\']records["\']\)["\'])'
            r'[^>]*>.*?'
            r'<span\b[^>]*class=["\'][^"\']*\boverview-link-title\b[^"\']*["\'][^>]*>'
            r'\s*Stationsrekorde\s*</span>.*?</button>'
        )
        text = insert_after_match(
            text,
            overview_pattern,
            OVERVIEW_INSERT,
            "Übersicht / Stationsrekorde-Schnellzugriff",
        )

    if DESKTOP_MARKER not in text:
        raise RuntimeError("Desktop-Navigationsmarker fehlt nach Patch.")
    if OVERVIEW_MARKER not in text:
        raise RuntimeError("Übersichtsmarker fehlt nach Patch.")
    if text.count("dekadenrekorde.html") < 2:
        raise RuntimeError("Dekadenrekorde sind nicht zweimal verlinkt.")

    changed = text != original
    if changed:
        path.write_text(text, encoding="utf-8")
        print("Dekadenrekorde wurden im Stationen-Menü und auf der Übersicht verlinkt.")
    else:
        print("Dekadenrekord-Navigation ist bereits vollständig vorhanden.")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="index.html")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"Datei nicht gefunden: {path}")

    patch(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
