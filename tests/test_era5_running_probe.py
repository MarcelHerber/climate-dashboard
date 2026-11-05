"""Regression tests: the newest valid T/P day must not be skipped by an assumed lag."""
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_era5_land_europe_running as running


def test_probe_starts_yesterday_not_six_days_ago():
    candidates = running.probe_candidate_dates(date(2026, 11, 5))
    assert len(candidates) == running.MAX_LOOKBACK_DAYS == 14
    assert candidates[0] == date(2026, 11, 4)
    assert candidates[4] == date(2026, 10, 31)
    assert candidates[-1] == date(2026, 10, 22)


def test_probe_detects_october_31_on_november_5(monkeypatch, tmp_path):
    monkeypatch.setattr(running, "CACHE_DIR", tmp_path)
    attempted = []

    def fake_daily(_client, years, month, days, _target, _label, **_kwargs):
        d = date(years[0], month, days[0])
        attempted.append(d)
        if d > date(2026, 10, 31):
            raise RuntimeError("Temperatur noch nicht geliefert")

    def fake_precip(_client, years, month, days, _target, _label, **_kwargs):
        assert date(years[0], month, days[0]) == attempted[-1].fromordinal(
            attempted[-1].toordinal() + 1
        )

    monkeypatch.setattr(running, "request_daily_temperature", fake_daily)
    monkeypatch.setattr(running, "request_precip_group", fake_precip)
    monkeypatch.setattr(
        running, "read_temperature",
        lambda _path: (np.array([49.75]), np.array([10.25]), np.array([[15.0]]))
    )
    monkeypatch.setattr(
        running, "read_precip",
        lambda _paths, _month, _day: (np.array([49.75]), np.array([10.25]), np.array([[1.0]]))
    )

    got = running.probe_available_day(object(), date(2026, 11, 5))
    assert got == date(2026, 10, 31)
    assert attempted == [
        date(2026, 11, 4), date(2026, 11, 3), date(2026, 11, 2),
        date(2026, 11, 1), date(2026, 10, 31)
    ]


def test_probe_rejects_day_when_precip_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(running, "CACHE_DIR", tmp_path)
    candidates = []

    def fake_temp(_client, years, month, days, _target, _label, **_kwargs):
        candidates.append(date(years[0], month, days[0]))

    def fake_precip(_client, years, month, days, _target, _label, **_kwargs):
        if candidates[-1] > date(2026, 10, 30):
            raise RuntimeError("Niederschlag für diesen UTC-Tag fehlt")

    monkeypatch.setattr(running, "request_daily_temperature", fake_temp)
    monkeypatch.setattr(running, "request_precip_group", fake_precip)
    monkeypatch.setattr(
        running, "read_temperature",
        lambda _path: (np.array([49.75]), np.array([10.25]), np.array([[15.0]]))
    )
    monkeypatch.setattr(
        running, "read_precip",
        lambda _paths, _month, _day: (np.array([49.75]), np.array([10.25]), np.array([[1.0]]))
    )
    assert running.probe_available_day(object(), date(2026, 11, 5)) == date(2026, 10, 30)
    assert candidates[-1] == date(2026, 10, 30)
