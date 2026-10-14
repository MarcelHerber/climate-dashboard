#!/usr/bin/env python3
"""Windbasierter Major-SSW-Katalog (Charlton & Polvani 2007) aus NASA MERRA-2."""
import argparse
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DAY = timedelta(days=1)
DATE = re.compile(r"^\d{4}-\d\d-\d\d$")


def days(start, end):
    while start <= end:
        yield start
        start += DAY


def parse_nasa(raw):
    result = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 9 or not DATE.fullmatch(parts[0]):
            continue
        try:
            date_value = date.fromisoformat(parts[0])
            wind = float(parts[1])
            lead = int(parts[9]) if len(parts) >= 10 else 0
        except ValueError:
            continue
        if lead == 0 and math.isfinite(wind) and -250 < wind < 250:
            result[date_value] = wind
    return result


def west_run(wind, start, end, n):
    consecutive = 0
    for day in days(start, end):
        if wind.get(day, 0) > 0:
            consecutive += 1
            if consecutive == n:
                return (day - timedelta(days=n - 1)).isoformat()
        else:
            consecutive = 0
    return None


def classify(year, wind, today):
    first, last = date(year, 11, 1), date(year + 1, 4, 30)
    required = list(days(first - DAY, last))
    missing = [day for day in required if day not in wind]
    count = len(required) - len(missing)
    leap_gap = bool(missing) and all(d.month == 2 and d.day == 29 for d in missing)
    usable = today >= last and (not missing or leap_gap)
    season = {"year": year, "label": f"{year}/{str(year+1)[-2:]}",
              "status": "complete" if today >= last and not missing else
                        "leap_gap" if today >= last and leap_gap else
                        "incomplete" if today >= last else "in_progress",
              "days_available": count, "days_expected": len(required),
              "missing_feb29": leap_gap, "events": 0}
    # Kein Ersatzwert am 29. Februar. Kontinuierliche Windphasen
    # werden beim fehlenden Kalendertag unterbrochen.
    if not usable:
        return season, [], []
    found, final = [], []
    prior_event = None
    for day in days(first, date(year + 1, 3, 31)):
        if day not in wind or day-DAY not in wind or wind[day] >= 0 or wind[day-DAY] < 0:
            continue
        if prior_event and not west_run(wind, prior_event+DAY, day-DAY, 20):
            continue
        prior_event = day
        recovery = west_run(wind, day+DAY, last, 10)
        run = 0
        while day + timedelta(days=run) <= last and wind.get(day+timedelta(days=run), 0) < 0:
            run += 1
        value = min(wind[k] for k in days(day, min(last,day+timedelta(days=29))) if k in wind)
        record = {"date": day.isoformat(), "year": year,
                  "winter": season["label"], "easterly_days": run,
                  "minimum_30d_ms": round(value,2), "return_west_10d": recovery}
        (found if recovery else final).append(record)
    season["events"] = len(found)
    season["final_excluded"] = len(final)
    return season, found, final


def build(source, today=None):
    today = today or datetime.now(timezone.utc).date()
    last_season = today.year if today.month >= 7 else today.year-1
    seasons, events, final = [], [], []
    latest = None
    for year in range(1978,last_season+1):
        filename = source/f"u60n_10_{year}_merra2.txt"
        wind = parse_nasa(filename.read_text(encoding="utf-8")) if filename.is_file() else {}
        recent = max((d for d in wind if d <= today),default=None)
        if recent and (latest is None or recent > latest):
            latest = recent
        row, yes, no = classify(year,wind,today)
        seasons.append(row)
        events.extend(yes)
        final.extend(no)
    completed = sum(s["status"]=="complete" for s in seasons)
    leap_years = sum(s["status"]=="leap_gap" for s in seasons)
    return {"schema_version":1,
            "generated_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source":"NASA Ozone Watch / MERRA-2: u(60N,10hPa) Tagesmittel",
            "method":"Charlton & Polvani 2007, windbasiert; November–März, 20 Westwindtage zwischen Ereignissen, 10 Westwindtage vor dem 30. April zur Abgrenzung der final warming",
            "analysis_through":latest.isoformat() if latest else None,
            "complete_seasons":completed,
            "leap_gap_seasons":leap_years,
            "evaluated_seasons":completed+leap_years,
            "incomplete_seasons":sum(s["status"]=="incomplete" for s in seasons),
            "event_count":len(events),
            "seasons":seasons,
            "events":sorted(events,key=lambda e:e["date"],reverse=True),
            "excluded_final_warmings":sorted(final,key=lambda e:e["date"],reverse=True)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    opts=parser.parse_args()
    result=build(opts.source)
    opts.output.parent.mkdir(parents=True,exist_ok=True)
    opts.output.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(f"SSW: {result['event_count']} Ereignisse, {result['complete_seasons']} vollständige Winter")


if __name__=="__main__":
    main()
