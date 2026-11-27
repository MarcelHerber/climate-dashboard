#!/usr/bin/env python3
"""Offline-Tests für den Europa-Anomaliemonitor (Quellenschicht, Export, Fortsetzbarkeit).

Aufruf:  python test_europe_anomaly.py           (oder: python update_europe_anomaly_map.py --self-test)

Die Tests brauchen keine Netzverbindung. Sie bauen synthetische Rohdaten im Originalformat jedes Adapters,
lassen sie durch die UNVERÄNDERTEN Adapter-Funktionen laufen und prüfen:
  1. Mit Hook liefert jeder Adapter exakt dieselben Ergebnisse wie ohne Hook (nur der Schlüssel ``_pk`` kommt hinzu).
  2. Die erfasste Tageswertreihe entspricht den Eingangsdaten (inklusive Qualitätsregeln des Adapters).
  3. Die Engine-Rekorde stimmen mit den Rekorden des bestehenden Europa-Skripts überein.
  4. Klimamittel und Abdeckungsregel stimmen mit einer unabhängigen Brute-Force-Rechnung überein.
  5. Eine unterbrochene Baseline führt nach der Fortsetzung zum selben Ergebnis wie ein durchgehender Lauf.
Fehlende Adapter-Module werden übersprungen (und gemeldet), nie stillschweigend als bestanden gezählt.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import importlib
import importlib.util
import io
import math
import pickle
import random
import re
import sys
import tempfile
import types
import zipfile
from datetime import date
from pathlib import Path

import europe_anomaly_map as emap
import europe_anomaly_sources as src
import europe_climate_engine as E
import update_europe_station_records as core

SKIPPED: list = []
PASSED: list = []


# =========================================================================== Hilfen
def have(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def stub_missing_modules() -> list:
    """Nur für Tests: Module der Länder, die nicht Teil dieses Laufs sind, durch leere Platzhalter ersetzen,
    damit update_europe_station_records_all_sources importierbar ist (Metadaten-Konverter)."""
    if not have("update_europe_station_records_all_sources"):
        return []
    text = Path(importlib.util.find_spec("update_europe_station_records_all_sources").origin).read_text(encoding="utf-8")
    stubbed = []
    for name in re.findall(r"^import (update_\w+) as \w+", text, re.M):
        if not have(name) and name not in sys.modules:
            mod = types.ModuleType(name)
            mod.SOURCE = "STUB"
            sys.modules[name] = mod
            stubbed.append(name)
    return stubbed


def synth(y0: int, y1: int, seed: int, gap: float = 0.02, half_missing: float = 0.01) -> dict:
    """{date: (tx|None, tn|None)} in Zehntelgrad; mit Lücken, einseitigen Lücken und Schalttagen."""
    rnd = random.Random(seed)
    out = {}
    d = date(y0, 1, 1)
    while d.year <= y1:
        base = 110 + 90 * math.sin((d.timetuple().tm_yday - 105) / 365.25 * 2 * math.pi) + (d.year - y0) * 0.4
        tx = int(base) + rnd.randint(-45, 45)
        tn = tx - 75 + rnd.randint(-15, 15)
        r = rnd.random()
        if r < gap:
            pass                                              # Tag fehlt ganz
        elif r < gap + half_missing:
            out[d] = (tx, None) if rnd.random() < 0.5 else (None, tn)
        else:
            out[d] = (tx, tn)
        d += dt.timedelta(days=1)
    return out


def strip_pk(x):
    if isinstance(x, dict):
        return {k: strip_pk(v) for k, v in x.items() if k != "_pk"}
    return x


def upto(series: dict, year: int = 2025) -> dict:
    """Nur Tage bis einschließlich year (Baseline-Cutoff)."""
    return {d: v for d, v in series.items() if d.year <= year}


def series_dict(ser: E.Series) -> dict:
    return {date(y, m, d): (tx, tn) for y, m, d, tx, tn in ser.items()}


def only_present(series: dict, years=None) -> dict:
    out = {}
    for d, (tx, tn) in series.items():
        if (years is None or years(d.year)) and (tx is not None or tn is not None):
            out[d] = (tx, tn)
    return out


def brute_normal(series: dict, ref_index: int, element: int, mmdd: str):
    """Unabhängige Referenz (Tmax: element=0, Tmin: 1) -> (qualifizierende Jahre, Klimamittel in Hundertsteln|None)."""
    a, b = E.REFERENCES[ref_index]
    pos = E.POS[mmdd]
    window = [E._MD[(pos + o) % 366] for o in range(-7, 8)]
    ok = 0
    total = n = 0
    for year in range(a, b + 1):
        valid = 0
        for m, d in window:
            try:
                key = date(year, m, d)
            except ValueError:
                continue
            v = series.get(key, (None, None))[element]
            if v is not None:
                valid += 1
                total += v
                n += 1
        if valid >= 12:
            ok += 1
    nrm = int(math.floor(total * 10.0 / n + 0.5)) if ok >= 20 and n else None
    return ok, nrm


def check_engine_against_series(final: dict, series: dict, ref_index: int = E.DEFAULT_REF_INDEX, step: int = 1) -> None:
    """Engine == Brute-Force für Tmax/Tmin an (jedem step-ten) Kalendertag, plus Rekorde und Messjahre."""
    for i in range(0, 366, step):
        mmdd = E.CYCLE[i]
        for el, name in ((0, "TMAX"), (1, "TMIN")):
            ok, nrm = brute_normal(series, ref_index, el, mmdd)
            assert E.qualifying_years_at(final[name], ref_index, i) == ok, (name, mmdd)
            assert E.normal_hundredths(final[name], ref_index, i) == nrm, (name, mmdd)
            vals = [(d, v[el]) for d, v in series.items() if v[el] is not None and d.strftime("%m-%d") == mmdd]
            assert E.observed_years_at(final[name], i) == len(vals), (name, mmdd)
            if vals:
                hi = E.record_at(final[name], "hi", i)
                lo = E.record_at(final[name], "lo", i)
                assert hi[0] == max(v for _, v in vals) and lo[0] == min(v for _, v in vals), (name, mmdd)
                first_hi = min(d for d, v in vals if v == hi[0])
                first_lo = min(d for d, v in vals if v == lo[0])
                assert hi[1] == int(first_hi.strftime("%Y%m%d")) and lo[1] == int(first_lo.strftime("%Y%m%d"))
                assert hi[2] == sum(1 for _, v in vals if v == hi[0]) and lo[2] == sum(1 for _, v in vals if v == lo[0])


def check_engine_vs_core_state(final: dict, state: dict, compare_dates: bool = True) -> None:
    """Die Rekorde der Engine (Tmax hoch, Tmin tief) sind die des bestehenden Europa-Skripts.

    compare_dates=False nur für Belgien: Der Adapter speichert Hundertstelgrad, die Engine Zehntelgrad. Der Rekordwert
    (auf Zehntel gerundet) ist identisch, bei Gleichstand im Zehntel kann das erste Datum abweichen."""
    for mmdd in E.CYCLE:
        pos = E.POS[mmdd]
        for name, which in (("TMAX", "hi"), ("TMIN", "lo")):
            c = state[name]["cal"].get(mmdd)
            r = E.record_at(final[name], which, pos)
            if c and r:
                assert (c[0], c[1] if compare_dates else None) == (r[0], r[1] if compare_dates else None), (name, mmdd, c, r)
            else:
                assert c is None and r is None, (name, mmdd, c, r)
    assert max(r[0] for r in (E.record_at(final["TMAX"], "hi", p) for p in range(366)) if r) == state["TMAX"]["abs"][0]
    assert min(r[0] for r in (E.record_at(final["TMIN"], "lo", p) for p in range(366)) if r) == state["TMIN"]["abs"][0]


def check_engine_vs_compact(final: dict, rec: dict, decimals_to_tenths=lambda v: int(round(float(v) * 10.0))) -> None:
    """Gegen kompakte Adapter-Rekorde (calendar_tmax/-tmin mit [wert, iso-datum])."""
    for mmdd in E.CYCLE:
        pos = E.POS[mmdd]
        c = rec["calendar_tmax"].get(mmdd)
        r = E.record_at(final["TMAX"], "hi", pos)
        assert (decimals_to_tenths(c[0]), c[1]) == (r[0], f"{r[1] // 10000:04d}-{r[1] // 100 % 100:02d}-{r[1] % 100:02d}") if c and r else (c is None and r is None), ("TMAX", mmdd, c, r)
        c = rec["calendar_tmin"].get(mmdd)
        r = E.record_at(final["TMIN"], "lo", pos)
        assert (decimals_to_tenths(c[0]), c[1]) == (r[0], f"{r[1] // 10000:04d}-{r[1] // 100 % 100:02d}-{r[1] % 100:02d}") if c and r else (c is None and r is None), ("TMIN", mmdd, c, r)


def passed(name: str) -> None:
    PASSED.append(name)
    print(f"  ok  {name}")


def skipped(name: str, why: str) -> None:
    SKIPPED.append((name, why))
    print(f"  --  {name}: ÜBERSPRUNGEN ({why})")


# =========================================================================== Core: DWD, GHCN, Météo-France
def make_dwd_zip(series: dict) -> bytes:
    lines = ["STATIONS_ID;MESS_DATUM;QN_3;TMK;TXK;TNK;eor"]
    for d in sorted(series):
        tx, tn = series[d]
        f = lambda v: "-999" if v is None else f"{v / 10:.1f}"
        lines.append(f"1;{d:%Y%m%d};10;0.0;{f(tx)};{f(tn)};eor")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("produkt_klima_tag_19500101_20261231_00001.txt", "\n".join(lines) + "\n")
        zf.writestr("Metadaten_Geographie_00001.txt", "ignored;file\n")
    return buf.getvalue()


def make_dly(series: dict, sid: str = "AU000011111", flagged: set = frozenset()) -> bytes:
    by = {}
    for d, (tx, tn) in series.items():
        for el, v in (("TMAX", tx), ("TMIN", tn)):
            if v is not None:
                by.setdefault((d.year, d.month, el), {})[d.day] = v
    out = []
    for (y, m, el), days in sorted(by.items()):
        cells = []
        for day in range(1, 32):
            if day in days:
                q = "X" if (el, y, m, day) in flagged else " "
                cells.append(f"{days[day]:5d} {q} ")
            else:
                cells.append(f"{-9999:5d}   ")
        out.append(f"{sid}{y:04d}{m:02d}{el}" + "".join(cells))
    return ("\n".join(out) + "\n").encode("ascii")


def make_mf_gz(rows: list) -> bytes:
    """rows: (num_poste, lat, lon, date, tx, qtx, tn, qtn) mit Werten in Zehntelgrad|None."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["NUM_POSTE", "NOM_USUEL", "LAT", "LON", "ALTI", "AAAAMMJJ", "TN", "QTN", "TX", "QTX"])
    for num, lat, lon, d, tx, qtx, tn, qtn in rows:
        f = lambda v: "" if v is None else f"{v / 10:.1f}"
        w.writerow([num, f"ST{num}", lat, lon, 100, f"{d:%Y%m%d}", f(tn), qtn, f(tx), qtx])
    raw = gzip.compress(buf.getvalue().encode("utf-8"))
    return raw


