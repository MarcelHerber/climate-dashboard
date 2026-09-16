# Meere / SST Europa – Stufe 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `Meere / SST` main tab that publishes daily MUR sea-surface temperature and MUR-minus-OISST-1991–2020 anomaly maps for five fixed regions, with archive navigation from 2020-01-01 onward, PNG/PDF export, and safe daily/backfill automation.

**Architecture:** Keep the scientific pipeline in a focused `scripts/sst/` Python package. Fetch spatial MUR subsets from NASA Harmony, cache one NOAA 1991–2020 daily-normal NetCDF, regrid that reference to each MUR subset, render fixed-geometry WebP maps, validate all ten outputs for a date, then update an archive manifest atomically. Store historical WebP files on a separate `sst-archive` branch while the main branch contains only code/frontend; the browser reads the manifest and never constructs archive paths itself.

**Tech Stack:** Python 3.13, unittest, requests, numpy, xarray, netCDF4, scipy, matplotlib, cartopy, Pillow/WebP, GitHub Actions, vanilla HTML/CSS/JavaScript, html2canvas, jsPDF.

**Spec:** `docs/superpowers/specs/2026-09-16-sst-europe-design.md`

## Global Constraints

- MUR source: `MUR-JPL-L4-GLOB-v4.1`, NASA collection concept ID `C1996881146-POCLOUD`, 0.01° native grid.
- NOAA reference: 1991–2020 daily SST normals based on OISST, 0.25° grid.
- Archive begins `2020-01-01`.
- Regions are exactly: `europe`, `mediterranean`, `north_baltic`, `north_atlantic`, `nordic_seas`.
- Absolute SST scale is fixed at `-2..34 °C` in Stufe 1.
- Anomaly scale is fixed at `-6..6 °C` in Stufe 1.
- Sea-ice masking threshold is `sea_ice_fraction >= 0.15`.
- No city labels, extrema labels, arrows, or station markers in Stufe 1.
- A date is publishable only when all `5 regions × 2 views = 10` WebP maps validate.
- The frontend must obtain URLs from `manifest.json`; it must not infer archive file paths.
- Historical binary output must not be committed to `main`.
- Animation generation is out of scope, but every region must render with fixed pixel geometry so later MP4 generation can consume the archive directly.

---

## File map

Create these focused modules:

```text
scripts/sst/__init__.py          package marker
scripts/sst/config.py            immutable regions/scales/source constants
scripts/sst/sources.py           CMR availability, Harmony MUR download, NOAA-normal discovery/cache
scripts/sst/climatology.py       daily-normal selection and interpolation
scripts/sst/processing.py        Kelvin→°C, ice/land masking, anomaly fields, scientific validation
scripts/sst/render.py            fixed-geometry map rendering and WebP encoding
scripts/sst/manifest.py          schema-v1 manifest read/update/write and archive paths
scripts/sst/build_daily.py       atomic one-date orchestrator
scripts/sst/backfill.py          resumable date/month batches + storage report
sst_europe.css                   standalone tab styling
sst_europe.js                    manifest-driven tab/navigation/export logic
scripts/patch_sst_frontend.py    idempotent index.html integration
tests/test_sst_*.py              Python scientific/archive tests
tests/test_patch_sst_frontend.py index integration test
requirements-sst.txt             workflow-only scientific dependencies
.github/workflows/update-sst-europe.yml
.github/workflows/backfill-sst-europe.yml
SST_SETUP.md                     operational notes, secret and backfill procedure
```

Do not fold this feature into the already very large inline JavaScript/CSS body in `index.html`; only patch in the tab markup plus two external asset references.

---

### Task 1: Lock down SST configuration and public contracts

**Files:**
- Create: `scripts/sst/__init__.py`
- Create: `scripts/sst/config.py`
- Create: `requirements-sst.txt`
- Create: `tests/test_sst_config.py`

**Interfaces:**
- Produces: `Region`, `REGIONS`, `ABSOLUTE_RANGE`, `ANOMALY_RANGE`, `SEA_ICE_THRESHOLD`, `ARCHIVE_START`, `MUR_COLLECTION_ID`, `MUR_HARMONY_BASE`, `NOAA_NORMALS_BASE`.

- [ ] **Step 1: Write the failing configuration test**

