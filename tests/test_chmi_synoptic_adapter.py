import base64
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import chmi_synoptic_adapter as c

NOW=datetime(2026,10,17,7,tzinfo=timezone.utc)
DUMMY_PNG=c.PNG_HEADER+b"X"*19000

def frame(player_time,forecast):
    return {"dateTime":player_time,"isForecastStart":forecast,
            "image":"image/png;base64,"+base64.b64encode(DUMMY_PNG).decode("ascii")}


class CzechSynopticTests(unittest.TestCase):
    def test_real_embedded_header_date_overrides_player_time(self):
        obj={"type":"image","data":[frame("2026-10-17T10:00:00Z",False),
                                      frame("2026-10-18T10:00:00Z",True)]}
        labels=iter(["Analýza synoptické situace Termín: 17.10.2026 00 UTC",
                     "Předpovědní synoptická mapa na: 18.10.2026 12 UTC"])
        values=c.parse_chmi_json(obj,NOW,heading_reader=lambda raw:next(labels))
        self.assertEqual([r["valid_utc"] for r,_ in values],
                         ["2026-10-17T00:00+00:00","2026-10-18T12:00+00:00"])
        self.assertEqual([r["kind"] for r,_ in values],["Analyse","Prognose"])
        self.assertNotEqual(values[0][0]["provider_timeline_utc"],values[0][0]["valid_utc"])
        self.assertNotEqual(values[1][0]["provider_timeline_utc"],values[1][0]["valid_utc"])

    def test_no_published_map_without_legible_printed_validity(self):
        obj={"type":"image","data":[frame("2026-10-17T10:00:00Z",False)]}
        self.assertEqual(c.parse_chmi_json(obj,NOW,heading_reader=lambda raw:"No text"),[])

    def test_reject_unrelated_printed_date(self):
        obj={"type":"image","data":[frame("2026-10-17T10:00:00Z",False)]}
        self.assertEqual(c.parse_chmi_json(obj,NOW,
                         heading_reader=lambda raw:"Termín: 05.10.2026 00 UTC"),[])

    def test_header_parser_rejects_non_utc_and_impossible_date(self):
        with self.assertRaises(ValueError):
            c.parse_printed_timestamp("17.10.2026 10 CEST")
        with self.assertRaises(ValueError):
            c.parse_printed_timestamp("32.10.2026 00 UTC")
        self.assertEqual(c.parse_printed_timestamp("Termín: 17.10.2026 00 UTC"),
                         datetime(2026,10,17,0,tzinfo=timezone.utc))


if __name__=="__main__":
    unittest.main()
