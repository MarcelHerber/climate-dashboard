"""Fetch and validate the DWD GWL-REA v1.6 catalogue without gap filling."""
import csv
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlopen, Request

URL = "https://opendata.dwd.de/climate_environment/CDC/event_catalogues/europe/weather_types/GWL-REA/v1.6/historical/GWL-REA_v1.6_ERA5_GLP_catalogue.csv"
OUT = Path("data/grosswetterlagen/rea.csv")

def parse(text):
    result = {}
    for i, row in enumerate(csv.reader(text.splitlines(), delimiter=";")):
        if not row or not row[0].strip() or row[0].startswith("#"):
            continue
        try:
            day = date.fromisoformat(row[0].strip())
        except ValueError:
            if i == 0 or row[0].strip().lower() in ("datum", "date"):
                continue
            raise
        if len(row) < 3:
            raise ValueError(f"Malformed row {i+1}")
        code = row[2].strip().upper()
        if day in result or not code or not code.isascii() or not all(c.isalnum() or c in "_-" for c in code):
            raise ValueError(f"Invalid or duplicate row {i+1}")
        result[day] = (int(row[1]), code)
    days = sorted(result)
    if not days or days[0] != date(1940, 1, 1) or len(days) != (days[-1] - days[0]).days + 1:
        raise ValueError("Unexpected coverage or date gaps")
    if days[-1] < date(2026, 6, 30) or days[-1] > date.today():
        raise ValueError("Unexpected end date")
    if len(set(result.values())) != 30 or len({v[0] for v in result.values()}) != 30 or len({v[1] for v in result.values()}) != 30:
        raise ValueError("Expected 30 distinct weather types")
    return days, result

def main():
    with urlopen(Request(URL, headers={"User-Agent":"Climate Dashboard Deutschland"}), timeout=90) as response:
        raw = response.read(5_000_000)
    days, result = parse(raw.decode("utf-8-sig"))
    if OUT.exists():
        old, _ = parse(OUT.read_text(encoding="utf-8"))
        if days[-1] < old[-1]:
            raise ValueError("Refusing catalogue regression")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(("Datum","GWL Nummer","GWL Abkuerzung"))
        writer.writerows((d.isoformat(), *result[d]) for d in days)
    tmp.replace(OUT)
    print(f"Validated {len(days)} days: {days[0]} to {days[-1]}")

if __name__ == "__main__":
    main()
