import io,sys,unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from PIL import Image
import imo_synoptic_adapter as imo

NOW=datetime(2026,10,19,14,tzinfo=timezone.utc)
URL="https://en.vedur.is/photos/sjo_atlant_spa/261019_0000_12.png"
def img():
    stream=io.BytesIO()
    Image.new("RGB",(800,480),"white").save(stream,format="PNG")
    data=stream.getvalue()
    # Add harmless ancillary payload via PNG text (still valid PNG, >20 kB).
    if len(data)<20_000:
        from PIL import PngImagePlugin
        meta=PngImagePlugin.PngInfo()
        meta.add_text("padding","x"*24000)
        stream=io.BytesIO()
        Image.new("RGB",(800,480),"white").save(stream,format="PNG",pnginfo=meta)
    return stream.getvalue()
def candidate():
    return {"url":URL,"forecast_hours":12,"run_utc":"2026-10-19T00:00+00:00",
            "calculated_valid_utc":"2026-10-19T12:00+00:00"}

class IMOOriginalMapTests(unittest.TestCase):
    def test_parse_validity_label_day_month_year(self):
        text="Reiknitími: 19.10.2026 00:00\nGildistími: 19.10.2026 12:00"
        self.assertEqual(imo.parse_printed_validity(text).isoformat(),"2026-10-19T12:00:00+00:00")
    def test_no_inference_from_run_without_printed_validity(self):
        with self.assertRaises(ValueError):
            imo.parse_printed_validity("Reiknitími: 19.10.2026 00:00")
    def test_valid_record_requires_agreeing_filename_and_printed_map(self):
        record=imo.verified_chart(img(),candidate(),NOW,
            caption_reader=lambda _:"Reiknitími 19.10.2026 00:00\nGildistími: 19.10.2026 12:00")
        self.assertEqual(record["valid_utc"],"2026-10-19T12:00+00:00")
        self.assertEqual(record["kind"],"Prognose")
        self.assertEqual(record["source_id"],"imo")
    def test_disagreeing_printed_time_never_publishes(self):
        with self.assertRaises(ValueError):
            imo.verified_chart(img(),candidate(),NOW,
                caption_reader=lambda _:"Gildistími: 19.10.2026 18:00")
    def test_foreign_server_rejected(self):
        with self.assertRaises(ValueError):
            imo.parse_filename("https://example.org/photos/sjo_atlant_spa/261019_0000_12.png")
    def test_invalid_lead_and_run_rejected(self):
        with self.assertRaises(ValueError):
            imo.parse_filename("https://en.vedur.is/photos/sjo_atlant_spa/261019_0000_10.png")
        with self.assertRaises(ValueError):
            imo.parse_filename("https://en.vedur.is/photos/sjo_atlant_spa/261019_0500_12.png")
    def test_ocr_variant_iso_date(self):
        self.assertEqual(imo.parse_printed_validity("Gildistimi 2026-10-19 12:00").hour,12)
    def test_candidate_tamper_rejected(self):
        bad=candidate();bad["forecast_hours"]=24
        with self.assertRaises(ValueError):
            imo.verified_chart(img(),bad,NOW,caption_reader=lambda _:"Gildistími: 19.10.2026 12:00")

if __name__=="__main__":unittest.main()
