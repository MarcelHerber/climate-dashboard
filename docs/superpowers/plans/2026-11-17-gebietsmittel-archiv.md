# Gebietsmittel Archiv Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved climate archive to the existing Gebietsmittel dashboard.
**Architecture:** Reuse loaded monthly data, a pure calculation and palette module, and a lazy browser UI. Deep link into the existing regional-map comparison instead of duplicating it.
**Tech Stack:** Vanilla JS, HTML, CSS, Node test runner, existing html2canvas/jsPDF.
**Spec:** `docs/superpowers/specs/2026-11-17-gebietsmittel-archiv-design.md`

## Global Constraints
- Use existing DWD observations only, no estimates; preserve existing Gebietsmittel behavior.
- Same fixed approved palettes for all years and areas; require 29 reference years, missing is not zero.
- Publish assets through the existing Pages builder and expose desktop/mobile navigation.

## Review Focus
- Early years with missing sunshine, unfinished months and incomplete seasons: remain missing.
- Winter spanning prior December and leap-year weighting, nonpositive reference denominators.
- Percentage vs. percentage-point deviations, clipping colors without clipping values.
- Switch parameters/area/reference/year, select a historical cell and retain map comparison settings.
- Narrow mobile viewport, keyboard access and dark-theme UI; downloads identify region/reference.

### Task 1: Data model and fixed palettes
- [ ] Write `tests/test_gebietsmittel_archive.cjs` with real German June 2025 values and null, winter, palette and rank cases; run `node --test tests/test_gebietsmittel_archive.cjs`, expect missing module.
- [ ] Implement `gebietsmittel_archiv.js`: `buildIndex`, `valueFor`, `referenceMean`, `anomaly`, `colorFor`, `rankFor`, `csvFor`.
- [ ] Run tests; expect all pass.

### Task 2: Integrated archive UI
- [ ] Test archive interaction against real data using browser viewport if available; before implementation archive tab absent.
- [ ] Add HTML tab, entry in desktop and mobile menus, load hooks, CSS and JS in Pages build. Display twelve cards plus season/year summaries, full historical table, detail and existing maps bridge, PNG/PDF/CSV.
- [ ] Run new tests, existing monthly/navigation checks and browser check; review diff.
- [ ] Commit only intended archive files, publish safely and verify deployment status.
