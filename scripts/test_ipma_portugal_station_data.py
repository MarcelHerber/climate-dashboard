#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

UA = "climate-dashboard-ipma-portugal-probe/3.0 (+GitHub Actions)"

STATION_JSON = (
    "https://www.ipma.pt/pt/oclima/series.longas/"
    "list-long-series-stations.json"
)
DATA_BASE = (
    "https://api.ipma.pt/open-data/observation/climate/"
    "monthly-long-series/"
)


def fetch(url: str, timeout: int = 90, attempts: int = 3) -> bytes:
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if not raw:
                    raise RuntimeError("leere Antwort")
                return raw
        except Exception as exc:
            last = exc
            print(f"WARNUNG {attempt}/{attempts}: {url}: {exc}", flush=True)
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Download fehlgeschlagen: {url}: {last}")


def colnum(cell_ref: str) -> int:
    m = re.match(r"([A-Z]+)", cell_ref or "")
    if not m:
        return -1
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_shared_strings(z: zipfile.ZipFile):
    path = "xl/sharedStrings.xml"
    if path not in z.namelist():
        return []

    root = ET.fromstring(z.read(path))
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    out = []
    for si in root.findall("a:si", ns):
        texts = [t.text or "" for t in si.findall(".//a:t", ns)]
        out.append("".join(texts))
    return out


def workbook_sheets(z: zipfile.ZipFile):
    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_pkg = "http://schemas.openxmlformats.org/package/2006/relationships"

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))

    relmap = {}
    for rel in rels.findall(f"{{{ns_pkg}}}Relationship"):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            relmap[rid] = target

    sheets = []
    for s in wb.findall(f".//{{{ns_main}}}sheet"):
        name = s.attrib.get("name")
        rid = s.attrib.get(f"{{{ns_rel}}}id")
        target = relmap.get(rid)
        if target:
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
        sheets.append((name, target))
    return sheets


def parse_sheet(z: zipfile.ZipFile, path: str, shared):
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(z.read(path))
    rows = []

    for r in root.findall(".//a:sheetData/a:row", ns):
        vals = {}
        for c in r.findall("a:c", ns):
            ref = c.attrib.get("r", "")
            idx = colnum(ref)
            ctype = c.attrib.get("t")
            v = c.find("a:v", ns)

            value = ""
            if ctype == "inlineStr":
                t = c.find(".//a:t", ns)
                value = t.text if t is not None and t.text is not None else ""
            elif v is not None and v.text is not None:
                raw = v.text
                if ctype == "s":
                    try:
                        value = shared[int(raw)]
                    except Exception:
                        value = raw
                elif ctype == "b":
                    value = "TRUE" if raw == "1" else "FALSE"
                else:
                    value = raw

            vals[idx] = value

        if vals:
            width = max(vals) + 1
            row = [""] * width
            for idx, val in vals.items():
                if idx >= 0:
                    row[idx] = val
            rows.append((int(r.attrib.get("r", len(rows) + 1)), row))

    return rows


def print_rows(label, rows, n=12):
    print(f"\n--- {label} ---")
    print(f"Nichtleere Zeilen: {len(rows):,}")

    print("Erste Zeilen:")
    for rn, row in rows[:n]:
        print(f"R{rn}: " + " | ".join(str(x) for x in row))

    print("Letzte Zeilen:")
    for rn, row in rows[-n:]:
        print(f"R{rn}: " + " | ".join(str(x) for x in row))


def inspect_xlsx(url: str):
    print("\n============================================================")
    print("TÄGLICHE TEMPERATUR-XLSX PRÜFEN")
    print("============================================================")
    print(f"URL: {url}")

    raw = fetch(url)
    print(f"Bytes: {len(raw):,}")
    print(f"Magic: {raw[:8]!r}")

    if not raw.startswith(b"PK"):
        print("Datei ist kein XLSX/ZIP-Container.")
        print(raw[:1000])
        return

    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        shared = read_shared_strings(z)
        sheets = workbook_sheets(z)

        print(f"Shared strings: {len(shared):,}")
        print(f"Sheets: {len(sheets):,}")
        for i, (name, path) in enumerate(sheets, 1):
            print(f"Sheet {i}: {name!r} -> {path}")

        for name, path in sheets:
            if not path or path not in z.namelist():
                print(f"\nWARNUNG Sheet fehlt im ZIP: {name!r} -> {path}")
                continue

            rows = parse_sheet(z, path, shared)
            print_rows(f"SHEET {name}", rows, n=14)

            # Search for temperature/date-like labels in the first ~80 rows.
            labels = []
            for rn, row in rows[:80]:
                joined = " | ".join(str(x) for x in row)
                low = joined.lower()
                if any(
                    k in low
                    for k in (
                        "tmin",
                        "tmax",
                        "min",
                        "max",
                        "temper",
                        "date",
                        "data",
                        "year",
                        "ano",
                        "month",
                        "mes",
                        "mês",
                        "day",
                        "dia",
                    )
                ):
                    labels.append((rn, joined))

            print("Mögliche Header-/Parameterzeilen:")
            for rn, joined in labels[:30]:
                print(f"R{rn}: {joined}")

            # Candidate data rows: at least 3 numeric-ish cells.
            numeric_like = []
            for rn, row in rows:
                count = 0
                for value in row:
                    s = str(value).strip()
                    if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
                        count += 1
                if count >= 3:
                    numeric_like.append((rn, row))

            print(f"Numerisch wirkende Datenzeilen: {len(numeric_like):,}")
            print("Erste numerische Datenzeilen:")
            for rn, row in numeric_like[:8]:
                print(f"R{rn}: " + " | ".join(str(x) for x in row))
            print("Letzte numerische Datenzeilen:")
            for rn, row in numeric_like[-8:]:
                print(f"R{rn}: " + " | ".join(str(x) for x in row))


