# Regional SST yearly curves implementation plan

**Goal:** Extend the existing SST yearly plot to global and regional means with daily NOAA OISST history from 1982.

**Architecture:** Reuse the four validated Earth Indicators CSV series (world, North Atlantic, North Pacific, subpolar Atlantic); compute the six actual map boxes from native OISST and publish an independent resumable data snapshot. Keep Niño behavior intact. Use one regional selector, synchronized with map changes when the map box is supported.

- [ ] Test CSV parsing with cold ocean values, blank cells, full-year bins, region mapping, and existing Niño chart. Add regional choices and source/coverage captions.
- [ ] Test area-weighted native-grid means with land NaN, Greenwich wrapping and latitude weighting; build one annual archive per run batch and compact CSVs. Use OISST SST values as distributed, including sea-ice proxy, not a variable daily ice mask. Exact map boxes are not ocean-basin masks.
- [ ] Test resumability and full historical year completeness. Add daily scheduled/dispatch workflow, persist completed annual files and refresh current year; separately validate real source CSVs and NOAA annual file in CI.
- [ ] Review, run local tests and CI, publish changes through a feature branch. Regional data become available after their initial archive finishes.