```python
from datetime import date
from scripts.sst.config import (
    ABSOLUTE_RANGE, ANOMALY_RANGE, ARCHIVE_START, REGIONS,
    SEA_ICE_THRESHOLD, MUR_COLLECTION_ID,
)


def test_sst_stage1_contract():
    assert list(REGIONS) == [
        "europe", "mediterranean", "north_baltic",
        "north_atlantic", "nordic_seas",
    ]
    assert REGIONS["europe"].bounds == (-30.0, 30.0, 45.0, 72.0)
    assert REGIONS["mediterranean"].bounds == (-6.0, 29.0, 38.0, 47.0)
    assert REGIONS["north_baltic"].bounds == (-12.0, 48.0, 32.0, 66.0)
    assert REGIONS["north_atlantic"].bounds == (-60.0, 25.0, 20.0, 70.0)
    assert REGIONS["nordic_seas"].bounds == (-45.0, 55.0, 50.0, 82.0)
    assert ABSOLUTE_RANGE == (-2.0, 34.0)
    assert ANOMALY_RANGE == (-6.0, 6.0)
    assert SEA_ICE_THRESHOLD == 0.15
    assert ARCHIVE_START == date(2020, 1, 1)
    assert MUR_COLLECTION_ID == "C1996881146-POCLOUD"
```

- [ ] **Step 2: Run it and confirm the package is missing**

Run: `python -m unittest tests.test_sst_config -v`
Expected: import failure for `scripts.sst.config`.

- [ ] **Step 3: Implement the immutable constants**

```python
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class Region:
    id: str
    label: str
    west: float
    south: float
    east: float
    north: float
    width_px: int = 1600
    height_px: int = 1050

    @property
    def bounds(self):
        return (self.west, self.south, self.east, self.north)

REGIONS = {
    "europe": Region("europe", "Europa gesamt", -30, 30, 45, 72),
    "mediterranean": Region("mediterranean", "Mittelmeer", -6, 29, 38, 47),
    "north_baltic": Region("north_baltic", "Nordsee + Ostsee", -12, 48, 32, 66),
    "north_atlantic": Region("north_atlantic", "Nordatlantik", -60, 25, 20, 70),
    "nordic_seas": Region("nordic_seas", "Nordmeer / Skandinavien", -45, 55, 50, 82),
}
ABSOLUTE_RANGE = (-2.0, 34.0)
ANOMALY_RANGE = (-6.0, 6.0)
SEA_ICE_THRESHOLD = 0.15
ARCHIVE_START = date(2020, 1, 1)
MUR_COLLECTION_ID = "C1996881146-POCLOUD"
MUR_HARMONY_BASE = f"https://harmony.earthdata.nasa.gov/{MUR_COLLECTION_ID}/ogc-api-coverages/1.0.0/collections/all/coverage/rangeset"
NOAA_NORMALS_BASE = "https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/2023.sst.normals/"
```

Use this workflow-only dependency file:

```text
requests>=2.32,<3
numpy>=2.1,<3
xarray>=2025.1
netCDF4>=1.7
scipy>=1.14
matplotlib>=3.10
cartopy>=0.24
Pillow>=11
```

- [ ] **Step 4: Run the test**

Run: `python -m unittest tests.test_sst_config -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/sst/__init__.py scripts/sst/config.py requirements-sst.txt tests/test_sst_config.py
git commit -m "feat: define SST Europe configuration"
```

---

### Task 2: Implement deterministic source access without full-global MUR downloads

**Files:**
- Create: `scripts/sst/sources.py`
- Create: `tests/test_sst_sources.py`

**Interfaces:**
- Consumes: `Region`, `MUR_COLLECTION_ID`, `MUR_HARMONY_BASE`, `NOAA_NORMALS_BASE`.
- Produces:
  - `mur_date_available(day: date, session=requests) -> bool`
  - `latest_available_mur_date(today: date, lookback_days: int = 10, session=requests) -> date`
  - `download_mur_subset(day: date, region: Region, destination: Path, token: str, session=requests) -> Path`
  - `discover_oisst_daily_normals_url(session=requests) -> str`
  - `ensure_oisst_daily_normals(cache_dir: Path, session=requests) -> Path`

- [ ] **Step 1: Write tests for CMR probing, Harmony URL generation, and NOAA index discovery**

Use mocked HTTP responses; never call NASA/NOAA in unit tests.