def main():
    print("============================================================")
    print("IPMA PORTUGAL PROBE V3 · ECHTE DAILY-DATEIEN")
    print("============================================================")
    print("Noch KEIN Cache. Noch KEINE Europa-Integration.")

    raw = fetch(STATION_JSON)
    obj = json.loads(raw.decode("utf-8-sig"))
    stations = obj.get("stationsList", [])

    print(f"\nStations-JSON: {STATION_JSON}")
    print(f"dataUpdate: {obj.get('dataUpdate')}")
    print(f"Beschreibung: {obj.get('description')}")
    print(f"Stationsobjekte: {len(stations):,}")

    daily_temp = []
    daily_prec = []
    daily_press = []
    monthly_homo = []
    monthly_original = []

    print("\n=== STATIONSLISTE ===")
    for st in stations:
        sid = st.get("NEstacao")
        name = st.get("NomeEstacao")
        td = st.get("TempDailyHomo") or ""
        pd = st.get("PrecDailyHomo") or ""
        prd = st.get("PresDailyHomo") or ""
        mh = st.get("MonthlyHomo") or ""
        mv = st.get("MonthlyVal") or ""

        print(
            f"{sid} | {name} | "
            f"TempDailyHomo={td!r} | "
            f"MonthlyHomo={mh!r} | MonthlyVal={mv!r}"
        )

        if td:
            daily_temp.append((sid, name, td))
        if pd:
            daily_prec.append((sid, name, pd))
        if prd:
            daily_press.append((sid, name, prd))
        if mh:
            monthly_homo.append((sid, name, mh))
        if mv:
            monthly_original.append((sid, name, mv))

    print("\n=== VERFÜGBARKEIT ===")
    print(f"Stationen gesamt: {len(stations):,}")
    print(f"Mit TempDailyHomo: {len(daily_temp):,}")
    print(f"Mit PrecDailyHomo: {len(daily_prec):,}")
    print(f"Mit PresDailyHomo: {len(daily_press):,}")
    print(f"Mit MonthlyHomo: {len(monthly_homo):,}")
    print(f"Mit MonthlyVal: {len(monthly_original):,}")

    print("\n=== DAILY TEMPERATURE DATEIEN ===")
    for sid, name, filename in daily_temp:
        url = urllib.parse.urljoin(DATA_BASE, filename)
        print(f"{sid} | {name} | {filename} | {url}")

    if not daily_temp:
        print("Keine TempDailyHomo-Datei vorhanden.")
        return 1

    # Inspect every daily-temperature workbook; current JSON is small.
    for sid, name, filename in daily_temp:
        print(f"\n\nSTATION {sid} · {name}")
        inspect_xlsx(urllib.parse.urljoin(DATA_BASE, filename))

    print("\n============================================================")
    print("FAZIT")
    print("============================================================")
    print(f"Offizielle Langreihen-Stationen: {len(stations):,}")
    print(f"Mit offizieller homogenisierter täglicher Temperaturdatei: {len(daily_temp):,}")
    print()
    print("Bitte den Log dieses Runs schicken.")
    print("Entscheidend:")
    print("1) 'Mit TempDailyHomo'")
    print("2) Sheet-Namen")
    print("3) Header-/Parameterzeilen")
    print("4) erste/letzte numerische Datenzeilen")
    print()
    print(
        "Wenn TempDailyHomo tatsächlich nur für Lisboa/Geofísico vorhanden ist, "
        "reicht die IPMA-Langreihen-Sammlung alleine nicht für einen landesweiten "
        "Portugal-Stationsrekordcache. Dann entscheiden wir im nächsten Schritt "
        "über den sinnvollsten Hybrid mit GHCN."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
