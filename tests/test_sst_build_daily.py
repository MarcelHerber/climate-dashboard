import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import xarray as xr
from PIL import Image

from scripts.sst.config import REGIONS
from scripts.sst.build_daily import build_date


def normals_dataset():
    values = np.full((365, 3, 4), 12.0, dtype=float)
    return xr.Dataset(
        {"sst": (("time", "lat", "lon"), values)},
        coords={
            "time": np.arange(365),
            "lat": [50.0, 51.0, 52.0],
            "lon": [-2.0, 0.0, 2.0, 4.0],
        },
    )


def mur_dataset():
    absolute = np.array([
        [10.0, 11.0, 12.0, 13.0],
        [11.0, 12.0, 13.0, 14.0],
        [12.0, 13.0, 14.0, 15.0],
    ])
    return xr.Dataset(
        {
            "analysed_sst": (("time", "lat", "lon"), absolute[None, ...] + 273.15, {"units": "K"}),
            "sea_ice_fraction": (("time", "lat", "lon"), np.zeros((1, 3, 4), dtype=float)),
        },
        coords={"time": [0], "lat": [50.0, 51.0, 52.0], "lon": [-2.0, 0.0, 2.0, 4.0]},
    )


class FakeAdapter:
    def __init__(self, fail_region=None):
        self.fail_region = fail_region
        self.fetch_order = []
        self.normal_calls = 0

    def fetch_mur(self, day, region, path):
        self.fetch_order.append(region.id)
        if region.id == self.fail_region:
            raise RuntimeError("synthetic download failure")
        path.parent.mkdir(parents=True, exist_ok=True)
        mur_dataset().to_netcdf(path, engine="scipy")
        return path

    def normal_dataset(self):
        self.normal_calls += 1
        return normals_dataset()


def fake_render(fields, region, day, view, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (region.width_px, region.height_px), "white")
    image.save(output_path, "WEBP", quality=80)
    return output_path


def fake_validate(path, region):
    with Image.open(path) as image:
        assert image.size == (region.width_px, region.height_px)


def fake_statistics(fields, region):
    offset = float(list(REGIONS).index(region.id))
    return {
        "absolute": {"mean": 20.0 + offset, "min": 10.0 + offset, "max": 30.0 + offset},
        "anomaly": {"mean": 0.5 + offset, "min": -2.0 + offset, "max": 3.0 + offset},
    }


class SstBuildDailyTests(unittest.TestCase):
    def test_build_date_publishes_exactly_eight_files_then_manifest(self):
        adapter = FakeAdapter()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("scripts.sst.build_daily.render_map", side_effect=fake_render), \
             mock.patch("scripts.sst.build_daily.validate_rendered_map", side_effect=fake_validate), \
             mock.patch("scripts.sst.build_daily.summarize_region_statistics", side_effect=fake_statistics) as summarize:
            archive = Path(tmp) / "archive"
            cache = Path(tmp) / "cache"
            result = build_date(date(2026, 9, 14), archive, cache, "token", source_adapter=adapter)
            self.assertFalse(result.already_present)
            self.assertEqual(result.file_count, 8)
            self.assertEqual(len(list(archive.rglob("*.webp"))), 8)
            self.assertTrue((archive / "manifest.json").exists())
            manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
            stats = manifest["dates"]["2026-09-14"]["statistics"]
            self.assertEqual(stats["europe"]["anomaly"]["mean"], 0.5)
            self.assertEqual(stats["nordic_seas"]["absolute"]["max"], 33.0)
            self.assertEqual(summarize.call_count, len(REGIONS))
            self.assertEqual(adapter.fetch_order, list(REGIONS))
            self.assertEqual(adapter.normal_calls, 1)
            self.assertEqual(list(cache.rglob("mur_*.nc")), [])

    def test_second_build_skips_complete_registered_date(self):
        adapter = FakeAdapter()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("scripts.sst.build_daily.render_map", side_effect=fake_render), \
             mock.patch("scripts.sst.build_daily.validate_rendered_map", side_effect=fake_validate), \
             mock.patch("scripts.sst.build_daily.summarize_region_statistics", side_effect=fake_statistics):
            archive = Path(tmp) / "archive"
            cache = Path(tmp) / "cache"
            first = build_date(date(2026, 9, 14), archive, cache, "token", source_adapter=adapter)
            adapter.fetch_order.clear()
            second = build_date(date(2026, 9, 14), archive, cache, "token", source_adapter=adapter)
            self.assertFalse(first.already_present)
            self.assertTrue(second.already_present)
            self.assertEqual(second.file_count, 8)
            self.assertEqual(adapter.fetch_order, [])

    def test_failure_on_third_region_leaves_no_published_files_or_manifest(self):
        adapter = FakeAdapter(fail_region="north_atlantic")
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("scripts.sst.build_daily.render_map", side_effect=fake_render), \
             mock.patch("scripts.sst.build_daily.validate_rendered_map", side_effect=fake_validate), \
             mock.patch("scripts.sst.build_daily.summarize_region_statistics", side_effect=fake_statistics):
            archive = Path(tmp) / "archive"
            cache = Path(tmp) / "cache"
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                build_date(date(2026, 9, 14), archive, cache, "token", source_adapter=adapter)
            self.assertFalse((archive / "manifest.json").exists())
            self.assertEqual(list(archive.rglob("*.webp")), [])
            self.assertEqual(list(cache.rglob("mur_*.nc")), [])


if __name__ == "__main__":
    unittest.main()