```python
class FakeResponse:
    def __init__(self, *, json_data=None, text="", content=b"nc", status_code=200):
        self._json = json_data
        self.text = text
        self.content = content
        self.status_code = status_code
        self.ok = status_code < 400
    def json(self): return self._json
    def raise_for_status(self):
        if not self.ok: raise RuntimeError(self.status_code)


def test_cmr_probe_accepts_date_with_granule():
    session = mock.Mock()
    session.get.return_value = FakeResponse(json_data={"feed": {"entry": [{"id": "g1"}]}})
    assert mur_date_available(date(2026, 9, 14), session=session)
    assert "C1996881146-POCLOUD" in session.get.call_args.kwargs["params"]["collection_concept_id"]


def test_noaa_index_selects_1991_2020_daily_mean_netcdf():
    session = mock.Mock()
    session.get.return_value = FakeResponse(text='''
      <a href="sst.day.mean.1991-2020.nc">daily</a>
      <a href="sst.mon.mean.1991-2020.nc">monthly</a>
    ''')
    assert discover_oisst_daily_normals_url(session).endswith("sst.day.mean.1991-2020.nc")
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_sst_sources -v`
Expected: module/functions missing.

- [ ] **Step 3: Implement CMR availability probing**

Use public CMR metadata, not a data download:

```python
CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"

def mur_date_available(day, session=requests):
    start = f"{day.isoformat()}T00:00:00Z"
    stop = f"{day.isoformat()}T23:59:59Z"
    r = session.get(CMR_GRANULES, params={
        "collection_concept_id": MUR_COLLECTION_ID,
        "temporal": f"{start},{stop}",
        "page_size": 1,
    }, timeout=30)
    r.raise_for_status()
    return bool(r.json().get("feed", {}).get("entry"))
```

`latest_available_mur_date()` checks `today`, then walks backward for at most 10 days and raises if none is found.

- [ ] **Step 4: Implement Harmony spatial subset download**

Build a request using the official collection-specific Harmony endpoint and a full-day time subset:

```python
params = [
    ("subset", f"lat({region.south}:{region.north})"),
    ("subset", f"lon({region.west}:{region.east})"),
    ("subset", f"time({day.isoformat()}T00:00:00Z:{day.isoformat()}T23:59:59Z)"),
    ("format", "application/x-netcdf4"),
]
headers = {"Authorization": f"Bearer {token}"}
```

Stream the response to `destination.with_suffix('.part')`, fsync/close, then rename to the final `.nc`. Reject HTML or zero-byte responses before rename.

- [ ] **Step 5: Implement NOAA-normal discovery/cache**

Fetch `NOAA_NORMALS_BASE`, parse all `.nc` hrefs with `html.parser.HTMLParser`, then select exactly one filename satisfying all of:

```python
name.endswith(".nc")
"day" in name.lower()
"1991" in name
"2020" in name
("mean" in name.lower() or "normal" in name.lower())
```

If zero or multiple candidates remain, raise with the candidate list. Cache the selected file at `.sst_cache/oisst/oisst_daily_normals_1991_2020.nc`.

- [ ] **Step 6: Run tests**

Run: `python -m unittest tests.test_sst_sources -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/sst/sources.py tests/test_sst_sources.py
git commit -m "feat: add MUR and NOAA SST source adapters"
```

---

### Task 3: Implement daily normal selection, leap-day behavior, regridding, and masks

**Files:**
- Create: `scripts/sst/climatology.py`
- Create: `scripts/sst/processing.py`
- Create: `tests/test_sst_climatology.py`
- Create: `tests/test_sst_processing.py`

**Interfaces:**
- Produces:
  - `select_daily_normal(normals: xr.Dataset, day: date) -> tuple[xr.DataArray, str]`
  - `regrid_normal(normal: xr.DataArray, target_lat: xr.DataArray, target_lon: xr.DataArray) -> xr.DataArray`
  - `ProcessedFields` dataclass with `lon`, `lat`, `absolute_c`, `anomaly_c`, `valid_mask`, `reference_method`.
  - `process_mur_region(mur: xr.Dataset, normals: xr.Dataset, day: date) -> ProcessedFields`
  - `validate_scientific_fields(fields: ProcessedFields) -> None`

- [ ] **Step 1: Write synthetic xarray tests**

Cover all of these cases:

```python
def test_kelvin_to_celsius_and_anomaly(): ...
def test_ice_at_015_is_masked(): ...
def test_non_leap_day_maps_to_correct_daily_normal(): ...
def test_feb29_uses_explicit_366th_climatology_when_present(): ...
def test_feb29_averages_feb28_and_mar1_for_365_day_reference(): ...
def test_land_nan_remains_nan_after_regridding_and_final_mask(): ...
def test_implausible_absolute_sst_is_rejected(): ...
```

