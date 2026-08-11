#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import io
import math
import re
import statistics
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date

UA = "climate-dashboard-portugal-lisboa-crosswalk/1.0 (+GitHub Actions)"

GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
STATIONS_URL = f"{GHCN_BASE}/ghcnd-stations.txt"
INVENTORY_URL = f"{GHCN_BASE}/ghcnd-inventory.txt"
BY_STATION = f"{GHCN_BASE}/by_station"

IPMA_XLSX = (
    "https://api.ipma.pt/open-data/observation/climate/monthly-long-series/"
    "tmintmaxdaily_1855-2018_Lisbon-Geofisico.xlsx"
)

# Official IPMA Lisboa/Geofísico metadata
IPMA_ID = "535"
IPMA_NAME = "Lisboa/Geofísico"
IPMA_LAT = 38 + 42 / 60 + 59.4 / 3600
IPMA_LON = -(9 + 8 / 60 + 56.7 / 3600)
IPMA_ELEV = 77.0

EXPECTED_WMO = "08535"
EXPECTED_GHCN = "POM00008535"


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    if not raw:
        raise RuntimeError(f"Leere Antwort: {url}")
    return raw


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def parse_stations(text: str):
    out = {}
    for line in text.splitlines():
        if len(line) < 85:
            continue
        sid = line[0:11].strip()
        if not sid.startswith("PO"):
            continue
        try:
            lat = float(line[12:20].strip())
            lon = float(line[21:30].strip())
            elev_raw = line[31:37].strip()
            elev = float(elev_raw) if elev_raw else None
        except ValueError:
            continue

        out[sid] = {
            "id": sid,
            "lat": lat,
            "lon": lon,
            "elev": elev,
            "name": line[41:71].strip(),
            "gsn": line[72:75].strip(),
            "hcn": line[76:79].strip(),
            "wmo": line[80:85].strip(),
        }
    return out


def parse_inventory(text: str):
    inv = defaultdict(dict)
    for line in text.splitlines():
        if len(line) < 45:
            continue
        sid = line[0:11].strip()
        if not sid.startswith("PO"):
            continue
        element = line[31:35].strip()
        if element not in {"TMAX", "TMIN"}:
            continue
        try:
            first = int(line[36:40].strip())
            last = int(line[41:45].strip())
        except ValueError:
            continue
        inv[sid][element] = (first, last)
    return inv


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


def parse_sheet_rows(z, path, shared):
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(z.read(path))
    rows = []

    for r in root.findall(".//a:sheetData/a:row", ns):
        vals = {}
        for c in r.findall("a:c", ns):
            idx = colnum(c.attrib.get("r", ""))
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
                else:
                    value = raw
            vals[idx] = value

        if vals:
            width = max(vals) + 1
            row = [""] * width
            for idx, value in vals.items():
                if idx >= 0:
                    row[idx] = value
            rows.append(row)
    return rows


def num(x):
    try:
        return float(str(x).strip())
    except Exception:
        return None


def parse_ipma_daily():
    raw = fetch(IPMA_XLSX)
    if not raw.startswith(b"PK"):
        raise RuntimeError("IPMA-Datei ist kein XLSX")

    best = None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        shared = read_shared_strings(z)
        sheets = workbook_sheets(z)

        print("\n=== IPMA XLSX SHEETS ===")
        for name, path in sheets:
            print(f"{name!r} -> {path}")

        for name, path in sheets:
            if not path or path not in z.namelist():
                continue
            rows = parse_sheet_rows(z, path, shared)

            daily = {}
            rejected = 0

            for row in rows:
                if len(row) < 5:
                    continue
                y = num(row[0])
                m = num(row[1])
                d = num(row[2])
                tmin = num(row[3])
                tmax = num(row[4])

                if None in (y, m, d):
                    continue
                y, m, d = int(y), int(m), int(d)
                if not (1800 <= y <= 2020):
                    continue
                try:
                    dt = date(y, m, d)
                except ValueError:
                    rejected += 1
                    continue

                if tmin is None and tmax is None:
                    continue

                daily[dt.isoformat()] = {
                    "TMIN": tmin,
                    "TMAX": tmax,
                }

            print(
                f"Sheet {name!r}: erkannte Tagesdaten={len(daily):,} | "
                f"ungültige Kalenderzeilen={rejected:,}"
            )
            if daily:
                dates = sorted(daily)
                print(f"  Bereich: {dates[0]} bis {dates[-1]}")
                print(f"  Erste: {dates[0]} -> {daily[dates[0]]}")
                print(f"  Letzte: {dates[-1]} -> {daily[dates[-1]]}")

            if best is None or len(daily) > len(best[1]):
                best = (name, daily)

    if best is None or not best[1]:
        raise RuntimeError("Keine IPMA-Tagesdaten aus XLSX erkannt")

    return best


