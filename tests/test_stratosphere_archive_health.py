import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util

src=Path(__file__).resolve().parents[1]/"scripts"/"check_stratosphere_archive_health.py"
spec=importlib.util.spec_from_file_location("strato_archive_health",src)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def record(now,hour,age=12):
    when=(now-timedelta(hours=age)).replace(hour=hour,minute=0,second=0,microsecond=0)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def fixture(name,now):
    cfg=m.SOURCES[name]
    hour=0
    cycle=(now-timedelta(hours=12)).replace(hour=hour,minute=0,second=0,microsecond=0)
    iso=cycle.strftime("%Y-%m-%dT%H:%M:%SZ")
    dates=[(cycle+timedelta(days=i)).strftime("%Y-%m-%d") for i in range(17 if name=="GEFS" else 16)]
    members={k:[10.0]*len(dates) for k in ["c00"]+[f"p{i:02d}" for i in range(1,cfg["count"])]}
    run={"schema_version":1,"provider":cfg["provider"],"cycle_utc":iso,"member_count":cfg["count"],
         "level_hpa":10,"latitude_deg":60,"units":"m/s",
         "forecast_horizon_days":len(dates)-1,"valid_dates":dates,"members":members}
    idx={"schema_version":1,"provider":cfg["provider"],"latest_cycle_utc":iso,
         "runs":[{"cycle_utc":iso,"path":f"runs/{cycle:%Y%m%d_%H%M%S}.json"}]}
    return idx,run


class ArchiveHealthTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,30,12,tzinfo=timezone.utc)

    def test_fresh_complete_gefs_and_eps(self):
        for name in m.SOURCES:
            with self.subTest(name=name):
                idx,run=fixture(name,self.now)
                data,errors,warnings=m.validate_manifest(name,idx,run,self.now)
                self.assertFalse(errors,errors)
                self.assertEqual(data["members"],m.SOURCES[name]["count"])
                self.assertEqual(data["archive_runs"],1)
                self.assertTrue(warnings)

    def test_stale_current_cycle_fails(self):
        idx,run=fixture("GEFS",self.now)
        after=self.now+timedelta(days=2)
        _,errors,_=m.validate_manifest("GEFS",idx,run,after)
        self.assertTrue(any("age" in x for x in errors))

    def test_missing_06_12_18_hours_after_two_days_fails(self):
        idx,run=fixture("GEFS",self.now)
        two_days_later=self.now+timedelta(hours=56)
        _,errors,_=m.validate_manifest("GEFS",idx,run,two_days_later)
        self.assertTrue(any("06 UTC" in x and "12 UTC" in x and "18 UTC" in x for x in errors))

    def test_full_00_06_12_18_gefs_coverage_passes(self):
        idx,run=fixture("GEFS",self.now)
        idx["runs"]=[]
        for delta in [0,6,12,18]:
            when=datetime(2026,10,29,18,tzinfo=timezone.utc)-timedelta(hours=delta)
            idx["runs"].append({"cycle_utc":when.strftime("%Y-%m-%dT%H:00:00Z"),
                                "path":f"runs/{when:%Y%m%d_%H%M%S}.json"})
        idx["runs"].insert(0,{"cycle_utc":run["cycle_utc"],
                         "path":f"runs/{datetime.fromisoformat(run['cycle_utc'].replace('Z','+00:00')):%Y%m%d_%H%M%S}.json"})
        _,errors,warnings=m.validate_manifest("GEFS",idx,run,self.now+timedelta(hours=20))
        self.assertFalse(any("initialization hours" in x for x in errors),errors)

    def test_bad_member_count_and_latest_mismatch_fails(self):
        idx,run=fixture("ECMWF ENS",self.now)
        del run["members"]["p50"]
        idx["latest_cycle_utc"]="2026-10-29T00:00:00Z"
        _,errors,_=m.validate_manifest("ECMWF ENS",idx,run,self.now)
        self.assertTrue(any("metadata" in x for x in errors))
        self.assertTrue(any("differs" in x for x in errors))


if __name__=="__main__":
    unittest.main()
