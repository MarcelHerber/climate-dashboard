"""Offline checks for HYRAS + ensemble precipitation output."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_state_monthly_precip_outlook as precip
import build_state_monthly_ensemble_outlook as ensemble


class StateMonthlyPrecipTests(unittest.TestCase):
    def test_precip_rate_limit_uses_pacing_and_minute_cooldown(self):
        limited = Mock(status_code=429, text="Minutely API request limit exceeded")
        ok = Mock(status_code=200)
        ok.json.return_value = {"success": True}
        with (patch.object(ensemble.requests, "get", side_effect=[limited, ok]),
              patch.object(ensemble, "reserve_sunshine_request") as pace,
              patch.object(ensemble, "cooldown_sunshine_requests") as cooldown):
            self.assertEqual(ensemble.fetch_json(ensemble.ENSEMBLE_API, params={"hourly":"precipitation"}, retries=2), {"success":True})
            self.assertEqual(pace.call_count, 2)
            cooldown.assert_called_once()

    def model(self, run="2026-11-02T12:00:00Z"):
        return {"label":"GEFS", "api_model":"ncep_gefs_seamless", "run":run,
                "member_count":2, "regions":{r:{"dates":["2026-11-03","2026-11-04","2026-11-05"],
                    "member_keys":["precipitation_member01","precipitation_member02"],
                    "members":{"precipitation_member01":[3.,2.,1.],"precipitation_member02":[5.,4.,3.]},
                    "support_points":8} for r in precip.REGION_ORDER}}

    def test_retained_members_reanchor_on_new_observation(self):
        obs=self.make_observed()
        obs["dates"].append("2026-11-03"); obs["data_through"]="2026-11-03"
        for region in obs["regions"].values(): region["daily"].append(10)
        now=datetime(2026,11,4,0,tzinfo=timezone.utc)
        payload, cache=precip.build_resilient_payload(obs, {}, {"gefs":self.model()}, None, {"gefs":"HTTP 429"}, now)
        curve=payload["regions"]["Hessen"]["models"]["gefs"]
        self.assertEqual(curve["stats"]["mean"][:5], [None,None,None,15.,17.])
        self.assertEqual(curve["run"],"2026-11-02T12:00:00Z")
        self.assertTrue(curve["retained"])
        self.assertIn("gefs", cache)

    def test_cache_expiry_and_forecast_gap_do_not_create_data(self):
        obs=self.make_observed()
        now=datetime(2026,11,5,0,tzinfo=timezone.utc)
        for m in (self.model(), self.model("2026-11-04T12:00:00Z")):
            if m["run"].startswith("2026-11-04"):
                m["regions"]["Hessen"]["members"]={k:[None,4,5] for k in m["regions"]["Hessen"]["member_keys"]}
            payload, cache=precip.build_resilient_payload(obs, {}, {"gefs":m}, None, {}, now)
            self.assertEqual(payload["models_order"], [])

    def test_legacy_summary_only_with_identical_observed_anchor(self):
        obs=self.make_observed(); previous=precip.build_payload(obs,{"gefs":self.model()}, {})
        now=datetime(2026,11,3,0,tzinfo=timezone.utc)
        payload,_=precip.build_resilient_payload(obs,{}, {},previous,{},now)
        self.assertTrue(payload["regions"]["Hessen"]["models"]["gefs"]["retained"])
        obs["regions"]["Hessen"]["daily"][0]=8
        payload,_=precip.build_resilient_payload(obs,{}, {},previous,{},now)
        self.assertEqual(payload["models_order"],[])

    def test_newer_cached_run_not_replaced_by_older_model(self):
        obs=self.make_observed(); now=datetime(2026,11,3,0,tzinfo=timezone.utc)
        payload,cache=precip.build_resilient_payload(obs,{"gefs":self.model("2026-11-02T00:00:00Z")},{"gefs":self.model()},None,{},now)
        self.assertTrue(payload["regions"]["Hessen"]["models"]["gefs"]["retained"])
        self.assertEqual(cache["gefs"]["run"],"2026-11-02T12:00:00Z")

    def test_observation_regression_rejected(self):
        obs=self.make_observed(); previous=precip.build_payload(obs,{}, {})
        obs["dates"].pop(); obs["data_through"]=obs["dates"][-1]
        for region in obs["regions"].values(): region["daily"].pop()
        with self.assertRaises(ValueError):
            precip.build_resilient_payload(obs,{}, {},previous,{},datetime(2026,11,3,tzinfo=timezone.utc))

    def test_corrupt_legacy_forecast_rejected(self):
        obs=self.make_observed(); previous=precip.build_payload(obs,{"gefs":self.model()}, {})
        previous["regions"]["Hessen"]["models"]["gefs"]["stats"]["p95"][3]=None
        payload,_=precip.build_resilient_payload(obs,{}, {},previous,{},datetime(2026,11,3,tzinfo=timezone.utc))
        self.assertEqual(payload["models_order"],[])

    def test_final_observed_month_needs_no_model(self):
        obs=self.make_observed()
        obs["dates"]=[f"2026-11-{d:02}" for d in range(1,31)]
        obs["data_through"]=obs["dates"][-1]
        for region in obs["regions"].values(): region["daily"]=[1.]*30
        payload,_=precip.build_resilient_payload(obs,{}, {},None,{},datetime(2026,12,1,tzinfo=timezone.utc))
        self.assertTrue(payload["observation_complete"])
        self.assertEqual(payload["regions"]["Deutschland"]["observed_current"],30.)

    def test_previous_calendar_month_cannot_replace_newer_publication(self):
        obs=self.make_observed()
        previous={"parameter":"precipitation","observation_data_through":"2026-12-01"}
        with self.assertRaises(ValueError):
            precip.build_resilient_payload(obs,{}, {},previous,{},datetime(2026,12,2,tzinfo=timezone.utc))
    def make_observed(self):
        return {
            "schema_version": 1, "forecast": False, "unit": "mm",
            "month": "2026-11", "data_through": "2026-11-02",
            "dates": ["2026-11-01", "2026-11-02"],
            "regions": {r: {"daily": [1.5, 0.5]} for r in precip.REGION_ORDER},
        }

    def test_accumulates_once_and_preserves_future_gap(self):
        doc = self.make_observed()
        model = {"gefs": {
            "label": "GEFS", "api_model": "ncep_gefs_seamless",
            "member_count": 1, "run": None,
            "regions": {r: {
                "dates": ["2026-11-03", "2026-11-04"],
                "member_keys": ["precipitation_sum_member01"],
                "members": {"precipitation_sum_member01": [3.0, 2.0]},
                "support_points": 8,
            } for r in precip.REGION_ORDER},
        }}
        out = precip.build_payload(doc, model, {})
        self.assertEqual(out["parameter"], "precipitation")
        self.assertEqual(out["regions"]["Hessen"]["observed_running"][:4], [1.5, 2.0, None, None])
        self.assertEqual(out["regions"]["Hessen"]["models"]["gefs"]["control"][:5], [None, None, 5.0, 7.0, None])
        self.assertFalse(out["climatology_available"])

    def test_rejects_missing_observed_day(self):
        doc = self.make_observed()
        doc["dates"] = ["2026-11-01", "2026-11-03"]
        doc["data_through"] = "2026-11-03"
        with self.assertRaises(ValueError):
            precip.validate_observed(doc)

    def test_rejects_missing_region_or_negative(self):
        doc = self.make_observed()
        del doc["regions"]["Hessen"]
        with self.assertRaises(ValueError):
            precip.validate_observed(doc)
        doc = self.make_observed()
        doc["regions"]["Hessen"]["daily"][0] = -0.5
        with self.assertRaises(ValueError):
            precip.validate_observed(doc)


if __name__ == "__main__":
    unittest.main()