def parse_ghcn_station(sid: str):
    url = f"{BY_STATION}/{sid}.csv.gz"
    raw = fetch(url)
    text = gzip.decompress(raw).decode("utf-8", errors="replace")

    data = defaultdict(dict)
    qflagged = defaultdict(int)
    counts = defaultdict(int)

    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 7:
            continue
        rsid, datestr, element, value = row[:4]
        if element not in {"TMAX", "TMIN"}:
            continue

        qflag = row[5].strip()
        counts[element] += 1
        if qflag:
            qflagged[element] += 1
            continue

        try:
            v = int(value) / 10.0
            dt = date(
                int(datestr[0:4]),
                int(datestr[4:6]),
                int(datestr[6:8]),
            ).isoformat()
        except Exception:
            continue
        data[dt][element] = v

    return {
        "url": url,
        "data": dict(data),
        "counts": dict(counts),
        "qflagged": dict(qflagged),
    }


def pearson(xs, ys):
    if len(xs) < 2:
        return None
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(sx * sy)


def compare(ipma, ghcn, element: str):
    dates = sorted(set(ipma) & set(ghcn))
    pairs = []
    for d in dates:
        a = ipma[d].get(element)
        b = ghcn[d].get(element)
        if a is None or b is None:
            continue
        pairs.append((d, float(a), float(b), float(b) - float(a)))

    if not pairs:
        return None

    diffs = [p[3] for p in pairs]
    absdiffs = [abs(x) for x in diffs]
    xs = [p[1] for p in pairs]
    ys = [p[2] for p in pairs]

    sorted_abs = sorted(absdiffs)
    p95_idx = min(len(sorted_abs) - 1, int(round(0.95 * (len(sorted_abs) - 1))))

    worst = sorted(pairs, key=lambda x: abs(x[3]), reverse=True)[:12]

    return {
        "n": len(pairs),
        "first": pairs[0][0],
        "last": pairs[-1][0],
        "bias_ghcn_minus_ipma": statistics.fmean(diffs),
        "mae": statistics.fmean(absdiffs),
        "median_abs": statistics.median(absdiffs),
        "p95_abs": sorted_abs[p95_idx],
        "max_abs": max(absdiffs),
        "within_0_1": sum(x <= 0.1000001 for x in absdiffs),
        "within_0_5": sum(x <= 0.5000001 for x in absdiffs),
        "corr": pearson(xs, ys),
        "worst": worst,
    }


def print_comparison(sid, element, stats):
    print(f"\n{sid} · {element}")
    if stats is None:
        print("  Keine gemeinsamen gültigen Tageswerte.")
        return
    print(
        f"  Überlappung: {stats['n']:,} Tage | "
        f"{stats['first']} bis {stats['last']}"
    )
    print(
        f"  Bias GHCN-IPMA: {stats['bias_ghcn_minus_ipma']:+.3f} °C | "
        f"MAE: {stats['mae']:.3f} °C | "
        f"Median abs: {stats['median_abs']:.3f} °C | "
        f"P95 abs: {stats['p95_abs']:.3f} °C | "
        f"Max abs: {stats['max_abs']:.3f} °C"
    )
    corr = stats["corr"]
    print(
        f"  Korrelation: {corr:.6f}" if corr is not None
        else "  Korrelation: n/a"
    )
    print(
        f"  |Δ| <=0.1°C: {stats['within_0_1']:,}/{stats['n']:,} "
        f"({100*stats['within_0_1']/stats['n']:.1f}%) | "
        f"<=0.5°C: {stats['within_0_5']:,}/{stats['n']:,} "
        f"({100*stats['within_0_5']/stats['n']:.1f}%)"
    )
    print("  Größte Abweichungen:")
    for d, ip, gh, diff in stats["worst"]:
        print(
            f"    {d} | IPMA={ip:.1f} | GHCN={gh:.1f} | "
            f"GHCN-IPMA={diff:+.1f}"
        )