def test_core_dwd() -> None:
    series = synth(1950, 2025, 11)
    data = make_dwd_zip(series)
    unhooked = core.parse_dwd_product_bytes(data, cutoff_year=2025)
    src.install_core_hooks()
    try:
        hooked = core.parse_dwd_product_bytes(data, cutoff_year=2025)
        assert strip_pk(hooked) == strip_pk(unhooked) and strip_pk(hooked) == unhooked
        ser = hooked["_pk"]
        assert series_dict(ser) == only_present(series)
        final = ser.to_final()
        check_engine_against_series(final, series, step=7)
        check_engine_against_series(final, series, ref_index=E.REF_KEYS.index("1961_1990"), step=37)
        check_engine_vs_core_state(final, unhooked)
        # cutoff und laufendes Jahr: keine Reihe, Ergebnis unverändert
        cur_u = _plain(lambda: core.parse_dwd_product_bytes(data, exact_year=2025))
        cur_h = core.parse_dwd_product_bytes(data, exact_year=2025)
        assert cur_h == cur_u and "_pk" not in cur_h
        h2 = core.parse_dwd_product_bytes(data, cutoff_year=1999)
        assert max(y for y, *_ in h2["_pk"].items()) == 1999
    finally:
        src.uninstall_hooks()
    passed("DWD: Hook ändert nichts, Reihe + Klimamittel + Rekorde stimmen")


def _plain(fn):
    src.uninstall_hooks()
    try:
        return fn()
    finally:
        src.install_core_hooks()


def test_core_ghcn() -> None:
    series = synth(1940, 2026, 5)                                   # 2026 liegt hinter dem Cutoff 2025
    both = sorted(d for d, v in series.items() if v[0] is not None and v[1] is not None)
    d_x = next(d for d in both if d >= date(1990, 7, 15))          # Tmax-Wert mit Qualitätsflag
    d_n = next(d for d in both if d >= date(2003, 8, 12))          # Tmin-Wert mit Qualitätsflag
    flagged = {("TMAX", d_x.year, d_x.month, d_x.day), ("TMIN", d_n.year, d_n.month, d_n.day)}
    data = make_dly(series, flagged=flagged)
    unhooked = core.parse_dly_station(io.BytesIO(data), 2025)
    src.install_core_hooks()
    try:
        hooked = core.parse_dly_station(io.BytesIO(data), 2025)
        assert strip_pk(hooked) == unhooked
        expected = {d: v for d, v in only_present(upto(series)).items()}
        expected[d_x] = (None, expected[d_x][1])
        expected[d_n] = (expected[d_n][0], None)
        expected = {d: v for d, v in expected.items() if v != (None, None)}
        assert series_dict(hooked["_pk"]) == expected
        final = hooked["_pk"].to_final()
        check_engine_vs_core_state(final, unhooked)
        # Qualitätsflag-Test: der geflaggte Wert taucht nirgends auf
        ser = hooked["_pk"]
        assert ser.y[d_x.year][E._POS_TABLE[d_x.month * 32 + d_x.day]] == E.MISSING
        assert ser.y[d_n.year][366 + E._POS_TABLE[d_n.month * 32 + d_n.day]] == E.MISSING
        # echtes Stream-Objekt (wie im tar-Lauf): read() wird nur einmal aufgerufen
        stream = io.BufferedReader(io.BytesIO(data))
        assert strip_pk(core.parse_dly_station(stream, 2025)) == unhooked
        # nur leere Datei -> keine Reihe, kein Fehler
        empty = core.parse_dly_station(io.BytesIO(b""), 2025)
        assert "_pk" not in empty
    finally:
        src.uninstall_hooks()
    passed("GHCN: Qualitätsflags wie im Core, Reihe + Rekorde stimmen, Stream-Verhalten")


def test_core_meteofrance() -> None:
    sA = synth(1950, 1989, 21)
    sB = synth(1990, 2026, 22)                                      # 2026 liegt hinter dem Cutoff 2025
    full = {**sA, **sB}

    def rows_for(num: str, series: dict, lat="45.0", lon="2.0"):
        out = []
        for d, (tx, tn) in series.items():
            qtx, qtn = ("0", "1")
            out.append((num, lat, lon, d, tx, qtx, tn, qtn))
        return out

    rowsA = rows_for("01001001", sA)
    rowsB = rows_for("01001001", sB)
    # Qualitätscode 2 ("douteuse") und fehlende Koordinaten werden verworfen
    bad_day = date(1985, 7, 10)
    rowsA = [(n, la, lo, d, tx, "2" if d == bad_day else q1, tn, qn) for n, la, lo, d, tx, q1, tn, qn in rowsA]
    rowsA.append(("01001001", "", "", date(1980, 1, 1), 999, "0", 999, "0"))        # ohne Koordinaten
    rowsB += rows_for("99999002", {date(2000, 1, 1): (100, 50), date(2001, 6, 6): (300, 150)})
    gzA, gzB = make_mf_gz(rowsA), make_mf_gz(rowsB)

    unA = core.parse_mf_stream(io.BytesIO(gzA), cutoff_year=2025)
    unB = core.parse_mf_stream(io.BytesIO(gzB), cutoff_year=2025)
    src.install_core_hooks()
    try:
        hA = core.parse_mf_stream(io.BytesIO(gzA), cutoff_year=2025)
        hB = core.parse_mf_stream(io.BytesIO(gzB), cutoff_year=2025)
        for h, u in ((hA, unA), (hB, unB)):
            assert strip_pk(h[0]) == u[0] and h[1] == u[1] and h[2] == u[2]
        expectedA = only_present(sA)
        expectedA[bad_day] = (None, expectedA[bad_day][1])                       # nur Tmax war als zweifelhaft markiert
        assert series_dict(hA[0]["MF:01001001"]["_pk"]) == {d: v for d, v in expectedA.items() if v != (None, None)}
        # zwei Ressourcen (Perioden) zusammenführen -> wie ein Gesamtlauf; Cache-Roundtrip (Pickle) dazwischen
        hA_cached = pickle.loads(pickle.dumps(hA, protocol=pickle.HIGHEST_PROTOCOL))
        merged: dict = {}
        core.merge_mf_partial(merged, hA_cached[0])
        core.merge_mf_partial(merged, hB[0])
        final_states = core.finalize_mf_states(merged)
        st = final_states["MF:01001001"]
        ser = st["_pk"]
        expected_full = {**expectedA, **only_present(upto(sB))}
        expected_full = {d: v for d, v in expected_full.items() if v != (None, None)}
        assert series_dict(ser) == expected_full
        check_engine_vs_core_state(ser.to_final(), strip_pk(st))
        # Mutation der zusammengeführten Reihe darf die zwischengespeicherten Teilstände nicht verändern
        ser.add(2020, 1, 1, 1, 1)
        assert series_dict(hB[0]["MF:01001001"]["_pk"]).get(date(2020, 1, 1)) != (1, 1)
        # laufendes Jahr: unverändert und ohne Reihe
        cu = core.parse_mf_stream(io.BytesIO(gzB), exact_year=2025)
        assert all("_pk" not in v for v in cu[0].values()) and cu[1]
        # Ressourcen-Cache (Einzeldatei-Shard) enthält die Reihe, und ein erneuter Lauf nutzt sie
        with tempfile.TemporaryDirectory() as tmp:
            res = {"url": "https://example.invalid/Q_01_previous-1950-1989_RR-T-Vent.csv.gz", "dept": "01", "period": (1950, 1989)}
            real_open = core.http_open
            core.http_open = lambda url, attempts=1, timeout=1: io.BytesIO(gzA)
            try:
                p1, m1, mode1, _ = core.process_mf_historical_resource(res, 2025, Path(tmp), False)
                core.http_open = lambda *a, **k: (_ for _ in ()).throw(AssertionError("zweiter Lauf darf nicht laden"))
                p2, m2, mode2, _ = core.process_mf_historical_resource(res, 2025, Path(tmp), False)
            finally:
                core.http_open = real_open
            assert (mode1, mode2) == ("download", "cache")
            assert series_dict(p2["MF:01001001"]["_pk"]) == series_dict(p1["MF:01001001"]["_pk"])
    finally:
        src.uninstall_hooks()
    passed("Météo-France: QC wie im Core, Zusammenführen mehrerer Perioden, Einzeldatei-Cache enthält Reihen")


