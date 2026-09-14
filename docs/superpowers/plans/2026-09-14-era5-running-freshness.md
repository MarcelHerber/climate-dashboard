# ERA5 Running Freshness Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent stale ERA5-Land running data from remaining published and prevent the temperature-rank backfill from accepting a stale partial-month cutoff.

**Architecture:** Prebuild the immutable 1991–2020 daily reference for each calendar month once, restore it into the daily running workflow, and probe the newest common T/P day before every render. Validate the rendered index against that exact probe date. Independently probe temperature availability inside the rank-backfill current-stack builder and reject any planned end day that disagrees with the fresh probe.

**Tech Stack:** Python 3.13, pytest, GitHub Actions, CDS API, xarray/NetCDF.

**Spec:** User request in chat on 2026-09-14.

## Global Constraints

- Keep ERA5-Land maps on the existing 0.1° grid.
- Keep the 1991–2020 reference period unchanged.
- Do not publish a running index whose `data_through` differs from the fresh common T/P probe.
- Do not build a rank-backfill current stack whose `end_day` differs from fresh temperature availability.

---

### Task 1: Freshness guard

**Files:**
- Create: `scripts/era5_running_freshness_guard.py`
- Create: `tests/test_era5_running_freshness_guard.py`

**Interfaces:**
- Produces: `select_reference_month(...)`, `validate_index_data_through(...)`, `validate_backfill_end_day(...)`.

- [x] Write failing tests for stale index and stale partial-month plans.
- [x] Run tests and confirm the new module/functions are missing.
- [x] Implement the minimal guard functions and CLI.
- [x] Run the tests and confirm they pass.

### Task 2: Reliable daily running update

**Files:**
- Modify: `.github/workflows/update-era5-land-running.yml`
- Modify: `.github/workflows/build-era5-land-running-reference-0p1.yml`

**Interfaces:**
- Consumes: `era5-land-running-0p1-reference-v1-YYYY-MM` cache.
- Produces: a rendered `era5_land_europe/running/index.json` validated against the fresh probe.

- [x] Schedule the full historical reference cache on the first day of each calendar month.
- [x] Restore the exact reference cache selected by the fresh T/P probe before rendering.
- [x] Fail on a missing reference cache rather than falling back to hours of historical downloads.
- [x] Validate `data_through` against the probe before committing.
- [x] Dispatch the running updater after a monthly reference cache is published.

### Task 3: Backfill safety

**Files:**
- Modify: `scripts/build_era5_temperature_rank_backfill_current.py`

**Interfaces:**
- Consumes: `probe_latest_temperature_day()` and `validate_backfill_end_day(...)`.
- Produces: no current-stack artifact unless the workflow plan matches fresh ERA5-Land temperature availability.

- [x] Probe temperature availability immediately before building the current stack.
- [x] Reject incomplete past months and stale current-month end days.
- [x] Keep the existing stack generation unchanged after the guard succeeds.

### Task 4: Verification

**Files:**
- Verify all files above.

- [ ] Run unit tests.
- [ ] Compile modified Python files.
- [ ] Parse both modified workflow YAML files.
- [ ] Commit atomically to `main`.
- [ ] Verify the reference workflow starts and then verify the running updater uses the new cache/probe path.
