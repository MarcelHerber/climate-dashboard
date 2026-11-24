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
from threading import Lock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from shapely.geometry import Point, shape
from shapely.ops import unary_union

ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"
STATES_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
USER_AGENT = "climate-dashboard-state-monthly-ensemble/1.0 (+GitHub Actions)"

# All ensemble queries share the provider's weighted request budget.
_SUNSHINE_API_LOCK = Lock()
_SUNSHINE_NEXT_REQUEST = 0.0
_SUNSHINE_REQUEST_GAP_SECONDS = 20.0
_ENSEMBLE_STOP_REASON: str | None = None
_HOURLY_PAUSE_USED = False


class EnsembleQuotaExhausted(RuntimeError):
    """No further requests should be made in this execution."""


def rate_limit_delay(reason: str, now: datetime) -> float | None:
    reason = reason.lower()
    if "daily" in reason or "day limit" in reason or "per day" in reason:
        return None
    if "hourly" in reason or "hour limit" in reason or "per hour" in reason:
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return max(65.0, (next_hour - now).total_seconds() + 5)
    return 65.0


def month_forecast_days(today: date, year: int, month: int) -> int:
    return max(1, (date(year, month, calendar.monthrange(year, month)[1]) - today).days + 1)


def next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def outlook_months(today: date) -> tuple[tuple[int, int], tuple[int, int]]:
    return (today.year, today.month), next_month(today.year, today.month)


def month_observations(doc, year, month):
    """Select a validated monthly observation file, without inventing days."""
    if doc["month"] == f"{year:04d}-{month:02d}":
        return doc["dates"], {r: doc["regions"][r]["daily"] for r in REGION_ORDER}
    return [], {r: [] for r in REGION_ORDER}


def empty_hydro_observations(today, unit, **metadata):
    return {"schema_version": 1, "forecast": False, "unit": unit,
            "month": today.strftime("%Y-%m"), "dates": [], "data_through": None,
            "regions": {r: {"daily": []} for r in REGION_ORDER}, **metadata}


def reserve_sunshine_request() -> None:
    global _SUNSHINE_NEXT_REQUEST
    with _SUNSHINE_API_LOCK:
        remaining = _SUNSHINE_NEXT_REQUEST - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        _SUNSHINE_NEXT_REQUEST = time.monotonic() + _SUNSHINE_REQUEST_GAP_SECONDS


def cooldown_sunshine_requests(seconds: float = 65.0) -> None:
    global _SUNSHINE_NEXT_REQUEST
    with _SUNSHINE_API_LOCK:
        _SUNSHINE_NEXT_REQUEST = max(_SUNSHINE_NEXT_REQUEST, time.monotonic() + seconds)

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


def validate_available_models(models: Iterable[str]) -> None:
    keys = set(models)
    if not keys or not keys <= set(MODEL_CONFIG):
        raise ValueError(f"Keine gültigen Ensemblemodelle: {sorted(keys)}")


def unhealthy_models(models: dict[str, Any], now: datetime) -> dict[str, str]:
    failures = {}
    for key in MODEL_CONFIG:
        if key not in models:
            failures[key] = "fehlt"
            continue
        try:
            run = datetime.fromisoformat(models[key]["run"].replace("Z", "+00:00"))
            age = (now - run).total_seconds() / 3600
            if not -1 <= age <= 36:
                failures[key] = f"Laufalter {age:.1f} h"
        except (KeyError, TypeError, ValueError, AttributeError):
            failures[key] = "Laufzeit fehlt oder ungültig"
    return failures


