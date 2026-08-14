#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_TIMESERIES_ROUNDING_V1"


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("HYRAS-Zeitreihenwerte sind bereits auf eine Nachkommastelle formatiert.")
        return 0

    old = 'plugins:{legend:{display:true},tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${Number(context.raw).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m²`}}},scales:'
    new = 'plugins:{legend:{display:true},datalabels:{formatter:value=>Number.isFinite(Number(value))?Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):""},tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${Number(context.raw).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m²`}}},scales:'

    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"HYRAS-Rundungsfix fehlgeschlagen: erwartete Chart-Stelle Treffer={count}")

    text = text.replace(old, new, 1)
    # Add an explicit marker near the HYRAS click-series frontend marker.
    anchor = "// HYRAS_CLICK_TIMESERIES_V1"
    if anchor not in text:
        raise RuntimeError("HYRAS Klick-Zeitreihenmarker nicht gefunden")
    text = text.replace(anchor, anchor + "\n" + MARKER, 1)

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS-Zeitreihen-Datenlabels werden jetzt immer mit genau einer Nachkommastelle angezeigt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
