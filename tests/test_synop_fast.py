"""Real-format DWD BUFR GeoJSON parser regression tests."""
import unittest
from datetime import datetime, timezone
from scripts.update_synop_fast import flatten_values, parse_feature

class SynopGeojsonTests(unittest.TestCase):
    def test_numbered_data_wrappers_keep_physical_shortnames(self):
        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [10.70903, 51.58345, 240.0]},
            "properties": {
                "data_000": {"name": "AIR TEMPERATURE", "shortname": "airTemperature",
                             "value": 289.15, "unit": "K"},
                "data_001": {"name": "WIND SPEED", "shortname": "windSpeed",
                             "value": 4.5, "unit": "m/s"},
                "data_002": {"shortname": "blockNumber", "value": 10},
                "data_003": {"shortname": "stationNumber", "value": 184},
                "data_004": {"shortname": "typicalDate", "value": 20261030},
                "data_005": {"shortname": "typicalTime", "value": 120000},
            },
        }
        flat = {}
        flatten_values(feature["properties"], flat)
        self.assertIn("airtemperature", flat)
        self.assertEqual(flat["airtemperature"], [289.15])
        result = parse_feature(feature, datetime(2026, 10, 30, 12, tzinfo=timezone.utc))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["temperature_c"], 16.0)
        self.assertEqual(result["wind_speed_ms"], 4.5)
        self.assertEqual(result["wmo_id"], "10184")
        self.assertEqual(result["time_utc"], "2026-10-30T12:00Z")

    def test_missing_fields_do_not_fabricate_observations(self):
        feature = {"geometry": {"type": "Point", "coordinates": [10, 50]},
                   "properties": {"data_000": {"shortname": "stationNumber",
                                                "value": 184}}}
        self.assertIsNone(parse_feature(
            feature, datetime(2026, 10, 30, tzinfo=timezone.utc)))

if __name__ == "__main__":
    unittest.main()
