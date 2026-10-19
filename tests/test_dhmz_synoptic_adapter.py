import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import dhmz_synoptic_adapter as dhmz

NOW=datetime(2026,10,19,6,tzinfo=timezone.utc)


class DHMZChartTests(unittest.TestCase):
    def test_croatian_printed_date_not_computed_tomorrow(self):
        actual=dhmz.parse_valid_utc("ČET, 15. LIS 2026. 12:00")
        self.assertEqual(actual,datetime(2026,10,15,12,tzinfo=timezone.utc))
        self.assertLess(actual,NOW)

    def test_valid_charts_and_months(self):
        self.assertEqual(dhmz.parse_valid_utc("PON, 19. LIS. 2026. 12:00"),
                         datetime(2026,10,19,12,tzinfo=timezone.utc))
        self.assertEqual(dhmz.parse_valid_utc("UTORAK, 20. OŽU 2026. 12:00"),
                         datetime(2026,3,20,12,tzinfo=timezone.utc))

    def test_unreadable_and_inconsistent_date_rejected(self):
        for text in ("DHMZ forecast tomorrow 12 UTC","16. LIS 2026. 00:00",
                     "15. LIS 2026. 18:00","55. LIS 2026. 12:00"):
            with self.assertRaises(ValueError):
                dhmz.parse_valid_utc(text)

    def test_stale_image_rejected(self):
        from PIL import Image
        import io
        im=Image.new("RGB",(800,600),"white")
        b=io.BytesIO();im.save(b,format="JPEG")
        with self.assertRaisesRegex(ValueError,"outdated"):
            dhmz.verified_chart(b.getvalue(),NOW,
                caption_reader=lambda _: "ČET, 15. LIS 2026. 12:00")

    def test_valid_forecast_marked_as_official(self):
        from PIL import Image
        import io
        im=Image.new("RGB",(800,600),"white")
        b=io.BytesIO();im.save(b,format="JPEG")
        rec=dhmz.verified_chart(b.getvalue(),NOW,
            caption_reader=lambda _: "PON, 19. LIS 2026. 12:00")
        self.assertEqual(rec["source_id"],"dhmz")
        self.assertEqual(rec["valid_utc"],"2026-10-19T12:00+00:00")
        self.assertEqual(rec["kind"],"Prognose")

if __name__=="__main__":
    unittest.main()