# =========================================================================== Österreich, Polen
def test_austria() -> None:
    if not have("update_geosphere_austria_station_cache"):
        return skipped("GeoSphere Austria", "Modul fehlt")
    at = importlib.import_module("update_geosphere_austria_station_cache")
    s1 = synth(1990, 2025, 31, gap=0.03)
    s2 = synth(1990, 2025, 32)

    def payload(series_by_station: dict, y0: int, y1: int) -> dict:
        days = [date(y0, 1, 1) + dt.timedelta(days=i) for i in range((date(y1, 12, 31) - date(y0, 1, 1)).days + 1)]
        feats = []
        for station, series in series_by_station.items():
            tx = [None if series.get(d, (None, None))[0] is None else series[d][0] / 10 for d in days]
            tn = [None if series.get(d, (None, None))[1] is None else series[d][1] / 10 for d in days]
            tx[5] = -99.0                                  # Ausreißer außerhalb der Adaptergrenzen -> verworfen
            feats.append({"properties": {"station": station, "parameters": {"tlmax": {"data": tx}, "tlmin": {"data": tn}}}})
        return {"timestamps": [f"{d.isoformat()}T00:00+00:00" for d in days], "features": feats}

    p_old = payload({1: s1, 2: s2}, 1990, 2007)
    s1 = {**s1, **synth(2026, 2026, 33)}                              # 2026 liegt hinter dem Cutoff 2025
    s2 = {**s2, **synth(2026, 2026, 34)}
    p_new = payload({1: s1, 2: s2}, 2008, 2026)
    un_old = at.parse_feature_collection(p_old, "tlmax", "tlmin", cutoff_year=2025)
    un_new = at.parse_feature_collection(p_new, "tlmax", "tlmin", cutoff_year=2025)
    src.install_austria_hooks(at)
    try:
        h_old = at.parse_feature_collection(p_old, "tlmax", "tlmin", cutoff_year=2025)
        h_new = at.parse_feature_collection(p_new, "tlmax", "tlmin", cutoff_year=2025)
        assert strip_pk(h_old[0]) == un_old[0] and h_old[1] == un_old[1]
        # Blockcache-Roundtrip, dann zusammenführen und finalisieren wie build_baseline
        cached = pickle.loads(pickle.dumps({"partial": h_old[0]}, protocol=pickle.HIGHEST_PROTOCOL))
        merged: dict = {}
        at.merge_partial_states(merged, cached["partial"])
        at.merge_partial_states(merged, h_new[0])
        states = at.finalize_partial_states(merged)
        expected = {}
        for d, (tx, tn) in only_present(upto(s1)).items():
            expected[d] = (tx, tn)
        assert max(d.year for d in expected) == 2025
        got = series_dict(states["GSA:1"]["_pk"])
        # Der Ausreißer -99 °C steht in jedem Block an Position 5 (6.1.1990 und 6.1.2008): Der Adapter verwirft ihn
        # (Grenzwert in temp_to_tenths), also fehlt dort Tmax.
        for d in (date(1990, 1, 6), date(2008, 1, 6)):
            if d in expected:
                expected[d] = (None, expected[d][1])
        expected = {d: v for d, v in expected.items() if v != (None, None)}
        assert got == expected
        final = states["GSA:1"]["_pk"].to_final()
        base_state = at.finalize_partial_states(merge_unhooked(at, un_old[0], un_new[0]))["GSA:1"]
        check_engine_vs_core_state(final, base_state)
        assert strip_pk(states) == {k: v for k, v in at.finalize_partial_states(merge_unhooked(at, un_old[0], un_new[0])).items()}
        # laufendes Jahr: unverändert
        cu = at.parse_feature_collection(p_new, "tlmax", "tlmin", exact_year=2026)
        assert cu[0] == {} and cu[1]
    finally:
        src.uninstall_hooks()
    passed("Österreich: Hook ändert nichts, Blockcache + Merge + Finalize behalten die Reihen")


def merge_unhooked(mod, *partials) -> dict:
    """Merge ohne Hook (nutzt die Originalfunktion, solange die Hooks installiert sind)."""
    target: dict = {}
    original = src._orig(mod, "merge_partial_states") if (mod.__name__, "merge_partial_states") in src._ORIG else mod.merge_partial_states
    for p in partials:
        original(target, p)
    return target


def make_imgw_zip(rows: list, member: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    for row in rows:
        w.writerow(row)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, buf.getvalue().encode("cp1250", errors="replace"))
        zf.writestr("k_d_t_01_2001.csv", "ignored;reduced\n")
    return out.getvalue()


def test_poland() -> None:
    if not have("update_imgw_poland_station_cache"):
        return skipped("IMGW Polen", "Modul fehlt")
    pl = importlib.import_module("update_imgw_poland_station_cache")
    schema = {"headers": ["NSP", "POST", "ROK", "MC", "DZ", "TMAX", "WTMAX", "TMIN", "WTMIN"],
              "station": 0, "name": 1, "year": 2, "month": 3, "day": 4, "tmax": 5, "tmin": 7}
    s1 = synth(1951, 2000, 41)
    s2 = synth(2001, 2026, 42)                                      # 2026 liegt hinter dem Cutoff 2025

    def rows(series: dict, code: str, name: str):
        out = []
        for d, (tx, tn) in sorted(series.items()):
            f = lambda v: "" if v is None else f"{v / 10:.1f}".replace(".", ",")
            out.append([code, name, d.year, d.month, d.day, f(tx), "", f(tn), ""])
        return out

    old_rows = rows(s1, "250180010", "Łódź") + rows({date(1999, 5, 5): (1000, 900)}, "250180010", "Łódź")  # 100 °C: außerhalb der Adaptergrenze
    zip_old = make_imgw_zip(old_rows, "k_d_01_1951-2000.csv")
    zip_new = make_imgw_zip(rows(s2, "250180010", "Łódź"), "k_d_01_2001-2025.csv")
    un_old = pl.parse_zip(zip_old, schema, cutoff_year=2025)
    un_new = pl.parse_zip(zip_new, schema, cutoff_year=2025)
    src.install_poland_hooks(pl)
    try:
        h_old = pl.parse_zip(zip_old, schema, cutoff_year=2025)
        h_new = pl.parse_zip(zip_new, schema, cutoff_year=2025)
        assert strip_pk(h_old[0]) == un_old[0] and h_old[1] == un_old[1] and h_old[2] == un_old[2]
        sid = "IMGW:250180010"
        expected = only_present(s1)
        assert series_dict(h_old[0][sid]["_pk"]) == expected              # 100 °C wurde vom Adapter verworfen
        merged: dict = {}
        pl.merge_partial(merged, pickle.loads(pickle.dumps(h_old[0])))
        pl.merge_partial(merged, h_new[0])
        states = pl.finalize_partial_states(merged)
        full = {**only_present(s1), **only_present(upto(s2))}
        assert series_dict(states[sid]["_pk"]) == full
        ref = pl.finalize_partial_states(merge_unhooked(pl, un_old[0], un_new[0]))
        check_engine_vs_core_state(states[sid]["_pk"].to_final(), ref[sid])
        check_engine_against_series(states[sid]["_pk"].to_final(), full, step=11)
        assert strip_pk(states) == ref
        # laufendes Jahr: unverändert, keine Erfassung nötig
        cu = pl.parse_zip(zip_new, schema, exact_year=2026)
        assert cu[0] == {} and cu[1]
        # Shard-Cache: erster Lauf lädt, zweiter liest aus dem Cache und liefert die Reihe weiter
        with tempfile.TemporaryDirectory() as tmp:
            real = pl.read_bytes
            pl.read_bytes = lambda url, attempts=3, timeout=120: zip_new
            try:
                resource = {"key": "2001_2025", "url": "https://example.invalid/2001.zip"}
                p1, m1, e1 = pl.process_resource(resource, schema, Path(tmp), 2025)
                pl.read_bytes = lambda *a, **k: (_ for _ in ()).throw(AssertionError("zweiter Lauf darf nicht laden"))
                p2, m2, e2 = pl.process_resource(resource, schema, Path(tmp), 2025)
            finally:
                pl.read_bytes = real
            assert (m1, m2, e1, e2) == ("download", "cache", None, None)
            assert series_dict(p2["partial"][sid]["_pk"]) == only_present(upto(s2))
        # Thread-Sicherheit: parallele Aufrufe vermischen die erfassten Bytes nicht
        from concurrent.futures import ThreadPoolExecutor
        zips = [zip_old, zip_new] * 6
        with ThreadPoolExecutor(max_workers=6) as pool:
            outs = list(pool.map(lambda z: pl.parse_zip(z, schema, cutoff_year=2025), zips))
        for z, o in zip(zips, outs):
            want = only_present(s1 if z is zip_old else upto(s2))
            assert series_dict(o[0][sid]["_pk"]) == want
    finally:
        src.uninstall_hooks()
    passed("IMGW Polen: Hook ändert nichts, Shard-Cache + Merge + Threads sicher")