Use tiny `2×3` / `3×4` arrays; no real files.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_sst_climatology tests.test_sst_processing -v`
Expected: imports/functions missing.

- [ ] **Step 3: Implement robust SST-variable discovery**

For the NOAA dataset, choose a data variable by this deterministic order:

1. exact names `sst_mean`, `sst`, `sea_surface_temperature`;
2. otherwise variables containing `sst` whose name does not contain `std`, `count`, `min`, `max`, `extreme` and which have latitude + longitude dimensions.

Normalize longitude coordinates to `[-180, 180)` and sort them before interpolation.

- [ ] **Step 4: Implement calendar selection**

For 366-entry references use calendar day-of-year directly. For 365-entry references, map leap-year dates after Feb 28 back by one index; for Feb 29 return `(Feb28 + Mar01) / 2` and `reference_method="feb29_interpolated"`. Otherwise return `reference_method="daily_normal"`.

- [ ] **Step 5: Implement field processing**

Use `analysed_sst` as the authoritative data-valid mask because land cells are absent/NaN in MUR. Convert Kelvin only when metadata units begin with `K`; otherwise accept already-Celsius values. Build:

```python
absolute_c = mur_sst_c.where(np.isfinite(mur_sst_c))
ice_ok = (sea_ice_fraction < SEA_ICE_THRESHOLD) | sea_ice_fraction.isnull()
valid_mask = np.isfinite(absolute_c) & ice_ok
normal_hi = regrid_normal(normal, absolute_c.lat, absolute_c.lon)
anomaly_c = (absolute_c - normal_hi).where(valid_mask)
absolute_c = absolute_c.where(valid_mask)
```

- [ ] **Step 6: Implement scientific validation**

Reject a region if:

```text
valid ocean pixels == 0
absolute finite minimum < -3 °C
absolute finite maximum > 40 °C
no finite anomaly pixels
anomaly absolute maximum > 20 °C
```

The display scales still clip to `-2..34` and `-6..6`; these wider validation bounds are only corruption guards.

- [ ] **Step 7: Run tests and commit**

Run: `python -m unittest tests.test_sst_climatology tests.test_sst_processing -v`
Expected: PASS.

```bash
git add scripts/sst/climatology.py scripts/sst/processing.py tests/test_sst_climatology.py tests/test_sst_processing.py
git commit -m "feat: process SST normals and anomalies"
```

---

### Task 4: Render clean, fixed-geometry WebP maps and validate encoded output

**Files:**
- Create: `scripts/sst/render.py`
- Create: `tests/test_sst_render.py`

**Interfaces:**
- Consumes: `ProcessedFields`, `Region`, fixed scales.
- Produces:
  - `render_map(fields, region, day, view, output_path) -> Path`
  - `validate_rendered_map(path, region) -> None`

- [ ] **Step 1: Write rendering tests**

Generate a tiny synthetic field and assert:

```python
with Image.open(path) as image:
    assert image.format == "WEBP"
    assert image.size == (1600, 1050)
assert path.stat().st_size > 10_000
```

Also assert that `view="absolute"` and `view="anomaly"` pass fixed `vmin/vmax` values `(-2, 34)` and `(-6, 6)` to the renderer (patch `Axes.pcolormesh` or expose `view_scale(view)`).

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_sst_render -v`
Expected: missing module/functions.

- [ ] **Step 3: Implement the clean map**

Use a Plate Carrée map with:

```python
ax.set_extent(region.bounds, crs=ccrs.PlateCarree())
ax.add_feature(cfeature.LAND, facecolor="#eeeeee", zorder=4)
ax.coastlines(resolution="50m", linewidth=0.55, color="#3e454b", zorder=5)
ax.add_feature(cfeature.BORDERS, linewidth=0.35, edgecolor="#70777d", zorder=5)
```

No city labels. Render SST/anomaly with a rasterized `pcolormesh`, fixed scale, and a horizontal colorbar. Include a stable header/footer inside the image so future animation frames are self-contained:

```text
Meeresoberflächentemperatur · <Region>
YYYY-MM-DD · SST absolut
Quelle: NASA/JPL MUR SST v4.1
```

or

```text
Meeresoberflächentemperatur · <Region>
YYYY-MM-DD · Abweichung zu 1991–2020
Quelle: NASA/JPL MUR SST v4.1 · Referenz: NOAA OISST-Normale 1991–2020
```

Save a temporary PNG from Matplotlib, open with Pillow, convert to RGB, resize/crop only if required to exact `1600×1050`, then encode WebP quality `82`, method `6`.

- [ ] **Step 4: Validate files after encoding**

