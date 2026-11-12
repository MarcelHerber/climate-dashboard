#!/usr/bin/env python3
"""Official CPC GEFS/GFS NAO/AO daily index forecasts for GitHub Pages.

Inputs are NOAA/CPC normalized daily index CSV products, not raw model fields.
No fabrication, interpolation, artificial members or mixing of index definitions.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "nao_ao_forecast" / "latest.json"
BASE = "https://ftp.cpc.ncep.noaa.gov/cwlinks/"
SOURCE = {
    index: {
        "gefs": BASE + f"norm.daily.{index}.gefs.{level}.120days.csv",
        "gfs": BASE + f"norm.daily.{index}.gfs.{level}.120days.csv",
        "obs": BASE + f"norm.daily.{index}.cdas.{level}.19500101_current.csv",
    }
    for index, level in (("nao", "z500"), ("ao", "z1000"))
}
MAX_FORECAST_DAYS = 15
MEMBER_COUNT = 31
MISSING = {"", "nan", "NaN", "null", "-99", "-99.00", "-999", "-9999"}


def download(url: str, attempts: int = 3) -> str:
    for attempt in range(attempts):
        try:
            req = Request(url, headers={
                "User-Agent": "climate-dashboard/noaa-index-forecast/1.0",
                "Accept": "text/csv,text/plain,*/*",
            })
            with urlopen(req, timeout=55) as response:
                content = response.read()
            if len(content) < 100:
                raise ValueError("Quelle liefert ungewöhnlich wenig Daten")
            return content.decode("utf-8-sig", errors="replace")
        except (OSError, ValueError) as exc:
            if attempt + 1 == attempts:
                raise RuntimeError(f"NOAA-Datenquelle nicht erreichbar: {url}: {exc}") from exc
            time.sleep((attempt + 1) * 3)
    raise AssertionError("unreachable")


def parse_model_csv(text: str, index: str, model: str) -> dict[str, dict[int, dict[int, float]]]:
    """Return run -> lead day -> member -> original CPC standardized index."""
    if index not in ("nao", "ao") or model not in ("gefs", "gfs"):
        raise ValueError("Unbekannter Index oder Modelltyp")
    reader = csv.DictReader(io.StringIO(text))
    required = {"lead", "time", "valid_time", f"{index}_index"}
    if model == "gefs":
        required.add("member")
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError(f"CPC-CSV-Spalten geändert: {reader.fieldnames}")
    runs: dict[str, dict[int, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    for row in reader:
        try:
            run_date = date.fromisoformat(row["time"])
            lead = int(row["lead"])
            valid = date.fromisoformat(row["valid_time"])
            member = int(row["member"]) if model == "gefs" else -1
            raw = row[f"{index}_index"].strip()
            if (lead < 0 or lead > MAX_FORECAST_DAYS
                    or valid != run_date + timedelta(days=lead)
                    or (model == "gefs" and not 0 <= member < MEMBER_COUNT)
                    or raw in MISSING):
                continue
            val = float(raw)
            if not math.isfinite(val) or abs(val) > 15:
                continue
        except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
            continue
        runs[run_date.isoformat()][lead][member] = val
    if not runs:
        raise ValueError(f"Keine gültigen CPC-{index.upper()}-{model.upper()}-Werte erkannt")
    return dict(runs)


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        raise ValueError("Quantil ohne Ensemblewerte")
    rank = p * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (rank - lo)


def summarize_run(run_date: str, rows: dict[int, dict[int, float]], *, full: bool = False) -> dict:
    """Require >=25/31 members per day: no invented statistics in partial data."""
    if any(len(rows.get(lead, {})) < 25 for lead in range(16)):
        raise ValueError(f"GEFS-Lauf {run_date}: weniger als 25 Member an mindestens einem Tag")
    members = {
        str(m): [round(rows[lead][m], 3) if m in rows[lead] else None for lead in range(16)]
        for m in range(MEMBER_COUNT)
    }
    mean = []
    p10 = []
    p90 = []
    n = []
    probability = {"negative": [], "positive": [], "strong_negative": [], "strong_positive": []}
    for lead in range(16):
        values = sorted(rows[lead].values())
        count = len(values)
        n.append(count)
        mean.append(round(sum(values) / count, 3))
        p10.append(round(percentile(values, 0.10), 3))
        p90.append(round(percentile(values, 0.90), 3))
        probability["negative"].append(round(100 * sum(x < 0 for x in values) / count, 1))
        probability["positive"].append(round(100 * sum(x >= 0 for x in values) / count, 1))
        probability["strong_negative"].append(round(100 * sum(x <= -1 for x in values) / count, 1))
        probability["strong_positive"].append(round(100 * sum(x >= 1 for x in values) / count, 1))
    out = {
        "init_date": run_date,
        "valid_dates": [(date.fromisoformat(run_date) + timedelta(days=i)).isoformat() for i in range(16)],
        "mean": mean,
        "p10": p10,
        "p90": p90,
        "member_count": n,
    }
    if full:
        out.update({"members": members, "probability": probability})
    return out


def parse_observations(text: str, index: str) -> list[list]:
    # Reuse exactly the importer used on the existing historical NAO/AO page.
    from update_climate_indices import parse_daily_csv
    rows = parse_daily_csv(text, index)
    return rows[-60:]


def build(fetch=download, today: date | None = None) -> dict:
    today = today or date.today()
    output = {
        "schema": 1, "ready": True, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publisher": "NOAA Climate Prediction Center",
        "lead_days": list(range(16)), "expected_gefs_members": MEMBER_COUNT,
        "models": ["GEFS", "GFS"],
        "index_method": "CPC daily standardized NAO from Z500 and AO from Z1000. All values are original CPC forecast indices; GEFS member statistics calculated for this dashboard.",
        "indices": {},
    }
    for index in ("nao", "ao"):
        sources = SOURCE[index]
        gefs = parse_model_csv(fetch(sources["gefs"]), index, "gefs")
        gfs = parse_model_csv(fetch(sources["gfs"]), index, "gfs")
        candidates = []
        for run_date in sorted(gefs, reverse=True):
            try:
                candidates.append(summarize_run(run_date, gefs[run_date], full=not candidates))
            except ValueError:
                continue
            if len(candidates) >= 8:
                break
        if not candidates:
            raise RuntimeError(f"{index.upper()}: kein vollständiger GEFS-Lauf")
        latest = candidates[0]
        if date.fromisoformat(latest["init_date"]) < today - timedelta(days=4):
            raise RuntimeError(f"{index.upper()}: letzter vollständiger GEFS-Lauf {latest['init_date']} ist zu alt")
        deterministic_candidates = [
            run_date for run_date in sorted(gfs, reverse=True)
            if all(-1 in gfs[run_date].get(i, {}) for i in range(16))
        ]
        if deterministic_candidates:
            gfs_date = deterministic_candidates[0]
            if date.fromisoformat(gfs_date) >= today - timedelta(days=4):
                latest["gfs"] = {
                    "init_date": gfs_date,
                    "valid_dates": [(date.fromisoformat(gfs_date) + timedelta(days=i)).isoformat() for i in range(16)],
                    "values": [round(gfs[gfs_date][i][-1], 3) for i in range(16)],
                }
        observations = parse_observations(fetch(sources["obs"]), index)
        if date.fromisoformat(observations[-1][0]) < today - timedelta(days=10):
            raise RuntimeError(f"{index.upper()}: Beobachtungen veraltet ({observations[-1][0]})")
        output["indices"][index] = {
            "sources": sources,
            "observation_latest_date": observations[-1][0],
            "observations": observations,
            "latest": latest,
            "previous_runs": candidates[1:],
            "available_run_count": len(candidates),
            "pressure_hpa": 500 if index == "nao" else 1000,
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    for k, data in result["indices"].items():
        latest = data["latest"]
        print(k.upper(), "GEFS", latest["init_date"], "Member", latest["member_count"],
              "runs", data["available_run_count"], "GFS", latest.get("gfs", {}).get("init_date"),
              "observations", data["observation_latest_date"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
