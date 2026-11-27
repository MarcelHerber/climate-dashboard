#!/usr/bin/env python3
"""Quellenneutrale Klima-Engine für den Europa-Anomalie- und Rekordmonitor.

Eine Station wird als `eng` geführt: je Element (TMAX, TMIN, TMEAN) ein Block.
Jeder Tageswert läuft genau einmal durch `add_day()`. Daraus entstehen

* Klimamittel für fünf Referenzperioden (Summen/Anzahlen je Kalendertag, 366-Tage-Zyklus inkl. 29.02.),
* Gültigkeitsmasken je Jahr (für die Mindestabdeckungsregel),
* Messjahre je Kalendertag (`n`),
* Rekorde je Kalendertag in vier Richtungen (Tmax hoch/tief, Tmin hoch/tief).

Regeln (Vorgabe):
* Klimamittel = Mittel aller gültigen Werte der Referenzperiode im Fenster ±7 Tage (gepoolt).
* Ein Klimamittel gilt nur, wenn mindestens 20 verschiedene Referenzjahre im 15-Tage-Fenster
  mindestens 80 % gültige Tage haben (12 von 15).
* Rekorde gelten nur für den exakten Kalendertag und nur ab N tatsächlichen Messjahren an diesem Tag
  (29.02.: ein Viertel davon).
* Tmean ist einheitlich (Tmax+Tmin)/2 und zählt nur an Tagen, an denen beide Werte vorliegen.
  Er wird in verdoppelten Zehntelgrad geführt (tx+tn), damit keine Rundung vorweggenommen wird.

Einheiten: Tmax/Tmin in Zehntelgrad (int), Tmean in verdoppelten Zehntelgrad.
Nur Standardbibliothek.
"""
from __future__ import annotations

import datetime as dt
import math
from array import array
from typing import Any, Dict, Optional, Tuple

ENGINE_VERSION = 1

REFERENCES = ((1951, 1980), (1961, 1990), (1971, 2000), (1981, 2010), (1991, 2020))
REF_KEYS = tuple(f"{a}_{b}" for a, b in REFERENCES)
DEFAULT_REF = "1991_2020"
DEFAULT_REF_INDEX = REF_KEYS.index(DEFAULT_REF)

YEAR0, YEAR1 = REFERENCES[0][0], REFERENCES[-1][1]      # 1951 … 2020
NYEARS = YEAR1 - YEAR0 + 1
HALF_WINDOW = 7
WINDOW_DAYS = 2 * HALF_WINDOW + 1
MIN_QUALIFYING_YEARS = 20
MIN_WINDOW_VALID_FRACTION = 0.8
WINDOW_NEED = math.ceil(MIN_WINDOW_VALID_FRACTION * WINDOW_DAYS)   # 12 von 15

RECORD_YEAR_OPTIONS = (30, 50, 75, 100)
MIN_RECORD_YEARS = RECORD_YEAR_OPTIONS[0]
LEAP_DAY_DIVISOR = 4

ELEMENTS = ("TMAX", "TMIN", "TMEAN")
NA = -32768                           # "kein Klimamittel" in nrm-Arrays (int16)

# --------------------------------------------------------------------------- Kalender
CYCLE = [(dt.date(2000, 1, 1) + dt.timedelta(days=i)).strftime("%m-%d") for i in range(366)]
POS = {m: i for i, m in enumerate(CYCLE)}
_POS_TABLE = [-1] * (13 * 32)
for _m, _i in POS.items():
    _POS_TABLE[int(_m[:2]) * 32 + int(_m[3:])] = _i
_BIT = [1 << i for i in range(366)]
_WIN = [tuple((p + o) % 366 for o in range(-HALF_WINDOW, HALF_WINDOW + 1)) for p in range(366)]
_WINMASK = [sum(_BIT[i] for i in w) for w in _WIN]
_REFS_BY_YEAR = {y: tuple(i for i, (a, b) in enumerate(REFERENCES) if a <= y <= b) for y in range(YEAR0, YEAR1 + 1)}


def pos_of(mmdd: str) -> Optional[int]:
    return POS.get(mmdd)


# --------------------------------------------------------------------------- Aufbau
def _rec() -> list:
    return [array("h", [0]) * 366, array("i", [0]) * 366, array("B", [0]) * 366]   # Wert, Datum, Anzahl