`validate_rendered_map()` must verify format, exact dimensions, and minimum size `10_000 bytes`.

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest tests.test_sst_render -v`
Expected: PASS.

```bash
git add scripts/sst/render.py tests/test_sst_render.py
git commit -m "feat: render fixed SST archive maps"
```

---

### Task 5: Define the archive manifest and atomic one-day builder

**Files:**
- Create: `scripts/sst/manifest.py`
- Create: `scripts/sst/build_daily.py`
- Create: `tests/test_sst_manifest.py`
- Create: `tests/test_sst_build_daily.py`

**Interfaces:**
- Produces:
  - `empty_manifest() -> dict`
  - `archive_relpath(day, region_id, view) -> str`
  - `register_date(manifest, day, outputs, reference_method) -> dict`
  - `write_manifest_atomic(path, payload) -> None`
  - `build_date(day, archive_root, cache_root, earthdata_token, *, source_adapter=None) -> BuildResult`

- [ ] **Step 1: Write manifest tests**

Required schema:

```json
{
  "schema_version": 1,
  "archive_start": "2020-01-01",
  "data_through": "2026-09-14",
  "generated_at": "...Z",
  "source": {
    "sst": "MUR-JPL-L4-GLOB-v4.1",
    "reference": "NOAA OISST 1991-2020"
  },
  "scales": {"absolute": [-2.0, 34.0], "anomaly": [-6.0, 6.0]},
  "regions": {"europe": {"label": "Europa gesamt", "bounds": [-30, 30, 45, 72]}},
  "available_dates": ["2026-09-14"],
  "dates": {
    "2026-09-14": {
      "reference_method": "daily_normal",
      "regions": {
        "europe": {
          "absolute": "2026/09/europe/absolute/2026-09-14.webp",
          "anomaly": "2026/09/europe/anomaly/2026-09-14.webp"
        }
      }
    }
  }
}
```

Tests must assert sorted unique dates and that a date cannot be registered unless exactly ten view URLs are provided.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_sst_manifest tests.test_sst_build_daily -v`
Expected: missing modules.

- [ ] **Step 3: Implement archive paths and atomic JSON**

Use:

```python
def archive_relpath(day, region_id, view):
    return f"{day:%Y/%m}/{region_id}/{view}/{day.isoformat()}.webp"
```

Write JSON to `manifest.json.tmp`, flush/fsync, then `os.replace()`.

- [ ] **Step 4: Implement staged daily orchestration**

`build_date()` must:

1. return `already_present=True` when the manifest already has that date and all ten files validate;
2. create a temporary staging directory;
3. load/cache NOAA daily normals once;
4. process the five regions sequentially, one MUR NetCDF at a time;
5. render both views per region;
6. validate fields and files;
7. confirm there are exactly ten final WebPs;
8. move the ten files from staging into `archive_root`;
9. only then update `manifest.json`;
10. always remove temporary MUR subset files in `finally`.

Dependency injection for tests is through a small adapter object with methods `fetch_mur(day, region, path)` and `normal_dataset()` so the unit test never accesses the network.

- [ ] **Step 5: Add the failure-atomicity test**

Make the fake adapter throw on the third region and assert:

```python
assert not (archive_root / "manifest.json").exists()
assert list(archive_root.rglob("*.webp")) == []
```

- [ ] **Step 6: Run tests and commit**

Run: `python -m unittest tests.test_sst_manifest tests.test_sst_build_daily -v`
Expected: PASS.

```bash
git add scripts/sst/manifest.py scripts/sst/build_daily.py tests/test_sst_manifest.py tests/test_sst_build_daily.py
git commit -m "feat: build SST dates atomically"
```

---

### Task 6: Add resumable backfill and the mandatory seven-day storage prototype

**Files:**
- Create: `scripts/sst/backfill.py`
- Create: `tests/test_sst_backfill.py`

**Interfaces:**
- Produces:
  - `iter_dates(start, end)`
  - `backfill(start, end, archive_root, cache_root, token) -> dict`
  - `storage_report(archive_root, dates) -> dict`
- CLI:

```text
python -m scripts.sst.backfill --start 2026-09-01 --end 2026-09-07 --archive-root /tmp/sst-prototype
```

- [ ] **Step 1: Write resume/storage-report tests**

Test that an already complete date is skipped, a partial date is rebuilt, and the report contains:

```json
{
  "date_count": 7,
  "file_count": 70,
  "total_bytes": 123,
  "mean_bytes_per_day": 17.57,
  "projected_archive_gib_from_2020": 0.0
}
```

