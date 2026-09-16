import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
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


def _fake_noaa_chunk(west: float, east: float) -> bytes:
    lon = np.arange(west + 0.125, east, 0.25, dtype=np.float32)
    lat = np.array([25.125, 25.375], dtype=np.float32)
    time = np.array([0.0, 1.0], dtype=np.float64)
    values = np.zeros((time.size, lat.size, lon.size), dtype=np.float32)
    dataset = xr.Dataset(
        {"sst": (("time", "lat", "lon"), values)},
        coords={"time": time, "lat": lat, "lon": lon},
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

    def test_noaa_normals_cache_chunks_wide_request_and_merges_longitudes(self):
        session = mock.Mock()

        def get_chunk(_url, **kwargs):
            params = kwargs["params"]
            west = float(params["west"])
            east = float(params["east"])
            return FakeResponse(
                content=_fake_noaa_chunk(west, east),
                headers={"content-type": "application/x-netcdf"},
            )

        session.get.side_effect = get_chunk
        with tempfile.TemporaryDirectory() as tmp:
            path = ensure_oisst_daily_normals(Path(tmp), session=session)
            self.assertTrue(path.exists())
            with xr.open_dataset(path) as merged:
                lon = np.asarray(merged["lon"].values)
                self.assertEqual(lon.size, 440)
                self.assertTrue(np.all(np.diff(lon) > 0))
                self.assertAlmostEqual(float(lon.min()), -59.875, places=3)
                self.assertAlmostEqual(float(lon.max()), 49.875, places=3)

        self.assertEqual(session.get.call_count, 8)
        for call in session.get.call_args_list:
            params = call.kwargs["params"]
            self.assertEqual(params["var"], "sst")
            self.assertEqual(params["time"], "all")
            self.assertGreaterEqual(float(params["west"]), 0.0)
            self.assertLessEqual(float(params["east"]) - float(params["west"]), 15.0)
            self.assertEqual(params["south"], 25.0)
            self.assertEqual(params["north"], 82.0)

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

    def test_harmony_subset_request_includes_region_date_and_token(self):
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
        self.assertIn("lat(30.0:72.0)", subsets)
        self.assertIn("lon(-30.0:45.0)", subsets)
        self.assertTrue(any("2026-09-14T00:00:00Z" in value for value in subsets))


if __name__ == "__main__":
    unittest.main()
