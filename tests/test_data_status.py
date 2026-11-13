import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_data_status as status


class DataStatusTests(unittest.TestCase):
    def test_date_and_month_parsing(self):
        self.assertEqual(status.valid_date("2026-09"), date(2026, 9, 1))
        self.assertEqual(status.valid_date("2026-10-13"), date(2026, 10, 13))
        self.assertIsNone(status.valid_date("not-a-date"))

    def test_recent_and_delayed_not_confused(self):
        today = datetime.now(timezone.utc).date()
        recent = status.result("a", "A", "T", (today-timedelta(days=1)).isoformat(),
                               None, "tests", allowed_delay=5)
        late = status.result("b", "B", "T", (today-timedelta(days=20)).isoformat(),
                             None, "tests", allowed_delay=5)
        self.assertEqual(recent["status"], "current")
        self.assertEqual(late["status"], "delayed")
        self.assertEqual(status.result("c", "C", "T", None, None, "none")["status"], "unknown")

    def test_model_runs_are_hourly_not_day_based(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=29)).isoformat().replace("+00:00", "Z")
        recent = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        icon = lambda run: {
            "schema": 2, "run_utc": run, "generated_utc": now.isoformat(),
            "duration_h": 24, "grid": {"rows": 100},
            "periods": [{"start_h": h, "end_h": h+24} for h in range(0, 120, 24)]
        }
        mos = lambda run: {
            "product": "DWD MOSMIX-L", "issue_time": run,
            "generated_at": now.isoformat(), "station_count": 2818,
            "timesteps": list(range(40))
        }
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(status, "ROOT", Path(temp)):
                older = {r["id"]: r for r in status.build({
                    "mosmix": mos(old), "mosmix_quality": {"quality": "passed", "issue_time": old},
                    "icon": icon(old)})["datasets"]}
                newer = {r["id"]: r for r in status.build({
                    "mosmix": mos(recent), "mosmix_quality": {"quality": "passed", "issue_time": recent},
                    "icon": icon(recent)})["datasets"]}
        self.assertEqual(older["mosmix"]["status"], "delayed")
        self.assertEqual(older["icon_hazards"]["status"], "delayed")
        self.assertEqual(newer["mosmix"]["status"], "current")
        self.assertEqual(newer["icon_hazards"]["status"], "current")
        self.assertEqual(older["icon_hazards"]["cadence"], "hourly")

    def test_europe_tmax_old_icon_cycle_is_delayed_even_with_five_good_days(self):
        now = datetime.now(timezone.utc)
        days = [
            {"date": (now.date()+timedelta(days=i)).isoformat(),
             "coverage": .85, "icon_png": "verified.png", "icon_raw_png": "verified-raw.png",
             "stations": [{"city": str(n), "tmax_c": 12.0, "tmin_c": 5.0}
                          for n in range(31)]}
            for i in range(5)
        ]
        def archive(hours):
            return {"schema": 2, "icon_cycle":
                    (now-timedelta(hours=hours)).strftime("%Y%m%d%H"),
                    "built_utc": now.isoformat(),
                    "stations_catalog_count": 4400, "days": days}
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(status, "ROOT", Path(temp)):
                items = {x["id"]: x for x in status.build({
                    "europe_tmax": archive(35), "europe_tmin": archive(2)})["datasets"]}
        self.assertEqual(items["europe_tmax"]["status"], "delayed")
        self.assertEqual(items["europe_tmin"]["status"], "current")
        self.assertEqual(items["europe_tmax"]["cadence"], "hourly")
        self.assertIn("T", items["europe_tmax"]["latest"])

    def test_snow_station_gaps_are_visible_without_false_global_failure(self):
        recent = (datetime.now(timezone.utc).date()-timedelta(days=2)).isoformat()
        def snow(available):
            return {"ready": True, "data_through": recent,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "stations_with_current_season_values": available,
                    "profile_station_count": 299}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/"station_snow_height_current_index.json").write_text(
                json.dumps(snow(268)), encoding="utf-8")
            with patch.object(status, "ROOT", folder):
                good = next(x for x in status.build()["datasets"] if x["id"] == "snow")
            (folder/"station_snow_height_current_index.json").write_text(
                json.dumps(snow(99)), encoding="utf-8")
            with patch.object(status, "ROOT", folder):
                poor = next(x for x in status.build()["datasets"] if x["id"] == "snow")
        self.assertEqual(good["status"], "current")
        self.assertIn("268/299", good["coverage"])
        self.assertIn("31 ohne Saisonmessung", good["coverage"])
        self.assertEqual(poor["status"], "incomplete")

    def test_synoptic_status_reports_partial_source_outage(self):
        now = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/"data"/"synoptic_charts"
            folder.mkdir(parents=True)
            (folder/"index.json").write_text(json.dumps({
                "ready": True, "generated_utc": now,
                "charts": [{"source_id": "dwd", "valid_utc": now}],
                "source_status": {
                    "dwd": {"state": "available", "charts": 1},
                    "noaa_24": {"state": "unavailable",
                                "reason": "No plausible dated chart URL found"}
                }
            }), encoding="utf-8")
            with patch.object(status, "ROOT", Path(temp)):
                item = next(x for x in status.build()["datasets"]
                            if x["id"] == "synoptic_original")
        self.assertEqual(item["status"], "incomplete")
        self.assertIn("1/2 geprüfte Quellen erreichbar", item["coverage"])
        self.assertIn("noaa_24", item["note"])


    def test_live_observations_use_hourly_freshness(self):
        now = datetime.now(timezone.utc)
        recent = status.result("live", "SYNOP", "Stationen",
                               (now - timedelta(minutes=15)).isoformat(), None,
                               "measured", cadence="hourly", allowed_delay=3)
        late = status.result("live", "SYNOP", "Stationen",
                             (now - timedelta(hours=10)).isoformat(), None,
                             "measured", cadence="hourly", allowed_delay=3)
        self.assertEqual(recent["status"], "current")
        self.assertEqual(late["status"], "delayed")
        self.assertGreaterEqual(late["lag"], 9)

    def test_known_missing_backfill_is_visible(self):
        today = datetime.now(timezone.utc).date()
        incomplete = status.result("a", "A", "T", today.isoformat(), None,
                                   "0/30 reference years", incomplete=True)
        self.assertEqual(incomplete["status"], "incomplete")

    def test_derived_archive_status(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "update_status.json").write_text(json.dumps({
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "monthly": {"latest_complete_month": today[:7], "area_count": 17, "records": 100},
                "daily": {"latest_date": today, "records": 10, "latest_station_count": 4}
            }), encoding="utf-8")
            (root / "era5_stratosphere").mkdir()
            (root / "era5_stratosphere/index.json").write_text(json.dumps({
                "ready": True, "data_through": today, "reference_years_completed": 0
            }), encoding="utf-8")
            with patch.object(status, "ROOT", root):
                archive = status.build()
            rows = {row["id"]: row for row in archive["datasets"]}
            self.assertEqual(rows["dwd_monthly"]["status"], "current")
            self.assertEqual(rows["era5_strat"]["status"], "incomplete")
            self.assertEqual(rows["era5_strat_reference"]["status"], "incomplete")
            self.assertIn("Temperatur: 0/366 Klimatologietage",
                          rows["era5_strat_reference"]["coverage"])
            self.assertIn("Zonalwind: 0/366", rows["era5_strat_reference"]["coverage"])


    def test_sst_region_completeness_excludes_partial_days(self):
        today = datetime.now(timezone.utc).date()
        full = {"absolute": "maps/a.webp", "anomaly": "maps/b.webp"}
        fixture = {"dates": {
            (today - timedelta(days=2)).isoformat(): {"regions": {"europe": full, "mediterranean": full}},
            (today - timedelta(days=1)).isoformat(): {"regions": {"europe": full}},
            today.isoformat(): {"regions": {"europe": full, "mediterranean": full}},
        }}
        latest, count, recent = status.sst_region_status(fixture, ("europe", "mediterranean"))
        self.assertEqual(latest, today.isoformat())
        self.assertEqual(count, 2)
        self.assertEqual(recent, 2)

    def test_era5_stratosphere_climatology_days_count_only_real_full_samples(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "era5_stratosphere"
            path.mkdir()
            (path / "index.json").write_text(json.dumps({
                "ready": True, "data_through": today,
                "reference_years_completed": 0,
                "reference_wind_years_completed": 0,
                "reference": {
                    **{f"tcap_{lev}": {"01-01": {"mean": -55}}
                       for lev in (10,30,50,100)},
                    **{f"u60_{lev}": {"01-01": {"mean": 20}}
                       for lev in (10,30,50,100)}
                }
            }), encoding="utf-8")
            with patch.object(status, "ROOT", root):
                entry = next(x for x in status.build()["datasets"]
                             if x["id"] == "era5_strat")
            self.assertEqual(entry["status"], "incomplete")
            with patch.object(status, "ROOT", root):
                reference = next(x for x in status.build()["datasets"]
                                 if x["id"] == "era5_strat_reference")
            self.assertEqual(reference["status"], "incomplete")
            self.assertIn("Temperatur: 1/366", reference["coverage"])
            self.assertIn("Zonalwind: 1/366", reference["coverage"])

    def test_current_stratosphere_day_stays_current_despite_missing_climatology(self):
        today = datetime.now(timezone.utc).date()
        latest = (today - timedelta(days=6)).isoformat()
        day = {"date": latest}
        day.update({f"u60_{hpa}": 12.0 for hpa in (10,30,50,100)})
        day.update({f"tcap_{hpa}": -55.0 for hpa in (10,30,50,100)})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "era5_stratosphere"
            folder.mkdir()
            (folder / "index.json").write_text(json.dumps({
                "ready": True, "data_through": latest,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "reference_years_completed": 30,
                "reference_wind_years_completed": 15,
                "reference": {}, "series": [day]
            }), encoding="utf-8")
            with patch.object(status, "ROOT", root):
                rows = {row["id"]: row for row in status.build()["datasets"]}
        self.assertEqual(rows["era5_strat"]["status"], "current")
        self.assertEqual(rows["era5_strat_reference"]["status"], "incomplete")
        self.assertIn("4/4 Windhöhen", rows["era5_strat"]["coverage"])
        self.assertIn("4/4 Temperaturhöhen", rows["era5_strat"]["coverage"])
        self.assertIn("15/30", rows["era5_strat_reference"]["note"])


    def test_historical_stratosphere_wind_progress_counts_only_verified_days(self):
        latest = (datetime.now(timezone.utc).date()-timedelta(days=6)).isoformat()
        all_winds = {f"u60_{level}": 18.0 for level in (10,30,50,100)}
        latest_values = {"date": latest, **all_winds,
                         **{f"tcap_{level}": -55.0 for level in (10,30,50,100)}}
        rows = [
            {"date": "1991-01-01", **all_winds},
            {"date": "1991-01-02", "u60_10": 19.0},  # incomplete
            {"date": "1992-02-29", **all_winds},
            latest_values,
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "era5_stratosphere"
            folder.mkdir()
            (folder/"index.json").write_text(json.dumps({
                "ready": True, "data_through": latest,
                "reference_years_completed": 30,
                "reference_wind_years_completed": 0,
                "reference": {}, "series": rows
            }), encoding="utf-8")
            with patch.object(status, "ROOT", root):
                results = {row["id"]: row for row in status.build()["datasets"]}
        self.assertEqual(results["era5_strat"]["status"], "current")
        self.assertEqual(results["era5_strat_reference"]["status"], "incomplete")
        self.assertIn("Windtageswerte: 2/10958", results["era5_strat_reference"]["coverage"])
        self.assertIn("Zonalwind: 0/366", results["era5_strat_reference"]["coverage"])

    def test_forecasts_do_not_use_valid_end_as_last_observation(self):
        now = datetime.now(timezone.utc)
        run_date = now.date().isoformat()
        run_utc = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        forecast = {
            "mosmix": {"product": "DWD MOSMIX-L", "issue_time": run_utc,
                       "generated_at": now.isoformat(), "station_count": 120,
                       "timesteps": [run_date] * 60},
            "mosmix_quality": {"quality": "passed", "issue_time": run_utc},
            "icon": {"schema": 1, "run_utc": run_utc,
                     "generated_utc": now.isoformat(), "grid": {"rows": 90},
                     "periods": [{"start_h": i, "end_h": i + 24}
                                 for i in range(0,120,24)]}
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(status, "ROOT", Path(tmp)):
                rows = {r["id"]: r for r in status.build(forecast)["datasets"]}
        self.assertEqual(rows["mosmix"]["status"], "current")
        self.assertEqual(rows["icon_hazards"]["status"], "current")
        self.assertEqual(rows["ensembles"]["status"], "unknown")

    def test_real_tmin_tmax_manifests_and_missing_city(self):
        from datetime import datetime
        now = datetime.now(timezone.utc)
        cycle = now.strftime("%Y%m%d%H")
        days = []
        for i in range(5):
            label = (now.date() + timedelta(days=i)).isoformat()
            points = [{"city": str(k), "tmax_c": float(k), "tmin_c": float(k)}
                      for k in range(29)]
            points.append({"city": "Missing", "tmax_c": None, "tmin_c": None})
            days.append({"date": label, "coverage": .84, "icon_png": label + ".png",
                         "icon_raw_png": label + "_raw.png", "stations": points})
        archive = {"schema": 2, "icon_cycle": cycle, "built_utc": now.isoformat(),
                   "stations_catalog_count": 4400, "days": days}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(status, "ROOT", Path(tmp)):
                rows = {x["id"]: x for x in status.build({
                    "europe_tmax": archive, "europe_tmin": archive})["datasets"]}
        for mode in ("europe_tmax", "europe_tmin"):
            self.assertEqual(rows[mode]["status"], "current")
            self.assertIn("29–29/31", rows[mode]["coverage"])
            self.assertIn("Missing", rows[mode]["note"])

    def test_opera_requires_real_verified_frames_not_advertised_timestamps(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
        old = (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
        remote = {"opera": {"updated_utc": now.isoformat(), "products": {
            "dbzh": {"frames": [{"utc": recent}] * 4},
            "rate": {"frames": [{"utc": old}] * 8},
        }}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(status, "ROOT", Path(tmp)):
                rows = {x["id"]: x for x in status.build(remote)["datasets"]}
                missing = {x["id"]: x for x in status.build({})["datasets"]}
        self.assertEqual(rows["opera_dbzh"]["status"], "current")
        self.assertEqual(rows["opera_rate"]["status"], "delayed")
        self.assertIn("4 überprüfte", rows["opera_dbzh"]["coverage"])
        self.assertEqual(missing["opera_dbzh"]["status"], "unknown")
        self.assertEqual(missing["opera_rate"]["status"], "unknown")

    def test_chart_future_validity_is_not_a_future_data_date(self):
        today = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data/synoptic_charts"
            folder.mkdir(parents=True)
            (folder / "index.json").write_text(json.dumps({
                "ready": True, "generated_utc": today.isoformat(),
                "charts": [{"valid_utc": (today + timedelta(days=3)).isoformat(),
                            "source_id": "dwd"}]}), encoding="utf-8")
            with patch.object(status, "ROOT", root):
                rows = {r["id"]: r for r in status.build()["datasets"]}
        self.assertEqual(rows["synoptic_original"]["status"], "current")

    def test_noaa_index_freshness_uses_older_subproduct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "climate_indices").mkdir()
            today = datetime.now(timezone.utc).date()
            p = {
                "ready": True, "generated_at": datetime.now(timezone.utc).isoformat(),
                "teleconnections": {
                    "nao": {"latest_date": today.isoformat(), "daily": [[str(i), 0] for i in range(2100)]},
                    "ao": {"latest_date": (today-timedelta(days=20)).isoformat(), "daily": [[str(i), 0] for i in range(2100)]}
                }
            }
            (root / "climate_indices/index.json").write_text(json.dumps(p), encoding="utf-8")
            with patch.object(status, "ROOT", root):
                rows = {r["id"]: r for r in status.build()["datasets"]}
            self.assertEqual(rows["nao"]["status"], "current")
            self.assertEqual(rows["ao"]["status"], "delayed")
            self.assertEqual(rows["enso"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
