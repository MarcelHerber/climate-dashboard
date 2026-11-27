#!/usr/bin/env python3
"""Export des Europa-Anomalie- und Rekordmonitors als statische, gzip-komprimierte JSON-Dateien.

Ausgabe (``<output>/``)
  index.json                        Metadaten, Referenzen, Regeln, Quellen mit Status, Abdeckung, Datenstand
  stations.json.gz                  Stationsverzeichnis (einmal; die Tagesdateien verweisen per Index darauf)
  calendar/<mm-dd>.json.gz          Tageswerte, Anomalien der Standardreferenz, Rekorde, Messjahre
  calendar_ref/<ref>/<mm-dd>.json.gz  Anomalien der übrigen Referenzperioden (nur Stationen mit Referenz)

Fehlendes wird nie ersetzt:
* Station hat einen Tageswert, aber keine Referenz -> Zeile bleibt, Anomalie = null (die Referenzdatei enthält sie nicht).
* Quelle fehlt/ist im Aufbau/ist nur geplant -> Eintrag in ``sources`` und ``missing`` mit Status und Meldung.
Tmean ist überall (Tmax+Tmin)/2 und im Index ausdrücklich als berechnet gekennzeichnet.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import europe_climate_engine as E

MAP_VERSION = 1

DAY_FIELDS = [
    "idx",
    "tx", "tx_anom", "tx_hi", "tx_hi_status", "tx_lo", "tx_lo_status", "tx_years",
    "tn", "tn_anom", "tn_hi", "tn_hi_status", "tn_lo", "tn_lo_status", "tn_years",
    "tm", "tm_anom",
]
REF_FIELDS = ["idx", "tx_anom", "tn_anom", "tm_anom"]
STATION_FIELDS = ["id", "name", "lat", "lon", "elev", "country", "source"]
ROW_WIDTH = len(DAY_FIELDS)
REF_LABELS = {k: f"{a}–{b}" for k, (a, b) in zip(E.REF_KEYS, E.REFERENCES)}

# Standardreferenz zuerst, dann der Rest in zeitlicher Reihenfolge
REF_ORDER = [E.DEFAULT_REF_INDEX] + [i for i in range(len(E.REFERENCES)) if i != E.DEFAULT_REF_INDEX]


def _gz_json(path: Path, payload: Any) -> int:
    """Deterministisch (mtime=0, feste Schlüsselreihenfolge): unveränderte Tage ergeben identische Dateien."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    data = buf.getvalue()
    path.write_bytes(data)
    return len(data)


def _tm_tenths(tx: Optional[int], tn: Optional[int]) -> Optional[int]:
    """Tmean = (Tmax+Tmin)/2 in Zehntelgrad, kaufmännisch gerundet; nur wenn beide Werte vorliegen."""
    if tx is None or tn is None:
        return None
    return int(math.floor((tx + tn) / 2.0 + 0.5))


def _record_pair(block: Optional[dict], which: str, pos: int, current: Optional[int], higher: bool) -> Tuple[Optional[int], int]:
    rec = E.record_at(block, which, pos)
    if rec is None:
        return None, 0
    return rec[0], E.record_status(current, rec, higher)


def station_order(results: Iterable[Any]) -> Tuple[List[str], Dict[str, Any], Dict[str, Any], Dict[str, int]]:
    """Alle Stationen mit Metadaten und Daten im laufenden Jahr, sortiert nach Kennung.

    Rückgabe: (ids, meta, source_of, without_meta_by_source)
    """
    meta: Dict[str, Any] = {}
    source_of: Dict[str, Any] = {}
    without_meta: Dict[str, int] = {}
    for res in results:
        if res.status != "ok":
            continue
        for sid in res.current:
            m = res.stations.get(sid)
            if m is None:
                without_meta[res.key] = without_meta.get(res.key, 0) + 1
                continue
            if sid in meta:                       # gleiche Kennung aus zwei Quellen: erste Quelle gewinnt, kein Mischen
                continue
            meta[sid] = m
            source_of[sid] = res
    ids = sorted(meta)
    return ids, meta, source_of, without_meta


