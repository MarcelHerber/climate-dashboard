#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from typing import Iterable

BASES = (
    "https://clidata.met.ie/cli/climate_data/webdata",
    "https://cli.fusio.net/cli/climate_data/webdata",
)
STATION_DETAILS_NAMES = ("StationDetails.csv", "stationdetails.csv")
SAMPLE_NAMES = (
    "Dublin Airport",
    "Valentia Observatory",
    "Cork Airport",
    "Shannon Airport",
    "Malin Head",
    "Belmullet",
    "Casement",
    "Mullingar",
)

UA = "climate-dashboard-ireland-probe/1.0 (+GitHub Actions)"


def fetch(url: str, timeout: int = 45, attempts: int = 3) -> bytes:
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/csv,text/plain,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if not data:
                    raise RuntimeError("leere Antwort")
                return data
        except Exception as exc:
            last = exc
            print(f"WARNUNG Download {attempt}/{attempts} fehlgeschlagen: {url}: {exc}")
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Download fehlgeschlagen: {url}: {last}")


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def fetch_first(candidates: Iterable[str]) -> tuple[str, str]:
    errors = []
    for url in candidates:
        try:
            return url, decode_bytes(fetch(url))
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Kein Kandidat erreichbar:\n" + "\n".join(errors))


def sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:30])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (",", ";", "\t")}
        return max(counts, key=counts.get)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").strip().lower())


def read_station_details():
    candidates = [
        f"{base}/{name}"
        for base in BASES
        for name in STATION_DETAILS_NAMES
    ]
    url, text = fetch_first(candidates)
    delim = sniff_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise RuntimeError("StationDetails ist leer")

    header = [c.strip().lstrip("\ufeff") for c in rows[0]]
    data = rows[1:]
    print("=== MET ÉIREANN STATIONSINVENTAR ===")
    print(f"Quelle: {url}")
    print(f"Trennzeichen: {repr(delim)}")
    print(f"Header ({len(header)}): {' | '.join(header)}")
    print(f"Datenzeilen: {len(data):,}")

    hnorm = [norm(x) for x in header]
    def idx_like(*names):
        wanted = {norm(x) for x in names}
        for i, h in enumerate(hnorm):
            if h in wanted:
                return i
        for i, h in enumerate(hnorm):
            if any(w in h for w in wanted):
                return i
        return None

    idx = {
        "station": idx_like("Station Number", "StationNumber", "Station No", "StationNo"),
        "name": idx_like("Name", "Station Name", "StationName"),
        "county": idx_like("County"),
        "lat": idx_like("Latitude", "Lat"),
        "lon": idx_like("Longitude", "Long", "Lon"),
        "open": idx_like("Open Year", "OpenYear"),
        "close": idx_like("Close Year", "CloseYear"),
        "height": idx_like("Height (m)", "Height", "Elevation"),
    }
    print("Erkannte Spalten:", idx)

    for j, row in enumerate(data[:5], start=1):
        print(f"Beispiel {j}: " + " | ".join(c.strip() for c in row))

    return url, header, data, idx


def cell(row, i):
    if i is None or i >= len(row):
        return ""
    return row[i].strip()


def select_samples(data, idx):
    # Bevorzugt bekannte lange/hauptamtliche Stationen; fällt auf beliebige
    # Stationen mit Stationsnummer zurück.
    chosen = []
    used = set()

    name_idx = idx["name"]
    station_idx = idx["station"]

    for wanted in SAMPLE_NAMES:
        nw = norm(wanted)
        candidates = []
        for row in data:
            name = cell(row, name_idx)
            st = cell(row, station_idx)
            if not st or not re.fullmatch(r"\d+", st):
                continue
            n = norm(name)
            score = 0
            if n == nw:
                score = 100
            elif nw in n or n in nw:
                score = 80
            elif all(part in n for part in nw.split() if part):
                score = 50
            if score:
                candidates.append((score, row))
        candidates.sort(key=lambda x: x[0], reverse=True)
        for _, row in candidates:
            st = cell(row, station_idx)
            if st not in used:
                chosen.append(row)
                used.add(st)
                break

    # Falls Namensabgleich wegen leicht anderer Stationsbezeichnungen
    # nicht reicht: auf bis zu 8 plausible nummerierte Stationen ergänzen.
    if len(chosen) < 8:
        for row in data:
            st = cell(row, station_idx)
            if re.fullmatch(r"\d+", st or "") and st not in used:
                chosen.append(row)
                used.add(st)
                if len(chosen) >= 8:
                    break
    return chosen[:8]


