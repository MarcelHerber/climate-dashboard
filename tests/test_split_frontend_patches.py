import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHES = (
    "patch_dashboard_lazy_loading.py",
    "patch_hyras_live_frontend.py",
    "patch_hyras_click_timeseries_frontend.py",
    "fix_hyras_timeseries_rounding.py",
    "patch_hyras_reference_period_frontend.py",
    "patch_state_monthly_ensemble_frontend.py",
    "move_hyras_top3_below_map.py",
    "patch_t850_ensembles_frontend.py",
    "patch_sst_frontend.py",
    "patch_era5_tp_month_frontend.py",
    "patch_era5_current_tp_frontend.py",
    "patch_era5_temperature_rank_frontend.py",
    "fix_era5_period_year_labels.py",
    "patch_era5_running_frontend.py",
)


class SplitFrontendPatchesTest(unittest.TestCase):
    def test_daily_frontend_patches_are_idempotent_after_split(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            shutil.copyfile(ROOT / "index.html", site / "index.html")
            shutil.copytree(ROOT / "js", site / "js")
            (site / "scripts").mkdir()
            shutil.copyfile(ROOT / "scripts/build_pages_site.sh", site / "scripts/build_pages_site.sh")
            sources = [site / "index.html", site / "scripts/build_pages_site.sh", *sorted((site / "js").glob("*.js"))]
            original = {path: path.read_bytes() for path in sources}
            for name in PATCHES:
                with self.subTest(script=name):
                    shutil.copyfile(ROOT / "scripts" / name, site / "scripts" / name)
                    result = subprocess.run(
                        [sys.executable, str(site / "scripts" / name)],
                        cwd=site, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual({p: p.read_bytes() for p in sources}, original)
