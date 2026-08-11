#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from html.parser import HTMLParser

UA = "climate-dashboard-ipma-portugal-probe/1.0 (+GitHub Actions)"

LONG_SERIES = "https://www.ipma.pt/pt/oclima/series.longas/"
LONG_LIST = "https://www.ipma.pt/pt/oclima/series.longas/list.jsp"

API_STATIONS = "https://api.ipma.pt/open-data/observation/meteorology/stations/stations.json"
API_OBS = "https://api.ipma.pt/open-data/observation/meteorology/stations/observations.json"

SAMPLE_LOCS = [
    "Lisboa/Geofísico",
    "Coimbra/Geofísico",
    "Évora",
    "Faro",
    "Porto",
    "Bragança",
    "Funchal",
    "Ponta Delgada",
]


def fetch(url: str, timeout: int = 60, attempts: int = 3) -> tuple[bytes, str]:
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/json,text/csv,*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                ctype = r.headers.get("Content-Type", "")
                if not raw:
                    raise RuntimeError("leere Antwort")
                return raw, ctype
        except Exception as exc:
            last = exc
            print(f"WARNUNG Download {attempt}/{attempts}: {url}: {exc}", flush=True)
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Download endgültig fehlgeschlagen: {url}: {last}")


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = []
        self.options = []
        self._option_value = None
        self._option_text = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        for key in ("href", "src", "data-url", "data-href", "action"):
            if d.get(key):
                self.attrs.append((tag, key, d[key]))
        if tag.lower() == "option":
            self._option_value = d.get("value")
            self._option_text = []

    def handle_data(self, data):
        if self._option_value is not None:
            self._option_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "option" and self._option_value is not None:
            self.options.append(
                (self._option_value, " ".join("".join(self._option_text).split()))
            )
            self._option_value = None
            self._option_text = []


def abs_urls(base: str, text: str):
    p = LinkParser()
    p.feed(text)

    urls = set()
    for _, _, value in p.attrs:
        urls.add(urllib.parse.urljoin(base, html.unescape(value)))

    patterns = [
        r"[\"']([^\"']+\.(?:csv|json|xlsx|xls|txt)(?:\?[^\"']*)?)[\"']",
        r"[\"']([^\"']+\.jsp(?:\?[^\"']*)?)[\"']",
        r"[\"']([^\"']+(?:ajax|download|export|series)[^\"']*)[\"']",
    ]
    for pat in patterns:
        for value in re.findall(pat, text, flags=re.I):
            if len(value) < 500:
                urls.add(urllib.parse.urljoin(base, html.unescape(value)))

    return sorted(urls), p.options


def interesting_urls(urls):
    keys = ("csv", "json", "xlsx", "xls", "download", "export", "series", "ajax", "longa")
    return [u for u in urls if any(k in u.lower() for k in keys)]


def print_fragments(text: str, terms, max_each=8):
    lines = text.splitlines()
    seen = 0
    for i, line in enumerate(lines):
        low = line.lower()
        if any(t.lower() in low for t in terms):
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                print(f"  L{i+1}: {cleaned[:900]}")
                seen += 1
                if seen >= max_each:
                    break
    if seen == 0:
        print("  (keine passenden Fragmente)")