def day_counts(ids: List[str], source_of: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for sid in ids:
        cur = source_of[sid].current[sid]
        days = set(cur.get("TMAX", {})) | set(cur.get("TMIN", {}))
        for mmdd in days:
            counts[mmdd] = counts.get(mmdd, 0) + 1
    return counts


def pick_default_date(counts: Dict[str, int], year: int, min_share: float = 0.5, window: int = 14) -> Optional[str]:
    """Neuester Tag mit mindestens ``min_share`` der Stationszahl der letzten Tage (nicht der halbfertige Tag von heute)."""
    dated = {}
    for mmdd, n in counts.items():
        try:
            dated[dt.date(year, int(mmdd[:2]), int(mmdd[3:]))] = n
        except ValueError:
            continue
    for day in sorted(dated, reverse=True):
        recent = [dated[d] for d in dated if 0 <= (day - d).days < window]
        if dated[day] >= min_share * max(recent):
            return day.strftime("%m-%d")
    return None


def _row_for(sid: str, idx: int, res: Any, mmdd: str, pos: int) -> Optional[Tuple[list, list, Optional[int]]]:
    cur = res.current[sid]
    txd = cur.get("TMAX", {}).get(mmdd)
    tnd = cur.get("TMIN", {}).get(mmdd)
    if txd is None and tnd is None:
        return None
    tx = txd[0] if txd else None
    tn = tnd[0] if tnd else None
    tm = _tm_tenths(tx, tn)
    tm2 = None if tx is None or tn is None else tx + tn
    eng = res.engines.get(sid)
    bx = eng.get("TMAX") if eng else None
    bn = eng.get("TMIN") if eng else None
    bm = eng.get("TMEAN") if eng else None
    # Standardreferenz
    d = E.DEFAULT_REF_INDEX
    tx_hi, tx_hi_st = _record_pair(bx, "hi", pos, tx, True)
    tx_lo, tx_lo_st = _record_pair(bx, "lo", pos, tx, False)
    tn_hi, tn_hi_st = _record_pair(bn, "hi", pos, tn, True)
    tn_lo, tn_lo_st = _record_pair(bn, "lo", pos, tn, False)
    row = [
        idx,
        tx, E.anomaly_tenths(bx, d, pos, tx), tx_hi, tx_hi_st, tx_lo, tx_lo_st, E.observed_years_at(bx, pos),
        tn, E.anomaly_tenths(bn, d, pos, tn), tn_hi, tn_hi_st, tn_lo, tn_lo_st, E.observed_years_at(bn, pos),
        tm, E.anomaly_tenths(bm, d, pos, tm2, 2),
    ]
    refs = []
    for ri in range(len(E.REFERENCES)):
        refs.append((ri, E.anomaly_tenths(bx, ri, pos, tx), E.anomaly_tenths(bn, ri, pos, tn), E.anomaly_tenths(bm, ri, pos, tm2, 2)))
    return row, refs, tm


def ensure_cleanable(output_dir: Path) -> None:
    """Löscht nur Verzeichnisse, die leer sind oder von diesem Export stammen (nie z. B. das ganze europe_stations/)."""
    output_dir = Path(output_dir)
    if not output_dir.exists() or not any(output_dir.iterdir()):
        return
    index = output_dir / "index.json"
    try:
        payload = json.loads(index.read_text(encoding="utf-8"))
        if payload.get("fields") == DAY_FIELDS and "stations_id" in payload:
            return
    except Exception:
        pass
    raise RuntimeError(f"{output_dir} ist nicht leer und stammt nicht von diesem Export – es wird nichts gelöscht.")


def write_map(output_dir: Path, results: List[Any], year: int, *, generated_at: Optional[str] = None,
              log=print, clean: bool = True) -> dict:
    output_dir = Path(output_dir)
    ids, meta, source_of, without_meta = station_order(results)
    if not ids:
        raise RuntimeError("Keine Station mit Metadaten und aktuellen Daten – es gibt nichts zu exportieren.")
    counts = day_counts(ids, source_of)
    default_mmdd = pick_default_date(counts, year)
    if default_mmdd is None:
        raise RuntimeError("Kein Tag mit ausreichend vielen Stationen gefunden.")
    index_of = {sid: i for i, sid in enumerate(ids)}
    stations_id = hashlib.sha1("\n".join(ids).encode("utf-8")).hexdigest()[:12]
    source_keys = [r.key for r in results]
    source_idx = {k: i for i, k in enumerate(source_keys)}

    if clean:
        ensure_cleanable(output_dir)
        if output_dir.exists():
            shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stations_payload = {
        "version": MAP_VERSION, "stations_id": stations_id, "fields": STATION_FIELDS,
        "sources": [{"key": r.key, "label": r.label} for r in results],
        "stations": [[sid, meta[sid].name, round(meta[sid].lat, 4), round(meta[sid].lon, 4), meta[sid].elev,
                      meta[sid].country_code, source_idx[source_of[sid].key]] for sid in ids],
    }
    size_stations = _gz_json(output_dir / "stations.json.gz", stations_payload)

    # ---- Tagesdateien
    by_source_default: Dict[str, Dict[str, Any]] = {}
    by_country_default: Dict[str, Dict[str, Any]] = {}
    latest_by_source: Dict[str, str] = {}
    size_days = size_refs = 0
    written_days = 0
    ref_counts_default = {k: 0 for k in E.REF_KEYS}
    for mmdd in sorted(counts, key=lambda m: E.POS[m]):
        pos = E.POS[mmdd]
        rows: List[list] = []
        ref_rows: List[List[list]] = [[] for _ in E.REFERENCES]
        for sid in ids:
            res = source_of[sid]
            built = _row_for(sid, index_of[sid], res, mmdd, pos)
            if built is None:
                continue
            row, refs, _tm = built
            rows.append(row)
            for ri, ax, an, am in refs:
                if ax is not None or an is not None or am is not None:
                    ref_rows[ri].append([row[0], ax, an, am])
            day = None
            for el in ("TMAX", "TMIN"):
                got = res.current[sid].get(el, {}).get(mmdd)
                if got:
                    day = got[1]
            if day:
                iso = f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:8]}"
                if iso > latest_by_source.get(res.key, ""):
                    latest_by_source[res.key] = iso
            if mmdd == default_mmdd:
                has_any = row[2] is not None or row[9] is not None or row[16] is not None
                src = by_source_default.setdefault(res.key, {"stations": 0, "with_anomaly": 0, "by_ref": {k: 0 for k in E.REF_KEYS}})
                src["stations"] += 1
                src["with_anomaly"] += 1 if has_any else 0
                for ri, ax, an, am in refs:
                    if ax is not None or an is not None or am is not None:
                        src["by_ref"][E.REF_KEYS[ri]] += 1
                cc = by_country_default.setdefault(meta[sid].country_code, {"stations": 0, "with_anomaly": 0, "source": res.key})
                cc["stations"] += 1
                cc["with_anomaly"] += 1 if has_any else 0
        iso_date = f"{year}-{mmdd}"
        size_days += _gz_json(output_dir / "calendar" / f"{mmdd}.json.gz", {
            "date": iso_date, "mmdd": mmdd, "stations_id": stations_id, "fields": DAY_FIELDS, "rows": rows})
        for ri, key in enumerate(E.REF_KEYS):
            if ri == E.DEFAULT_REF_INDEX:
                continue
            size_refs += _gz_json(output_dir / "calendar_ref" / key / f"{mmdd}.json.gz", {
                "date": iso_date, "mmdd": mmdd, "stations_id": stations_id, "ref": key, "fields": REF_FIELDS, "rows": ref_rows[ri]})
        if mmdd == default_mmdd:
            for ri, key in enumerate(E.REF_KEYS):
                ref_counts_default[key] = len(ref_rows[ri])
        written_days += 1

    # ---- Index
    sources_info = []
    missing = []
    for res in results:
        info = {
            "key": res.key, "label": res.label, "stage": res.stage, "countries": list(res.countries),
            "status": res.status, "message": res.message, "notes": list(res.notes),
            "stations": sum(1 for sid in ids if source_of[sid] is res),
            "stations_with_engine": sum(1 for sid in ids if source_of[sid] is res and sid in res.engines),
            "stations_without_meta": without_meta.get(res.key, 0),
            "latest_date": latest_by_source.get(res.key),
            "on_default_date": by_source_default.get(res.key, {"stations": 0, "with_anomaly": 0, "by_ref": {k: 0 for k in E.REF_KEYS}}),
        }
        sources_info.append(info)
        if res.status != "ok":
            missing.append({"source": res.key, "label": res.label, "countries": list(res.countries), "stage": res.stage,
                            "status": res.status, "message": res.message})
    complete = not missing
    default_iso = f"{year}-{default_mmdd}"
    index = {
        "version": MAP_VERSION, "ready": True, "year": year,
        "generated_at": generated_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "stations_id": stations_id, "station_count": len(ids),
        "default_date": default_iso, "data_through": default_iso,
        "latest_date_any": max(latest_by_source.values()) if latest_by_source else None,
        "day_count": written_days,
        "day_station_counts": {m: counts[m] for m in sorted(counts, key=lambda m: E.POS[m])},
        "complete": complete,
        "units": "Temperaturen in Zehntelgrad Celsius (ganzzahlig); Tmean-Mittel gerundet auf Zehntelgrad",
        "references": [{"key": k, "label": REF_LABELS[k], "default": k == E.DEFAULT_REF} for k in E.REF_KEYS],
        "default_reference": E.DEFAULT_REF,
        "record_year_options": list(E.RECORD_YEAR_OPTIONS),
        "record_year_rule": ("Rekorde gelten nur für den exakten Kalendertag und nur mit mindestens N tatsächlichen Messjahren an diesem Tag; "
                             "am 29. Februar gilt ein Viertel (30→8, 50→13, 75→19, 100→25)."),
        "normals_rule": {
            "smoothing_days": E.HALF_WINDOW, "window_days": E.WINDOW_DAYS,
            "min_reference_years": E.MIN_QUALIFYING_YEARS, "min_valid_fraction": E.MIN_WINDOW_VALID_FRACTION,
            "text": (f"Klimamittel: gepoolt über ±{E.HALF_WINDOW} Tage; gilt nur, wenn mindestens {E.MIN_QUALIFYING_YEARS} verschiedene "
                     f"Referenzjahre im {E.WINDOW_DAYS}-Tage-Fenster mindestens {int(E.MIN_WINDOW_VALID_FRACTION * 100)} % gültige Tage haben."),
        },
        "tmean": {"definition": "(Tmax+Tmin)/2", "computed": True,
                  "note": "Berechnetes Temperaturmittel, einheitlich in ganz Europa; nur an Tagen mit Tmax und Tmin. "
                          "Für Deutschland bleibt der offizielle DWD-Wert (TMK) in der separaten Deutschlandkarte."},
        "status_codes": {"0": "kein Rekord", "1": "Rekord gebrochen", "2": "Rekord eingestellt"},
        "missing_reference": "Ein Stationswert ohne Referenz erscheint mit anomaly = null; die Referenzdatei enthält diese Station nicht.",
        "fields": DAY_FIELDS, "ref_fields": REF_FIELDS, "station_fields": STATION_FIELDS,
        "sources": sources_info,
        "missing": missing,
        "by_country_default_date": {cc: by_country_default[cc] for cc in sorted(by_country_default)},
        "sizes_bytes": {"stations": size_stations, "calendar": size_days, "calendar_ref": size_refs},
    }
    (output_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Europa-Anomaliekarte: {len(ids):,} Stationen | {written_days} Tage | Standarddatum {default_iso} | "
        f"Dateien: Tage {size_days / 1e6:.1f} MB, Referenzen {size_refs / 1e6:.1f} MB | "
        f"nicht vollständig: {len(missing)} Quelle(n)")
    return index