# =========================================================================== Spanien, Niederlande, Belgien, Schweiz, Tschechien
def allsrc_or_none():
    if not have("update_europe_station_records_all_sources"):
        return None
    return importlib.import_module("update_europe_station_records_all_sources")


def test_aemet() -> None:
    if not have("update_aemet_spain_station_cache"):
        return skipped("AEMET Spanien", "Modul fehlt")
    am = importlib.import_module("update_aemet_spain_station_cache")
    allsrc = allsrc_or_none()
    s1 = synth(2001, 2025, 51)
    s2 = synth(2001, 2025, 52)

    def rows(series: dict, sid: str, lo: date, hi: date):
        out = []
        for d, (tx, tn) in sorted(series.items()):
            if lo <= d <= hi:
                f = lambda v: None if v is None else f"{v / 10:.1f}".replace(".", ",")
                out.append({"indicativo": sid, "fecha": d.isoformat(), "nombre": f"EST {sid}", "tmax": f(tx), "tmin": f(tn)})
        return out

    inv = {"A": {"id": "A"}}
    w1 = (date(2001, 1, 1), date(2013, 12, 31))
    w2 = (date(2014, 1, 1), date(2025, 12, 31))
    pay1 = rows(s1, "A", *w1) + rows(s2, "B", *w1)
    pay2 = rows(s1, "A", *w2) + rows(s2, "B", *w2)
    rec_u: dict = {}
    am.consume_daily_payload(pay1, window_start=w1[0], window_end=w1[1], inventory={}, records=rec_u)
    am.consume_daily_payload(pay2, window_start=w2[0], window_end=w2[1], inventory={}, records=rec_u)
    src.install_aemet_hooks(am)
    try:
        rec_h: dict = {}
        inv_h: dict = {}
        am.consume_daily_payload(pay1, window_start=w1[0], window_end=w1[1], inventory=inv_h, records=rec_h)
        am.consume_daily_payload(pay1, window_start=w1[0], window_end=w1[1], inventory=inv_h, records=rec_h)   # Fenster erneut (Wiederholung nach Abbruch)
        am.consume_daily_payload(pay2, window_start=w2[0], window_end=w2[1], inventory=inv_h, records=rec_h)
        for sid in ("A", "B"):
            h = strip_pk(rec_h[sid])
            u = rec_u[sid]
            for key in ("first_date", "last_date", "tmax_abs", "tmax_low_abs", "tmin_abs", "tmin_high_abs", "calendar_tmax", "calendar_tmin"):
                assert h[key] == u[key], (sid, key)               # Rekorde unverändert; nur observation_days zählt die Wiederholung doppelt (Adapter-Eigenheit)
        assert series_dict(rec_h["A"]["_pk"]) == only_present(s1) and series_dict(rec_h["B"]["_pk"]) == only_present(s2)
        final = rec_h["A"]["_pk"].to_final()
        check_engine_vs_compact(final, rec_u["A"], lambda v: int(round(float(v) * 10.0)))
        check_engine_against_series(final, s1, step=13)
        # Adapter-Fehler (außerhalb des Fensters / unplausibel) bleiben Fehler und erfassen nichts
        bad = [{"indicativo": "Z", "fecha": "2020-01-01", "tmax": "99,0", "tmin": "1,0"}]
        try:
            am.consume_daily_payload(bad, window_start=date(2020, 1, 1), window_end=date(2020, 1, 14), inventory={}, records=(rz := {}))
            raise AssertionError("unplausibler Wert muss den Adapter-Fehler auslösen")
        except RuntimeError:
            assert "Z" not in rz or "_pk" not in rz["Z"]
        # Einseitige Werte: nur Tmax -> Reihe hat nur Tmax
        only = [{"indicativo": "C", "fecha": "2020-07-01", "tmax": "30,5", "tmin": ""}]
        rc: dict = {}
        am.consume_daily_payload(only, window_start=date(2020, 7, 1), window_end=date(2020, 7, 14), inventory={}, records=rc)
        assert list(rc["C"]["_pk"].items()) == [(2020, 7, 1, 305, None)]
    finally:
        src.uninstall_hooks()

    # ---- Fortsetzung nach Abbruch: build_baseline unterbrechen, neu starten, mit durchgehendem Lauf vergleichen
    real_fetch, real_start = am.fetch_api_payload, am.START_DATE
    am.START_DATE = date(2001, 1, 1)
    calls = {"n": 0, "fail_after": None}
    inventory_payload = [{"indicativo": f"I{i:03d}", "nombre": f"X{i}", "provincia": "P", "altitud": "10", "latitud": "402441N",
                          "longitud": "0034040W", "indsinop": ""} for i in range(120)]

    def fake_fetch(api_path, api_key, *, label, no_data_is_empty=False):
        if api_path == am.INVENTORY_PATH:
            return inventory_payload
        calls["n"] += 1
        if calls["fail_after"] is not None and calls["n"] > calls["fail_after"]:
            raise RuntimeError("simulierter Netzabbruch")
        lo, hi = (date.fromisoformat(x) for x in re.findall(r"\d{4}-\d{2}-\d{2}", api_path)[:2])
        return rows(s1, "A", lo, hi) + rows(s2, "B", lo, hi)

    am.fetch_api_payload = fake_fetch
    src.install_aemet_hooks(am)
    try:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            full = am.build_baseline(api_key="x", cutoff_year=2025, cache_dir=Path(t1))
            assert full["complete"]
            calls.update(n=0, fail_after=120)
            try:
                am.build_baseline(api_key="x", cutoff_year=2025, cache_dir=Path(t2))
                raise AssertionError("Abbruch erwartet")
            except RuntimeError as exc:
                assert "simulierter" in str(exc)
            # frischer Prozess: Hooks neu installieren, Fortschritt von der Platte lesen
            src.uninstall_hooks()
            src.install_aemet_hooks(am)
            calls.update(n=0, fail_after=None)
            resumed = am.build_baseline(api_key="x", cutoff_year=2025, cache_dir=Path(t2))
            assert resumed["complete"] and calls["n"] > 0
            base_full = am.load_baseline(Path(t1), 2025)
            base_res = am.load_baseline(Path(t2), 2025)
            for sid, ref_series in (("A", s1), ("B", s2)):
                a = series_dict(base_full["records"][sid]["_pk"])
                b = series_dict(base_res["records"][sid]["_pk"])
                assert a == b == only_present(ref_series), sid
            engines = src._engines_from_holders("AEMET", base_res["records"], lambda raw: f"AEMET:{raw}")
            check_engine_against_series(engines["AEMET:A"], s1, step=17)
            # Cache ohne Hook gebaut -> klare Fehlermeldung statt leerer Karte
            try:
                src._engines_from_holders("AEMET", {k: strip_pk(v) for k, v in base_res["records"].items()}, lambda raw: raw)
                raise AssertionError("fehlende Reihen müssen auffallen")
            except RuntimeError as exc:
                assert "force-baseline" in str(exc)
    finally:
        src.uninstall_hooks()
        am.fetch_api_payload, am.START_DATE = real_fetch, real_start
    passed("AEMET Spanien: Hook ändert nichts, Wiederholung idempotent, Abbruch + Fortsetzung = durchgehender Lauf")


def knmi_text(series_by_station: dict, lo: date, hi: date) -> str:
    lines = ["# SOURCE: KNMI", "#", "# STN      LON(east)   LAT(north)     ALT(m)  NAME"]
    for i, stn in enumerate(sorted(series_by_station)):
        lines.append(f"# {stn}:         {5.0 + i:.3f}       {52.0 + i / 10:.3f}       2.00  STATION {stn}")
    lines += ["#", "# STN,YYYYMMDD,   TN,   TX", "#"]
    for stn in sorted(series_by_station):
        for d, (tx, tn) in sorted(series_by_station[stn].items()):
            if lo <= d <= hi and (tx is not None or tn is not None):
                lines.append(f"  {stn},{d:%Y%m%d},{'' if tn is None else tn:>5},{'' if tx is None else tx:>5}")
    return "\n".join(lines) + "\n"


