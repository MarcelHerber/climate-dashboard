#!/usr/bin/env python3
"""Integrate the 73 map-ready ARSO Slovenia stations into the Europe updater.

One-shot repository patcher, matching the existing Estonia integration style.

Production rule:
- ARSO inventory has 74 source IDs.
- ID 346 (Turški Vrh) is deliberately NOT published.
- Exactly the other 73 IDs must receive verified coordinates and be published.
- No guessed coordinate is introduced for 346.
"""

from __future__ import annotations

import argparse
from pathlib import Path

MAIN = Path("scripts/update_europe_station_records_all_sources.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: erwartete genau 1 Fundstelle, gefunden {count}."
        )
    return text.replace(old, new, 1)


def patch_main(text: str) -> str:
    if (
        "import update_arso_slovenia_station_cache as slovenia_hist" in text
        or '"Slowenien": slovenia_hist.SOURCE' in text
    ):
        raise RuntimeError("Slowenien scheint bereits integriert zu sein.")

    if "import update_ilmateenistus_estonia_station_cache as estonia_hist" not in text:
        raise RuntimeError(
            "Der Europa-Hauptlauf enthält Estland noch nicht. "
            "Bitte den aktuellen Repo-Stand verwenden."
        )

    text = replace_once(
        text,
        "- Estonia: Estonian Environment Agency climate API (daily DTAX/DTAN)\n"
        "- remaining Europe: GHCN-Daily",
        "- Estonia: Estonian Environment Agency climate API (daily DTAX/DTAN)\n"
        "- Slovenia: ARSO Agromet official daily Tmin/Tmax month tables (73 map-ready IDs)\n"
        "- remaining Europe: GHCN-Daily",
        "Docstring Slowenien",
    )

    text = replace_once(
        text,
        "import re\nimport zipfile",
        "import re\nimport subprocess\nimport sys\nimport zipfile",
        "subprocess/sys imports",
    )

    text = replace_once(
        text,
        "import update_ilmateenistus_estonia_station_cache as estonia_hist\n"
        "import update_ilmateenistus_estonia_current as estonia_current_mod\n",
        "import update_ilmateenistus_estonia_station_cache as estonia_hist\n"
        "import update_ilmateenistus_estonia_current as estonia_current_mod\n"
        "import update_arso_slovenia_station_cache as slovenia_hist\n"
        "import update_arso_slovenia_current as slovenia_current_mod\n"
        "import update_arso_slovenia_station_metadata as slovenia_meta\n",
        "ARSO imports",
    )

    text = replace_once(
        text,
        'ACTIVE_GRACE_DAYS = 45\n'
        'NATIONAL_GHCN_CODES = {"GM", "FR", "SP", "ES", "AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN"}',
        'ACTIVE_GRACE_DAYS = 45\n'
        'SLOVENIA_IGNORED_IDS = {"346"}\n'
        'SLOVENIA_EXPECTED_MAP_READY = 73\n'
        'NATIONAL_GHCN_CODES = {"GM", "FR", "SP", "ES", "AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN", "SI"}',
        "ARSO constants / GHCN country exclusion",
    )

    marker = "\ndef chmi_payload_inventory("
    helper = r"""

def _slovenia_filter_records(records: dict[str, Any]) -> dict[str, Any]:
    return {
        str(raw_id): record
        for raw_id, record in records.items()
        if str(raw_id) not in SLOVENIA_IGNORED_IDS
    }


def _load_slovenia_map_metadata() -> dict[str, dict[str, Any]]:
    # Resolve exactly the 73 accepted ARSO coordinates.
    # NOAA/GHCN is deliberately not called here: ID 346 is now an intentional
    # exclusion rather than a matching problem to solve.
    inventory, _ = slovenia_hist.load_inventory()
    current_meta, historical_meta = slovenia_meta.load_agromet_metadata()
    gis_rows = slovenia_meta.load_gis_rows()

    result = slovenia_meta.build_metadata(
        inventory,
        current_meta,
        historical_meta,
        gis_rows,
        [],
    )
    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict):
        raise RuntimeError("ARSO-Metadatenresultat ist kein Dictionary.")

    inventory_ids = set(str(x) for x in inventory)
    expected_ids = inventory_ids - SLOVENIA_IGNORED_IDS
    actual_ids = set(str(x) for x in metadata)

    if len(inventory) != 74:
        raise RuntimeError(f"ARSO-Inventar hat {len(inventory)} statt 74 IDs.")
    if not SLOVENIA_IGNORED_IDS.issubset(inventory_ids):
        raise RuntimeError("ARSO-ID 346 fehlt unerwartet im Quellinventar.")
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise RuntimeError(
            "ARSO-Metadaten sind nicht exakt die 73 freigegebenen IDs: "
            f"missing={missing}, extra={extra}"
        )
    if len(metadata) != SLOVENIA_EXPECTED_MAP_READY:
        raise RuntimeError(
            f"ARSO: {len(metadata)} statt 73 kartierbare Stationen."
        )
    if "346" in metadata:
        raise RuntimeError("ARSO 346 darf nicht veröffentlicht werden.")

    return metadata


def slovenia_metadata_to_meta(
    metadata: dict[str, dict[str, Any]],
) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}

    for raw_id, meta in metadata.items():
        raw_id = str(raw_id)
        if raw_id in SLOVENIA_IGNORED_IDS or not isinstance(meta, dict):
            continue

        sid = f"ARSO:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat",),
            lon_keys=("lon",),
            elev_keys=("elevation_m",),
            name_keys=("name", "metadata_name"),
            country_code="SI",
            country="Slowenien",
            source=slovenia_hist.SOURCE,
            quality_rule=(
                "ARSO Slowenien: offizielle Agromet-Tageswerte Tmin/Tmax aus "
                "monatlichen TXT-Tabellen; grobe Plausibilitäts-QC, Tmin>Tmax "
                "wird verworfen. Von 74 Quell-IDs werden exakt 73 kartiert; "
                "ID 346 Turški Vrh ist wegen fehlender verifizierter Koordinate "
                "bewusst ausgeschlossen."
            ),
        )
        if station is not None:
            out[sid] = station

    if len(out) != SLOVENIA_EXPECTED_MAP_READY:
        raise RuntimeError(f"ARSO StationMeta: {len(out)} statt 73 Stationen.")
    if "ARSO:346" in out:
        raise RuntimeError("ARSO:346 wurde trotz Ausschluss erzeugt.")

    return out

"""
    if marker not in text:
        raise RuntimeError("Einfügemarke vor chmi_payload_inventory fehlt.")
    text = text.replace(marker, helper + marker, 1)

    marker = "\ndef _load_compact_national_sources("
    baseline_helper = r"""

def _load_or_build_slovenia_baseline(
    cache_dir: Path,
    current_year: int,
    force: bool,
) -> dict:
    cutoff_year = current_year - 1
    path = slovenia_hist.baseline_path(cache_dir, cutoff_year)

    if force or not slovenia_hist.valid_baseline(path, cutoff_year):
        script = Path(__file__).with_name(
            "update_arso_slovenia_station_cache.py"
        )
        cmd = [
            sys.executable,
            str(script),
            "--cutoff-year",
            str(cutoff_year),
            "--workers",
            "12",
            "--batch-size",
            "600",
            "--max-runtime-minutes",
            "300",
        ]
        if force:
            cmd.append("--force")

        log(
            "Baue/aktualisiere ARSO-Slowenien-Baseline bis "
            f"{cutoff_year} ..."
        )
        subprocess.run(cmd, check=True)

    if not slovenia_hist.valid_baseline(path, cutoff_year):
        raise RuntimeError(f"ARSO-Slowenien-Baseline unvollständig: {path}")

    payload = slovenia_hist.load_pickle_gz(path)
    if not isinstance(payload, dict) or payload.get("complete") is not True:
        raise RuntimeError(f"ARSO-Slowenien-Baseline ungültig: {path}")

    log(f"Verwende ARSO-Slowenien-Baseline: {path}")
    return payload

"""
    if marker not in text:
        raise RuntimeError("Einfügemarke vor _load_compact_national_sources fehlt.")
    text = text.replace(marker, baseline_helper + marker, 1)

    replacements = [
        (
            "    force_fmi: bool,\n"
            "    force_estonia: bool,\n"
            "    force_chmi: bool,",
            "    force_fmi: bool,\n"
            "    force_estonia: bool,\n"
            "    force_slovenia: bool,\n"
            "    force_chmi: bool,",
            "_load_compact signature",
        ),
        (
            "    estonia_base = estonia_hist.load_pickle_gzip(estonia_base_path)\n\n"
            "    chmi_hist.build_baseline(",
            "    estonia_base = estonia_hist.load_pickle_gzip(estonia_base_path)\n\n"
            "    slovenia_base = _load_or_build_slovenia_baseline(\n"
            "        cache_dir,\n"
            "        current_year,\n"
            "        force=force_slovenia,\n"
            "    )\n\n"
            "    chmi_hist.build_baseline(",
            "historische ARSO-Baseline",
        ),
        (
            "    if not isinstance(estonia_cur, dict) or estonia_cur.get(\"complete\") is not True:\n"
            "        raise RuntimeError(f\"Estland-Current unvollständig: {estonia_current_path}\")\n\n"
            "    chmi_current_path =",
            "    if not isinstance(estonia_cur, dict) or estonia_cur.get(\"complete\") is not True:\n"
            "        raise RuntimeError(f\"Estland-Current unvollständig: {estonia_current_path}\")\n\n"
            "    slovenia_current_path = slovenia_current_mod.build_current(\n"
            "        cache_dir,\n"
            "        current_year,\n"
            "        workers=12,\n"
            "    )\n"
            "    slovenia_cur = slovenia_hist.load_pickle_gz(slovenia_current_path)\n"
            "    if not isinstance(slovenia_cur, dict) or slovenia_cur.get(\"complete\") is not True:\n"
            "        raise RuntimeError(f\"ARSO-Slowenien-Current unvollständig: {slovenia_current_path}\")\n\n"
            "    chmi_current_path =",
            "ARSO Current",
        ),
        (
            "        fmi_base, fmi_cur,\n"
            "        estonia_base, estonia_cur,\n"
            "        chmi_base, chmi_cur,",
            "        fmi_base, fmi_cur,\n"
            "        estonia_base, estonia_cur,\n"
            "        slovenia_base, slovenia_cur,\n"
            "        chmi_base, chmi_cur,",
            "ARSO return tuple",
        ),
        (
            "    fmi_current_count: int,\n"
            "    estonia_current_count: int,\n"
            "    chmi_current_count: int,",
            "    fmi_current_count: int,\n"
            "    estonia_current_count: int,\n"
            "    slovenia_current_count: int,\n"
            "    chmi_current_count: int,",
            "patch_index_metadata signature",
        ),
        (
            '"Estonian Environment Agency climate API (Estland) + GHCN-Daily (übriges Europa)"',
            '"Estonian Environment Agency climate API (Estland) + "\n'
            '        "ARSO Agromet (Slowenien) + GHCN-Daily (übriges Europa)"',
            "source headline",
        ),
        (
            '        {"name": estonia_hist.SOURCE, "scope": "Estland", "url": estonia_hist.PUBLIC_URL, "stations": counts.get(estonia_hist.SOURCE, 0)},\n'
            '        {"name": core.GHCN_SOURCE,',
            '        {"name": estonia_hist.SOURCE, "scope": "Estland", "url": estonia_hist.PUBLIC_URL, "stations": counts.get(estonia_hist.SOURCE, 0)},\n'
            '        {"name": slovenia_hist.SOURCE, "scope": "Slowenien", "url": slovenia_hist.FORM_URL, "stations": counts.get(slovenia_hist.SOURCE, 0)},\n'
            '        {"name": core.GHCN_SOURCE,',
            "sources list",
        ),
        (
            '"Estland: Estonian Environment Agency climate API DTAX/DTAN; nichtnumerische Werte verworfen, Tmin>Tmax abgelehnt. "\n'
            '        "Übriges Europa:',
            '"Estland: Estonian Environment Agency climate API DTAX/DTAN; nichtnumerische Werte verworfen, Tmin>Tmax abgelehnt. "\n'
            '        "Slowenien: ARSO Agromet tägliche Tmin/Tmax-Monatstabellen; grobe Plausibilitäts-QC und Tmin>Tmax verworfen; ID 346 Turški Vrh bewusst ohne Kartenintegration. "\n'
            '        "Übriges Europa:',
            "quality rule",
        ),
        (
            '"Estonian Environment Agency Estland für das verifizierte aktive 25-Stationen-Netz ab 1991 (Roomassaare ab 2007); "\n'
            '        "GHCN-Daily',
            '"Estonian Environment Agency Estland für das verifizierte aktive 25-Stationen-Netz ab 1991 (Roomassaare ab 2007); "\n'
            '        "ARSO Slowenien mit offiziellen täglichen Tmin/Tmax-Reihen und 73 kartierbaren Quell-IDs (346 ausgeschlossen); "\n'
            '        "GHCN-Daily',
            "history scope",
        ),
        (
            '"Niederlande, Norwegen, Dänemark, Schweden, Belgien, die Schweiz, Finnland, Tschechien, Ungarn, Irland und Estland; GHCN-Daily für Rest-Europa"',
            '"Niederlande, Norwegen, Dänemark, Schweden, Belgien, die Schweiz, Finnland, Tschechien, Ungarn, Irland, Estland und Slowenien; GHCN-Daily für Rest-Europa"',
            "publication scope",
        ),
        (
            '        "Estland": {\n'
            '            "source": estonia_hist.SOURCE,\n'
            '            "historical_complete": True,\n'
            '            "current_year_station_count": estonia_current_count,\n'
            '            "history_note": "Estonian Environment Agency: DTAX/DTAN für 25 verifizierte aktive Stationen; öffentliche Baseline ab 1991, Roomassaare ab 2007.",\n'
            '        },\n'
            '        "Rest-Europa":',
            '        "Estland": {\n'
            '            "source": estonia_hist.SOURCE,\n'
            '            "historical_complete": True,\n'
            '            "current_year_station_count": estonia_current_count,\n'
            '            "history_note": "Estonian Environment Agency: DTAX/DTAN für 25 verifizierte aktive Stationen; öffentliche Baseline ab 1991, Roomassaare ab 2007.",\n'
            '        },\n'
            '        "Slowenien": {\n'
            '            "source": slovenia_hist.SOURCE,\n'
            '            "historical_complete": True,\n'
            '            "current_year_station_count": slovenia_current_count,\n'
            '            "published_station_count": SLOVENIA_EXPECTED_MAP_READY,\n'
            '            "ignored_station_ids": sorted(SLOVENIA_IGNORED_IDS),\n'
            '            "history_note": "ARSO Agromet tägliche Tmin/Tmax-Monatstabellen; 73/74 Quell-IDs mit verifizierten Koordinaten. ID 346 Turški Vrh bewusst ausgeschlossen.",\n'
            '        },\n'
            '        "Rest-Europa":',
            "coverage Slovenia",
        ),
        (
            '        "Estland": estonia_hist.SOURCE,\n'
            '    }',
            '        "Estland": estonia_hist.SOURCE,\n'
            '        "Slowenien": slovenia_hist.SOURCE,\n'
            '    }',
            "validate expected country",
        ),
        (
            "        estonia_hist.SOURCE,\n"
            "        core.GHCN_SOURCE,",
            "        estonia_hist.SOURCE,\n"
            "        slovenia_hist.SOURCE,\n"
            "        core.GHCN_SOURCE,",
            "validate source counts",
        ),
        (
            '    assert {"SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN"}.issubset(NATIONAL_GHCN_CODES)\n',
            '    assert {"SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN", "SI"}.issubset(NATIONAL_GHCN_CODES)\n'
            '    assert SLOVENIA_IGNORED_IDS == {"346"}\n'
            '    assert SLOVENIA_EXPECTED_MAP_READY == 73\n'
            '    assert "346" not in _slovenia_filter_records({"345": {}, "346": {}, "347": {}})\n'
            '    one_si = _make_station_meta(\n'
            '        sid="ARSO:192", raw_meta={"name": "Ljubljana", "lat": 46.06, "lon": 14.51, "elevation_m": 299},\n'
            '        lat_keys=("lat",), lon_keys=("lon",), elev_keys=("elevation_m",), name_keys=("name",),\n'
            '        country_code="SI", country="Slowenien", source=slovenia_hist.SOURCE, quality_rule="test"\n'
            '    )\n'
            '    assert one_si is not None and one_si.country == "Slowenien" and one_si.id == "ARSO:192"\n',
            "self-test Slovenia",
        ),
        (
            '    parser.add_argument("--force-estonia-baseline", action="store_true")\n'
            '    parser.add_argument("--self-test", action="store_true")',
            '    parser.add_argument("--force-estonia-baseline", action="store_true")\n'
            '    parser.add_argument("--force-slovenia-baseline", action="store_true")\n'
            '    parser.add_argument("--self-test", action="store_true")',
            "CLI force Slovenia",
        ),
        (
            '"CHMI Tschechien + HungaroMet Ungarn + Met Éireann Irland + Estland Climate API + GHCN-Daily Rest-Europa."',
            '"CHMI Tschechien + HungaroMet Ungarn + Met Éireann Irland + Estland Climate API + ARSO Slowenien + GHCN-Daily Rest-Europa."',
            "startup log",
        ),
        (
            'if meta.country_code not in {"AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN"}',
            'if meta.country_code not in {"AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN", "SI"}',
            "runtime GHCN SI exclusion",
        ),
        (
            "Ausschluss DE/FR/ES/AT/PL/NL/NO/DK/SE/BE/CH/FI/CZ/HU/IE/EE:",
            "Ausschluss DE/FR/ES/AT/PL/NL/NO/DK/SE/BE/CH/FI/CZ/HU/IE/EE/SI:",
            "GHCN log Slovenia",
        ),
        (
            "        estonia_base,\n"
            "        estonia_cur_payload,\n"
            "        chmi_base,",
            "        estonia_base,\n"
            "        estonia_cur_payload,\n"
            "        slovenia_base,\n"
            "        slovenia_cur_payload,\n"
            "        chmi_base,",
            "main receive ARSO tuple",
        ),
        (
            "        force_estonia=force_all or args.force_estonia_baseline,\n"
            "        force_chmi=",
            "        force_estonia=force_all or args.force_estonia_baseline,\n"
            "        force_slovenia=force_all or args.force_slovenia_baseline,\n"
            "        force_chmi=",
            "main pass force Slovenia",
        ),
        (
            '    estonia_current = compact_records_to_core_current(estonia_cur_payload.get("records", {}), prefix="ILMATEENISTUS")\n'
            '    chmi_current =',
            '    estonia_current = compact_records_to_core_current(estonia_cur_payload.get("records", {}), prefix="ILMATEENISTUS")\n'
            '    slovenia_current = compact_records_to_core_current(\n'
            '        _slovenia_filter_records(slovenia_cur_payload.get("records", {})),\n'
            '        prefix="ARSO",\n'
            '    )\n'
            '    chmi_current =',
            "ARSO current conversion",
        ),
        (
            '        ("Estland Climate API", estonia_current),\n'
            '        ("CHMI Tschechien", chmi_current),',
            '        ("Estland Climate API", estonia_current),\n'
            '        ("ARSO Slowenien", slovenia_current),\n'
            '        ("CHMI Tschechien", chmi_current),',
            "ARSO current validation",
        ),
        (
            "    fmi_stations = fmi_inventory_to_meta(fmi_inventory)\n"
            "    estonia_stations = estonia_inventory_to_meta(estonia_inventory)\n"
            "    chmi_stations =",
            "    fmi_stations = fmi_inventory_to_meta(fmi_inventory)\n"
            "    estonia_stations = estonia_inventory_to_meta(estonia_inventory)\n"
            "    slovenia_metadata = _load_slovenia_map_metadata()\n"
            "    slovenia_stations = slovenia_metadata_to_meta(slovenia_metadata)\n"
            "    log(\n"
            "        f\"ARSO Slowenien Metadaten: {len(slovenia_stations)} Stationen; \"\n"
            "        \"ID 346 Turški Vrh bewusst ausgeschlossen.\"\n"
            "    )\n"
            "    chmi_stations =",
            "ARSO metadata construction",
        ),
        (
            "or not fmi_stations or not estonia_stations or not chmi_stations or not hungary_stations",
            "or not fmi_stations or not estonia_stations or not slovenia_stations or not chmi_stations or not hungary_stations",
            "metadata completeness condition",
        ),
        (
            'f"Estland={len(estonia_stations)}, CHMI={len(chmi_stations)}, HungaroMet={len(hungary_stations)}, "',
            'f"Estland={len(estonia_stations)}, Slowenien={len(slovenia_stations)}, CHMI={len(chmi_stations)}, HungaroMet={len(hungary_stations)}, "',
            "metadata completeness log",
        ),
        (
            "    stations.update(estonia_stations)\n"
            "    stations.update(chmi_stations)",
            "    stations.update(estonia_stations)\n"
            "    stations.update(slovenia_stations)\n"
            "    stations.update(chmi_stations)",
            "merge ARSO station metadata",
        ),
        (
            '    states.update(compact_records_to_core_states(estonia_base.get("records", {}), prefix="ILMATEENISTUS"))\n'
            '    states.update(chmi_packed_to_core_states',
            '    states.update(compact_records_to_core_states(estonia_base.get("records", {}), prefix="ILMATEENISTUS"))\n'
            '    states.update(compact_records_to_core_states(\n'
            '        _slovenia_filter_records(slovenia_base.get("records", {})),\n'
            '        prefix="ARSO",\n'
            '    ))\n'
            '    states.update(chmi_packed_to_core_states',
            "merge ARSO historical states",
        ),
        (
            "    current.update(estonia_current)\n"
            "    current.update(chmi_current)",
            "    current.update(estonia_current)\n"
            "    current.update(slovenia_current)\n"
            "    current.update(chmi_current)",
            "merge ARSO current",
        ),
        (
            "        estonia_current_count=len(estonia_current),\n"
            "        chmi_current_count=",
            "        estonia_current_count=len(estonia_current),\n"
            "        slovenia_current_count=len(slovenia_current),\n"
            "        chmi_current_count=",
            "patch metadata ARSO count",
        ),
    ]

    for old, new, label in replacements:
        text = replace_once(text, old, new, label)

    validation_marker = (
        '    ghcn_rows = [row for row in rows if row.get("source") == core.GHCN_SOURCE]\n'
    )
    validation = r"""    slovenia_rows = [
        row for row in rows
        if row.get("country") == "Slowenien"
    ]
    if len(slovenia_rows) != SLOVENIA_EXPECTED_MAP_READY:
        raise RuntimeError(
            f"Slowenien enthält {len(slovenia_rows)} statt exakt 73 Stationen."
        )
    if any(str(row.get("id")) == "ARSO:346" for row in slovenia_rows):
        raise RuntimeError("ARSO:346 darf nicht in der Europa-Ausgabe erscheinen.")

"""
    if validation_marker not in text:
        raise RuntimeError("validate_payload GHCN-Marke fehlt.")
    text = text.replace(validation_marker, validation + validation_marker, 1)

    for needle in (
        'SLOVENIA_IGNORED_IDS = {"346"}',
        "SLOVENIA_EXPECTED_MAP_READY = 73",
        '"Slowenien": slovenia_hist.SOURCE',
        'prefix="ARSO"',
        'slovenia_current_count=len(slovenia_current)',
        'ARSO:346',
    ):
        if needle not in text:
            raise RuntimeError(f"Slowenien-Integrationsmarker fehlt: {needle}")

    return text