Use exact computed values in the fixture rather than hard-coding the example numbers above.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_sst_backfill -v`
Expected: module missing.

- [ ] **Step 3: Implement sequential, resume-safe backfill**

Every date delegates to `build_date()`. Do not parallelize MUR regions/dates in Stufe 1; predictable memory is more important than maximum throughput.

At the end write `storage_report.json` beside the manifest. Projection is:

```python
projected_days = (date.today() - ARCHIVE_START).days + 1
projected_bytes = mean_bytes_per_day * projected_days
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m unittest tests.test_sst_backfill -v`
Expected: PASS.

```bash
git add scripts/sst/backfill.py tests/test_sst_backfill.py
git commit -m "feat: add resumable SST backfill"
```

- [ ] **Step 5: Before the historical backfill, run the live seven-day prototype**

After the workflow/secret exists, run exactly:

```bash
python -m scripts.sst.backfill \
  --start 2026-09-01 \
  --end 2026-09-07 \
  --archive-root /tmp/sst-prototype \
  --cache-root .sst_cache
```

Gate for proceeding: 70 valid WebPs, one valid manifest, and a recorded `storage_report.json`. If file volume is unexpectedly large, adjust WebP dimensions/quality before any 2020 backfill; do not alter the manifest schema.

---

### Task 7: Publish daily and monthly-batch output to `sst-archive`

**Files:**
- Create: `.github/workflows/update-sst-europe.yml`
- Create: `.github/workflows/backfill-sst-europe.yml`
- Create: `SST_SETUP.md`

**Interfaces:**
- Consumes GitHub Actions secret: `EARTHDATA_TOKEN`.
- Produces branch: `sst-archive` with `manifest.json`, `storage_report.json`, and dated WebP tree.
- Daily workflow concurrency group: `sst-archive-writer`.
- Backfill workflow uses the same concurrency group so two jobs never mutate the archive simultaneously.

- [ ] **Step 1: Write the daily workflow**

Core setup must match the repository's current Python-3.13 workflow pattern:

```yaml
permissions:
  contents: write
concurrency:
  group: sst-archive-writer
  cancel-in-progress: false

steps:
  - uses: actions/checkout@v6
    with:
      ref: main
      fetch-depth: 0
  - uses: actions/setup-python@v6
    with:
      python-version: "3.13"
      cache: "pip"
  - run: python -m pip install -r requirements-sst.txt
```

Schedule once per day and allow `workflow_dispatch`. Restore `.sst_cache` through `actions/cache@v4`.

Fetch the archive branch when it exists:

```bash
rm -rf /tmp/sst-archive
if git ls-remote --exit-code --heads origin sst-archive >/dev/null 2>&1; then
  git fetch origin sst-archive --depth=1
  git worktree add -B sst-archive /tmp/sst-archive origin/sst-archive
else
  mkdir -p /tmp/sst-archive
  git -C /tmp/sst-archive init
  git -C /tmp/sst-archive remote add origin "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY.git"
fi
```

Run `latest_available_mur_date()` then `build_date()` with `EARTHDATA_TOKEN`.

- [ ] **Step 2: Keep archive history as a snapshot, not a growing binary history**

After a successful build:

```bash
cd /tmp/sst-archive
git config user.name "climate-dashboard-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then exit 0; fi
if git rev-parse HEAD >/dev/null 2>&1; then
  git commit --amend --no-edit || git commit -m "SST Archiv aktualisiert"
else
  git commit -m "SST Archiv initialisiert"
fi
git push --force-with-lease origin HEAD:sst-archive
```

If the initial empty-repo path makes amend awkward, create one normal first commit; subsequent jobs amend that single snapshot commit. Because both workflows share one concurrency group, `--force-with-lease` is safe and will still reject an unexpected external race.

- [ ] **Step 3: Write the backfill workflow as one calendar-month batch per dispatch**

Inputs:

```yaml
month:
  description: "Monat YYYY-MM, z. B. 2020-01"
  required: true
  type: string
```

Validate with `^[0-9]{4}-[0-9]{2}$`, derive first/last day in Python, reject months before `2020-01` or after the newest MUR month, then run the same archive restore → `backfill()` → snapshot publish sequence.

Do not create a giant 2020–today single job.

- [ ] **Step 4: Document operations**

`SST_SETUP.md` must state:

```text
Required secret: EARTHDATA_TOKEN
Daily archive branch: sst-archive
Daily update: .github/workflows/update-sst-europe.yml
Historical batch: .github/workflows/backfill-sst-europe.yml, one YYYY-MM per dispatch
Mandatory first live test: 2026-09-01 through 2026-09-07
Do not start 2020 backfill until storage_report.json has been reviewed.
```

Also include NASA collection ID `C1996881146-POCLOUD` and NOAA normals source directory.

- [ ] **Step 5: Validate YAML locally and commit**

Run:

```bash
python - <<'PY'
import yaml
for p in [
    '.github/workflows/update-sst-europe.yml',
    '.github/workflows/backfill-sst-europe.yml',
]:
    yaml.safe_load(open(p, encoding='utf-8'))
    print('OK', p)
