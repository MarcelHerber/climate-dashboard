import gzip
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts import hyras_temperature_raster as raster


class TestRaster(unittest.TestCase):
    def test_export_preserves_signed_values_and_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            entry = {"start_date": "2026-11-01", "end_date": "2026-11-14"}
            raster.publish(root, entry, "month_11", "1991-2020", np.array([[1.25, np.nan], [-2.5, 0]]), "2026-11-01", "2026-11-14")
            path = root / entry["raster_by_reference"]["1991-2020"]
            self.assertEqual(np.frombuffer(gzip.decompress(path.read_bytes()), dtype="<i2").tolist(), [125, -32768, -250, 0])
            self.assertEqual(entry["raster_grid"], {"width": 2, "height": 2})
            self.assertEqual(entry["raster_dates_by_reference"]["1991-2020"], ["2026-11-01", "2026-11-14"])

    def test_references_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            entry = {}
            for ref, value in [("1991-2020", 1), ("1961-1990", 2)]:
                raster.publish(root, entry, "month_11", ref, np.array([[value]]), "2026-11-01", "2026-11-14")
            self.assertEqual(len(set(entry["raster_by_reference"].values())), 2)
            self.assertEqual(set(entry["raster_by_reference"]), {"1991-2020", "1961-1990"})

    def test_preserve_live_anomaly_only_for_same_dates(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            old={"start_date":"2026-11-01","end_date":"2026-11-14","anomaly":"live.png","reference_exact":True}
            (root/'live.png').touch()
            raster.publish(root,old,'month_11','1991-2020',np.array([[1.0]]),'2026-11-01','2026-11-14')
            changed={"start_date":"2026-11-01","end_date":"2026-11-15"}
            raster.preserve(root,changed,old)
            self.assertNotIn('anomaly',changed)
            same={"start_date":"2026-11-01","end_date":"2026-11-14"}
            raster.preserve(root,same,old)
            self.assertEqual(same['anomaly'],'live.png')
            self.assertEqual(same['raster_by_reference'],old['raster_by_reference'])


if __name__ == "__main__":
    unittest.main()