def select_temperature_models(fresh: dict, cached: dict, observed_through: str, now: datetime) -> tuple[dict, list[str]]:
    """Retain raw daily member data only while it can be re-anchored without a gap."""
    next_day = (date.fromisoformat(observed_through) + timedelta(days=1)).isoformat()
    selected, retained = {}, []
    for key in MODEL_CONFIG:
        candidates = []
        for is_fresh, source in ((True, fresh), (False, cached), (False, cached.get("__preview", {}))):
            model = source.get(key)
            if not isinstance(model, dict) or model.get("daily_variable") != "temperature_2m_mean":
                continue
            try:
                run = datetime.fromisoformat(model["run"].replace("Z", "+00:00"))
                age = (now - run).total_seconds() / 3600
                if not -1 <= age <= 48:
                    continue
            except (KeyError, TypeError, ValueError, AttributeError):
                if not is_fresh or model.get("run") is not None:
                    continue
                run = datetime.min.replace(tzinfo=timezone.utc)
            try:
                for region in REGION_ORDER:
                    r = model["regions"][region]
                    i = r["dates"].index(next_day)
                    if not r["member_keys"] or not all(finite(r["members"][m][i]) is not None for m in r["member_keys"]):
                        raise ValueError("Forecast gap")
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            # Fresh complete members with unverified metadata must not lose
            # to an older cache merely because its initialization is known.
            # With two verified timestamps, always prefer the newer run.
            ranking_run = now if is_fresh and run == datetime.min.replace(tzinfo=timezone.utc) else run
            candidates.append((ranking_run, is_fresh, model))
        if candidates:
            _, is_fresh, model = max(candidates, key=lambda c: (c[0], c[1]))
            selected[key] = {**model, "retained": not is_fresh}
            if not is_fresh:
                retained.append(key)
    return selected, retained