def _block(with_records: bool) -> dict:
    b = {
        "s": [array("i", [0]) * 366 for _ in REFERENCES],      # Summen je Referenz
        "c": [array("B", [0]) * 366 for _ in REFERENCES],      # Anzahlen je Referenz
        "vm": [0] * NYEARS,                                    # gültige Tage je Jahr als 366-Bit-Maske
        "n": array("H", [0]) * 366,                            # Jahre mit Wert an genau diesem Kalendertag
    }
    if with_records:
        b["hi"] = _rec()
        b["lo"] = _rec()
    return b


def new_eng() -> dict:
    return {"TMAX": _block(True), "TMIN": _block(True), "TMEAN": _block(False)}


def _upd_hi(r: list, pos: int, v: int, d: int) -> None:
    k = r[2][pos]
    if k == 0 or v > r[0][pos]:
        r[0][pos] = v; r[1][pos] = d; r[2][pos] = 1
    elif v == r[0][pos]:
        if k < 255:
            r[2][pos] = k + 1
        if d < r[1][pos]:
            r[1][pos] = d


def _upd_lo(r: list, pos: int, v: int, d: int) -> None:
    k = r[2][pos]
    if k == 0 or v < r[0][pos]:
        r[0][pos] = v; r[1][pos] = d; r[2][pos] = 1
    elif v == r[0][pos]:
        if k < 255:
            r[2][pos] = k + 1
        if d < r[1][pos]:
            r[1][pos] = d


def _feed(b: dict, pos: int, v: int, d: int, refs: tuple, yi: int, bit: int) -> None:
    b["n"][pos] += 1
    for i in refs:
        b["s"][i][pos] += v
        b["c"][i][pos] += 1
    if yi >= 0:
        b["vm"][yi] |= bit
    if "hi" in b:
        _upd_hi(b["hi"], pos, v, d)
        _upd_lo(b["lo"], pos, v, d)


def add_day(eng: dict, year: int, month: int, day: int, tx: Optional[int], tn: Optional[int],
            normals: bool = True) -> None:
    """Ein Tag einer Station. tx/tn in Zehntelgrad oder None. Jeder Tag darf nur einmal gemeldet werden.

    normals=False: Der Tag zählt für Rekorde und Messjahre, aber nicht für Klimamittel
    (z. B. inhomogene SYNOP-Fenstermaxima in Belgien vor 2000).
    """
    if tx is None and tn is None:
        return
    pos = _POS_TABLE[month * 32 + day]
    if pos < 0:
        return
    d = year * 10000 + month * 100 + day
    if normals:
        refs = _REFS_BY_YEAR.get(year, ())
        yi = year - YEAR0 if YEAR0 <= year <= YEAR1 else -1
    else:
        refs, yi = (), -1
    bit = _BIT[pos]
    if tx is not None:
        _feed(eng["TMAX"], pos, tx, d, refs, yi, bit)
    if tn is not None:
        _feed(eng["TMIN"], pos, tn, d, refs, yi, bit)
    if tx is not None and tn is not None:
        _feed(eng["TMEAN"], pos, tx + tn, d, refs, yi, bit)


def has_data(eng: Optional[dict]) -> bool:
    if not eng:
        return False
    return any(b is not None and any(b["n"]) for b in eng.values())


# --------------------------------------------------------------------------- Tageswert-Reihe je Station
MISSING = -32768
_MD = [(int(m[:2]), int(m[3:])) for m in CYCLE]
VALUE_LIMIT = 1500                       # ±150 °C: Sicherheitsnetz, die Adapter prüfen strenger
DROPPED = {"out_of_range": 0, "bad_date": 0}


