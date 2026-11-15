# Satellite pressure centers V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement.

**Goal:** Show broad closed Azores high and true fixed native-grid centers.

**Architecture:** Python identifies significant closed cores; common JS selects and places markers, then relocates numeric labels along their actual contour paths. SVG, raster and vector exports consume the shared layout.

**Tech Stack:** NumPy/SciPy/ContourPy, JavaScript, Node test, Python unittest.

**Spec:** `docs/superpowers/specs/2026-11-15-pressure-centers-v3-design.md`

## Global Constraints
- Preserve original contours and true coordinates; identical grid candidates at 2/5 hPa; keep old archives readable.

## Review Focus
- Broad shallow core vs tiny speckle; separate closed cores; overcrowding by tiny Greenland lows; number collision; export parity.

### Task 1 — Grid discovery
- [x] Add broad shallow closed 1025-hPa high regression and narrow speckle regression in `tests/test_satellite_mslp_grid_centers.py`; run red.
- [x] Implement closed-area-aware threshold and area metadata in `scripts/satellite_mslp_grid_centers.py`, version v3; run Python test suite.

### Task 2 — Shared layout
- [x] Add tests in `tests/test_satellite_grid_centers.cjs` for exact anchor, dynamic number and numeric relocation along a real contour; run red.
- [x] Implement fixed H/T and contour-number collision handling in `satellite_isobar_geometry.js`, use in `satellite_isobars.js` and `satellite_map_export.js`; update cache versions and v3 recognition.
- [ ] Run all satellite JS and Python tests, regenerate the actual 10:50 UTC frame and inspect its Atlantic annotations, run browser QA, review and publish via PR.
