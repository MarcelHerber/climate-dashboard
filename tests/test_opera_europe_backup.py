"""Offline checks: OPERA fallback must use only official source URLs and real COGs."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_opera_europe_radar as opera


class FakeResponse:
    def __init__(self, code, payload=None):
        self.status_code = code
        self.payload = payload or {}
        self.content = b"real-image-data" if code == 200 else b""
    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))
    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append(url)
        return self.replies[url]


class OperaBackupTests(unittest.TestCase):
    def test_fallback_s3_uses_official_backup_bucket(self):
        instant = datetime(2026, 11, 13, 6, 20, tzinfo=timezone.utc)
        primary = opera.s3url(instant, "dbzh", opera.S3_ENDPOINTS[0])
        backup = opera.s3url(instant, "dbzh", opera.S3_ENDPOINTS[1])
        self.assertTrue(primary.endswith("/2026/11/13/OPERA/COMP/OPERA@20261113T0620@0@DBZH.tiff"))
        self.assertIn("openradar-24h-backup", backup)

    def test_verified_cog_falls_back_after_primary_404(self):
        instant = datetime(2026, 11, 13, 6, 20, tzinfo=timezone.utc)
        primary = opera.s3url(instant, "dbzh", opera.S3_ENDPOINTS[0])
        backup = opera.s3url(instant, "dbzh", opera.S3_ENDPOINTS[1])
        session = FakeSession({primary: FakeResponse(404), backup: FakeResponse(200)})
        valid = (np.ones((3, 3), dtype=np.uint8), {"coverage": .5})
        with patch.object(opera, "decode_geotiff", return_value=valid) as decode:
            out = opera.load_verified_cog(session, instant, "dbzh")
        self.assertIsNotNone(out)
        self.assertEqual(session.calls, [primary, backup])
        decode.assert_called_once_with(b"real-image-data", "dbzh", instant)

    def test_no_fake_radar_frame_when_both_stores_missing(self):
        instant = datetime(2026, 11, 13, 6, 20, tzinfo=timezone.utc)
        session = FakeSession({
            opera.s3url(instant, "rate", base): FakeResponse(404)
            for base in opera.S3_ENDPOINTS
        })
        self.assertIsNone(opera.load_verified_cog(session, instant, "rate"))

    def test_backup_api_used_when_primary_unavailable(self):
        now = datetime(2026, 11, 13, 6, 24, tzinfo=timezone.utc)
        times = [(now - timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z")
                 for i in range(9)]
        session = FakeSession({
            opera.API_ENDPOINTS[0]: FakeResponse(503),
            opera.API_ENDPOINTS[1]: FakeResponse(200, {
                "domain": {"axes": {"t": {"values": times}}}
            })
        })
        records = opera.discover(session, "dbzh", now, 4)
        self.assertEqual(records[-1], now)
        self.assertEqual(session.calls, list(opera.API_ENDPOINTS))


if __name__ == "__main__":
    unittest.main()
