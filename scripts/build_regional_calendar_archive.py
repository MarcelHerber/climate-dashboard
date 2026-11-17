#!/usr/bin/env python3
"""Build a disjoint DWD calendar archive epoch. Outputs are date-addressable gzip JSON."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dwd_common import download
from update_station_records import (
    HISTORICAL_URL, HISTORICAL_PATTERN, RECENT_URL, RECENT_PATTERN, METADATA_URL,
    STATION_ID_PATTERN, RR_HISTORICAL_URL, RR_HISTORICAL_PATTERN, RR_RECENT_URL,
    RR_RECENT_PATTERN, RR_METADATA_URL, RR_STATION_ID_PATTERN, AREAS,
    NoUsableProductFileError, parse_metadata, list_station_files, download_station_zip,
)
from build_rekordlabor_regional_calendar import (
    METRICS, QC_VERSION, TOP_K, RegionalAccumulator, parse_kl_zip,
    parse_rr_zip, load_temperature_exclusions,
)

FORMAT = 'regional-calendar-v1'


def archive_files(files, first, last):
    result = []
    for name in files:
        match = re.search(r'_(\d{4})\d{4}_(\d{4})\d{4}_hist\.zip$', name, re.I)
        if not match:
            raise ValueError(f'Nicht erkannter Archivzeitraum: {name}')
        if int(match[1]) <= last and int(match[2]) >= first:
            result.append(name)
    return result


def checked_exclusions(root, first, last):
    for year in range(max(1901, first), last + 1):
        if not (root / str(year) / 'quality.json.gz').is_file():
            raise ValueError(f'Temperatur-QC-Audit fehlt: {year}')
    return load_temperature_exclusions(root, first, last)


def namespace_observations(rows, network):
    # The DWD RR directory also includes several Austrian stations. Only
    # metadata-confirmed German locations qualify for national or state ranks.
    return (replace(o, metadata_key=f'{network}:{o.metadata_key}') for o in rows
            if o.state in AREAS[1:])


def _compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def write_archive(accumulator, output, first, last, metadata):
    """Write each calendar-day shard in year order; avoid loading an epoch in RAM."""
    output.mkdir(parents=True, exist_ok=False)
    station_indexes = {}
    stations = []
    years = []
    days = set()
    candidate_count = 0
    data_start = data_end = None

    def station_index(key):
        if key not in station_indexes:
            station_indexes[key] = len(stations)
            network, raw_key = key.split(':', 1)
            sid = raw_key.split(':', 1)[0]
            stations.append({'key':key, 'network':network, **metadata.get(key, {
                'id':sid,'name':f'Station {sid}','state':None,'lat':None,'lon':None,'height':None,
            })})
        return station_indexes[key]

    with tempfile.TemporaryDirectory(prefix='calendar-shards-', dir=output.parent) as work:
        scratch = Path(work)
        for year in range(first, last+1):
            yearly = accumulator.records(year)
            if not yearly:
                continue
            years.append(year)
            for day, metrics in sorted(yearly.items()):
                days.add(day)
                full_date = f'{year}-{day}'
                data_start = data_start or full_date
                data_end = full_date
                compact = {}
                for metric, areas in metrics.items():
                    compact[metric] = {}
                    for area, rows in areas.items():
                        compact[metric][area] = [[int(round(value*10)), station_index(key), preliminary]
                                                  for value, _, key, preliminary in rows]
                        candidate_count += len(rows)
                with (scratch / day).open('a', encoding='utf-8') as f:
                    f.write(_compact_json([year, compact])+'\n')
            print(f'Archivjahr {year}: {len(yearly)} Tage', flush=True)
        if not years:
            raise ValueError('Keine verwertbaren Messwerte im angeforderten Zeitraum')
        files = {}
        for day in sorted(days):
            path = output / f'{day}.json.gz'
            with path.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as dst:
                dst.write(b'[')
                with (scratch / day).open('rb') as src:
                    for i, line in enumerate(src):
                        if i: dst.write(b',')
                        dst.write(line.rstrip(b'\n'))
                dst.write(b']')
            files[day] = {'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return {'version':FORMAT,'quality_version':QC_VERSION,'first':first,'last':last,
            'data_start':data_start,'data_end':data_end,'years':years,'days':sorted(days),
            'metrics':METRICS,'areas':AREAS,'top_k_per_year':TOP_K,'value_scale':0.1,
            'columns':['value_tenths','station_index','preliminary'], 'stations':stations,
            'candidate_count':candidate_count,'files':files}


def build(args):
    today = datetime.now(timezone.utc).date()
    start, end = date(args.first,1,1), min(date(args.last,12,31), today-timedelta(days=1))
    if start > end:
        raise ValueError('Ungültiger Zeitraum')
    excluded = checked_exclusions(args.qc_root, args.first, args.last)
    metadata = {}; sources = {}; skipped = []
    specs = [
        ('kl',METADATA_URL,HISTORICAL_URL,HISTORICAL_PATTERN,RECENT_URL,RECENT_PATTERN,STATION_ID_PATTERN,parse_kl_zip,500,300),
        ('rr',RR_METADATA_URL,RR_HISTORICAL_URL,RR_HISTORICAL_PATTERN,RR_RECENT_URL,RR_RECENT_PATTERN,RR_STATION_ID_PATTERN,parse_rr_zip,4000,1500),
    ]
    with tempfile.TemporaryDirectory(prefix='regional-calendar-db-',dir=args.work) as tmp:
        accumulator = RegionalAccumulator(Path(tmp)/'observations.sqlite', excluded)
        try:
            for network,meta_url,hist,hist_pat,recent,recent_pat,sid_pat,parser,hmin,rmin in specs:
                index = parse_metadata(download(meta_url))
                metadata.update({f'{network}:{k}':v for k,v in index.public_dict().items()})
                historical = archive_files(list_station_files(hist,hist_pat,hmin),args.first,args.last)
                jobs = [(hist,name,False) for name in historical]
                if args.last >= today.year-2:
                    jobs.extend((recent,name,True) for name in list_station_files(recent,recent_pat,rmin))
                if args.station:
                    jobs = [j for j in jobs if sid_pat.search(j[1])[1] in args.station]
                if args.limit:
                    jobs = jobs[:args.limit]
                if not jobs:
                    raise ValueError(f'Keine {network} Dateien für {args.first}–{args.last}')
                stats = {'archives':len(jobs),'parsed':0,'skipped':0,'observations':0,'geographic_exclusions':0}
                print(f'{network}: {len(jobs)} Archive',flush=True)
                def process(job):
                    url,name,preliminary = job
                    sid = sid_pat.search(name)[1]
                    content = download_station_zip(url,name)
                    try:
                        return parser(content,sid,index,start,end,preliminary),None
                    except NoUsableProductFileError as exc:
                        return [],f'{name}: {exc}'
                # Ordered results make historical-overlap tie handling deterministic.
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    for offset in range(0,len(jobs),args.workers*3):
                        for rows,reason in pool.map(process,jobs[offset:offset+args.workers*3]):
                            if reason:
                                skipped.append({'network':network,'reason':reason}); stats['skipped']+=1
                            else:
                                stats['parsed']+=1
                                accepted=list(namespace_observations(rows,network))
                                stats['geographic_exclusions']+=len(rows)-len(accepted)
                                stats['observations']+=len(accepted)
                                accumulator.add_many(accepted,network)
                        if offset%(args.workers*3*10)==0 or offset+args.workers*3>=len(jobs):
                            print(f'{network}: {min(offset+args.workers*3,len(jobs))}/{len(jobs)}; {stats["observations"]:,} Messzeilen',flush=True)
                sources[network]=stats
            manifest = write_archive(accumulator,args.out,args.first,args.last,metadata)
        finally:
            accumulator.close()
    manifest.update({'built_at':datetime.now(timezone.utc).isoformat(),'sources':sources,
                     'skipped_archives':skipped,'contrast_qc_exclusions':len(excluded),
                     'contrast_qc_years':list(range(max(1901,args.first),args.last+1)),
                     'pilot':bool(args.station or args.limit)})
    (args.out/'manifest.json').write_text(_compact_json(manifest),encoding='utf-8')
    print(f'Fertig: {len(manifest["years"])} Jahre, {len(manifest["days"])} Kalendertage, {manifest["candidate_count"]:,} Kandidaten',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first',type=int,required=True); parser.add_argument('--last',type=int,required=True)
    parser.add_argument('--out',type=Path,required=True); parser.add_argument('--qc-root',type=Path,required=True)
    parser.add_argument('--work',type=Path); parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--station',action='append',default=[]); parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    if args.first<1750 or args.last<args.first or args.last>date.today().year or not 1<=args.workers<=24:
        parser.error('Ungültige Jahresgrenzen oder Anzahl der parallelen Downloads')
    build(args)


if __name__=='__main__': main()
