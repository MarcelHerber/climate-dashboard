#!/usr/bin/env python3
"""Offline regression tests: archive shards must be complete and lossless."""
import json
import tempfile
import unittest
from pathlib import Path
from scripts.merge_rekordlabor_hourly import merge,validate_station

def station(sid):
    return {"schema":1,"station_id":sid,"name":"DWD station "+sid,
        "state":"Hessen","lat":50.1,"lon":8.7,"generated_at":"2026-11-14T12:00:00+00:00",
        "unavailable_sources":{},
        "metrics":{"temperature":{
            "source":"DWD CDC temperature","source_url":"https://opendata.dwd.de/true.zip",
            "unit":"°C","period":{"start":"2000-01-01T00:00Z","end":"2020-12-31T00:00Z"},
            "observed_hours":500000,
            "windows":{"1":{"coverage":{"pairs":100},
                "up":[{"start":"2020-01-01T00:00Z","end":"2020-01-01T01:00Z",
                     "before":1.0,"after":2.0,"delta":1.0,
                     "trace":[["2020-01-01T00:00Z",1.0],["2020-01-01T01:00Z",2.0]]}],
                "down":[]}},
            "quality_notes":"Exact DWD observations"}}}
def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf8")

class HourlyShardedTests(unittest.TestCase):
    def test_merge_preserves_prior_stations_and_documents_exclusions(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);archive=base/"published";parts=base/"parts"
            old=station("00001")
            dump(archive/"00001.json",old)
            dump(archive/"index.json",{"schema":1,"ready":True,"stations":[validate_station(old,"00001")]})
            for shard,sid in [(0,"00002"),(1,"00003")]:
                folder=parts/f"hourly-shard-{shard}"
                valid=[sid] if shard==0 else []
                excluded={} if shard==0 else {sid:{"temperature":"No measured pairs"}}
                dump(folder/"_manifest.json",{
                    "schema":1,"shard_index":shard,"shard_count":2,
                    "candidate_hash":"identical-inventory","candidate_count":2,
                    "attempted":[sid],"accepted":valid,"excluded":excluded})
                if valid:dump(folder/(sid+".json"),station(sid))
            result,coverage=merge(parts,archive,2)
            self.assertEqual(len(result["stations"]),2)
            self.assertEqual(coverage["candidate_count"],2)
            self.assertEqual(coverage["validated_in_run"],1)
            self.assertEqual(coverage["excluded_count"],1)
            self.assertTrue((archive/"00001.json").exists())
            self.assertEqual(len(json.loads((archive/"index.json").read_text())["stations"]),2)

    def test_duplicate_shards_abort_before_touching_index(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);archive=base/"archive";parts=base/"parts"
            dump(archive/"index.json",{"ready":True,"stations":[]})
            for number in (0,1):
                dump(parts/f"hourly-shard-{number}"/"_manifest.json",{
                    "schema":1,"shard_index":0,"shard_count":2,
                    "candidate_hash":"abc","candidate_count":2,
                    "attempted":["00002"],"accepted":[],"excluded":{"00002":"missing"}})
            with self.assertRaises(ValueError):
                merge(parts,archive,2)
            self.assertEqual(json.loads((archive/"index.json").read_text())["stations"],[])

    def test_fabricated_source_rejected(self):
        doc=station("00002")
        doc["metrics"]["temperature"]["source_url"]="https://example.com/fiction.zip"
        with self.assertRaises(ValueError):
            validate_station(doc,"00002")

if __name__=="__main__":
    unittest.main()
