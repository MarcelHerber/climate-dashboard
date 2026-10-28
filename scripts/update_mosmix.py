#!/usr/bin/env python3
"""
Build German MOSMIX map data and regional on-demand station meteograms.

The upstream DWD KMZ covers worldwide stations, but only forecasts within
German map bounds are parsed. No worldwide station catalogue is published.

Outputs:
- mosmix_ttt.json: German-region TTT, extrema and sunshine map data
- stations/<key>.json: German-region on-demand meteograms
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

# Read original DWD interval forecasts; do not infer multi-hour totals or gusts
# from hourly points. Both spellings of the 12-hour gust occur in catalogues.
METEOGRAM_PARAMS = (
    "TTT", "TX", "TN", "Td", "RR1c", "RR3c", "RR6c", "RRhc", "RRdc",
    "FF", "FX1", "FX3", "FXh", "FFXh", "DD", "N", "PPPP",
    "SunD1", "Rad1h", "Neff", "Nl", "Nm", "Nh",
    "VV", "VV10", "wwM", "wwM6", "wwT", "wwT6", "wwC",
    "wwS", "RRS1c", "RRS3c", "ww",
)


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

        if parameter in {"TTT", "Td", "TX", "TN"}:
            converted.append(round(value - 273.15, 1))
        elif parameter in {"FF", "FX1", "FX3", "FXh", "FFXh"}:
            # MOSMIX wind is m/s; display files use km/h for the dashboard.
            converted.append(round(value * 3.6, 1))
        elif parameter == "SunD1":
            # The DWD supplies one-hour sunshine duration in seconds.
            # A plotted 60 min means full sunshine during the preceding hour.
            converted.append(round(max(0.0,min(3600.0,value))/60.0, 1))
        elif parameter == "VV":
            # Visibility is published in metres. Map and diagrams use km.
            converted.append(round(value / 1000.0, 2))
        elif parameter == "ww":
            # WMO-like code is categorical, not a probability.
            converted.append(int(value) if 0 <= value <= 99 and int(value) == value else None)
        elif parameter in {"VV10", "wwM", "wwM6", "wwT", "wwT6",
                           "wwC", "wwS"}:
            converted.append(round(value, 1) if 0 <= value <= 100 else None)
        elif parameter == "Rad1h":
            # One-hour shortwave energy sum in kJ/m².
            converted.append(round(value, 1))
        elif parameter == "PPPP":
            # Reduced pressure is supplied in Pa; use hPa in the meteogram.
            converted.append(round(value / 100.0, 1))
        elif parameter in {"RR1c", "RR3c", "RR6c", "RRhc", "RRdc", "RRS1c", "RRS3c"}:
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
    tx_indices: list[int] = []
    tn_indices: list[int] = []
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
                        index = len(timesteps)
                        timesteps.append(text)
                        # DWD: in Europe TX valid 18 UTC and TN valid 06 UTC;
                        # both forecast a 12-hour extrema interval.
                        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
                        utc_hour = stamp.astimezone(timezone.utc).hour
                        if utc_hour == 18:
                            tx_indices.append(index)
                        elif utc_hour == 6:
                            tn_indices.append(index)
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
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    elem.clear()
                    continue
                if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
                    # Skip costly worldwide forecast vectors entirely.
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

                # Canonicalize the original 12 h gust field despite its
                # FXh/FFXh naming difference across DWD reference catalogues.
                if "FXh" not in forecasts and "FFXh" in forecasts:
                    forecasts["FXh"] = forecasts["FFXh"]
                forecasts.pop("FFXh", None)

                ttt = forecasts.get("TTT") or [None] * len(timesteps)
                tx = forecasts.get("TX") or []
                tn = forecasts.get("TN") or []
                sun1 = forecasts.get("SunD1") or [None] * len(timesteps)
                # Sparse maps avoid adding hundreds of nulls per station.
                tx12 = {str(i): tx[i] for i in tx_indices if i < len(tx) and tx[i] is not None}
                tn12 = {str(i): tn[i] for i in tn_indices if i < len(tn) and tn[i] is not None}
                if not (any(v is not None for v in ttt) or tx12 or tn12):
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
                # Extra map parameters are held in the source archive only.
                # The browser receives day/parameter slices, not these arrays.
                map_extra = {
                    name: forecasts[name] for name in (
                        "RR1c", "RR3c", "RR6c", "RRhc", "RRdc",
                        "FX1", "FX3", "FXh", "N", "Neff", "Nl", "Nm", "Nh",
                        "VV", "VV10", "wwM", "wwM6", "wwT", "wwT6",
                        "wwC", "wwS", "RRS1c", "RRS3c", "ww",
                    ) if name in forecasts
                }
                stations.append({
                    **station_meta, "values": ttt,
                    "tx12": tx12, "tn12": tn12,
                    "sun1": sun1, "map_extra": map_extra,
                })
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
        raise RuntimeError("Keine MOSMIX-Temperaturpunkte im Deutschlandausschnitt gefunden.")
    if not any(station["tx12"] for station in stations):
        raise RuntimeError("Kein originaler MOSMIX-TX-Wert für 18 UTC gefunden.")
    if not any(station["tn12"] for station in stations):
        raise RuntimeError("Kein originaler MOSMIX-TN-Wert für 06 UTC gefunden.")

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
        "parameter": "TTT / TX / TN / SunD1 / Rad1h",
        "extrema_reference": {
            "TX": {"valid_hour_utc": 18, "period_hours": 12, "unit": "°C"},
            "TN": {"valid_hour_utc": 6, "period_hours": 12, "unit": "°C"},
        },
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
            "TX": {"label": "Temperaturmaximum letzte 12 h, 18 UTC", "unit": "°C"},
            "TN": {"label": "Temperaturminimum letzte 12 h, 06 UTC", "unit": "°C"},
            "Td": {"label": "2-m-Taupunkt", "unit": "°C"},
            "RR1c": {"label": "1-h-Niederschlag", "unit": "mm"},
            "RR3c": {"label": "3-h-Niederschlag", "unit": "mm"},
            "RR6c": {"label": "6-h-Niederschlag", "unit": "mm"},
            "RRhc": {"label": "12-h-Niederschlag", "unit": "mm"},
            "RRdc": {"label": "24-h-Niederschlag", "unit": "mm"},
            "FF": {"label": "Wind", "unit": "km/h"},
            "FX1": {"label": "1-h-Böe", "unit": "km/h"},
            "FX3": {"label": "3-h-Böe", "unit": "km/h"},
            "FXh": {"label": "12-h-Böe", "unit": "km/h"},
            "DD": {"label": "Windrichtung", "unit": "°"},
            "N": {"label": "Gesamtbedeckung", "unit": "%"},
            "Neff": {"label": "Effektiver Bedeckungsgrad", "unit": "%"},
            "Nl": {"label": "Tiefe Bewölkung unter 2 km", "unit": "%"},
            "Nm": {"label": "Mittelhohe Bewölkung 2 bis 7 km", "unit": "%"},
            "Nh": {"label": "Hohe Bewölkung über 7 km", "unit": "%"},
            "PPPP": {"label": "Luftdruck", "unit": "hPa"},
            "SunD1": {"label": "Sonnenscheindauer der letzten Stunde", "unit": "min"},
            "Rad1h": {"label": "Globalstrahlung der letzten Stunde", "unit": "kJ/m²"},
            "VV": {"label": "Sichtweite", "unit": "km"},
            "VV10": {"label": "Wahrscheinlichkeit Sichtweite unter 1 km", "unit": "%"},
            "wwM": {"label": "Nebelwahrscheinlichkeit letzte 1 h", "unit": "%"},
            "wwM6": {"label": "Nebelwahrscheinlichkeit letzte 6 h", "unit": "%"},
            "wwT": {"label": "Gewitterwahrscheinlichkeit letzte 1 h", "unit": "%"},
            "wwT6": {"label": "Gewitterwahrscheinlichkeit letzte 6 h", "unit": "%"},
            "wwC": {"label": "Konvektiver Niederschlag letzte 1 h", "unit": "%"},
            "wwS": {"label": "Fester Niederschlag letzte 1 h", "unit": "%"},
            "RRS1c": {"label": "Schneeniederschlag Wasseräquivalent letzte 1 h", "unit": "mm"},
            "RRS3c": {"label": "Schneeniederschlag Wasseräquivalent letzte 3 h", "unit": "mm"},
            "ww": {"label": "Signifikantes Wetter, DWD-Wettercode", "unit": "Code"},
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
    # Clean up obsolete worldwide outputs on local / repeated builds.
    (output.parent / "world_stations.json").unlink(missing_ok=True)
    import shutil
    shutil.rmtree(output.parent / "world", ignore_errors=True)

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
        f"Deutschland-Meteogramme: {len(list(detail_dir.glob('*.json')))}"
    )


if __name__ == "__main__":
    main()