class Series:
    """Kompakte Tageswertreihe einer Station: je Jahr 366 Tmax- und 366 Tmin-Werte in Zehntelgrad.

    Sie ist idempotent (derselbe Tag darf mehrfach gemeldet werden, der letzte Wert gilt) und lässt sich
    deshalb gefahrlos in fortsetzbare Adapter-Zwischenstände einhängen. Aus ihr entsteht erst am Ende
    der Engine-Stand. Auf der Platte komprimiert gzip die Leerstellen fast vollständig.
    """
    __slots__ = ("y",)

    def __init__(self) -> None:
        self.y: Dict[int, array] = {}

    def __getstate__(self):
        return self.y

    def __setstate__(self, state) -> None:
        self.y = state

    def add(self, year: int, month: int, day: int, tx: Optional[int], tn: Optional[int]) -> None:
        if tx is None and tn is None:
            return
        pos = _POS_TABLE[month * 32 + day] if 1 <= month <= 12 and 1 <= day <= 31 else -1
        if pos < 0 or (pos == 59 and not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))):
            DROPPED["bad_date"] += 1
            return
        row = self.y.get(year)
        if row is None:
            row = self.y[year] = array("h", [MISSING]) * 732
        if tx is not None:
            if -VALUE_LIMIT <= tx <= VALUE_LIMIT:
                row[pos] = tx
            else:
                DROPPED["out_of_range"] += 1
        if tn is not None:
            if -VALUE_LIMIT <= tn <= VALUE_LIMIT:
                row[366 + pos] = tn
            else:
                DROPPED["out_of_range"] += 1

    def merge(self, other: "Series") -> None:
        for year, src in other.y.items():
            dst = self.y.get(year)
            if dst is None:
                self.y[year] = array("h", src)
                continue
            for i, v in enumerate(src):
                if v != MISSING:
                    dst[i] = v

    def copy(self) -> "Series":
        out = Series()
        out.y = {year: array("h", row) for year, row in self.y.items()}
        return out

    def day_count(self) -> int:
        return sum(1 for row in self.y.values() for p in range(366)
                   if row[p] != MISSING or row[366 + p] != MISSING)

    def items(self):
        """(jahr, monat, tag, tx|None, tn|None) in zeitlicher Reihenfolge."""
        for year in sorted(self.y):
            row = self.y[year]
            for pos in range(366):
                tx, tn = row[pos], row[366 + pos]
                if tx == MISSING and tn == MISSING:
                    continue
                month, day = _MD[pos]
                yield year, month, day, (None if tx == MISSING else tx), (None if tn == MISSING else tn)

    def to_engine(self, normals_from_year: Optional[int] = None) -> dict:
        eng = new_eng()
        for year, month, day, tx, tn in self.items():
            add_day(eng, year, month, day, tx, tn, normals_from_year is None or year >= normals_from_year)
        return eng

    def to_final(self, normals_from_year: Optional[int] = None) -> Optional[dict]:
        return finalize_eng(self.to_engine(normals_from_year))


# --------------------------------------------------------------------------- Zusammenführen (Teilstände disjunkter Zeiträume)
def _merge_rec(dst: list, src: list, pos: int, higher: bool) -> None:
    k = src[2][pos]
    if k == 0:
        return
    if dst[2][pos] == 0:
        dst[0][pos], dst[1][pos], dst[2][pos] = src[0][pos], src[1][pos], k
        return
    dv, sv = dst[0][pos], src[0][pos]
    if sv == dv:
        dst[2][pos] = min(255, dst[2][pos] + k)
        dst[1][pos] = min(dst[1][pos], src[1][pos])
    elif (sv > dv) == higher:
        dst[0][pos], dst[1][pos], dst[2][pos] = sv, src[1][pos], k


def merge_eng(dst: dict, src: dict) -> None:
    """src in dst einarbeiten. Beide müssen unfinalisiert sein und disjunkte Tage enthalten."""
    for el in ELEMENTS:
        d, s = dst[el], src[el]
        if "fin" in d or "fin" in s:
            raise ValueError("finalisierte Engine-Stände können nicht zusammengeführt werden")
        nz = [p for p in range(366) if s["n"][p]]
        for p in nz:
            d["n"][p] += s["n"][p]
            for i in range(len(REFERENCES)):
                d["s"][i][p] += s["s"][i][p]
                d["c"][i][p] += s["c"][i][p]
            if "hi" in d:
                _merge_rec(d["hi"], s["hi"], p, True)
                _merge_rec(d["lo"], s["lo"], p, False)
        sv, dv = s["vm"], d["vm"]
        for k in range(NYEARS):
            if sv[k]:
                dv[k] |= sv[k]


# --------------------------------------------------------------------------- Finalisieren
def _qualifying_years(vm: list, a: int, b: int) -> array:
    """Je Kalendertag: Anzahl Referenzjahre mit >= 80 % gültigen Tagen im 15-Tage-Fenster."""
    out = array("B", [0]) * 366
    for y in range(a, b + 1):
        m = vm[y - YEAR0]
        if not m:
            continue
        # Fehlen im ganzen Jahr höchstens 3 Tage (der 29.02. zählt im Nichtschaltjahr mit),
        # hat jedes Fenster mindestens 12 von 15 gültige Tage.
        if m.bit_count() >= 366 - (WINDOW_DAYS - WINDOW_NEED):
            for p in range(366):
                out[p] += 1
            continue
        for p in range(366):
            if (m & _WINMASK[p]).bit_count() >= WINDOW_NEED:
                out[p] += 1
    return out


