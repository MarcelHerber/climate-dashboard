#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

DESKTOP_MARKER = "<!-- DWD_DECADE_RECORDS_DESKTOP_NAV_V1 -->"
OVERVIEW_MARKER = "<!-- DWD_DECADE_RECORDS_OVERVIEW_LINK_V1 -->"

DESKTOP_INSERT = f'''{DESKTOP_MARKER}
<button type="button" class="tab-dropdown-item" onclick="window.location.href='dekadenrekorde.html'">Dekadenrekorde</button>'''

OVERVIEW_INSERT = f'''{OVERVIEW_MARKER}
<button type="button" class="overview-link-button" onclick="window.location.href='dekadenrekorde.html'">
  <span>Dekadenrekorde</span>
  <small>1.–3. Dekade · Deutschland &amp; Bundesländer</small>
</button>'''


def insert_after_once(text: str, pattern: str, addition: str, label: str) -> str:
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL))
    if len(matches) != 1:
        raise RuntimeError(
            f"{label}: genau 1 Einfügeposition erwartet, gefunden: {len(matches)}"
        )
    match = matches[0]
    return text[: match.end()] + "\n" + addition + text[match.end() :]


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if DESKTOP_MARKER not in text:
        text = insert_after_once(
            text,
            r'''<button\b[^>]*class=["'][^"']*\btab-dropdown-item\b[^"']*["'][^>]*\bdata-tab=["']annual-records["'][^>]*>\s*Jahresrekorde\s*</button>''',
            DESKTOP_INSERT,
            "Stationen-Menü / Jahresrekorde",
        )

    if OVERVIEW_MARKER not in text:
        text = insert_after_once(
            text,
            r'''<button\b[^>]*class=["'][^"']*\boverview-link-button\b[^"']*["'][^>]*\bdata-tab-target=["']stationen["'][^>]*>.*?</button>''',
            OVERVIEW_INSERT,
            "Übersicht / Direkteinstieg Stationsrekorde",
        )

    if DESKTOP_MARKER not in text:
        raise RuntimeError("Desktop-Navigationsmarker fehlt nach Patch.")
    if OVERVIEW_MARKER not in text:
        raise RuntimeError("Übersichtsmarker fehlt nach Patch.")
    if text.count("dekadenrekorde.html") < 2:
        raise RuntimeError("Dekadenrekord-Link wurde nicht zweimal eingebaut.")

    changed = text != original
    if changed:
        path.write_text(text, encoding="utf-8")
        print("index.html wurde um die Dekadenrekord-Navigation ergänzt.")
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
