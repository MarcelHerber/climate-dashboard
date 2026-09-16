import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import requests
import xarray as xr

from scripts.sst.config import REGIONS
from scripts.sst.sources import (
    discover_oisst_daily_normals_url,
    download_mur_subset,
    ensure_oisst_daily_normals,
    latest_available_mur_date,
    mur_date_available,
)


class FakeResponse:
    def __init__(self, *, json_data=None, text="", content=b"nc", status_code=200, headers=None, chunks=None):
        self._json = json_data
        self.text = text
        self.content = content
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = headers or {}
        self._chunks = chunks

    def json(self):
        if self._json is not None:
            return self._json
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)

    def iter_content(self, chunk_size=1024 * 1024):
        if self._chunks is not None:
            yield from self._chunks
        elif self.content:
            yield self.content


def _fake_erddap_chunk(url: str) -> bytes:
    match = re.search(
        r"sst\[(\d+):1:(\d+)\]\[(\d+):1:(\d+)\]\[(\d+):1:(\d+)\]",
        url,
    )
    if not match:
        raise AssertionError(f"Unerwartete ERDDAP-URL: {url}")
    time_start, time_stop, lat_start, lat_stop, lon_start, lon_stop = map(int, match.groups())
    time = np.arange(time_start, time_stop + 1, dtype=np.float64)
    lat = np.array(
        [-89.875 + lat_start * 0.25, -89.875 + lat_stop * 0.25],
        dtype=np.float32,
    )
    lon = 0.125 + np.arange(lon_start, lon_stop + 1, dtype=np.float32) * 0.25
    values = np.zeros((time.size, lat.size, lon.size), dtype=np.float32)
    dataset = xr.Dataset(
        {"sst": (("time", "latitude", "longitude"), values)},
        coords={"time": time, "latitude": lat, "longitude": lon},
    )
    return dataset.to_netcdf()