def daily_candidates(station_number: str):
    n = station_number.strip()
    return [f"{base}/dly{n}.csv" for base in BASES]


def detect_daily_header(lines):
    # Daily-Dateien besitzen einen Erläuterungs-/Metadatenblock vor dem CSV-Header.
    for i, line in enumerate(lines):
        s = line.strip().lstrip("\ufeff")
        if not s:
            continue
        low = s.lower()
        # Typischer Met-Éireann-Header beginnt "date,ind,rain,..."
        if re.match(r"^date\s*[,;\t]", low):
            return i
    # Fallback: Zeile mit date + max + min
    for i, line in enumerate(lines):
        low = line.lower()
        if "date" in low and "max" in low and "min" in low:
            return i
    return None


def parse_date(s: str):
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def probe_daily(row, idx):
    st = cell(row, idx["station"])
    name = cell(row, idx["name"]) or "(ohne Name)"
    county = cell(row, idx["county"])
    print("\n" + "=" * 76)
    print(f"STATION {st} · {name}" + (f" · {county}" if county else ""))
    print("=" * 76)

    url, text = fetch_first(daily_candidates(st))
    print(f"URL: {url}")
    print(f"Download: {len(text.encode('utf-8', errors='ignore')) / 1024:.1f} KiB")

    lines = text.splitlines()
    header_i = detect_daily_header(lines)
    print(f"Zeilen gesamt: {len(lines):,}")
    print(f"Messheader-Zeile: {header_i + 1 if header_i is not None else 'NICHT GEFUNDEN'}")

    print("--- Dateivorspann (max. 16 Zeilen) ---")
    for line in lines[:16]:
        print(line[:500])

    if header_i is None:
        return {
            "station": st,
            "name": name,
            "ok": False,
            "reason": "Header nicht gefunden",
        }

    csv_text = "\n".join(lines[header_i:])
    delim = sniff_delimiter(csv_text)
    reader = csv.reader(io.StringIO(csv_text), delimiter=delim)
    rows = list(reader)
    if not rows:
        return {"station": st, "name": name, "ok": False, "reason": "keine CSV-Zeilen"}

    header = [x.strip().lstrip("\ufeff") for x in rows[0]]
    data = [r for r in rows[1:] if any(c.strip() for c in r)]
    print(f"Trennzeichen Messblock: {repr(delim)}")
    print(f"Messdaten-Header ({len(header)}): {' | '.join(header)}")
    print(f"Messdatenzeilen: {len(data):,}")

    for j, r in enumerate(data[:3], 1):
        print(f"Erste Messzeile {j}: " + " | ".join(c.strip() for c in r))
    for j, r in enumerate(data[-3:], 1):
        print(f"Letzte Messzeile {j}: " + " | ".join(c.strip() for c in r))

    hn = [norm(h) for h in header]
    max_cols = [i for i, h in enumerate(hn) if h in {"max", "maxt", "maxtemp", "maximumairtemperature"}]
    min_cols = [i for i, h in enumerate(hn) if h in {"min", "mint", "mintemp", "minimumairtemperature"}]
    date_cols = [i for i, h in enumerate(hn) if h == "date"]

    # Typische Met-Éireann-Struktur: date,ind,rain,ind,max,ind,min,...
    if not max_cols:
        max_cols = [i for i, h in enumerate(hn) if h == "maximum" or ("max" in h and "wind" not in h and "gust" not in h)]
    if not min_cols:
        min_cols = [i for i, h in enumerate(hn) if h == "minimum" or ("min" in h and "wind" not in h)]

    print(f"Erkannte Datumsspalte(n): {date_cols}")
    print(f"Erkannte Tmax-Spalte(n): {max_cols}")
    print(f"Erkannte Tmin-Spalte(n): {min_cols}")

    dates = []
    if date_cols:
        dc = date_cols[0]
        for r in data:
            if dc < len(r):
                d = parse_date(r[dc])
                if d:
                    dates.append(d)
    if dates:
        print(f"Datumsbereich: {min(dates)} bis {max(dates)}")
        print(f"Aktuellstes Datum: {max(dates)}")
    else:
        print("Datumsbereich konnte nicht automatisch erkannt werden.")

    return {
        "station": st,
        "name": name,
        "ok": True,
        "header": tuple(header),
        "delimiter": delim,
        "rows": len(data),
        "first_date": str(min(dates)) if dates else "",
        "last_date": str(max(dates)) if dates else "",
        "has_tmax": bool(max_cols),
        "has_tmin": bool(min_cols),
    }


