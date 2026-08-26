import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from era5_temperature_rank import (
    RANK_CLASS_LABELS,
    RANK_COLORS,
    decode_delta_x_u8,
    temperature_rank_field,
)


def test_decode_delta_x_u8_restores_rows_and_missing_code():
    encoded = np.array([[[10, 2, 253, 6], [250, 10, 1, 251]]], dtype=np.uint8)
    restored = decode_delta_x_u8(encoded)
    expected = np.array([[[10, 12, 9, 15], [250, 4, 5, 0]]], dtype=np.uint8)
    np.testing.assert_array_equal(restored, expected)


def test_temperature_rank_field_assigns_warm_rank_one_and_cold_rank_last():
    history = np.array([
        [[10.0, 10.0, np.nan]],
        [[12.0,  8.0, np.nan]],
        [[11.0,  9.0, np.nan]],
    ])
    current = np.array([[13.0, 7.0, 5.0]])
    rank = temperature_rank_field(current, history)
    np.testing.assert_allclose(rank[0, :2], [1.0, 4.0])
    assert np.isnan(rank[0, 2])


def test_temperature_rank_field_uses_competition_rank_for_ties():
    history = np.array([[[13.0]], [[12.0]], [[12.0]], [[10.0]]])
    current = np.array([[12.0]])
    rank = temperature_rank_field(current, history)
    assert rank[0, 0] == 2.0


def test_palette_matches_the_agreed_nine_rank_classes():
    assert RANK_CLASS_LABELS == [
        '1', '2', '3', '4–9', '10–20', '21–40', '41–60', '61–76', '77'
    ]
    assert len(RANK_COLORS) == 9


def test_decode_temperature_pack_values_uses_metadata_and_missing_code():
    from era5_temperature_rank import decode_temperature_pack_values
    original = np.array([[[1, 3, 255, 5]]], dtype=np.uint8)
    encoded = np.empty_like(original)
    encoded[..., 0] = original[..., 0]
    encoded[..., 1:] = np.mod(
        original[..., 1:].astype(np.int16) - original[..., :-1].astype(np.int16), 256
    ).astype(np.uint8)
    meta = {'n_years': 1, 'nlat': 1, 'nlon': 4, 'missing': 255, 'offset': -2.0, 'step': 0.5}
    values = decode_temperature_pack_values(encoded.tobytes(), meta)
    np.testing.assert_allclose(values[0, 0, [0, 1, 3]], [-1.5, -0.5, 0.5])
    assert np.isnan(values[0, 0, 2])


def test_combine_history_temperature_uses_calendar_day_weights_per_year():
    from era5_temperature_rank import combine_history_temperature
    years = np.array([2023, 2024])
    feb = np.array([[[0.0]], [[0.0]]])
    mar = np.array([[[31.0]], [[31.0]]])
    combined = combine_history_temperature({2: feb, 3: mar}, years, [2, 3])
    expected_2023 = (0.0 * 28 + 31.0 * 31) / 59
    expected_2024 = (0.0 * 29 + 31.0 * 31) / 60
    np.testing.assert_allclose(combined[:, 0, 0], [expected_2023, expected_2024])


def test_area_weighted_fraction_weights_latitude_rows():
    from era5_temperature_rank import area_weighted_fraction
    lat=np.array([0.0,60.0])
    mask=np.array([[True,False],[True,False]])
    valid=np.ones_like(mask,dtype=bool)
    assert area_weighted_fraction(mask,valid,lat)==50.0


def test_rank_palette_boundaries_cover_exact_agreed_classes():
    from era5_temperature_rank import RANK_BOUNDARIES
    assert RANK_BOUNDARIES == [0.5,1.5,2.5,3.5,9.5,20.5,40.5,60.5,76.5,77.5]
