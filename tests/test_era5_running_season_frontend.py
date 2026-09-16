from copy import deepcopy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_expose_synthesizes_autumn_and_removes_stale_summer():
    from expose_era5_running_month import expose_running

    main = {
        "periods": {
            "latest_month": {"id": "latest_month"},
            "running_summer": {"id": "running_summer", "label": "alter Sommer"},
        }
    }
    running = {
        "ready": True,
        "data_through": "2026-09-10",
        "preliminary": True,
        "periods": {
            "running_month": {
                "id": "running_month",
                "label": "September 2026 bis 10.09.",
                "date_start": "2026-09-01",
                "date_end": "2026-09-10",
                "temperature": {"absolute": {"file": "month.png"}},
                "precipitation": {"absolute": {"file": "month-p.png"}},
            }
        },
    }

    out = expose_running(deepcopy(main), running)
    assert "running_summer" not in out["periods"]
    assert out["periods"]["running_autumn"]["id"] == "running_autumn"
    assert out["periods"]["running_autumn"]["label"] == "Herbst 2026 bis 10.09."
    assert out["periods"]["running_autumn"]["temperature"]["absolute"]["file"] == "month.png"
    assert out["running"]["season_id"] == "running_autumn"


def test_v1_frontend_is_migrated_to_dynamic_running_season():
    from patch_era5_running_frontend import patch_text

    text = '''<script>
// ERA5_TP_ALL_MONTHS_FRONTEND_V1
// ERA5_RUNNING_FRONTEND_V1
function era5EuropeUpdatePeriodOptions(){
  const runningSummer=era5EuropeIndex?.periods?.running_summer;
  if(runningSummer) console.log(runningSummer);
}
function era5EuropePeriodIsHistoricalOnly(period){return false;}
</script>'''
    patched = patch_text(text)
    assert "// ERA5_RUNNING_FRONTEND_V2" in patched
    assert "// ERA5_RUNNING_FRONTEND_V1" not in patched
    assert "running_autumn" in patched
    assert "running_winter" in patched
    assert "runningSummer" not in patched


def test_first_season_month_is_added_without_cds_or_rerender(tmp_path):
    from add_era5_running_season import add_running_season

    index = tmp_path / "index.json"
    index.write_text(json.dumps({
        "ready": True,
        "data_through": "2026-09-10",
        "periods": {
            "running_month": {
                "id": "running_month",
                "label": "September 2026 bis 10.09.",
                "date_start": "2026-09-01",
                "date_end": "2026-09-10",
                "temperature": {"absolute": {"file": "month.png"}},
                "precipitation": {"absolute": {"file": "month-p.png"}},
            }
        }
    }), encoding="utf-8")

    class NoCdsCore:
        def __getattr__(self, name):
            raise AssertionError(f"CDS/rendering darf im ersten Saisonmonat nicht aufgerufen werden: {name}")

    add_running_season(NoCdsCore(), index_path=index, cache_dir=tmp_path / "cache")
    out = json.loads(index.read_text(encoding="utf-8"))
    autumn = out["periods"]["running_autumn"]
    assert autumn["label"] == "Herbst 2026 bis 10.09."
    assert autumn["date_start"] == "2026-09-01"
    assert autumn["temperature"]["absolute"]["file"] == "month.png"
