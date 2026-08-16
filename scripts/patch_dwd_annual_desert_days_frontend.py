#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

PAGE = Path("jahresextremwerte.html")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: genau 1 Treffer erwartet, gefunden {count}"
        )
    return text.replace(old, new, 1)


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    original = text

    if '<div class="summary-value">11</div>' not in text:
        text = replace_once(
            text,
            '<div class="summary-value">10</div>',
            '<div class="summary-value">11</div>',
            "Parameter-Karte",
        )

    if 'colspan="4">Maximale Kenntage an einer Station</th>' not in text:
        text = replace_once(
            text,
            '<th class="group-days" colspan="3">Maximale Kenntage an einer Station</th>',
            '<th class="group-days" colspan="4">Maximale Kenntage an einer Station</th>',
            "Kenntage-Colspan",
        )

    if '<th class="group-days">≥35 °C</th>' not in text:
        old = (
            '            <th class="group-days">&gt;30 °C</th>\n'
            '            <th class="group-days">Tmin &gt;20 °C</th>'
        )
        new = (
            '            <th class="group-days">&gt;30 °C</th>\n'
            '            <th class="group-days">≥35 °C</th>\n'
            '            <th class="group-days">Tmin &gt;20 °C</th>'
        )
        text = replace_once(text, old, new, "Wüstentage-Header")

    if '"desert_days_max",' not in text:
        old = (
            '    "hot_days_max",\n'
            '    "tropical_nights_max",'
        )
        new = (
            '    "hot_days_max",\n'
            '    "desert_days_max",\n'
            '    "tropical_nights_max",'
        )
        text = replace_once(text, old, new, "METRIC_ORDER")

    if 'metric === "desert_days_max"' not in text:
        old = (
            '      metric === "hot_days_max" ||\n'
            '      metric === "tropical_nights_max"'
        )
        new = (
            '      metric === "hot_days_max" ||\n'
            '      metric === "desert_days_max" ||\n'
            '      metric === "tropical_nights_max"'
        )
        text = replace_once(text, old, new, "valueText-Kenntage")

    text = text.replace("min-width:1760px;", "min-width:1910px;", 1)
    text = text.replace('colspan="11"', 'colspan="12"')

    if "TXK ≥35,0 °C" not in text:
        old = (
            'TXK &gt;25,0 °C, TXK &gt;30,0 °C '
            'und TNK &gt;20,0 °C.'
        )
        new = (
            'TXK &gt;25,0 °C, TXK &gt;30,0 °C, '
            'TXK ≥35,0 °C und TNK &gt;20,0 °C.'
        )
        text = replace_once(text, old, new, "Methodik")

    text = text.replace(
        '`${data.areas.length} Gebiete · 10 Parameter`',
        '`${data.areas.length} Gebiete · 11 Parameter`',
    )

    if text != original:
        PAGE.write_text(text, encoding="utf-8")
        print("Wüstentage ins Frontend eingebaut.")
    else:
        print("Frontend war bereits aktuell.")

    required = [
        '<div class="summary-value">11</div>',
        'colspan="4">Maximale Kenntage an einer Station</th>',
        '<th class="group-days">≥35 °C</th>',
        '"desert_days_max",',
        'metric === "desert_days_max"',
        '11 Parameter',
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError(
            "Frontend-Prüfung fehlgeschlagen: " + ", ".join(missing)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
