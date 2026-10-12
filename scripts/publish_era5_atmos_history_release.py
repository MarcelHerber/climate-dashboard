#!/usr/bin/env python3
"""Resumable GitHub Release publishing for an ERA5 atmospheric history year.

Skips assets that already exist, retries temporary rate limits, and publishes the
manifest only after all 48 map atlases are available.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

MAX_RETRIES = 18
WAIT_SECONDS = 300
EXPECTED_ATLASES = 48


def gh(*args: str) -> str:
    for attempt in range(1, MAX_RETRIES + 1):
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
        failure = (proc.stdout + "\n" + proc.stderr).strip()
        rate_limited = any(
            phrase in failure.lower()
            for phrase in (
                "api rate limit exceeded",
                "secondary rate limit",
                "rate limit exceeded",
                "too many requests",
                "http 429",
                "http 403",
                "abuse detection",
            )
        )
        if not rate_limited or attempt == MAX_RETRIES:
            raise RuntimeError(
                f"gh {' '.join(args[:3])} failed (attempt {attempt}): "
                f"{failure[-2500:]}"
            )
        print(
            f"GitHub-Limit bei {' '.join(args[:3])}; "
            f"Versuch {attempt}/{MAX_RETRIES}. "
            f"Nächster Versuch nach {WAIT_SECONDS} Sekunden.",
            flush=True,
        )
        time.sleep(WAIT_SECONDS)
    raise RuntimeError("Unexpected retry end")


def release_assets(tag: str) -> set[str]:
    raw = gh("release", "view", tag, "--json", "assets", "--jq", ".assets[].name")
    return set(raw.splitlines())


def ensure_release(tag: str, year: int) -> None:
    # A missing release returns HTTP 404, whereas HTTP 403 requires waiting.
    for attempt in range(1, MAX_RETRIES + 1):
        result = subprocess.run(
            ["gh", "release", "view", tag],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            return
        error = (result.stdout + "\n" + result.stderr).lower()
        if "not found" in error or "http 404" in error:
            break
        if "rate limit" not in error and "http 403" not in error:
            raise RuntimeError(result.stderr[-2500:])
        print(f"API-Limit beim Release-Check: {year}. Pause {WAIT_SECONDS}s.", flush=True)
        time.sleep(WAIT_SECONDS)
    notes = (
        "144 ERA5-Ansichten (12 Monate × 4 Felder × Absolutwert/Anomalie/Rang) "
        "in 48 WebP-Atlanten. Referenz 1991–2020, Ränge 1940–2025."
    )
    gh(
        "release", "create", tag, "--target", "main",
        "--title", f"ERA5 Atmosphäre historische Monatskarten {year}",
        "--notes", notes,
    )


def publish(year: int, folder: Path) -> None:
    tag = f"era5-atmos-history-{year}-v1"
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Missing manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("year") != year:
        raise RuntimeError(f"Year mismatch in {manifest_path}")
    if len(manifest.get("periods", {})) != 12:
        raise RuntimeError(f"Incomplete monthly manifest: {year}")
    images = sorted(folder.glob("*.webp"))
    if len(images) != EXPECTED_ATLASES:
        raise RuntimeError(f"Expected {EXPECTED_ATLASES} atlases, got {len(images)}")
    ensure_release(tag, year)
    uploaded = release_assets(tag)
    for index, path in enumerate(images, start=1):
        if path.name in uploaded:
            continue
        gh("release", "upload", tag, str(path))
        uploaded.add(path.name)
        print(f"{year}: Atlas {index}/{EXPECTED_ATLASES} veröffentlicht", flush=True)

    final = release_assets(tag)
    expected = {path.name for path in images}
    if not expected.issubset(final):
        missing = sorted(expected - final)
        raise RuntimeError(f"Not all images uploaded for {year}: {missing}")
    if manifest_path.name not in final:
        gh("release", "upload", tag, str(manifest_path))
    verified = release_assets(tag)
    if not expected.issubset(verified) or "manifest.json" not in verified:
        raise RuntimeError(f"Release missing assets after verification: {year}")
    print(
        f"Historisches Jahr {year} vollständig: 48 WebP-Atlanten + Manifest.",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    publish(args.year, args.directory)
