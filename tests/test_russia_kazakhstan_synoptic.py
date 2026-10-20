import io,sys,unittest
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import probe_russia_kazakhstan_synoptic as mod

NOW=datetime(2026,10,20,8,tzinfo=timezone.utc)
def png():
    f=io.BytesIO()
    Image.new("RGB",(1000,650),"white").save(f,format="PNG")
    return f.getvalue()
class RussiaKazakhstanTests(unittest.TestCase):
    def test_russia_printed_full_utc(self):
        label="Гидрометцентр России АНАЛИЗ ПРИЗЕМНЫЙ от 12.10.2026 00ч ВСВ"
        value=mod.printed_russia_time(label,"00",NOW)
        self.assertEqual(value.isoformat(timespec="minutes"),"2026-10-12T00:00+00:00")
        self.assertEqual(mod.russian_freshness(value,NOW),"stale")
    def test_historical_original_four_slots_stale(self):
        for run,date in (("00","12.10.2026"),("06","26.08.2026"),
                         ("12","06.10.2026"),("18","06.10.2026")):
            with self.subTest(run=run):
                dt=mod.printed_russia_time(
                   "АНАЛИЗ ПРИЗЕМНЫЙ от "+date+" "+run+"ч ВСВ",run,NOW)
                self.assertEqual(mod.russian_freshness(dt,NOW),"stale")
    def test_missing_printed_date_and_mismatched_slot_rejected(self):
        for caption,run in (("АНАЛИЗ 00 UTC","00"),
                            ("Синоптическая карта 19.10.2026 00ч ВСВ","00"),
                            ("АНАЛИЗ ПРИЗЕМНЫЙ от 12.10.2026 06ч ВСВ","00")):
            with self.assertRaises(ValueError):
                mod.printed_russia_time(caption,run,NOW)
    def test_kaz_html_icons_are_not_synoptic_source(self):
        html='''<img src="/img/logo.png"><script src="/js/app.js"></script>
        <div>Loading synoptic maps… Date UTC time Source file:</div>'''
        result=mod.inspect_kaz_html(html)
        self.assertEqual(result["same_host_image_reference_count"],1)
        self.assertFalse(result["chart_image_utc_verified"])
        self.assertFalse(result["image_reuse_permitted"])
        self.assertEqual(result["same_host_script_reference_count"],1)
    def test_kaz_external_or_http_script_is_excluded(self):
        html='<script src="https://bad.example/a.js"></script><script src="http://www.kazhydromet.kz/attack.js"></script>'
        result=mod.inspect_kaz_html(html)
        self.assertEqual(result["script_urls"],[])
    def test_both_countries_fail_closed_even_if_russian_dates_are_valid(self):
        labels=list(mod.RUSSIAN_ORIGINALS)
        idx=0
        def get_image(_url):return png()
        def read_image(_data):
            nonlocal idx
            hour=labels[idx];idx+=1
            return ("АНАЛИЗ ПРИЗЕМНЫЙ от 20.10.2026 "+hour+"ч ВСВ",[1000,650])
        result=mod.inspect(NOW,get_image,read_image,kaz_fetch=lambda url:"<html></html>")
        self.assertEqual(len(result["russia"]["records"]),4)
        self.assertFalse(result["ready_for_automatic_image_reuse"])
        self.assertTrue(result["no_images_persisted"])
        self.assertFalse(result["kazakhstan"]["chart_image_utc_verified"])
        self.assertTrue(all(not rec["image_reuse_permitted"] for rec in result["russia"]["records"]))
    def test_kaz_url_is_not_a_run_validity_time(self):
        html='<img src="/storage/maps/abc_2026102006.png"><div>Date UTC</div>'
        result=mod.inspect_kaz_html(html)
        self.assertFalse(result["chart_image_utc_verified"])
if __name__=="__main__":unittest.main()