def main():
    print("============================================================")
    print("PORTUGAL · LISBOA IPMA ↔ GHCN CROSSWALK PROBE")
    print("============================================================")
    print("Nur Identitäts-/Überlappungsprüfung. KEIN Cache.")
    print()
    print(
        f"IPMA {IPMA_NAME} | Nr. {IPMA_ID} | "
        f"{IPMA_LAT:.6f},{IPMA_LON:.6f} | {IPMA_ELEV:.1f} m"
    )
    print(f"Erwarteter WMO-Code: {EXPECTED_WMO}")
    print(f"Erwartete GHCN-ID: {EXPECTED_GHCN}")

    stations = parse_stations(fetch(STATIONS_URL).decode("latin-1"))
    inv = parse_inventory(fetch(INVENTORY_URL).decode("latin-1"))

    candidates = []
    for sid, meta in stations.items():
        if "TMAX" not in inv.get(sid, {}) or "TMIN" not in inv.get(sid, {}):
            continue
        dist = haversine_km(
            IPMA_LAT, IPMA_LON, meta["lat"], meta["lon"]
        )
        if dist <= 80:
            candidates.append((dist, sid, meta))

    candidates.sort()

    print("\n=== GHCN-KANDIDATEN <= 80 km ===")
    for dist, sid, meta in candidates:
        tmax = inv[sid]["TMAX"]
        tmin = inv[sid]["TMIN"]
        print(
            f"{sid} | {meta['name']} | WMO={meta['wmo']!r} | "
            f"{meta['lat']:.4f},{meta['lon']:.4f} | "
            f"elev={meta['elev']} m | Distanz={dist:.2f} km | "
            f"TMAX={tmax[0]}-{tmax[1]} | TMIN={tmin[0]}-{tmin[1]}"
        )

    print("\n=== ERWARTETER DIREKTTREFFER ===")
    if EXPECTED_GHCN in stations:
        meta = stations[EXPECTED_GHCN]
        dist = haversine_km(
            IPMA_LAT, IPMA_LON, meta["lat"], meta["lon"]
        )
        print(
            f"GEFUNDEN: {EXPECTED_GHCN} | {meta['name']} | "
            f"WMO={meta['wmo']!r} | "
            f"{meta['lat']:.4f},{meta['lon']:.4f} | "
            f"elev={meta['elev']} m | Distanz={dist:.3f} km"
        )
        print(f"Inventar: {inv.get(EXPECTED_GHCN)}")
    else:
        print(f"NICHT GEFUNDEN: {EXPECTED_GHCN}")

    sheet_name, ipma = parse_ipma_daily()
    print(
        f"\nVerwendetes IPMA-Sheet: {sheet_name!r} | "
        f"Tage={len(ipma):,}"
    )

    # Compare expected ID plus nearest candidates, without duplicates.
    compare_ids = []
    if EXPECTED_GHCN in stations and EXPECTED_GHCN in inv:
        compare_ids.append(EXPECTED_GHCN)
    for _, sid, _ in candidates[:6]:
        if sid not in compare_ids:
            compare_ids.append(sid)

    print("\n============================================================")
    print("TAGESWERT-VERGLEICH")
    print("============================================================")
    summary = []

    for sid in compare_ids:
        meta = stations[sid]
        print("\n" + "-" * 78)
        print(
            f"{sid} | {meta['name']} | WMO={meta['wmo']} | "
            f"{meta['lat']:.4f},{meta['lon']:.4f}"
        )
        g = parse_ghcn_station(sid)
        print(f"GHCN URL: {g['url']}")
        print(
            f"GHCN Rohzeilen TMIN={g['counts'].get('TMIN',0):,}, "
            f"TMAX={g['counts'].get('TMAX',0):,} | "
            f"QFLAG TMIN={g['qflagged'].get('TMIN',0):,}, "
            f"TMAX={g['qflagged'].get('TMAX',0):,}"
        )

        smin = compare(ipma, g["data"], "TMIN")
        smax = compare(ipma, g["data"], "TMAX")
        print_comparison(sid, "TMIN", smin)
        print_comparison(sid, "TMAX", smax)

        n_total = (smin["n"] if smin else 0) + (smax["n"] if smax else 0)
        mae_values = [
            s["mae"] for s in (smin, smax) if s is not None
        ]
        mean_mae = statistics.fmean(mae_values) if mae_values else None
        summary.append((sid, meta["name"], n_total, mean_mae))

    print("\n============================================================")
    print("RANKING DER KANDIDATEN")
    print("============================================================")
    for sid, name, n_total, mean_mae in sorted(
        summary,
        key=lambda x: (
            -(x[2]),
            x[3] if x[3] is not None else 999,
        ),
    ):
        print(
            f"{sid} | {name} | gemeinsame TMIN+TMAX-Werte={n_total:,} | "
            f"mittlere MAE="
            + (f"{mean_mae:.3f} °C" if mean_mae is not None else "n/a")
        )

    print("\n============================================================")
    print("ENTSCHEIDUNGSREGEL")
    print("============================================================")
    print(
        "POM00008535 darf nur als direkte Fortsetzung von IPMA 535 behandelt "
        "werden, wenn Metadaten (Name/WMO/Koordinaten/Höhe) zusammenpassen und "
        "die Tageswert-Überlappung klar besser passt als bei benachbarten "
        "GHCN-Stationen."
    )
    print()
    print("Bitte den vollständigen Log schicken, besonders:")
    print("1) ERWARTETER DIREKTTREFFER")
    print("2) POM00008535 TMIN/TMAX-Vergleich")
    print("3) RANKING DER KANDIDATEN")
    print()
    print("Danach legen wir den Portugal-Crosswalk endgültig fest.")


if __name__ == "__main__":
    main()
