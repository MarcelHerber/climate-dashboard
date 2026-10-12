#!/usr/bin/env python3
"""Publish ERA5-Europe monthly-backfill artifacts without replacing the latest month."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

PRODUCTS = {"t850", "z500", "wind300", "mslp"}
VIEWS = ("absolute", "anomaly", "rank")
MONTHS = tuple(f"2026-{month:02d}" for month in range(1, 9))


def publish(artifacts: Path, repository: Path) -> list[str]:
    validated: list[tuple[str, Path]] = []
    for period in MONTHS:
        source = artifacts / f"era5-europe-{period}"
        index_file = source / "index.json"
        if not index_file.is_file():
            raise RuntimeError(f"Monatsartefakt fehlt: {period}")
        metadata = json.loads(index_file.read_text(encoding="utf-8"))
        if (
            metadata.get("period") != period
            or metadata.get("year") != 2026
            or metadata.get("month") != int(period[-2:])
        ):
            raise RuntimeError(f"Falsches Monatsartefakt: {period}")
        if set(metadata.get("products", {})) != PRODUCTS:
            raise RuntimeError(f"Fehlende Parameter: {period}")
        for product in metadata["products"].values():
            for view in VIEWS:
                expected = Path(product[view]["file"])
                if expected.parent.as_posix() != f"era5_europe/archive/{period}":
                    raise RuntimeError(f"Ungültiger Archivpfad: {expected}")
                actual = source / expected.name
                if not actual.is_file() or actual.stat().st_size <= 1000:
                    raise RuntimeError(f"Fehlende ERA5-Karte: {actual}")
            rank = product["rank"]
            if rank.get("history_start") != 1940 or rank.get("history_end") != 2026:
                raise RuntimeError(f"Historie unvollständig: {period}")
        validated.append((period, source))

    archive = repository / "era5_europe/archive"
    for period, source in validated:
        target = archive / period
        target.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            if item.is_file():
                shutil.copy2(item, target / item.name)

    root_index = repository / "era5_europe/index.json"
    payload = json.loads(root_index.read_text(encoding="utf-8"))
    current = set(payload.get("available_periods", []))
    payload["available_periods"] = sorted(current | set(MONTHS))
    # Keep the latest month and all live maps on main untouched.
    root_index.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + chr(10),
        encoding="utf-8",
    )
    print("Fertiges Monatsarchiv:", ", ".join(payload["available_periods"]), flush=True)
    return payload["available_periods"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    publish(args.artifacts, args.repo)
