#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

BASE = "https://opendata.fmi.fi/wfs"
UA = "climate-dashboard-fmi-finland-probe/1.0"
TIMEOUT = 120
TRIES = 5
FINLAND_BBOX = "19.0,59.0,32.0,71.5"
DAILY_SIMPLE = "fmi::observations::weather::daily::simple"
DAILY_MPC = "fmi::observations::weather::daily::multipointcoverage"
STATIONS_QUERY = "fmi::ef::stations"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def request_bytes(params: dict[str, Any]) -> bytes:
    query = {
        "service": "WFS",
        "version": "2.0.0",
        **params,
    }
    url = BASE + "?" + urllib.parse.urlencode(query, doseq=True)

    last: Exception | None = None
    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/xml,text/xml,*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                raw = response.read()
                if not raw:
                    raise RuntimeError("Leere FMI-Antwort")
                return raw
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            RuntimeError,
        ) as exc:
            last = exc
            retryable = (
                not isinstance(exc, urllib.error.HTTPError)
                or exc.code in {408, 429, 500, 502, 503, 504}
            )
            if attempt >= TRIES or not retryable:
                if isinstance(exc, urllib.error.HTTPError):
                    try:
                        body = exc.read().decode("utf-8", errors="replace")
                    except Exception:
                        body = ""
                    if body:
                        log("FMI HTTP-Fehlertext:")
                        log(body[:3000])
                raise
            wait = min(30, 3 * attempt)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(str(last))


def parse_xml(raw: bytes) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        preview = raw[:4000].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"FMI XML konnte nicht geparst werden: {exc}\n{preview}"
        ) from exc


def child_text(node: ET.Element, wanted: str) -> str | None:
    for element in node.iter():
        if local(element.tag) == wanted and element.text:
            text = element.text.strip()
            if text:
                return text
    return None


def all_child_texts(node: ET.Element, wanted: str) -> list[str]:
    out = []
    for element in node.iter():
        if local(element.tag) == wanted and element.text:
            text = element.text.strip()
            if text:
                out.append(text)
    return out


def parse_float(value: Any) -> float | None:
    try:
        x = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_pos(text: str | None) -> tuple[float, float] | None:
    if not text:
        return None
    nums = []
    for part in re.split(r"[\s,]+", text.strip()):
        if not part:
            continue
        try:
            nums.append(float(part))
        except ValueError:
            return None
    if len(nums) < 2:
        return None

    a, b = nums[0], nums[1]
    if 50 <= a <= 75 and 10 <= b <= 40:
        return (a, b)
    if 50 <= b <= 75 and 10 <= a <= 40:
        return (b, a)
    return (a, b)


def wfs_members(root: ET.Element) -> list[ET.Element]:
    out = []
    for node in root.iter():
        if local(node.tag) == "member":
            children = list(node)
            if children:
                out.append(children[0])
    return out


def parse_simple_members(raw: bytes) -> list[dict[str, Any]]:
    root = parse_xml(raw)
    rows = []

    for member in wfs_members(root):
        if local(member.tag) != "BsWfsElement":
            continue

        param = child_text(member, "ParameterName")
        value = child_text(member, "ParameterValue")
        obstime = child_text(member, "Time")
        pos = child_text(member, "pos")
        identifiers = all_child_texts(member, "identifier")
        names = all_child_texts(member, "name")

        rows.append(
            {
                "parameter": param,
                "value": parse_float(value),
                "time": obstime,
                "date": parse_date(obstime),
                "pos": parse_pos(pos),
                "identifiers": identifiers,
                "names": names,
                "gml_id": next(
                    (v for k, v in member.attrib.items() if local(k) == "id"),
                    None,
                ),
            }
        )

    return rows


def identifier_by_codespace(
    node: ET.Element,
    wanted_fragment: str,
) -> str | None:
    wanted = wanted_fragment.lower()
    for element in node.iter():
        if local(element.tag) != "identifier":
            continue
        code_space = next(
            (
                str(v)
                for k, v in element.attrib.items()
                if local(k).lower() == "codespace"
            ),
            "",
        ).lower()
        if wanted in code_space and element.text and element.text.strip():
            return element.text.strip()
    return None


