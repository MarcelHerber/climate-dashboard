#!/usr/bin/env bash
# Reconcile all validated original DWD records against the CURRENT main branch.
# A concurrent build may have written newer archives after this run started.
set -euo pipefail

parts="_hourly_parts"
if [ "$#" -ge 1 ]; then parts="$1"; fi
expected=8
if [ "$#" -ge 2 ]; then expected="$2"; fi
parts="$(realpath "$parts")"
if [ ! -d "$parts" ]; then
  echo "Verified DWD hourly shard artifacts absent: $parts" >&2
  exit 1
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

for attempt in 1 2 3 4 5; do
  echo "DWD hourly publisher: fresh main merge attempt $attempt"
  git fetch origin main
  # All validated artifacts are untracked and survive the reset.
  git reset --hard origin/main

  python -u scripts/merge_rekordlabor_hourly.py \
    --parts "$parts" \
    --archive data/rekordlabor/weather_turns \
    --expected-shards "$expected"

  git add data/rekordlabor/weather_turns
  if git diff --cached --quiet; then
    echo "DWD hourly records already fully published; nothing to push."
    exit 0
  fi

  git commit -m "data: publish every validated DWD historical hourly station"
  if git push origin HEAD:main; then
    echo "DWD original hourly archives successfully published from verified shards."
    exit 0
  fi
  echo "Main changed during DWD hourly publishing. Rebuilding the validated merge on newest main."
  sleep "$((attempt * 4))"
done

echo "DWD station archives remain in Actions artifacts but could not be pushed after five fresh merges." >&2
exit 1
