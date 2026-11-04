#!/usr/bin/env python3
"""Observed IMS snow cover and same-calendar-day occurrence departure, 2001–2020.

NSIDC G02156: ASCII row zero starts at the SOUTH edge, unlike the companion
binary latitude/longitude grids. Reproject categories by nearest neighbour;
calculate anomalies on the native grid before reprojection. Sea/lake ice and
water never count as snow-free land. No model or screenshot pixels are used.
"""
from __future__ import annotations

import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import gzip
import html
import io
import json
import logging
import math
from pathlib import Path
import re
import urllib.parse
import urllib.request

import numpy as np

LOG = logging.getLogger('snow_maps')
SOURCE = 'https://noaadata.apps.nsidc.org/NOAA/G02156/24km/'
GEOGRAPHY = ('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/'
             'v5.1.2/geojson/ne_50m_admin_0_countries.geojson')
VERSION = 2
SIZE = 1024
CELL = 23684.977
XLL, YLL = -12126597.0, -12126480.0
RADIUS = 6371200.0
K0 = (1 + math.sin(math.radians(60))) / 2
FILE = re.compile(r'ims(\d{4})(\d{3})(?:_00UTC)?_24km_v([\d.]+)\.asc\.gz', re.I)
PACKED = re.compile(rb'[0-4]{1024}')
EXPANDED = re.compile(rb'[0-4](?:\s+[0-4])*')


def parse_grid(packed: bytes) -> np.ndarray:
    raw = gzip.decompress(packed)
    lines = [line.strip() for line in raw.splitlines()]
    rows = [line for line in lines if PACKED.fullmatch(line)]
    if len(rows) == SIZE:
        return np.frombuffer(b''.join(rows), dtype=np.uint8).reshape(SIZE, SIZE) - 48
    # Some historical days use expanded, whitespace-separated one-digit codes.
    tokens = b' '.join(line for line in lines if EXPANDED.fullmatch(line)).split()
    if len(tokens) != SIZE * SIZE:
        raise ValueError('IMS-Raster unvollständig oder ungültig')
    return np.frombuffer(b''.join(tokens), dtype=np.uint8).reshape(SIZE, SIZE) - 48


def reference_dates(date: dt.date) -> tuple[list[dt.date], int]:
    leap = (date.month, date.day) == (2, 29)
    return ([dt.date(y, date.month, date.day) for y in range(2001, 2021)
             if not leap or calendar.isleap(y)], 4 if leap else 15)


def reference_counts(grids) -> tuple[np.ndarray, np.ndarray]:
    snow = count = None
    for grid in grids:
        if snow is None:
            snow = np.zeros(grid.shape, dtype=np.uint16)
            count = np.zeros(grid.shape, dtype=np.uint16)
        if grid.shape != snow.shape:
            raise ValueError('Historische IMS-Raster haben verschiedene Formen')
        snow += grid == 4
        count += (grid == 2) | (grid == 4)
    if snow is None:
        raise ValueError('Keine historischen IMS-Landraster')
    return snow, count


def snow_departure(current, snow, count, minimum=15) -> np.ndarray:
    result = np.full(current.shape, np.nan, dtype=np.float32)
    valid = ((current == 2) | (current == 4)) & (count >= minimum)
    result[valid] = 100 * ((current[valid] == 4).astype(np.float32) -
                          snow[valid] / count[valid])
    return result


def ascii_indices(latitude, longitude) -> tuple[np.ndarray, np.ndarray]:
    rho = 2 * RADIUS * K0 * np.tan(np.pi / 4 - np.radians(latitude) / 2)
    angle = np.radians(longitude + 80)
    x, y = rho * np.sin(angle), -rho * np.cos(angle)
    # The ASCII header specifies (1,1) at lower left; do not flip these rows.
    row = np.floor((y - YLL) / CELL).astype(int)
    col = np.floor((x - XLL) / CELL).astype(int)
    return row, col


def display_indices():
    lon, lat = np.meshgrid(np.arange(-179.875, 180, .25),
                          np.arange(89.875, 20, -.25))
    rows, cols = ascii_indices(lat, lon)
    if not ((rows >= 0) & (rows < SIZE) & (cols >= 0) & (cols < SIZE)).all():
        raise ValueError('Kartenprojektion außerhalb des IMS-Rasters')
    return rows, cols


