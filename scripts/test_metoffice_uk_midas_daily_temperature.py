#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import Any

UA = "climate-dashboard-uk-midas-open-probe/1.0 (+GitHub Actions)"

DATASET_VERSION = "202607"
DATASET_NAME = "uk-daily-temperature-obs"

DATA_ROOT = (
    "https://data.ceda.ac.uk/badc/ukmo-midas-open/data/"
    f"{DATASET_NAME}/dataset-version-{DATASET_VERSION}"
)
DAP_ROOT = (
    "https://dap.ceda.ac.uk/badc/ukmo-midas-open/data/"
    f"{DATASET_NAME}/dataset-version-{DATASET_VERSION}"
)

TOKEN_URL = "https://services.ceda.ac.uk/api/token/create/"

STATION_METADATA_NAME = (
    f"midas-open_{DATASET_NAME}_dv-{DATASET_VERSION}_station-metadata.csv"
)

SAMPLE_TERMS = (
    "heathrow",
    "oxford",
    "cambridge",
    "braemar",
    "lerwick",
    "cardiff",
    "belfast",
    "durham",
)

# MIDAS Open daily-temperature rows with this source ID are documented
# commissioning-trial records and must not be used.
COMMISSIONING_SRC_ID = "99999"


@dataclass(frozen=True)
class StationDir:
    county: str
    dirname: str
    src_id: str
    name: str
    data_url: str


