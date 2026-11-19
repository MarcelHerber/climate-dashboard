# Stratosphere height anomalies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Daily polar-sector height anomalies from ERA5 and real 15-day ensembles.

**Architecture:** Independent resumable data products; a browser SVG view derives anomalies from daily regional means, draws filled contours and exposes comparison/export controls.

**Tech Stack:** Python, numpy, eccodes, CDS API, ECMWF Open Data, NOMADS, JavaScript SVG/D3, jsPDF/svg2pdf.

**Spec:** docs/superpowers/specs/2026-11-19-stratosphere-height-anomalies.md

## Global Constraints
- No synthetic values in production; all times 00 UTC, 1991–2020 daily reference, area weighting, dam, 10–1000 hPa. Preserve previous stratosphere features.

## Review Focus
- Greenwich and dateline wrapping, geopotential conversion, strict completeness, no forecast extrapolation over missing records, 15-day native-level forecast dates, responsive vector output.

## Tasks
- [ ] Test `sector_means`, `reference_means`, `validate_forecast`, then implement in `scripts/strato_height_data.py`; run Python tests, verify real single-step GEFS and ECMWF data in CI.
- [ ] Test `makeSeries`, `gridSamples` for anomaly conversion, missing dates and log-pressure interpolation, then build `stratosphere_height.js` and CSS using independent data branch URLs. Test rendering and export in browser where feasible.
- [ ] Add independent scheduled workflows for ERA5 and two forecast models with resumable data and preservation of prior good runs. Integrate files into Pages staging and run CI before publishing.
