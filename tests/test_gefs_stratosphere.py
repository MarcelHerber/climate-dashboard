"""Offline regression tests for 60N/10hPa NOAA GEFS ensemble ingestion."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import build_gefs_60n_10hpa_ensemble as mod
from datetime import datetime,timezone


class GefsWindTests(unittest.TestCase):
    def test_control_and_perturbed_naming(self):
        cycle=datetime(2026,10,21,0,tzinfo=timezone.utc)
        control=parse_qs(urlparse(mod.url_for(cycle,"c00",840)).query)
        perturbed=parse_qs(urlparse(mod.url_for(cycle,"p30",384)).query)
        self.assertEqual(control["file"],["gec00.t00z.pgrb2a.0p50.f840"])
        self.assertEqual(perturbed["file"],["gep30.t00z.pgrb2a.0p50.f384"])
        self.assertEqual(control["lev_10_mb"],["on"])
        self.assertEqual(control["var_UGRD"],["on"])
        self.assertEqual(control["toplat"],["60.5"])
        self.assertEqual(control["bottomlat"],["59.5"])
        self.assertIn("/gefs.20261021/00/atmos/pgrb2ap5",control["dir"][0])

    def test_each_6hour_cycle_uses_its_own_noaa_filename_and_directory(self):
        cycle=datetime(2026,10,30,12,tzinfo=timezone.utc)
        url=urlparse(mod.url_for(cycle,"p01",384))
        query=parse_qs(url.query)
        self.assertEqual(query["file"],["gep01.t12z.pgrb2a.0p50.f384"])
        self.assertIn("/gefs.20261030/12/atmos/pgrb2ap5",query["dir"][0])
        self.assertEqual([x.hour for x in mod.candidates(datetime(2026,10,30,17,35,tzinfo=timezone.utc))[:4]],[12,6,0,18])

    def test_06z_never_requests_35day_horizon(self):
        cycle=datetime(2026,10,30,6,tzinfo=timezone.utc)
        leads=[]
        def fake_fetch(c,m,h):
            leads.append(h)
            return m,h,12.
        with patch.object(mod,"candidates",return_value=[cycle]), \
             patch.object(mod,"fetch_wind",side_effect=fake_fetch):
            self.assertEqual(mod.choose_cycle(),(cycle,16))
        self.assertNotIn(840,leads)
        self.assertIn(384,leads)

    def test_archiving_newer_gefs_and_delayed_35day_old_cycle(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old=datetime(2026,10,28,0,tzinfo=timezone.utc)
            new=datetime(2026,10,28,6,tzinfo=timezone.utc)
            def field(run,member,lead):
                # The U wind in the long extension must match the same 00 cycle,
                # never get mixed into the 06 UTC 16-day product.
                return member,lead,10.0+(run.hour/6)+lead/1000
            with patch.object(mod,"fetch_wind",side_effect=field):
                mod.build_cycle(root,2,old,16)
                mod.build_cycle(root,2,new,16)
                mod.build_cycle(root,2,old,35)
            index=json.loads((root/"gefs_index.json").read_text())
            current=json.loads((root/"gefs_current.json").read_text())
            assert current["cycle_utc"]==new.isoformat().replace("+00:00","Z")
            assert current["forecast_horizon_days"]==16
            assert len(index["runs"])==2
            assert index["runs"][0]["cycle_utc"]==current["cycle_utc"]
            archived=json.loads((root/"runs"/"20261028_000000.json").read_text())
            assert archived["forecast_horizon_days"]==35
            assert len(archived["members"]["p30"])==36
            assert archived["members"]["p30"][16]==10.384
            assert archived["members"]["p30"][35]==10.84
            assert mod.verified(archived)
            assert mod.verified(current)
            assert mod.publish(root,current)["runs"][1]["forecast_horizon_days"]==35

    def test_incomplete_gefs_cannot_replace_current_archive(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cycle=datetime(2026,10,28,12,tzinfo=timezone.utc)
            def partial(run,member,lead):
                if member=="p17" and lead==48:
                    raise RuntimeError("missing original field")
                return member,lead,10.0
            with patch.object(mod,"fetch_wind",side_effect=partial):
                with self.assertRaises(RuntimeError):
                    mod.build_cycle(root,2,cycle,16)
            assert not (root/"gefs_current.json").exists()
            assert not (root/"gefs_index.json").exists()

    def test_all_real_members(self):
        self.assertEqual(len(mod.MEMBERS),31)
        self.assertEqual(mod.MEMBERS[0],"c00")
        self.assertEqual(mod.MEMBERS[-1],"p30")
        self.assertEqual(len(set(mod.MEMBERS)),31)

    def test_sample_only_exact_latitude(self):
        # 720 longitudes at latitude 60.0 are averaged; the neighbouring
        # 59.5 and 60.5 bands must not affect the result.
        lat=np.concatenate([np.full(720,v,dtype=np.float32) for v in (60.5,60.,59.5)])
        lon=np.tile(np.arange(720,dtype=np.float32)/2,3)
        speed=np.concatenate([np.full(720,99,dtype=np.float32),
                              np.arange(720,dtype=np.float32)/10,
                              np.full(720,-40,dtype=np.float32)])
        result=mod.zonal_mean_from_grid(lat,lon,speed)
        self.assertAlmostEqual(result,35.95,places=3)

    def test_prefer_latest_sixteen_day_run_over_older_thirtyfive(self):
        newest=datetime(2026,10,23,0,tzinfo=timezone.utc)
        older=datetime(2026,10,22,0,tzinfo=timezone.utc)
        checked=[]
        def mocked_fetch(cycle,member,lead):
            checked.append((cycle,member,lead))
            if cycle==newest and lead==840:
                raise RuntimeError("Fresh 35-day endpoint not yet published")
            if cycle in (newest,older):
                return member,lead,15.0
            raise RuntimeError("not found")
        with patch.object(mod,"candidates",return_value=[newest,older]), \
             patch.object(mod,"fetch_wind",side_effect=mocked_fetch):
            self.assertEqual(mod.choose_cycle(),(newest,16))
        self.assertEqual(checked[0],(newest,"c00",840))
        self.assertEqual(checked[1],(newest,"c00",384))
        self.assertEqual(checked[2],(newest,"p30",384))

    def test_fallback_to_older_complete_cycle(self):
        newest=datetime(2026,10,23,0,tzinfo=timezone.utc)
        older=datetime(2026,10,22,0,tzinfo=timezone.utc)
        def mocked_fetch(cycle,member,lead):
            if cycle==newest:
                raise RuntimeError("new cycle missing")
            return member,lead,20.0
        with patch.object(mod,"candidates",return_value=[newest,older]), \
             patch.object(mod,"fetch_wind",side_effect=mocked_fetch):
            self.assertEqual(mod.choose_cycle(),(older,35))

    def test_missing_longitude_rejected(self):
        lon=np.arange(719,dtype=np.float32)/2
        lat=np.full(719,60,dtype=np.float32)
        values=np.full(719,20,dtype=np.float32)
        with self.assertRaisesRegex(ValueError,"incomplete"):
            mod.zonal_mean_from_grid(lat,lon,values)


if __name__=="__main__":
    unittest.main()
