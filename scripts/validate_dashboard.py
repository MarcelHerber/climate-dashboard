from __future__ import annotations
import json,re,sys
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name):
    with (ROOT/name).open(encoding="utf-8") as handle:return json.load(handle)
def fail(message): raise RuntimeError(message)
def main():
    html=(ROOT/"index.html").read_text(encoding="utf-8")
    for path in ["css/dashboard.css","js/dashboard.js"]:
        if path not in html or not (ROOT/path).exists(): fail(f"Frontend-Datei fehlt oder ist nicht eingebunden: {path}")
    ids=re.findall(r'<canvas[^>]+id="([^"]+)"',html)
    if len(ids)!=len(set(ids)): fail("Doppelte Canvas-IDs im HTML")
    js=(ROOT/"js/dashboard.js").read_text(encoding="utf-8")
    missing=[canvas for canvas in ids if canvas not in js]
    if missing: fail("Canvas ohne JavaScript-Verwendung: "+", ".join(missing))
    monthly=load("data.json"); daily=load("daily_tmax_1881_2026.json")
    keys=[(item.get("area","Deutschland"),item["date"]) for item in monthly]
    if len(keys)!=len(set(keys)): fail("Doppelte Gebiet-Monat-Werte")
    dates=[date.fromisoformat(item["date"]) for item in daily]
    if dates!=sorted(dates) or len(dates)!=len(set(dates)): fail("Tagesdaten nicht eindeutig sortiert")
    for previous,current in zip(dates,dates[1:]):
        if current!=previous+timedelta(days=1): fail(f"Lücke in Tagesdaten: {previous} bis {current}")
    for item in daily:
        value=float(item["tmax"])
        if not -60<=value<=60: fail(f"Unplausible Tmax am {item['date']}: {value}")
        count=item.get("station_count")
        if count is not None and int(count)<1: fail(f"Ungültige Stationszahl am {item['date']}")
    for name in ["station_precip_index.json","station_climate_days_index.json","station_heatwaves_index.json"]:
        payload=load(name)
        if payload.get("ready"):
            stations=payload.get("stations") or []
            if len(stations)<100: fail(f"Zu wenige Stationen in {name}: {len(stations)}")
            coordinate_count=sum(1 for station in stations if station.get("latitude") is not None and station.get("longitude") is not None)
            if coordinate_count<len(stations)*.9: fail(f"Zu viele Stationen ohne Koordinaten in {name}")
    print(json.dumps({"ok":True,"monthly_records":len(monthly),"daily_records":len(daily),"canvas_count":len(ids)},ensure_ascii=False,indent=2))
if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"VALIDIERUNGSFEHLER: {exc}",file=sys.stderr);raise