PY
```

Then:

```bash
git add .github/workflows/update-sst-europe.yml .github/workflows/backfill-sst-europe.yml SST_SETUP.md
git commit -m "feat: automate SST archive updates"
```

---

### Task 8: Add the standalone `Meere / SST` frontend tab and 30-day navigation

**Files:**
- Create: `sst_europe.css`
- Create: `sst_europe.js`
- Create: `scripts/patch_sst_frontend.py`
- Create: `tests/test_patch_sst_frontend.py`
- Modify: `index.html` by running the tested patcher.

**Interfaces:**
- Archive base: `https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/sst-archive`
- Frontend entry point: `window.mountSstEurope()`.
- Manifest loader: `loadSstManifest()`.
- State: `{region, view, date}`.

- [ ] **Step 1: Write the patcher test first**

A minimal index fixture must gain exactly once:

```html
<link rel="stylesheet" href="sst_europe.css">
<button class="tab-button" data-tab="sst-europe">Meere / SST</button>
<div id="sst-europe" class="tab-content">...</div>
<script src="sst_europe.js"></script>
```

Run the patch twice and assert byte-for-byte idempotency on the second run. If expected navigation/body markers are absent, raise `RuntimeError` instead of silently appending at EOF.

- [ ] **Step 2: Implement tab markup**

The panel must contain these IDs:

```text
sstRegion
sstView
sstDate
sstPrevDay
sstLatestDay
sstNextDay
sstTimeline
sstMapImage
sstStatus
sstDataThrough
sstPngDownload
sstPdfDownload
```

Region options are populated from the manifest; do not duplicate bounds in JavaScript.

- [ ] **Step 3: Implement manifest-driven loading**

```javascript
const SST_ARCHIVE_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/sst-archive";
let sstManifestPromise=null;
async function loadSstManifest(){
  if(!sstManifestPromise){
    sstManifestPromise=fetch(`${SST_ARCHIVE_BASE}/manifest.json?t=${Date.now()}`,{cache:"no-store"})
      .then(r=>{if(!r.ok)throw new Error(`SST manifest HTTP ${r.status}`);return r.json();})
      .catch(e=>{sstManifestPromise=null;throw e;});
  }
  return sstManifestPromise;
}
```

For a selected date, use exactly:

```javascript
const rel=manifest.dates?.[date]?.regions?.[region]?.[view];
```

If missing, display `Für dieses Datum liegt keine SST-Karte vor.` and clear the image. Never synthesize a path.

Set `image.crossOrigin="anonymous"` before assigning `src` so canvas export remains untainted with raw.githubusercontent.com's CORS response.

- [ ] **Step 4: Implement the 30-day strip**

Build 30 calendar buttons ending at the selected date; each checks `manifest.dates[iso]`. Available dates are clickable; unavailable dates render disabled. No image preloading is allowed.

`← Vortag` and `Folgetag →` move one calendar day, not one available-date index. `Heute / neuester verfügbarer Tag` always selects `manifest.data_through`.

- [ ] **Step 5: Implement clean responsive styling**

Use existing page CSS variables (`--card`, `--border`, `--shadow`, `--muted`) and keep the map image centered with `max-width:100%`. On narrow displays, controls stack and the timeline scrolls horizontally.

- [ ] **Step 6: Run patcher tests, patch index.html, and commit**

```bash
python -m unittest tests.test_patch_sst_frontend -v
python scripts/patch_sst_frontend.py --file index.html
python -m unittest tests.test_patch_sst_frontend -v
git add sst_europe.css sst_europe.js scripts/patch_sst_frontend.py tests/test_patch_sst_frontend.py index.html
git commit -m "feat: add Meere SST dashboard tab"
```

---

### Task 9: Add PNG and PDF export from the displayed archive image

**Files:**
- Modify: `sst_europe.js`
- Modify: `sst_europe.css`
- Create: `tests/test_sst_frontend_static.py`

**Interfaces:**
- Produces:
  - `composeSstExportCanvas()`
  - `downloadSstPng()`
  - `downloadSstPdf()`

- [ ] **Step 1: Add static frontend assertions**

Because the repository does not currently run a JS unit-test runner, use a Python static test to assert the critical export contract in the asset:

```python
text = Path("sst_europe.js").read_text(encoding="utf-8")
assert 'crossOrigin="anonymous"' in text or "crossOrigin='anonymous'" in text
assert "composeSstExportCanvas" in text
assert "toDataURL(\"image/png\")" in text
assert "window.jspdf" in text
assert "SST_" in text
```

Also assert the file contains no hard-coded regional archive path such as `2026/`.

- [ ] **Step 2: Implement one canonical export canvas**

`composeSstExportCanvas()` draws a white background, the fully rendered WebP image, then a small footer containing the selected date, region label, view label, and exact data source text. Since the archive WebP already carries the stable title/colorbar, do not redraw another colorbar.

- [ ] **Step 3: Implement PNG download**

Filename pattern:

```text
SST_<region>_<absolute|anomaly>_<YYYY-MM-DD>.png
```

Use `canvas.toBlob()` where available and a temporary `<a download>`.

- [ ] **Step 4: Implement PDF from the same canvas**

Use the already loaded `window.jspdf.jsPDF`. Determine landscape/portrait from the canvas dimensions and fit the PNG data URL to the page preserving aspect ratio.

- [ ] **Step 5: Run test and commit**

```bash
python -m unittest tests.test_sst_frontend_static -v
git add sst_europe.js sst_europe.css tests/test_sst_frontend_static.py
git commit -m "feat: export SST maps as PNG and PDF"
```

---

### Task 10: End-to-end verification before any 2020 backfill

**Files:**
- Verify all files above; only fix defects found by verification.

- [ ] **Step 1: Run the complete SST unit suite**

```bash
python -m unittest discover -s tests -p 'test_sst*.py' -v
python -m unittest tests.test_patch_sst_frontend -v
```

Expected: all PASS.

- [ ] **Step 2: Compile Python**

```bash
python -m compileall -q scripts/sst scripts/patch_sst_frontend.py
```

Expected: exit 0.

- [ ] **Step 3: Verify index integration is idempotent**

```bash
sha256sum index.html > /tmp/index.before
python scripts/patch_sst_frontend.py --file index.html
sha256sum index.html > /tmp/index.after
diff -u /tmp/index.before /tmp/index.after
```

Expected: no diff.

- [ ] **Step 4: Configure `EARTHDATA_TOKEN` in repository Actions secrets**

Do not put the token in code, workflow YAML, logs, artifacts, or `SST_SETUP.md`.

- [ ] **Step 5: Run the seven-day live prototype first**

Build `2026-09-01` through `2026-09-07`; inspect all five regions in both views. Confirm:

```text
70 WebPs present
all files 1600×1050
land neutral/light grey
ice-covered cells masked
absolute scale fixed -2..34
anomaly scale fixed -6..6
no city labels
manifest has all seven dates
storage_report.json present
```

- [ ] **Step 6: Publish the prototype snapshot to `sst-archive` and smoke-test the website**

Verify in browser:

```text
Meere / SST tab appears in desktop navigation
Meere / SST appears in mobile navigation
all five regions switch correctly
absolute/anomaly switch correctly
date picker works
prev/latest/next works
30-day strip does not preload 30 images
missing date shows explicit message
PNG downloads successfully
PDF downloads successfully
```

- [ ] **Step 7: Only after prototype approval, start historical backfill**

Dispatch `backfill-sst-europe.yml` one calendar month at a time beginning with `2020-01`. Resume is safe because complete dates are skipped and publication is atomic per date/month snapshot.

- [ ] **Step 8: Final commit if verification required fixes**

```bash
git add -A
git commit -m "fix: verify SST Europe stage 1"
```

If no fixes were necessary, do not create an empty commit.

---

## Self-review against the spec

Coverage is explicit for: five regions, MUR source, NOAA 1991–2020 daily normals, leap day, fixed absolute/anomaly scales, land/ice mask, clean design, daily date navigation, 30-day strip, missing-data state, PNG/PDF export, archive from 2020, separate `sst-archive` branch, WebP-only historical storage, manifest URL contract, daily freshness probe, atomic publication, resume-safe monthly backfill, storage prototype, and fixed frame geometry for future animation.

Deliberately deferred because the spec marks it as Stufe 2+: MP4 creation, 7/30/90-day animation UI, custom animation date range, city labels, extrema labels, free-form region bounds, and regional absolute-SST palettes.