def probe_long_series():
    print("=== IPMA PORTUGAL · SÉRIES LONGAS ===")
    print("Ziel: echte tägliche TMIN/TMAX-Downloadwege und Stationsinventar erkennen.")

    pages = [
        ("Hauptseite", LONG_SERIES),
        ("Download-/Stationsliste", LONG_LIST),
    ]

    for label, url in pages:
        raw, ctype = fetch(url)
        text = decode(raw)
        urls, options = abs_urls(url, text)

        print(f"\n--- {label} ---")
        print(f"URL: {url}")
        print(f"Content-Type: {ctype}")
        print(f"Bytes: {len(raw):,}")
        print(f"HTML-Zeilen: {len(text.splitlines()):,}")
        print(f"OPTION-Einträge: {len(options):,}")
        if options:
            for v, t in options[:30]:
                print(f"OPTION: value={v!r} | text={t!r}")

        iu = interesting_urls(urls)
        print(f"Interessante Links/URLs: {len(iu):,}")
        for u in iu[:100]:
            print(f"URL-Kandidat: {u}")

        print("Fragmente zu daily/homogenized/CSV/Tmax/Tmin:")
        print_fragments(
            text,
            ["daily", "diári", "homogen", "csv", "tmax", "tmin", "temperatura", "temperature"],
            max_each=35,
        )

    print("\n=== STATIONSPAGES · STICHPROBE ===")
    discovered_data_urls = set()

    for loc in SAMPLE_LOCS:
        q = urllib.parse.urlencode({"loc": loc, "type": "raw"})
        url = LONG_SERIES + "?" + q
        print("\n" + "=" * 78)
        print(f"LOKAL: {loc}")
        print(f"URL: {url}")
        try:
            raw, ctype = fetch(url)
            text = decode(raw)
        except Exception as exc:
            print(f"FEHLER: {exc}")
            continue

        urls, _ = abs_urls(url, text)
        iu = interesting_urls(urls)

        print(f"Content-Type: {ctype} | Bytes: {len(raw):,}")
        print(f"Interessante Links/URLs: {len(iu):,}")
        for u in iu[:80]:
            print(f"URL-Kandidat: {u}")
            if any(ext in u.lower() for ext in (".csv", ".json", ".xlsx", ".xls", ".txt")):
                discovered_data_urls.add(u)

        print("HTML-Fragmente:")
        print_fragments(
            text,
            [
                "csv", "daily", "diári", "homogen", "tmax", "tmin",
                "minimum", "maximum", "mínima", "máxima",
                "download", "descarregar",
            ],
            max_each=28,
        )

        js_urls = [u for u in urls if re.search(r"\.js(?:\?|$)", u, flags=re.I)]
        print(f"JavaScript-Dateien: {len(js_urls):,}")
        for js in js_urls[-15:]:
            print(f"JS: {js}")

        inspect_js = []
        for js in js_urls:
            low = js.lower()
            if "ipma.pt" in low and any(k in low for k in ("clima", "serie", "chart", "long", "oclima")):
                inspect_js.append(js)
        for js in js_urls[-5:]:
            if "ipma.pt" in js.lower() and js not in inspect_js:
                inspect_js.append(js)

        for js in inspect_js[:8]:
            try:
                js_raw, _ = fetch(js, timeout=30, attempts=2)
                js_text = decode(js_raw)
            except Exception as exc:
                print(f"JS-FEHLER: {js}: {exc}")
                continue
            print(f"--- JS-INSPEKTION {js} ({len(js_raw):,} Bytes) ---")
            print_fragments(
                js_text,
                ["series.longas", ".csv", "csv", "download", "ajax", "tmax", "tmin", "daily"],
                max_each=14,
            )
            js_found, _ = abs_urls(js, js_text)
            for candidate in interesting_urls(js_found):
                print(f"JS-URL-Kandidat: {candidate}")
                if any(ext in candidate.lower() for ext in (".csv", ".json", ".xlsx", ".xls", ".txt")):
                    discovered_data_urls.add(candidate)

    print("\n=== ENTDECKTE DIREKTE DATENURLS ===")
    if not discovered_data_urls:
        print("Keine direkten CSV/JSON/XLS(X)/TXT-URLs automatisch gefunden.")
    else:
        for u in sorted(discovered_data_urls):
            print(u)

    print("\n=== DIREKTE DATENURLS TESTEN ===")
    for u in sorted(discovered_data_urls)[:24]:
        try:
            raw, ctype = fetch(u, timeout=40, attempts=2)
            text = decode(raw)
            print(f"\nOK {u}")
            print(f"Content-Type: {ctype} | Bytes: {len(raw):,}")
            for line in text.splitlines()[:15]:
                print(line[:1000])
        except Exception as exc:
            print(f"FEHLER {u}: {exc}")


