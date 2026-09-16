from datetime import date
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_september_is_running_autumn():
    from era5_running_season import season_spec

    spec = season_spec(date(2026, 9, 10))
    assert spec.key == "autumn"
    assert spec.period_id == "running_autumn"
    assert spec.label == "Herbst 2026 bis 10.09."
    assert spec.start == date(2026, 9, 1)
    assert spec.completed_months == ()


def test_winter_crosses_year_boundary():
    from era5_running_season import season_spec

    spec = season_spec(date(2027, 2, 10))
    assert spec.key == "winter"
    assert spec.period_id == "running_winter"
    assert spec.label == "Winter 2026/27 bis 10.02."
    assert spec.start == date(2026, 12, 1)
    assert spec.completed_months == ((2026, 12), (2027, 1))


def test_completed_months_are_weighted_into_season():
    from era5_running_season import combine_season_fields

    current_temp = np.array([[20.0]])
    reference_temp = np.array([[10.0]])
    current_precip = np.array([[20.0]])
    reference_precip = np.array([[10.0]])
    completed_current = {(2026, 9): (np.array([[10.0]]), np.array([[30.0]]))}
    completed_reference = {9: (np.array([[8.0]]), np.array([[25.0]]))}

    t, tr, p, pr = combine_season_fields(
        data_through=date(2026, 10, 10),
        current_temp=current_temp,
        reference_temp=reference_temp,
        current_precip=current_precip,
        reference_precip=reference_precip,
        completed_current=completed_current,
        completed_reference=completed_reference,
    )
    assert np.allclose(t, [[12.5]])
    assert np.allclose(tr, [[8.5]])
    assert np.allclose(p, [[50.0]])
    assert np.allclose(pr, [[35.0]])
