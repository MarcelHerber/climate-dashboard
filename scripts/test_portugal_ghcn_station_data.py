#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import io
import urllib.request
from collections import defaultdict
from datetime import datetime

UA = "climate-dashboard-portugal-ghcn-probe/1.0 (+GitHub Actions)"

BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
STATIONS_URL = f"{BASE}/ghcnd-stations.txt"
INVENTORY_URL = f"{BASE}/ghcnd-inventory.txt"
BY_STATION = f"{BASE}/by_station"

COUNTRY_PREFIX = "PO"


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


def parse_stations(text: str):
    out = {}
    for line in text.splitlines():
        if len(line) < 85:
            continue
        sid = line[0:11].strip()
        if not sid.startswith(COUNTRY_PREFIX):
            continue
        try:
            lat = float(line[12:20].strip())
            lon = float(line[21:30].strip())
            elev_raw = line[31:37].strip()
            elev = float(elev_raw) if elev_raw else None
        except ValueError:
            continue

        state = line[38:40].strip()
        name = line[41:71].strip()
        gsn = line[72:75].strip()
        hcn = line[76:79].strip()
        wmo = line[80:85].strip()

        out[sid] = {
            "id": sid,
            "lat": lat,
            "lon": lon,
            "elev": elev,
            "state": state,
            "name": name,
            "gsn": gsn,
            "hcn": hcn,
            "wmo": wmo,
        }
    return out


def parse_inventory(text: str):
    inv = defaultdict(dict)
    for line in text.splitlines():
        if len(line) < 45:
            continue
        sid = line[0:11].strip()
        if not sid.startswith(COUNTRY_PREFIX):
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


def region(lat: float, lon: float) -> str:
    if -10.0 <= lon <= -6.0 and 36.5 <= lat <= 42.5:
        return "Continente"
    if -32.0 <= lon <= -24.0 and 36.0 <= lat <= 40.5:
        return "Açores"
    if -18.0 <= lon <= -15.0 and 30.0 <= lat <= 33.5:
        return "Madeira"
    return "Sonstige"


def inspect_by_station(sid: str):
    url = f"{BY_STATION}/{sid}.csv.gz"
    raw = fetch(url)
    text = gzip.decompress(raw).decode("utf-8", errors="replace")

    first = {"TMAX": None, "TMIN": None}
    last = {"TMAX": None, "TMIN": None}
    counts = {"TMAX": 0, "TMIN": 0}
    qflagged = {"TMAX": 0, "TMIN": 0}
    current_2026 = {"TMAX": 0, "TMIN": 0}
    samples_2026 = []

    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 4:
            continue
        rsid, datestr, element, value = row[:4]
        if element not in {"TMAX", "TMIN"}:
            continue

        qflag = row[5].strip() if len(row) > 5 else ""
        try:
            d = datetime.strptime(datestr, "%Y%m%d").date()
            v = int(value) / 10.0
        except ValueError:
            continue

        counts[element] += 1
        if qflag:
            qflagged[element] += 1

        iso = d.isoformat()
        if first[element] is None or iso < first[element]:
            first[element] = iso
        if last[element] is None or iso > last[element]:
            last[element] = iso

        if d.year == 2026 and not qflag:
            current_2026[element] += 1
            if len(samples_2026) < 8:
                samples_2026.append((iso, element, v, row[4:8]))

    return {
        "url": url,
        "bytes_gz": len(raw),
        "first": first,
        "last": last,
        "counts": counts,
        "qflagged": qflagged,
        "current_2026": current_2026,
        "samples_2026": samples_2026,
    }