def flatten_station_features(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if isinstance(obj.get("features"), list):
            return obj["features"]
        if isinstance(obj.get("data"), list):
            return obj["data"]
    return []


def probe_current_api():
    print("\n\n=== IPMA OPEN DATA · AKTUELLES STATIONSNETZ ===")

    raw, ctype = fetch(API_STATIONS)
    stations_obj = json.loads(decode(raw))
    features = flatten_station_features(stations_obj)

    print(f"Stations-URL: {API_STATIONS}")
    print(f"Content-Type: {ctype}")
    print(f"Stationsobjekte: {len(features):,}")

    stations = {}
    mainland = azores = madeira = other = 0

    for f in features:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        sid = props.get("idEstacao")
        name = props.get("localEstacao")
        if sid is not None:
            stations[str(sid)] = {
                "name": name,
                "coords": coords,
                "properties": props,
            }

        try:
            lon, lat = float(coords[0]), float(coords[1])
            if -10.0 <= lon <= -6.0 and 36.5 <= lat <= 42.5:
                mainland += 1
            elif -32.0 <= lon <= -24.0 and 36.0 <= lat <= 40.5:
                azores += 1
            elif -18.0 <= lon <= -15.5 and 30.0 <= lat <= 33.5:
                madeira += 1
            else:
                other += 1
        except Exception:
            other += 1

    print(
        f"Geografische Grobeinteilung: Continente={mainland:,} | "
        f"Açores={azores:,} | Madeira/Selvagens={madeira:,} | sonstige={other:,}"
    )

    for sid, meta in list(stations.items())[:15]:
        print(f"Station: {sid} | {meta['name']} | coords={meta['coords']}")

    raw, ctype = fetch(API_OBS)
    obs_obj = json.loads(decode(raw))

    print("\n--- observations.json ---")
    print(f"URL: {API_OBS}")
    print(f"Content-Type: {ctype}")
    print(f"Bytes: {len(raw):,}")

    if not isinstance(obs_obj, dict):
        print(f"Unerwarteter Root-Typ: {type(obs_obj).__name__}")
        return

    timestamps = sorted(obs_obj.keys())
    print(f"Zeitstempel: {len(timestamps):,}")
    if timestamps:
        print(f"Erster Zeitstempel: {timestamps[0]}")
        print(f"Letzter Zeitstempel: {timestamps[-1]}")

    key_counts = Counter()
    stations_with_temp = set()
    sample_rows = []

    for ts, by_station in obs_obj.items():
        if not isinstance(by_station, dict):
            continue
        for sid, values in by_station.items():
            if not isinstance(values, dict):
                continue
            key_counts.update(values.keys())
            val = values.get("temperatura")
            if isinstance(val, (int, float)) and val != -99:
                stations_with_temp.add(str(sid))
                if len(sample_rows) < 15:
                    sample_rows.append((ts, str(sid), val, values))

    print("Feldhäufigkeiten:")
    for k, n in key_counts.most_common():
        print(f"  {k}: {n:,}")

    print(f"Stationen mit mindestens einer gültigen 'temperatura': {len(stations_with_temp):,}")
    print("Beispiele:")
    for ts, sid, temp, values in sample_rows:
        name = stations.get(sid, {}).get("name")
        print(f"  {ts} | {sid} | {name} | temperatura={temp} | keys={sorted(values)}")

    maxmin_like = sorted(
        k for k in key_counts
        if any(word in k.lower() for word in ("max", "min", "tmax", "tmin"))
    )
    print(f"Felder mit max/min im Namen: {maxmin_like}")

    print("\nWICHTIG:")
    print(
        "Wenn observations.json nur stündliche 'temperatura' enthält, reicht "
        "diese Datei allein nicht für einen rückwirkenden 2026-Tages-Tmax/Tmin-Cache. "
        "Dann suchen wir im nächsten Schritt gezielt nach einer IPMA-Tagesquelle."
    )


def main():
    print("============================================================")
    print("IPMA PORTUGAL PROBE · HISTORISCHE + AKTUELLE STATIONSDATEN")
    print("============================================================")
    print(
        "Dieser Schritt erzeugt KEINEN Cache und ändert KEINE Europa-Integration. "
        "Er untersucht nur die offiziellen IPMA-Datenwege."
    )

    historical_ok = True
    current_ok = True

    try:
        probe_long_series()
    except Exception as exc:
        historical_ok = False
        print(f"\nFEHLER HISTORISCHE SCHIENE: {exc}")

    try:
        probe_current_api()
    except Exception as exc:
        current_ok = False
        print(f"\nFEHLER CURRENT-API: {exc}")

    print("\n============================================================")
    print("FAZIT FÜR DEN NÄCHSTEN SCHRITT")
    print("============================================================")
    print(f"Historische Langreihen-Seite erreichbar: {historical_ok}")
    print(f"Aktuelle Stations-API erreichbar: {current_ok}")
    print()
    print("Bitte den vollständigen GitHub-Log dieses Probe-Runs schicken.")
    print("Besonders wichtig sind:")
    print("1) OPTION-Einträge / Stationsnamen der Séries-longas-Seite")
    print("2) URL-Kandidat / JS-URL-Kandidat für CSV/Download/AJAX")
    print("3) Inhalte unter 'DIREKTE DATENURLS TESTEN'")
    print("4) Zahl und Felder aus stations.json / observations.json")
    print("Danach bauen wir erst den historischen Portugal-Cache.")

    if not historical_ok and not current_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
