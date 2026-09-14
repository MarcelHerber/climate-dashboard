#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path


def select_reference_month(today: date, requested_month: str | None = None) -> tuple[int, int, str]:
    raw = (requested_month or '').strip()
    month = int(raw) if raw else today.month
    if not 1 <= month <= 12:
        raise ValueError(f'Ungültiger Referenzmonat: {month}')
    year = today.year
    return year, month, f'{year}-{month:02d}'


def validate_index_data_through(index_path: Path, expected_data_through: str) -> str:
    expected = date.fromisoformat(str(expected_data_through)).isoformat()
    payload = json.loads(index_path.read_text(encoding='utf-8'))
    if payload.get('ready') is not True:
        raise RuntimeError(f'ERA5-Running-Index ist nicht ready: {index_path}')
    actual_raw = payload.get('data_through')
    if not actual_raw:
        raise RuntimeError(f'ERA5-Running-Index enthält kein data_through: {index_path}')
    actual = date.fromisoformat(str(actual_raw)).isoformat()
    if actual != expected:
        raise RuntimeError(
            f'ERA5-Running-Datenstand stimmt nicht mit der frischen Probe überein: '
            f'Index={actual}, Probe={expected}'
        )
    return actual



def validate_backfill_end_day(
    target_year: int,
    target_month: int,
    planned_end_day: int,
    available_through: date,
) -> int:
    target_year = int(target_year)
    target_month = int(target_month)
    planned_end_day = int(planned_end_day)
    if not 1 <= target_month <= 12:
        raise ValueError(f'Ungültiger Backfill-Monat: {target_month}')

    target_key = (target_year, target_month)
    available_key = (available_through.year, available_through.month)
    if target_key > available_key:
        raise RuntimeError(
            f'Backfill {target_year}-{target_month:02d} liegt hinter dem frisch verfügbaren '
            f'ERA5-Land-Temperaturstand {available_through.isoformat()}.'
        )

    expected_end_day = (
        available_through.day
        if target_key == available_key
        else calendar.monthrange(target_year, target_month)[1]
    )
    if planned_end_day != expected_end_day:
        raise RuntimeError(
            f'Veralteter ERA5-Backfill-Plan für {target_year}-{target_month:02d}: '
            f'geplant bis Tag {planned_end_day}, frisch geprüft ist Tag {expected_end_day} '
            f'(ERA5-Land verfügbar bis {available_through.isoformat()}).'
        )
    return expected_end_day

def append_output(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        for key, value in values.items():
            print(f'{key}={value}')
        return
    with path.open('a', encoding='utf-8') as fh:
        for key, value in values.items():
            fh.write(f'{key}={value}\n')


def main() -> int:
    parser = argparse.ArgumentParser(description='Schutzlogik für laufende ERA5-Land-Daten.')
    sub = parser.add_subparsers(dest='command', required=True)

    ref = sub.add_parser('reference-month', help='Referenzmonat für den Monatscache bestimmen')
    ref.add_argument('--today')
    ref.add_argument('--month', default='')
    ref.add_argument('--github-output', type=Path, default=Path(os.environ['GITHUB_OUTPUT']) if os.environ.get('GITHUB_OUTPUT') else None)

    validate = sub.add_parser('validate-index', help='Index gegen den frisch ermittelten Datenstand prüfen')
    validate.add_argument('--index', type=Path, required=True)
    validate.add_argument('--expected', required=True)

    args = parser.parse_args()
    if args.command == 'reference-month':
        today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
        year, month, month_key = select_reference_month(today, args.month)
        append_output(args.github_output, {
            'year': str(year),
            'month': f'{month:02d}',
            'month_key': month_key,
        })
        print(f'ERA5-Referenzcache: {month_key}')
        return 0

    actual = validate_index_data_through(args.index, args.expected)
    print(f'ERA5-Running-Datenstand verifiziert: {actual}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