def _pooled(s: array, c: array) -> Tuple[list, list]:
    tot = sum(s[(0 + o) % 366] for o in range(-HALF_WINDOW, HALF_WINDOW + 1))
    cnt = sum(c[(0 + o) % 366] for o in range(-HALF_WINDOW, HALF_WINDOW + 1))
    ts, cs = [0] * 366, [0] * 366
    for p in range(366):
        ts[p], cs[p] = tot, cnt
        tot += s[(p + HALF_WINDOW + 1) % 366] - s[(p - HALF_WINDOW) % 366]
        cnt += c[(p + HALF_WINDOW + 1) % 366] - c[(p - HALF_WINDOW) % 366]
    return ts, cs


def finalize_block(b: dict) -> Optional[dict]:
    if "fin" in b:
        return b
    if not any(b["n"]):
        return None
    ok_all, nrm_all = [], []
    for i, (a, bb) in enumerate(REFERENCES):
        ok = _qualifying_years(b["vm"], a, bb)
        ts, cs = _pooled(b["s"][i], b["c"][i])
        nrm = array("h", [NA]) * 366
        for p in range(366):
            if ok[p] >= MIN_QUALIFYING_YEARS and cs[p] > 0:
                v = int(math.floor(ts[p] * 10.0 / cs[p] + 0.5))          # Hundertstel der Einheit, kaufmännisch gerundet
                if -32767 <= v <= 32767:                                 # außerhalb: Datenmüll -> kein Mittel
                    nrm[p] = v
        ok_all.append(ok)
        nrm_all.append(nrm)
    out = {"fin": True, "ok": ok_all, "nrm": nrm_all, "n": b["n"]}
    if "hi" in b:
        out["hi"], out["lo"] = b["hi"], b["lo"]
    return out


def finalize_eng(eng: dict) -> Optional[dict]:
    """Rohstand -> kompakter Endstand (ohne Summen/Masken). Leere Elemente werden None."""
    out = {el: finalize_block(eng[el]) if eng.get(el) is not None else None for el in ELEMENTS}
    return out if any(v is not None for v in out.values()) else None


# --------------------------------------------------------------------------- Abfrage (Endstand)
def qualifying_years_at(block: Optional[dict], ref_index: int, pos: int) -> int:
    return int(block["ok"][ref_index][pos]) if block else 0


def normal_hundredths(block: Optional[dict], ref_index: int, pos: int) -> Optional[int]:
    if not block:
        return None
    v = block["nrm"][ref_index][pos]
    return None if v == NA else int(v)


def anomaly_tenths(block: Optional[dict], ref_index: int, pos: int, value_units: Optional[int], divisor: int = 1) -> Optional[int]:
    """Anomalie in Zehntelgrad. value_units: Tmax/Tmin in Zehntelgrad (divisor 1), Tmean als tx+tn (divisor 2)."""
    if value_units is None:
        return None
    nrm = normal_hundredths(block, ref_index, pos)
    if nrm is None:
        return None
    return int(math.floor((value_units * 10.0 - nrm) / (10.0 * divisor) + 0.5))


def record_at(block: Optional[dict], which: str, pos: int) -> Optional[Tuple[int, int, int]]:
    if not block or which not in block:
        return None
    r = block[which]
    k = r[2][pos]
    return None if k == 0 else (int(r[0][pos]), int(r[1][pos]), int(k))


def observed_years_at(block: Optional[dict], pos: int) -> int:
    return int(block["n"][pos]) if block else 0


def required_record_years(mmdd: str, min_years: int) -> int:
    """29.02. hat nur etwa jedes vierte Jahr einen Wert: 30->8, 50->13, 75->19, 100->25."""
    if mmdd == "02-29":
        return (int(min_years) + LEAP_DAY_DIVISOR - 1) // LEAP_DAY_DIVISOR
    return int(min_years)


def record_status(current: Optional[int], record: Optional[Tuple[int, int, int]], higher: bool) -> int:
    """0 = kein Rekord, 1 = gebrochen, 2 = eingestellt."""
    if current is None or record is None:
        return 0
    prev = record[0]
    if current == prev:
        return 2
    return 1 if (current > prev) == higher else 0


