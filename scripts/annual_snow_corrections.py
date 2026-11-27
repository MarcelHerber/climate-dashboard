"""Dashboard-local snow-height correction; never modifies DWD source archives."""
from datetime import date

STATION = "01975"
DAYS = frozenset(date(2026, 1, n) for n in (10, 11, 12))
VALUE = 25.0
CORRECTION = {
    "station_id": STATION,
    "dates": [d.isoformat() for d in sorted(DAYS)],
    "value_cm": VALUE,
    "status": "manual_dashboard_estimate",
    "note": "Schneewehe am Sensor; 25 cm für Hamburg am 10.01.2026 laut DWD gegenüber NDR. Für den 11. und 12.01. auf Nutzerwunsch ebenfalls 25 cm angesetzt; keine amtlichen korrigierten Stations-Tagesmesswerte.",
    "source": "https://www.ndr.de/nachrichten/info/extrem-oder-halb-so-wild-antworten-zum-winterwetter-im-norden%2Cwinterwetter-158.html",
    "study": "https://doi.org/10.5676/DWD_PUB/ATTRIBUTION/2026_01"
}

def corrected_snow(station_id, day, value):
    if str(station_id).zfill(5) == STATION and day in DAYS:
        return VALUE
    return value
