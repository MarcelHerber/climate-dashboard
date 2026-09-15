import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_hyras_daily_anomaly_animations import build_all, build_parameter


class AnimationBuilderTests(unittest.TestCase):
    def make_tree(self, root: Path, parameter="tmean"):
        regions = root / parameter / "regions"
        for reference in ("1991-2020", "1961-1990"):
            folder = regions / "daily_anomalies" / reference
            folder.mkdir(parents=True, exist_ok=True)
            for day in ("2026-06-01", "2026-06-02", "2026-06-03"):
                (folder / f"{day}.png").write_bytes(b"png")
        manifest = {
            "schema_version": 1,
            "parameter": parameter,
            "data_through": "2026-06-03",
            "references": ["1991-2020", "1961-1990"],
            "available_dates": ["2026-06-01", "2026-06-02", "2026-06-03"],
            "dates": {
                day: {
                    ref: f"daily_anomalies/{ref}/{day}.png"
                    for ref in ("1991-2020", "1961-1990")
                }
                for day in ("2026-06-01", "2026-06-02", "2026-06-03")
            },
        }
        (regions / "daily_anomaly_maps.json").write_text(json.dumps(manifest), encoding="utf-8")
        return regions, manifest

    def test_build_parameter_writes_separate_mp4s_without_touching_source_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            output = Path(tmp) / "animations"
            regions, original_manifest = self.make_tree(root)

            def fake_run(command, check):
                Path(command[-1]).write_bytes(b"mp4")
                return mock.Mock(returncode=0)

            with mock.patch("scripts.build_hyras_daily_anomaly_animations.shutil.which", return_value="/usr/bin/ffmpeg"), \
                 mock.patch("scripts.build_hyras_daily_anomaly_animations.subprocess.run", side_effect=fake_run):
                result = build_parameter(root, output, "tmean", fps=3)

            self.assertEqual(result["data_through"], "2026-06-03")
            self.assertEqual(set(result["references"]), {"1991-2020", "1961-1990"})
            for ref, meta in result["references"].items():
                self.assertEqual(meta["format"], "mp4")
                self.assertEqual(meta["fps"], 3)
                self.assertEqual(meta["frame_count"], 3)
                self.assertEqual(meta["start_date"], "2026-06-01")
                self.assertEqual(meta["end_date"], "2026-06-03")
                self.assertTrue((output / meta["url"]).exists())
                self.assertIn(ref, meta["url"])

            after = json.loads((regions / "daily_anomaly_maps.json").read_text(encoding="utf-8"))
            self.assertEqual(after, original_manifest)

    def test_build_all_writes_one_snapshot_manifest_for_all_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            output = Path(tmp) / "animations"
            for parameter in ("tmean", "tmax", "tmin"):
                self.make_tree(root, parameter)

            def fake_run(command, check):
                Path(command[-1]).write_bytes(b"mp4")
                return mock.Mock(returncode=0)

            with mock.patch("scripts.build_hyras_daily_anomaly_animations.shutil.which", return_value="/usr/bin/ffmpeg"), \
                 mock.patch("scripts.build_hyras_daily_anomaly_animations.subprocess.run", side_effect=fake_run):
                snapshot = build_all(root, output, fps=3)

            self.assertEqual(snapshot["schema_version"], 1)
            self.assertEqual(set(snapshot["parameters"]), {"tmean", "tmax", "tmin"})
            disk = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(disk, snapshot)

    def test_missing_frame_is_rejected_instead_of_building_incomplete_movie(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            output = Path(tmp) / "animations"
            regions, _ = self.make_tree(root)
            (regions / "daily_anomalies" / "1991-2020" / "2026-06-02.png").unlink()

            with mock.patch("scripts.build_hyras_daily_anomaly_animations.shutil.which", return_value="/usr/bin/ffmpeg"):
                with self.assertRaisesRegex(RuntimeError, "Frame fehlt"):
                    build_parameter(root, output, "tmean", fps=3)

    def test_ffmpeg_command_uses_h264_mp4_and_fixed_portrait_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            output = Path(tmp) / "animations"
            self.make_tree(root)
            commands = []

            def fake_run(command, check):
                commands.append(command)
                Path(command[-1]).write_bytes(b"mp4")
                return mock.Mock(returncode=0)

            with mock.patch("scripts.build_hyras_daily_anomaly_animations.shutil.which", return_value="/usr/bin/ffmpeg"), \
                 mock.patch("scripts.build_hyras_daily_anomaly_animations.subprocess.run", side_effect=fake_run):
                build_parameter(root, output, "tmean", fps=4)

            self.assertEqual(len(commands), 2)
            cmd = commands[0]
            self.assertIn("libx264", cmd)
            self.assertIn("yuv420p", cmd)
            self.assertIn("4", cmd)
            filter_arg = cmd[cmd.index("-vf") + 1]
            self.assertIn("1080", filter_arg)
            self.assertIn("1320", filter_arg)


if __name__ == "__main__":
    unittest.main()
