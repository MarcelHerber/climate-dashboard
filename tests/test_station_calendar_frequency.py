from datetime import date
import io
import zipfile


def _module():
    try:
        from scripts import station_calendar_frequency as module
    except (ModuleNotFoundError, ImportError):
        return None
    return module


def test_calendar_frequency_reports_counts_percent_and_records():
    module = _module()
    assert module is not None, 'station_calendar_frequency module is missing'

    tx = {
        date(2020, 4, 4): 26.0,
        date(2021, 4, 4): 24.0,
        date(2022, 4, 4): 31.0,
        date(2020, 3, 30): 25.2,
        date(2021, 10, 15): 25.1,
        date(2020, 4, 1): 35.1,
    }
    snow = {
        date(2020, 12, 1): 12.0,
        date(2021, 12, 1): 0.0,
        date(2022, 12, 1): 5.0,
        date(2020, 10, 20): 1.0,
        date(2021, 11, 15): 6.0,
        date(2022, 5, 2): 6.0,
        date(2020, 5, 15): 10.0,
        date(2021, 4, 10): 1.0,
    }

    payload = module.build_calendar_frequency_payload(tx, snow)
    april4 = module.non_leap_index(date(2021, 4, 4))
    dec1 = module.non_leap_index(date(2021, 12, 1))

    temp = payload['temperature']
    assert temp['valid_years'][april4] == 3
    assert temp['counts']['25'][april4] == 2
    assert temp['percent']['25'][april4] == 66.7
    assert temp['counts']['30'][april4] == 1
    assert temp['percent']['30'][april4] == 33.3
    assert temp['records']['25']['earliest']['month_day'] == '03-30'
    assert temp['records']['25']['latest']['month_day'] == '10-15'

    snow_payload = payload['snow']
    assert snow_payload['valid_years'][dec1] == 3
    assert snow_payload['counts']['1'][dec1] == 2
    assert snow_payload['percent']['1'][dec1] == 66.7
    assert snow_payload['counts']['10'][dec1] == 1
    assert snow_payload['records']['1']['earliest_second_half']['month_day'] == '10-20'
    assert snow_payload['records']['1']['latest_first_half']['month_day'] == '05-15'


def test_parse_snow_heights_from_kl_zip_reads_shk_tag_and_ignores_missing():
    module = _module()
    assert module is not None, 'station_calendar_frequency module is missing'

    text = (
        'STATIONS_ID;MESS_DATUM;TXK;SHK_TAG;eor\n'
        '1420;20200101;4.2;3;eor\n'
        '1420;20200102;5.1;-999;eor\n'
        '1420;20200103;6.0;0;eor\n'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('produkt_klima_tag_01420.txt', text.encode('latin-1'))

    result = module.parse_snow_heights_from_kl_zip(
        buffer.getvalue(), date(2020, 1, 1), date(2020, 1, 3)
    )
    assert result == {date(2020, 1, 1): 3.0, date(2020, 1, 3): 0.0}
