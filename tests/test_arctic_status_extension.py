import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_data_status as mod


class ArcticArchiveStatusTests(unittest.TestCase):
    def fixture(self, folder, *, missing_cap=False):
        root = Path(folder)
        folder_dmi = root / "data"
        folder_dmi.mkdir(parents=True, exist_ok=True)
        years = {}
        for y in range(1958, 2027):
            years[str(y)] = [None] * 366
        days = ["01-01"] * 366
        days[0] = "11-07"
        years["2026"][0] = -12.1
        (folder_dmi / "arctic80_temperature.json").write_text(json.dumps({
            "schema": 1, "days": days, "years": years, "last_date": "2026-11-07",
            "updated_utc": "2026-11-09T00:03:04Z"
        }))
        arctic_dir = folder_dmi / "arctic_era5_maps"
        arctic_dir.mkdir()
        rows = []
        for iso in ["2026-10-30", "2026-10-31", "2026-11-01"]:
            regions = {}
            for cap in ("60", "70", "80"):
                tag = iso.replace("-", "")
                regions[cap] = {
                    "temperature_png": f"maps/t2m_{cap}n_{tag}.png",
                    "anomaly_png": f"maps/anomaly_{cap}n_{tag}.png",
                    "mean_c": -8.5, "mean_anomaly_k": 2.5
                }
            if missing_cap and iso == "2026-10-31":
                del regions["60"]
            rows.append({"date": iso, "regions": regions})
        (arctic_dir / "index.json").write_text(json.dumps({
            "schema": 2, "ready": True, "latest_date": "2026-11-01",
            "generated_utc": "2026-11-08T22:00:00Z", "target_days": 3,
            "days": rows
        }))
        return root

    def test_complete_three_region_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "ROOT", self.fixture(tmp)):
                rows = {x["id"]: x for x in mod.build()["datasets"]}
            self.assertEqual(rows["dmi_arctic"]["latest"], "2026-11-07")
            self.assertEqual(rows["era5_arctic_maps"]["latest"], "2026-11-01")
            self.assertIn("3/3 vollständig", rows["era5_arctic_maps"]["coverage"])
            self.assertNotIn("Lücken", rows["era5_arctic_maps"]["coverage"])

    def test_missing_region_does_not_count_as_a_complete_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "ROOT", self.fixture(tmp, missing_cap=True)):
                rows = {x["id"]: x for x in mod.build()["datasets"]}
            self.assertEqual(rows["era5_arctic_maps"]["status"], "incomplete")
            self.assertIn("2/3 vollständig", rows["era5_arctic_maps"]["coverage"])
            self.assertIn("1 Lücken", rows["era5_arctic_maps"]["coverage"])

    def test_date_mismatch_flags_dmi_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            p = root / "data/arctic80_temperature.json"
            doc = json.loads(p.read_text())
            doc["last_date"] = "2026-11-08"
            p.write_text(json.dumps(doc))
            with patch.object(mod, "ROOT", root):
                rows = {x["id"]: x for x in mod.build()["datasets"]}
            self.assertEqual(rows["dmi_arctic"]["status"], "delayed")
            self.assertIn("prüfen", rows["dmi_arctic"]["note"])


if __name__ == "__main__":
    unittest.main()
