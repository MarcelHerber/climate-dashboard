"""Compute paired medians, retain individual results and configuration."""
import json
import statistics
import sys
from pathlib import Path

root = Path(sys.argv[1])
device = sys.argv[2]
metrics = ("first-contentful-paint", "largest-contentful-paint", "speed-index",
           "total-blocking-time", "cumulative-layout-shift", "interactive", "total-byte-weight")
stages = {}
config = None
for stage in (sys.argv[3:] or ("baseline", "extract", "defer", "lazy")):
    rows = []
    for path in sorted(root.glob(f"{stage}-*.report.json")):
        report = json.loads(path.read_text())
        if report.get("runtimeError"):
            raise SystemExit(f"{path}: {report['runtimeError']}")
        comparable = (report["lighthouseVersion"], report["environment"]["hostUserAgent"], report["configSettings"])
        if config is None:
            config = comparable
        elif config != comparable:
            raise SystemExit(f"Non-comparable configuration: {path}")
        rows.append({"file": path.name, "fetchTime": report["fetchTime"],
                     "score": 100 * report["categories"]["performance"]["score"],
                     **{key: report["audits"][key]["numericValue"] for key in metrics}})
    if len(rows) != 3:
        raise SystemExit(f"Expected three cold audits for {stage}, got {len(rows)}")
    stages[stage] = {"runs": rows, "median": {key: statistics.median(row[key] for row in rows)
                    for key in ("score", *metrics)}}
baseline = next(iter(stages.values()))["median"]
for stage, entry in stages.items():
    entry["delta_vs_baseline"] = {key: value - baseline[key] for key, value in entry["median"].items()}
summary = {"device": device, "config": config, "stages": stages}
(root / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps({stage: entry["median"] for stage, entry in stages.items()}, indent=2))
