"""Offline tests for DUETT + hourly Open-Meteo sunshine ensemble outlook."""
from __future__ import annotations
import sys
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_state_monthly_sun_outlook as sun
import build_state_monthly_ensemble_outlook as ensemble


class SunOutlookTests(unittest.TestCase):
    def observations(self):
        return {
            "schema_version": 1,
            "product": "state_monthly_duett_sunshine_observations",
            "forecast": False,
            "unit": "h", "month": "2026-11", "data_through": "2026-11-02",
            "dates": ["2026-11-01", "2026-11-02"],
            "regions": {r: {"daily": [6.5, 3.5]} for r in sun.REGION_ORDER},
        }

    def test_daily_handover(self):
        doc=self.observations()
        m={"gefs": {
            "label": "GFS/GEFS", "run": None, "api_model":"ncep_gefs_seamless",
            "regions": {r: {
                "dates":["2026-11-03", "2026-11-04"],
                "member_keys":["sunshine_duration_member01"],
                "members":{"sunshine_duration_member01":[2.5, 5.0]},
                "support_points":5,
            } for r in sun.REGION_ORDER},
        }}
        out=sun.build_payload(doc,m)
        self.assertEqual(out["unit"],"h")
        self.assertEqual(out["regions"]["Hessen"]["observed_running"][:3],[6.5,10,None])
        self.assertEqual(out["regions"]["Hessen"]["models"]["gefs"]["control"][:5],[None,None,12.5,17.5,None])
        self.assertFalse(out["climatology_available"])

    def test_rejects_incomplete_or_over24h_day(self):
        doc=self.observations()
        doc["regions"]["Deutschland"]["daily"][0]=25
        with self.assertRaises(ValueError):
            sun.validate_observations(doc)
        doc=self.observations()
        doc["dates"]=["2026-11-01","2026-11-03"]
        doc["data_through"]="2026-11-03"
        with self.assertRaises(ValueError):
            sun.validate_observations(doc)

    def test_rate_limit_does_not_multiply_calls_by_splitting(self):
        refs = [ensemble.LocationRef("Hessen", 0.25, 50.1, 8.7) for _ in range(4)]
        with patch.object(ensemble, "fetch_json", side_effect=RuntimeError("HTTP 429: rate limit")) as fetch:
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                ensemble.request_model_chunk(
                    "gefs", refs, variable="sunshine_duration", time_resolution="hourly",
                )
        self.assertEqual(fetch.call_count, 1)

    def test_sunshine_http_429_waits_for_provider_cooldown(self):
        limited = Mock(status_code=429, text="Minutely API request limit exceeded")
        ok = Mock(status_code=200)
        ok.json.return_value = {"success": True}
        with (
            patch.object(ensemble.requests, "get", side_effect=[limited, ok]) as request,
            patch.object(ensemble, "reserve_sunshine_request") as pace,
            patch.object(ensemble, "cooldown_sunshine_requests") as cooldown,
        ):
            result = ensemble.fetch_json(
                ensemble.ENSEMBLE_API,
                params={"hourly": "sunshine_duration"},
                retries=2,
            )
        self.assertEqual(result, {"success": True})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(pace.call_count, 2)
        cooldown.assert_called_once()



if __name__=="__main__":
    unittest.main()
