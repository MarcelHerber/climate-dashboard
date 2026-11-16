# HYRAS Temperature Maps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the temperature anomaly map the large first element for Tmean, Tmax and Tmin and enable true 1-km cell inspection for both climate references.
**Architecture:** Reuse the existing high-resolution PNG maps as immediate/fallback views, publish lossless-to-0.01-K north-up numeric anomaly planes from the same source arrays for each reference, and attach a shared interactive canvas to the existing temperature panels. Preserve charts, daily animation and downloads.
**Tech Stack:** Existing HTML/JavaScript, Canvas, browser DecompressionStream, Python/NumPy/xarray, GitHub Actions.
**Spec:** docs/superpowers/specs/2026-11-16-hyras-temperature-maps-design.md

## Global Constraints
- HYRAS-DE native 1-km spatial resolution; numeric values in K, signed int16 little-endian scale 100, missing -32768.
- 1991–2020 and 1961–1990 exactly match the selected reference and calendar interval; no silent substitution.
- No changes to precipitation logic; keep charts, records, animation, PNG/PDF.
- Keep map accessible at mobile widths and retain matching PNG fallback while numeric publication catches up.

## Review Focus
- Rapid parameter/reference/period changes: stale fetch cannot replace the selected view.
- Missing reference or incomplete raster: never label an older or wrong-reference layer as current.
- Outside Germany and raster borders: no out-of-bounds reads; no value shown for nodata.
- Touch and desktop hover: same cell mapping without resizing distortion.
- Data updates: old map/raster manifests cannot claim fresh dates or reference availability.

### Task 1: Publish true temperature raster planes
**Files:** scripts/build_hyras_tmax_maps.py, scripts/build_hyras_tmin_maps.py, scripts/build_hyras_temperature_live_reference.py, scripts/build_hyras_reference_1961_1990.py; tests/test_hyras_temperature_raster.py
**Interfaces:** Reuse temp.qwrite(path, array); map_downloads.json entries expose `raster_by_reference` mapping reference to path relative to parameter root, `raster_grid` width/height, dates and data through. Tmean may alternatively read its existing tmean/index.json.
- [ ] Write tests checking quantization including NaN and negative values, north-up orientation, 2 bytes/cell, manifest exact reference association.
- [ ] Run pytest -q tests/test_hyras_temperature_raster.py; expect failing missing raster manifest behavior.
- [ ] Write native planes when the existing completed-period Tmax/Tmin anomaly is rendered (same normalized array).
- [ ] Write native planes when live period anomaly is rendered, and in the 1961–1990 build for all three parameters; preserve existing metadata and distinguish references.
- [ ] Run tests and check fixture dimensions, masks and range; commit.

### Task 2: Map-first frontend and actual cell query
**Files:** index.html, new hyras_temperature_interactive.js (if separate script, include in scripts/build_pages_site.sh), tests/test_hyras_temperature_map.py 
**Interfaces:** Uses existing hyrasTmean/Tmax/TminRenderCurveChart, hyrasReferencePeriod(), HYRAS_DATA_BASE, map manifest paths, and period start/end.
- [ ] Write regression tests: for each temperature parameter, map precedes chart; switch references and verify exact PNG; preserve chart and daily animation nodes; missing reference does not use default.
- [ ] Run tests; expect current chart-first layout to fail.
- [ ] Move the anomaly preview above the region header/chart in all three renderers, make full-width with matching responsive CSS, place current-month option first when no selection can be retained.
- [ ] Render native planes into canvas with nearest-neighbor sampling, existing HYRAS anomaly palette and boundary overlay; show selected dates/reference and legend. Fetch only current selection, validate decompressed size and nodata; each pointer/touch maps to the cell using canvas bounding rectangle.
- [ ] Use a selection generation/token and check that target element remains connected after async fetch; preserve PNG fallback when unavailable. Keep matching download links and existing chart event handlers.
- [ ] Test desktop and 390px mobile including touch, rapid switching and precipitation return; commit.

### Task 3: Workflow and publication verification
**Files:** .github/workflows/update-hyras.yml, .github/workflows/rebuild-hyras-temperature-download-maps.yml, .github/workflows/build-hyras-temperature-live-reference.yml, .github/workflows/add-hyras-reference-1961-1990.yml, .github/workflows/test-hyras-browser.yml as needed.
- [ ] Check existing job ordering and publish paths; include raster directories and manifests in commit paths of restricted workflows. Add helper paths to triggers/cache dependencies as needed.
- [ ] Run unit tests and browser tests. Verify all three current-month and completed-month map entries against both reference manifests, matching dimensions/date range and image availability.
- [ ] Trigger or observe relevant data workflows, verify their conclusion and published numeric artifacts; confirm Pages deployment and mobile/desktop with real data.
- [ ] Do not call publication complete until deployment actually succeeds; report any pending backfill accurately.
