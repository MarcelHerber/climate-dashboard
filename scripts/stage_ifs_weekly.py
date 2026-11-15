"""Verify and stage the original 0.1-degree IFS week for GitHub Pages."""
import argparse
import base64
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

FILES = ('current.json', 'forecast.json', 'geography.json')
GRID = (1801, 601, 0.1, 85, 25, -80, 100)
GRID_KEYS = ('width', 'height', 'grid_degrees', 'lat_north', 'lat_south', 'lon_west', 'lon_east')
LABEL = 'ECMWF IFS · 7-Tage-Temperaturanomalie'


def validate(folder):
    current, forecast, geo = [json.loads((folder / f).read_text(encoding='utf-8')) for f in FILES]
    for data in (current, forecast, geo):
        assert data['schema'] == 1 and tuple(data[k] for k in GRID_KEYS) == GRID
    assert current['type'] == forecast['type'] == 'ifs_0p1_seven_day_forecast'
    run = datetime.fromisoformat(current['run_utc'])
    assert datetime.fromisoformat(current['valid_from_utc']) == run
    assert datetime.fromisoformat(current['valid_to_utc']) == run + timedelta(hours=168)
    assert current['period_days'] == 7 and current['sample_count'] == 29
    assert current['lead_hours'] == list(range(0, 169, 6)) and len(current['sources']) == 29
    for h, src in zip(current['lead_hours'], current['sources']):
        assert src['forecast_hour'] == h and datetime.fromisoformat(src['valid_utc']) == run + timedelta(hours=h)
        assert re.fullmatch(r'[a-f0-9]{64}', src['sha256']) and src['bytes'] > 1000
    assert forecast['reference_ready'] is False and current['reference_ready'] is True
    assert all(current[k] == v for k, v in forecast.items() if k != 'reference_ready')
    assert current['reference_version'] == 'era5-t2m-calendar-hour-1991-2020-v1'
    ref = current['reference_metadata']
    assert (ref['period'], ref['years'], ref['native_grid_degrees'], ref['interpolation']) == ('1991–2020', 30, .25, 'bilinear')
    assert geo['type'] == 'geographic_country_boundaries_not_temperature' and geo['countries'] and len(geo['rings']) >= 100
    for data, key in ((current, 'forecast_mean_q10_b64'), (current, 'anomaly_mean_q10_b64'), (geo, 'country_mask_b64')):
        assert len(base64.b64decode(data[key], validate=True)) == 1801 * 601 * 2
    print('Verified IFS 0.1° and ERA5 reference:', current['run_utc'])


def add_navigation(root):
    page, mobile = root / 'index.html', root / 'mobile_navigation.js'
    html = page.read_text(encoding='utf-8')
    nav = mobile.read_text(encoding='utf-8')
    marker = 'data-nav-group="misc" href="ifs_weekly_europe.html"'
    if marker not in html:
        anchor = re.compile(r'<a\b[^>]*data-nav-group="misc" href="gfs_weekly_europe\.html"[^>]*>[^<]*</a>')
        assert len(anchor.findall(html)) == 1, 'GFS desktop navigation anchor missing or duplicated'
        html = anchor.sub(lambda m: m.group(0) + '\n          <a class="tab-button" ' + marker + '>' + LABEL + '</a>', html)
    target = '["gfs_weekly_europe.html","GFS · 7-Tage-Temperaturanomalie"]'
    addition = '["ifs_weekly_europe.html","' + LABEL + '"]'
    if addition not in nav:
        assert nav.count(target) == 1, 'GFS mobile navigation anchor missing or duplicated'
        nav = nav.replace(target, target + ',' + addition, 1)
    assert html.count(marker) == nav.count(addition) == 1
    page.write_text(html, encoding='utf-8')
    mobile.write_text(nav, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--site', type=Path)
    args = parser.parse_args()
    validate(args.source)
    if args.site:
        dest = args.site / 'ifs_weekly_europe'
        dest.mkdir(parents=True, exist_ok=True)
        for file in FILES:
            shutil.copyfile(args.source / file, dest / file)
        add_navigation(args.site)


if __name__ == '__main__':
    main()
