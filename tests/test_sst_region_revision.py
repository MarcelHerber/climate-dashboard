from pathlib import Path
import unittest

from scripts.sst.config import REGIONS


class SstRegionRevisionTests(unittest.TestCase):
    def test_revised_region_contract(self):
        self.assertEqual(
            list(REGIONS),
            ["europe", "mediterranean", "north_atlantic", "nordic_seas"],
        )
        self.assertNotIn("north_baltic", REGIONS)

        self.assertEqual(REGIONS["europe"].bounds, (-30.0, 25.0, 45.0, 72.0))
        self.assertEqual(REGIONS["europe"].download_bounds, (-31.5, 23.5, 46.5, 73.5))

        self.assertEqual(REGIONS["mediterranean"].bounds, (-18.0, 30.0, 36.0, 46.0))
        self.assertEqual(REGIONS["mediterranean"].download_bounds, (-19.5, 28.5, 37.5, 47.5))

        self.assertEqual(REGIONS["north_atlantic"].bounds, (-65.0, 20.0, 25.0, 78.0))
        self.assertEqual(REGIONS["north_atlantic"].download_bounds, (-66.5, 18.5, 26.5, 79.5))

        self.assertEqual(REGIONS["nordic_seas"].bounds, (-35.0, 50.0, 50.0, 84.0))
        self.assertEqual(REGIONS["nordic_seas"].download_bounds, (-36.5, 48.5, 51.5, 85.0))

    def test_cartopy_receives_extent_as_west_east_south_north(self):
        render_source = Path("scripts/sst/render.py").read_text(encoding="utf-8")
        self.assertIn(
            "ax.set_extent((region.west, region.east, region.south, region.north), crs=ccrs.PlateCarree())",
            render_source,
        )
        self.assertNotIn("ax.set_extent(region.bounds", render_source)

    def test_pilot_expects_four_regions_for_seven_days(self):
        workflow = Path(".github/workflows/probe-sst-seven-days.yml").read_text(encoding="utf-8")
        self.assertIn('test "$COUNT" -eq 56', workflow)
        self.assertIn("Erwartete Karten: 56", workflow)
        self.assertIn("sst-europe-pilot-2026-09-01-to-07-v4", workflow)
        self.assertNotIn('test "$COUNT" -eq 70', workflow)


if __name__ == "__main__":
    unittest.main()
