#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = "climate-dashboard-ipma-portugal-temp-probe/4.0 (+GitHub Actions)"

ROOT = "https://api.ipma.pt/open-data/observation/climate/"
TMAX_ROOT = ROOT + "temperature-max/"
TMIN_ROOT = ROOT + "temperature-min/"
TEMP_ROOT = ROOT + "temperature/"

SAMPLES = [
    ("TMAX Lisboa", TMAX_ROOT + "lisboa/mtxmx-1106-lisboa.csv"),
    ("TMIN Lisboa", TMIN_ROOT + "lisboa/mtnmn-1106-lisboa.csv"),
    ("TMAX Porto", TMAX_ROOT + "porto/mtxmx-1312-porto.csv"),
    ("TMIN Porto", TMIN_ROOT + "porto/mtnmn-1312-porto.csv"),
    ("TMAX Faro", TMAX_ROOT + "faro/mtxmx-0805-faro.csv"),
    ("TMIN Faro", TMIN_ROOT + "faro/mtnmn-0805-faro.csv"),
    ("TMAX Évora", TMAX_ROOT + "evora/mtxmx-0705-evora.csv"),
    ("TMIN Évora", TMIN_ROOT + "evora/mtnmn-0705-evora.csv"),
    (
        "TMAX Castelo Branco",
        TMAX_ROOT + "castelo-branco/mtxmx-0502-castelo-branco.csv",
    ),
    (
        "TMIN Castelo Branco",
        TMIN_ROOT + "castelo-branco/mtnmn-0502-castelo-branco.csv",
    ),
]

CURRENT_TEMP = (
    TEMP_ROOT + "t2m-p1d-continental-obssup-idw-concelhos-20d.csv"
)


def fetch(url: str, timeout: int = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


class ListingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        d = dict(attrs)
        href = d.get("href")
        if href:
            self.links.append(href)


def list_links(url: str):
    raw, _ = fetch(url)
    text = decode(raw)
    p = ListingParser()
    p.feed(text)
    return [
        urllib.parse.urljoin(url, href)
        for href in p.links
        if href not in ("../", "/")
    ]


def sniff_csv(text: str):
    sample = text[:8000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except Exception:
        delim = ";"

    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    return delim, rows


def date_like(value: str) -> bool:
    s = value.strip()
    patterns = [
        r"\d{4}-\d{2}-\d{2}",
        r"\d{2}/\d{2}/\d{4}",
        r"\d{4}/\d{2}/\d{2}",
        r"\d{4}-\d{2}",
        r"\d{2}/\d{4}",
        r"\d{4}",
    ]
    return any(re.fullmatch(p, s) for p in patterns)


def inspect_file(label: str, url: str):
    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)
    print("URL:", url)

    try:
        raw, ctype = fetch(url)
    except Exception as exc:
        print("FEHLER:", exc)
        return

    text = decode(raw)
    print("Content-Type:", ctype)
    print("Bytes:", f"{len(raw):,}")
    print("Textzeilen:", f"{len(text.splitlines()):,}")

    delim, rows = sniff_csv(text)
    print("Delimiter:", repr(delim))
    print("CSV-Zeilen:", f"{len(rows):,}")

    print("\nErste 15 Zeilen:")
    for i, row in enumerate(rows[:15], 1):
        print(f"R{i}: " + " | ".join(row))

    print("\nLetzte 15 Zeilen:")
    start = max(0, len(rows) - 15)
    for i, row in enumerate(rows[-15:], start + 1):
        print(f"R{i}: " + " | ".join(row))

    max_cols = max((len(r) for r in rows), default=0)
    print("\nMaximale Spaltenzahl:", max_cols)

    date_cells = []
    for r_idx, row in enumerate(rows, 1):
        for c_idx, val in enumerate(row, 1):
            if date_like(val):
                date_cells.append((r_idx, c_idx, val.strip()))
                if len(date_cells) >= 30:
                    break
        if len(date_cells) >= 30:
            break

    print("Erste datumartig erkannte Zellen:")
    for item in date_cells:
        print(f"  R{item[0]} C{item[1]} = {item[2]!r}")

    joined_head = "\n".join(text.splitlines()[:60]).lower()
    keywords = [
        "station", "estacao", "estação", "concelho", "municip",
        "normal", "climat", "idw", "interpol", "tmax", "tmin",
        "temperatura", "ano", "year", "dia", "day",
    ]
    print("Gefundene Schlüsselwörter in ersten 60 Zeilen:")
    print([k for k in keywords if k in joined_head])


def main():
    print("============================================================")
    print("IPMA PORTUGAL PROBE V4 · TEMPERATURE-MAX / TEMPERATURE-MIN")
    print("============================================================")
    print("Nur Prüfung. KEIN Cache. KEINE Europa-Integration.")
    print()

    print("=== TOP-LEVEL VERZEICHNISSE ===")
    for label, root in [
        ("temperature-max", TMAX_ROOT),
        ("temperature-min", TMIN_ROOT),
        ("temperature", TEMP_ROOT),
    ]:
        try:
            links = list_links(root)
            dirs = [u for u in links if u.endswith("/")]
            files = [u for u in links if not u.endswith("/")]
            print(
                f"{label}: Unterordner={len(dirs):,} | Dateien={len(files):,}"
            )
            for u in links[:30]:
                print(" ", u)
        except Exception as exc:
            print(f"{label}: FEHLER {exc}")

    print("\n=== STICHPROBEN MAX/MIN ===")
    for label, url in SAMPLES:
        inspect_file(label, url)

    print("\n=== AKTUELLES TEMPERATUR-PRODUKT ===")
    inspect_file("t2m-p1d continental municipalities", CURRENT_TEMP)

    print("\n" + "=" * 80)
    print("FAZIT-FRAGEN")
    print("=" * 80)
    print("Bitte den Log schicken. Entscheidend ist:")
    print("1) Header + erste/letzte Zeilen der mtxmx/mtnmn-Dateien")
    print("2) ob echte Kalenderdaten/Jahre enthalten sind")
    print("3) ob es Stations- oder Gemeinde-/Concelho-Daten sind")
    print("4) Struktur des aktuellen t2m-p1d-IDW-Produkts")
    print()
    print(
        "Erst danach entscheiden wir, ob diese offiziellen IPMA-Dateien "
        "für Stationsrekorde geeignet sind."
    )


if __name__ == "__main__":
    main()
