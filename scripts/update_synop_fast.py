#!/usr/bin/env python3
"""Build a compact fast-live snapshot from DWD SYNOP GeoJSON products.

The DWD weather_reports/synoptic/germany/geojson directory receives decoded
SYNOP batches several times per hour. The batches are incremental, so this
script combines the recent files and maps their observations to the existing
DWD CDC 10-minute station network by coordinates.

Output: fast_current.json + fast_state.json

This is intentionally a supplement to, not a replacement for, the CDC
10-minute live updater. Parameters not safely represented by SYNOP remain on
CDC data (e.g. accumulated daily precipitation and full 24 h series).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

import requests

BASE_URL = "https://opendata.dwd.de/weather/weather_reports/synoptic/germany/geojson/"
USER_AGENT = "climate-dashboard-fast-live/14.0 (+GitHub Actions; DWD Open Data)"
FILE_RE = re.compile(r'href=["\']([^"\']+\.geojson\.gz)["\']', re.I)
STAMP_RE = re.compile(r"_(\d{14})_bda01")


def request(url: str, timeout: int = 40) -> requests.Response:
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            if attempt == 3:
                raise
    raise RuntimeError(str(last))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def set_output(name: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def file_stamp(name: str) -> datetime | None:
    m = STAMP_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def recent_files(listing: str, minutes: int) -> list[tuple[str, datetime]]:
    rows: list[tuple[str, datetime]] = []
    seen: set[str] = set()
    for raw in FILE_RE.findall(listing):
        name = unquote(html.unescape(raw)).split("/")[-1]
        if name in seen:
            continue
        seen.add(name)
        stamp = file_stamp(name)
        if stamp:
            rows.append((name, stamp))
    if not rows:
        return []
    newest = max(stamp for _, stamp in rows)
    cutoff = newest - timedelta(minutes=minutes)
    return sorted([(name, stamp) for name, stamp in rows if stamp >= cutoff], key=lambda x: x[1])


def normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def add_flat(flat: dict[str, list[Any]], key: Any, value: Any) -> None:
    norm = normalize_key(key)
    if not norm:
        return
    if isinstance(value, (str, int, float, bool)) or value is None:
        flat.setdefault(norm, []).append(value)


def flatten_values(node: Any, flat: dict[str, list[Any]]) -> None:
    """Support both ordinary GeoJSON properties and ecCodes key/value dumps."""
    if isinstance(node, dict):
        if "key" in node and "value" in node:
            add_flat(flat, node.get("key"), node.get("value"))
        for key, value in node.items():
            if isinstance(value, dict) and "value" in value:
                add_flat(flat, key, value.get("value"))
            elif not isinstance(value, (dict, list)):
                add_flat(flat, key, value)
            if isinstance(value, (dict, list)):
                flatten_values(value, flat)
    elif isinstance(node, list):
        for value in node:
            flatten_values(value, flat)


def values_for(flat: dict[str, list[Any]], aliases: Iterable[str]) -> list[Any]:
    result: list[Any] = []
    for alias in aliases:
        result.extend(flat.get(normalize_key(alias), []))
    return result


def scalar(flat: dict[str, list[Any]], aliases: Iterable[str]) -> Any:
    vals = values_for(flat, aliases)
    for value in reversed(vals):
        if value not in (None, "", "null", "missing", "MISSING"):
            return value
    return None


def numeric_values(flat: dict[str, list[Any]], aliases: Iterable[str]) -> list[float]:
    result: list[float] = []
    for value in values_for(flat, aliases):
        try:
            n = float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            continue
        if math.isfinite(n) and abs(n) < 1e20 and n not in (999999, 1e20):
            result.append(n)
    return result


def number(flat: dict[str, list[Any]], aliases: Iterable[str], prefer: str = "last") -> float | None:
    vals = numeric_values(flat, aliases)
    if not vals:
        return None
    if prefer == "max":
        return max(vals)
    return vals[-1]


def temperature_c(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 150:  # BUFR SI unit Kelvin
        value -= 273.15
    if not -80 <= value <= 65:
        return None
    return round(value, 2)


def pressure_hpa(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 2000:
        value /= 100.0
    return round(value, 2) if 700 <= value <= 1100 else None


def relative_humidity(value: float | None) -> float | None:
    if value is None:
        return None
    if 0 <= value <= 1.2:
        value *= 100
    return round(value, 1) if 0 <= value <= 100.5 else None


def observation_time(flat: dict[str, list[Any]], fallback: datetime) -> datetime:
    typical_date = scalar(flat, ["typicalDate", "date"])
    typical_time = scalar(flat, ["typicalTime", "time"])
    if typical_date is not None:
        try:
            d = str(int(float(str(typical_date)))).zfill(8)
            t = str(int(float(str(typical_time or 0)))).zfill(6)
            return datetime.strptime(d + t[:6], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except Exception:
            pass
    try:
        y = int(float(str(scalar(flat, ["year"]))))
        m = int(float(str(scalar(flat, ["month"]))))
        d = int(float(str(scalar(flat, ["day"]))))
        h = int(float(str(scalar(flat, ["hour"]))))
        minute = int(float(str(scalar(flat, ["minute"]))))
        sec_raw = scalar(flat, ["second"])
        sec = int(float(str(sec_raw))) if sec_raw is not None else 0
        if 1990 <= y <= 2100:
            return datetime(y, m, d, h, minute, sec, tzinfo=timezone.utc)
    except Exception:
        pass
    return fallback


def iter_features(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("features"), list):
            return [x for x in payload["features"] if isinstance(x, dict)]
        if payload.get("type") == "Feature":
            return [payload]
        # Some DWD converters may wrap multiple feature collections.
        out: list[dict[str, Any]] = []
        for value in payload.values():
            if isinstance(value, (dict, list)):
                out.extend(iter_features(value))
        return out
    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for value in payload:
            out.extend(iter_features(value))
        return out
    return []


def feature_coordinates(feature: dict[str, Any], flat: dict[str, list[Any]]) -> tuple[float, float] | None:
    geom = feature.get("geometry")
    if isinstance(geom, dict):
        coords = geom.get("coordinates")
        if isinstance(coords, list) and len(coords) >= 2:
            try:
                lon, lat = float(coords[0]), float(coords[1])
                if 45 <= lat <= 56 and 4 <= lon <= 16:
                    return lat, lon
            except Exception:
                pass
    lat = number(flat, ["latitude", "localLatitude"])
    lon = number(flat, ["longitude", "localLongitude"])
    if lat is not None and lon is not None and 45 <= lat <= 56 and 4 <= lon <= 16:
        return lat, lon
    return None


def parse_feature(feature: dict[str, Any], fallback_time: datetime) -> dict[str, Any] | None:
    flat: dict[str, list[Any]] = {}
    flatten_values(feature.get("properties", feature), flat)
    coords = feature_coordinates(feature, flat)
    if not coords:
        return None
    lat, lon = coords

    temp = temperature_c(number(flat, ["airTemperatureAt2M", "airTemperature2M", "airTemperature"] ))
    dew = temperature_c(number(flat, ["dewpointTemperatureAt2M", "dewPointTemperatureAt2M", "dewpointTemperature"] ))
    wind = number(flat, ["windSpeedAt10M", "windSpeed10M", "windSpeed"])
    wind_dir = number(flat, ["windDirectionAt10M", "windDirection10M", "windDirection"])
    gust = number(flat, ["maximumWindGustSpeed", "maximumInstantaneousWindSpeedOver10Minutes", "maximumInstantaneousWindSpeed", "windGustSpeed"], prefer="max")
    gust_dir = number(flat, ["maximumWindGustDirection", "windGustDirection"])
    rh = relative_humidity(number(flat, ["relativeHumidity", "relativeHumidityAt2M"] ))
    pressure = pressure_hpa(number(flat, ["pressure", "stationPressure", "nonCoordinatePressure"] ))

    if wind is not None and not 0 <= wind <= 100:
        wind = None
    if gust is not None and not 0 <= gust <= 120:
        gust = None
    if wind_dir is not None:
        wind_dir %= 360
    if gust_dir is not None:
        gust_dir %= 360

    if not any(v is not None for v in (temp, dew, wind, wind_dir, gust, rh, pressure)):
        return None

    block = scalar(flat, ["blockNumber"])
    station_number = scalar(flat, ["stationNumber"])
    wmo = scalar(flat, ["WMO_station_id", "wmoStationId", "stationIdentifier"])
    if wmo is None and block is not None and station_number is not None:
        try:
            wmo = int(float(str(block))) * 1000 + int(float(str(station_number)))
        except Exception:
            wmo = None
    name = scalar(flat, ["stationOrSiteName", "stationName", "name"])
    dt = observation_time(flat, fallback_time)

    return {
        "wmo_id": str(wmo) if wmo is not None else None,
        "station_name": str(name).strip() if name not in (None, "") else None,
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "time_utc": dt.isoformat(timespec="minutes").replace("+00:00", "Z"),
        "temperature_c": temp,
        "dewpoint_c": dew,
        "humidity_pct": rh,
        "pressure_hpa": pressure,
        "wind_speed_ms": round(wind, 2) if wind is not None else None,
        "wind_direction_deg": round(wind_dir, 1) if wind_dir is not None else None,
        "gust_speed_ms": round(gust, 2) if gust is not None else None,
        "gust_direction_deg": round(gust_dir, 1) if gust_dir is not None else None,
    }


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_station(obs: dict[str, Any], stations: list[dict[str, Any]], max_km: float) -> tuple[dict[str, Any] | None, float | None]:
    best = None
    best_d = 1e9
    for station in stations:
        try:
            lat = float(station.get("lat"))
            lon = float(station.get("lon"))
        except (TypeError, ValueError):
            continue
        d = haversine_km(obs["lat"], obs["lon"], lat, lon)
        if d < best_d:
            best, best_d = station, d
    if best is None or best_d > max_km:
        return None, None
    return best, best_d


def richness(obs: dict[str, Any]) -> int:
    keys = ("temperature_c", "dewpoint_c", "humidity_pct", "pressure_hpa", "wind_speed_ms", "wind_direction_deg", "gust_speed_ms", "gust_direction_deg")
    return sum(obs.get(k) is not None for k in keys)


def merge_observation(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return dict(incoming)
    old_t = existing.get("time_utc") or ""
    new_t = incoming.get("time_utc") or ""
    if new_t > old_t:
        merged = dict(existing)
        merged.update({k: v for k, v in incoming.items() if v is not None})
        merged["time_utc"] = new_t
        return merged
    if new_t == old_t:
        merged = dict(existing)
        for key, value in incoming.items():
            if value is not None:
                merged[key] = value
        return merged
    return existing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="fast_live")
    parser.add_argument("--station-index", required=True)
    parser.add_argument("--window-minutes", type=int, default=95)
    parser.add_argument("--max-distance-km", type=float, default=5.0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    station_index_path = Path(args.station_index)
    base = json.loads(station_index_path.read_text(encoding="utf-8"))
    stations = [s for s in base.get("stations", []) if s.get("lat") is not None and s.get("lon") is not None]
    if not stations:
        raise RuntimeError("Keine Stationen mit Koordinaten im CDC-Liveindex gefunden")

    listing = request(BASE_URL).text
    files = recent_files(listing, args.window_minutes)
    if not files:
        raise RuntimeError("Keine aktuellen DWD-SYNOP-GeoJSON-Dateien gefunden")

    signature_payload = "\n".join(name for name, _ in files) + "\n" + hashlib.sha256(station_index_path.read_bytes()).hexdigest()
    signature = hashlib.sha256(signature_payload.encode()).hexdigest()
    state_path = output / "fast_state.json"
    old_state: dict[str, Any] = {}
    if state_path.exists():
        try:
            old_state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            old_state = {}
    if not args.force and old_state.get("source_signature") == signature and (output / "fast_current.json").exists():
        print("SYNOP-Verzeichnis unverändert – kein neuer Fast-Live-Snapshot nötig.")
        set_output("changed", "false")
        return 0

    print(f"Verarbeite {len(files)} SYNOP-GeoJSON-Batches aus den letzten {args.window_minutes} Minuten …")
    raw_observations: list[dict[str, Any]] = []
    failures: list[str] = []
    for i, (name, stamp) in enumerate(files, 1):
        try:
            raw = request(BASE_URL + name).content
            payload = json.loads(gzip.decompress(raw).decode("utf-8", errors="replace"))
            features = iter_features(payload)
            for feature in features:
                obs = parse_feature(feature, stamp)
                if obs:
                    raw_observations.append(obs)
        except Exception as exc:
            failures.append(f"{name}: {str(exc)[:140]}")
        if i % 5 == 0 or i == len(files):
            print(f"  {i}/{len(files)} Batches verarbeitet · {len(raw_observations)} nutzbare Meldungen")

    if not raw_observations:
        raise RuntimeError("In den SYNOP-GeoJSON-Dateien wurden keine nutzbaren Wetterwerte erkannt")

    # First consolidate repeated SYNOP locations/WMO reports by their identity.
    consolidated: dict[str, dict[str, Any]] = {}
    for obs in raw_observations:
        key = obs.get("wmo_id") or f"{obs['lat']:.4f},{obs['lon']:.4f}"
        consolidated[key] = merge_observation(consolidated.get(key), obs)

    matched: dict[str, dict[str, Any]] = {}
    unmatched = 0
    distances: list[float] = []
    for obs in consolidated.values():
        station, distance = nearest_station(obs, stations, args.max_distance_km)
        if not station or distance is None:
            unmatched += 1
            continue
        enriched = dict(obs)
        enriched["station_id"] = str(station.get("id"))
        enriched["station_name_cdc"] = station.get("name")
        enriched["state"] = station.get("state")
        enriched["match_distance_km"] = round(distance, 2)
        sid = enriched["station_id"]
        current = matched.get(sid)
        if current is None or enriched["time_utc"] > current["time_utc"] or (enriched["time_utc"] == current["time_utc"] and richness(enriched) > richness(current)):
            matched[sid] = enriched
        distances.append(distance)

    if len(matched) < 40:
        raise RuntimeError(f"Zu wenige SYNOP-Meldungen konnten dem CDC-Netz zugeordnet werden: {len(matched)}")

    latest = max((x.get("time_utc") for x in matched.values() if x.get("time_utc")), default=None)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {
        "schema_version": 1,
        "generated_at_utc": now,
        "latest_measurement_utc": latest,
        "station_count": len(matched),
        "raw_observation_count": len(raw_observations),
        "consolidated_synop_count": len(consolidated),
        "unmatched_synop_count": unmatched,
        "source_file_count": len(files),
        "source_window_minutes": args.window_minutes,
        "max_match_distance_km": args.max_distance_km,
        "mean_match_distance_km": round(sum(distances) / len(distances), 2) if distances else None,
        "source": "DWD weather_reports/synoptic/germany/geojson",
        "source_note": "Fast-Live-Ergänzung aus dekodierten DWD-SYNOP-Meldungen; Zuordnung zum CDC-10-Minuten-Stationsnetz über Koordinaten. CDC bleibt Referenz für vollständige 24-h-Verläufe und akkumulierte Niederschlagswerte.",
        "stations": sorted(matched.values(), key=lambda x: x["station_id"]),
        "failures": failures[:20],
    }
    write_json(output / "fast_current.json", payload)
    write_json(state_path, {
        "source_signature": signature,
        "generated_at_utc": now,
        "latest_measurement_utc": latest,
        "station_count": len(matched),
        "source_file_count": len(files),
        "schema_version": 1,
    })
    print(f"Fast-Live erstellt: {len(matched)} Stationen · letzter Messzeitpunkt {latest} · {len(failures)} Batch-Fehler")
    set_output("changed", "true")
    set_output("station_count", str(len(matched)))
    set_output("latest_measurement", str(latest or ""))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        set_output("changed", "false")
        raise
