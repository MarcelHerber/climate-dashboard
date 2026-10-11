#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import json
import math
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from shapely.geometry import Point, shape
from shapely.ops import unary_union

ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"
STATES_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
USER_AGENT = "climate-dashboard-state-monthly-ensemble/1.0 (+GitHub Actions)"

MODEL_CONFIG = {
    "gefs": {
        "label": "GFS / GEFS",
        "api_model": "ncep_gefs_seamless",
        "meta_domain": "ncep_gefs025",
        "forecast_days": 35,
    },
    "ifs": {
        "label": "ECMWF IFS ENS",
        "api_model": "ecmwf_ifs025_ensemble",
        "meta_domain": "ecmwf_ifs025_ensemble",
        "forecast_days": 15,
    },
    "aifs": {
        "label": "ECMWF AIFS ENS",
        "api_model": "ecmwf_aifs025_ensemble",
        "meta_domain": "ecmwf_aifs025_ensemble",
        "forecast_days": 15,
    },
    "icon_eu": {
        "label": "DWD ICON-EU EPS",
        "api_model": "dwd_icon_eu_eps",
        "meta_domain": "dwd_icon_eu_eps",
        "forecast_days": 7,
    },
}

EXPECTED_STATES = [
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg",
    "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen",
    "Rheinland-Pfalz", "Saarland", "Sachsen", "Sachsen-Anhalt",
    "Schleswig-Holstein", "Thüringen",
]
REGION_ORDER = ["Deutschland", *EXPECTED_STATES]


def fetch_json(url: str, *, params: dict[str, Any] | None = None, timeout: int = 120, retries: int = 4) -> Any:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(
                url,
                params=params,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            if r.status_code in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last = exc
            if attempt + 1 >= retries:
                break
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Download fehlgeschlagen: {url}: {last}")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def qtile(values: Iterable[float], q: float) -> float | None:
    a = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not a:
        return None
    if len(a) == 1:
        return a[0]
    pos = (len(a) - 1) * q
    lo = int(math.floor(pos))
    hi = min(len(a) - 1, lo + 1)
    f = pos - lo
    return a[lo] * (1 - f) + a[hi] * f


def running(values: list[float | None]) -> list[float | None]:
    total = 0.0
    count = 0
    out: list[float | None] = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        total += float(value)
        count += 1
        out.append(total / count if count else None)
    return out


def month_dates(year: int, month: int) -> list[str]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d).isoformat() for d in range(1, last + 1)]


def load_regions(current_path: Path, climate_path: Path) -> tuple[dict[str, Any], dict[str, Any], int, int, str]:
    current = load_json(current_path)
    climate = load_json(climate_path)
    data_through = str(current["data_through"])
    year, month, _ = map(int, data_through.split("-"))
    for region in REGION_ORDER:
        if region not in current.get("regions", {}):
            raise RuntimeError(f"HYRAS aktuell: Gebiet fehlt: {region}")
        if region not in climate.get("regions", {}):
            raise RuntimeError(f"HYRAS Klima: Gebiet fehlt: {region}")
    return current, climate, year, month, data_through


def load_geometries() -> dict[str, Any]:
    data = fetch_json(STATES_URL, timeout=90)
    geoms: dict[str, Any] = {}
    for feature in data.get("features", []):
        name = str(feature.get("properties", {}).get("name", "")).strip()
        if name:
            geoms[name] = shape(feature["geometry"])
    missing = [name for name in EXPECTED_STATES if name not in geoms]
    if missing:
        raise RuntimeError("Bundesländer fehlen im GeoJSON: " + ", ".join(missing))
    geoms["Deutschland"] = unary_union([geoms[name] for name in EXPECTED_STATES])
    return geoms


def candidate_points(geom: Any, spacing: float = 0.30) -> list[tuple[float, float]]:
    minx, miny, maxx, maxy = geom.bounds
    out: list[tuple[float, float]] = []
    y = math.floor(miny / spacing) * spacing + spacing / 2
    while y <= maxy + 1e-9:
        x = math.floor(minx / spacing) * spacing + spacing / 2
        while x <= maxx + 1e-9:
            if geom.contains(Point(x, y)):
                out.append((x, y))
            x += spacing
        y += spacing
    if not out:
        p = geom.representative_point()
        out = [(float(p.x), float(p.y))]
    return out


