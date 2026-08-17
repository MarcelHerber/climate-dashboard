#!/usr/bin/env python3
"""One-shot deterministic integration of Estonia into the Europe station updater."""
from __future__ import annotations

import argparse
from pathlib import Path


MAIN = Path("scripts/update_europe_station_records_all_sources.py")
WORKFLOW = Path(".github/workflows/update-europe-stations.yml")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: erwartete Fundstellen=1, tatsächlich={count}. "
            "Repo hat sich gegenüber dem geprüften Stand verändert."
        )
    return text.replace(old, new, 1)


def patch_main(text: str) -> str:
    if "import update_ilmateenistus_estonia_station_cache as estonia_hist" in text:
        raise RuntimeError("Estland ist im Europa-Updater bereits integriert.")

    text = replace_once(
        text,
        "- Ireland: Met Éireann Climate Data Online (daily maxtp/mintp)\n"
        "- remaining Europe: GHCN-Daily",
        "- Ireland: Met Éireann Climate Data Online (daily maxtp/mintp)\n"
        "- Estonia: Estonian Environment Agency climate API (daily DTAX/DTAN)\n"
        "- remaining Europe: GHCN-Daily",
        "Docstring",
    )

    text = replace_once(
        text,
        "import update_met_eireann_ireland_station_cache as ireland_hist\n"
        "import update_met_eireann_ireland_current as ireland_current_mod\n",
        "import update_met_eireann_ireland_station_cache as ireland_hist\n"
        "import update_met_eireann_ireland_current as ireland_current_mod\n"
        "import update_ilmateenistus_estonia_station_cache as estonia_hist\n"
        "import update_ilmateenistus_estonia_current as estonia_current_mod\n",
        "Estland-Imports",
    )

    text = replace_once(
        text,
        'NATIONAL_GHCN_CODES = {"GM", "FR", "SP", "ES", "AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI"}',
        'NATIONAL_GHCN_CODES = {"GM", "FR", "SP", "ES", "AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN"}',
        "GHCN-Ausschlussliste",
    )

    estonia_meta = """def estonia_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"ILMATEENISTUS:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="EN",
            country="Estland",
            source=estonia_hist.SOURCE,
            quality_rule=(
                "Estonian Environment Agency climate API: tägliche DTAX=Tmax und "
                "DTAN=Tmin für das verifizierte aktive 25-Stationen-Netz. "
                "Nichtnumerische Werte werden verworfen; Tmin>Tmax wird abgelehnt."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


"""
    text = replace_once(
        text,
        "\n\ndef hungary_inventory_to_meta(\n",
        "\n\n" + estonia_meta + "def hungary_inventory_to_meta(\n",
        "Estland-Metadatenadapter",
    )

    text = replace_once(
        text,
        "    force_swiss: bool,\n"
        "    force_fmi: bool,\n"
        "    force_chmi: bool,\n",
        "    force_swiss: bool,\n"
        "    force_fmi: bool,\n"
        "    force_estonia: bool,\n"
        "    force_chmi: bool,\n",
        "Loader-Signatur",
    )

    text = replace_once(
        text,
        "    fmi_base = fmi_hist.load_baseline(cache_dir, cutoff_year)\n\n"
        "    chmi_hist.build_baseline(\n",
        "    fmi_base = fmi_hist.load_baseline(cache_dir, cutoff_year)\n\n"
        "    estonia_hist.build_baseline(\n"
        "        cache_dir,\n"
        "        cutoff_year,\n"
        "        force=force_estonia,\n"
        "        max_runtime_minutes=155.0,\n"
        "    )\n"
        "    estonia_base_path = estonia_hist.baseline_path(cache_dir, cutoff_year)\n"
        "    if not estonia_hist.valid_final(estonia_base_path, cutoff_year):\n"
        "        raise RuntimeError(f\"Estland-Baseline unvollständig: {estonia_base_path}\")\n"
        "    estonia_base = estonia_hist.load_pickle_gzip(estonia_base_path)\n\n"
        "    chmi_hist.build_baseline(\n",
        "Estland-Historiencache",
    )

    text = replace_once(
        text,
        "    fmi_current_path = fmi_current_mod.build_current(cache_dir, current_year)\n"
        "    fmi_cur = fmi_hist.load_pickle_gzip(fmi_current_path)\n\n"
        "    chmi_current_path = chmi_current_mod.build_current(cache_dir, current_year, workers=12)\n",
        "    fmi_current_path = fmi_current_mod.build_current(cache_dir, current_year)\n"
        "    fmi_cur = fmi_hist.load_pickle_gzip(fmi_current_path)\n\n"
        "    estonia_current_path = estonia_current_mod.build_current(cache_dir, current_year)\n"
        "    estonia_cur = estonia_hist.load_pickle_gzip(estonia_current_path)\n"
        "    if not isinstance(estonia_cur, dict) or estonia_cur.get(\"complete\") is not True:\n"
        "        raise RuntimeError(f\"Estland-Current unvollständig: {estonia_current_path}\")\n\n"
        "    chmi_current_path = chmi_current_mod.build_current(cache_dir, current_year, workers=12)\n",
        "Estland-Currentcache",
    )

    text = replace_once(
        text,
        "        swiss_base, swiss_cur,\n"
        "        fmi_base, fmi_cur,\n"
        "        chmi_base, chmi_cur,\n",
        "        swiss_base, swiss_cur,\n"
        "        fmi_base, fmi_cur,\n"
        "        estonia_base, estonia_cur,\n"
        "        chmi_base, chmi_cur,\n",
        "Loader-Rückgabe",
    )

    text = replace_once(
        text,
        "    fmi_current_count: int,\n"
        "    chmi_current_count: int,\n",
        "    fmi_current_count: int,\n"
        "    estonia_current_count: int,\n"
        "    chmi_current_count: int,\n",
        "Index-Signatur",
    )

    text = replace_once(
        text,
        '        "HungaroMet Open Data (Ungarn) + Met Éireann Climate Data Online (Irland) + "\n'
        '        "GHCN-Daily (übriges Europa)"',
        '        "HungaroMet Open Data (Ungarn) + Met Éireann Climate Data Online (Irland) + "\n'
        '        "Estonian Environment Agency climate API (Estland) + GHCN-Daily (übriges Europa)"',
        "Quellenbeschreibung",
    )

    text = replace_once(
        text,
        '        {"name": ireland_hist.SOURCE, "scope": "Irland", "url": ireland_hist.PUBLIC_URL, "stations": counts.get(ireland_hist.SOURCE, 0)},\n'
        '        {"name": core.GHCN_SOURCE, "scope": "übriges Europa", "url": core.GHCN_BASE, "stations": counts.get(core.GHCN_SOURCE, 0)},',
        '        {"name": ireland_hist.SOURCE, "scope": "Irland", "url": ireland_hist.PUBLIC_URL, "stations": counts.get(ireland_hist.SOURCE, 0)},\n'
        '        {"name": estonia_hist.SOURCE, "scope": "Estland", "url": estonia_hist.PUBLIC_URL, "stations": counts.get(estonia_hist.SOURCE, 0)},\n'
        '        {"name": core.GHCN_SOURCE, "scope": "übriges Europa", "url": core.GHCN_BASE, "stations": counts.get(core.GHCN_SOURCE, 0)},',
        "Sources-Liste",
    )

    text = replace_once(
        text,
        '        "Irland: Met Éireann Climate Data Online maxtp/mintp; gmin/igmin werden ausgeschlossen; Republik Irland ohne Nordirland. "\n'
        '        "Übriges Europa: GHCN-Daily TMAX/TMIN nur mit leerem Q-FLAG."',
        '        "Irland: Met Éireann Climate Data Online maxtp/mintp; gmin/igmin werden ausgeschlossen; Republik Irland ohne Nordirland. "\n'
        '        "Estland: Estonian Environment Agency climate API DTAX/DTAN; nichtnumerische Werte verworfen, Tmin>Tmax abgelehnt. "\n'
        '        "Übriges Europa: GHCN-Daily TMAX/TMIN nur mit leerem Q-FLAG."',
        "Quality-Rule",
    )

    text = replace_once(
        text,
        '        "Met Éireann Irland mit offiziellen täglichen maxtp/mintp-Reihen bis zurück 1939; "\n'
        '        "GHCN-Daily für das übrige Europa. "',
        '        "Met Éireann Irland mit offiziellen täglichen maxtp/mintp-Reihen bis zurück 1939; "\n'
        '        "Estonian Environment Agency Estland für das verifizierte aktive 25-Stationen-Netz ab 1991 (Roomassaare ab 2007); "\n'
        '        "GHCN-Daily für das übrige Europa. "',
        "History-Scope",
    )

    text = replace_once(
        text,
        '        "Niederlande, Norwegen, Dänemark, Schweden, Belgien, die Schweiz, Finnland, Tschechien, Ungarn und Irland; GHCN-Daily für Rest-Europa"',
        '        "Niederlande, Norwegen, Dänemark, Schweden, Belgien, die Schweiz, Finnland, Tschechien, Ungarn, Irland und Estland; GHCN-Daily für Rest-Europa"',
        "Publication-Scope",
    )

    text = replace_once(
        text,
        '        "Irland": {\n'
        '            "source": ireland_hist.SOURCE,\n'
        '            "historical_complete": True,\n'
        '            "current_year_station_count": ireland_current_count,\n'
        '            "history_note": "Met Éireann: offizielle tägliche maxtp/mintp-Lufttemperatur; gmin/igmin ausgeschlossen; nur Republik Irland.",\n'
        '        },\n'
        '        "Rest-Europa": {"source": core.GHCN_SOURCE, "historical_complete": True},',
        '        "Irland": {\n'
        '            "source": ireland_hist.SOURCE,\n'
        '            "historical_complete": True,\n'
        '            "current_year_station_count": ireland_current_count,\n'
        '            "history_note": "Met Éireann: offizielle tägliche maxtp/mintp-Lufttemperatur; gmin/igmin ausgeschlossen; nur Republik Irland.",\n'
        '        },\n'
        '        "Estland": {\n'
        '            "source": estonia_hist.SOURCE,\n'
        '            "historical_complete": True,\n'
        '            "current_year_station_count": estonia_current_count,\n'
        '            "history_note": "Estonian Environment Agency: DTAX/DTAN für 25 verifizierte aktive Stationen; öffentliche Baseline ab 1991, Roomassaare ab 2007.",\n'
        '        },\n'
        '        "Rest-Europa": {"source": core.GHCN_SOURCE, "historical_complete": True},',
        "Coverage",
    )

    text = replace_once(
        text,
        '        "Ungarn": hungary_hist.SOURCE,\n'
        '        "Irland": ireland_hist.SOURCE,\n',
        '        "Ungarn": hungary_hist.SOURCE,\n'
        '        "Irland": ireland_hist.SOURCE,\n'
        '        "Estland": estonia_hist.SOURCE,\n',
        "Payload-Erwartung",
    )

    text = replace_once(
        text,
        "        hungary_hist.SOURCE,\n"
        "        ireland_hist.SOURCE,\n"
        "        core.GHCN_SOURCE,\n",
        "        hungary_hist.SOURCE,\n"
        "        ireland_hist.SOURCE,\n"
        "        estonia_hist.SOURCE,\n"
        "        core.GHCN_SOURCE,\n",
        "Quellenvalidierung",
    )

    text = replace_once(
        text,
        '    assert {"SW", "BE", "SZ", "FI", "EZ", "HU", "EI"}.issubset(NATIONAL_GHCN_CODES)\n',
        '    assert {"SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN"}.issubset(NATIONAL_GHCN_CODES)\n',
        "Selftest GHCN",
    )

    text = replace_once(
        text,
        '    fmi_meta_test = fmi_inventory_to_meta({"100001": {"name": "Test FI", "lat": 60.2, "lon": 24.9, "elevation_m": 50}})\n'
        '    assert fmi_meta_test["FMI:100001"].country == "Finnland"\n'
        '    chmi_meta_test = chmi_inventory_to_meta',
        '    fmi_meta_test = fmi_inventory_to_meta({"100001": {"name": "Test FI", "lat": 60.2, "lon": 24.9, "elevation_m": 50}})\n'
        '    assert fmi_meta_test["FMI:100001"].country == "Finnland"\n'
        '    estonia_meta_test = estonia_inventory_to_meta({"AJHARK01": {"name": "Tallinn-Harku", "lat": 59.398, "lon": 24.603}})\n'
        '    assert estonia_meta_test["ILMATEENISTUS:AJHARK01"].country == "Estland"\n'
        '    assert estonia_meta_test["ILMATEENISTUS:AJHARK01"].source == estonia_hist.SOURCE\n'
        '    chmi_meta_test = chmi_inventory_to_meta',
        "Selftest Estland-Meta",
    )

    text = replace_once(
        text,
        '    parser.add_argument("--force-ireland-baseline", action="store_true")\n'
        '    parser.add_argument("--self-test", action="store_true")',
        '    parser.add_argument("--force-ireland-baseline", action="store_true")\n'
        '    parser.add_argument("--force-estonia-baseline", action="store_true")\n'
        '    parser.add_argument("--self-test", action="store_true")',
        "CLI-Argument",
    )

    text = replace_once(
        text,
        '        "CHMI Tschechien + HungaroMet Ungarn + Met Éireann Irland + GHCN-Daily Rest-Europa."\n',
        '        "CHMI Tschechien + HungaroMet Ungarn + Met Éireann Irland + Estland Climate API + GHCN-Daily Rest-Europa."\n',
        "Startlog",
    )

    text = replace_once(
        text,
        '        if meta.country_code not in {"AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI"}',
        '        if meta.country_code not in {"AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN"}',
        "GHCN-Filter",
    )

    text = replace_once(
        text,
        '        f"GHCN-Metadaten Rest-Europa nach Ausschluss DE/FR/ES/AT/PL/NL/NO/DK/SE/BE/CH/FI/CZ/HU/IE: "',
        '        f"GHCN-Metadaten Rest-Europa nach Ausschluss DE/FR/ES/AT/PL/NL/NO/DK/SE/BE/CH/FI/CZ/HU/IE/EE: "',
        "GHCN-Log",
    )

    text = replace_once(
        text,
        "        fmi_base,\n"
        "        fmi_cur_payload,\n"
        "        chmi_base,\n",
        "        fmi_base,\n"
        "        fmi_cur_payload,\n"
        "        estonia_base,\n"
        "        estonia_cur_payload,\n"
        "        chmi_base,\n",
        "Tuple-Unpack",
    )

    text = replace_once(
        text,
        "        force_fmi=force_all or args.force_fmi_baseline,\n"
        "        force_chmi=force_all or args.force_chmi_baseline,\n",
        "        force_fmi=force_all or args.force_fmi_baseline,\n"
        "        force_estonia=force_all or args.force_estonia_baseline,\n"
        "        force_chmi=force_all or args.force_chmi_baseline,\n",
        "Loader-Aufruf",
    )

    text = replace_once(
        text,
        '    fmi_current = compact_records_to_core_current(fmi_cur_payload.get("records", {}), prefix="FMI")\n'
        '    chmi_current = chmi_packed_to_core_current',
        '    fmi_current = compact_records_to_core_current(fmi_cur_payload.get("records", {}), prefix="FMI")\n'
        '    estonia_current = compact_records_to_core_current(estonia_cur_payload.get("records", {}), prefix="ILMATEENISTUS")\n'
        '    chmi_current = chmi_packed_to_core_current',
        "Current-Adapter",
    )

    text = replace_once(
        text,
        '        ("FMI Finnland", fmi_current),\n'
        '        ("CHMI Tschechien", chmi_current),',
        '        ("FMI Finnland", fmi_current),\n'
        '        ("Estland Climate API", estonia_current),\n'
        '        ("CHMI Tschechien", chmi_current),',
        "Current-Validierung",
    )

    text = replace_once(
        text,
        '    fmi_inventory = dict(fmi_base.get("inventory", {}))\n'
        '    fmi_inventory.update(fmi_cur_payload.get("inventory", {}))\n'
        '    chmi_inventory = chmi_payload_inventory',
        '    fmi_inventory = dict(fmi_base.get("inventory", {}))\n'
        '    fmi_inventory.update(fmi_cur_payload.get("inventory", {}))\n'
        '    estonia_inventory = dict(estonia_base.get("inventory", {}))\n'
        '    estonia_inventory.update(estonia_cur_payload.get("inventory", {}))\n'
        '    chmi_inventory = chmi_payload_inventory',
        "Estland-Inventar",
    )

    text = replace_once(
        text,
        "    fmi_stations = fmi_inventory_to_meta(fmi_inventory)\n"
        "    chmi_stations = chmi_inventory_to_meta(chmi_inventory)\n",
        "    fmi_stations = fmi_inventory_to_meta(fmi_inventory)\n"
        "    estonia_stations = estonia_inventory_to_meta(estonia_inventory)\n"
        "    chmi_stations = chmi_inventory_to_meta(chmi_inventory)\n",
        "Estland-Stationmeta",
    )

    text = replace_once(
        text,
        "            or not fmi_stations or not chmi_stations or not hungary_stations\n"
        "            or not ireland_stations):",
        "            or not fmi_stations or not estonia_stations or not chmi_stations or not hungary_stations\n"
        "            or not ireland_stations):",
        "Metadaten-Pflicht",
    )

    text = replace_once(
        text,
        '            f"MeteoSwiss={len(swiss_stations)}, FMI={len(fmi_stations)}, "\n'
        '            f"CHMI={len(chmi_stations)}, HungaroMet={len(hungary_stations)}, "',
        '            f"MeteoSwiss={len(swiss_stations)}, FMI={len(fmi_stations)}, "\n'
        '            f"Estland={len(estonia_stations)}, CHMI={len(chmi_stations)}, HungaroMet={len(hungary_stations)}, "',
        "Metadaten-Fehlertext",
    )

    text = replace_once(
        text,
        "    stations.update(fmi_stations)\n"
        "    stations.update(chmi_stations)\n",
        "    stations.update(fmi_stations)\n"
        "    stations.update(estonia_stations)\n"
        "    stations.update(chmi_stations)\n",
        "Stations-Merge",
    )

    text = replace_once(
        text,
        '    states.update(compact_records_to_core_states(fmi_base.get("records", {}), prefix="FMI"))\n'
        '    states.update(chmi_packed_to_core_states',
        '    states.update(compact_records_to_core_states(fmi_base.get("records", {}), prefix="FMI"))\n'
        '    states.update(compact_records_to_core_states(estonia_base.get("records", {}), prefix="ILMATEENISTUS"))\n'
        '    states.update(chmi_packed_to_core_states',
        "Historien-Merge",
    )

    text = replace_once(
        text,
        "    current.update(fmi_current)\n"
        "    current.update(chmi_current)\n",
        "    current.update(fmi_current)\n"
        "    current.update(estonia_current)\n"
        "    current.update(chmi_current)\n",
        "Current-Merge",
    )

    text = replace_once(
        text,
        "        fmi_current_count=len(fmi_current),\n"
        "        chmi_current_count=len(chmi_current),\n",
        "        fmi_current_count=len(fmi_current),\n"
        "        estonia_current_count=len(estonia_current),\n"
        "        chmi_current_count=len(chmi_current),\n",
        "Index-Aufruf",
    )

    return text


