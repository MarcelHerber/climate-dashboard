"""Conservative annual-extreme QC. Raw DWD archives are never changed.

Flag unusual values, exclude only explicit documented/strongly implausible cases.
QN codes describe processing, not a general valid/invalid switch.
"""
from datetime import date
from collections import defaultdict
from math import ceil

RULES_VERSION = 1
RULES = [
    dict(station_id="02552",field="RS",start="1903-01-01",end="1915-12-31",status="excluded",
         reason="Kellinghusen: 13 nearly or completely dry calendar years. Station-year archive quarantined; no replacement guessed.",
         evidence="Internal annual consistency audit; raw-station and neighbour evidence to be added."),
    dict(station_id="01006",field="TMK",start="1898-08-10",end="1898-08-10",status="excluded",expected=-14,
         reason="Dömitz: daily mean -14 °C in August at 15 m, physically implausible for this location; no replacement guessed."),
    dict(station_id="01975",field="SHK",start="2026-01-13",end="2026-01-14",status="excluded",
         reason="Continuation of documented sensor snow drift: 43/30 cm while Hamburg-Neuwiedenthal 3/0 cm; thaw. No replacement guessed.",
         evidence="https://www.wetterkontor.de/de/wetter/deutschland/extremwerte-hamburg.asp?id=20260113 ; https://www.wetterkontor.de/de/wetter/deutschland/extremwerte-hamburg.asp?id=20260114"),
    dict(station_id="05640",field="SHK",start="2004-11-17",end="2004-11-17",status="suspect",reason="134 cm at 7 m and +134 cm/24h; check original archive, QN and neighbours."),
    dict(station_id="01572",field="SHK",start="2002-01-03",end="2002-01-03",status="suspect",reason="99 cm at 80 m and +97 cm/24h; original/neighbor check required."),
    dict(station_id="01572",field="SHK",start="2004-01-30",end="2004-01-30",status="suspect",reason="101 cm at 80 m and +99 cm/24h; original/neighbor check required."),
    dict(station_id="01228",field="SHK",start="2015-07-20",end="2015-07-20",status="excluded",expected=11,
         reason="11 cm snow in July at sea level, offshore UFS TW Ems; not credible as a snow cover observation."),
]
_INDEX=defaultdict(list)
for rule in RULES:
    _INDEX[(rule["station_id"],rule["field"])].append(rule)

def matching_rule(sid,field,day,value=None):
    if (str(sid).zfill(5),field) not in _INDEX:return None
    iso=day.isoformat()
    for r in _INDEX[(str(sid).zfill(5),field)]:
        if r["start"]<=iso<=r["end"] and ("expected" not in r or value==r["expected"]):
            return r
    return None

def accepted_value(sid,field,day,value):
    r=matching_rule(sid,field,day,value)
    return None if r and r["status"]=="excluded" else value

def clean_temperature_fields(fields):
    """Do not decide which sensor is wrong if Tmin > Tmax; drop both.
    TMK is removed only for gross violations (> 2 K) of the measured range.
    Different reporting windows/old rounding can cause small inconsistencies."""
    lo=fields.get("TNK");hi=fields.get("TXK");avg=fields.get("TMK")
    if lo is not None and hi is not None and lo>hi:
        return {k:v for k,v in fields.items() if k not in ("TNK","TXK","TMK")}
    if avg is not None and ((lo is not None and avg<lo-2) or (hi is not None and avg>hi+2)):
        return {k:v for k,v in fields.items() if k!="TMK"}
    return fields

def valid_count(n,year,cut):
    end=min(cut,date(year,12,31))
    return n>=ceil(.9*((end-date(year,1,1)).days+1))

def quality_level(row,field):
    # QN_3: wind; QN_4: other KL; QN_6: RR; QN_9: hourly TU.
    # Preserve the numeric level for evidence, do not treat 5 as invalid.
    keys={"FX":("QN_3","QN"),"RS":("QN_6","QN"),"TT_TU":("QN_9","QN")}.get(field,("QN_4","QN"))
    for k in keys:
        try:
            q=int(row.get(k,"").strip())
            if q>=0:return q
        except (ValueError,AttributeError):pass
    return None