def test_knmi() -> None:
    if not have("update_knmi_netherlands_station_cache"):
        return skipped("KNMI Niederlande", "Modul fehlt")
    kn = importlib.import_module("update_knmi_netherlands_station_cache")
    s260 = synth(1986, 2025, 61)
    s280 = synth(1986, 2025, 62)
    both = {"260": s260, "280": s280}
    rows = kn.parse_daily_rows(knmi_text(both, date(1986, 1, 1), date(2025, 12, 31)))
    rec_u: dict = {}
    kn.consume_rows(rec_u, rows)
    src.install_knmi_hooks(kn)
    try:
        rec_h: dict = {}
        kn.consume_rows(rec_h, rows)
        for sid in ("260", "280"):
            assert strip_pk(rec_h[sid]) == rec_u[sid], sid
        assert series_dict(rec_h["260"]["_pk"]) == only_present(s260)
        final = rec_h["260"]["_pk"].to_final()
        check_engine_vs_compact(final, rec_u["260"], lambda v: int(round(float(v) * 10.0)))
        check_engine_against_series(final, s260, step=19)
    finally:
        src.uninstall_hooks()

    # ---- Fortsetzung nach Abbruch (Jahres-Checkpoints) und Laufzeitgrenze
    real_req, real_start = kn.request_knmi, kn.START_YEAR
    kn.START_YEAR = 1986
    state = {"n": 0, "fail_after": None}

    def fake_request(start: date, end: date) -> str:
        state["n"] += 1
        if state["fail_after"] is not None and state["n"] > state["fail_after"]:
            raise RuntimeError("simulierter Netzabbruch")
        return knmi_text(both, start, end)

    kn.request_knmi = fake_request
    src.install_knmi_hooks(kn)
    try:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2, tempfile.TemporaryDirectory() as t3:
            p_full = kn.build_baseline(Path(t1), 2025)
            assert kn.valid_final_baseline(p_full, 2025)
            state.update(n=0, fail_after=15)
            try:
                kn.build_baseline(Path(t2), 2025)
                raise AssertionError("Abbruch erwartet")
            except RuntimeError as exc:
                assert "simulierter" in str(exc)
            src.uninstall_hooks()
            src.install_knmi_hooks(kn)                                  # frischer Prozess
            state.update(n=0, fail_after=None)
            p_res = kn.build_baseline(Path(t2), 2025)
            assert kn.valid_final_baseline(p_res, 2025) and state["n"] == 40 - 15
            a, b = kn.load_pickle_gzip(p_full), kn.load_pickle_gzip(p_res)
            for stn, ref in (("260", s260), ("280", s280)):
                assert series_dict(a["records"][stn]["_pk"]) == series_dict(b["records"][stn]["_pk"]) == only_present(ref)
            # Laufzeitgrenze 0: Zwischenstand, keine fertige Baseline
            state.update(n=0, fail_after=None)
            p_part = kn.build_baseline(Path(t3), 2025, max_runtime_minutes=0.0)
            assert not kn.valid_final_baseline(p_part, 2025)
    finally:
        src.uninstall_hooks()
        kn.request_knmi, kn.START_YEAR = real_req, real_start
    passed("KNMI Niederlande: Hook ändert nichts, Abbruch + Fortsetzung = durchgehender Lauf")


def test_belgium() -> None:
    if not have("update_rmi_belgium_station_cache"):
        return skipped("KMI/RMI Belgien", "Modul fehlt")
    be = importlib.import_module("update_rmi_belgium_station_cache")
    allsrc = allsrc_or_none()
    uccle = be.UCCLE_CODE
    su = synth(1950, 2025, 71)
    so = synth(1952, 2025, 72)
    # Zwei Dezimalstellen wie bei den AWS-Daten; 14,25 prüft die Rundung gegen den Adapter-Pfad (round(x, 2) -> Zehntel)
    def val(v):
        return None if v is None else (v / 10 + 0.05 if v % 7 == 0 else v / 10)

    def feed(records: dict) -> None:
        for sid, series in ((uccle, su), ("6455", so)):
            for d, (tx, tn) in sorted(series.items()):
                prov = "GHCN_UCCLE" if (sid == uccle and d.year < 2000) else ("RMI_SYNOP" if d.year < 2000 else "RMI_AWS")
                be.consume_day(records, sid, d, val(tn), val(tx), prov)

    rec_u: dict = {}
    feed(rec_u)
    src.install_belgium_hooks(be)
    try:
        rec_h: dict = {}
        feed(rec_h)
        for sid in (uccle, "6455"):
            assert strip_pk(rec_h[sid]) == rec_u[sid], sid
        ser_u = rec_h[uccle]["_pk"]
        assert ser_u.day_count() == len(only_present(su))
        if allsrc is not None:
            states = allsrc.compact_records_to_core_states(rec_u, prefix="RMI")
            for sid, series in ((uccle, su), ("6455", so)):
                check_engine_vs_core_state(rec_h[sid]["_pk"].to_final(), states[f"RMI:{sid}"], compare_dates=False)
        # Rundung: derselbe Wert wie über den bestehenden kompakten Pfad (round(x, 2) -> int(round(x * 10)))
        for d, (tx, tn) in list(su.items())[:4000]:
            if tx is not None and val(tx) is not None:
                expected = int(round(round(float(val(tx)), 2) * 10.0))
                got = ser_u.y[d.year][E._POS_TABLE[d.month * 32 + d.day]]
                if d.year >= 1950 and got != E.MISSING:
                    assert got == expected, (d, got, expected)
        # Uccle: alle Jahre in den Klimamitteln; andere Station: nur AWS ab 2000
        engines = src._engines_from_holders("KMI/RMI", rec_h, lambda raw: f"RMI:{raw}",
                                            normals_from=lambda raw: None if raw == uccle else src.BELGIUM_NORMALS_FROM_YEAR)
        e_uc, e_ot = engines[f"RMI:{uccle}"], engines["RMI:6455"]
        ri_6190 = E.REF_KEYS.index("1961_1990")
        ri_9120 = E.DEFAULT_REF_INDEX
        assert any(E.normal_hundredths(e_uc["TMAX"], ri_6190, p) is not None for p in range(366))        # Uccle: 1961-1990 vorhanden
        assert all(E.normal_hundredths(e_ot["TMAX"], ri_6190, p) is None for p in range(366))            # SYNOP-Zeitraum zählt nicht
        assert any(E.normal_hundredths(e_ot["TMAX"], ri_9120, p) is not None for p in range(366))        # 2000-2020 = 21 Jahre
        # Rekorde und Messjahre der anderen Station nutzen alle Jahre (wie der bestehende Rekordstand)
        assert E.observed_years_at(e_ot["TMAX"], E.POS["07-01"]) == sum(1 for d, v in so.items() if (d.month, d.day) == (7, 1) and v[0] is not None)
    finally:
        src.uninstall_hooks()
    passed("KMI/RMI Belgien: Hook ändert nichts, Rundung wie Adapter, SYNOP-Zeit nur für Rekorde")


def test_meteoswiss() -> None:
    if not have("update_meteoswiss_switzerland_station_cache"):
        return skipped("MeteoSwiss Schweiz", "Modul fehlt")
    sw = importlib.import_module("update_meteoswiss_switzerland_station_cache")
    series = synth(1980, 2025, 81)
    raw_lines = ["station_abbr;reference_timestamp;tre200dn;tre200dx"]
    for d, (tx, tn) in sorted(series.items()):
        raw_lines.append(f"BER;{d:%d.%m.%Y} 00:00;{'' if tn is None else f'{tn / 10:.1f}'};{'' if tx is None else f'{tx / 10:.1f}'}")
    raw = ("\n".join(raw_lines) + "\n").encode("utf-8")
    rows = sw.parse_daily_asset(raw, cutoff_year=2025, historical_qc=True, qc_stats={})
    assert rows
    rec_u = sw.empty_record()
    for d, tn, tx in rows:
        sw.consume_day(rec_u, d, tn, tx)
    src.install_swiss_hooks(sw)
    try:
        rec_h = sw.empty_record()
        for d, tn, tx in rows:
            sw.consume_day(rec_h, d, tn, tx)
        assert strip_pk(rec_h) == rec_u
        got = series_dict(rec_h["_pk"])
        expect = {d: (None if tx is None else int(round(tx * 10.0)), None if tn is None else int(round(tn * 10.0))) for d, tn, tx in rows}
        assert got == expect
        final = rec_h["_pk"].to_final()
        check_engine_vs_compact(final, rec_u, lambda v: int(round(float(v) * 10.0)))
        # Rückgabewert False (kein Wert) -> keine Reihe
        empty = sw.empty_record()
        assert sw.consume_day(empty, date(2020, 1, 1), None, None) is False and "_pk" not in empty
    finally:
        src.uninstall_hooks()
    passed("MeteoSwiss Schweiz: Hook ändert nichts, Reihe + Rekorde stimmen")