def main():
    print("============================================================")
    print("PORTUGAL · NOAA GHCN-DAILY PROBE")
    print("============================================================")
    print("Nur Probe. Noch KEIN Cache und KEINE Europa-Integration.")
    print(f"GHCN-Ländercode: {COUNTRY_PREFIX} = Portugal")

    print("\nLade Stationsmetadaten ...")
    stations = parse_stations(fetch(STATIONS_URL).decode("latin-1"))
    print(f"Portugal-Stationen in ghcnd-stations.txt: {len(stations):,}")

    print("Lade Element-Inventar ...")
    inv = parse_inventory(fetch(INVENTORY_URL).decode("latin-1"))
    print(f"Portugal-Stationen mit TMAX und/oder TMIN im Inventar: {len(inv):,}")

    rows = []
    for sid, meta in stations.items():
        el = inv.get(sid, {})
        tmax = el.get("TMAX")
        tmin = el.get("TMIN")
        if not tmax and not tmin:
            continue

        first_candidates = [x[0] for x in (tmax, tmin) if x]
        last_candidates = [x[1] for x in (tmax, tmin) if x]

        rows.append(
            {
                **meta,
                "region": region(meta["lat"], meta["lon"]),
                "tmax_first": tmax[0] if tmax else None,
                "tmax_last": tmax[1] if tmax else None,
                "tmin_first": tmin[0] if tmin else None,
                "tmin_last": tmin[1] if tmin else None,
                "both": bool(tmax and tmin),
                "first_any": min(first_candidates) if first_candidates else None,
                "last_any": max(last_candidates) if last_candidates else None,
                "both_2026": bool(
                    tmax and tmin and tmax[1] >= 2026 and tmin[1] >= 2026
                ),
            }
        )

    print("\n=== INVENTAR-ZUSAMMENFASSUNG ===")
    print(f"Mit TMAX oder TMIN: {len(rows):,}")
    print(f"Mit TMAX UND TMIN: {sum(r['both'] for r in rows):,}")
    print(f"Mit TMAX UND TMIN bis 2026: {sum(r['both_2026'] for r in rows):,}")

    for reg in ("Continente", "Açores", "Madeira", "Sonstige"):
        rr = [r for r in rows if r["region"] == reg]
        if not rr:
            continue
        print(
            f"{reg}: {len(rr):,} mit TMAX/TMIN-Element | "
            f"{sum(r['both'] for r in rr):,} mit beiden | "
            f"{sum(r['both_2026'] for r in rr):,} mit beiden bis 2026"
        )

    both = [r for r in rows if r["both"]]
    both.sort(key=lambda r: (r["first_any"], r["id"]))

    print("\n=== LÄNGSTE REIHEN MIT TMAX + TMIN ===")
    for r in both[:40]:
        print(
            f"{r['id']} | {r['name']} | {r['region']} | "
            f"{r['lat']:.4f},{r['lon']:.4f} | "
            f"TMAX {r['tmax_first']}-{r['tmax_last']} | "
            f"TMIN {r['tmin_first']}-{r['tmin_last']}"
        )

    active = [r for r in rows if r["both_2026"]]
    active.sort(key=lambda r: (r["first_any"], r["id"]))

    print("\n=== 2026-AKTIVE REIHEN MIT TMAX + TMIN ===")
    for r in active:
        print(
            f"{r['id']} | {r['name']} | {r['region']} | "
            f"TMAX {r['tmax_first']}-{r['tmax_last']} | "
            f"TMIN {r['tmin_first']}-{r['tmin_last']}"
        )

    # Samples: longest 8 + up to 12 currently active, without duplicates.
    sample_ids = []
    for r in both[:8] + active[:12]:
        if r["id"] not in sample_ids:
            sample_ids.append(r["id"])

    print("\n=== BY_STATION STICHPROBEN ===")
    successful = 0
    for sid in sample_ids:
        meta = stations[sid]
        print("\n" + "-" * 76)
        print(f"{sid} | {meta['name']} | {region(meta['lat'], meta['lon'])}")
        try:
            info = inspect_by_station(sid)
        except Exception as exc:
            print(f"FEHLER: {exc}")
            continue

        successful += 1
        print(f"URL: {info['url']}")
        print(f"GZIP-Bytes: {info['bytes_gz']:,}")
        print(
            f"TMAX: {info['first']['TMAX']} bis {info['last']['TMAX']} | "
            f"Zeilen {info['counts']['TMAX']:,} | "
            f"QFLAG {info['qflagged']['TMAX']:,} | "
            f"2026 gültig {info['current_2026']['TMAX']:,}"
        )
        print(
            f"TMIN: {info['first']['TMIN']} bis {info['last']['TMIN']} | "
            f"Zeilen {info['counts']['TMIN']:,} | "
            f"QFLAG {info['qflagged']['TMIN']:,} | "
            f"2026 gültig {info['current_2026']['TMIN']:,}"
        )

        for sample in info["samples_2026"]:
            print(
                f"2026 SAMPLE: {sample[0]} | {sample[1]} | "
                f"{sample[2]:.1f} °C | flags={sample[3]}"
            )

    print("\n============================================================")
    print("FAZIT")
    print("============================================================")
    print(f"Portugal GHCN-Stationen mit TMAX+TMIN: {len(both):,}")
    print(f"Davon bis 2026 aktiv: {len(active):,}")
    print(f"Erfolgreiche by_station-Stichproben: {successful:,}/{len(sample_ids):,}")
    print()
    print("Bitte den vollständigen Log schicken, besonders:")
    print("1) INVENTAR-ZUSAMMENFASSUNG")
    print("2) LÄNGSTE REIHEN MIT TMAX + TMIN")
    print("3) 2026-AKTIVE REIHEN")
    print("4) BY_STATION STICHPROBEN")
    print()
    print(
        "Danach entscheiden wir nur, ob Portugal historisch komplett aus GHCN "
        "gebaut wird oder ob Lisboa/Geofísico als offizielle IPMA-Langreihe "
        "zusätzlich/ersetzend eingebunden wird."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
