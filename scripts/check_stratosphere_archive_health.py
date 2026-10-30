#!/usr/bin/env python3
"""Audit published stratospheric GEFS/EPS archives and GitHub Pages as a separate
lightweight GitHub Actions check. No data writes and no synthetic forecasts."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard"
SOURCES = {
    "GEFS": dict(branch="stratosphere-ensemble-data", directory="data/stratosphere/ensemble",
                 index="gefs_index.json", current="gefs_current.json",
                 provider="NOAA GEFS", count=31, hours=(0, 6, 12, 18), max_age=24),
    "ECMWF ENS": dict(branch="stratosphere-ecmwf-ens-data", directory="data/stratosphere/ecmwf",
                     index="ens_index.json", current="ens_current.json",
                     provider="ECMWF IFS ENS", count=51, hours=(0, 12), max_age=30),
}


def fetch(url):
    last = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "ClimateDashboard-Stratosphere-Health/1.0"})
            with urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8")
        except (OSError, HTTPError, URLError) as exc:
            last = exc
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f"Cannot verify {url}: {last}") from last


def timestamp(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT(?:00|06|12|18):00:00Z", s):
        raise ValueError(f"Invalid model cycle: {s}")
    result = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if result.strftime("%Y-%m-%dT%H:00:00Z") != s:
        raise ValueError("Invalid UTC calendar date")
    return result


def validate_manifest(name, index, current, now=None):
    """Return (human-readable metrics, hard errors, warnings)."""
    now = now or datetime.now(timezone.utc)
    cfg = SOURCES[name]
    errors, warnings = [], []
    if not isinstance(index, dict) or not isinstance(current, dict):
        return {}, ["Malformed published JSON"], warnings
    if index.get("schema_version") != 1 or index.get("provider") != cfg["provider"]:
        errors.append("Invalid model index/provider")
    if current.get("schema_version") != 1 or current.get("provider") != cfg["provider"]:
        errors.append("Invalid latest run/provider")
    if current.get("level_hpa") != 10 or current.get("latitude_deg") != 60 or current.get("units") != "m/s":
        errors.append("Incorrect physical parameter or units")
    try:
        latest = timestamp(index["latest_cycle_utc"])
        cycle = timestamp(current["cycle_utc"])
        if latest != cycle:
            errors.append("Archive index latest cycle differs from current published run")
        if cycle.hour not in cfg["hours"]:
            errors.append("Invalid cycle hour")
        age = (now - cycle).total_seconds() / 3600
        if not 0 <= age <= cfg["max_age"]:
            errors.append(f"Latest original forecast age is {age:.1f}h (limit {cfg['max_age']}h)")
    except (KeyError, ValueError) as exc:
        errors.append(str(exc))
        latest = now
        age = None
    members = current.get("members")
    names = {"c00"} | {f"p{i:02d}" for i in range(1, cfg["count"])}
    dates = current.get("valid_dates")
    horizon = current.get("forecast_horizon_days")
    if (not isinstance(members, dict) or set(members) != names or
        current.get("member_count") != cfg["count"] or
        not isinstance(horizon, int) or (name == "GEFS" and horizon not in (16, 35)) or
        (name == "ECMWF ENS" and horizon != 15) or
        not isinstance(dates, list) or len(dates) != horizon + 1 if isinstance(horizon, int) else True):
        errors.append("Incomplete member/forecast horizon metadata")
    elif any(not isinstance(v, list) or len(v) != len(dates) or
             any(not isinstance(x, (int, float)) or not -160 < x < 170 for x in v)
             for v in members.values()):
        errors.append("Unverified or incomplete original member values")
    records = index.get("runs")
    cycles = []
    if not isinstance(records, list) or not records:
        errors.append("Empty/nonexistent run archive")
    else:
        for entry in records:
            try:
                t = timestamp(entry["cycle_utc"])
                if t.hour not in cfg["hours"]:
                    raise ValueError("Archive cycle hour not permitted")
                if entry.get("path") != f"runs/{t:%Y%m%d_%H%M%S}.json":
                    raise ValueError("Archive file name does not match its cycle")
                cycles.append(t)
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(f"Invalid archived run entry: {exc}")
        if cycles and cycles != sorted(set(cycles), reverse=True):
            errors.append("Archive contains duplicate or unsorted runs")
        # Do not demand a complete 00/06/12/18 history during the first 48h
        # of collecting archived cycles. Later, flag missing initialization
        # hours independently of overall forecast freshness.
        if cycles and min(cycles) <= now - timedelta(hours=48):
            observed = {x.hour for x in cycles if now - x <= timedelta(hours=96)}
            missing = set(cfg["hours"]) - observed
            if missing:
                errors.append("Required initialization hours absent in the recent archive: " +
                              ", ".join(f"{h:02d} UTC" for h in sorted(missing)))
        else:
            warnings.append("Run archive still in early backfill period; cycle coverage pending")
    metrics = {
        "model": name,
        "latest_utc": current.get("cycle_utc", "?"),
        "age_hours": round(age, 1) if age is not None else None,
        "members": len(members) if isinstance(members, dict) else 0,
        "archive_runs": len(records) if isinstance(records, list) else 0,
        "hours": sorted({c.hour for c in cycles}),
    }
    return metrics, errors, warnings


def check_pages():
    base = "https://marcelherber.github.io/climate-dashboard/"
    html = fetch(base + "stratosphaere.html")
    code = fetch(base + "stratosphere_reversal_diagnostics.js")
    missing = [needle for needle in (
        'id="stratoHeatmap"', 'id="stratoReversalDiagnostics"',
        'stratosphere_reversal_diagnostics.js'
    ) if needle not in html]
    if missing or "function analyzeMember(" not in code:
        return ["GitHub Pages is still missing diagnostics/heatmap assets: " + ", ".join(missing)]
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-pages", action="store_true", help="Only validate the source data branches")
    opts = parser.parse_args()
    now = datetime.now(timezone.utc)
    report = ["# Stratosphären-Datenversorgung", "", f"Check UTC: {now:%Y-%m-%d %H:%M}", ""]
    errors = []
    for name, cfg in SOURCES.items():
        url = f"{ROOT}/{cfg['branch']}/{cfg['directory']}/"
        try:
            index = json.loads(fetch(url + cfg["index"]))
            current = json.loads(fetch(url + cfg["current"]))
            metrics, problems, warnings = validate_manifest(name, index, current, now)
            state = "FAIL" if problems else "OK"
            report.append(f"- **{name}: {state}** · {metrics.get('latest_utc')} · "
                          f"{metrics.get('members')}/{cfg['count']} Mitglieder · "
                          f"{metrics.get('archive_runs')} archivierte Zyklen · "
                          f"{metrics.get('age_hours')} h alt")
            for note in warnings:
                report.append("  - Hinweis: " + note)
            for problem in problems:
                report.append("  - Problem: " + problem)
                errors.append(f"{name}: {problem}")
        except (ValueError, RuntimeError) as exc:
            errors.append(f"{name}: {exc}")
            report.append(f"- **{name}: FAIL** · {exc}")
    if not opts.skip_pages:
        try:
            pages_problems = check_pages()
            report.append("- **GitHub Pages: " + ("FAIL" if pages_problems else "OK") + "**")
            errors += pages_problems
            report.extend("  - Problem: " + x for x in pages_problems)
        except RuntimeError as exc:
            errors.append(f"GitHub Pages: {exc}")
            report.append(f"- **GitHub Pages: FAIL** · {exc}")
    report.extend(["", "Kein fehlender Ensemblewert wird ergänzt oder interpoliert."])
    result = "\n".join(report) + "\n"
    print(result)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(result)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