def test_chmi_packed() -> None:
    allsrc = allsrc_or_none()
    series = synth(1961, 2025, 91)
    missing = -32768
    days = sorted(series)
    record = {
        "ordinals": [d.toordinal() for d in days],
        "tmax_tenths": [missing if series[d][0] is None else series[d][0] for d in days],
        "tmin_tenths": [missing if series[d][1] is None else series[d][1] for d in days],
    }
    ser = src.series_from_chmi_packed(record, missing)
    assert series_dict(ser) == only_present(series)
    final = ser.to_final()
    check_engine_against_series(final, series, step=23)
    if allsrc is not None:
        chmi = importlib.import_module("update_chmi_czechia_station_cache") if have("update_chmi_czechia_station_cache") else None
        if chmi is not None and hasattr(chmi, "MISSING_I16"):
            assert chmi.MISSING_I16 == missing
        state = allsrc.chmi_packed_to_core_states({"X": record})["CHMI:X"]
        check_engine_vs_core_state(final, state)
    assert src.series_from_chmi_packed({"ordinals": [], "tmax_tenths": [], "tmin_tenths": []}, missing) is None
    passed("CHMI: gepackte Tagesreihe -> Reihe -> Engine, Rekorde wie im bestehenden Skript")


# =========================================================================== Export, Quellenlauf, Kommandozeile
def fake_meta(sid: str, cc: str = "XX", lat: float = 50.0, lon: float = 10.0, source: str = "TEST"):
    return core.StationMeta(sid, lat, lon, 100.0, f"Station {sid}", cc, cc, source, "Testregel")


def current_from_series(series: dict, year: int, upto: date) -> dict:
    out = {"TMAX": {}, "TMIN": {}}
    for d, (tx, tn) in series.items():
        if d.year == year and d <= upto:
            mmdd = d.strftime("%m-%d")
            if tx is not None:
                out["TMAX"][mmdd] = (tx, int(d.strftime("%Y%m%d")))
            if tn is not None:
                out["TMIN"][mmdd] = (tn, int(d.strftime("%Y%m%d")))
    return out


def expected_anomaly(series: dict, ref_index: int, element: int, mmdd: str, value10: int):
    ok, nrm = brute_normal(series, ref_index, element, mmdd)
    return None if nrm is None else int(math.floor((value10 * 10.0 - nrm) / 10.0 + 0.5))


def build_export_fixture(year: int = 2026):
    """Quelle A (ok, 3 Stationen: mit Referenz / ohne Engine / zu kurze Reihe), B (failed), C (planned), D (building)."""
    s1 = synth(1981, 2025, 101, gap=0.01)
    s3 = synth(2016, 2025, 103)
    cur_end = date(year, 11, 20)
    c1 = synth(year, year, 111, gap=0.0, half_missing=0.0)
    c2 = synth(year, year, 112, gap=0.0, half_missing=0.0)
    c3 = synth(year, year, 113, gap=0.0, half_missing=0.0)
    # S1: am 1. Juli ein neuer Tmax-Rekord, am 2. Juli ein eingestellter, am 3. Juli kein Rekord; am 5. Juli ein neuer Tmin-Tiefrekord
    pos = lambda m, d: E.POS[f"{m:02d}-{d:02d}"]
    base_final = src_finalize(s1)
    hi1 = E.record_at(base_final["TMAX"], "hi", pos(7, 1))[0]
    hi2 = E.record_at(base_final["TMAX"], "hi", pos(7, 2))[0]
    lo5 = E.record_at(base_final["TMIN"], "lo", pos(7, 5))[0]
    tn1 = c1[date(year, 7, 1)][1]
    c1[date(year, 7, 1)] = (hi1 + 5, tn1)
    c1[date(year, 7, 2)] = (hi2, c1[date(year, 7, 2)][1])
    c1[date(year, 7, 3)] = (E.record_at(base_final["TMAX"], "hi", pos(7, 3))[0] - 20, c1[date(year, 7, 3)][1])
    c1[date(year, 7, 5)] = (c1[date(year, 7, 5)][0], lo5 - 3)
    sid1, sid2, sid3, sid4 = "A:1", "A:2", "A:3", "A:4"
    cur = {sid1: current_from_series(c1, year, cur_end), sid2: current_from_series(c2, year, cur_end),
           sid3: current_from_series(c3, year, cur_end)}
    cur[sid4] = {"TMAX": {"11-21": (50, int(f"{year}1121"))}, "TMIN": {"11-21": (10, int(f"{year}1121"))}}     # nur der Tag nach dem Standarddatum
    res_a = src.SourceResult("test_a", "Test A", "A", ("XX",), status="ok", message="ok")
    res_a.stations = {sid1: fake_meta(sid1, "AT"), sid2: fake_meta(sid2, "AT", 49.0, 11.0), sid3: fake_meta(sid3, "DE", 48.0, 9.0),
                      sid4: fake_meta(sid4, "DE", 47.0, 8.0)}
    res_a.engines = {sid1: base_final, sid3: src_finalize(s3)}
    res_a.current = cur
    res_b = src.SourceResult("test_b", "Test B", "A", ("NL",), status="failed", message="RuntimeError: boom")
    res_c = src.SourceResult("test_c", "Test C", "B2.2", ("DK",), status="planned", message="Adapter noch nicht angebunden")
    res_d = src.SourceResult("test_d", "Test D", "B2.1", ("ES",), status="building", message="AEMET-Baseline im Aufbau: Fenster 100/1000")
    return [res_a, res_b, res_c, res_d], {"s1": s1, "s3": s3, "c1": c1, "c2": c2, "c3": c3, "sid": (sid1, sid2, sid3, sid4)}


def src_finalize(series: dict):
    ser = E.Series()
    for d, (tx, tn) in series.items():
        ser.add(d.year, d.month, d.day, tx, tn)
    return ser.to_final()


def read_gz_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        import json
        return json.load(handle)


