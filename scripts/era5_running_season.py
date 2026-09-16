from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

SEASONS = {
    "spring": {"name": "Frühling", "months": (3, 4, 5)},
    "summer": {"name": "Sommer", "months": (6, 7, 8)},
    "autumn": {"name": "Herbst", "months": (9, 10, 11)},
    "winter": {"name": "Winter", "months": (12, 1, 2)},
}
RUNNING_SEASON_IDS = tuple(f"running_{key}" for key in SEASONS)


@dataclass(frozen=True)
class SeasonSpec:
    key: str
    name: str
    period_id: str
    start: date
    completed_months: tuple[tuple[int, int], ...]
    label: str


def season_key_for_month(month: int) -> str:
    month = int(month)
    for key, meta in SEASONS.items():
        if month in meta["months"]:
            return key
    raise ValueError("month muss zwischen 1 und 12 liegen")


def season_spec(data_through: date) -> SeasonSpec:
    key = season_key_for_month(data_through.month)
    meta = SEASONS[key]
    months = tuple(int(m) for m in meta["months"])
    idx = months.index(data_through.month)

    if key == "winter":
        start_year = data_through.year if data_through.month == 12 else data_through.year - 1

        def year_for_month(month: int) -> int:
            return start_year if month == 12 else start_year + 1

        label_year = f"{start_year}/{str(start_year + 1)[-2:]}"
    else:
        start_year = data_through.year

        def year_for_month(month: int) -> int:
            return data_through.year

        label_year = str(data_through.year)

    completed = tuple((year_for_month(month), month) for month in months[:idx])
    start = date(start_year, months[0], 1)
    label = f"{meta['name']} {label_year} bis {data_through.strftime('%d.%m.')}"
    return SeasonSpec(
        key=key,
        name=str(meta["name"]),
        period_id=f"running_{key}",
        start=start,
        completed_months=completed,
        label=label,
    )


def combine_season_fields(
    *,
    data_through: date,
    current_temp,
    reference_temp,
    current_precip,
    reference_precip,
    completed_current,
    completed_reference,
):
    import numpy as np

    spec = season_spec(data_through)
    end_day = data_through.day

    temp_sum = np.asarray(current_temp, dtype=float) * end_day
    temp_ref_sum = np.asarray(reference_temp, dtype=float) * end_day
    temp_days = end_day
    precip_sum = np.asarray(current_precip, dtype=float).copy()
    precip_ref_sum = np.asarray(reference_precip, dtype=float).copy()

    for year, month in spec.completed_months:
        current = completed_current.get((year, month))
        reference = completed_reference.get(month)
        if current is None:
            raise ValueError(f"Aktuelles Monatsfeld {year}-{month:02d} fehlt für {spec.name}-bis-aktuell.")
        if reference is None:
            raise ValueError(f"Referenz-Monatsfeld {month:02d} fehlt für {spec.name}-bis-aktuell.")
        days = calendar.monthrange(year, month)[1]
        temp_sum = temp_sum + np.asarray(current[0], dtype=float) * days
        temp_ref_sum = temp_ref_sum + np.asarray(reference[0], dtype=float) * days
        temp_days += days
        precip_sum = precip_sum + np.asarray(current[1], dtype=float)
        precip_ref_sum = precip_ref_sum + np.asarray(reference[1], dtype=float)

    return temp_sum / temp_days, temp_ref_sum / temp_days, precip_sum, precip_ref_sum
