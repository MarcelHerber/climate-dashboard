#!/usr/bin/env python3
from __future__ import annotations

import calendar
import copy
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from era5_running_season import combine_season_fields, season_spec


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _same_grid(lat, lon, other_lat, other_lon) -> bool:
    return np.allclose(lat, other_lat) and np.allclose(lon, other_lon)


def add_running_season(core, *, index_path: Path, cache_dir: Path) -> str:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if payload.get("ready") is not True:
        raise RuntimeError("Laufender ERA5-Land-Index ist nicht bereit.")
    data_through = date.fromisoformat(str(payload.get("data_through")))
    spec = season_spec(data_through)
    periods = payload.get("periods") or {}
    month_period = periods.get("running_month")
    if not isinstance(month_period, dict):
        raise RuntimeError("running_month fehlt im laufenden ERA5-Land-Index.")

    if spec.period_id in periods:
        return spec.period_id

    if not spec.completed_months:
        season = copy.deepcopy(month_period)
        season.update({
            "id": spec.period_id,
            "label": spec.label,
            "date_start": spec.start.isoformat(),
            "date_end": data_through.isoformat(),
            "completed_months": [],
            "partial_month": data_through.month,
        })
        periods[spec.period_id] = season
        payload["periods"] = periods
        _write_json(index_path, payload)
        print(f"ERA5 Running: {spec.label} entspricht im ersten Saisonmonat dem laufenden Monat.")
        return spec.period_id

    client = core.cds_client()
    year = data_through.year
    month = data_through.month
    end_day = data_through.day
    month_days = calendar.monthrange(year, month)[1]

    cur_temp_file = cache_dir / f"current_temp_{year}_{month:02d}_01_{end_day:02d}.nc"
    lat, lon, cur_temp = core.read_temperature(cur_temp_file, max_day=end_day)

    ref_temp_prefix = cache_dir / f"reference_temp_{core.REFERENCE_START}_{core.REFERENCE_END}_{month:02d}_full.nc"
    ref_temp_files = core.request_daily_temperature_period(
        client,
        list(range(core.REFERENCE_START, core.REFERENCE_END + 1)),
        month,
        list(range(1, month_days + 1)),
        ref_temp_prefix,
        f"Temperatur-Referenz {core.MONTH_NAMES[month]} {core.REFERENCE_START}–{core.REFERENCE_END}",
    )
    rlat, rlon, ref_temp = core.read_temperature(ref_temp_files, max_day=end_day)
    if not _same_grid(lat, lon, rlat, rlon):
        raise RuntimeError("Aktuelles Temperaturfeld und Referenz besitzen unterschiedliche Raster.")

    cur_precip_prefix = cache_dir / f"current_precip_{year}_{month:02d}_01_{end_day:02d}.nc"
    cur_precip_files = core.request_precip_period(
        client, [year], month, end_day, cur_precip_prefix,
        f"Niederschlag {year}-{month:02d}-01 bis {data_through}",
    )
    plat, plon, cur_precip = core.read_precip(cur_precip_files, month, end_day)

    ref_precip_prefix = cache_dir / f"reference_precip_{core.REFERENCE_START}_{core.REFERENCE_END}_{month:02d}_full.nc"
    ref_precip_files = core.request_precip_period(
        client,
        list(range(core.REFERENCE_START, core.REFERENCE_END + 1)),
        month,
        month_days,
        ref_precip_prefix,
        f"Niederschlags-Referenz {core.MONTH_NAMES[month]} {core.REFERENCE_START}–{core.REFERENCE_END}",
    )
    prlat, prlon, ref_precip = core.read_precip(
        ref_precip_files,
        month,
        end_day,
        reference_years=core.REFERENCE_END - core.REFERENCE_START + 1,
    )
    if not (_same_grid(lat, lon, plat, plon) and _same_grid(lat, lon, prlat, prlon)):
        raise RuntimeError("Temperatur- und Niederschlagsraster stimmen nicht überein.")

    by_year: dict[int, list[int]] = defaultdict(list)
    for completed_year, completed_month in spec.completed_months:
        by_year[completed_year].append(completed_month)

    current_monthly = {}
    for completed_year, months in sorted(by_year.items()):
        months = sorted(months)
        target = cache_dir / (
            f"season_completed_current_{spec.key}_{completed_year}_"
            f"{'_'.join(f'{item:02d}' for item in months)}.nc"
        )
        if not target.exists():
            core.request_monthly_tp(
                client, [completed_year], months, target,
                f"Vollständige {spec.name}-Monate {completed_year}: {months}",
            )
        mlat, mlon, fields = core.read_monthly_fields(target)
        if not _same_grid(lat, lon, mlat, mlon):
            raise RuntimeError("Tages- und Monatsraster für laufende Saison stimmen nicht überein.")
        current_monthly.update(fields)

    ref_months = sorted({completed_month for _, completed_month in spec.completed_months})
    ref_target = cache_dir / (
        f"season_completed_reference_{core.REFERENCE_START}_{core.REFERENCE_END}_{spec.key}_"
        f"{'_'.join(f'{item:02d}' for item in ref_months)}.nc"
    )
    if not ref_target.exists():
        core.request_monthly_tp(
            client,
            list(range(core.REFERENCE_START, core.REFERENCE_END + 1)),
            ref_months,
            ref_target,
            f"{spec.name}-Monatsreferenz {core.REFERENCE_START}–{core.REFERENCE_END}: {ref_months}",
        )
    rmlat, rmlon, ref_fields = core.read_monthly_fields(ref_target)
    if not _same_grid(lat, lon, rmlat, rmlon):
        raise RuntimeError("Tages- und Referenz-Monatsraster für laufende Saison stimmen nicht überein.")
    ref_monthly = {item: core.climatology_monthly(ref_fields, item) for item in ref_months}

    season_temp, season_temp_ref, season_precip, season_precip_ref = combine_season_fields(
        data_through=data_through,
        current_temp=cur_temp,
        reference_temp=ref_temp,
        current_precip=cur_precip,
        reference_precip=ref_precip,
        completed_current=current_monthly,
        completed_reference=ref_monthly,
    )
    renderer = core.load_core()
    season = core.render_period(
        renderer,
        spec.period_id,
        spec.label,
        spec.start,
        data_through,
        lat,
        lon,
        season_temp,
        season_temp_ref,
        season_precip,
        season_precip_ref,
    )
    season["completed_months"] = [f"{y:04d}-{m:02d}" for y, m in spec.completed_months]
    season["partial_month"] = month
    periods[spec.period_id] = season
    payload["periods"] = periods
    _write_json(index_path, payload)
    print(f"ERA5 Running: {spec.label} als {spec.period_id} ergänzt.")
    return spec.period_id