def patch_workflow(text: str) -> str:
    if "force_estonia_baseline:" in text:
        raise RuntimeError("Estland ist im Europa-Workflow bereits integriert.")

    text = replace_once(
        text,
        '      force_ireland_baseline:\n'
        '        description: "Nur Met Éireann Irland neu aufbauen"\n'
        '        required: false\n'
        '        default: false\n'
        '        type: boolean\n',
        '      force_ireland_baseline:\n'
        '        description: "Nur Met Éireann Irland neu aufbauen"\n'
        '        required: false\n'
        '        default: false\n'
        '        type: boolean\n'
        '      force_estonia_baseline:\n'
        '        description: "Nur Estonian Environment Agency Estland neu aufbauen"\n'
        '        required: false\n'
        '        default: false\n'
        '        type: boolean\n',
        "Workflow-Input",
    )

    text = replace_once(
        text,
        '      - name: Cache-Bestand anzeigen\n',
        '      - name: Estland-Cache ergänzen\n'
        '        uses: actions/cache/restore@v5\n'
        '        with:\n'
        '          path: .cache/europe-stations\n'
        '          key: europe-merge-ee-${{ steps.dates.outputs.year }}-${{ github.run_id }}\n'
        '          restore-keys: |\n'
        '            ilmateenistus-estonia-current-v1-${{ steps.dates.outputs.year }}-\n'
        '            ilmateenistus-estonia-v1-${{ steps.dates.outputs.base_year }}-\n\n'
        '      - name: Cache-Bestand anzeigen\n',
        "Estland-Cache-Restore",
    )

    text = replace_once(
        text,
        '            scripts/update_met_eireann_ireland_station_cache.py \\\n'
        '            scripts/update_met_eireann_ireland_current.py\n',
        '            scripts/update_met_eireann_ireland_station_cache.py \\\n'
        '            scripts/update_met_eireann_ireland_current.py \\\n'
        '            scripts/update_ilmateenistus_estonia_station_cache.py \\\n'
        '            scripts/update_ilmateenistus_estonia_current.py\n',
        "Workflow-Dateiprüfung",
    )

    text = replace_once(
        text,
        '          python scripts/update_met_eireann_ireland_station_cache.py --self-test\n'
        '          python scripts/update_met_eireann_ireland_current.py --self-test\n'
        '          python scripts/update_europe_station_records_all_sources.py --self-test\n',
        '          python scripts/update_met_eireann_ireland_station_cache.py --self-test\n'
        '          python scripts/update_met_eireann_ireland_current.py --self-test\n'
        '          python scripts/update_ilmateenistus_estonia_station_cache.py --self-test\n'
        '          python scripts/update_ilmateenistus_estonia_current.py --self-test\n'
        '          python scripts/update_europe_station_records_all_sources.py --self-test\n',
        "Workflow-Selftests",
    )

    text = replace_once(
        text,
        "          FORCE_IRELAND_BASELINE: ${{ github.event.inputs.force_ireland_baseline || 'false' }}\n",
        "          FORCE_IRELAND_BASELINE: ${{ github.event.inputs.force_ireland_baseline || 'false' }}\n"
        "          FORCE_ESTONIA_BASELINE: ${{ github.event.inputs.force_estonia_baseline || 'false' }}\n",
        "Workflow-Env",
    )

    text = replace_once(
        text,
        '          [[ "$FORCE_IRELAND_BASELINE" == "true" ]] && EXTRA_ARGS="$EXTRA_ARGS --force-ireland-baseline"\n',
        '          [[ "$FORCE_IRELAND_BASELINE" == "true" ]] && EXTRA_ARGS="$EXTRA_ARGS --force-ireland-baseline"\n'
        '          [[ "$FORCE_ESTONIA_BASELINE" == "true" ]] && EXTRA_ARGS="$EXTRA_ARGS --force-estonia-baseline"\n',
        "Workflow-ExtraArg",
    )

    text = replace_once(
        text,
        '              "Irland":"Met Éireann Climate Data Online",\n',
        '              "Irland":"Met Éireann Climate Data Online",\n'
        '              "Estland":"Estonian Environment Agency climate API",\n',
        "Workflow-Ergebnis-Erwartung",
    )

    text = replace_once(
        text,
        '              "FMI Open Data","CHMI Open Data","HungaroMet Open Data",\n'
        '              "Met Éireann Climate Data Online","GHCN-Daily"\n',
        '              "FMI Open Data","CHMI Open Data","HungaroMet Open Data",\n'
        '              "Met Éireann Climate Data Online","Estonian Environment Agency climate API","GHCN-Daily"\n',
        "Workflow-Quellenprüfung",
    )

    text = replace_once(
        text,
        '          forbidden={"GM","FR","SP","ES","AU","PL","NL","NO","DA","SW","BE","SZ","FI","EZ","HU","EI"}',
        '          forbidden={"GM","FR","SP","ES","AU","PL","NL","NO","DA","SW","BE","SZ","FI","EZ","HU","EI","EN"}',
        "Workflow-GHCN-Ausschluss",
    )

    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        assert MAIN.as_posix() == "scripts/update_europe_station_records_all_sources.py"
        assert WORKFLOW.as_posix() == ".github/workflows/update-europe-stations.yml"
        print("Estonia Europe integration patcher self-test OK")
        return 0

    if not MAIN.exists():
        raise SystemExit(f"Fehlt: {MAIN}")
    if not WORKFLOW.exists():
        raise SystemExit(f"Fehlt: {WORKFLOW}")

    main_before = MAIN.read_text(encoding="utf-8")
    workflow_before = WORKFLOW.read_text(encoding="utf-8")

    main_after = patch_main(main_before)
    workflow_after = patch_workflow(workflow_before)

    MAIN.write_text(main_after, encoding="utf-8")
    WORKFLOW.write_text(workflow_after, encoding="utf-8")

    print("Estland-Integration angewendet:")
    print(f"  geändert: {MAIN}")
    print(f"  geändert: {WORKFLOW}")
    print("  GHCN-Ländercode EN wird ausgeschlossen.")
    print("  Nationalquelle: Estonian Environment Agency climate API.")
    print("  Stationspräfix: ILMATEENISTUS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
