#!/usr/bin/env python3
"""Publish only successfully released ERA5 historical years to the Pages index."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

FIRST_YEAR = 1940
LAST_YEAR = 2025
REQUIRED_PRODUCTS = {"t850", "z500", "wind300", "mslp"}
VIEWS = ("absolute", "anomaly", "rank")


def merge(artifact_dir: Path, repo_root: Path) -> list[int]:
    history_dir = repo_root / "era5_europe" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    new_years: list[int] = []
    for item in sorted(artifact_dir.rglob("manifest.json")):
        try:
            content = json.loads(item.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        year = int(content.get("year", 0))
        if not (FIRST_YEAR <= year <= LAST_YEAR):
            continue
        expected_periods = {f"{year:04d}-{month:02d}" for month in range(1, 13)}
        if set(content.get("periods", {})) != expected_periods:
            raise RuntimeError(f"Unvollständiger Monatssatz im Manifest {year}")
        for period, month in content["periods"].items():
            if set(month.get("products", {})) != REQUIRED_PRODUCTS:
                raise RuntimeError(f"Unvollständiger Datensatz {period}")
            for product in month["products"].values():
                for view in VIEWS:
                    url = product.get(view, {}).get("file", "")
                    expected = f"/era5-atmos-history-{year}-v1/"
                    if expected not in url or not url.endswith(".webp"):
                        raise RuntimeError(f"Unerwartete URL {period} {view}: {url}")
        shutil.copy2(item, history_dir / f"{year}.json")
        new_years.append(year)

    if not new_years:
        raise RuntimeError("Kein vollständig veröffentlichtes historisches Jahr vorhanden")

    index_path = repo_root / "era5_europe" / "index.json"
    root = json.loads(index_path.read_text(encoding="utf-8"))
    existing = [
        int(year) for year in root.get("history_years", [])
        if FIRST_YEAR <= int(year) <= LAST_YEAR
    ]
    root["history_years"] = sorted(set(existing + new_years))
    root["history_archive_start"] = FIRST_YEAR
    root["history_archive_end"] = LAST_YEAR
    root["history_archive_type"] = "monthly-remote-webp-releases"
    root["history_archive_note"] = (
        "Historical monthly images are hosted in annual GitHub Releases. "
        "The year appears only after all 144 maps and manifest are published."
    )
    index_path.write_text(
        json.dumps(root, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Historische Jahre ergänzt: {len(new_years)}", flush=True)
    print(f"Insgesamt verfügbar: {len(root['history_years'])} historische Jahre", flush=True)
    return new_years


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    merge(args.artifacts, args.repo)


if __name__ == "__main__":
    main()
