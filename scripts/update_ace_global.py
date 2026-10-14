#!/usr/bin/env python3
"""Global ACE proxy from NOAA IBTrACS v04r01, calendar-year attribution.

Six-hourly USA_WIND (1-min maximum sustained winds in knots) for TS/SS,
>=34 kt, excludes intermediate observations. Do not combine basin-specific
CSV files because storms crossing basin boundaries would be duplicated.
"""
import csv
import io
import json
from collections import defaultdict
from contextlib import ExitStack
from itertools import chain
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
       "stewardship-ibtracs/v04r01/access/csv/ibtracs.since1980.list.v04r01.csv")
LATEST_URL = URL.replace("ibtracs.since1980.list", "ibtracs.last3years.list")
NAMES = {"NA":"Nordatlantik", "EP":"Nordost-/Zentralpazifik",
         "WP":"Nordwestpazifik", "NI":"Nordindischer Ozean",
         "SI":"Südindischer Ozean", "SP":"Südpazifik"}
CODES = tuple(NAMES)
FIRST, LAST_REFERENCE = 1980, 2020

def aggregate(rows):
    counts = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    seen = set()
    latest = None
    for row in rows:
        stamp = (row.get("ISO_TIME") or "").strip()
        basin = (row.get("BASIN") or "").strip()
        nature = (row.get("NATURE") or "").strip()
        sid = (row.get("SID") or "").strip()
        if basin not in NAMES or nature not in ("TS", "SS") or len(stamp) < 16:
            continue
        try:
            dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
            wind = float(row.get("USA_WIND") or "")
        except (ValueError, TypeError):
            continue
        if dt.hour not in (0,6,12,18) or dt.minute != 0 or wind < 34:
            continue
        key = (sid, stamp)
        if key in seen:
            continue
        seen.add(key)
        year = dt.year
        if year < FIRST:
            continue
        counts[basin][year][dt.strftime("%m-%d")] += wind * wind / 10000.0
        if latest is None or dt > latest: latest = dt
    return counts, latest

def build(rows):
    observations, latest_observation = aggregate(rows)
    current_year = datetime.now(timezone.utc).year
    last_year = current_year if latest_observation and latest_observation.year == current_year else current_year - 1
    last_observed_date = latest_observation.date() if latest_observation else None
    all_basins = {**{key:NAMES[key] for key in CODES}, "GLOBAL":"Global"}
    records = {}
    start = date(2000,1,1)
    days = [(start+timedelta(days=i)).strftime("%m-%d") for i in range(366)]
    for basin,name in all_basins.items():
        years = {}
        for year in range(FIRST,last_year+1):
            values = defaultdict(float)
            for key in (CODES if basin == "GLOBAL" else [basin]):
                for day,val in observations[key].get(year,{}).items():
                    values[day] += val
            total=0.0
            curve=[]
            for day in days:
                if year == current_year and day != "02-29" and (not last_observed_date or date(year, int(day[:2]), int(day[3:])) > last_observed_date):
                    curve.append(None)
                    continue
                if year == current_year and day == "02-29" and year % 4:
                    curve.append(None)
                    continue
                total += values[day]
                curve.append(round(total,3))
            years[str(year)] = {"total":round(total,2),"daily_cumulative":curve,
                                "provisional":year==current_year,
                                "last_date":last_observed_date.isoformat() if year==current_year else None}
        reference = [years[str(y)]["total"] for y in range(1991,LAST_REFERENCE+1)]
        climatology = [round(sum(years[str(y)]["daily_cumulative"][i] for y in range(1991,2021))/30,3) for i in range(366)]
        records[basin] = {"name":name,"first_year":FIRST,"last_year":last_year,
          "reference_mean":round(sum(reference)/30,2),
          "reference_daily":climatology,"years":years}
    return {"ready":True,"source":"NOAA IBTrACS v04r01",
        "source_url":URL,"recent_source_url":LATEST_URL,"wind_column":"USA_WIND","reference_period":[1991,2020],
        "method":"6-hourly USA_WIND >=34 kt, NATURE TS/SS, squared wind / 10000, calendar years",
        "note":"Comparable ACE approximation, not official basin RSMC ACE totals; retrospective IBTrACS data may be revised.",
        "updated_utc":datetime.now(timezone.utc).isoformat(),
        "last_observation":latest_observation.isoformat() if latest_observation else None,
        "basins":records}

def main():
    def observations(response):
        text = io.TextIOWrapper(response, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        next(reader, None)  # IBTrACS column units.
        return reader
    with ExitStack() as stack:
        base = stack.enter_context(urlopen(Request(URL, headers={"User-Agent":"ClimateDashboard/1.0"}),timeout=180))
        feeds = [observations(base)]
        try:
            recent = stack.enter_context(urlopen(Request(LATEST_URL,headers={"User-Agent":"ClimateDashboard/1.0"}),timeout=90))
            feeds.append(observations(recent))
            print("Recent IBTrACS feed loaded")
        except Exception as error:
            print("Recent feed unavailable; only validated base source used:", error)
        result = build(chain.from_iterable(feeds))
    if result["basins"]["GLOBAL"]["reference_mean"] <= 50:
        raise RuntimeError("Implausible global ACE climatology; source parsing may have failed")
    target=Path("ace/global.json")
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print("Wrote",target,"through",result["basins"]["GLOBAL"]["last_year"])

if __name__=="__main__":
    main()
