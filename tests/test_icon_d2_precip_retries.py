"""Regression tests for robust DWD ICON-D2 precipitation downloads."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from http.client import RemoteDisconnected
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_icon_d2_precip_film import retrieve

TEST_URL = "https://opendata.dwd.de/weather/nwp/icon-d2/grib/03/rain_gsp/test.grib2.bz2"
PAYLOAD = b"BZh" + bytes(180)


class DownloadRetryTests(unittest.TestCase):
    def test_remote_disconnected_is_retried(self):
        with patch("build_icon_d2_precip_film.urlopen",
                   side_effect=[RemoteDisconnected("closed"), io.BytesIO(PAYLOAD)]) as fetch, \
             patch("build_icon_d2_precip_film.time.sleep") as sleep:
            self.assertEqual(retrieve(TEST_URL, retries=3), PAYLOAD)
            self.assertEqual(fetch.call_count, 2)
            sleep.assert_called_once_with(8)

    def test_404_does_not_retry(self):
        failure = HTTPError(TEST_URL, 404, "Not Found", {}, None)
        with patch("build_icon_d2_precip_film.urlopen", side_effect=failure) as fetch, \
             patch("build_icon_d2_precip_film.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "dauerhaft"):
                retrieve(TEST_URL)
            fetch.assert_called_once()
            sleep.assert_not_called()

    def test_exhaustion_reports_filename(self):
        with patch("build_icon_d2_precip_film.urlopen",
                   side_effect=RemoteDisconnected("closed")) as fetch, \
             patch("build_icon_d2_precip_film.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "nach 3 Versuchen"):
                retrieve(TEST_URL, retries=3)
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
