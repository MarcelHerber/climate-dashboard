import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))


def test_reference_month_defaults_to_calendar_month():
    from era5_running_freshness_guard import select_reference_month
    assert select_reference_month(date(2026, 9, 14), None) == (2026, 9, '2026-09')


def test_reference_month_allows_manual_override():
    from era5_running_freshness_guard import select_reference_month
    assert select_reference_month(date(2026, 9, 14), '08') == (2026, 8, '2026-08')


def test_validate_index_rejects_stale_data_through(tmp_path):
    from era5_running_freshness_guard import validate_index_data_through
    index = tmp_path / 'index.json'
    index.write_text(json.dumps({'ready': True, 'data_through': '2026-08-25'}), encoding='utf-8')
    try:
        validate_index_data_through(index, '2026-09-08')
    except RuntimeError as exc:
        assert '2026-08-25' in str(exc)
        assert '2026-09-08' in str(exc)
    else:
        raise AssertionError('staler Datenstand wurde akzeptiert')


def test_validate_index_accepts_exact_probe_date(tmp_path):
    from era5_running_freshness_guard import validate_index_data_through
    index = tmp_path / 'index.json'
    index.write_text(json.dumps({'ready': True, 'data_through': '2026-09-08'}), encoding='utf-8')
    assert validate_index_data_through(index, '2026-09-08') == '2026-09-08'


def test_backfill_plan_requires_full_completed_month():
    from era5_running_freshness_guard import validate_backfill_end_day
    try:
        validate_backfill_end_day(2026, 8, 25, date(2026, 9, 8))
    except RuntimeError as exc:
        assert '31' in str(exc)
        assert '25' in str(exc)
    else:
        raise AssertionError('unvollständiger abgeschlossener Monat wurde akzeptiert')


def test_backfill_plan_requires_exact_current_availability():
    from era5_running_freshness_guard import validate_backfill_end_day
    try:
        validate_backfill_end_day(2026, 9, 5, date(2026, 9, 8))
    except RuntimeError as exc:
        assert '8' in str(exc)
        assert '5' in str(exc)
    else:
        raise AssertionError('veralteter laufender Monat wurde akzeptiert')


def test_backfill_plan_accepts_fresh_current_availability():
    from era5_running_freshness_guard import validate_backfill_end_day
    assert validate_backfill_end_day(2026, 9, 8, date(2026, 9, 8)) == 8


def test_daily_workflow_requires_exact_reference_cache_and_probe_validation():
    workflow = (ROOT / '.github/workflows/update-era5-land-running.yml').read_text(encoding='utf-8')
    assert 'Frischen gemeinsamen ERA5-Land-T/P-Tag bestimmen' in workflow
    assert 'era5-land-running-0p1-reference-v1-${{ steps.probe.outputs.month_key }}' in workflow
    assert 'fail-on-cache-miss: true' in workflow
    assert '--expected "$EXPECTED_DATA_THROUGH"' in workflow
    assert 'push:' not in workflow.split('jobs:', 1)[0]


def test_reference_workflow_prebuilds_calendar_month_and_dispatches_running_update():
    workflow = (ROOT / '.github/workflows/build-era5-land-running-reference-0p1.yml').read_text(encoding='utf-8')
    assert 'cron: "19 3 1 * *"' in workflow
    assert 'reference-month' in workflow
    assert 'era5-land-running-0p1-reference-v1-${{ needs.target.outputs.month_key }}' in workflow
    assert 'gh workflow run update-era5-land-running.yml --ref main' in workflow


def test_completed_backfill_month_skips_live_probe():
    from era5_running_freshness_guard import should_probe_backfill_availability
    assert should_probe_backfill_availability(2026, 6, date(2026, 9, 11)) is False


def test_current_backfill_month_still_requires_live_probe():
    from era5_running_freshness_guard import should_probe_backfill_availability
    assert should_probe_backfill_availability(2026, 9, date(2026, 9, 11)) is True


def test_rank_backfill_workflow_reuses_known_source_and_allows_six_hours():
    workflow = (ROOT / '.github/workflows/backfill-era5-running-temperature-ranks.yml').read_text(encoding='utf-8')
    assert 'source_date:' in workflow
    current = workflow.split('\n  current:', 1)[1].split('\n  shards:', 1)[0]
    assert 'timeout-minutes: 360' in current
    assert '--known-available-through' in current