def first_numeric_identifier(node: ET.Element) -> str | None:
    for element in node.iter():
        if local(element.tag) != "identifier":
            continue
        if element.text:
            text = element.text.strip()
            if text.isdigit():
                return text
    return None


def parse_station_members(raw: bytes) -> list[dict[str, Any]]:
    root = parse_xml(raw)
    stations = []

    for member in wfs_members(root):
        if local(member.tag) != "EnvironmentalMonitoringFacility":
            continue

        fmisid = (
            identifier_by_codespace(member, "stationcode/fmisid")
            or first_numeric_identifier(member)
        )
        name = (
            identifier_by_codespace(member, "locationcode/name")
            or child_text(member, "name")
        )
        pos = parse_pos(child_text(member, "pos"))
        begin = child_text(member, "beginPosition")

        end = None
        for node in member.iter():
            if local(node.tag) == "endPosition":
                if node.text and node.text.strip():
                    end = node.text.strip()
                else:
                    end = next(
                        (
                            v
                            for k, v in node.attrib.items()
                            if local(k) == "indeterminatePosition"
                        ),
                        None,
                    )
                break

        station_type = None
        for node in member.iter():
            if local(node.tag) == "belongsTo":
                station_type = next(
                    (
                        v
                        for k, v in node.attrib.items()
                        if local(k) == "title"
                    ),
                    None,
                )
                if station_type:
                    break

        stations.append(
            {
                "fmisid": str(fmisid or "").strip(),
                "name": str(name or "").strip(),
                "type": station_type,
                "pos": pos,
                "start": begin,
                "end": end,
            }
        )

    return stations


def in_finland(pos: tuple[float, float] | None) -> bool:
    if pos is None:
        return False
    lat, lon = pos
    return 59.0 <= lat <= 71.5 and 19.0 <= lon <= 32.0


def is_weather_station(station: dict[str, Any]) -> bool:
    text = str(station.get("type") or "").lower()
    return (
        "weather" in text
        or "meteorolog" in text
        or "sää" in text
        or "saa" in text
    )


def get_stations(
    starttime: str | None = None,
    endtime: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "request": "GetFeature",
        "storedquery_id": STATIONS_QUERY,
    }
    if starttime:
        params["starttime"] = starttime
    if endtime:
        params["endtime"] = endtime

    return parse_station_members(request_bytes(params))


def daily_simple(
    *,
    starttime: str,
    endtime: str,
    fmisid: str | None = None,
    bbox: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "request": "GetFeature",
        "storedquery_id": DAILY_SIMPLE,
        "starttime": starttime,
        "endtime": endtime,
        "parameters": "tmin,tmax",
        "timestep": 1440,
    }
    if fmisid:
        params["fmisid"] = fmisid
    if bbox:
        params["bbox"] = bbox

    return parse_simple_members(request_bytes(params))