def main():
    _, header, data, idx = read_station_details()
    if idx["station"] is None:
        raise RuntimeError("Stationsnummer konnte im Stationsinventar nicht erkannt werden.")

    samples = select_samples(data, idx)
    print("\n=== AUSGEWÄHLTE DAILY-STICHPROBE ===")
    for row in samples:
        print(
            f"{cell(row, idx['station'])} | {cell(row, idx['name'])} | "
            f"{cell(row, idx['county'])} | Open={cell(row, idx['open'])} | "
            f"Close={cell(row, idx['close'])}"
        )

    results = []
    for row in samples:
        try:
            results.append(probe_daily(row, idx))
        except Exception as exc:
            st = cell(row, idx["station"])
            name = cell(row, idx["name"])
            print(f"\nFEHLER Station {st} {name}: {exc}")
            results.append({"station": st, "name": name, "ok": False, "reason": str(exc)})

    print("\n=== SCHEMA-ZUSAMMENFASSUNG ===")
    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    print(f"Geprüft: {len(results)} | erfolgreich: {len(ok)} | Fehler: {len(bad)}")

    schemas = Counter((r.get("delimiter"), r.get("header")) for r in ok)
    for k, ((delim, header_tuple), count) in enumerate(schemas.most_common(), 1):
        print(f"\nSchema {k}: {count} Datei(en), delimiter={repr(delim)}")
        print("Header: " + " | ".join(header_tuple or ()))

    print("\n=== TMAX/TMIN-PRÜFUNG ===")
    print(f"Mit erkannter Tmax-Spalte: {sum(bool(r.get('has_tmax')) for r in ok)}/{len(ok)}")
    print(f"Mit erkannter Tmin-Spalte: {sum(bool(r.get('has_tmin')) for r in ok)}/{len(ok)}")
    for r in ok:
        print(
            f"{r['station']} | {r['name']} | Zeilen={r['rows']:,} | "
            f"{r['first_date']} -> {r['last_date']} | "
            f"Tmax={r.get('has_tmax')} | Tmin={r.get('has_tmin')}"
        )

    if bad:
        print("\n=== FEHLER ===")
        for r in bad:
            print(f"{r['station']} | {r['name']} | {r.get('reason')}")

    print("\n=== FAZIT FÜR DEN NÄCHSTEN SCHRITT ===")
    print("Bitte den vollständigen GitHub-Log dieses Probe-Runs schicken.")
    print("Entscheidend sind:")
    print("1) Header des StationDetails-Inventars")
    print("2) Messdaten-Header der Daily-CSV-Dateien")
    print("3) erkannte Tmax/Tmin-Spalten")
    print("4) Datumsbereich bzw. Aktualität der Daily-Dateien")
    print("Erst danach bauen wir den historischen Irland-Cache.")

    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