def test_export() -> None:
    import json
    import shutil
    year = 2026
    results, fx = build_export_fixture(year)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "anomaly_map"
        index = emap.write_map(out, results, year, generated_at="2026-11-27T05:00:00+00:00", log=lambda m: None)
        emap.validate_output(out)
        sid1, sid2, sid3, sid4 = fx["sid"]
        stations = read_gz_json(out / "stations.json.gz")
        ids = [r[0] for r in stations["stations"]]
        assert ids == sorted(ids) == [sid1, sid2, sid3, sid4]
        idx = {sid: i for i, sid in enumerate(ids)}
        assert stations["stations_id"] == index["stations_id"]
        # Standarddatum: der 21.11. hat nur 1 von 4 Stationen (<50 %) -> der 20.11. ist der Datenstand
        assert index["default_date"] == f"{year}-11-20", index["default_date"]
        assert index["day_station_counts"]["11-21"] == 1 and index["day_station_counts"]["11-20"] == 3
        assert not (out / "calendar" / "02-29.json.gz").exists()                # 2026 ist kein Schaltjahr

        # --- Tageszeilen gegen unabhängige Rechnung
        s1, c1 = fx["s1"], fx["c1"]
        for mmdd in ("01-15", "07-01", "07-02", "07-03", "07-05", "11-20"):
            day = read_gz_json(out / "calendar" / f"{mmdd}.json.gz")
            assert day["fields"] == emap.DAY_FIELDS and day["date"] == f"{year}-{mmdd}"
            row = next(r for r in day["rows"] if r[0] == idx[sid1])
            f = dict(zip(emap.DAY_FIELDS, row))
            d = date(year, int(mmdd[:2]), int(mmdd[3:]))
            tx, tn = c1[d]
            assert f["tx"] == tx and f["tn"] == tn
            assert f["tx_anom"] == expected_anomaly(s1, E.DEFAULT_REF_INDEX, 0, mmdd, tx), mmdd
            assert f["tn_anom"] == expected_anomaly(s1, E.DEFAULT_REF_INDEX, 1, mmdd, tn), mmdd
            vals_x = [v[0] for dd, v in s1.items() if dd.strftime("%m-%d") == mmdd and v[0] is not None]
            vals_n = [v[1] for dd, v in s1.items() if dd.strftime("%m-%d") == mmdd and v[1] is not None]
            assert f["tx_hi"] == max(vals_x) and f["tx_lo"] == min(vals_x) and f["tx_years"] == len(vals_x)
            assert f["tn_hi"] == max(vals_n) and f["tn_lo"] == min(vals_n) and f["tn_years"] == len(vals_n)
            assert f["tm"] == int(math.floor((tx + tn) / 2.0 + 0.5))
            tm_series = {dd: (None if v[0] is None or v[1] is None else v[0] + v[1], None) for dd, v in s1.items()}
            ok, nrm = brute_normal(tm_series, E.DEFAULT_REF_INDEX, 0, mmdd)
            want = None if nrm is None else int(math.floor(((tx + tn) * 10.0 - nrm) / 20.0 + 0.5))
            assert f["tm_anom"] == want, (mmdd, f["tm_anom"], want)
        # Rekordstatus
        def fld(mmdd, name):
            day = read_gz_json(out / "calendar" / f"{mmdd}.json.gz")
            row = next(r for r in day["rows"] if r[0] == idx[sid1])
            return dict(zip(emap.DAY_FIELDS, row))[name]
        assert fld("07-01", "tx_hi_status") == 1          # gebrochen
        assert fld("07-02", "tx_hi_status") == 2          # eingestellt
        assert fld("07-03", "tx_hi_status") == 0
        assert fld("07-05", "tn_lo_status") == 1          # Tmin-Tiefrekord
        # --- Station ohne Engine: Wert bleibt sichtbar, alles andere ausdrücklich leer
        day = read_gz_json(out / "calendar" / "07-01.json.gz")
        f2 = dict(zip(emap.DAY_FIELDS, next(r for r in day["rows"] if r[0] == idx[sid2])))
        assert f2["tx"] is not None and f2["tx_anom"] is None and f2["tn_anom"] is None and f2["tm_anom"] is None
        assert f2["tx_hi"] is None and f2["tx_hi_status"] == 0 and f2["tx_years"] == 0
        # --- Station mit zu kurzer Reihe (10 Jahre): Rekorde da, Klimamittel nirgends
        f3 = dict(zip(emap.DAY_FIELDS, next(r for r in day["rows"] if r[0] == idx[sid3])))
        assert f3["tx_hi"] is not None and f3["tx_years"] >= 9 and f3["tx_anom"] is None and f3["tn_anom"] is None
        # --- Referenzdateien: S1 mit passenden Referenzen, S2/S3 nie
        for ri, key in enumerate(E.REF_KEYS):
            if ri == E.DEFAULT_REF_INDEX:
                assert not (out / "calendar_ref" / key).exists()
                continue
            ref_day = read_gz_json(out / "calendar_ref" / key / "07-01.json.gz")
            rows = {r[0]: r for r in ref_day["rows"]}
            assert idx[sid2] not in rows and idx[sid3] not in rows
            want_x = expected_anomaly(s1, ri, 0, "07-01", c1[date(year, 7, 1)][0])
            if want_x is None:
                assert idx[sid1] not in rows or rows[idx[sid1]][1] is None
            else:
                assert rows[idx[sid1]][1] == want_x
        # 1951-1980 hat für S1 (ab 1981) nirgends eine Referenz -> Station fehlt in der Referenzdatei
        r0 = read_gz_json(out / "calendar_ref" / "1951_1980" / "07-01.json.gz")
        assert idx[sid1] not in {r[0] for r in r0["rows"]}
        # --- Index: Quellenstatus, Fehlend-Liste, keine stillen Ersatzquellen
        by_key = {s["key"]: s for s in index["sources"]}
        assert [s["status"] for s in index["sources"]] == ["ok", "failed", "planned", "building"]
        assert by_key["test_b"]["stations"] == 0 and by_key["test_c"]["stations"] == 0 and by_key["test_d"]["stations"] == 0
        assert {m["source"] for m in index["missing"]} == {"test_b", "test_c", "test_d"}
        assert index["complete"] is False
        assert by_key["test_a"]["stations"] == 4 and by_key["test_a"]["stations_with_engine"] == 2
        assert by_key["test_a"]["on_default_date"]["stations"] == 3
        assert by_key["test_a"]["on_default_date"]["with_anomaly"] == 1
        assert index["by_country_default_date"]["AT"] == {"stations": 2, "with_anomaly": 1, "source": "test_a"}
        assert index["tmean"]["computed"] is True and index["default_reference"] == "1991_2020"
        assert index["normals_rule"]["min_reference_years"] == 20 and index["normals_rule"]["min_valid_fraction"] == 0.8
        assert index["record_year_options"] == [30, 50, 75, 100]
        assert [r["key"] for r in index["references"]] == ["1951_1980", "1961_1990", "1971_2000", "1981_2010", "1991_2020"]
        # --- Prüfung schlägt bei beschädigtem Export an
        broken = Path(tmp) / "broken"
        shutil.copytree(out, broken)
        (broken / "calendar_ref" / "1961_1990" / "11-20.json.gz").unlink()
        try:
            emap.validate_output(broken)
            raise AssertionError("fehlende Referenzdatei muss auffallen")
        except Exception as exc:
            assert "AssertionError" not in type(exc).__name__
        idx_path = broken / "index.json"
        payload = json.loads(idx_path.read_text(encoding="utf-8"))
        payload["sources"][1]["stations"] = 5                                    # nicht-ok-Quelle mit Stationen = Quellenwechsel
        shutil.copytree(out, Path(tmp) / "broken2")
        (Path(tmp) / "broken2" / "index.json").write_text(json.dumps(payload), encoding="utf-8")
        try:
            emap.validate_output(Path(tmp) / "broken2")
            raise AssertionError("Quellenwechsel muss auffallen")
        except RuntimeError as exc:
            assert "Quellenwechsel" in str(exc)
        # --- Deterministisch: gleiche Eingabe = byte-identische Dateien (kein Git-Rauschen)
        out2 = Path(tmp) / "again"
        emap.write_map(out2, results, year, generated_at="2026-11-27T05:00:00+00:00", log=lambda m: None)
        files1 = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
        files2 = sorted(p.relative_to(out2) for p in out2.rglob("*") if p.is_file())
        assert files1 == files2 and all((out / p).read_bytes() == (out2 / p).read_bytes() for p in files1)
        # --- Sicherheit: fremdes Verzeichnis wird nicht gelöscht
        foreign = Path(tmp) / "europe_stations"
        foreign.mkdir()
        (foreign / "stations.json").write_text("{}", encoding="utf-8")
        try:
            emap.write_map(foreign, results, year, log=lambda m: None)
            raise AssertionError("fremdes Verzeichnis darf nicht gelöscht werden")
        except RuntimeError as exc:
            assert "nichts gelöscht" in str(exc)
        assert (foreign / "stations.json").exists()
        # --- keine Daten: klare Fehlermeldung
        try:
            emap.write_map(Path(tmp) / "nothing", [results[1], results[2]], year, log=lambda m: None)
            raise AssertionError
        except RuntimeError as exc:
            assert "nichts zu exportieren" in str(exc)
    passed("Export: Zeilen = unabhängige Rechnung, Fehlend-Status ausdrücklich, deterministisch, Schutz vor Löschen")


def test_export_leap_day() -> None:
    year = 2028
    s1 = synth(1981, 2025, 121, gap=0.0, half_missing=0.0)
    c1 = synth(year, year, 122, gap=0.0, half_missing=0.0)
    res = src.SourceResult("t", "T", "A", ("XX",), status="ok")
    res.stations = {"T:1": fake_meta("T:1")}
    res.engines = {"T:1": src_finalize(s1)}
    res.current = {"T:1": current_from_series(c1, year, date(year, 3, 10))}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "m"
        index = emap.write_map(out, [res], year, generated_at="x", log=lambda m: None)
        emap.validate_output(out)
        day = read_gz_json(out / "calendar" / "02-29.json.gz")
        row = dict(zip(emap.DAY_FIELDS, day["rows"][0]))
        n_leap = sum(1 for y in range(1981, 2026) if y % 4 == 0)                  # 11 Schaltjahre
        assert row["tx_years"] == n_leap and row["tn_years"] == n_leap
        assert row["tx_anom"] == expected_anomaly(s1, E.DEFAULT_REF_INDEX, 0, "02-29", c1[date(year, 2, 29)][0])
    passed("Export: 29. Februar (Messjahre = nur Schaltjahre, Anomalie wie Brute-Force)")


def test_runner() -> None:
    keys = lambda specs: [s.key for s in specs]
    assert keys(src.select_specs(None)) == ["dwd_de", "meteofrance_fr", "chmi_cz", "ghcn_rest", "geosphere_at", "imgw_pl",
                                           "meteoswiss_ch", "knmi_nl", "rmi_be", "aemet_es"]
    assert keys(src.select_specs(["A"])) == ["dwd_de", "meteofrance_fr", "chmi_cz", "ghcn_rest"]
    assert keys(src.select_specs(["dwd_de", "A"]))[:2] == ["dwd_de", "meteofrance_fr"] and len(src.select_specs(["dwd_de", "A"])) == 4
    try:
        src.select_specs(["xx"])
        raise AssertionError
    except ValueError:
        pass
    assert src.classify_error(src.BaselineIncomplete("x")) == "building"
    assert src.classify_error(RuntimeError("Météo-France Schnellpass noch unvollständig: 3 von 400")) == "building"
    assert src.classify_error(RuntimeError("HTTP 500")) == "failed"

    def ok_run(ctx, res):
        res.stations = {"X:1": fake_meta("X:1")}
        res.current = {"X:1": {"TMAX": {}, "TMIN": {}}}
        res.engines = {"X:1": {}}
        res.status, res.message = "ok", "fein"
        return res

    def boom(ctx, res):
        res.stations = {"Y:1": fake_meta("Y:1")}               # Teilzustand darf nicht durchsickern
        raise RuntimeError("boom")

    def incomplete(ctx, res):
        raise src.BaselineIncomplete("noch im Aufbau")

    fake = (src.Spec("ok1", "Ok", "A", ("XX",), ok_run), src.Spec("bad", "Bad", "A", ("YY",), boom),
            src.Spec("inc", "Inc", "B1", ("ZZ",), incomplete), src.Spec("plan", "Plan", "B2.2", ("DK",)),
            src.Spec("skip", "Skip", "C", ("GB",), ok_run))
    real = src.SPECS
    src.SPECS = fake
    try:
        ctx = src.Ctx(year=2026, cache_dir=Path(tempfile.gettempdir()) / "unused", log=lambda m: None)
        results = src.run_sources(ctx, [fake[0], fake[1], fake[2], fake[3]])
    finally:
        src.SPECS = real
    st = {r.key: r for r in results}
    assert [r.status for r in results] == ["ok", "failed", "building", "planned", "planned"]
    assert st["bad"].stations == {} and st["bad"].current == {} and "boom" in st["bad"].message
    assert st["skip"].message == "in diesem Lauf nicht ausgewählt" and st["plan"].message.startswith("Adapter noch nicht")
    assert st["ok1"].stations and not st["skip"].stations
    passed("Quellenlauf: Fehler/Aufbau/geplant sichtbar, kein Teilzustand, Länder stoppen sich nicht gegenseitig")