def available_dates(catalogs, today, days):
    return sorted({date for year in (today.year - 1, today.year)
                   for date in catalogs.get(year, {}) if date <= today}, reverse=True)[:days]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': 'ClimateDashboardSnowMaps/1.0'})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


class Archive:
    def __init__(self, cache: Path):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.catalogs = {}

    def inventory(self, year):
        base = f'{SOURCE}{year}/'
        listing = fetch(base).decode('utf-8', 'replace')
        result = {}
        versions = {}
        for link in re.findall(r'href=["\x27]([^"\x27]+)', listing):
            name = urllib.parse.unquote(html.unescape(link)).rsplit('/', 1)[-1]
            match = FILE.fullmatch(name)
            if not match or int(match[1]) != year:
                continue
            date = dt.date(year, 1, 1) + dt.timedelta(days=int(match[2]) - 1)
            if date.year != year:
                continue
            version = tuple(int(x) for x in match[3].strip('.').split('.'))
            if date not in result or version > versions[date]:
                result[date] = urllib.parse.urljoin(base, link)
                versions[date] = version
        self.catalogs[year] = result
        return result

    def grid(self, date):
        link = self.catalogs.get(date.year, {}).get(date)
        if not link:
            raise ValueError(f'Kein IMS-Originalraster für {date}')
        path = self.cache / link.rsplit('/', 1)[-1]
        if path.exists():
            try:
                return parse_grid(path.read_bytes())
            except (ValueError, OSError, EOFError):
                path.unlink()
        data = fetch(link)
        grid = parse_grid(data)  # Reject HTML, partial grids and invalid gzip before caching.
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(path)
        return grid


def complete_pair(directory: Path, record: dict) -> bool:
    from PIL import Image
    try:
        for key in ('cover', 'anomaly'):
            with Image.open(directory / record[key]) as image:
                image.load()
                if image.width < 3000 or image.height < 900 or image.mode != 'RGB':
                    return False
        return True
    except (OSError, KeyError):
        return False


def geography(cache: Path):
    path = cache / 'ne_50m_countries_v5.1.2.json'
    if not path.exists():
        data = fetch(GEOGRAPHY)
        obj = json.loads(data)
        if obj.get('type') != 'FeatureCollection' or len(obj.get('features', [])) < 150:
            raise ValueError('Natural-Earth-Ländergrenzen unvollständig')
        path.write_bytes(data)
    return json.loads(path.read_text())


def borders(ax, countries):
    from matplotlib.collections import LineCollection
    lines = []
    for feature in countries['features']:
        geom = feature['geometry']
        polygons = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
        for polygon in polygons:
            for ring in polygon:
                coords = np.asarray(ring)
                if coords[:, 1].max() < 20:
                    continue
                # Never draw a horizontal line across the map at the date line.
                for segment in np.split(coords, np.flatnonzero(np.abs(np.diff(coords[:, 0])) > 180) + 1):
                    if len(segment) > 1:
                        lines.append(segment)
    ax.add_collection(LineCollection(lines, colors='#586c7e', linewidths=.28, zorder=3))


