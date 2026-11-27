#!/usr/bin/env python3
"""DWD-Tageskarte: Anomalien (5 Klimareferenzen), vier Rekordrichtungen, Messreihen-Filter.

Zeilenformat calendar/{mm-dd}.json.gz (Standardreferenz 1991-2020) - Index 0-13 sind
abwaertskompatibel zur bisherigen Version, neue Felder stehen hinten:

  0 station_index   1 tmax   2 tmin   3 tmax_anom   4 tmin_anom
  5 tmax_hi_status  6 tmin_lo_status (0 = kein Rekord, 1 = gebrochen, 2 = eingestellt)
  7 tmax_hi_record  8 tmin_lo_record
  9 tmax_ref_years 10 tmin_ref_years 11 tmean 12 tmean_anom 13 tmean_ref_years
 14 tmax_lo_record 15 tmin_hi_record 16 tmax_lo_status 17 tmin_hi_status
 18 tmax_obs_years 19 tmin_obs_years   (Jahre mit Messwert an genau diesem Kalendertag)

Weitere Referenzen: calendar_ref/{von_bis}/{mm-dd}.json.gz mit schlankeren Zeilen
  [station_index, tmax_anom, tmin_anom, tmean_anom, tmax_ref_years, tmin_ref_years, tmean_ref_years]
"""
from __future__ import annotations

import argparse, datetime as dt, functools, gzip, json, math, re, tempfile
from array import array
from pathlib import Path
from typing import Any, Mapping

# --------------------------------------------------------------------------- Referenzen
REFERENCES = ((1951, 1980), (1961, 1990), (1971, 2000), (1981, 2010), (1991, 2020))
DEFAULT_REFERENCE = (1991, 2020)


def ref_key(start: int, end: int) -> str:
    return f"{start}_{end}"


def ref_label(start: int, end: int) -> str:
    return f"{start}–{end}"


REFERENCE_BOUNDS = tuple((ref_key(a, b), a, b) for a, b in REFERENCES)
REFERENCE_START, REFERENCE_END = DEFAULT_REFERENCE
REFERENCE_KEY = ref_key(*DEFAULT_REFERENCE)
REFERENCE_LABEL = ref_label(*DEFAULT_REFERENCE)
MIN_REFERENCE_YEARS = 20          # Referenzjahre (Median im Glaettungsfenster) fuer ein Klimamittel
SMOOTHING_HALF_WINDOW = 7         # Klimamittel: +-7 Tage um den Kalendertag (0 = ungeglaettet)

# --------------------------------------------------------------------------- Rekorde / Messreihen
# Basis-Mindestlaenge: Rekordstatus wird nur fuer Kalendertage mit mindestens so vielen
# Messjahren vergeben. Das Frontend kann ueber die Zaehler (Feld 18/19) weiter verschaerfen.
RECORD_YEAR_OPTIONS = (30, 50, 75, 100)
MIN_RECORD_YEARS = RECORD_YEAR_OPTIONS[0]
LEAP_DAY_DIVISOR = 4              # 29.02. gibt es nur in jedem 4. Jahr -> Mindestjahre / 4 (aufgerundet)
# (Name, Element, Tabelle im Baseline-Cache, "hoeher ist Rekord")
RECORD_DIRECTIONS = (
    ("tmax_hi", "TMAX", "cal", True),      # waermster Tag
    ("tmin_lo", "TMIN", "cal", False),     # kaelteste Nacht
    ("tmax_lo", "TMAX", "cal_lo", False),  # kaeltester Tag
    ("tmin_hi", "TMIN", "cal_hi", True),   # waermste Nacht
)

CACHE_VERSION = 5
PAYLOAD_VERSION = 2

STATES = ("Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg", "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen", "Rheinland-Pfalz", "Saarland", "Sachsen", "Sachsen-Anhalt", "Schleswig-Holstein", "Thüringen")
MIN_ANNUAL_VALID_DAYS = 300
CLIMATE_DAY_DEFS = {
    "summer_days": {"label": "Sommertage", "definition": "Tmax ≥ 25,0 °C", "element": "TMAX", "op": "ge", "threshold": 250},
    "hot_days": {"label": "Hitzetage", "definition": "Tmax ≥ 30,0 °C", "element": "TMAX", "op": "ge", "threshold": 300},
    "very_hot_days": {"label": "Sehr heiße Tage", "definition": "Tmax ≥ 35,0 °C", "element": "TMAX", "op": "ge", "threshold": 350},
    "tropical_nights": {"label": "Tropennächte", "definition": "Tmin ≥ 20,0 °C", "element": "TMIN", "op": "ge", "threshold": 200},
    "frost_days": {"label": "Frosttage", "definition": "Tmin < 0,0 °C", "element": "TMIN", "op": "lt", "threshold": 0},
    "ice_days": {"label": "Eistage", "definition": "Tmax < 0,0 °C", "element": "TMAX", "op": "lt", "threshold": 0},
}

