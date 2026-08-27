from __future__ import annotations

import numpy as np
import pytest

from scripts.build_hyras_daily_archive import (
    ARCHIVE_TAG,
    RESOLUTION_KM,
    _archive_filename,
    _release_url,
    _validate_dates,
)


def day_range(start: str, stop: str) -> np.ndarray:
    return np.arange(np.datetime64(start), np.datetime64(stop), dtype="datetime64[D]")


def test_archive_is_native_one_kilometre():
    assert RESOLUTION_KM == 1


def test_validate_complete_non_leap_year():
    dates = day_range("2025-01-01", "2026-01-01")
    _validate_dates(dates, 2025, require_complete=True)
    assert dates.size == 365


def test_validate_complete_leap_year():
    dates = day_range("2024-01-01", "2025-01-01")
    _validate_dates(dates, 2024, require_complete=True)
    assert dates.size == 366


def test_validate_rejects_gap():
    dates = day_range("2025-01-01", "2025-01-10")
    dates = np.delete(dates, 4)
    with pytest.raises(RuntimeError, match="Lücke"):
        _validate_dates(dates, 2025, require_complete=False)


def test_validate_allows_partial_current_style_year():
    dates = day_range("2026-01-01", "2026-08-24")
    _validate_dates(dates, 2026, require_complete=False)
    assert str(dates[-1]) == "2026-08-23"


def test_release_url_and_filename_are_stable():
    name = _archive_filename("tmean", 1951)
    assert name == "hyras-tmean-1951-1km.npz"
    assert ARCHIVE_TAG == "hyras-daily-archive-1km"
    assert _release_url("MarcelHerber/climate-dashboard", name) == (
        "https://github.com/MarcelHerber/climate-dashboard/releases/download/"
        "hyras-daily-archive-1km/hyras-tmean-1951-1km.npz"
    )
