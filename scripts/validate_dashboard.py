from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    with (ROOT / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> None:
    index_path = ROOT / "index.html"
    css_path = ROOT / "css" / "dashboard.css"
    js_path = ROOT / "js" / "dashboard.js"

    if not index_path.exists():
        fail("index.html fehlt.")

    html = index_path.read_text(encoding="utf-8")

    required_frontend = {
        "css/dashboard.css": css_path,
        "js/dashboard.js": js_path,
    }
    for reference, path in required_frontend.items():
        if reference not in html:
            fail(f"index.html bindet {reference} nicht ein.")
        if not path.exists():
            fail(f"Frontend-Datei fehlt: {reference}")

    js = js_path.read_text(encoding="utf-8")
    js_size = js_path.stat().st_size
    if js_size < 100_000:
        fail(
            "js/dashboard.js ist zu klein oder unvollständig "
            f"({js_size:,} Byte). Die vollständige Datei aus Version 12/12.1 hat rund 169.000 Byte. "
            "Bitte js/dashboard.js vollständig ersetzen."
        )

    canvas_ids = re.findall(r'<canvas\b[^>]*\bid=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    if len(canvas_ids) != len(set(canvas_ids)):
        duplicates = sorted({item for item in canvas_ids if canvas_ids.count(item) > 1})
        fail("Doppelte Canvas-IDs im HTML: " + ", ".join(duplicates))

    missing = [canvas_id for canvas_id in canvas_ids if canvas_id not in js]
    if missing:
        if len(missing) == len(canvas_ids):
            fail(
                "js/dashboard.js passt nicht zur index.html: Keine der Canvas-IDs wird in der "
                "JavaScript-Datei verwendet. Wahrscheinlich wurde eine ältere, leere oder falsch "
                "hochgeladene dashboard.js gespeichert. Bitte index.html, css/dashboard.css und "
                "js/dashboard.js gemeinsam aus dem Version-12.1-Paket ersetzen."
            )
        fail(
            "Diese Canvas-IDs aus index.html fehlen in js/dashboard.js: "
            + ", ".join(missing)
            + ". Bitte die Frontend-Dateien gemeinsam aus demselben Versionspaket ersetzen."
        )

    monthly = load("data.json")
    daily = load("daily_tmax_1881_2026.json")

    keys = [(item.get("area", "Deutschland"), item["date"]) for item in monthly]
    if len(keys) != len(set(keys)):
        fail("Doppelte Gebiet-Monat-Werte in data.json.")

    dates = [date.fromisoformat(item["date"]) for item in daily]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        fail("Tagesdaten sind nicht eindeutig chronologisch sortiert.")

    for previous, current in zip(dates, dates[1:]):
        if current != previous + timedelta(days=1):
            fail(f"Lücke in Tagesdaten: {previous} bis {current}")

    for item in daily:
        value = float(item["tmax"])
        if not -60 <= value <= 60:
            fail(f"Unplausible Tmax am {item['date']}: {value}")
        count = item.get("station_count")
        if count is not None and int(count) < 1:
            fail(f"Ungültige Stationszahl am {item['date']}")

    for name in [
        "station_precip_index.json",
        "station_climate_days_index.json",
        "station_heatwaves_index.json",
    ]:
        payload = load(name)
        if payload.get("ready"):
            stations = payload.get("stations") or []
            if len(stations) < 100:
                fail(f"Zu wenige Stationen in {name}: {len(stations)}")
            coordinate_count = sum(
                1
                for station in stations
                if station.get("latitude") is not None and station.get("longitude") is not None
            )
            if coordinate_count < len(stations) * 0.9:
                fail(f"Zu viele Stationen ohne Koordinaten in {name}")

    print(
        json.dumps(
            {
                "ok": True,
                "monthly_records": len(monthly),
                "daily_records": len(daily),
                "canvas_count": len(canvas_ids),
                "dashboard_js_bytes": js_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"VALIDIERUNGSFEHLER: {exc}", file=sys.stderr)
        raise
