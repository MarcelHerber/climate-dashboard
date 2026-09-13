#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "index.html",
    ROOT / "scripts" / "patch_hyras_click_timeseries_frontend.py",
]

OLD_NOTE = "Die roten Markierungen 1–3 zeigen die räumlich getrennten Maxima der aktuell dargestellten Karte."
NEW_NOTE = "Die drei räumlich getrennten Maxima der aktuell dargestellten Karte stehen direkt unter der Karte."


def patch_text(text: str, label: str) -> str:
    original = text

    # Die Top-3 nur noch ermitteln, nicht mehr in das Karten-Canvas zeichnen.
    pattern = re.compile(
        r"function hyrasDrawMapMaxima\(canvas,raster,state,metric\)\{.*?\n\}",
        flags=re.S,
    )
    replacement = (
        "function hyrasMapMaxima(raster,state){\n"
        "  return hyrasFindSeparatedMaxima(raster,state,3);\n"
        "}"
    )
    text, count = pattern.subn(replacement, text, count=1)
    if count == 0 and "function hyrasMapMaxima(raster,state)" not in text:
        raise RuntimeError(f"{label}: HYRAS-Maxima-Funktion nicht gefunden")

    old_call = "const maxima=hyrasDrawMapMaxima(canvas,raster,state,metric),strip="
    new_call = "const maxima=hyrasMapMaxima(raster,state),strip="
    if old_call in text:
        text = text.replace(old_call, new_call, 1)
    elif new_call not in text:
        raise RuntimeError(f"{label}: HYRAS-Maxima-Aufruf nicht gefunden")

    if OLD_NOTE in text:
        text = text.replace(OLD_NOTE, NEW_NOTE, 1)
    elif NEW_NOTE not in text:
        raise RuntimeError(f"{label}: HYRAS-Maxima-Hinweis nicht gefunden")

    if "hyrasDrawMapMaxima(" in text:
        raise RuntimeError(f"{label}: alte Canvas-Maxima-Funktion ist noch vorhanden")

    return text if text != original else original


def main() -> int:
    changed = []
    for path in TARGETS:
        if not path.exists():
            raise RuntimeError(f"Datei fehlt: {path}")
        text = path.read_text(encoding="utf-8")
        patched = patch_text(text, path.name)
        if patched != text:
            path.write_text(patched, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(ROOT).as_posix())

    if changed:
        print("HYRAS Top-3 unter die Karte verschoben:")
        for item in changed:
            print(f"  {item}")
    else:
        print("HYRAS Top-3-Darstellung ist bereits aktuell.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