def self_test() -> None:
    assert replace_once("A\nB\n", "A", "X", "test") == "X\nB\n"

    try:
        replace_once("A A", "A", "X", "test duplicate")
    except RuntimeError:
        pass
    else:
        raise AssertionError("replace_once muss Mehrfachtreffer ablehnen.")

    source = Path(__file__).read_text(encoding="utf-8")
    assert 'SLOVENIA_IGNORED_IDS = {"346"}' in source
    assert "SLOVENIA_EXPECTED_MAP_READY = 73" in source
    assert "force-slovenia-baseline" in source
    print("Slovenia -> Europe 73-station integration patcher self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if not MAIN.exists():
        raise SystemExit(f"Fehlt: {MAIN}")

    before = MAIN.read_text(encoding="utf-8")
    after = patch_main(before)

    if args.check_only:
        print(
            "Slowenien-Patch passt auf den aktuellen Europa-Hauptlauf "
            "(73 Stationen, 346 ausgeschlossen)."
        )
        return 0

    if after == before:
        raise SystemExit("Der Europa-Hauptlauf wurde nicht verändert.")

    MAIN.write_text(after, encoding="utf-8")
    print(
        "Slowenien integriert: exakt 73 ARSO-Stationen, "
        "ID 346 Turški Vrh ausgeschlossen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