# --------------------------------------------------------------------------- Selbsttest
def _brute(series: Dict[int, Tuple[Optional[int], Optional[int]]], ref_index: int):
    """Unabhängige Referenzrechnung für einen Wertesatz {datum_int: (tx, tn)} -> je Kalendertag (ok_years, nrm_hundredths)."""
    a, b = REFERENCES[ref_index]
    by_year: Dict[int, Dict[int, int]] = {}
    for di, (tx, tn) in series.items():
        if tx is None:
            continue
        y, m, d = di // 10000, (di // 100) % 100, di % 100
        by_year.setdefault(y, {})[_POS_TABLE[m * 32 + d]] = tx
    res = []
    for p in range(366):
        ok = 0
        tot = cnt = 0
        for y in range(a, b + 1):
            days = by_year.get(y, {})
            valid = [q for q in _WIN[p] if q in days]
            if len(valid) >= WINDOW_NEED:
                ok += 1
            tot += sum(days[q] for q in valid)
            cnt += len(valid)
        res.append((ok, int(math.floor(tot * 10.0 / cnt + 0.5)) if ok >= MIN_QUALIFYING_YEARS and cnt else NA))
    return res


def self_test() -> None:
    import random

    rnd = random.Random(7)
    assert WINDOW_NEED == 12 and len(CYCLE) == 366 and CYCLE[59] == "02-29"

    # ---- Testreihe 1981-2025 mit Lücken
    series: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
    d = dt.date(1981, 1, 1)
    while d <= dt.date(2025, 12, 31):
        base = int(100 + 80 * math.sin((d.timetuple().tm_yday - 100) / 365 * 2 * math.pi) + (d.year - 1981) * 0.8)
        tx = base + rnd.randint(-30, 30)
        tn = tx - 80 + rnd.randint(-10, 10)
        y = d.year
        miss = False
        if y == 1995 and d.month <= 6:                 # Halbjahr fehlt -> 1995 qualifiziert im Winter nicht
            miss = True
        if y == 2003 and d.month in (7, 8):            # Hitzesommer-Lücke
            miss = True
        if rnd.random() < 0.01:
            miss = True
        series[int(d.strftime("%Y%m%d"))] = (None, None) if miss else (tx, tn)
        d += dt.timedelta(days=1)

    eng = new_eng()
    for di, (tx, tn) in series.items():
        if tx is not None:
            add_day(eng, di // 10000, (di // 100) % 100, di % 100, tx, tn)
    raw_vm = [list(b["vm"]) for b in (eng["TMAX"],)][0]
    fin = finalize_eng(eng)
    assert fin is not None and fin["TMAX"]["fin"] and "vm" not in fin["TMAX"] and "s" not in fin["TMAX"]

    # ---- Engine == Brute-Force für alle Referenzen und alle 366 Tage (Tmax)
    for ri in range(len(REFERENCES)):
        bf = _brute(series, ri)
        for p in range(366):
            assert qualifying_years_at(fin["TMAX"], ri, p) == bf[p][0], (ri, p)
            got = normal_hundredths(fin["TMAX"], ri, p)
            assert (got if got is not None else NA) == bf[p][1], (ri, p, got, bf[p][1])
    # Referenz 1951-1980 hat für diese Reihe nur 1981+ -> nirgends 20 Jahre
    assert all(normal_hundredths(fin["TMAX"], 0, p) is None for p in range(366))
    assert normal_hundredths(fin["TMAX"], DEFAULT_REF_INDEX, POS["07-15"]) is not None
    # 29.02. hat ein Mittel (Fenster wird mit Nachbartagen gefüllt)
    assert normal_hundredths(fin["TMAX"], DEFAULT_REF_INDEX, POS["02-29"]) is not None
    # 1995 (Halbjahr fehlt) zählt im Januar nicht, im Dezember schon
    ok_jan = qualifying_years_at(fin["TMAX"], DEFAULT_REF_INDEX, POS["01-20"])
    ok_dec = qualifying_years_at(fin["TMAX"], DEFAULT_REF_INDEX, POS["12-20"])
    assert ok_dec - ok_jan >= 1

    # ---- Tmean = (tx+tn)/2, nur wenn beide vorliegen
    p = POS["06-10"]
    tm_series = {di: (None if v[0] is None else v[0] + v[1], None) for di, v in series.items()}
    bf_tm = _brute(tm_series, DEFAULT_REF_INDEX)
    assert normal_hundredths(fin["TMEAN"], DEFAULT_REF_INDEX, p) == bf_tm[p][1]
    tx, tn = 250, 110
    a = anomaly_tenths(fin["TMEAN"], DEFAULT_REF_INDEX, p, tx + tn, 2)
    nrm = normal_hundredths(fin["TMEAN"], DEFAULT_REF_INDEX, p)
    assert a == int(math.floor(((tx + tn) * 10.0 - nrm) / 20.0 + 0.5))

    # ---- 80-%-Regel an der Grenze: 3 fehlende Tage im Fenster qualifizieren, 4 nicht
    for missing, expect in ((3, 1), (4, 0)):
        e2 = new_eng()
        for y in range(2001, 2021):                                   # 20 Jahre nur im Juli
            for day in range(1, 32):
                if y == 2010 and 12 <= day < 12 + missing:            # Lücke im Fenster 09.-23.07.
                    continue
                add_day(e2, y, 7, day, 200, 100)
        f2 = finalize_eng(e2)
        got = qualifying_years_at(f2["TMAX"], DEFAULT_REF_INDEX, POS["07-16"])
        assert got == 19 + expect, (missing, got)
        has_norm = normal_hundredths(f2["TMAX"], DEFAULT_REF_INDEX, POS["07-16"]) is not None
        assert has_norm == bool(expect), (missing, has_norm)          # 19 Jahre reichen nicht, 20 schon

    # ---- Rekorde in vier Richtungen gegen Brute-Force
    for p_mmdd in ("01-05", "07-15", "12-31", "02-29"):
        p = POS[p_mmdd]
        vals = [(di, v) for di, v in series.items() if v[0] is not None and _POS_TABLE[((di // 100) % 100) * 32 + di % 100] == p]
        txs = [v[0] for _, v in vals]
        tns = [v[1] for _, v in vals]
        assert record_at(fin["TMAX"], "hi", p)[0] == max(txs)
        assert record_at(fin["TMAX"], "lo", p)[0] == min(txs)
        assert record_at(fin["TMIN"], "hi", p)[0] == max(tns)
        assert record_at(fin["TMIN"], "lo", p)[0] == min(tns)
        assert observed_years_at(fin["TMAX"], p) == len(vals)
    assert observed_years_at(fin["TMAX"], POS["02-29"]) == len([1 for di in series if di % 10000 == 229 and series[di][0] is not None])
    assert [required_record_years("08-28", n) for n in RECORD_YEAR_OPTIONS] == [30, 50, 75, 100]
    assert [required_record_years("02-29", n) for n in RECORD_YEAR_OPTIONS] == [8, 13, 19, 25]
    assert record_status(301, (300, 1, 1), True) == 1 and record_status(300, (300, 1, 1), True) == 2 and record_status(299, (300, 1, 1), True) == 0
    assert record_status(99, (100, 1, 1), False) == 1 and record_status(101, (100, 1, 1), False) == 0 and record_status(None, (1, 1, 1), True) == 0

    # ---- Zusammenführen disjunkter Zeiträume == Einzelaufbau (inkl. Rekordgleichstand)
    ea, eb = new_eng(), new_eng()
    for di, (tx, tn) in series.items():
        if tx is None:
            continue
        add_day(ea if di < 20050101 else eb, di // 10000, (di // 100) % 100, di % 100, tx, tn)
    merge_eng(ea, eb)
    fm = finalize_eng(ea)
    for el in ELEMENTS:
        for ri in range(len(REFERENCES)):
            assert list(fm[el]["ok"][ri]) == list(fin[el]["ok"][ri]) and list(fm[el]["nrm"][ri]) == list(fin[el]["nrm"][ri]), (el, ri)
        assert list(fm[el]["n"]) == list(fin[el]["n"])
        if "hi" in fin[el]:
            for w in ("hi", "lo"):
                for k in range(3):
                    assert list(fm[el][w][k]) == list(fin[el][w][k]), (el, w, k)
    try:
        merge_eng(new_eng(), {"TMAX": {"fin": True}, "TMIN": {}, "TMEAN": {}})
        raise AssertionError("merge mit finalisiertem Stand muss scheitern")
    except ValueError:
        pass

    # ---- Randfälle
    assert finalize_eng(new_eng()) is None and not has_data(new_eng())
    e = new_eng(); add_day(e, 2020, 2, 30, 100, 50); add_day(e, 2020, 6, 1, None, None)
    assert not has_data(e)
    e = new_eng(); add_day(e, 2020, 6, 1, 100, None)
    f = finalize_eng(e)
    assert f["TMAX"] is not None and f["TMIN"] is None and f["TMEAN"] is None
    assert anomaly_tenths(None, 0, 0, 100) is None and anomaly_tenths(f["TMAX"], 4, POS["06-01"], 100) is None
    # ---- Series: Idempotenz, Merge, Pickle, ungültige Daten, normals_from_year
    import pickle
    ser = Series()
    for di, (tx, tn) in series.items():
        if tx is not None:
            ser.add(di // 10000, (di // 100) % 100, di % 100, tx, tn)
            ser.add(di // 10000, (di // 100) % 100, di % 100, tx, tn)          # doppelt gemeldet
    f_ser = ser.to_final()
    for el in ELEMENTS:
        for ri in range(len(REFERENCES)):
            assert list(f_ser[el]["nrm"][ri]) == list(fin[el]["nrm"][ri]) and list(f_ser[el]["ok"][ri]) == list(fin[el]["ok"][ri])
        assert list(f_ser[el]["n"]) == list(fin[el]["n"])
    assert ser.day_count() == len([1 for v in series.values() if v[0] is not None])
    s1, s2 = Series(), Series()
    for di, (tx, tn) in series.items():
        if tx is not None:
            (s1 if di < 20050101 else s2).add(di // 10000, (di // 100) % 100, di % 100, tx, tn)
    s1.merge(s2)
    assert list(s1.to_final()["TMAX"]["nrm"][DEFAULT_REF_INDEX]) == list(fin["TMAX"]["nrm"][DEFAULT_REF_INDEX])
    ca, cb = Series(), Series()
    ca.add(2001, 6, 1, 100, 50)
    ca.add(2001, 6, 2, 110, None)
    cb.add(2001, 6, 2, 120, 60)                                                # Überschneidung: die zuletzt eingearbeitete Meldung gilt
    cb.add(2001, 6, 3, 130, 70)
    ca.merge(cb)
    assert list(ca.items()) == [(2001, 6, 1, 100, 50), (2001, 6, 2, 120, 60), (2001, 6, 3, 130, 70)]
    s3 = pickle.loads(pickle.dumps(ser, protocol=pickle.HIGHEST_PROTOCOL))
    assert s3.day_count() == ser.day_count()
    bad = Series()
    before = dict(DROPPED)
    bad.add(2023, 2, 29, 100, 50)            # kein Schaltjahr
    bad.add(2024, 2, 30, 100, 50)            # gibt es nie
    bad.add(2024, 2, 29, 100, 50)            # gültig
    bad.add(2024, 3, 1, 5000, None)          # außerhalb des Sicherheitsnetzes
    assert bad.day_count() == 1 and DROPPED["bad_date"] - before["bad_date"] == 2 and DROPPED["out_of_range"] - before["out_of_range"] == 1
    only_tx = Series(); only_tx.add(2000, 5, 5, 100, None)
    only_tx.add(2000, 5, 5, None, 40)                                          # zweite Meldung ergänzt Tmin
    assert next(only_tx.items()) == (2000, 5, 5, 100, 40)
    # normals_from_year: Rekorde und Messjahre bleiben, Klimamittel nutzen nur spätere Jahre
    full = ser.to_final()
    late = ser.to_final(normals_from_year=2000)
    assert list(late["TMAX"]["n"]) == list(full["TMAX"]["n"])
    assert [tuple(late["TMAX"]["hi"][k]) for k in range(3)] == [tuple(full["TMAX"]["hi"][k]) for k in range(3)]
    assert normal_hundredths(late["TMAX"], DEFAULT_REF_INDEX, POS["07-15"]) != normal_hundredths(full["TMAX"], DEFAULT_REF_INDEX, POS["07-15"])
    assert normal_hundredths(late["TMAX"], REF_KEYS.index("1981_2010"), POS["07-15"]) is None      # nur 2000-2010 = 11 Jahre

    print("europe_climate_engine.py self-test OK")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--self-test", action="store_true")
    if ap.parse_args().self_test:
        self_test()
