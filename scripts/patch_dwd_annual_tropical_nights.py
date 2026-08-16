#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

PAGE = Path("jahresextremwerte.html")
MAIN_BUILDER = Path("scripts/build_dwd_annual_extremes.py")


def patch_frontend() -> None:
    text = PAGE.read_text(encoding="utf-8")
    original = text

    text = text.replace(
        "Tmin &gt;20 °C",
        "Tropennächte ≥20 °C",
    )

    text = text.replace(
        "TXK &gt;25,0 °C, TXK &gt;30,0 °C und TNK &gt;20,0 °C.",
        (
            "TXK &gt;25,0 °C und TXK &gt;30,0 °C. "
            "Tropennächte werden nach DWD-Definition aus Stundenwerten "
            "bestimmt: Das Minimum von 18 UTC bis 06 UTC muss ≥20,0 °C bleiben."
        ),
    )
    text = text.replace(
        (
            "TXK &gt;25,0 °C, TXK &gt;30,0 °C, "
            "TXK ≥35,0 °C und TNK &gt;20,0 °C."
        ),
        (
            "TXK &gt;25,0 °C, TXK &gt;30,0 °C und TXK ≥35,0 °C. "
            "Tropennächte werden nach DWD-Definition aus Stundenwerten "
            "bestimmt: Das Minimum von 18 UTC bis 06 UTC muss ≥20,0 °C bleiben."
        ),
    )

    if "13-Stunden-Nachtfenster" not in text:
        text = text.replace(
            "Das laufende Jahr ist\n    naturgemäß unvollständig.",
            (
                "Für Tropennächte werden nur vollständig vorhandene "
                "13-Stunden-Nachtfenster ausgewertet. Das laufende Jahr ist\n"
                "    naturgemäß unvollständig."
            ),
        )

    if text != original:
        PAGE.write_text(text, encoding="utf-8")
        print("Frontend auf DWD-Tropennacht-Definition umgestellt.")
    else:
        print("Frontend war bereits aktuell.")

    check = PAGE.read_text(encoding="utf-8")
    assert "Tropennächte ≥20 °C" in check
    assert "Minimum von 18 UTC" in check


def patch_main_builder() -> None:
    text = MAIN_BUILDER.read_text(encoding="utf-8")
    original = text

    pattern = re.compile(
        r'    "tropical_nights_max": \{\n.*?    \},\n',
        re.DOTALL,
    )
    replacement = (
        '    "tropical_nights_max": {\n'
        '        "label": "Tropennächte ≥20 °C",\n'
        '        "description": "Höchste Zahl der Tropennächte an einer Station; Nachtminimum 18 UTC bis 06 UTC >= 20,0 °C",\n'
        '        "unit": "Nächte",\n'
        '        "kind": "station_year_count",\n'
        '        "threshold": "Nachtminimum 18–06 UTC >= 20.0 °C",\n'
        '        "direction": "desc",\n'
        '        "source": "DWD hourly/air_temperature · TT_TU",\n'
        '    },\n'
    )
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("tropical_nights_max-Metadaten nicht gefunden.")

    if "def merge_official_tropical_nights(" not in text:
        marker = "\ndef reference_value(\n"
        helper = r'''
def merge_official_tropical_nights(
    records: dict[str, Any],
) -> dict[str, Any]:
    path = Path("data/dwd_annual_tropical_nights.json")
    if not path.is_file():
        raise RuntimeError(
            "Offizielle Tropennacht-Datenbasis fehlt: "
            "data/dwd_annual_tropical_nights.json"
        )

    tropical = json.loads(path.read_text(encoding="utf-8"))
    if tropical.get("areas") != AREAS:
        raise RuntimeError(
            "Tropennacht-Gebietsliste passt nicht zur Hauptdatei."
        )

    for area in AREAS:
        tropical_years = tropical["records"][area]
        for year, row in records[area].items():
            row["tropical_nights_max"] = tropical_years.get(year)

    return tropical

'''
        if marker not in text:
            raise RuntimeError("Einfügepunkt vor reference_value nicht gefunden.")
        text = text.replace(marker, "\n" + helper + marker, 1)

    if "tropical_data = merge_official_tropical_nights(records)" not in text:
        needle = "    records = acc.public_records(today.year)\n"
        if needle not in text:
            raise RuntimeError("records-Einfügepunkt nicht gefunden.")
        text = text.replace(
            needle,
            needle + "    tropical_data = merge_official_tropical_nights(records)\n",
            1,
        )

    if 'tropical_data.get("stations", {})' not in text:
        needle = (
            "    stations = merge_station_metadata(\n"
            "        kl_metadata,\n"
            "        rr_metadata,\n"
            "        records,\n"
            "    )\n"
        )
        if needle not in text:
            raise RuntimeError("stations-Einfügepunkt nicht gefunden.")
        text = text.replace(
            needle,
            (
                needle
                + '    for key, value in tropical_data.get("stations", {}).items():\n'
                + "        stations.setdefault(key, value)\n"
            ),
            1,
        )

    text = text.replace(
        '"mit TXK >25,0 °C, TXK >30,0 °C und TNK >20,0 °C gezählt; "',
        (
            '"mit TXK >25,0 °C und TXK >30,0 °C gezählt. Tropennächte "'
            '"werden separat nach DWD-Definition aus TT_TU-Stundenwerten "'
            '"für 18–06 UTC mit Minimum >=20,0 °C übernommen; "'
        ),
    )
    text = text.replace(
        (
            '"mit TXK >25,0 °C, TXK >30,0 °C, TXK >=35,0 °C '
            'und TNK >20,0 °C gezählt; "'
        ),
        (
            '"mit TXK >25,0 °C, TXK >30,0 °C und TXK >=35,0 °C gezählt. "'
            '"Tropennächte werden separat nach DWD-Definition aus "'
            '"TT_TU-Stundenwerten für 18–06 UTC mit Minimum >=20,0 °C übernommen; "'
        ),
    )

    if text != original:
        MAIN_BUILDER.write_text(text, encoding="utf-8")
        print("Haupt-Builder gegen Rückfall auf tägliches TNK abgesichert.")
    else:
        print("Haupt-Builder war bereits aktuell.")

    check = MAIN_BUILDER.read_text(encoding="utf-8")
    assert "merge_official_tropical_nights" in check
    assert "data/dwd_annual_tropical_nights.json" in check
    assert "DWD hourly/air_temperature · TT_TU" in check


def main() -> int:
    patch_frontend()
    patch_main_builder()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