def fetch_json(url: str, *, params: dict[str, Any] | None = None, timeout: int = 120, retries: int = 4) -> Any:
    global _ENSEMBLE_STOP_REASON, _HOURLY_PAUSE_USED
    last: Exception | None = None
    ensemble_request = url == ENSEMBLE_API
    for attempt in range(retries):
        try:
            if ensemble_request:
                if _ENSEMBLE_STOP_REASON:
                    raise EnsembleQuotaExhausted(_ENSEMBLE_STOP_REASON)
                reserve_sunshine_request()
            r = requests.get(
                url,
                params=params,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            if r.status_code in {429, 500, 502, 503, 504}:
                if r.status_code == 429 and ensemble_request:
                    reason = f"HTTP 429: {r.text[:200]}"
                    delay = rate_limit_delay(reason, datetime.now(timezone.utc))
                    hourly = any(word in reason.lower() for word in ("hourly", "hour limit", "per hour"))
                    if delay is None or (hourly and _HOURLY_PAUSE_USED):
                        _ENSEMBLE_STOP_REASON = reason
                        raise EnsembleQuotaExhausted(reason)
                    if hourly:
                        _HOURLY_PAUSE_USED = True
                    try:
                        delay = max(delay, float(r.headers.get("Retry-After", 0)))
                    except (ValueError, TypeError):
                        pass
                    print(f"Ensemble-API: {reason}; Pause {delay:.0f}s", flush=True)
                    cooldown_sunshine_requests(delay)
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            return r.json()
        except EnsembleQuotaExhausted:
            raise
        except Exception as exc:
            last = exc
            if attempt + 1 >= retries:
                break
            if ensemble_request and "HTTP 429" in str(exc):
                # Next attempt is paced by the shared cooldown, not a short retry.
                continue
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
    """Running arithmetic mean; missing samples are not converted to zero."""
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


def running_sum(values: list[float | None]) -> list[float | None]:
    """Cumulative daily precipitation (mm) or sunshine (h), preserving gaps.

    The caller must verify complete observed days before using the final value
    as a forecast starting point. Missing data is not a dry/overcast day.
    """
    total = 0.0
    out: list[float | None] = []
    for value in values:
        daily = finite(value)
        if daily is None:
            out.append(None)
            continue
        if daily < 0:
            raise ValueError("A daily precipitation/sunshine total cannot be negative")
        total += daily
        out.append(round(total, 6))
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


def member_keys(daily: dict[str, Any], variable: str = "temperature_2m_mean") -> list[str]:
    base = variable
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


def hourly_sunshine_to_daily(location: dict[str, Any]) -> dict[str, Any]:
    """Convert hourly sunshine seconds to complete DWD-like UTC synoptic days.

    Open-Meteo timestamps label the *end* of the previous-hour sum.
    DWD DUETT synoptic intervals end at HH:50, so a given DUETT day
    (00:50..23:50) aligns most closely with Open-Meteo hours ending
    01:00..next-day 00:00 (10 minute shift). Incomplete days are omitted.
    """
    hourly = location.get("hourly") or {}
    times = [str(t) for t in hourly.get("time", [])]
    if not times or len(times) != len(set(times)):
        raise ValueError("Missing/duplicate Open-Meteo hourly sunshine timestamps")
    units = (location.get("hourly_units") or {}).get("sunshine_duration")
    if units not in ("s", "seconds", "second"):
        raise ValueError(f"Unexpected sunshine-duration unit: {units!r} (expected seconds)")
    days: dict[str, list[int]] = defaultdict(list)
    for idx, timestamp in enumerate(times):
        if len(timestamp) != 16 or timestamp[10] != "T":
            raise ValueError(f"Open-Meteo sunshine hour has unexpected UTC timestamp {timestamp}")
        end_time = datetime.fromisoformat(timestamp)
        if end_time.minute != 0 or end_time.second != 0:
            raise ValueError(f"Unexpected Open-Meteo non-hourly timestamp {timestamp}")
        # A 00:00-end timestamp belongs to the preceding synoptic day.
        synoptic_day = (end_time - timedelta(minutes=1)).date().isoformat()
        days[synoptic_day].append(idx)
    complete = [
        day for day, idx in sorted(days.items())
        if len(idx) == 24
        and {times[i][11:] for i in idx} == {f"{hour:02d}:00" for hour in range(24)}
    ]
    fields: dict[str, list[float | None]] = {}
    for key in member_keys(hourly, "sunshine_duration"):
        values = hourly.get(key) or []
        daily_values = []
        for day in complete:
            indices = days[day]
            samples = [finite(values[i]) if i < len(values) else None for i in indices]
            if any(v is None or v < 0 or v > 3600.01 for v in samples):
                daily_values.append(None)
            else:
                daily_values.append(round(sum(samples) / 3600, 6))
        fields[key] = daily_values
    return {**location, "daily": {"time": complete, **fields}}


def hourly_precipitation_to_hyras_day(location: dict[str, Any]) -> dict[str, Any]:
    """Aggregate hourly preceding-hour precipitation to HYRAS 06–06 UTC days.

    HYRAS-DE-PR labels a day by its starting calendar date and integrates
    station precipitation from 06 UTC to 06 UTC of the following day.
    Open-Meteo hourly precipitation timestamps are end-times; HYRAS day D
    therefore uses model hours ending D 07:00 through D+1 06:00.
    """
    hourly = location.get("hourly") or {}
    times = [str(t) for t in hourly.get("time", [])]
    if not times or len(times) != len(set(times)):
        raise ValueError("Missing/duplicate hourly precipitation timestamps")
    units = (location.get("hourly_units") or {}).get("precipitation")
    if units not in ("mm", "millimeter", "millimetres", "millimeters"):
        raise ValueError(f"Unexpected hourly precipitation unit {units!r}")
    days: dict[str, list[int]] = defaultdict(list)
    for idx, stamp in enumerate(times):
        if len(stamp) != 16 or stamp[10] != "T":
            raise ValueError(f"Invalid hourly precipitation timestamp: {stamp}")
        end_time = datetime.fromisoformat(stamp)
        if end_time.minute != 0 or end_time.second != 0:
            raise ValueError(f"Not an hourly precipitation timestamp: {stamp}")
        hyras_day = (end_time - timedelta(hours=7)).date().isoformat()
        days[hyras_day].append(idx)
    complete = [
        day for day, indices in sorted(days.items())
        if len(indices) == 24
        and {times[i][11:] for i in indices} == {f"{hour:02d}:00" for hour in range(24)}
    ]
    fields: dict[str, list[float | None]] = {}
    for key in member_keys(hourly, "precipitation"):
        samples = hourly.get(key) or []
        daily_values = []
        for day in complete:
            vals = [finite(samples[i]) if i < len(samples) else None for i in days[day]]
            if any(v is None or v < 0 or v > 1000 for v in vals):
                daily_values.append(None)
            else:
                daily_values.append(round(sum(vals), 6))
        fields[key] = daily_values
    return {**location, "daily": {"time": complete, **fields}}


def request_model_chunk(model_key: str, refs: list[LocationRef], variable: str = "temperature_2m_mean", *, time_resolution: str = "daily", forecast_days: int | None = None) -> tuple[list[LocationRef], list[dict[str, Any]]]:
    cfg = MODEL_CONFIG[model_key]
    params = {
        "latitude": ",".join(f"{r.latitude:.4f}" for r in refs),
        "longitude": ",".join(f"{r.longitude:.4f}" for r in refs),
        time_resolution: variable,
        "models": cfg["api_model"],
        "forecast_days": str(min(cfg["forecast_days"], forecast_days) if forecast_days is not None else cfg["forecast_days"]),
        "past_days": "3",
        "timezone": "GMT" if time_resolution == "hourly" else "Europe/Berlin",
        "cell_selection": "land",
    }
    try:
        # Große Multi-Location-Requests können besonders bei IFS/AIFS upstream
        # ins Read-Timeout laufen. Dann teilen wir den Batch rekursiv statt das
        # komplette Modell zu verlieren.
        data = fetch_json(
            ENSEMBLE_API, params=params, timeout=90,
            retries=4 if time_resolution == "hourly" else 3,
        )
    except Exception as exc:
        if "HTTP 429" in str(exc):
            # Smaller requests cost *more* API calls and worsen a minute cap.
            raise
        if len(refs) <= 2:
            raise
        mid = len(refs) // 2
        print(
            f"{model_key}: Batch mit {len(refs)} Punkten fehlgeschlagen ({exc}); "
            f"teile in {mid}+{len(refs)-mid}.",
            flush=True,
        )
        left_refs, left_locations = request_model_chunk(model_key, refs[:mid], variable, time_resolution=time_resolution, forecast_days=forecast_days)
        right_refs, right_locations = request_model_chunk(model_key, refs[mid:], variable, time_resolution=time_resolution, forecast_days=forecast_days)
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
            left_refs, left_locations = request_model_chunk(model_key, refs[:mid], variable, time_resolution=time_resolution, forecast_days=forecast_days)
            right_refs, right_locations = request_model_chunk(model_key, refs[mid:], variable, time_resolution=time_resolution, forecast_days=forecast_days)
            return left_refs + right_refs, left_locations + right_locations
        raise RuntimeError(f"{model_key}: {len(locations)} Antworten für {len(refs)} Punkte")
    if time_resolution == "hourly" and variable == "sunshine_duration":
        locations = [hourly_sunshine_to_daily(loc) for loc in locations]
    elif time_resolution == "hourly" and variable == "precipitation":
        locations = [hourly_precipitation_to_hyras_day(loc) for loc in locations]
    return refs, locations


def model_run_time(model_key: str, now: datetime | None = None) -> str | None:
    """Plausibility-check *metadata*, never infer a run time from forecast dates.

    Open-Meteo can serve forecasts independently of /static/meta.json. An old
    metadata timestamp is not proof that today's freshly retrieved ensemble
    members belong to that old run. Keep their actual origin unverified.
    """
    domain = MODEL_CONFIG[model_key].get("meta_domain")
    if not domain:
        return None
    url = f"https://api.open-meteo.com/data/{domain}/static/meta.json"
    try:
        meta = fetch_json(url, timeout=30, retries=2)
        ts = finite(meta.get("last_run_initialisation_time"))
        if ts is None:
            return None
        run = datetime.fromtimestamp(ts, tz=timezone.utc)
        age = (now or datetime.now(timezone.utc)) - run
        if not -timedelta(hours=1) <= age <= timedelta(hours=48):
            print(
                f"Warnung: {model_key} Metadaten-Laufzeit {run.isoformat()} "
                f"ist unplausibel ({age.total_seconds()/3600:.1f} h); "
                "Ensemblewerte werden separat geprüft, Laufzeit bleibt unbekannt.",
                flush=True,
            )
            return None
        return run.isoformat().replace("+00:00", "Z")
    except Exception as exc:
        print(f"Warnung: Laufzeit {model_key} nicht verfügbar: {exc}", flush=True)
        return None


def collect_model(model_key: str, support: dict[str, list[dict[str, float]]], batch_size: int = 24, *, variable: str = "temperature_2m_mean", time_resolution: str = "daily", forecast_days: int | None = None) -> dict[str, Any]:
    refs = flatten_support_points(support)
    responses: list[tuple[LocationRef, dict[str, Any]]] = []

    # IFS ist bei großen Multi-Location-Abfragen deutlich empfindlicher.
    # Kleinere Start-Batches plus die rekursive Teilung oben sind stabiler.
    model_batch_size = min(batch_size, 10 if model_key == "ifs" else 12) if variable == "temperature_2m_mean" else min(batch_size, 10) if model_key == "ifs" else batch_size
    workers = 1 if variable in {"temperature_2m_mean", "precipitation"} else 2 if model_key == "ifs" else 3
    batches = list(chunks(refs, model_batch_size))
    print(f"{model_key}: {len(refs)} Stützpunkte in {len(batches)} API-Batches", flush=True)
    if workers == 1:
        # Do not queue more expensive requests after a persistent rate limit.
        for batch in batches:
            batch_refs, locations = request_model_chunk(model_key, batch, variable, time_resolution=time_resolution, forecast_days=forecast_days)
            responses.extend(zip(batch_refs, locations))
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as pool:
            futures = [pool.submit(request_model_chunk, model_key, batch, variable, time_resolution=time_resolution, forecast_days=forecast_days) for batch in batches]
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
            keys = member_keys(daily, variable)
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
        "daily_variable": variable,
        "time_resolution": time_resolution,
        "forecast_days": min(MODEL_CONFIG[model_key]["forecast_days"], forecast_days) if forecast_days is not None else MODEL_CONFIG[model_key]["forecast_days"],
        "run": model_run_time(model_key),
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
    if str(current["data_through"]) < period_dates[0]:
        return [], []
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
    *,
    aggregation: str = "mean",
) -> dict[str, Any]:
    """Join observed days to ensemble members without double counting.

    Temperature keeps the running mean. Precipitation and sunshine use
    aggregation='sum' with independently accumulated daily amounts.
    """
    if aggregation not in ("mean", "sum"):
        raise ValueError(f"Unknown aggregation: {aggregation}")
    if len(observed_dates) != len(observed_values):
        raise ValueError("Observed dates and values must be aligned")
    if any(finite(v) is None for v in observed_values):
        raise ValueError("Observed series contains missing days")
    if aggregation == "sum" and any(float(v) < 0 for v in observed_values):
        raise ValueError("Observed accumulated quantity cannot be negative")
    obs_through = observed_dates[-1] if observed_dates else None
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
            if obs_through is not None and d <= obs_through:
                continue
            idx = date_idx.get(d)
            if idx is None:
                break
            value = finite(values[idx] if idx < len(values) else None)
            if value is None:
                break
            if aggregation == "sum" and value < 0:
                break
            total += value
            count += 1
            curve[i] = total if aggregation == "sum" else total / count
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
    reference_to_date = clim_run[len(obs_dates) - 1] if obs_dates else None

    models: dict[str, Any] = {}
    for key, mdata in model_data.items():
        models[key] = {
            "label": mdata["label"],
            "run": mdata.get("run"),
            "retrieved_at": mdata.get("retrieved_at"),
            "api_model": mdata.get("api_model"),
            "retained": bool(mdata.get("retained")),
            **merge_running_outlook(obs_dates, obs_values, mdata["regions"][region], dates),
        }

    return {
        "observed_through": obs_dates[-1] if obs_dates else None,
        "observed_running": observed_running,
        "observed_current": round(obs_run[-1], 3) if obs_run else None,
        "climatology_running": clim_run,
        "climatology_month_mean": climate_final,  # historische Frontend-Kompatibilität
        "climatology_period_mean": climate_final,
        "climatology_to_date": reference_to_date,
        "observed_anomaly_to_date": round(obs_run[-1] - reference_to_date, 3) if obs_run else None,
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
        "observation_data_through": regions[REGION_ORDER[0]]["observed_through"],
        "observation_source_through": data_through,
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


def build_temperature_documents(current, climate, fresh, cached, today, support, now):
    """Use one collection of raw members for both calendar months."""
    (year, month), (ny, nm) = outlook_months(today)
    through = current["data_through"]
    first = date(year, month, 1)
    next_first = date(ny, nm, 1)
    anchor = max(date.fromisoformat(through), first - timedelta(days=1))
    models, retained = select_temperature_models(fresh, cached, anchor.isoformat(), now)
    # A preview starts independently: November's sum/mean cannot enter December.
    preview_models, preview_retained = select_temperature_models(
        fresh, cached, (next_first - timedelta(days=1)).isoformat(), now)
    payload = build_payload(current, climate, models, year, month, through, support)
    payload["retained_models"] = retained
    if preview_models:
        preview = build_payload(current, climate, preview_models, ny, nm, through, support)
        preview["retained_models"] = preview_retained
        payload["next_month"] = preview
    return payload, merge_month_caches(models, preview_models)


def merge_month_caches(current, preview):
    """Keep distinct selected raw runs; legacy one-run-per-model caches still work."""
    result = {**preview, **current}
    alternate = {key: model for key, model in preview.items() if key in current and model.get("run") != current[key].get("run")}
    if alternate:
        result["__preview"] = alternate
    return result


def validate_monthly_document(doc):
    """Validate publication including an independently anchored preview."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def check_month(item, preview=False):
        is_temperature = item.get("product") == "state_monthly_ensemble_temperature"
        require(item.get("schema_version") == (2 if is_temperature else 1), "Invalid schema")
        dates = month_dates(item["year"], item["month"])
        require(item["dates"] == dates, "Invalid date axis")
        require(item["regions_order"] == REGION_ORDER and set(item["regions"]) == set(REGION_ORDER), "Missing regions")
        keys = item["models_order"]
        require(len(keys) == len(set(keys)) and set(keys) <= set(MODEL_CONFIG), "Invalid model keys")
        if preview:
            require(bool(keys) and item["observation_data_through"] is None, "Invalid forecast-only preview")
        wanted_periods = {"month", "season", "year"}
        if is_temperature:
            require(set(item["periods"]) == wanted_periods and item["periods"]["month"]["dates"] == dates, "Invalid periods")
        for name in REGION_ORDER:
            region = item["regions"][name]
            periods = region["periods"] if is_temperature else {"month": region}
            require(set(periods) == (wanted_periods if is_temperature else {"month"}), f"Invalid periods {name}")
            for period_key, series in periods.items():
                axis = item["periods"][period_key]["dates"] if is_temperature else dates
                require(bool(axis), "Empty period")
                if is_temperature:
                    p = item["periods"][period_key]
                    require(p["start_date"] == axis[0] and p["end_date"] == axis[-1], "Invalid period bounds")
                    require(len(series["climatology_running"]) == len(axis) and all(finite(v) is not None for v in series["climatology_running"]), "Incomplete climatology")
                observed = series["observed_running"]
                cutoff = series["observed_through"]
                n = axis.index(cutoff)+1 if cutoff else 0
                require(len(observed) == len(axis) and all(finite(v) is not None for v in observed[:n]) and all(v is None for v in observed[n:]), f"Invalid observations {name}/{period_key}")
                require(series["observed_current"] == (observed[n-1] if n else None), "Invalid observed summary")
                if period_key == "month":
                    require(cutoff == item["observation_data_through"], "Inconsistent cutoff")
                require(set(series["models"]) == set(keys), "Inconsistent model keys")
                for m in series["models"].values():
                    require(m["member_count"] > 0 and len(m["control"]) == len(axis), "Invalid member series")
                    require(all(len(m["stats"][k]) == len(axis) for k in ("min","p05","p20","mean","p80","p95","max")), "Invalid percentile series")
                    if preview and period_key == "month":
                        require(m["forecast_from"] == axis[0] and finite(m["stats"]["mean"][0]) is not None, "Forecast does not reach first preview day")
    check_month(doc)
    if "next_month" in doc:
        following = doc["next_month"]
        require((following["year"], following["month"]) == next_month(doc["year"], doc["month"]) and "next_month" not in following, "Invalid next month")
        check_month(following, preview=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--climate", required=True)
    ap.add_argument("--output", default="state_monthly_ensemble.json")
    ap.add_argument("--cache", type=Path, help="Raw temperature member data from the previous run (updated in place)")
    ap.add_argument("--models", default=",".join(MODEL_CONFIG))
    ap.add_argument("--batch-size", type=int, default=24)
    args = ap.parse_args()

    current, climate, _, _, data_through = load_regions(Path(args.current), Path(args.climate))
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    year, month = today.year, today.month
    print(f"HYRAS Datenstand: {data_through}; Zielmonat {year}-{month:02d}", flush=True)

    support = build_support_points(load_geometries())
    print("Stützpunkte:", ", ".join(f"{k}={len(v)}" for k, v in support.items()), flush=True)

    requested = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in requested if m not in MODEL_CONFIG]
    if unknown:
        raise SystemExit("Unbekannte Modelle: " + ", ".join(unknown))

    model_data: dict[str, dict[str, Any]] = {}
    model_errors: dict[str, str] = {}
    forecast_days = month_forecast_days(today, *next_month(year, month))
    for model_key in requested:
        try:
            model_data[model_key] = collect_model(model_key, support, args.batch_size, forecast_days=forecast_days)
            print(f"{model_key}: erfolgreich ({model_data[model_key]['member_count']} Member)", flush=True)
        except Exception as exc:
            model_errors[model_key] = str(exc)
            print(f"FEHLER {model_key}: {exc}", flush=True)

    cache = {}
    if args.cache and args.cache.is_file():
        try:
            old = load_json(args.cache)
            if old.get("schema_version") == 1 and isinstance(old.get("models"), dict):
                if old.get("observation_data_through", "") > data_through:
                    raise SystemExit("HYRAS-Datenstand zurückgefallen; bisherige Daten bleiben erhalten.")
                cache = old["models"]
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            print(f"Temperatur-Cache nicht lesbar: {exc}", flush=True)
    payload, selected = build_temperature_documents(current, climate, model_data, cache, today, support, datetime.now(timezone.utc))
    if not payload["models_order"] and not payload.get("next_month") and not payload["observation_data_through"]:
        raise SystemExit("Kein Ensemblemodell konnte geladen werden.")
    for model_key in model_data.keys() - set(payload["models_order"]):
        model_errors.setdefault(model_key, "Keine gültigen Member für den ersten Prognosetag oder Laufalter außerhalb der Grenzen")
        print(f"WARNUNG {model_key}: {model_errors[model_key]}", flush=True)
    payload["model_errors"] = model_errors
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if args.cache:
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_text(json.dumps({"schema_version":1,"observation_data_through":data_through,"models":selected}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Geschrieben: {output} ({output.stat().st_size/1024:.1f} KiB)", flush=True)
    print("Modelle:", ", ".join(payload["models_order"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

