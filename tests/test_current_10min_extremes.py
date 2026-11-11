#!/usr/bin/env python3
"""Regression checks for the DWD original 10-minute extreme temperature fields."""
import importlib.util
import unittest
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location("current10", "scripts/update_current_10min.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
UTC = timezone.utc


def row(stamp, **kwargs):
    return {"dt": datetime.fromisoformat(stamp.replace("Z", "+00:00")), **kwargs}


class RealExtremaTests(unittest.TestCase):
    def test_dwd_original_source_is_configured(self):
        source = module.SOURCE_CONFIG["temperature_extrema"]
        self.assertEqual(source["fields"]["temp_max_10min"], "TX_10")
        self.assertEqual(source["fields"]["temp_min_10min"], "TN_10")
        self.assertEqual(source["fields"]["ground_min_10min"], "TN5_10")
        listing = '10minutenwerte_extrema_temp_00150_now.zip'
        self.assertEqual(set(source["pattern"].findall(listing)), {"00150"})
        self.assertEqual(source["filename"].format(id="00150"), listing)
        self.assertGreaterEqual(module.LIVE_SCHEMA_VERSION, 5)

    def profile(self, include_extrema=True):
        source_rows = {
            "temperature": [
                row("2026-11-10T23:00:00Z", temp=9.9, humidity=100, dewpoint=8.2, pressure=1050, ground_temp=10),
                row("2026-11-11T06:00:00Z", temp=9.0, humidity=72, dewpoint=6.0, pressure=1008, ground_temp=10),
                row("2026-11-11T10:00:00Z", temp=11.1, humidity=91, dewpoint=9.7, pressure=1005, ground_temp=12),
                row("2026-11-11T14:00:00Z", temp=15.4, humidity=61, dewpoint=8.0, pressure=1004, ground_temp=15),
            ],
            "temperature_extrema": [
                # The extreme of the ten minutes ending 00:00 MEZ belongs
                # to November 10, never the fresh local day November 11.
                row("2026-11-10T23:00:00Z", temp_max_10min=42.0, temp_min_10min=-18.0),
                row("2026-11-11T06:00:00Z", temp_max_10min=12.1, temp_min_10min=8.7),
                row("2026-11-11T10:00:00Z", temp_max_10min=14.9, temp_min_10min=10.2),
                row("2026-11-11T14:00:00Z", temp_max_10min=16.3, temp_min_10min=14.4),
            ] if include_extrema else [],
            "wind": [
                row("2026-11-10T23:00:00Z", wind_speed=33),
                row("2026-11-11T06:00:00Z", wind_speed=4),
                row("2026-11-11T10:00:00Z", wind_speed=7.5),
                row("2026-11-11T14:00:00Z", wind_speed=3),
            ],
            "gust": [
                row("2026-11-10T23:00:00Z", gust_speed=45),
                row("2026-11-11T06:00:00Z", gust_speed=10),
                row("2026-11-11T14:00:00Z", gust_speed=9),
            ],
            "precipitation": [
                row("2026-11-10T23:00:00Z", precip_10min=99),
                row("2026-11-11T06:00:00Z", precip_10min=0.6),
                row("2026-11-11T10:00:00Z", precip_10min=None),
                row("2026-11-11T14:00:00Z", precip_10min=0.9),
            ],
        }
        old = module.fetch_source_rows
        try:
            module.fetch_source_rows = lambda source, station_id, available, cutoff: source_rows[source]
            metadata = {"00150": {"id": "00150", "name": "Teststation",
                "state": "Hessen", "elevation_m": 100, "lat": 50.0, "lon": 8.0}}
            available = {key: {"00150"} for key in module.SOURCE_CONFIG}
            return module.build_station_profile("00150", metadata, available,
                datetime(2026, 11, 11, 15, 30, tzinfo=UTC))
        finally:
            module.fetch_source_rows = old

    def test_real_extremes_not_momentary_temperature(self):
        summary, detail = self.profile()
        self.assertEqual(summary["today_min_c"], 8.7)
        self.assertEqual(summary["today_max_c"], 16.3)
        self.assertNotEqual(summary["today_max_c"], 15.4)
        self.assertEqual(detail["today"]["sample_max_10min_c"], 15.4)
        self.assertEqual(detail["today"]["sample_min_10min_c"], 9.0)
        self.assertEqual(detail["today"]["extreme_temperature_max_count"], 3)
        self.assertEqual(detail["today"]["extreme_temperature_min_count"], 3)
        self.assertTrue(summary["availability"]["temperature_extrema"])
        self.assertIn("TX_10/TN_10", summary["today_extreme_source"])
        self.assertEqual(detail["series_columns"][-3:],
            ["temp_max_10min_c","temp_min_10min_c","ground_min_10min_c"])
        self.assertEqual(detail["series"][-1][-3:-1], [16.3, 14.4])

    def test_other_daily_maxima_and_only_daily_rain_sum(self):
        summary, detail = self.profile()
        self.assertEqual(summary["today_max_wind_ms"], 7.5)
        self.assertEqual(summary["today_max_gust_ms"], 10)
        self.assertEqual(summary["today_max_humidity_pct"], 91)
        self.assertEqual(summary["today_max_dewpoint_c"], 9.7)
        self.assertEqual(summary["today_max_pressure_hpa"], 1008)
        self.assertEqual(summary["today_max_ground_temp_c"], 15)
        # The first interval ends at 00:00 MEZ and belongs to the preceding
        # day. Missing values never enter the sum or count as zero.
        self.assertEqual(summary["today_precip_sum_mm"], 1.5)
        self.assertEqual(summary["today_precip_count"], 2)
        self.assertEqual(detail["today"]["max_gust_interval_end_local"][:10], "2026-11-11")
        self.assertEqual(detail["today"]["precip_last_interval_end_local"][:10], "2026-11-11")

    def test_no_false_extreme_when_source_unavailable(self):
        summary, detail = self.profile(include_extrema=False)
        self.assertIsNone(summary["today_min_c"])
        self.assertIsNone(summary["today_max_c"])
        self.assertFalse(summary["availability"]["temperature_extrema"])
        self.assertEqual(detail["today"]["sample_max_10min_c"], 15.4)


if __name__ == "__main__":
    unittest.main()