def try_daily_simple(
    *,
    starttime: str,
    endtime: str,
    fmisid: str | None = None,
    bbox: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Historical FMI requests can reject unsupported dates/station periods
    with HTTP 400. For probing, record that diagnostic instead of aborting.
    """
    try:
        rows = daily_simple(
            starttime=starttime,
            endtime=endtime,
            fmisid=fmisid,
            bbox=bbox,
        )
        return rows, None
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        detail = f"HTTP {exc.code}"
        if body:
            compact = " ".join(body.split())
            detail += ": " + compact[:700]
        return [], detail


def daily_mpc(
    *,
    starttime: str,
    endtime: str,
    bbox: str,
) -> bytes:
    return request_bytes(
        {
            "request": "GetFeature",
            "storedquery_id": DAILY_MPC,
            "starttime": starttime,
            "endtime": endtime,
            "parameters": "tmin,tmax",
            "timestep": 1440,
            "bbox": bbox,
        }
    )


def xml_structure_summary(raw: bytes) -> dict[str, Any]:
    root = parse_xml(raw)
    tags = Counter(local(node.tag) for node in root.iter())

    summary: dict[str, Any] = {
        "bytes": len(raw),
        "top_tags": tags.most_common(25),
        "positions_text": [],
        "tuple_lists": [],
        "field_names": [],
        "parameter_names": [],
    }

    for node in root.iter():
        lname = local(node.tag)

        if lname in {"positions", "posList"} and node.text:
            text = " ".join(node.text.split())
            if text:
                summary["positions_text"].append(text[:1200])

        if lname in {"doubleOrNilReasonTupleList", "tupleList"} and node.text:
            text = " ".join(node.text.split())
            if text:
                summary["tuple_lists"].append(text[:1200])

        if lname in {"field", "Quantity", "ParameterName", "name"}:
            name_attr = next(
                (v for k, v in node.attrib.items() if local(k) == "name"),
                None,
            )
            if name_attr:
                summary["field_names"].append(name_attr)

            if node.text and node.text.strip():
                text = node.text.strip()
                if text.lower() in {"tmin", "tmax"}:
                    summary["parameter_names"].append(text)

    summary["field_names"] = list(dict.fromkeys(summary["field_names"]))
    summary["parameter_names"] = list(dict.fromkeys(summary["parameter_names"]))
    return summary


def pick_long_running_station(
    stations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = []

    for station in stations:
        if not in_finland(station.get("pos")):
            continue

        start = parse_date(station.get("start"))
        if not start:
            continue

        name = str(station.get("name") or "").lower()
        bonus = 0
        if "kaisaniemi" in name:
            bonus -= 10000
        elif "sodankyl" in name:
            bonus -= 5000

        candidates.append((start.toordinal() + bonus, station))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def sample_years_for_station(station: dict[str, Any]) -> list[int]:
    start = parse_date(station.get("start"))
    years = []

    if start:
        years.extend(
            [
                start.year,
                max(start.year, 1900),
                max(start.year, 1950),
                max(start.year, 1961),
                max(start.year, 1991),
            ]
        )

    # Explicit boundary years help distinguish "station started early"
    # from "this WFS path only accepts later dates".
    years.extend([1844, 1850, 1900, 1959, 1960, 1961, 1970, 1991, 2025, 2026])
    return sorted(set(y for y in years if 1844 <= y <= 2026))


def probe() -> None:
    log("=== FMI FINNLAND PROBE ===")
    log(f"Daily Simple: {DAILY_SIMPLE}")
    log(f"Daily MultipointCoverage: {DAILY_MPC}")
    log("Parameter: tmin / tmax")
    log(f"Finnland-BBOX: {FINLAND_BBOX}")
    log("Keine API-Keys/Secrets erforderlich.")

    log()
    log("=== FMI STATIONS-INVENTAR AKTUELL ===")
    current_stations = get_stations()
    finland_stations = [s for s in current_stations if in_finland(s.get("pos"))]
    finland_weather = [s for s in finland_stations if is_weather_station(s)]

    log(f"Alle aktuell gelieferten Facilities: {len(current_stations)}")
    log(f"Davon im Finnland-BBOX: {len(finland_stations)}")
    log(f"Davon als Wetterstation erkannt: {len(finland_weather)}")

    for station in finland_stations[:8]:
        log(
            f"  FMISID {station['fmisid'] or 'NICHT ERKANNT'} | {station['name']} | "
            f"{station['type']} | pos={station['pos']} | "
            f"{station['start']} bis {station['end']}"
        )

    log()
    log("=== FMI HISTORISCHES STATIONS-INVENTAR ===")
    historical_stations = get_stations(
        "1844-01-01T00:00:00Z",
        "2026-12-31T23:59:59Z",
    )
    historical_finland = [
        s for s in historical_stations if in_finland(s.get("pos"))
    ]
    historical_weather = [
        s for s in historical_finland if is_weather_station(s)
    ]

    log(
        f"Facilities 1844-2026 im Finnland-BBOX: "
        f"{len(historical_finland)}"
    )
    log(
        f"Davon als Wetterstation erkannt: {len(historical_weather)}"
    )

    starts = [
        parse_date(s.get("start"))
        for s in historical_finland
        if parse_date(s.get("start"))
    ]
    if starts:
        log(f"Frühester Stationsbeginn im Inventar: {min(starts)}")

    chosen_pool = historical_weather or historical_finland
    long_station = pick_long_running_station(chosen_pool)
    if not long_station:
        raise RuntimeError(
            "Keine historische FMI-Station im Finnland-BBOX erkannt."
        )

    if not str(long_station.get("fmisid") or "").isdigit():
        raise RuntimeError(
            "Langzeit-Sample besitzt keine numerische FMI-Stations-ID. "
            f"Erkannt wurde: {long_station.get('fmisid')!r}"
        )

    log(
        f"Langzeit-Sample: FMISID {long_station['fmisid']} | "
        f"{long_station['name']} | {long_station['start']} bis "
        f"{long_station['end']} | pos={long_station['pos']}"
    )

    log()
    log("=== LANGZEIT-SAMPLE TMIN/TMAX ===")
    successful_years = []
    earliest_value_date = None

    for year in sample_years_for_station(long_station):
        start = f"{year}-01-01T00:00:00Z"
        end_day = date(year, 1, 1) + timedelta(days=6)
        end = end_day.isoformat() + "T23:59:59Z"

        rows, query_error = try_daily_simple(
            starttime=start,
            endtime=end,
            fmisid=long_station["fmisid"],
        )

        if query_error:
            log(
                f"  {year}: FMI-Abfrage abgelehnt ({query_error}) | "
                f"FMISID={long_station['fmisid']}"
            )
            continue

        valid = [
            r for r in rows
            if r.get("parameter") in {"tmin", "tmax"}
            and r.get("value") is not None
        ]

        dates = [r["date"] for r in valid if r.get("date")]
        params = Counter(r["parameter"] for r in valid)

        log(
            f"  {year}: {len(valid)} Werte | "
            f"tmin={params.get('tmin',0)} | "
            f"tmax={params.get('tmax',0)} | "
            f"{min(dates) if dates else 'keine Daten'}"
            f"{' bis ' + str(max(dates)) if dates else ''}"
        )

        if valid:
            successful_years.append(year)
            if dates and (
                earliest_value_date is None
                or min(dates) < earliest_value_date
            ):
                earliest_value_date = min(dates)

    log()
    log("=== FINNLAND-BBOX SIMPLE SAMPLE ===")
    national_rows, national_error = try_daily_simple(
        starttime="2026-08-01T00:00:00Z",
        endtime="2026-08-02T23:59:59Z",
        bbox=FINLAND_BBOX,
    )
    if national_error:
        log(f"Simple-BBOX-Abfrage abgelehnt: {national_error}")

    valid_rows = [
        r for r in national_rows
        if r.get("parameter") in {"tmin", "tmax"}
        and r.get("value") is not None
    ]
    coord_counts = Counter(
        r["pos"] for r in valid_rows if r.get("pos") is not None
    )
    params = Counter(r["parameter"] for r in valid_rows)

    log(f"Simple XML TMIN/TMAX-Werte: {len(valid_rows)}")
    log(
        f"Koordinaten/Stationspunkte im 2-Tage-Sample: "
        f"{len(coord_counts)}"
    )
    log(
        f"tmin={params.get('tmin',0)} | "
        f"tmax={params.get('tmax',0)}"
    )

    for row in valid_rows[:6]:
        log(
            f"  {row['date']} | {row['parameter']}={row['value']} | "
            f"pos={row['pos']} | ids={row['identifiers']} | "
            f"names={row['names']} | gml_id={row['gml_id']}"
        )

    log()
    log("=== FINNLAND-BBOX MULTIPOINTCOVERAGE SAMPLE ===")
    mpc_raw = daily_mpc(
        starttime="2026-08-01T00:00:00Z",
        endtime="2026-08-03T23:59:59Z",
        bbox=FINLAND_BBOX,
    )
    structure = xml_structure_summary(mpc_raw)

    log(f"MultipointCoverage XML-Größe: {structure['bytes']:,} Bytes")
    log(f"Häufigste XML-Tags: {structure['top_tags']}")
    log(f"Erkannte Feldnamen: {structure['field_names']}")
    log(f"Erkannte Parameternamen: {structure['parameter_names']}")
    log(
        f"Positions-/posList-Blöcke: "
        f"{len(structure['positions_text'])}"
    )
    for text in structure["positions_text"][:2]:
        log(f"  positions: {text[:900]}")
    log(f"Tuple-Listen: {len(structure['tuple_lists'])}")
    for text in structure["tuple_lists"][:2]:
        log(f"  tuple: {text[:900]}")

    log()
    log("=" * 72)
    log("=== FMI FINLAND PROBE SUMMARY ===")
    log("=" * 72)
    log(
        f"Aktuelle Facilities Finnland: {len(finland_stations)} | "
        f"erkannte Wetterstationen: {len(finland_weather)}"
    )
    log(
        f"Historische Facilities Finnland 1844-2026: "
        f"{len(historical_finland)} | "
        f"erkannte Wetterstationen: {len(historical_weather)}"
    )
    log(
        f"Frühester Stationsbeginn im Inventar: "
        f"{min(starts) if starts else None}"
    )
    log(
        f"Langzeit-Sample: {long_station['name']} "
        f"(FMISID {long_station['fmisid']})"
    )
    log(
        f"Sample-Jahre mit tatsächlichem tmin/tmax: "
        f"{successful_years}"
    )
    log(
        f"Frühestes tatsächlich gefundenes Sample-Datum: "
        f"{earliest_value_date}"
    )
    log(
        f"Simple-BBOX 2026: {len(coord_counts)} Stationspunkte | "
        f"{len(valid_rows)} Tmin/Tmax-Werte"
    )
    log(
        f"MultipointCoverage: {structure['bytes']:,} Bytes | "
        f"Felder={structure['field_names']}"
    )
    log(
        "Hinweis: HTTP-400 bei einzelnen sehr alten Testjahren ist im Probe "
        "nur eine Reichweiten-Diagnose und kein Abbruchgrund."
    )
    log("FMI Finland Probe OK.")


def self_test() -> None:
    simple_xml = b'''<?xml version="1.0"?>
<wfs:FeatureCollection
 xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:BsWfs="http://xml.fmi.fi/schema/wfs/2.0"
 xmlns:gml="http://www.opengis.net/gml/3.2">
 <wfs:member>
  <BsWfs:BsWfsElement gml:id="BsWfsElement.1.1">
   <BsWfs:Location>
    <gml:Point><gml:pos>60.17 24.94</gml:pos></gml:Point>
   </BsWfs:Location>
   <BsWfs:Time>2026-08-01T00:00:00Z</BsWfs:Time>
   <BsWfs:ParameterName>tmax</BsWfs:ParameterName>
   <BsWfs:ParameterValue>28.4</BsWfs:ParameterValue>
  </BsWfs:BsWfsElement>
 </wfs:member>
</wfs:FeatureCollection>'''

    rows = parse_simple_members(simple_xml)
    assert len(rows) == 1
    assert rows[0]["parameter"] == "tmax"
    assert rows[0]["value"] == 28.4
    assert rows[0]["date"] == date(2026, 8, 1)
    assert rows[0]["pos"] == (60.17, 24.94)

    station_xml = b'''<?xml version="1.0"?>
<wfs:FeatureCollection
 xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ef="http://inspire.ec.europa.eu/schemas/ef/4.0"
 xmlns:gml="http://www.opengis.net/gml/3.2"
 xmlns:xlink="http://www.w3.org/1999/xlink">
 <wfs:member>
  <ef:EnvironmentalMonitoringFacility>
   <gml:identifier codeSpace="http://xml.fmi.fi/namespace/stationcode/fmisid">100971</gml:identifier>
   <gml:name codeSpace="http://xml.fmi.fi/namespace/locationcode/name">Helsinki Kaisaniemi</gml:name>
   <ef:belongsTo xlink:title="weather"/>
   <ef:representativePoint>
    <gml:Point><gml:pos>60.18 24.94</gml:pos></gml:Point>
   </ef:representativePoint>
   <ef:operationalActivityPeriod>
    <ef:OperationalActivityPeriod>
     <ef:activityTime>
      <gml:TimePeriod>
       <gml:beginPosition>1844-01-01</gml:beginPosition>
       <gml:endPosition indeterminatePosition="unknown"/>
      </gml:TimePeriod>
     </ef:activityTime>
    </ef:OperationalActivityPeriod>
   </ef:operationalActivityPeriod>
  </ef:EnvironmentalMonitoringFacility>
 </wfs:member>
</wfs:FeatureCollection>'''

    stations = parse_station_members(station_xml)
    assert len(stations) == 1
    assert stations[0]["fmisid"] == "100971"
    assert stations[0]["name"] == "Helsinki Kaisaniemi"
    assert stations[0]["pos"] == (60.18, 24.94)
    assert stations[0]["start"] == "1844-01-01"
    assert is_weather_station(stations[0])

    print("FMI Finland probe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