def render(path, field, date, countries, *, anomaly=False, minimum=15, reference_years=20, surface=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, LinearSegmentedColormap
    from matplotlib.patches import Patch
    from PIL import Image

    fig, ax = plt.subplots(figsize=(16, 5.4), dpi=220, facecolor='white')
    fig.subplots_adjust(left=.045, right=.985, top=.79, bottom=.22)
    ax.set_facecolor('#eaf1f5')
    title = 'Abweichung der Schneebedeckung' if anomaly else 'Beobachtete Schneebedeckung'
    fig.text(.045, .925, title + ' | Nordhalbkugel', fontsize=18, weight='bold', color='#243b53')
    fig.text(.045, .867, f'NOAA / USNIC IMS · {date:%d.%m.%Y}, 00 UTC · nominal 24 km',
             fontsize=10.5, color='#51677d')
    if anomaly:
        if surface is not None:
            background = np.where((surface == 2) | (surface == 4), 1, 0)
            ax.imshow(background, origin='upper', extent=(-180, 180, 20, 90),
                      cmap=ListedColormap(['#eaf1f5', '#e8ecef']), vmin=0, vmax=1,
                      interpolation='nearest', aspect='auto')
        cmap = LinearSegmentedColormap.from_list('snow_departure',
                ['#9e2646', '#d77064', '#f2bca8', '#ffffff', '#c1d4eb', '#779bcd', '#3f4d98'])
        cmap.set_bad((0, 0, 0, 0))
        image = ax.imshow(np.ma.masked_invalid(field), origin='upper', extent=(-180, 180, 20, 90),
                          cmap=cmap, vmin=-100, vmax=100, interpolation='nearest', aspect='auto')
        bar_ax = fig.add_axes((.25, .145, .5, .023))
        bar = fig.colorbar(image, cax=bar_ax, orientation='horizontal', ticks=[-100, -75, -50, -25, 0, 25, 50, 75, 100])
        bar.ax.tick_params(labelsize=8)
        bar.set_label('Abweichung in Prozentpunkten · Rot: weniger Schnee · Blau: mehr Schnee', fontsize=9)
        note = (f'Referenz: gleicher Kalendertag 2001–2020 · {reference_years} verfügbare Jahresraster · '
                f'mindestens {minimum} gültige Landwerte je Zelle.')
    else:
        cmap = ListedColormap(['#eaf1f5', '#eaf1f5', '#ffffff', '#b8c6d0', '#7697c7'])
        ax.imshow(field, origin='upper', extent=(-180, 180, 20, 90), cmap=cmap, vmin=-.5, vmax=4.5,
                  interpolation='nearest', aspect='auto')
        ax.legend(handles=[Patch(color='#7697c7', label='Schneebedecktes Land'),
                           Patch(color='#ffffff', ec='#8b99a4', label='Schneefreies Land'),
                           Patch(color='#b8c6d0', label='Meer- / Seeeis')],
                  loc='upper center', bbox_to_anchor=(.5, -.13), ncol=3, frameon=False, fontsize=10)
        note = 'Beobachtete Landbedeckung: Schnee vorhanden / nicht vorhanden. Keine Schneehöhe oder Neuschneemenge.'
    borders(ax, countries)
    ax.set(xlim=(-180, 180), ylim=(20, 90))
    ax.set_xticks([-180, -120, -60, 0, 60, 120, 180],
                  ['180°', '120° W', '60° W', '0°', '60° O', '120° O', '180°'])
    ax.set_yticks([30, 50, 70, 90], ['30° N', '50° N', '70° N', '90° N'])
    ax.tick_params(labelsize=8, colors='#51677d', length=0, pad=5)
    ax.grid(color='#748ba1', alpha=.12, linewidth=.4)
    for spine in ax.spines.values():
        spine.set_edgecolor('#8091a0')
        spine.set_linewidth(.6)
    fig.text(.045, .035, 'Quelle: NOAA / USNIC IMS via NSIDC, G02156 · DOI 10.7265/N52R3PMC · Grenzen: Natural Earth',
             fontsize=7.5, color='#51677d')
    fig.text(.045, .014, note, fontsize=7.5, color='#51677d')
    data = io.BytesIO()
    fig.savefig(data, format='png', facecolor='white', transparent=False)
    plt.close(fig)
    data.seek(0)
    # Explicit RGB fixes dark backgrounds in mobile image viewers.
    with Image.open(data) as image:
        image.convert('RGB').save(path)


def update(output: Path, cache: Path, *, days=7, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'images').mkdir(exist_ok=True)
    manifest = output / 'index.json'
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    archive = Archive(cache)
    years = list(range(2001, 2021)) + [today.year - 1, today.year]
    errors = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(archive.inventory, year): year for year in sorted(set(years))}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                errors.append(f'IMS-Verzeichnis {futures[future]}: {exc}')
    current_dates = available_dates(archive.catalogs, today, days)
    countries = geography(cache)
    rows, cols = display_indices()
    records = {r['date']: r for r in previous.get('maps', []) if complete_pair(output, r)}
    for date in current_dates:
        dates, minimum = reference_dates(date)
        old = records.get(date.isoformat())
        if (old and old.get('version') == VERSION and len(old.get('reference_years', [])) == len(dates)):
            continue
        try:
            grids = {}
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(archive.grid, day): day for day in [date] + dates}
                for future in as_completed(futures):
                    day = futures[future]
                    try:
                        grids[day] = future.result()
                    except Exception as exc:
                        errors.append(f'{day}: {exc}')
            current = grids.pop(date)  # Missing current day must never borrow another date.
            if len(grids) < minimum:
                raise ValueError(f'Nur {len(grids)} statt mindestens {minimum} Referenzjahre')
            snow, count = reference_counts(grids.values())
            departure = snow_departure(current, snow, count, minimum)
            view = current[rows, cols]
            difference = departure[rows, cols]
            land = (view == 2) | (view == 4)
            coverage = float(np.isfinite(difference[land]).mean())
            if np.count_nonzero(land) < 50000 or coverage < .9:
                raise ValueError(f'Unvollständige Landreferenz: {coverage:.1%}')
            entry = {'date': date.isoformat(), 'valid_utc': date.isoformat() + 'T00:00:00Z',
                     'version': VERSION, 'cover': f'images/{date}_cover.png',
                     'anomaly': f'images/{date}_anomaly.png',
                     'reference_years': sorted(day.year for day in grids),
                     'minimum_samples': minimum, 'reference_land_coverage': round(coverage, 5),
                     'source_url': archive.catalogs[date.year][date],
                     'reference_sources': [archive.catalogs[d.year][d] for d in sorted(grids)]}
            staged = {kind: str(Path(entry[kind]).with_suffix('.tmp.png')) for kind in ('cover', 'anomaly')}
            for kind, field in [('cover', view), ('anomaly', difference)]:
                temporary = output / staged[kind]
                render(temporary, field, date, countries, anomaly=kind == 'anomaly',
                       minimum=minimum, reference_years=len(grids), surface=view)
            if not complete_pair(output, staged):
                raise ValueError('Kartenpaar nicht vollständig')
            # Render AND validate both before replacing a previously complete pair.
            for kind in ('cover', 'anomaly'):
                (output / staged[kind]).replace(output / entry[kind])
            records[entry['date']] = entry
            LOG.info('%s: zwei Karten, %d Referenzjahre, %.2f%% Landreferenz', date, len(grids), coverage * 100)
        except Exception as exc:
            errors.append(f'Karten {date}: {exc}')
            LOG.warning('Karten %s nicht veröffentlicht: %s', date, exc)
    selected = sorted(records.values(), key=lambda r: r['date'], reverse=True)[:days]
    if not selected:
        raise RuntimeError('Keine vollständigen echten IMS-Karten: ' + '; '.join(errors[-5:]))
    result = {'schema': 1, 'product': 'IMS snow cover and occurrence departure',
              'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'latest': selected[0]['date'], 'reference_period': [2001, 2020],
              'resolution_km_nominal': 24, 'extent': [-180, 180, 20, 90],
              'anomaly_unit': 'percentage points', 'sea_ice_in_anomaly': False,
              'maps': selected, 'source': {'name': 'NOAA / USNIC IMS via NSIDC G02156',
                                         'doi': '10.7265/N52R3PMC'}, 'source_errors': errors}
    # A cache check without new data should not create another data commit.
    if ({k: v for k, v in result.items() if k != 'generated_utc'} ==
            {k: v for k, v in previous.items() if k != 'generated_utc'}):
        return previous
    temporary = manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(manifest)
    keep = {r[kind] for r in selected for kind in ('cover', 'anomaly')}
    for path in (output / 'images').glob('*.png'):
        if path.relative_to(output).as_posix() not in keep:
            path.unlink()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('eurasia_snow/maps'))
    parser.add_argument('--cache', type=Path, default=Path('.cache/ims-snow-maps'))
    parser.add_argument('--days', type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.days <= 31:
        parser.error('--days muss zwischen 1 und 31 liegen')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    result = update(args.output, args.cache, days=args.days)
    LOG.info('%d Kartenpaare; neueste Gültigkeit %s', len(result['maps']), result['latest'])
    if result['source_errors']:
        LOG.warning('%d Quellenfehler (siehe Manifest)', len(result['source_errors']))


if __name__ == '__main__':
    main()