ROW_FIELDS = ["station_index", "tmax", "tmin", "tmax_anom", "tmin_anom", "tmax_hi_status", "tmin_lo_status",
              "tmax_hi_record", "tmin_lo_record", "tmax_ref_years", "tmin_ref_years", "tmean", "tmean_anom",
              "tmean_ref_years", "tmax_lo_record", "tmin_hi_record", "tmax_lo_status", "tmin_hi_status",
              "tmax_obs_years", "tmin_obs_years"]
REF_ROW_FIELDS = ["station_index", "tmax_anom", "tmin_anom", "tmean_anom", "tmax_ref_years", "tmin_ref_years", "tmean_ref_years"]

# 366-Tage-Zyklus inkl. 29.02.: Index in den Climatology-Arrays, Fenster laufen ueber Jahreswechsel und Schalttag.
_CYCLE = [(dt.date(2000, 1, 1) + dt.timedelta(days=i)).strftime("%m-%d") for i in range(366)]
_CYCLE_POS = {m: i for i, m in enumerate(_CYCLE)}


@functools.lru_cache(maxsize=None)
def _window(pos: int, half: int) -> tuple:
    return tuple((pos + off) % 366 for off in range(-half, half + 1))


def climate_day_hit(definition: Mapping[str, Any], value: int | None) -> bool:
    if value is None:
        return False
    threshold = int(definition["threshold"])
    return int(value) >= threshold if definition["op"] == "ge" else int(value) < threshold


# --------------------------------------------------------------------------- Baseline-Bausteine (vom Parser genutzt)
def add_climatology_value(block: dict, mmdd: str, value: int, year: int) -> None:
    """Addiert einen Tageswert zu allen Referenzperioden, in die `year` faellt.
    Speicherform: block["clim"][ref_key] = [summen(array), anzahlen(array)] ueber 366 Kalendertage."""
    pos = _CYCLE_POS.get(mmdd)
    if pos is None:
        return
    clim = block.setdefault("clim", {})
    for key, start, end in REFERENCE_BOUNDS:
        if start <= year <= end:
            arrays = clim.get(key)
            if arrays is None:
                arrays = clim[key] = [array("i", [0]) * 366, array("i", [0]) * 366]
            arrays[0][pos] += int(value)
            arrays[1][pos] += 1


def add_observation_count(block: dict, mmdd: str) -> None:
    """Zaehlt die Jahre mit gueltigem Messwert an genau diesem Kalendertag."""
    pos = _CYCLE_POS.get(mmdd)
    if pos is None:
        return
    counts = block.get("n")
    if counts is None:
        counts = block["n"] = array("H", [0]) * 366
    counts[pos] += 1


def update_extreme(table: dict, mmdd: str, value: int, date_int: int, higher: bool) -> None:
    """Pflegt (wert, datum, anzahl_gleicher_werte) je Kalendertag; higher=True -> Maximum, sonst Minimum."""
    old = table.get(mmdd)
    if old is None or (value > old[0] if higher else value < old[0]):
        table[mmdd] = (int(value), int(date_int), 1)
    elif value == old[0]:
        table[mmdd] = (old[0], old[1], old[2] + 1)


def clim_raw(block: Mapping[str, Any], key: str, mmdd: str):
    arrays = (block.get("clim") or {}).get(key)
    pos = _CYCLE_POS.get(mmdd)
    if not arrays or pos is None:
        return 0, 0
    return int(arrays[0][pos]), int(arrays[1][pos])


