# Satellite temperature advection implementation plan

**Goal:** Add optional red WLA and blue KLA wind-direction arrows to the satellite map and composite downloads.

**Architecture:** Compute horizontal temperature advection from IFS pressure-level grids and surface pressure, interpolate the source fields to the existing 10-minute timestamps, and attach compact significant-region markers to existing pressure chunks. Share projected arrow layout between SVG, canvas and vector PDF.

**Tech stack:** Python, NumPy/SciPy, ecCodes, ECMWF Open Data, vanilla JavaScript, existing GitHub Actions.

**Constraints:** 850 hPa default; 925 and 700 hPa alternatives; arrows indicate wind direction and magnitude of advection by size; no filled regions; real data, no extrapolation or below-ground samples; default off; same model run and UTC as isobars. Preserve existing H/T and contour logic.

## Tasks

- [ ] Create numeric tests for advection sign, units, terrain exclusion, spacing and interpolation; implement `scripts/satellite_temperature_advection.py` and optional data attachment to the existing 10-minute builder. Test with a real IFS GRIB sample.
- [ ] Create JS tests for map layout, direction, warm/cold labels, strength and export vectors; share a layout helper between interactive SVG, Canvas and PDF; wire export options and a level selector. Fail explicitly when selected advection is unavailable instead of silently exporting stale data.
- [ ] Extend the existing workflow with tests and validated data generation; verify relevant Python and Node suites. Review changes, publish via normal GitHub workflow, and check progress.

## Review focus

- Reversed north/south axis or sign; latitude-dependent longitudinal distance; masked terrain contaminating neighbors; mismatched run or time; missing model leads or an older cached pressure chunk; unreadable labels on narrow exports.
