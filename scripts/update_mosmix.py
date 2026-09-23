#!/usr/bin/env python3
"""
Build compact Germany-only MOSMIX-L data for the dashboard.

Outputs:
- mosmix_ttt.json: compact TTT map data for all Germany-area points
- stations/<key>.json: on-demand meteogram data for one point
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

DEFAULT_SOURCE_URL = "https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/all_stations/kml/MOSMIX_L_LATEST.kmz"
USER_AGENT = "climate-dashboard-mosmix/2.0 (+GitHub Actions; DWD Open Data)"

# Germany plus a small border buffer so border points are not lost.
LON_MIN, LON_MAX = 5.45, 15.55
LAT_MIN, LAT_MAX = 47.15, 55.15

METEOGRAM_PARAMS = ("TTT", "Td", "RR1c", "FF", "FX1", "DD", "N", "PPPP")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(node: ET.Element, wanted: str) -> str | None:
    for child in node.iter():
        if local_name(child.tag) == wanted:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def raw_values(forecast: ET.Element) -> list[float | None]:
    raw = " ".join(part.strip() for part in forecast.itertext() if part and part.strip())
    values: list[float | None] = []
    for token in raw.split():
        if token in {"-", "--", "NaN", "nan"}:
            values.append(None)
            continue
        try:
            values.append(float(token))
        except ValueError:
            values.append(None)
    return values


def convert_values(parameter: str, values: list[float | None]) -> list[float | None]:
    converted: list[float | None] = []
    for value in values:
        if value is None:
            converted.append(None)
            continue

        if parameter in {"TTT", "Td"}:
            converted.append(round(value - 273.15, 1))
        elif parameter in {"FF", "FX1"}:
            # MOSMIX wind is m/s; display files use km/h for the dashboard.
            converted.append(round(value * 3.6, 1))
        elif parameter == "PPPP":
            # Reduced pressure is supplied in Pa; use hPa in the meteogram.
            converted.append(round(value / 100.0, 1))
        elif parameter == "RR1c":
            # kg/m² water equivalent == mm precipitation.
            converted.append(round(value, 2))
        elif parameter in {"N", "DD"}:
            converted.append(round(value, 1))
        else:
            converted.append(round(value, 2))
    return converted


def normalize_length(values: list[float | None], length: int) -> list[float | None]:
    if len(values) < length:
        return values + [None] * (length - len(values))
    if len(values) > length:
        return values[:length]
    return values


def station_key(station_id: str, lat: float, lon: float) -> str:
    token = f"{station_id}|{lat:.5f}|{lon:.5f}".encode("utf-8")
    return hashlib.sha1(token).hexdigest()[:14]


def download(url: str, target: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as response, target.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def parse_kmz(path: Path, source_url: str, detail_dir: Path) -> dict:
    timesteps: list[str] = []
    stations: list[dict] = []
    issue_time: str | None = None
    models: list[dict] = []
    detail_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(path) as zf:
        kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not kml_names:
            raise RuntimeError("MOSMIX-KMZ enthält keine KML-Datei.")

        with zf.open(kml_names[0]) as handle:
            for _event, elem in ET.iterparse(handle, events=("end",)):
                name = local_name(elem.tag)

                if name == "IssueTime" and not issue_time:
                    issue_time = (elem.text or "").strip() or None
                    elem.clear()
                    continue

                if name == "TimeStep":
                    text = (elem.text or "").strip()
                    if text:
                        timesteps.append(text)
                    elem.clear()
                    continue

                if name == "Model":
                    model_name = None
                    reference_time = None
                    for key, value in elem.attrib.items():
                        lk = local_name(key)
                        if lk == "name":
                            model_name = value
                        elif lk == "referenceTime":
                            reference_time = value
                    if model_name or reference_time:
                        models.append({"name": model_name, "reference_time": reference_time})
                    elem.clear()
                    continue

                if name != "Placemark":
                    continue

                station_id = child_text(elem, "name") or ""
                station_name = child_text(elem, "description") or station_id
                coords_text = child_text(elem, "coordinates")
                if not coords_text:
                    elem.clear()
                    continue

                parts = coords_text.split()[0].split(",")
                if len(parts) < 2:
                    elem.clear()
                    continue

                lon = parse_float(parts[0])
                lat = parse_float(parts[1])
                elev = parse_float(parts[2]) if len(parts) > 2 else None
                if lon is None or lat is None:
                    elem.clear()
                    continue
                if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
                    elem.clear()
                    continue

                forecasts: dict[str, list[float | None]] = {}
                for node in elem.iter():
                    if local_name(node.tag) != "Forecast":
                        continue

                    element_name = None
                    for key, value in node.attrib.items():
                        if local_name(key) == "elementName":
                            element_name = value
                            break

                    if element_name not in METEOGRAM_PARAMS:
                        continue

                    values = convert_values(element_name, raw_values(node))
                    forecasts[element_name] = normalize_length(values, len(timesteps))

                ttt = forecasts.get("TTT")
                if not ttt or not any(v is not None for v in ttt):
                    elem.clear()
                    continue

                key = station_key(station_id, lat, lon)
                station_meta = {
                    "id": station_id,
                    "name": station_name,
                    "lat": round(lat, 5),
                    "lon": round(lon, 5),
                    "elev_m": None if elev is None else round(elev, 1),
                    "key": key,
                }
                stations.append({**station_meta, "values": ttt})

                detail = {
                    **station_meta,
                    "issue_time": issue_time,
                    "parameters": forecasts,
                }
                (detail_dir / f"{key}.json").write_text(
                    json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )

                elem.clear()

    if not timesteps:
        raise RuntimeError("Keine MOSMIX-Zeitschritte gefunden.")
    if not stations:
        raise RuntimeError("Keine MOSMIX-TTT-Punkte im Deutschlandausschnitt gefunden.")

    seen = set()
    unique_models = []
    for model in models:
        key = (model.get("name"), model.get("reference_time"))
        if key in seen:
            continue
        seen.add(key)
        unique_models.append(model)

    return {
        "product": "DWD MOSMIX-L",
        "parameter": "TTT",
        "unit": "°C",
        "issue_time": issue_time,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_url": source_url,
        "bounds": [LON_MIN, LAT_MIN, LON_MAX, LAT_MAX],
        "models": unique_models,
        "timesteps": timesteps,
        "station_count": len(stations),
        "meteogram_parameters": {
            "TTT": {"label": "2-m-Temperatur", "unit": "°C"},
            "Td": {"label": "2-m-Taupunkt", "unit": "°C"},
            "RR1c": {"label": "1-h-Niederschlag", "unit": "mm"},
            "FF": {"label": "Wind", "unit": "km/h"},
            "FX1": {"label": "1-h-Böe", "unit": "km/h"},
            "DD": {"label": "Windrichtung", "unit": "°"},
            "N": {"label": "Gesamtbedeckung", "unit": "%"},
            "PPPP": {"label": "Luftdruck", "unit": "hPa"},
        },
        "stations": sorted(stations, key=lambda s: (s["name"], s["id"], s["key"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="mosmix_ttt.json")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    detail_dir = output.parent / "stations"

    if detail_dir.exists():
        for file in detail_dir.glob("*.json"):
            file.unlink()

    with tempfile.TemporaryDirectory(prefix="mosmix-") as tmp:
        kmz = Path(tmp) / "MOSMIX_L_LATEST.kmz"
        print(f"Lade {args.source_url}")
        download(args.source_url, kmz)
        print(f"KMZ: {kmz.stat().st_size / 1024 / 1024:.1f} MB")
        data = parse_kmz(kmz, args.source_url, detail_dir)

    tmp_out = output.with_suffix(output.suffix + ".tmp")
    tmp_out.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp_out.replace(output)

    print(
        f"Geschrieben: {output} | {data['station_count']} Punkte | "
        f"{len(data['timesteps'])} Zeitschritte | Lauf {data.get('issue_time')} | "
        f"Meteogramme: {len(list(detail_dir.glob('*.json')))}"
    )


if __name__ == "__main__":
    main()
