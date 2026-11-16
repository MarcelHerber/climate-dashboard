# Monthly precipitation resilience

Goal: retain trustworthy precipitation forecasts when Open-Meteo throttles requests.

Architecture: reuse the existing expensive-hourly-request pacing and retry logic; persist regional daily member values in the precipitation data branch, then recompute cumulative curves with each new HYRAS anchor. Mark retained runs with original initialization and reject expired/gapped forecasts. Legacy summary fallback is only safe with identical observations. Recovery checks actual model coverage and dates, with a 180-minute cooldown.

Constraints: no fabricated dry days, no synthetic extrapolation or re-anchoring of aggregate quantiles, no mixing different months, no concurrent publication. Keep sunshine/temperature unchanged.

- [x] Regression-test and implement precipitation pacing, minute cooldown, bounded retries; avoid recursive batch splitting on 429.
- [x] Test retained member cache, newer observations, stale runs and legacy summary; persist valid earlier runs and mark fallback in UI.
- [x] Test and add precipitation recovery for missing/stale models and missing forecast continuity; preserve cooldown/active-run guard.
- [ ] Run tests, independently review, publish and verify GitHub jobs and live data.