def request_bytes(
    url: str,
    *,
    token: str | None = None,
    timeout: int = 90,
    method: str = "GET",
    data: bytes | None = None,
    basic_auth: str | None = None,
    attempts: int = 3,
) -> bytes:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        headers = {
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if basic_auth:
            headers["Authorization"] = f"Basic {basic_auth}"

        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if not raw:
                    raise RuntimeError("leere Antwort")
                return raw
        except Exception as exc:
            last = exc
            print(
                f"WARNUNG {attempt}/{attempts}: {url}: {exc}",
                flush=True,
            )
            if attempt < attempts:
                time.sleep(2 * attempt)

    raise RuntimeError(f"Download fehlgeschlagen: {url}: {last}")


def request_json(url: str, *, token: str | None = None) -> Any:
    raw = request_bytes(url, token=token)
    return json.loads(raw.decode("utf-8-sig"))


def json_listing(url: str) -> list[dict]:
    sep = "&" if "?" in url else "?"
    obj = request_json(url.rstrip("/") + f"/{sep}json=")
    items = obj.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError(f"Ungültige JSON-Liste: {url}")
    return items


def item_is_dir(item: dict) -> bool:
    return str(item.get("type", "")).lower() in {"dir", "directory"}


def item_is_file(item: dict) -> bool:
    return str(item.get("type", "")).lower() == "file"


def station_from_item(county: str, item: dict) -> StationDir | None:
    dirname = str(item.get("name", "")).strip()
    m = re.match(r"^(\d+)_([a-z0-9].*)$", dirname, re.I)
    if not m:
        return None

    src_id = m.group(1)
    name = m.group(2).replace("-", " ").strip()
    url = f"{DATA_ROOT}/{county}/{dirname}"
    return StationDir(
        county=county,
        dirname=dirname,
        src_id=src_id,
        name=name,
        data_url=url,
    )


def enumerate_public_inventory() -> tuple[list[str], list[StationDir]]:
    root_items = json_listing(DATA_ROOT)
    counties = sorted(
        str(x.get("name", ""))
        for x in root_items
        if item_is_dir(x)
        and str(x.get("name", "")) != "change_log_station_files"
    )

    stations: list[StationDir] = []

    print(f"Öffentliche County-Verzeichnisse: {len(counties):,}")
    for i, county in enumerate(counties, 1):
        items = json_listing(f"{DATA_ROOT}/{county}")
        found = []
        for item in items:
            if not item_is_dir(item):
                continue
            st = station_from_item(county, item)
            if st:
                stations.append(st)
                found.append(st)

        print(
            f"[{i:03d}/{len(counties):03d}] {county}: "
            f"{len(found):,} Stationsverzeichnisse",
            flush=True,
        )

    return counties, stations


def select_samples(stations: list[StationDir]) -> list[StationDir]:
    selected: list[StationDir] = []
    used: set[str] = set()

    for term in SAMPLE_TERMS:
        matches = [
            s for s in stations
            if term in s.name.lower()
            or term in s.dirname.lower()
        ]
        matches.sort(key=lambda x: (x.county, x.src_id, x.dirname))

        if matches:
            st = matches[0]
            key = f"{st.county}/{st.dirname}"
            if key not in used:
                used.add(key)
                selected.append(st)

    # Ensure the probe still has enough real stations even if one of the
    # preferred names disappears in a future release.
    for st in stations:
        if len(selected) >= 10:
            break
        key = f"{st.county}/{st.dirname}"
        if key not in used:
            used.add(key)
            selected.append(st)

    return selected


def station_year_files(st: StationDir) -> list[tuple[int, str, str]]:
    qcurl = f"{st.data_url}/qc-version-1"
    items = json_listing(qcurl)
    out: list[tuple[int, str, str]] = []

    for item in items:
        if not item_is_file(item):
            continue
        name = str(item.get("name", ""))
        m = re.search(r"_qcv-1_(\d{4})\.csv$", name)
        if not m:
            continue
        year = int(m.group(1))
        out.append((year, name, f"{qcurl}/{name}"))

    out.sort()
    return out


def get_ceda_token() -> str | None:
    # Robustester Weg für GitHub Actions:
    # Ein im CEDA-Services-Portal manuell erzeugter Archive Access Token.
    # CEDA dokumentiert für diese Tokens derzeit eine Lebensdauer von 3 Tagen.
    manual_token = os.environ.get("CEDA_ACCESS_TOKEN", "").strip()
    if manual_token:
        print(
            "CEDA-Authentifizierung: verwende CEDA_ACCESS_TOKEN.",
            flush=True,
        )
        return manual_token

    # Fallback: Token programmatisch aus CEDA_USERNAME/CEDA_PASSWORD erzeugen.
    # Der offizielle Endpoint verwendet POST + HTTP Basic Auth.
    username = os.environ.get("CEDA_USERNAME", "").strip()
    password = os.environ.get("CEDA_PASSWORD", "")

    if not username or not password:
        return None

    print(
        "CEDA-Authentifizierung: versuche Token-API mit "
        "CEDA_USERNAME/CEDA_PASSWORD.",
        flush=True,
    )

    credentials = base64.b64encode(
        f"{username}:{password}".encode("utf-8")
    ).decode("ascii")

    try:
        raw = request_bytes(
            TOKEN_URL,
            method="POST",
            data=b"",
            basic_auth=credentials,
            timeout=60,
            attempts=2,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"{exc}\n"
            "Hinweis: Falls der CEDA-Token-Endpunkt HTTP 500 liefert, "
            "im CEDA Services Portal unter 'access token' einen manuellen "
            "Archive Access Token erzeugen und in GitHub als Secret "
            "CEDA_ACCESS_TOKEN speichern."
        ) from exc

    obj = json.loads(raw.decode("utf-8"))
    token = str(obj.get("access_token", "")).strip()
    if not token:
        raise RuntimeError(
            "CEDA Token API antwortete ohne access_token. "
            "Alternativ CEDA_ACCESS_TOKEN verwenden."
        )
    return token


def dap_url(data_url: str) -> str:
    if data_url.startswith(DATA_ROOT):
        return DAP_ROOT + data_url[len(DATA_ROOT):]
    return data_url.replace(
        "https://data.ceda.ac.uk/",
        "https://dap.ceda.ac.uk/",
        1,
    )


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def parse_badc_csv(text: str) -> tuple[list[str], list[list[str]], list[str]]:
    """
    Returns (column references, data rows, header lines).

    BADC-CSV structure:
      metadata...
      data
      col_ref_1,col_ref_2,...
      rows...
      end data
    """
    lines = text.splitlines()
    data_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if line.strip().lower().rstrip(",") == "data":
            data_idx = i
            break

    if data_idx is None:
        raise RuntimeError("Kein BADC-CSV 'data'-Marker gefunden.")

    for i in range(data_idx + 1, len(lines)):
        if lines[i].strip().lower().rstrip(",") == "end data":
            end_idx = i
            break

    if end_idx is None:
        end_idx = len(lines)

    if data_idx + 1 >= end_idx:
        return [], [], lines[:data_idx]

    refs = next(
        csv.reader([lines[data_idx + 1]], skipinitialspace=False)
    )
    rows = list(
        csv.reader(
            io.StringIO("\n".join(lines[data_idx + 2:end_idx]))
        )
    )

    # Drop wholly empty rows.
    rows = [
        r for r in rows
        if any(str(x).strip() for x in r)
    ]
    return [x.strip() for x in refs], rows, lines[:data_idx]


def parse_station_metadata(text: str) -> tuple[list[str], list[list[str]]]:
    if "Conventions,G,BADC-CSV" in text[:500]:
        refs, rows, _ = parse_badc_csv(text)
        return refs, rows

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    return [x.strip() for x in rows[0]], rows[1:]


def normalize_ref(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", x.strip().lower()).strip("_")


def field_index(refs: list[str], *names: str) -> int | None:
    norm = {normalize_ref(v): i for i, v in enumerate(refs)}
    for name in names:
        key = normalize_ref(name)
        if key in norm:
            return norm[key]
    return None


def safe_value(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return str(row[idx]).strip()


def as_float(x: str) -> float | None:
    x = x.strip()
    if x in {"", "NA", "N/A", "-999", "-999.0"}:
        return None
    try:
        return float(x)
    except ValueError:
        return None


def inspect_temperature_file(
    label: str,
    data_file_url: str,
    token: str,
) -> None:
    url = dap_url(data_file_url)

    print("\n" + "=" * 82)
    print(label)
    print("=" * 82)
    print("URL:", url)

    raw = request_bytes(url, token=token)
    text = decode_text(raw)

    print(f"Bytes: {len(raw):,}")
    print(f"Textzeilen: {len(text.splitlines()):,}")

    refs, rows, header = parse_badc_csv(text)
    print(f"BADC Headerzeilen: {len(header):,}")
    print(f"Datenspalten: {len(refs):,}")
    print("Spalten:")
    print(refs)
    print(f"Datenzeilen: {len(rows):,}")

    print("\nErste 3 Datenzeilen:")
    for row in rows[:3]:
        print(" | ".join(row))
    print("Letzte 3 Datenzeilen:")
    for row in rows[-3:]:
        print(" | ".join(row))

    idx_time = field_index(
        refs,
        "ob_end_time",
        "observation_end_time",
        "obs_end_time",
    )
    idx_hours = field_index(refs, "ob_hour_count")
    idx_tmax = field_index(refs, "max_air_temp")
    idx_tmin = field_index(refs, "min_air_temp")
    idx_tmax_q = field_index(refs, "max_air_temp_q")
    idx_tmin_q = field_index(refs, "min_air_temp_q")
    idx_src = field_index(refs, "src_id")
    idx_version = field_index(refs, "version_num")
    idx_domain = field_index(refs, "met_domain_name")

    valid_tmax = 0
    valid_tmin = 0
    tmax_q = Counter()
    tmin_q = Counter()
    hours = Counter()
    end_hours = Counter()
    src_ids = Counter()
    versions = Counter()
    domains = Counter()
    timestamps: list[str] = []
    commissioning = 0

    for row in rows:
        src_id = safe_value(row, idx_src)
        if src_id:
            src_ids[src_id] += 1
        if src_id == COMMISSIONING_SRC_ID:
            commissioning += 1
            continue

        tm = safe_value(row, idx_time)
        if tm:
            timestamps.append(tm)
            m = re.search(r"[ T](\d{2}):?(\d{2})", tm)
            if m:
                end_hours[m.group(1)] += 1

        h = safe_value(row, idx_hours)
        if h:
            hours[h] += 1

        ver = safe_value(row, idx_version)
        if ver:
            versions[ver] += 1

        dom = safe_value(row, idx_domain)
        if dom:
            domains[dom] += 1

        qmax = safe_value(row, idx_tmax_q)
        qmin = safe_value(row, idx_tmin_q)
        tmax_q[qmax or "<leer>"] += 1
        tmin_q[qmin or "<leer>"] += 1

        vmax = as_float(safe_value(row, idx_tmax))
        vmin = as_float(safe_value(row, idx_tmin))

        if vmax is not None:
            valid_tmax += 1
        if vmin is not None:
            valid_tmin += 1

    print("\n--- Erkannte MIDAS-Felder ---")
    print("ob_end_time:", idx_time)
    print("ob_hour_count:", idx_hours)
    print("max_air_temp:", idx_tmax)
    print("min_air_temp:", idx_tmin)
    print("max_air_temp_q:", idx_tmax_q)
    print("min_air_temp_q:", idx_tmin_q)
    print("src_id:", idx_src)
    print("version_num:", idx_version)
    print("met_domain_name:", idx_domain)

    print("\n--- Zusammenfassung ---")
    print(f"Gültig numerisch TMAX: {valid_tmax:,}")
    print(f"Gültig numerisch TMIN: {valid_tmin:,}")
    print("TMAX QC-Codes:", dict(tmax_q.most_common()))
    print("TMIN QC-Codes:", dict(tmin_q.most_common()))
    print("ob_hour_count:", dict(hours.most_common()))
    print("Beobachtungs-Endstunden:", dict(end_hours.most_common()))
    print("src_id:", dict(src_ids.most_common(20)))
    print("version_num:", dict(versions.most_common()))
    print("met_domain_name:", dict(domains.most_common()))
    print(f"src_id=99999 Commissioning-Zeilen: {commissioning:,}")

    if timestamps:
        print("Erster ob_end_time:", min(timestamps))
        print("Letzter ob_end_time:", max(timestamps))


def main() -> int:
    print("=" * 82)
    print("UK · MET OFFICE MIDAS OPEN DAILY TEMPERATURE PROBE V1")
    print("=" * 82)
    print("Nur Probe. Noch KEIN Cache und KEINE Europa-Integration.")
    print(f"Dataset release: v{DATASET_VERSION}")
    print("Ziel: tägliche max_air_temp / min_air_temp")
    print("Verwendete Datenebene: qc-version-1")
    print()

    print("1) ÖFFENTLICHE ARCHIVSTRUKTUR")
    counties, stations = enumerate_public_inventory()

    print("\n" + "=" * 82)
    print("PUBLIC INVENTORY SUMMARY")
    print("=" * 82)
    print(f"County-Verzeichnisse: {len(counties):,}")
    print(f"Erkannte Stationsverzeichnisse: {len(stations):,}")

    by_county = Counter(s.county for s in stations)
    print("\n20 Counties mit den meisten Stationsverzeichnissen:")
    for county, n in by_county.most_common(20):
        print(f"{county}: {n:,}")

    print("\nErste 30 Stationsverzeichnisse:")
    for st in stations[:30]:
        print(f"{st.src_id} | {st.name} | {st.county} | {st.dirname}")

    samples = select_samples(stations)

    print("\n" + "=" * 82)
    print("2) STICHPROBEN · ÖFFENTLICHE JAHRESLISTEN")
    print("=" * 82)

    sample_year_files: dict[str, list[tuple[int, str, str]]] = {}

    for st in samples:
        key = f"{st.county}/{st.dirname}"
        try:
            files = station_year_files(st)
        except Exception as exc:
            print(f"{key}: FEHLER {exc}")
            continue

        sample_year_files[key] = files
        years = [y for y, _, _ in files]
        if years:
            print(
                f"{st.src_id} | {st.name} | {st.county} | "
                f"qcv1-Jahresdateien={len(files):,} | "
                f"{min(years)}-{max(years)}"
            )
        else:
            print(
                f"{st.src_id} | {st.name} | {st.county} | "
                "keine qcv1-Jahresdateien"
            )

    print("\n" + "=" * 82)
    print("3) CEDA-AUTHENTIFIZIERUNG")
    print("=" * 82)

    try:
        token = get_ceda_token()
    except Exception as exc:
        print("CEDA-LOGIN FEHLGESCHLAGEN:", exc)
        return 2

    if token is None:
        print("CEDA_USERNAME / CEDA_PASSWORD sind nicht als Secrets gesetzt.")
        print()
        print("Die öffentliche Inventur war erfolgreich.")
        print(
            "Für das Lesen der Stationsmetadaten und echten BADC-CSV-Werte "
            "müssen im GitHub-Repository zwei Actions-Secrets gesetzt werden:"
        )
        print("  CEDA_USERNAME")
        print("  CEDA_PASSWORD")
        print()
        print(
            "Danach diesen SELBEN Workflow erneut starten. Das Skript erzeugt "
            "automatisch über die CEDA Token API einen kurzlebigen Bearer-Token."
        )
        print()
        print("FAZIT: Probe Teil 1 erfolgreich; Datendownload benötigt CEDA-Login.")
        return 0

    print("CEDA-Zugang: OK (Bearer-Token automatisch erzeugt)")
    print("Token wird nicht ausgegeben.")

    print("\n" + "=" * 82)
    print("4) STATION METADATA")
    print("=" * 82)

    metadata_url = f"{DAP_ROOT}/{STATION_METADATA_NAME}"
    raw = request_bytes(metadata_url, token=token)
    text = decode_text(raw)
    refs, rows = parse_station_metadata(text)

    print("URL:", metadata_url)
    print(f"Bytes: {len(raw):,}")
    print(f"Metadaten-Spalten: {len(refs):,}")
    print(refs)
    print(f"Metadaten-Datensätze: {len(rows):,}")

    print("\nErste 5 Metadatenzeilen:")
    for row in rows[:5]:
        print(" | ".join(row))

    print("\nLetzte 5 Metadatenzeilen:")
    for row in rows[-5:]:
        print(" | ".join(row))

    print("\n" + "=" * 82)
    print("5) ECHTE DAILY-TEMPERATURE BADC-CSV STICHPROBEN")
    print("=" * 82)

    inspected = 0
    for st in samples:
        key = f"{st.county}/{st.dirname}"
        files = sample_year_files.get(key, [])
        if not files:
            continue

        choices = []
        choices.append(files[0])
        if files[-1] != files[0]:
            choices.append(files[-1])

        for year, name, url in choices:
            try:
                inspect_temperature_file(
                    f"{st.src_id} · {st.name} · {year}",
                    url,
                    token,
                )
                inspected += 1
            except Exception as exc:
                print(
                    f"FEHLER bei {st.src_id} {st.name} {year}: {exc}",
                    flush=True,
                )

    print("\n" + "=" * 82)
    print("FAZIT")
    print("=" * 82)
    print(f"Öffentliche Stationsverzeichnisse: {len(stations):,}")
    print(f"Echte BADC-CSV-Dateien geprüft: {inspected:,}")
    print()
    print("Bitte den vollständigen GitHub-Log schicken, besonders:")
    print("1) PUBLIC INVENTORY SUMMARY")
    print("2) STICHPROBEN · ÖFFENTLICHE JAHRESLISTEN")
    print("3) STATION METADATA")
    print("4) Erkannte MIDAS-Felder")
    print("5) TMAX/TMIN QC-Codes + ob_hour_count + Beobachtungs-Endstunden")
    print()
    print(
        "Danach bauen wir – falls Format und QC eindeutig sind – als nächsten "
        "einzelnen Schritt den historischen UK-Cache bis 2025."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
