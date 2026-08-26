from datetime import date

import numpy as np
import pytest

from scripts.hyras_temperature_rank import (
    HISTORY_END,
    HISTORY_START,
    RANK_BOUNDARIES,
    RANK_CLASS_LABELS,
    RANK_COLORS,
    PRODUCTS,
    extract_products,
    historical_years,
    rank_field,
)


def test_hyras_history_is_1951_through_2025_with_76_total_positions():
    years = historical_years()
    assert years[0] == 1951
    assert years[-1] == 2025
    assert len(years) == 75
    assert len(years) + 1 == 76


def test_rank_palette_is_adapted_to_76_positions():
    assert RANK_CLASS_LABELS == [
        "1", "2", "3", "4–9", "10–20", "21–40", "41–60", "61–75", "76"
    ]
    assert RANK_COLORS == [
        "#D7198C", "#E31A1C", "#F46D43", "#FDB863", "#FFF7D6",
        "#D7E9F7", "#82B5D8", "#2C6AA0", "#4B176D",
    ]
    assert RANK_BOUNDARIES == [0.5, 1.5, 2.5, 3.5, 9.5, 20.5, 40.5, 60.5, 75.5, 76.5]


def test_rank_one_is_warmest_and_rank_76_is_coldest():
    history = np.arange(75, dtype=float).reshape(75, 1, 1)
    assert rank_field(np.array([[100.0]]), history)[0, 0] == 1
    assert rank_field(np.array([[-1.0]]), history)[0, 0] == 76


def test_equal_historical_values_share_the_same_competition_rank():
    history = np.array([[[5.0]], [[5.0]], [[4.0]], [[6.0]]])
    assert rank_field(np.array([[5.0]]), history)[0, 0] == 2


def test_extract_products_for_august_25_uses_day_month_and_summer_windows():
    target = date(2026, 8, 25)
    dates = np.arange(np.datetime64("2026-06-01"), np.datetime64("2026-08-26"))
    cube = np.arange(len(dates), dtype=float).reshape(-1, 1, 1)

    products = extract_products(dates, cube, target)

    assert tuple(products) == PRODUCTS
    assert products["day"][0, 0] == cube[-1, 0, 0]
    august = cube[-25:, 0, 0]
    assert products["month_to_date"][0, 0] == pytest.approx(float(np.mean(august)))
    assert products["summer_to_date"][0, 0] == pytest.approx(float(np.mean(cube[:, 0, 0])))


def test_extract_products_requires_same_calendar_target_day():
    target = date(2026, 8, 25)
    dates = np.arange(np.datetime64("2026-06-01"), np.datetime64("2026-08-25"))
    cube = np.zeros((len(dates), 2, 2), dtype=float)
    with pytest.raises(ValueError, match="Zieltag"):
        extract_products(dates, cube, target)


def test_extract_products_masks_cells_without_any_valid_values():
    target = date(2026, 6, 3)
    dates = np.array(["2026-06-01", "2026-06-02", "2026-06-03"], dtype="datetime64[D]")
    cube = np.array([
        [[1.0, np.nan]],
        [[2.0, np.nan]],
        [[3.0, np.nan]],
    ])
    products = extract_products(dates, cube, target)
    assert products["day"][0, 0] == 3.0
    assert products["month_to_date"][0, 0] == 2.0
    assert products["summer_to_date"][0, 0] == 2.0
    assert np.isnan(products["summer_to_date"][0, 1])


from scripts.hyras_temperature_rank import (
    MISSING_I16,
    TEMPERATURE_SCALE,
    date_codes,
    dequantize_temperature,
    quantize_temperature,
)


def test_quantized_temperature_cache_roundtrips_to_one_hundredth_degree():
    source = np.array([[[-12.345, 0.0, 41.234, np.nan]]], dtype=float)
    packed = quantize_temperature(source)
    assert packed.dtype == np.int16
    assert packed[0, 0, 3] == MISSING_I16
    decoded = dequantize_temperature(packed)
    assert decoded[0, 0, 0] == pytest.approx(-12.34, abs=0.011)
    assert decoded[0, 0, 1] == 0.0
    assert decoded[0, 0, 2] == pytest.approx(41.23, abs=0.011)
    assert np.isnan(decoded[0, 0, 3])
    assert TEMPERATURE_SCALE == 100


def test_date_codes_store_month_and_day_only():
    dates = np.array(["1951-06-01", "1951-08-25"], dtype="datetime64[D]")
    assert date_codes(dates).tolist() == [601, 825]


from scripts.build_hyras_temperature_rank_shard import historical_dates_for_target
from scripts.build_hyras_temperature_rank_maps import period_label


def test_historical_dates_for_target_reuses_same_calendar_window():
    dates = historical_dates_for_target(1951, date(2026, 8, 25))
    assert str(dates[0]) == "1951-06-01"
    assert str(dates[-1]) == "1951-08-25"
    assert len(dates) == 86


def test_period_labels_make_running_windows_explicit():
    target = date(2026, 8, 25)
    assert period_label("day", target) == "25.08.2026"
    assert period_label("month_to_date", target) == "01.–25.08.2026"
    assert period_label("summer_to_date", target) == "01.06.–25.08.2026"
