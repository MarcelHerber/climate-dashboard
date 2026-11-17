# Satellite full-disk implementation plan

**Goal:** Add maximum northern hemisphere coverage, full-disc HD/4K, and correctly projected borders, pressure contours, H/T and temperature-advection markers while retaining existing geographic views and defaults.

**Architecture:** The existing disk request remains unchanged; a northern half-disc uses the same projection and metre bounds. A shared projection helper transforms WGS84 locations and clips hidden portions at the satellite limb. Existing regional ECMWF chunks remain unchanged; a separate wide-disc chunk per hour is produced from the same true IFS source grids. The new overlays use that chunk only when UTC provenance matches; no stale substitute. Full-disc HD/4K uses the existing tile renderer in the very same projected coordinate system.

**Tech stack:** JavaScript, SVG/Canvas/PDF, Python NumPy/SciPy/contourpy, ECMWF Open Data, EUMETSAT WMS and Natural Earth.

**Constraints:** Keep the existing 5 geographic regions, their data and defaults, 2-hPa availability and paused fronts. New disk/north use 5-hPa (10-hPa optional). No extrapolation, no projection mismatch, no invalid markers on the far side. Use separate wide data and borders, fetched only for new views. Preserve PNG/PDF/GIF export paths and honest unsupported-status messages. No unrelated changes.

## Tasks

- [ ] Implement `SatelliteProjection` shared full-disk regions, point/line projection, limb clipping and global Natural Earth border overlay, with independent reference-coordinate tests.
- [ ] Produce separate wide 10-minute IFS contour/center/advection chunks (`disk_hours` index entries and `hXX_disk.json`) while keeping old regional datasets byte-contract compatible; test both output variants and update CI publication validation.
- [ ] Render/project full-disc pressure, center, and WLA/KLA geometry on screen and in vector/raster exports using the shared projection and new chunks; test UTC matching, no invalid fallback, edge clipping.
- [ ] Add north region and disk/north HD/4K tile WMS requests; retain existing region options and film behaviour. Verify data/asset inclusion in Pages build.
- [ ] Run all satellite tests and live WMS checks; review branch, publish only validated changes, confirm public page and new data.

## Review focus

- Limb crossings must split lines; no wraparound chords across the planet.
- Northern half and full disc must agree at equal projected coordinates (same CRS).
- Old cached index lacking `disk_hours` cannot produce misleading partial disk overlays.
- HD tiles preserve exact WMS extent/CRS and selected observation timestamp; no pixel upscaling mislabeled as 4K.
- Existing 2-hPa data, regional arrows, export and timestamp navigation remain functional.
