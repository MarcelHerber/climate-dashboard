#!/usr/bin/env python3
"""Preserve the preceding *real* MOSMIX-L run for station meteogram comparison.

Only variables already present in the previous Germany-only map archive are
copied. UTC-validity timestamps are retained to prevent lead-time mismatches.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path


def attach_previous(previous_path,current_path):
    previous_path=Path(previous_path)
    current_path=Path(current_path)
    if not previous_path.is_file() or not current_path.is_file():
        return 0
    prev=json.loads(previous_path.read_text(encoding="utf-8"))
    curr=json.loads(current_path.read_text(encoding="utf-8"))
    if prev.get("product")!="DWD MOSMIX-L" or curr.get("product")!="DWD MOSMIX-L":
        raise ValueError("Invalid MOSMIX source for run comparison")
    if not isinstance(prev.get("timesteps"),list) or not prev["timesteps"]:
        return 0
    prev_issue=prev.get("issue_time")
    current_issue=curr.get("issue_time")
    if not prev_issue or not current_issue or prev_issue>=current_issue:
        return 0
    lookup={row["key"]:row for row in prev.get("stations",[]) if row.get("key")}
    details=current_path.parent/"stations"
    count=0
    for station in curr["stations"]:
        old=lookup.get(station["key"])
        if not old:
            continue
        f=details/(station["key"]+".json")
        if not f.is_file():
            continue
        detail=json.loads(f.read_text(encoding="utf-8"))
        if detail.get("issue_time")!=current_issue:
            continue
        detail["previous"]={
            "issue_time":prev_issue,
            "timesteps":prev["timesteps"],
            "TTT":old.get("values",[]),
            "TX":old.get("tx12",{}),
            "TN":old.get("tn12",{}),
        }
        f.write_text(json.dumps(detail,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
        count+=1
    print("MOSMIX-Laufvergleich:",prev_issue,"→",current_issue,"|",count,"Stationen")
    return count


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("previous")
    parser.add_argument("current")
    args=parser.parse_args()
    attach_previous(args.previous,args.current)
