#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from datetime import datetime

UA = "climate-dashboard-ipma-portugal-probe/2.0 (+GitHub Actions)"

BASE = "https://www.ipma.pt"
LONG_SERIES = BASE + "/pt/oclima/series.longas/"
LONG_LIST = BASE + "/pt/oclima/series.longas/list.jsp"

SAMPLE_LOCS = [
    "Évora",
    "Faro",
    "Porto",
    "Bragança",
    "Funchal",
    "Ponta Delgada",
]


def fetch(url: str, timeout: int = 60, attempts: int = 3) -> bytes:
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,*/*",
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


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


class StructureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.inputs = []
        self.options = []
        self.forms = []
        self.rows = []
        self._row = None
        self._cell = None
        self._option = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        tag = tag.lower()

        if tag == "a" and d.get("href"):
            self.links.append({"href": d["href"], "text": ""})

        if tag == "input":
            self.inputs.append(dict(d))

        if tag == "form":
            self.forms.append(dict(d))

        if tag == "option":
            self._option = {"value": d.get("value"), "text": ""}

        if tag == "tr":
            self._row = []

        if tag in ("td", "th") and self._row is not None:
            self._cell = ""

    def handle_data(self, data):
        clean = " ".join(data.split())
        if not clean:
            return
        if self.links:
            self.links[-1]["text"] = (
                (self.links[-1].get("text", "") + " " + clean).strip()
            )
        if self._option is not None:
            self._option["text"] = (
                (self._option.get("text", "") + " " + clean).strip()
            )
        if self._cell is not None:
            self._cell = (self._cell + " " + clean).strip()

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag == "option" and self._option is not None:
            self.options.append(self._option)
            self._option = None

        if tag in ("td", "th") and self._cell is not None:
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None

        if tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def clean_url(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(value))


def looks_station_related(text: str) -> bool:
    low = text.lower()
    return any(
        x in low
        for x in (
            "loc=",
            "estacao",
            "estação",
            "serie",
            "série",
            "temp",
            "diar",
            "daily",
            "download",
            "descarregar",
            ".csv",
            ".txt",
            ".json",
            ".xls",
        )
    )


def print_list_structure():
    print("============================================================")
    print("1) IPMA SÉRIES LONGAS · STATIONSLISTE")
    print("============================================================")

    raw = fetch(LONG_LIST)
    text = decode(raw)
    parser = StructureParser()
    parser.feed(text)

    print(f"URL: {LONG_LIST}")
    print(f"Bytes: {len(raw):,}")
    print(f"Links: {len(parser.links):,}")
    print(f"Inputs: {len(parser.inputs):,}")
    print(f"Options: {len(parser.options):,}")
    print(f"Forms: {len(parser.forms):,}")
    print(f"Tabellenzeilen: {len(parser.rows):,}")

    print("\n--- FORMULARE ---")
    for f in parser.forms:
        print(f)

    print("\n--- INPUTS mit relevanten Attributen ---")
    relevant_inputs = []
    for x in parser.inputs:
        blob = " ".join(f"{k}={v}" for k, v in x.items())
        if looks_station_related(blob) or x.get("value"):
            relevant_inputs.append(x)
    for x in relevant_inputs[:250]:
        print(x)
    print(f"Relevante Inputs gesamt: {len(relevant_inputs):,}")

    print("\n--- OPTIONS ---")
    for x in parser.options[:250]:
        print(f"value={x.get('value')!r} | text={x.get('text')!r}")
    print(f"Options gesamt: {len(parser.options):,}")

    print("\n--- LINKS mit Stations-/Datenbezug ---")
    rel_links = []
    for x in parser.links:
        href = clean_url(LONG_LIST, x.get("href", ""))
        blob = href + " " + x.get("text", "")
        if looks_station_related(blob):
            rel_links.append((href, x.get("text", "")))
    for href, label in rel_links[:300]:
        print(f"{label!r} -> {href}")
    print(f"Relevante Links gesamt: {len(rel_links):,}")

    print("\n--- TABELLENZEILEN ---")
    for row in parser.rows[:300]:
        print(" | ".join(row))
    print(f"Tabellenzeilen gesamt: {len(parser.rows):,}")

    print("\n--- ROH-HTML FRAGMENTE rund um mögliche Stationsdaten ---")
    patterns = [
        r".{0,250}(?:loc=|station|estacao|estação|series\.longas|homogeneiz|diári|daily).{0,500}",
        r".{0,250}(?:\.csv|\.txt|\.json|download|descarregar).{0,500}",
    ]
    shown = set()
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.I | re.S):
            frag = re.sub(r"\s+", " ", m.group(0)).strip()
            if frag in shown:
                continue
            shown.add(frag)
            print(frag[:1200])
            if len(shown) >= 80:
                break
        if len(shown) >= 80:
            break

    # Candidate station locations for next stage.
    candidates = set()

    for x in parser.options:
        value = (x.get("value") or "").strip()
        label = (x.get("text") or "").strip()
        if value and value not in {"0", "-1"}:
            candidates.add(value)
        elif label:
            candidates.add(label)

    for href, label in rel_links:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        for val in qs.get("loc", []):
            if val.strip():
                candidates.add(val.strip())

    # Also discover quoted loc values / object metadata in raw source.
    for m in re.finditer(r"""(?:loc|local|estacao|estação)\s*[:=]\s*["']([^"']{2,100})["']""",
                         text, flags=re.I):
        val = html.unescape(m.group(1)).strip()
        if not any(ch in val for ch in "{}[]();"):
            candidates.add(val)

    print("\n--- ENTDECKTE STATIONSKANDIDATEN ---")
    for c in sorted(candidates)[:500]:
        print(c)
    print(f"Stationskandidaten gesamt: {len(candidates):,}")

    return sorted(candidates)


def extract_balanced(text: str, start: int, open_char: str, close_char: str):
    depth = 0
    quote = None
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if quote is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue

        if ch in ("'", '"'):
            quote = ch
            continue

        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def find_json_arrays_with_tmax_tmin(text: str):
    arrays = []
    seen = set()

    for match in re.finditer(r'["\']?(temp(?:_\d+)?)["\']?\s*:\s*\[', text, flags=re.I):
        name = match.group(1)
        arr_start = text.find("[", match.start())
        if arr_start < 0:
            continue
        raw_arr = extract_balanced(text, arr_start, "[", "]")
        if not raw_arr:
            continue
        if '"tmax"' not in raw_arr.lower() and "'tmax'" not in raw_arr.lower():
            continue
        key = (name.lower(), arr_start)
        if key not in seen:
            seen.add(key)
            arrays.append((name, raw_arr))

    # Fallback: locate tmax, walk backwards to likely array.
    if not arrays:
        for m in re.finditer(r'["\']tmax["\']\s*:', text, flags=re.I):
            search_start = max(0, m.start() - 100000)
            arr_start = text.rfind("[", search_start, m.start())
            if arr_start >= 0:
                raw_arr = extract_balanced(text, arr_start, "[", "]")
                if raw_arr and "tmin" in raw_arr.lower():
                    arrays.append(("fallback", raw_arr))
                    break

    return arrays


def parse_js_array(raw_arr: str):
    # IPMA's embedded data observed in probe v1 uses JSON-like objects.
    candidates = [
        raw_arr,
        raw_arr.replace("'", '"'),
    ]
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, list):
                return obj
        except Exception:
            pass

    # Conservative JS->JSON cleanup for unquoted keys.
    candidate = raw_arr
    candidate = re.sub(
        r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)',
        r'\1"\2"\3',
        candidate,
    )
    candidate = candidate.replace("'", '"')
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)

    try:
        obj = json.loads(candidate)
        if isinstance(obj, list):
            return obj
    except Exception:
        return None

    return None


def parse_possible_date(value):
    if value is None:
        return None
    s = str(value).strip()

    # Unix milliseconds / seconds
    if re.fullmatch(r"\d{10,13}", s):
        try:
            x = int(s)
            if len(s) >= 13:
                x /= 1000
            return datetime.utcfromtimestamp(x).date().isoformat()
        except Exception:
            pass

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m",
        "%Y",
    ):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except Exception:
            pass
    return None


def inspect_station(loc: str):
    url = LONG_SERIES + "?" + urllib.parse.urlencode({"loc": loc, "type": "raw"})
    raw = fetch(url)
    text = decode(raw)

    print("\n" + "=" * 78)
    print(f"2) STATIONSPAGE: {loc}")
    print("=" * 78)
    print(f"URL: {url}")
    print(f"Bytes: {len(raw):,}")
    print(f"Anzahl 'tmax': {len(re.findall(r'tmax', text, flags=re.I)):,}")
    print(f"Anzahl 'tmin': {len(re.findall(r'tmin', text, flags=re.I)):,}")

    arrays = find_json_arrays_with_tmax_tmin(text)
    print(f"Temperatur-Array-Kandidaten: {len(arrays):,}")

    for n, (name, raw_arr) in enumerate(arrays[:8], 1):
        print(f"\n--- Temperaturarray {n}: {name} ---")
        print(f"Rohgröße: {len(raw_arr):,} Zeichen")

        parsed = parse_js_array(raw_arr)
        if parsed is None:
            print("JSON/JS-Parsing fehlgeschlagen.")
            print("Anfang:")
            print(re.sub(r"\s+", " ", raw_arr[:2500]))
            print("Ende:")
            print(re.sub(r"\s+", " ", raw_arr[-1500:]))
            continue

        print(f"Datensätze: {len(parsed):,}")
        if not parsed:
            continue

        dict_rows = [x for x in parsed if isinstance(x, dict)]
        keys = sorted({str(k) for row in dict_rows[:200] for k in row})
        print(f"Keys: {keys}")

        print("Erste 3:")
        for row in dict_rows[:3]:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))

        print("Letzte 3:")
        for row in dict_rows[-3:]:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))

        date_fields = []
        for key in keys:
            values = [row.get(key) for row in dict_rows[:500] if key in row]
            parsed_dates = [parse_possible_date(v) for v in values]
            valid = [x for x in parsed_dates if x]
            if len(valid) >= max(3, len(values) // 2):
                date_fields.append(key)

        print(f"Mögliche Datumsfelder: {date_fields}")

        for key in date_fields[:5]:
            dates = []
            for row in dict_rows:
                d = parse_possible_date(row.get(key))
                if d:
                    dates.append(d)
            if dates:
                print(f"Datumsbereich {key}: {min(dates)} bis {max(dates)}")

        for temp_key in ("tmax", "tmin", "tmed", "tmean", "temp"):
            vals = []
            for row in dict_rows:
                if temp_key in row and isinstance(row[temp_key], (int, float)):
                    vals.append(float(row[temp_key]))
            if vals:
                print(
                    f"{temp_key}: n={len(vals):,} | "
                    f"min={min(vals):.2f} | max={max(vals):.2f}"
                )


def main():
    print("============================================================")
    print("IPMA PORTUGAL PROBE V2 · STATIONSLISTE + TAGESDATENBLOCK")
    print("============================================================")
    print("Noch KEIN Cache. Noch KEINE Europa-Integration.")
    print()

    candidates = []
    try:
        candidates = print_list_structure()
    except Exception as exc:
        print(f"FEHLER beim Stationslisten-Test: {exc}")

    # Use discovered candidates only if they look like human station names.
    usable = []
    for c in candidates:
        if (
            2 <= len(c) <= 80
            and not c.lower().startswith(("http", "javascript"))
            and not re.fullmatch(r"\d+", c)
        ):
            usable.append(c)

    test_locs = []
    for loc in usable[:8] + SAMPLE_LOCS:
        if loc not in test_locs:
            test_locs.append(loc)

    successes = 0
    for loc in test_locs[:12]:
        try:
            inspect_station(loc)
            successes += 1
        except Exception as exc:
            print(f"\nFEHLER Station {loc}: {exc}")

    print("\n============================================================")
    print("FAZIT")
    print("============================================================")
    print(f"Stationskandidaten aus list.jsp: {len(candidates):,}")
    print(f"Stationsseiten erfolgreich geprüft: {successes:,}/{min(12, len(test_locs)):,}")
    print()
    print("Bitte den GitHub-Log schicken, insbesondere:")
    print("1) ENTDECKTE STATIONSKANDIDATEN")
    print("2) Temperatur-Array-Kandidaten")
    print("3) Datensätze / Keys")
    print("4) Erste/Letzte Datenzeilen und Datumsbereich")
    print("Danach bauen wir den historischen Portugal-Cache bis 2025.")

    return 0 if successes else 1


if __name__ == "__main__":
    raise SystemExit(main())
