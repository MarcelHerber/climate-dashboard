from __future__ import annotations

from datetime import date
from typing import Callable


def resolve_available_through(
    year: int,
    month: int,
    end_day: int,
    indexed_data_through: date,
    probe_latest: Callable[[], date],
) -> tuple[date, bool]:
    """Use the already published data horizon when it covers the backfill target.

    Returns ``(available_through, used_live_probe)``. A live CDS probe is only
    needed when the requested target extends beyond the data horizon already
    recorded by the running ERA5 index.
    """
    target = date(int(year), int(month), int(end_day))
    if target <= indexed_data_through:
        return indexed_data_through, False
    return probe_latest(), True
