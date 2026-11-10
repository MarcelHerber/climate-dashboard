"""Europe snow area: projection, native land masks, real observation and reference tests."""
import datetime as dt
import unittest

import numpy as np

from scripts.update_europe_snow_area import (
    REGION, geographic_mask_and_weights, snow_area_mkm2, date_priority,
    build_result,
)
from scripts.update_snow_maps import SIZE, ascii_indices


class EuropeSnowAreaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mask, cls.weights = geographic_mask_and_weights()

    def test_geographic_bounds_match_the_published_europe_map(self):
        self.assertEqual(REGION, {
            "lat_south": 35, "lat_north": 75, "lon_west": -25, "lon_east": 70
        })
        self.assertTrue(45000 < np.count_nonzero(self.mask) < 65000)
        for lat, lon in [(64.1, -21.9), (52.52, 13.40), (60.0, 60.0)]:
            row, col = ascii_indices(np.array([lat]), np.array([lon]))
            self.assertTrue(self.mask[int(row[0]), int(col[0])],
                            f"Region excluded valid point {lat},{lon}")
        for lat, lon in [(80.0, 10.0), (55.0, 110.0), (27.0, 10.0)]:
            row, col = ascii_indices(np.array([lat]), np.array([lon]))
            self.assertFalse(self.mask[int(row[0]), int(col[0])],
                             f"Region included out-of-bounds point {lat},{lon}")

    def test_native_pixel_area_and_missing_land_rejection(self):
        grid = np.full((SIZE, SIZE), 2, dtype=np.uint8)
        points = np.flatnonzero(self.mask)[:4]
        grid.flat[points] = 4
        self.assertEqual(snow_area_mkm2(grid, self.mask, self.weights),
                         round(float(self.weights.flat[points].sum()), 5))
        grid.fill(3)  # Sea ice cannot be misclassified as snow-covered land.
        with self.assertRaises(ValueError):
            snow_area_mkm2(grid, self.mask, self.weights)
        grid.fill(2)
        self.assertEqual(snow_area_mkm2(grid, self.mask, self.weights), 0.0)

    def test_climatology_requires_true_reference_years(self):
        values = {f"{y}-11-09": round((y-2000)*.1, 5)
                  for y in range(2015, 2026)}
        values["2026-11-09"] = 1.25
        result = build_result(values, dt.date(2026, 11, 10), 1, [])
        row = result["climatology_by_month"]["11"][8]
        self.assertEqual(row["years"], 11)
        self.assertIsNotNone(row["mean"])
        self.assertEqual(row["min_year"], 2015)
        self.assertEqual(row["max_year"], 2025)
        self.assertIsNone(result["climatology_by_month"]["11"][9]["mean"])
        self.assertEqual(result["observed_latest"], "2026-11-09")
        self.assertEqual(result["status"]["n_climatology_days_year"], 1)
        self.assertEqual(result["analysis"]["region"], REGION)

    def test_prioritization_current_date_and_duplicate_safety(self):
        dates = [dt.date(2026, 11, 9), dt.date(2026, 11, 10),
                 dt.date(2025, 11, 9), dt.date(2019, 11, 9),
                 dt.date(2016, 2, 29)]
        todo = list(date_priority(dates, {"2025-11-09"}, dt.date(2026, 11, 10)))
        self.assertEqual(todo[0], dt.date(2026, 11, 9))
        self.assertEqual(todo[1], dt.date(2016, 2, 29))
        self.assertEqual(len(todo), 3)
        self.assertNotIn(dt.date(2026, 11, 10), todo)


if __name__ == "__main__":
    unittest.main()