def test_run_knmi_integration() -> None:
    """Gesamter Quellenlauf Niederlande mit Netz-Platzhaltern: Baseline, Engine-Cache, aktuelle Daten, Metadaten, Aufbau-Status."""
    if not (have("update_knmi_netherlands_station_cache") and allsrc_or_none()):
        return skipped("Quellenlauf KNMI", "Modul fehlt")
    kn = importlib.import_module("update_knmi_netherlands_station_cache")
    # Use the real current module if installed, but replace its network entry point
    # for the duration of this offline integration test.
    cur_mod = importlib.import_module("update_knmi_netherlands_current")
    real_build_current = getattr(cur_mod, "build_current", None)
    s260, s280 = synth(1986, 2025, 61), synth(1986, 2025, 62)
    both = {"260": s260, "280": s280}
    year = 2026
    cur26 = {"260": synth(year, year, 63, gap=0, half_missing=0), "280": synth(year, year, 64, gap=0, half_missing=0)}
    calls = {"req": 0, "cur": 0}

    def fake_request(start: date, end: date) -> str:
        calls["req"] += 1
        return knmi_text(both, start, end)

    def fake_build_current(cache_dir, y):
        calls["cur"] += 1
        records = {}
        for stn, series in cur26.items():
            cal_x, cal_n = {}, {}
            for d, (tx, tn) in series.items():
                if d <= date(year, 11, 20):
                    iso = d.isoformat()
                    cal_x[d.strftime("%m-%d")] = [tx / 10.0, iso]
                    cal_n[d.strftime("%m-%d")] = [tn / 10.0, iso]
            records[stn] = {"calendar_tmax": cal_x, "calendar_tmin": cal_n}
        inventory = kn.parse_station_metadata(knmi_text(both, date(2025, 1, 1), date(2025, 1, 2)))
        path = Path(cache_dir) / f"knmi_current_{y}.pkl.gz"
        kn.atomic_pickle_gzip(path, {"records": records, "inventory": inventory})
        return path

    real_req, real_start = kn.request_knmi, kn.START_YEAR
    kn.request_knmi, kn.START_YEAR = fake_request, 1986
    cur_mod.build_current = fake_build_current
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = src.Ctx(year=year, cache_dir=Path(tmp), log=lambda m: None, _ghcn_all={})
            ctx.workers = 2
            spec = src.SPEC_BY_KEY["knmi_nl"]
            res = src.run_knmi(ctx, src.SourceResult(spec.key, spec.label, spec.stage, spec.countries))
            assert res.status == "ok", res.message
            assert sorted(res.stations) == ["KNMI:260", "KNMI:280"] and sorted(res.engines) == ["KNMI:260", "KNMI:280"]
            assert sorted(res.current) == ["KNMI:260", "KNMI:280"]
            assert res.stations["KNMI:260"].country_code == "NL" and abs(res.stations["KNMI:260"].lat - 52.0) < 0.5
            check_engine_against_series(res.engines["KNMI:260"], s260, step=29)
            assert res.current["KNMI:260"]["TMAX"]["07-01"][0] == cur26["260"][date(year, 7, 1)][0]
            n_req = calls["req"]
            # zweiter Lauf: Engine-Cache, keine Baseline-Abrufe
            res2 = src.run_knmi(ctx, src.SourceResult(spec.key, spec.label, spec.stage, spec.countries))
            assert res2.status == "ok" and calls["req"] == n_req and sorted(res2.engines) == sorted(res.engines)
            # Export aus dem Quellenlauf
            out = Path(tmp) / "map"
            index = emap.write_map(out, [res2], year, generated_at="x", log=lambda m: None)
            emap.validate_output(out)
            assert index["default_date"] == f"{year}-11-20"
            # Baseline im Aufbau (Laufzeitgrenze 0) -> Status "building" statt Ersatzquelle
            ctx_b = src.Ctx(year=year, cache_dir=Path(tmp) / "fresh", log=lambda m: None, _ghcn_all={}, max_runtime_minutes=0.0)
            real_specs = src.SPECS
            src.SPECS = (spec,)
            try:
                out_b = src.run_sources(ctx_b, [spec])
            finally:
                src.SPECS = real_specs
            assert out_b[0].status == "building" and "im Aufbau" in out_b[0].message and not out_b[0].stations
    finally:
        src.uninstall_hooks()
        kn.request_knmi, kn.START_YEAR = real_req, real_start
        if real_build_current is None:
            del cur_mod.build_current
        else:
            cur_mod.build_current = real_build_current
    passed("Quellenlauf Niederlande: Baseline -> Engine-Cache -> Export; Aufbau-Status statt Ersatzquelle")


def test_cli() -> None:
    import update_europe_anomaly_map as cli
    year = 2026
    results, fx = build_export_fixture(year)
    ok_res = results[0]

    def run_ok(ctx, res):
        for k in ("stations", "engines", "current", "status", "message", "notes"):
            setattr(res, k, getattr(ok_res, k))
        return res

    def run_bad(ctx, res):
        raise RuntimeError("Quelle nicht erreichbar")

    fake = (src.Spec("t_ok", "T ok", "A", ("XX",), run_ok), src.Spec("t_bad", "T bad", "A", ("NL",), run_bad),
            src.Spec("t_plan", "T plan", "B2.2", ("DK",)))
    real, real_by_key = src.SPECS, src.SPEC_BY_KEY
    src.SPECS, src.SPEC_BY_KEY = fake, {s.key: s for s in fake}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "m"
            args = ["--year", str(year), "--output", str(out), "--cache-dir", str(Path(tmp) / "c"), "--sources", "t_ok,t_bad"]
            assert cli.main(args) == 0 and (out / "index.json").exists()                    # nicht strikt: Karte mit Lücken
            import json
            idx = json.loads((out / "index.json").read_text(encoding="utf-8"))
            assert {m["source"] for m in idx["missing"]} == {"t_bad", "t_plan"} and idx["complete"] is False
            out2 = Path(tmp) / "m2"
            assert cli.main(args[:3] + [str(out2)] + args[4:] + ["--strict"]) == 1 and (out2 / "index.json").exists()
            out3 = Path(tmp) / "m3"
            assert cli.main(["--year", str(year), "--output", str(out3), "--cache-dir", str(Path(tmp) / "c"), "--sources", "t_bad"]) == 1
            assert not out3.exists()                                                         # nichts exportiert, wenn keine Quelle liefert
            assert cli.main(["--baseline-only", "--year", str(year), "--output", str(out3), "--cache-dir", str(Path(tmp) / "c"), "--sources", "t_ok"]) == 0
            assert not out3.exists()
    finally:
        src.SPECS, src.SPEC_BY_KEY = real, real_by_key
    passed("Kommandozeile: Exit-Codes, --strict, nichts exportieren ohne Daten, --baseline-only")


# =========================================================================== Ablauf
def setup_paths() -> None:
    here = Path(__file__).resolve().parent
    for cand in (here, here / "adapters"):
        if cand.is_dir() and str(cand) not in sys.path:
            sys.path.insert(0, str(cand))


def test_engine_selftest() -> None:
    E.self_test()
    passed("Engine-Selbsttest: Normale, 80-%-Regel, Rekorde, Zusammenführen, Schaltjahre")


TESTS = [
    test_engine_selftest,
    test_core_dwd, test_core_ghcn, test_core_meteofrance, test_austria, test_poland,
    test_aemet, test_knmi, test_belgium, test_meteoswiss, test_chmi_packed,
    test_export, test_export_leap_day, test_runner, test_run_knmi_integration, test_cli,
]


def run_all(only: str = "") -> None:
    setup_paths()
    stubbed = stub_missing_modules()
    if stubbed:
        print(f"(Test-Platzhalter für {len(stubbed)} nicht vorhandene Länder-Module; sie werden von diesen Tests nicht benutzt)")
    for fn in TESTS:
        if only and only not in fn.__name__:
            continue
        fn()
    print(f"\n{len(PASSED)} Tests bestanden, {len(SKIPPED)} übersprungen.")
    if SKIPPED:
        for name, why in SKIPPED:
            print(f"  übersprungen: {name} ({why})")


if __name__ == "__main__":
    run_all(sys.argv[1] if len(sys.argv) > 1 else "")
