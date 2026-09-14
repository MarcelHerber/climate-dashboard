from datetime import date

from scripts.select_era5_temperature_rank_backfill_successor import choose_successor


def month_dates(year: int, month: int, days: int) -> set[str]:
    return {date(year, month, day).isoformat() for day in range(1, days + 1)}


def test_reopens_march_before_advancing_after_april():
    available = month_dates(2026, 3, 31) | month_dates(2026, 4, 30)
    available.remove("2026-03-17")

    decision = choose_successor(
        target_year=2026,
        target_month=4,
        source=date(2026, 9, 1),
        available=available,
    )

    assert decision == ("dispatch", 3, "gap")


def test_advances_to_may_when_march_and_april_are_complete():
    available = month_dates(2026, 3, 31) | month_dates(2026, 4, 30)

    decision = choose_successor(
        target_year=2026,
        target_month=4,
        source=date(2026, 9, 1),
        available=available,
    )

    assert decision == ("dispatch", 5, "next")


def test_reopens_earliest_gap_before_later_gap():
    available = (
        month_dates(2026, 3, 31)
        | month_dates(2026, 4, 30)
        | month_dates(2026, 5, 31)
    )
    available.remove("2026-03-02")
    available.remove("2026-04-20")

    decision = choose_successor(
        target_year=2026,
        target_month=5,
        source=date(2026, 9, 1),
        available=available,
    )

    assert decision == ("dispatch", 3, "gap")


def test_waits_when_next_month_is_not_available_from_source():
    available = month_dates(2026, 3, 31) | month_dates(2026, 4, 30)

    decision = choose_successor(
        target_year=2026,
        target_month=4,
        source=date(2026, 4, 30),
        available=available,
    )

    assert decision == ("wait", 5, "source")


def test_december_still_repairs_an_earlier_gap_before_finishing():
    import calendar

    available: set[str] = set()
    for month in range(3, 13):
        available |= month_dates(2026, month, calendar.monthrange(2026, month)[1])
    available.remove("2026-07-11")

    decision = choose_successor(
        target_year=2026,
        target_month=12,
        source=date(2026, 12, 31),
        available=available,
    )

    assert decision == ("dispatch", 7, "gap")


def test_december_finishes_when_everything_is_complete():
    import calendar

    available: set[str] = set()
    for month in range(3, 13):
        available |= month_dates(2026, month, calendar.monthrange(2026, month)[1])

    decision = choose_successor(
        target_year=2026,
        target_month=12,
        source=date(2026, 12, 31),
        available=available,
    )

    assert decision == ("done", None, "complete")
