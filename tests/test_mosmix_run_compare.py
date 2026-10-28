"""Previous MOSMIX model runs: same UTC validity and real source values only."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("mosmix_previous",ROOT/"scripts/merge_mosmix_previous.py")
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class PreviousRunTests(unittest.TestCase):
    def test_attach_real_previous_only_when_older(self):
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname)
            old=root/"previous.json"
            current=root/"mosmix_ttt.json"
            details=root/"stations"
            details.mkdir()
            old.write_text(json.dumps({
                "product":"DWD MOSMIX-L","issue_time":"2026-10-27T09:00:00Z",
                "timesteps":["2026-10-27T10:00:00Z","2026-10-27T11:00:00Z"],
                "stations":[{"key":"abc","values":[13,14],
                             "tx12":{"0":16.0},"tn12":{"1":9.0}}]}))
            current.write_text(json.dumps({
                "product":"DWD MOSMIX-L","issue_time":"2026-10-27T15:00:00Z",
                "timesteps":["2026-10-27T11:00:00Z","2026-10-27T12:00:00Z"],
                "stations":[{"key":"abc"}]}))
            f=details/"abc.json"
            f.write_text(json.dumps({"issue_time":"2026-10-27T15:00:00Z",
                                     "parameters":{"TTT":[14.5,15.0]}}))
            self.assertEqual(mod.attach_previous(old,current),1)
            content=json.loads(f.read_text())
            self.assertEqual(content["parameters"]["TTT"],[14.5,15.0])
            self.assertEqual(content["previous"]["TTT"],[13,14])
            self.assertEqual(content["previous"]["timesteps"][1],"2026-10-27T11:00:00Z")
            self.assertEqual(content["previous"]["TX"]["0"],16.0)
            self.assertEqual(content["previous"]["issue_time"],"2026-10-27T09:00:00Z")
            current.write_text(json.dumps({
                "product":"DWD MOSMIX-L","issue_time":"2026-10-27T03:00:00Z",
                "stations":[{"key":"abc"}]}))
            self.assertEqual(mod.attach_previous(old,current),0)
            self.assertEqual(json.loads(f.read_text())["issue_time"],"2026-10-27T15:00:00Z")


if __name__=="__main__":
    unittest.main()
