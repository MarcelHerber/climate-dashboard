#!/usr/bin/env python3
"""Build an evidence-based, public data freshness manifest for GitHub Pages.

Do not infer successful observations from GitHub Actions conclusions.
All dataset dates and coverage counts come from the committed archive metadata.
"""
from __future__ import annotations
import json
from datetime import date, datetime, timezone
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parent.parent


def read_json(rel):
    path = ROOT / rel
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def valid_date(value):
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 7:
            return date.fromisoformat(value + "-01")
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def result(id, label, group, date_value, updated, coverage, note="", cadence="daily",
           allowed_delay=5, incomplete=False):
    today = datetime.now(timezone.utc).date()
    latest = valid_date(date_value)
    if not latest:
        status, lag = "unknown", None
    elif latest > today:
        status, lag = "unknown", None
        note = (note + " · Zukunftsdatum im Archiv").strip(" ·")
    elif cadence == "monthly":
        lag = (today.year - latest.year)*12 + today.month - latest.month
        status = "delayed" if lag > allowed_delay else "current"
    else:
        lag = (today - latest).days
        status = "delayed" if lag > allowed_delay else "current"
    if incomplete and status == "current":
        status = "incomplete"
    return {
        "id": id, "label": label, "group": group,
        "latest": date_value if latest else None,
        "updated": updated if isinstance(updated, str) else None,
        "coverage": str(coverage), "note": note,
        "cadence": cadence, "lag": lag, "status": status,
    }


def build():
    items = []
    dwd = read_json("update_status.json")
    if dwd:
        stamp = dwd.get("updated_at")
        monthly = dwd.get("monthly") or {}
        items.append(result("dwd_monthly", "DWD Gebietsmittel", "Deutschland",
            monthly.get("latest_complete_month"), stamp,
            f'{monthly.get("area_count", "–")} Regionen · {monthly.get("records", "–")} Monatswerte',
            "Temperatur, Niederschlag und Sonnenschein; Angaben zu vollständigen Monaten",
            cadence="monthly", allowed_delay=2))
        daily = dwd.get("daily") or {}
        items.append(result("dwd_daily", "DWD Tageshöchstwerte", "Deutschland",
            daily.get("latest_date"), stamp,
            f'{daily.get("records", "–")} Tageswerte · {daily.get("latest_station_count", "–")} meldende Stationen am letzten Tag',
            "Stationsmaximum, kein flächiges Deutschlandmittel", allowed_delay=4))
        for key, label, coverage in [
            ("station_records", "Stationsrekorde", "KL- und RR-Stationsnetz"),
            ("station_precip", "Stationsniederschlag", "RR-Stationsnetz"),
            ("station_climate_days", "Stations-Kenntage", "KL-Stationsnetz"),
            ("station_heatwaves", "Stations-Hitzewellen", "KL-Stationsnetz"),
        ]:
            x = dwd.get(key) or {}
            items.append(result(key, label, "Stationen", x.get("data_through"), stamp,
                f'{x.get("station_count", "–")} Stationen' if x.get("station_count") else coverage,
                "Aktuelles Datenende; historische Bestände separat", allowed_delay=4))
    else:
        items.append(result("dwd_monthly", "DWD Gebietsmittel", "Deutschland", None, None,
            "Archivmetadaten fehlen", "update_status.json nicht verfügbar"))

    snow = read_json("station_snow_height_current_index.json")
    if snow:
        observed = snow.get("stations_with_current_season_values")
        possible = snow.get("profile_station_count")
        items.append(result("snow", "Stationsschneehöhe", "Stationen",
            snow.get("data_through"), snow.get("generated_at"),
            f'{observed}/{possible} Stationen mit Saisonwerten',
            "Fehlende Stationsmeldungen werden nicht als 0 cm gewertet", allowed_delay=5,
            incomplete=bool(possible and observed is not None and observed < possible)))

    era = read_json("era5_europe/index.json")
    if era:
        periods = era.get("available_periods", [])
        items.append(result("era5_monthly", "ERA5 Atmosphäre Europa", "Europa",
            era.get("data_through") or era.get("latest_month_key"), era.get("generated_at"),
            f'{len(periods)} Monatsperioden im aktuellen Index; historische Jahre separat ausgewiesen',
            "Verfügbare Perioden im Index bedeuten nicht automatisch vollständige historische Karten",
            cadence="monthly", allowed_delay=2,
            incomplete=not bool(era.get("ready"))))

    estrat = read_json("era5_stratosphere/index.json")
    if estrat:
        complete = estrat.get("reference_years_completed", 0)
        items.append(result("era5_strat", "ERA5 Stratosphäre", "Atmosphäre",
            estrat.get("data_through"), estrat.get("generated_at"),
            f'Referenz 1991–2020: {complete}/30 Jahre vollständig',
            "Historische Referenz unvollständig" if complete < 30 else "Historische Referenz vollständig",
            allowed_delay=14, incomplete=complete < 30))

    ice = read_json("sea_ice/index.json")
    if ice:
        for key, label in (("north", "Meereis Arktis"), ("south", "Meereis Antarktis")):
            hemi = ice.get(key) or {}
            count = len(hemi.get("years") or {})
            ready = ice.get("ready") and len(hemi.get("normal") or []) == 366
            items.append(result("ice_"+key, label, "Ozean",
                hemi.get("latest_date"), ice.get("created_utc"),
                f'{count} Jahrgänge · 366 Klimatologie-Kalendertage',
                "NSIDC Sea Ice Index v4 · Referenz 1991–2020",
                allowed_delay=6, incomplete=not ready))

    status_counts = {key: sum(x["status"] == key for x in items)
                     for key in ("current", "incomplete", "delayed", "unknown")}
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meaning": "Dataset metadata only; not a guarantee of error-free observations or complete backfills",
        "counts": status_counts,
        "datasets": items,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="_site/data/status/status.json")
    args = parser.parse_args()
    payload = build()
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Datenstatus: {len(payload['datasets'])} Produkte, {payload['counts']}, nach {out}")


if __name__ == "__main__":
    main()
