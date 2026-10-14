#!/usr/bin/env python3
"""Compute annual and daily accumulated cyclone energy from official NHC HURDAT2."""
import csv
import io
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SOURCES = {
 "atl": "https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-092326.txt",
 "epac": "https://www.nhc.noaa.gov/data/hurdat/hurdat2-nepac-1949-2025-092926.txt",
}
# NHC files are retrospective through 2025; current season is NOT represented.
def parse(text):
    daily = defaultdict(lambda: defaultdict(float))
    storm_id = None
    for line in csv.reader(io.StringIO(text)):
        fields = [v.strip() for v in line]
        if not fields: continue
        if fields[0].startswith(("AL", "EP", "CP")) and len(fields[0]) == 8:
            storm_id = fields[0]
            continue
        if not storm_id or len(fields) < 7: continue
        date, hour, status = fields[0], fields[1], fields[3]
        try: wind = int(fields[6])
        except ValueError: continue
        # Standard six-hour synoptic best-track points, tropical/subtropical storms.
        if hour not in ("0000", "0600", "1200", "1800"): continue
        if status not in ("TS", "HU", "SS") or wind < 34: continue
        y = int(date[:4])
        day = date[4:6] + "-" + date[6:8]
        daily[y][day] += wind * wind / 10000
    return daily

def main():
    out = {"ready": True, "source": "NHC HURDAT2", "updated_utc": datetime.now(timezone.utc).isoformat(),
           "reference_period": [1991, 2020], "basins": {}}
    for basin, url in SOURCES.items():
        req = Request(url, headers={"User-Agent": "ClimateDashboard/1.0 (research)"})
        with urlopen(req, timeout=90) as response: raw = response.read().decode("utf-8-sig")
        parsed = parse(raw)
        if not parsed: raise RuntimeError("No ACE records parsed: " + basin)
        years = sorted(parsed)
        series = {}
        for year in years:
            total = 0.0
            curve = []
            from datetime import date, timedelta
            day = date(2000, 1, 1)
            while day.year == 2000:
                total += parsed[year].get(day.strftime("%m-%d"), 0)
                curve.append(round(total, 3))
                day += timedelta(days=1)
            series[str(year)] = {"total": round(total, 2), "daily_cumulative": curve}
        baseline = [series[str(y)]["total"] for y in range(1991, 2021)]
        climatology = [round(sum(series[str(y)]["daily_cumulative"][d] for y in range(1991, 2021)) / 30, 3) for d in range(366)]
        out["basins"][basin] = {
          "name": "Nordatlantik" if basin == "atl" else "Nordost-/Nordzentralpazifik",
          "first_year": min(years), "last_year": max(years), "reference_mean": round(sum(baseline) / 30, 2),
          "reference_daily": climatology, "years": series, "source_url": url}
    target = Path("ace/index.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"))+"\n", encoding="utf-8")
    print("ACE years:", {b:(v["first_year"],v["last_year"]) for b,v in out["basins"].items()})
if __name__ == "__main__": main()
