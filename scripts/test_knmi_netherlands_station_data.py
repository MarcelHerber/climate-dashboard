#!/usr/bin/env python3
"""
Probe for KNMI daily station observations.

This script only inspects the API/file structure. It does not build a baseline
and does not modify the Europe station output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_ROOT = "https://api.dataplatform.knmi.nl/open-data/v1"

VALIDATED_DATASET = "daily-in-situ-meteorological-observations-validated"
VALIDATED_VERSION = "1.0"

CURRENT_DATASET = "daily-in-situ-meteorological-observations"
CURRENT_VERSION = "1.0"

# Official public anonymous KNMI Open Data API key.
# According to KNMI documentation this key is valid until 2027-08-01.
OFFICIAL_ANONYMOUS_KEY = (
    "eyJvcmciOiI1ZTU1NGUxOTI3NGE5NjAwMDEyYTNlYjEiLCJpZCI6"
    "IjUzYTg1ZDBhMmQ5YzRkYzJiYWNlNzQ4NTQ2Zjk4ODExIiwiaCI6"
    "Im11cm11cjEyOCJ9"
)

USER_AGENT = "climate-dashboard-knmi-probe/1.0"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def request_json(url: str, api_key: str, timeout: int = 90) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} für {url}: {body[:800]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Netzwerkfehler für {url}: {exc}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Antwort ist kein JSON ({len(raw)} Bytes) für {url}"
        ) from exc


def download_file(url: str, dest: Path, timeout: int = 180) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response, dest.open("wb") as f:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def list_files(
    api_key: str,
    dataset: str,
    version: str,
    *,
    sorting: str,
    max_keys: int = 5,
) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {"maxKeys": max_keys, "sorting": sorting, "orderBy": "filename"}
    )
    url = (
        f"{API_ROOT}/datasets/{urllib.parse.quote(dataset)}/versions/"
        f"{urllib.parse.quote(version)}/files?{params}"
    )
    payload = request_json(url, api_key)

    candidates = []
    if isinstance(payload, dict):
        for key in ("files", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
    elif isinstance(payload, list):
        candidates = payload

    normalized: list[dict[str, Any]] = []
    for item in candidates:
        if isinstance(item, str):
            normalized.append({"filename": item})
        elif isinstance(item, dict):
            name = (
                item.get("filename")
                or item.get("fileName")
                or item.get("name")
                or item.get("key")
            )
            if name:
                out = dict(item)
                out["filename"] = str(name)
                normalized.append(out)

    if not normalized:
        raise RuntimeError(
            f"Keine Dateinamen für {dataset}/{version} erkannt. "
            f"Antworttyp={type(payload).__name__}"
        )
    return normalized


def get_download_url(
    api_key: str, dataset: str, version: str, filename: str
) -> str:
    quoted_name = urllib.parse.quote(filename, safe="")
    url = (
        f"{API_ROOT}/datasets/{urllib.parse.quote(dataset)}/versions/"
        f"{urllib.parse.quote(version)}/files/{quoted_name}/url"
    )
    payload = request_json(url, api_key)
    if not isinstance(payload, dict):
        raise RuntimeError("Unerwartete Download-URL-Antwort.")

    for key in ("temporaryDownloadUrl", "downloadUrl", "url", "href"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

    raise RuntimeError(
        f"Keine Download-URL gefunden; Antwortschlüssel: {list(payload)}"
    )


def attrs(var: Any) -> dict[str, Any]:
    out = {}
    for name in var.ncattrs():
        try:
            value = getattr(var, name)
            if hasattr(value, "item"):
                value = value.item()
            out[name] = value
        except Exception:
            pass
    return out


def score_variable(name: str, var: Any, mode: str) -> int:
    meta = attrs(var)
    text = " ".join(
        [
            name,
            str(meta.get("standard_name", "")),
            str(meta.get("long_name", "")),
            str(meta.get("description", "")),
            str(meta.get("units", "")),
        ]
    ).lower()

    score = 0
    if mode == "tmax":
        for token, points in (
            ("maximum air temperature", 20),
            ("daily maximum", 15),
            ("maximum temperature", 12),
            ("air_temperature_maximum", 15),
            ("temperature_maximum", 12),
            ("tmax", 10),
            ("tx", 5),
        ):
            if token in text:
                score += points
    elif mode == "tmin":
        for token, points in (
            ("minimum air temperature", 20),
            ("daily minimum", 15),
            ("minimum temperature", 12),
            ("air_temperature_minimum", 15),
            ("temperature_minimum", 12),
            ("tmin", 10),
            ("tn", 5),
        ):
            if token in text:
                score += points
    elif mode == "station":
        for token, points in (
            ("wigos", 20),
            ("station identifier", 15),
            ("station_id", 12),
            ("station id", 12),
            ("station", 4),
        ):
            if token in text:
                score += points
    elif mode == "time":
        if name.lower() == "time":
            score += 20
        if "time" in str(meta.get("standard_name", "")).lower():
            score += 15
        if "since" in str(meta.get("units", "")).lower():
            score += 10
    return score


def best_candidates(ds: Any, mode: str, limit: int = 5) -> list[tuple[int, str]]:
    scored = []
    for name, var in ds.variables.items():
        score = score_variable(name, var, mode)
        if score > 0:
            scored.append((score, name))
    scored.sort(reverse=True)
    return scored[:limit]


def preview_values(var: Any, max_items: int = 8) -> str:
    try:
        data = var[:]
        flat = data.flatten() if hasattr(data, "flatten") else data
        vals = []
        for value in flat[:max_items]:
            if hasattr(value, "item"):
                value = value.item()
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            vals.append(value)
        return repr(vals)
    except Exception as exc:
        return f"<nicht lesbar: {exc}>"


def inspect_netcdf(path: Path, label: str) -> dict[str, Any]:
    try:
        import netCDF4
    except ImportError as exc:
        raise RuntimeError(
            "netCDF4 fehlt. Der GitHub-Workflow installiert das Paket automatisch."
        ) from exc

    log(f"\n=== NetCDF-Prüfung: {label} ===")
    log(f"Datei: {path.name} | Größe: {path.stat().st_size / 1024:.1f} KiB")

    result: dict[str, Any] = {}
    with netCDF4.Dataset(path, "r") as ds:
        log("Dimensionen:")
        for name, dim in ds.dimensions.items():
            log(f"  - {name}: {len(dim)}")

        log(f"Variablen ({len(ds.variables)}):")
        for name, var in ds.variables.items():
            meta = attrs(var)
            log(
                f"  - {name}: dtype={var.dtype}, dims={var.dimensions}, "
                f"standard_name={meta.get('standard_name', '')!r}, "
                f"long_name={meta.get('long_name', '')!r}, "
                f"units={meta.get('units', '')!r}"
            )

        for mode in ("station", "time", "tmax", "tmin"):
            candidates = best_candidates(ds, mode)
            result[mode] = candidates
            log(f"\nKandidaten {mode.upper()}:")
            if not candidates:
                log("  <keine automatisch erkannt>")
            for score, name in candidates:
                log(
                    f"  score={score:2d} {name}: "
                    f"Vorschau {preview_values(ds.variables[name])}"
                )

        if not result["tmax"] or not result["tmin"]:
            raise RuntimeError(
                "Tmax/Tmin konnten in dieser NetCDF-Stichprobe nicht beide "
                "automatisch erkannt werden. Alle Variablen stehen im Log."
            )
    return result


def probe_dataset(
    api_key: str,
    dataset: str,
    version: str,
    *,
    sample_oldest: bool,
    sample_newest: bool,
    temp_dir: Path,
) -> dict[str, Any]:
    log(f"\n{'=' * 72}")
    log(f"DATENSATZ: {dataset}/{version}")
    log(f"{'=' * 72}")

    oldest = list_files(api_key, dataset, version, sorting="asc", max_keys=5)
    newest = list_files(api_key, dataset, version, sorting="desc", max_keys=5)

    log("Älteste gelistete Dateien:")
    for item in oldest:
        log(f"  - {item['filename']}")

    log("Neueste gelistete Dateien:")
    for item in newest:
        log(f"  - {item['filename']}")

    summary = {
        "dataset": dataset,
        "version": version,
        "oldest_files": [x["filename"] for x in oldest],
        "newest_files": [x["filename"] for x in newest],
        "samples": [],
    }

    choices: list[tuple[str, str]] = []
    if sample_oldest:
        choices.append(("älteste Datei", oldest[0]["filename"]))
    if sample_newest:
        choices.append(("neueste Datei", newest[0]["filename"]))

    seen: set[str] = set()
    for label, filename in choices:
        if filename in seen:
            continue
        seen.add(filename)

        log(f"\nHole Download-URL für {label}: {filename}")
        dl_url = get_download_url(api_key, dataset, version, filename)
        suffix = Path(filename).suffix or ".nc"
        safe_dataset = re.sub(r"[^A-Za-z0-9_.-]+", "_", dataset)
        local = temp_dir / f"{safe_dataset}_{len(seen)}{suffix}"
        download_file(dl_url, local)

        detected = inspect_netcdf(local, f"{dataset} – {label}")
        summary["samples"].append(
            {"label": label, "filename": filename, "detected": detected}
        )

    return summary


def self_test() -> None:
    assert VALIDATED_DATASET.endswith("-validated")
    assert CURRENT_DATASET != VALIDATED_DATASET
    assert len(OFFICIAL_ANONYMOUS_KEY) > 80
    assert urllib.parse.quote("a b.nc", safe="") == "a%20b.nc"

    class FakeVar:
        def ncattrs(self):
            return ["standard_name", "long_name", "units"]
        standard_name = "air_temperature"
        long_name = "daily maximum air temperature"
        units = "K"

    fake = FakeVar()
    assert score_variable("temperature_max", fake, "tmax") > 0
    assert score_variable("temperature_max", fake, "tmin") == 0
    print("KNMI Netherlands probe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    supplied_key = os.environ.get("KNMI_API_KEY", "").strip()
    api_key = supplied_key or OFFICIAL_ANONYMOUS_KEY
    auth_kind = (
        "KNMI_API_KEY aus GitHub/Umgebung"
        if supplied_key
        else "offizieller anonymer KNMI-Key"
    )

    log("=== KNMI NIEDERLANDE PROBE ===")
    log(f"Authentifizierung: {auth_kind}")
    log("Es werden nur wenige Stichprobendateien geladen.")

    with tempfile.TemporaryDirectory(prefix="knmi_probe_") as tmp:
        temp_dir = Path(tmp)

        validated = probe_dataset(
            api_key,
            VALIDATED_DATASET,
            VALIDATED_VERSION,
            sample_oldest=True,
            sample_newest=True,
            temp_dir=temp_dir,
        )

        current = None
        try:
            current = probe_dataset(
                api_key,
                CURRENT_DATASET,
                CURRENT_VERSION,
                sample_oldest=False,
                sample_newest=True,
                temp_dir=temp_dir,
            )
        except Exception as exc:
            log(
                "\nWARNUNG: Der aktuelle Tagesdatensatz konnte nicht vollständig "
                f"geprüft werden: {exc}"
            )
            log(
                "Das blockiert die historische validierte Quelle nicht; "
                "der 2026-Pfad wird dann separat angepasst."
            )

        log("\n=== PROBE-ZUSAMMENFASSUNG ===")
        log(
            f"Validierter Datensatz: "
            f"{len(validated['samples'])} NetCDF-Stichproben erfolgreich."
        )
        if current is not None:
            log(
                f"Aktueller Datensatz: "
                f"{len(current['samples'])} NetCDF-Stichprobe(n) erfolgreich."
            )
        else:
            log("Aktueller Datensatz: separat zu klären.")
        log("KNMI Netherlands Probe OK.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