def _read_gz(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def validate_output(output_dir: Path) -> dict:
    output_dir = Path(output_dir)
    index_path = output_dir / "index.json"
    if not index_path.is_file():
        raise RuntimeError(f"Fehlender Index: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("ready") is not True or index.get("version") != MAP_VERSION:
        raise RuntimeError("Index meldet ready != true oder falsche Version.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(index.get("default_date") or "")):
        raise RuntimeError(f"Ungültiges Standarddatum: {index.get('default_date')!r}")
    if index.get("fields") != DAY_FIELDS or index.get("ref_fields") != REF_FIELDS:
        raise RuntimeError("Feldlisten im Index passen nicht zum Format.")
    stations = _read_gz(output_dir / "stations.json.gz")
    n = len(stations["stations"])
    if stations["stations_id"] != index["stations_id"] or n != index["station_count"]:
        raise RuntimeError("Stationsverzeichnis passt nicht zum Index.")
    mmdd = index["default_date"][5:]
    day = _read_gz(output_dir / "calendar" / f"{mmdd}.json.gz")
    if day["stations_id"] != index["stations_id"]:
        raise RuntimeError("Tagesdatei gehört zu einem anderen Stationsverzeichnis.")
    rows = day["rows"]
    if not rows:
        raise RuntimeError("Tagesdatei des Standarddatums ist leer.")
    for row in rows:
        if len(row) != ROW_WIDTH or not (0 <= row[0] < n):
            raise RuntimeError(f"Tageszeile hat falsche Breite oder ungültigen Stationsindex: {row[:3]}")
    if not any(r[2] is not None or r[9] is not None for r in rows):
        raise RuntimeError("Keine einzige Anomalie am Standarddatum – Klimamittel fehlen vollständig.")
    for ref in index["references"]:
        if ref["default"]:
            continue
        ref_day = _read_gz(output_dir / "calendar_ref" / ref["key"] / f"{mmdd}.json.gz")
        if ref_day["stations_id"] != index["stations_id"]:
            raise RuntimeError(f"Referenzdatei {ref['key']} gehört zu einem anderen Stationsverzeichnis.")
        if any(len(r) != len(REF_FIELDS) or not (0 <= r[0] < n) for r in ref_day["rows"]):
            raise RuntimeError(f"Referenzdatei {ref['key']} hat ein unerwartetes Format.")
    for src in index["sources"]:
        if src["status"] not in ("ok", "failed", "building", "planned"):
            raise RuntimeError(f"Unbekannter Quellenstatus: {src['status']}")
        if src["status"] != "ok" and src["stations"]:
            raise RuntimeError(f"Quelle {src['key']} ist nicht ok, liefert aber Stationen (Quellenwechsel?).")
    listed = {m["source"] for m in index["missing"]}
    for src in index["sources"]:
        if src["status"] != "ok" and src["key"] not in listed:
            raise RuntimeError(f"Quelle {src['key']} fehlt im Index unter 'missing'.")
    print(f"Europa-Anomaliekarte OK: {index['station_count']} Stationen | {index['default_date']} | "
          f"{len(index['missing'])} fehlende/unvollständige Quelle(n) ausgewiesen")
    return index