class SstSourceTests(unittest.TestCase):
    def test_cmr_probe_accepts_date_with_granule(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(json_data={"feed": {"entry": [{"id": "g1"}]}})
        self.assertTrue(mur_date_available(date(2026, 9, 14), session=session))
        params = session.get.call_args.kwargs["params"]
        self.assertEqual(params["collection_concept_id"], "C1996881146-POCLOUD")
        self.assertIn("2026-09-14T00:00:00Z", params["temporal"])

    def test_latest_available_mur_date_walks_back(self):
        session = mock.Mock()
        session.get.side_effect = [
            FakeResponse(json_data={"feed": {"entry": []}}),
            FakeResponse(json_data={"feed": {"entry": [{"id": "g"}]}}),
        ]
        self.assertEqual(latest_available_mur_date(date(2026, 9, 16), session=session), date(2026, 9, 15))

    def test_noaa_catalog_selects_exact_highres_daily_1991_2020_file(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(text='''
          <a href="catalog.html?dataset=x/sst.mon.ltm.1991-2020.nc">monthly</a>
          <a href="catalog.html?dataset=x/sst.day.mean.ltm.1991-2020.nc">daily</a>
        ''')
        url = discover_oisst_daily_normals_url(session=session)
        self.assertTrue(url.endswith("/sst.day.mean.ltm.1991-2020.nc"))
        self.assertIn("fileServer/Datasets/noaa.oisst.v2.highres", url)

    def test_noaa_normals_cache_uses_buffered_region_union(self):
        session = mock.Mock()

        def get_chunk(url, **_kwargs):
            self.assertIn("comet.nefsc.noaa.gov/erddap/griddap", url)
            return FakeResponse(
                content=_fake_erddap_chunk(url),
                headers={"content-type": "application/x-netcdf"},
            )

        session.get.side_effect = get_chunk
        with tempfile.TemporaryDirectory() as tmp:
            path = ensure_oisst_daily_normals(Path(tmp), session=session)
            self.assertTrue(path.exists())
            self.assertIn("regions_v2", path.name)
            with xr.open_dataset(path, decode_times=False) as merged:
                lon = np.asarray(merged["lon"].values)
                self.assertEqual(merged.sizes["time"], 365)
                self.assertEqual(lon.size, 472)
                self.assertTrue(np.all(np.diff(lon) > 0))
                self.assertAlmostEqual(float(lon.min()), -66.375, places=3)
                self.assertAlmostEqual(float(lon.max()), 51.375, places=3)

        self.assertEqual(session.get.call_count, 26)
        time_ranges = []
        lon_ranges = set()
        for call in session.get.call_args_list:
            url = call.args[0]
            match = re.search(
                r"sst\[(\d+):1:(\d+)\]\[(\d+):1:(\d+)\]\[(\d+):1:(\d+)\]",
                url,
            )
            self.assertIsNotNone(match)
            time_start, time_stop, lat_start, lat_stop, lon_start, lon_stop = map(int, match.groups())
            self.assertEqual((lat_start, lat_stop), (434, 699))
            self.assertLessEqual(time_stop - time_start + 1, 30)
            time_ranges.append((time_start, time_stop))
            lon_ranges.add((lon_start, lon_stop))

        self.assertEqual(lon_ranges, {(0, 205), (1174, 1439)})
        self.assertEqual(
            sorted(set(time_ranges)),
            [
                (0, 29),
                (30, 59),
                (60, 89),
                (90, 119),
                (120, 149),
                (150, 179),
                (180, 209),
                (210, 239),
                (240, 269),
                (270, 299),
                (300, 329),
                (330, 359),
                (360, 364),
            ],
        )
        for time_range in set(time_ranges):
            self.assertEqual(time_ranges.count(time_range), 2)

    def test_noaa_normals_retry_transient_500_then_succeed(self):
        session = mock.Mock()
        attempts = 0

        def get_chunk(url, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return FakeResponse(status_code=500, text="temporary NOAA failure")
            return FakeResponse(
                content=_fake_erddap_chunk(url),
                headers={"content-type": "application/x-netcdf"},
            )

        session.get.side_effect = get_chunk
        with tempfile.TemporaryDirectory() as tmp, mock.patch("scripts.sst.sources.time.sleep") as sleep:
            path = ensure_oisst_daily_normals(Path(tmp), session=session)
            self.assertTrue(path.exists())
            self.assertEqual(session.get.call_count, 27)
            sleep.assert_called_once()

    def test_harmony_async_job_is_polled_and_data_link_downloaded(self):
        session = mock.Mock()
        session.get.side_effect = [
            FakeResponse(
                json_data={
                    "jobID": "job-1",
                    "status": "running",
                    "progress": 0,
                    "links": [{"rel": "self", "href": "https://harmony.earthdata.nasa.gov/jobs/job-1"}],
                },
                headers={"content-type": "application/json"},
            ),
            FakeResponse(
                json_data={
                    "jobID": "job-1",
                    "status": "successful",
                    "progress": 100,
                    "links": [
                        {"rel": "self", "href": "https://harmony.earthdata.nasa.gov/jobs/job-1"},
                        {"rel": "data", "href": "https://example.test/output.nc"},
                    ],
                },
                headers={"content-type": "application/json"},
            ),
            FakeResponse(content=b"CDF\x01async", headers={"content-type": "application/x-netcdf4"}),
        ]
        with tempfile.TemporaryDirectory() as tmp, mock.patch("scripts.sst.sources.time.sleep"):
            dest = Path(tmp) / "mur.nc"
            download_mur_subset(date(2026, 9, 14), REGIONS["europe"], dest, "secret", session=session)
            self.assertEqual(dest.read_bytes(), b"CDF\x01async")
        self.assertEqual(session.get.call_count, 3)

    def test_harmony_retries_transient_read_timeout_then_succeeds(self):
        session = mock.Mock()
        session.get.side_effect = [
            requests.exceptions.ReadTimeout("temporary Harmony timeout"),
            FakeResponse(content=b"CDF\x01retry", headers={"content-type": "application/x-netcdf4"}),
        ]
        with tempfile.TemporaryDirectory() as tmp, mock.patch("scripts.sst.sources.time.sleep") as sleep:
            dest = Path(tmp) / "mur.nc"
            result = download_mur_subset(
                date(2026, 9, 14), REGIONS["europe"], dest, "secret", session=session
            )
            self.assertEqual(result, dest)
            self.assertEqual(dest.read_bytes(), b"CDF\x01retry")
        self.assertEqual(session.get.call_count, 2)
        sleep.assert_called_once()

    def test_harmony_subset_request_uses_buffered_region_bounds(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(content=b"CDF\x01payload", headers={"content-type": "application/x-netcdf4"})
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "mur.nc"
            result = download_mur_subset(date(2026, 9, 14), REGIONS["europe"], dest, "secret", session=session)
            self.assertEqual(result, dest)
            self.assertEqual(dest.read_bytes(), b"CDF\x01payload")
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        subsets = [value for key, value in kwargs["params"] if key == "subset"]
        self.assertIn("lat(23.5:73.5)", subsets)
        self.assertIn("lon(-31.5:46.5)", subsets)
        self.assertIn(
            'time("2026-09-14T00:00:00Z":"2026-09-14T23:59:59Z")',
            subsets,
        )


if __name__ == "__main__":
    unittest.main()