# --------------------------------------------------------------------------- Klimamittel
def smoothed_normal_tenths(block: Mapping[str, Any], mmdd: str, key: str = REFERENCE_KEY,
                           half_window: int = SMOOTHING_HALF_WINDOW):
    """Klimamittel eines Kalendertags (Zehntel Grad) und Referenzjahre.

    Gepoolt ueber das Fenster +-half_window Tage (Summe aller Werte / Anzahl aller Werte);
    der 29.02. ist im Zyklus enthalten. Referenzjahre = Median der Tageszaehler im Fenster. Der Zaehler
    eines Einzeltags ist exakt die Zahl der Jahre mit Wert an diesem Tag; der Median ueber das Fenster
    ist dagegen nur ein Naeherungsmass fuer die Abdeckung der Referenzperiode.
    half_window=0 -> ungeglaettetes Kalendertagsmittel."""
    pos = _CYCLE_POS.get(mmdd)
    arrays = (block.get("clim") or {}).get(key)
    if pos is None or not arrays:
        return None, 0
    sums, counts = arrays
    if half_window <= 0:
        c = int(counts[pos])
        return (int(round(sums[pos] / c)), c) if c >= MIN_REFERENCE_YEARS else (None, c)
    total = count = 0
    seen = []
    for i in _window(pos, half_window):
        c = counts[i]
        if c > 0:
            total += sums[i]; count += c; seen.append(c)
    if len(seen) < half_window + 1:
        return None, 0
    seen.sort()
    years = int(seen[len(seen) // 2])
    return (int(round(total / count)), years) if years >= MIN_REFERENCE_YEARS else (None, years)


def climate_normal_tenths(block: Mapping[str, Any], mmdd: str, key: str = REFERENCE_KEY):
    """Ungeglaettetes Kalendertagsmittel (Altverhalten)."""
    return smoothed_normal_tenths(block, mmdd, key, 0)


# --------------------------------------------------------------------------- Rekorde
def record_status_dir(current, record, higher: bool) -> int:
    if current is None or not record:
        return 0
    previous = int(record[0])
    if current == previous:
        return 2
    return 1 if (current > previous if higher else current < previous) else 0


def record_status(element, current, record):
    """Kompatibilitaet: TMAX -> Maximum-Rekord, TMIN -> Minimum-Rekord."""
    return record_status_dir(current, record, element == "TMAX")


def required_record_years(mmdd: str, min_years: int) -> int:
    """Mindestzahl an Messjahren eines Kalendertags. Der 29.02. hat nur etwa jedes vierte Jahr einen Wert,
    deshalb gilt dort min_years/4 (aufgerundet): 30->8, 50->13, 75->19, 100->25."""
    if mmdd == "02-29":
        return (int(min_years) + LEAP_DAY_DIVISOR - 1) // LEAP_DAY_DIVISOR
    return int(min_years)


def observed_years(block: Mapping[str, Any], mmdd: str) -> int:
    counts = block.get("n")
    pos = _CYCLE_POS.get(mmdd)
    return int(counts[pos]) if counts is not None and pos is not None else 0


# --------------------------------------------------------------------------- Hilfen
def parse_dwd_state_names(text: str):
    out = {}
    for raw in text.splitlines():
        m = re.match(r"^\s*(\d{1,5})\s+\d{8}\s+\d{8}\s+-?\d+(?:[.,]\d+)?\s+-?\d+(?:[.,]\d+)?\s+-?\d+(?:[.,]\d+)?\s+(.+?)\s*$", raw)
        if not m:
            continue
        tail = m.group(2)
        for state in sorted(STATES, key=len, reverse=True):
            if re.search(rf"(?:^|\s){re.escape(state)}(?:\s|$)", tail):
                out[f"DWD:{m.group(1).zfill(5)}"] = state
                break
    return out


def _finite(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _gzip_json(path, payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=7, mtime=0) as gz:
            gz.write(raw)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


def _current(state, element, mmdd):
    raw = (state.get(element) or {}).get(mmdd)
    if not raw:
        return None, None
    return int(raw[0]), int(raw[1])


def _rv(record):
    return int(record[0]) if record else None


def _dates(current, year):
    out = set()
    for state in current.values():
        for element in ("TMAX", "TMIN", "TMEAN"):
            for raw in (state.get(element) or {}).values():
                if raw:
                    d = int(raw[1])
                    if d // 10000 == year:
                        s = f"{d:08d}"
                        out.add(f"{s[:4]}-{s[4:6]}-{s[6:]}")
    return sorted(out)


def _current_climate_day(state: Mapping[str, Any], key: str, year: int):
    definition = CLIMATE_DAY_DEFS[key]
    element = definition["element"]
    values = []
    for raw in (state.get(element) or {}).values():
        if not raw:
            continue
        value, date_int = int(raw[0]), int(raw[1])
        if date_int // 10000 == year:
            values.append((value, date_int))
    if not values:
        return None, 0, None
    count = sum(1 for value, _ in values if climate_day_hit(definition, value))
    last = max(date_int for _, date_int in values)
    s = f"{last:08d}"
    return count, len(values), f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _climate_payload(ids, pos, current, hist_states, current_year: int, data_through: str | None):
    metrics = {}
    for key, definition in CLIMATE_DAY_DEFS.items():
        rows = []
        for sid in ids:
            count, valid_days, last_date = _current_climate_day(current[sid], key, current_year)
            record = ((hist_states.get(sid) or {}).get("CLIMATE_DAYS") or {}).get(key) or {}
            record_count = record.get("record")
            if count is None or record_count is None:
                continue
            record_count = int(record_count)
            rows.append([pos[sid], int(count), record_count, int(count) - record_count, list(record.get("years") or []), int(valid_days), last_date])
        metrics[key] = {"label": definition["label"], "definition": definition["definition"], "rows": rows}
    return {"version": 1, "year": current_year, "data_through": data_through, "minimum_historical_valid_days": MIN_ANNUAL_VALID_DAYS, "fields": ["station_index", "current_count", "historical_record", "difference", "record_years", "current_valid_days", "last_observation"], "metrics": metrics}


def _anomaly(value, block, mmdd, key):
    normal, years = smoothed_normal_tenths(block, mmdd, key)
    return (value - normal if value is not None and normal is not None else None), years


# --------------------------------------------------------------------------- Ausgabe
def write_daily_map(output_dir: Path, *, stations, baseline, current, current_year: int, station_listing_text: str = "", generated_at: str | None = None):
    output_dir = Path(output_dir)
    caldir = output_dir / "calendar"
    refdir = output_dir / "calendar_ref"
    caldir.mkdir(parents=True, exist_ok=True)
    state_names = parse_dwd_state_names(station_listing_text)
    hist_states = baseline.get("states") or {}
    dates = _dates(current, current_year)
    ids = sorted((sid for sid in current if sid in stations and (current[sid].get("TMAX") or current[sid].get("TMIN") or current[sid].get("TMEAN"))), key=lambda sid: (str(getattr(stations[sid], "name", "")).casefold(), sid))
    pos = {sid: i for i, sid in enumerate(ids)}
    blocks = {sid: ((hist_states.get(sid) or {}).get("TMAX") or {}, (hist_states.get(sid) or {}).get("TMIN") or {}, (hist_states.get(sid) or {}).get("TMEAN") or {}) for sid in ids}
    station_rows = []
    for sid in ids:
        m = stations[sid]
        raw = sid.rsplit(":", 1)[-1]
        station_rows.append([sid, re.sub(r"\D", "", raw).zfill(5), getattr(m, "name", sid), _finite(getattr(m, "lat", None)), _finite(getattr(m, "lon", None)), _finite(getattr(m, "elev", None)), state_names.get(sid, "")])

    other_refs = [(k, a, b) for k, a, b in REFERENCE_BOUNDS if k != REFERENCE_KEY]
    day_counts, anom_counts, rec_counts, rec_by_min = {}, {}, {}, {}
    ref_anom_counts = {k: {} for k, _, _ in other_refs}

    for iso in dates:
        date = dt.date.fromisoformat(iso)
        mmdd = date.strftime("%m-%d")
        dateint = int(date.strftime("%Y%m%d"))
        obs = []
        for sid in ids:
            cur = current[sid]
            tx, txd = _current(cur, "TMAX", mmdd)
            tn, tnd = _current(cur, "TMIN", mmdd)
            tm, tmd = _current(cur, "TMEAN", mmdd)
            if tx is None and tn is None and tm is None:
                continue
            if any(v != dateint for v in (txd, tnd, tmd) if v is not None):
                continue
            obs.append((sid, tx, tn, tm))

        # --- Standardreferenz + vier Rekordrichtungen
        rows, anoms = [], 0
        by_min = {n: 0 for n in RECORD_YEAR_OPTIONS}
        base_req = required_record_years(mmdd, MIN_RECORD_YEARS)
        for sid, tx, tn, tm in obs:
            hx, hn, hm = blocks[sid]
            txa, txc = _anomaly(tx, hx, mmdd, REFERENCE_KEY)
            tna, tnc = _anomaly(tn, hn, mmdd, REFERENCE_KEY)
            tma, tmc = _anomaly(tm, hm, mmdd, REFERENCE_KEY)
            if txa is not None or tna is not None or tma is not None:
                anoms += 1
            r_txh = (hx.get("cal") or {}).get(mmdd)
            r_txl = (hx.get("cal_lo") or {}).get(mmdd)
            r_tnl = (hn.get("cal") or {}).get(mmdd)
            r_tnh = (hn.get("cal_hi") or {}).get(mmdd)
            ntx, ntn = observed_years(hx, mmdd), observed_years(hn, mmdd)
            ok_x, ok_n = ntx >= base_req, ntn >= base_req
            s_txh = record_status_dir(tx, r_txh, True) if ok_x else 0
            s_txl = record_status_dir(tx, r_txl, False) if ok_x else 0
            s_tnl = record_status_dir(tn, r_tnl, False) if ok_n else 0
            s_tnh = record_status_dir(tn, r_tnh, True) if ok_n else 0
            any_x, any_n = bool(s_txh or s_txl), bool(s_tnl or s_tnh)
            if any_x or any_n:
                for n in RECORD_YEAR_OPTIONS:
                    need = required_record_years(mmdd, n)
                    if (any_x and ntx >= need) or (any_n and ntn >= need):
                        by_min[n] += 1
            rows.append([pos[sid], tx, tn, txa, tna, s_txh, s_tnl, _rv(r_txh), _rv(r_tnl), txc, tnc, tm, tma, tmc,
                         _rv(r_txl), _rv(r_tnh), s_txl, s_tnh, ntx, ntn])
        _gzip_json(caldir / f"{mmdd}.json.gz", {"version": PAYLOAD_VERSION, "date": iso, "reference_period": REFERENCE_LABEL, "rows": rows})
        day_counts[iso], anom_counts[iso] = len(rows), anoms
        rec_by_min[iso] = by_min
        rec_counts[iso] = by_min[MIN_RECORD_YEARS]

        # --- weitere Referenzperioden: nur Anomalien, schlanke Zeilen
        for key, a, b in other_refs:
            rrows = []
            for sid, tx, tn, tm in obs:
                hx, hn, hm = blocks[sid]
                txa, txc = _anomaly(tx, hx, mmdd, key)
                tna, tnc = _anomaly(tn, hn, mmdd, key)
                tma, tmc = _anomaly(tm, hm, mmdd, key)
                if txa is None and tna is None and tma is None:
                    continue
                rrows.append([pos[sid], txa, tna, tma, txc, tnc, tmc])
            _gzip_json(refdir / key / f"{mmdd}.json.gz", {"version": PAYLOAD_VERSION, "date": iso, "reference_period": ref_label(a, b), "rows": rrows})
            ref_anom_counts[key][iso] = len(rrows)

    keep = {dt.date.fromisoformat(v).strftime("%m-%d") + ".json.gz" for v in dates}
    for p in list(caldir.glob("*.json.gz")) + list(refdir.glob("*/*.json.gz")):
        if p.name not in keep:
            p.unlink()
    through = dates[-1] if dates else None
    _write_json(output_dir / "climate_days.json", _climate_payload(ids, pos, current, hist_states, current_year, through))
    references = [{"key": k, "label": ref_label(a, b), "start": a, "end": b, "default": k == REFERENCE_KEY,
                   "pattern": "calendar/{mm-dd}.json.gz" if k == REFERENCE_KEY else f"calendar_ref/{k}/{{mm-dd}}.json.gz"} for k, a, b in REFERENCE_BOUNDS]
    index = {
        "version": PAYLOAD_VERSION, "ready": bool(dates and station_rows),
        "generated_at": generated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "year": current_year, "reference_period": REFERENCE_LABEL, "reference_start_year": REFERENCE_START, "reference_end_year": REFERENCE_END,
        "minimum_reference_years": MIN_REFERENCE_YEARS, "smoothing_half_window_days": SMOOTHING_HALF_WINDOW,
        "default_reference": REFERENCE_KEY, "references": references,
        "station_fields": ["id", "dwd_id", "name", "lat", "lon", "height_m", "state"], "stations": station_rows, "station_count": len(station_rows),
        "dates": dates, "date_count": len(dates), "data_through": through,
        "latest_station_count": day_counts.get(through, 0) if through else 0,
        "latest_anomaly_count": anom_counts.get(through, 0) if through else 0,
        "latest_record_count": rec_counts.get(through, 0) if through else 0,
        "latest_record_counts_by_min_years": {str(n): c for n, c in (rec_by_min.get(through) or {}).items()} if through else {},
        "latest_anomaly_count_by_reference": {k: v.get(through, 0) for k, v in ref_anom_counts.items()} if through else {},
        "record_min_years": MIN_RECORD_YEARS, "record_min_years_options": list(RECORD_YEAR_OPTIONS), "leap_day_divisor": LEAP_DAY_DIVISOR,
        "record_directions": [{"key": k, "element": e, "higher_is_record": h} for k, e, _, h in RECORD_DIRECTIONS],
        "row_fields": ROW_FIELDS, "reference_row_fields": REF_ROW_FIELDS,
        "calendar_pattern": "calendar/{mm-dd}.json.gz", "climate_days_file": "climate_days.json", "climate_day_minimum_historical_valid_days": MIN_ANNUAL_VALID_DAYS,
        "source": "DWD Climate Data Center (CDC), Tageswerte KL, TXK/TNK/TMK",
        "note": ("Stationsabweichungen von Tmax, Tmin und Tmean (TMK) vom Klimamittel des gewählten Referenzzeitraums "
                 "(Kalendertag, geglättet über ±7 Tage, inkl. 29. Februar); Ausgabe ab 20 Referenzjahren (Median im Fenster). "
                 "Rekordflags beziehen sich auf den exakten Kalendertag in vier Richtungen (Tmax/Tmin jeweils Maximum und Minimum), "
                 "vergleichen mit der historischen Reihe bis zum Vorjahr und werden nur bei mindestens 30 Messjahren an diesem Kalendertag vergeben "
                 "(29. Februar: ein Viertel davon)."),
    }
    _write_json(output_dir / "index.json", index)
    return index


# --------------------------------------------------------------------------- Selbsttest
def _flat_block(mean_tenths, years: int = 20, leap_years: int = 8, means: Mapping[str, int] | None = None) -> dict:
    """Testblock: je Referenz konstantes Klimamittel ueber alle 366 Tage."""
    clim = {}
    for key, _, _ in REFERENCE_BOUNDS:
        mean = (means or {}).get(key, mean_tenths)
        counts = array("i", [leap_years if m == "02-29" else years for m in _CYCLE])
        clim[key] = [array("i", [mean * c for c in counts]), counts]
    return {"clim": clim}


def self_test():
    # --- Referenzzuordnung nach Jahr
    block = {}
    for year, value in ((1955, 100), (1995, 200), (2005, 300), (2024, 999)):
        add_climatology_value(block, "08-28", value, year)
    assert clim_raw(block, "1951_1980", "08-28") == (100, 1)
    assert clim_raw(block, "1991_2020", "08-28") == (500, 2)      # 1995 + 2005
    assert clim_raw(block, "1981_2010", "08-28") == (500, 2)
    assert clim_raw(block, "1971_2000", "08-28") == (200, 1)      # nur 1995
    assert clim_raw(block, "1961_1990", "08-28") == (0, 0)
    add_climatology_value(block, "13-40", 1, 1995)               # ungueltiger Tag wird ignoriert
    assert clim_raw(block, "1991_2020", "13-40") == (0, 0)

    # --- Glaettung: Jahreswechsel, Schalttag, Fensterrand
    flat = _flat_block(100)
    for m in ("01-01", "12-31", "02-29", "02-28", "03-01", "08-28"):
        n, y = smoothed_normal_tenths(flat, m)
        assert n == 100 and y >= MIN_REFERENCE_YEARS, (m, n, y)
    assert climate_normal_tenths(flat, "02-29")[0] is None       # ungeglaettet scheitert der 29.02. an 8 Schaltjahren
    lin = {"clim": {REFERENCE_KEY: [array("i", [10 * i * 20 for i in range(366)]), array("i", [20] * 366)]}}
    assert smoothed_normal_tenths(lin, "06-15")[0] == 10 * _CYCLE_POS["06-15"]
    sparse = {"clim": {REFERENCE_KEY: [array("i", [0] * 366), array("i", [0] * 366)]}}
    sparse["clim"][REFERENCE_KEY][0][_CYCLE_POS["08-28"]] = 4000
    sparse["clim"][REFERENCE_KEY][1][_CYCLE_POS["08-28"]] = 20
    assert smoothed_normal_tenths(sparse, "08-28")[0] is None    # zu wenige Datentage im Fenster
    assert smoothed_normal_tenths(sparse, "08-28", REFERENCE_KEY, 0) == (200, 20)
    assert smoothed_normal_tenths(flat, "13-40") == (None, 0)
    assert smoothed_normal_tenths(flat, "08-28", "1951_1980")[0] == 100
    assert smoothed_normal_tenths({}, "08-28") == (None, 0)

    # --- vier Rekordrichtungen
    assert record_status_dir(301, (300, 0, 1), True) == 1 and record_status_dir(300, (300, 0, 1), True) == 2 and record_status_dir(299, (300, 0, 1), True) == 0
    assert record_status_dir(99, (100, 0, 1), False) == 1 and record_status_dir(100, (100, 0, 1), False) == 2 and record_status_dir(101, (100, 0, 1), False) == 0
    assert record_status_dir(None, (1, 0, 1), True) == 0 and record_status_dir(5, None, True) == 0
    assert record_status("TMAX", 301, (300, 20200828, 1)) == 1 and record_status("TMIN", -20, (-20, 19930828, 1)) == 2
    table = {}
    for v, d in ((120, 19910828), (80, 19920828), (80, 20000828), (100, 19950828)):
        update_extreme(table, "08-28", v, d, False)
    assert table["08-28"] == (80, 19920828, 2)

    # --- Messreihen-Filter inkl. Schalttag
    assert [required_record_years("08-28", n) for n in RECORD_YEAR_OPTIONS] == [30, 50, 75, 100]
    assert [required_record_years("02-29", n) for n in RECORD_YEAR_OPTIONS] == [8, 13, 19, 25]
    counts = {}
    for _ in range(3):
        add_observation_count(counts, "02-29")
    assert observed_years(counts, "02-29") == 3 and observed_years(counts, "08-28") == 0 and observed_years({}, "08-28") == 0

    # --- Ende-zu-Ende
    class M:
        name = "Test"; lat = 50.; lon = 8.; elev = 100.

    def n_arr(years: int, leap: int | None = None):
        return array("H", [(leap if (m == "02-29" and leap is not None) else years) for m in _CYCLE])

    means_tx = {"1991_2020": 200, "1961_1990": 180}
    long_station = {
        "TMAX": {**_flat_block(200, means=means_tx), "n": n_arr(40, 10),
                 "cal": {"08-28": (300, 20200828, 1), "08-29": (300, 20200829, 1), "02-29": (250, 20200229, 1)},
                 "cal_lo": {"08-28": (-50, 19800828, 1), "08-29": (150, 19800829, 1), "02-29": (-30, 19600229, 1)}},
        "TMIN": {**_flat_block(100), "n": n_arr(40, 10),
                 "cal": {"08-28": (50, 19930828, 1), "08-29": (50, 19930829, 1), "02-29": (-90, 19560229, 1)},
                 "cal_hi": {"08-28": (180, 20030828, 1), "08-29": (180, 20030829, 1), "02-29": (60, 20200229, 1)}},
        "TMEAN": _flat_block(150),
        "CLIMATE_DAYS": {"summer_days": {"record": 1, "years": [2003]}, "hot_days": {"record": 1, "years": [2003]}, "very_hot_days": {"record": 0, "years": [2003]},
                         "tropical_nights": {"record": 0, "years": [2003]}, "frost_days": {"record": 20, "years": [1985]}, "ice_days": {"record": 8, "years": [1985]}},
    }
    short_station = {
        "TMAX": {**_flat_block(200), "n": n_arr(10), "cal": {"08-28": (300, 20200828, 1)}, "cal_lo": {"08-28": (-50, 19800828, 1)}},
        "TMIN": {**_flat_block(100), "n": n_arr(10), "cal": {"08-28": (50, 19930828, 1)}, "cal_hi": {"08-28": (180, 20030828, 1)}},
        "TMEAN": _flat_block(150),
    }
    cur = {
        "DWD:00001": {"TMAX": {"08-28": (310, 20260828), "08-29": (140, 20260829)}, "TMIN": {"08-28": (90, 20260828), "08-29": (190, 20260829)}, "TMEAN": {"08-28": (200, 20260828), "08-29": (150, 20260829)}},
        "DWD:00002": {"TMAX": {"08-28": (310, 20260828)}, "TMIN": {"08-28": (40, 20260828)}, "TMEAN": {"08-28": (200, 20260828)}},
    }
    with tempfile.TemporaryDirectory() as tmp:
        idx = write_daily_map(Path(tmp), stations={"DWD:00001": M(), "DWD:00002": M()}, baseline={"states": {"DWD:00001": long_station, "DWD:00002": short_station}},
                              current=cur, current_year=2026, station_listing_text="00001 19900101 20261231 100 50.0 8.0 Test Hessen")

        def load(path):
            with gzip.open(Path(tmp) / path, "rt", encoding="utf-8") as f:
                return json.load(f)["rows"]

        r0828 = {r[0]: r for r in load("calendar/08-28.json.gz")}
        assert len(r0828[0]) == len(ROW_FIELDS)
        a = r0828[0]                                                  # langer Standort: 310 > 300 -> neuer Tmax-Rekord
        assert a[3:7] == [110, -10, 1, 0] and a[7:9] == [300, 50] and a[11:14] == [200, 50, 20]
        assert a[14:20] == [-50, 180, 0, 0, 40, 40]                   # Tmax_lo, Tmin_hi, Status, Messjahre
        b = r0828[1]                                                  # kurze Reihe (10 Jahre): kein Rekordstatus, Werte bleiben sichtbar
        assert b[5] == 0 and b[6] == 0 and b[16] == 0 and b[17] == 0 and b[7] == 300 and b[18] == 10
        r0829 = load("calendar/08-29.json.gz")[0]
        assert r0829[16] == 1 and r0829[17] == 1 and r0829[5] == 0 and r0829[6] == 0   # kaeltester Tag + waermste Nacht
        assert idx["latest_record_count"] == 1 and idx["data_through"] == "2026-08-29"
        assert idx["latest_record_counts_by_min_years"] == {"30": 1, "50": 0, "75": 0, "100": 0}   # 08-29: 40 Jahre
        assert idx["latest_station_count"] == 1                       # am 29.08. hat nur Station 1 Werte
        # weitere Referenz: 1961-1990 hat fuer Tmax das Mittel 180 -> Anomalie 130
        ref = {r[0]: r for r in load("calendar_ref/1961_1990/08-28.json.gz")}
        assert ref[0][1:4] == [130, -10, 50] and ref[0][4] >= MIN_REFERENCE_YEARS
        assert len(ref[0]) == len(REF_ROW_FIELDS)
        assert idx["latest_anomaly_count_by_reference"]["1951_1980"] == 1
        assert {x["key"] for x in idx["references"]} == {k for k, _, _ in REFERENCE_BOUNDS} and idx["default_reference"] == "1991_2020"
        climate = json.loads((Path(tmp) / "climate_days.json").read_text(encoding="utf-8"))
        summer = climate["metrics"]["summer_days"]["rows"]
        assert len(summer) == 1 and summer[0][1:4] == [1, 1, 0] and summer[0][4] == [2003] and summer[0][5] == 2

    # --- Schalttag im Schaltjahr 2028: 10 Messjahre am 29.02. sind bei Filter 30 (-> 8) berechtigt, bei 50 (-> 13) nicht
    leap_cur = {"DWD:00001": {"TMAX": {"02-29": (260, 20280229)}, "TMIN": {"02-29": (-100, 20280229)}, "TMEAN": {"02-29": (0, 20280229)}}}
    with tempfile.TemporaryDirectory() as tmp:
        idx = write_daily_map(Path(tmp), stations={"DWD:00001": M()}, baseline={"states": {"DWD:00001": long_station}}, current=leap_cur, current_year=2028)
        with gzip.open(Path(tmp) / "calendar" / "02-29.json.gz", "rt", encoding="utf-8") as f:
            row = json.load(f)["rows"][0]
        assert row[3] == 60 and row[9] >= MIN_REFERENCE_YEARS          # Anomalie am 29.02. wird berechnet (vorher: None)
        assert row[5] == 1 and row[6] == 1 and row[18] == 10 and row[19] == 10   # Tmax-Rekord (260>250) und Tmin-Rekord (-100<-90)
        assert idx["latest_record_counts_by_min_years"] == {"30": 1, "50": 0, "75": 0, "100": 0}
    print("dwd_daily_map.py self-test OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