def farthest_sample(points: list[tuple[float, float]], n: int, seed: tuple[float, float]) -> list[tuple[float, float]]:
    if len(points) <= n:
        return points
    selected: list[tuple[float, float]] = []
    first = min(points, key=lambda p: (p[0] - seed[0]) ** 2 + (p[1] - seed[1]) ** 2)
    selected.append(first)
    remaining = [p for p in points if p != first]
    while remaining and len(selected) < n:
        best = max(
            remaining,
            key=lambda p: min((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for q in selected),
        )
        selected.append(best)
        remaining.remove(best)
    return selected


def point_count_for_geometry(region: str, geom: Any) -> int:
    if region == "Deutschland":
        return 24
    area = float(geom.area)
    if area < 0.12:
        return 1
    if area < 0.45:
        return 3
    if area < 1.2:
        return 5
    return 8


def build_support_points(geoms: dict[str, Any]) -> dict[str, list[dict[str, float]]]:
    result: dict[str, list[dict[str, float]]] = {}
    for region in REGION_ORDER:
        geom = geoms[region]
        candidates = candidate_points(geom, 0.30 if region != "Deutschland" else 0.38)
        rp = geom.representative_point()
        chosen = farthest_sample(candidates, point_count_for_geometry(region, geom), (rp.x, rp.y))
        weights = [max(0.1, math.cos(math.radians(lat))) for lon, lat in chosen]
        total = sum(weights)
        result[region] = [
            {"latitude": round(lat, 4), "longitude": round(lon, 4), "weight": round(w / total, 8)}
            for (lon, lat), w in zip(chosen, weights)
        ]
    return result


@dataclass
class LocationRef:
    region: str
    weight: float
    latitude: float
    longitude: float


def flatten_support_points(points: dict[str, list[dict[str, float]]]) -> list[LocationRef]:
    out: list[LocationRef] = []
    for region in REGION_ORDER:
        for p in points[region]:
            out.append(LocationRef(region, float(p["weight"]), float(p["latitude"]), float(p["longitude"])))
    return out


def chunks(seq: list[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def member_keys(daily: dict[str, Any]) -> list[str]:
    base = "temperature_2m_mean"
    keys = [
        k for k, v in daily.items()
        if k != "time" and isinstance(v, list) and (k == base or k.startswith(base + "_member"))
    ]
    def rank(k: str) -> tuple[int, int]:
        if k == base:
            return (0, 0)
        tail = k.rsplit("member", 1)[-1]
        try:
            return (1, int(tail))
        except ValueError:
            return (2, 9999)
    return sorted(keys, key=rank)


def request_model_chunk(model_key: str, refs: list[LocationRef]) -> tuple[list[LocationRef], list[dict[str, Any]]]:
    cfg = MODEL_CONFIG[model_key]
    params = {
        "latitude": ",".join(f"{r.latitude:.4f}" for r in refs),
        "longitude": ",".join(f"{r.longitude:.4f}" for r in refs),
        "daily": "temperature_2m_mean",
        "models": cfg["api_model"],
        "forecast_days": str(cfg["forecast_days"]),
        "past_days": "3",
        "timezone": "Europe/Berlin",
        "cell_selection": "land",
    }
    try:
        # Große Multi-Location-Requests können besonders bei IFS/AIFS upstream
        # ins Read-Timeout laufen. Dann teilen wir den Batch rekursiv statt das
        # komplette Modell zu verlieren.
        data = fetch_json(ENSEMBLE_API, params=params, timeout=90, retries=2)
    except Exception as exc:
        if len(refs) <= 2:
            raise
        mid = len(refs) // 2
        print(
            f"{model_key}: Batch mit {len(refs)} Punkten fehlgeschlagen ({exc}); "
            f"teile in {mid}+{len(refs)-mid}.",
            flush=True,
        )
        left_refs, left_locations = request_model_chunk(model_key, refs[:mid])
        right_refs, right_locations = request_model_chunk(model_key, refs[mid:])
        return left_refs + right_refs, left_locations + right_locations

    locations = data if isinstance(data, list) else [data]
    if len(locations) != len(refs):
        if len(refs) > 2:
            mid = len(refs) // 2
            print(
                f"{model_key}: {len(locations)} Antworten für {len(refs)} Punkte; "
                f"teile Batch in {mid}+{len(refs)-mid}.",
                flush=True,
            )
            left_refs, left_locations = request_model_chunk(model_key, refs[:mid])
            right_refs, right_locations = request_model_chunk(model_key, refs[mid:])
            return left_refs + right_refs, left_locations + right_locations
        raise RuntimeError(f"{model_key}: {len(locations)} Antworten für {len(refs)} Punkte")
    return refs, locations


def model_run_time(model_key: str) -> str | None:
    domain = MODEL_CONFIG[model_key].get("meta_domain")
    if not domain:
        return None
    url = f"https://api.open-meteo.com/data/{domain}/static/meta.json"
    try:
        meta = fetch_json(url, timeout=30, retries=2)
        ts = finite(meta.get("last_run_initialisation_time"))
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception as exc:
        print(f"Warnung: Laufzeit {model_key} nicht verfügbar: {exc}", flush=True)
        return None


def collect_model(model_key: str, support: dict[str, list[dict[str, float]]], batch_size: int = 24) -> dict[str, Any]:
    refs = flatten_support_points(support)
    responses: list[tuple[LocationRef, dict[str, Any]]] = []

    # IFS ist bei großen Multi-Location-Abfragen deutlich empfindlicher.
    # Kleinere Start-Batches plus die rekursive Teilung oben sind stabiler.
    model_batch_size = min(batch_size, 10) if model_key == "ifs" else batch_size
    workers = 2 if model_key == "ifs" else 3
    batches = list(chunks(refs, model_batch_size))
    print(f"{model_key}: {len(refs)} Stützpunkte in {len(batches)} API-Batches", flush=True)
    with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as pool:
        futures = [pool.submit(request_model_chunk, model_key, batch) for batch in batches]
        for future in as_completed(futures):
            batch_refs, locations = future.result()
            responses.extend(zip(batch_refs, locations))

    by_region: dict[str, list[tuple[LocationRef, dict[str, Any]]]] = defaultdict(list)
    for ref, payload in responses:
        by_region[ref.region].append((ref, payload))

    regions: dict[str, Any] = {}
    global_member_count = 0
    for region in REGION_ORDER:
        items = by_region.get(region, [])
        if not items:
            raise RuntimeError(f"{model_key}: keine Antworten für {region}")
        all_times: list[str] | None = None
        keys_common: list[str] | None = None
        for _, payload in items:
            daily = payload.get("daily") or {}
            times = [str(t) for t in daily.get("time", [])]
            keys = member_keys(daily)
            if not times or not keys:
                raise RuntimeError(f"{model_key}/{region}: keine Ensemble-Tageswerte")
            if all_times is None:
                all_times = times
            elif times != all_times:
                raise RuntimeError(f"{model_key}/{region}: Zeitachsen unterscheiden sich")
            keys_common = keys if keys_common is None else [k for k in keys_common if k in keys]
        assert all_times is not None
        keys_common = keys_common or []
        if not keys_common:
            raise RuntimeError(f"{model_key}/{region}: keine gemeinsamen Member")
        global_member_count = max(global_member_count, len(keys_common))

        members: dict[str, list[float | None]] = {}
        for key in keys_common:
            series: list[float | None] = []
            for i, _ in enumerate(all_times):
                weighted = 0.0
                weight_sum = 0.0
                for ref, payload in items:
                    vals = (payload.get("daily") or {}).get(key) or []
                    value = finite(vals[i] if i < len(vals) else None)
                    if value is None:
                        continue
                    weighted += ref.weight * value
                    weight_sum += ref.weight
                series.append(weighted / weight_sum if weight_sum > 0 else None)
            members[key] = series

        regions[region] = {
            "dates": all_times,
            "member_keys": keys_common,
            "members": members,
            "support_points": len(items),
        }

    return {
        "model": model_key,
        "label": MODEL_CONFIG[model_key]["label"],
        "api_model": MODEL_CONFIG[model_key]["api_model"],
        "forecast_days": MODEL_CONFIG[model_key]["forecast_days"],
        "run": model_run_time(model_key),
        "member_count": global_member_count,
        "regions": regions,
    }


def dates_between(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def period_definitions(year: int, month: int) -> dict[str, dict[str, Any]]:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    if month in (3, 4, 5):
        season_name, season_start, season_end = "Frühling", date(year, 3, 1), date(year, 5, 31)
    elif month in (6, 7, 8):
        season_name, season_start, season_end = "Sommer", date(year, 6, 1), date(year, 8, 31)
    elif month in (9, 10, 11):
        season_name, season_start, season_end = "Herbst", date(year, 9, 1), date(year, 11, 30)
    elif month == 12:
        end_year = year + 1
        season_name = "Winter"
        season_start = date(year, 12, 1)
        season_end = date(end_year, 2, calendar.monthrange(end_year, 2)[1])
    else:
        # Das aktuelle HYRAS-Regionenpaket enthält nur das laufende Jahr.
        # Deshalb ohne Dezember-Vorjahr ausdrücklich als Winter-Teilausschnitt,
        # niemals als vollständiges DJF-Flächenmittel ausgeben.
        season_name = "Winter (ab Januar; Dezember-Vorjahr fehlt)"
        season_start = date(year, 1, 1)
        season_end = date(year, 2, calendar.monthrange(year, 2)[1])
    return {
        "month": {"label": first.strftime("%m/%Y"), "start_date": first.isoformat(), "end_date": last.isoformat(),
                  "dates": dates_between(first, last), "complete_reference_period": True},
        "season": {"label": season_name, "start_date": season_start.isoformat(),
                   "end_date": season_end.isoformat(), "dates": dates_between(season_start, season_end),
                   "complete_reference_period": month not in (1, 2)},
        "year": {"label": f"Jahr {year}", "start_date": f"{year}-01-01",
                 "end_date": f"{year}-12-31", "dates": dates_between(date(year, 1, 1), date(year, 12, 31)),
                 "complete_reference_period": True},
    }


def observed_period(current: dict[str, Any], region: str, period_dates: list[str]) -> tuple[list[str], list[float]]:
    source = dict(zip(current.get("dates", []), current.get("regions", {}).get(region, [])))
    out_dates: list[str] = []
    out_values: list[float] = []
    for day in period_dates:
        value = finite(source.get(day))
        if value is None:
            if out_dates:
                break
            if day <= str(current["data_through"]):
                raise RuntimeError(f"HYRAS {region}: fehlender Starttag {day}")
            break
        out_dates.append(day)
        out_values.append(value)
    if not out_dates:
        raise RuntimeError(f"Keine HYRAS-Beobachtungen für {region} {period_dates[0]}")
    if out_dates[-1] != min(period_dates[-1], str(current["data_through"])):
        raise RuntimeError(f"HYRAS {region}: Beobachtungslücke bis {current['data_through']}")
    return out_dates, out_values


def climate_period(climate: dict[str, Any], region: str, period_dates: list[str]) -> list[float | None]:
    reg = climate.get("regions", {}).get(region, {})
    return [finite(reg.get(day[5:])) for day in period_dates]


def merge_running_outlook(
    observed_dates: list[str],
    observed_values: list[float],
    model_region: dict[str, Any],
    period_dates: list[str],
) -> dict[str, Any]:
    obs_through = observed_dates[-1]
    obs_sum = sum(observed_values)
    obs_n = len(observed_values)
    if observed_dates != period_dates[:obs_n]:
        raise RuntimeError(f"HYRAS Beobachtungslücke im Zeitraum ab {period_dates[0]}")

    model_dates = [str(d) for d in model_region["dates"]]
    date_idx = {d: i for i, d in enumerate(model_dates)}
    member_curves: list[list[float | None]] = []
    member_names: list[str] = []

    for key in model_region["member_keys"]:
        values = model_region["members"][key]
        total = obs_sum
        count = obs_n
        curve = [None] * len(period_dates)
        for i, d in enumerate(period_dates):
            if d <= obs_through:
                continue
            idx = date_idx.get(d)
            if idx is None:
                break
            value = finite(values[idx] if idx < len(values) else None)
            if value is None:
                break
            total += value
            count += 1
            curve[i] = total / count
        member_curves.append(curve)
        member_names.append(key)

    stats = {k: [None] * len(period_dates) for k in ["min", "p05", "p20", "mean", "p80", "p95", "max"]}
    forecast_dates: list[str] = []
    for i, day in enumerate(period_dates):
        vals = [curve[i] for curve in member_curves
                if curve[i] is not None and math.isfinite(float(curve[i]))]
        if not vals:
            continue
        forecast_dates.append(day)
        stats["min"][i] = min(vals)
        stats["p05"][i] = qtile(vals, 0.05)
        stats["p20"][i] = qtile(vals, 0.20)
        stats["mean"][i] = sum(vals) / len(vals)
        stats["p80"][i] = qtile(vals, 0.80)
        stats["p95"][i] = qtile(vals, 0.95)
        stats["max"][i] = max(vals)

    control = member_curves[0] if member_curves else [None] * len(period_dates)
    return {
        "member_count": len(member_curves),
        "control_key": member_names[0] if member_names else None,
        "forecast_from": forecast_dates[0] if forecast_dates else None,
        "forecast_through": forecast_dates[-1] if forecast_dates else None,
        "support_points": model_region.get("support_points"),
        "stats": {
            k: [round(v, 3) if v is not None else None for v in arr]
            for k, arr in stats.items()
        },
        "control": [round(v, 3) if v is not None else None for v in control],
    }


def build_period_region(
    current: dict[str, Any],
    climate: dict[str, Any],
    model_data: dict[str, dict[str, Any]],
    region: str,
    period: dict[str, Any],
) -> dict[str, Any]:
    dates = period["dates"]
    obs_dates, obs_values = observed_period(current, region, dates)
    obs_run = running(obs_values)
    obs_index = {d: v for d, v in zip(obs_dates, obs_run)}
    observed_running = [round(obs_index[d], 3) if d in obs_index else None for d in dates]

    clim_daily = climate_period(climate, region, dates)
    if any(value is None for value in clim_daily):
        raise RuntimeError(f"HYRAS Klimakurve {region}: Lücken im Zeitraum {dates[0]}–{dates[-1]}")
    clim_run = [round(v, 3) if v is not None else None for v in running(clim_daily)]
    climate_final = clim_run[-1]
    reference_to_date = clim_run[len(obs_dates) - 1]

    models: dict[str, Any] = {}
    for key, mdata in model_data.items():
        models[key] = {
            "label": mdata["label"],
            "run": mdata.get("run"),
            "api_model": mdata.get("api_model"),
            **merge_running_outlook(obs_dates, obs_values, mdata["regions"][region], dates),
        }

    return {
        "observed_through": obs_dates[-1],
        "observed_running": observed_running,
        "observed_current": round(obs_run[-1], 3),
        "climatology_running": clim_run,
        "climatology_month_mean": climate_final,  # historische Frontend-Kompatibilität
        "climatology_period_mean": climate_final,
        "climatology_to_date": reference_to_date,
        "observed_anomaly_to_date": round(obs_run[-1] - reference_to_date, 3),
        "models": models,
    }


def build_payload(
    current: dict[str, Any],
    climate: dict[str, Any],
    model_data: dict[str, dict[str, Any]],
    year: int,
    month: int,
    data_through: str,
    support: dict[str, list[dict[str, float]]],
) -> dict[str, Any]:
    periods = period_definitions(year, month)
    regions: dict[str, Any] = {}
    for region in REGION_ORDER:
        by_period = {
            key: build_period_region(current, climate, model_data, region, period)
            for key, period in periods.items()
        }
        # Alte Monatsfelder bleiben für ältere Frontend-Versionen lesbar.
        regions[region] = {
            **by_period["month"],
            "support_points": support[region],
            "periods": by_period,
        }

    return {
        "schema_version": 2,
        "product": "state_monthly_ensemble_temperature",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "year": year,
        "month": month,
        "dates": periods["month"]["dates"],
        "periods": periods,
        "observation_source": "DWD HYRAS-DE-TAS",
        "observation_data_through": data_through,
        "climatology_reference": "1991-2020",
        "forecast_source": "Open-Meteo Ensemble API",
        "method": {
            "observation": "1-km HYRAS area mean for Germany and the 16 federal states",
            "forecast": "Open-Meteo ensemble daily 2 m temperature averaged across deterministic support points within each region",
            "support_point_note": "Forecast area means are a support-point approximation; observations/climatology are exact HYRAS grid-area means.",
            "anomaly": "Running-period mean minus 1991-2020 running-period daily climatology for the same date.",
        },
        "regions_order": REGION_ORDER,
        "models_order": list(model_data),
        "regions": regions,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--climate", required=True)
    ap.add_argument("--output", default="state_monthly_ensemble.json")
    ap.add_argument("--models", default=",".join(MODEL_CONFIG))
    ap.add_argument("--batch-size", type=int, default=24)
    args = ap.parse_args()

    current, climate, year, month, data_through = load_regions(Path(args.current), Path(args.climate))
    print(f"HYRAS Datenstand: {data_through}; Zielmonat {year}-{month:02d}", flush=True)

    support = build_support_points(load_geometries())
    print("Stützpunkte:", ", ".join(f"{k}={len(v)}" for k, v in support.items()), flush=True)

    requested = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in requested if m not in MODEL_CONFIG]
    if unknown:
        raise SystemExit("Unbekannte Modelle: " + ", ".join(unknown))

    model_data: dict[str, dict[str, Any]] = {}
    model_errors: dict[str, str] = {}
    for model_key in requested:
        try:
            model_data[model_key] = collect_model(model_key, support, args.batch_size)
            print(f"{model_key}: erfolgreich ({model_data[model_key]['member_count']} Member)", flush=True)
        except Exception as exc:
            model_errors[model_key] = str(exc)
            print(f"FEHLER {model_key}: {exc}", flush=True)

    if not model_data:
        raise SystemExit("Kein Ensemblemodell konnte geladen werden.")

    payload = build_payload(current, climate, model_data, year, month, data_through, support)
    payload["model_errors"] = model_errors
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Geschrieben: {output} ({output.stat().st_size/1024:.1f} KiB)", flush=True)
    print("Modelle:", ", ".join(payload["models_order"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
