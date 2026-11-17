#!/usr/bin/env python3
"""Validate every published calendar shard against its manifest and rank contract."""
import argparse
import gzip
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from build_regional_calendar_archive import FORMAT
from build_rekordlabor_regional_calendar import METRICS, QC_VERSION, TOP_K
from update_station_records import AREAS


def verify_daily_coverage(coverage, first, end):
    day=date(max(first,1901),1,1)
    end=date.fromisoformat(end)
    while day<=end:
        key=day.isoformat()
        if key not in coverage: raise ValueError(f'Kalendertag fehlt: {key}')
        metrics=coverage[key]
        if not (metrics-{'rs_high'}): raise ValueError(f'KL fehlt: {key}')
        if 'rs_high' not in metrics: raise ValueError(f'RR fehlt: {key}')
        day+=timedelta(days=1)


def verify_archive(root: Path, full=False):
    m = json.loads((root/'manifest.json').read_text())
    def require(condition, message):
        if not condition: raise ValueError(message)
    require(m['version']==FORMAT and m['quality_version']==QC_VERSION, 'Unbekannte Archivversion')
    require(m['metrics']==METRICS and m['areas']==AREAS and m['top_k_per_year']==TOP_K, 'Falsches Schema')
    if full:
        require(not m['pilot'], 'Pilot darf nicht als Vollarchiv veröffentlicht werden')
        require(set(range(max(1901,m['first']),m['last']+1)) <= set(m['years']), 'Archivjahre fehlen')
        require(set(range(max(1901,m['first']),m['last']+1)) == set(m['contrast_qc_years']), 'QC-Jahre fehlen')
        require(set(m['sources'])=={'rr','kl'}, 'Messnetz fehlt')
        for network,stats in m['sources'].items():
            require(stats['archives']==stats['parsed']+stats['skipped'] and stats['observations']>0, f'Unvollständiges Messnetz: {network}')
    require(set(m['days'])==set(m['files']), 'Kalendertage und Manifest unterscheiden sich')
    require({p.name for p in root.glob('*.json.gz')}=={day+'.json.gz' for day in m['days']}, 'Unerwartete Dateien')
    seen_years=set(); count=0; coverage={}
    for day in m['days']:
        p = root / (day+'.json.gz')
        data = p.read_bytes()
        require(len(data)==m['files'][day]['bytes'] and hashlib.sha256(data).hexdigest()==m['files'][day]['sha256'], f'Checksum: {day}')
        rows=json.loads(gzip.decompress(data))
        prev_year=0
        for year,metrics in rows:
            require(m['first']<=year<=m['last'] and year>prev_year, f'Jahresreihenfolge {day}')
            full_date=date.fromisoformat(f'{year}-{day}')
            require(m['data_start']<=full_date.isoformat()<=m['data_end'], f'Datum außerhalb des Manifests {full_date}')
            prev_year=year;seen_years.add(year)
            coverage[full_date.isoformat()]=set(metrics)
            for metric,areas in metrics.items():
                require(metric in METRICS, f'Unbekannter Parameter {metric}')
                direction=METRICS[metric]['direction']
                require('Deutschland' in areas, f'Deutschland fehlt {full_date} {metric}')
                for area,records in areas.items():
                    require(area in AREAS and 0<len(records)<=TOP_K, f'Unzulässige Rangliste {full_date} {area}')
                    count+=len(records)
                    seen=set(); previous=None
                    for value,index,preliminary in records:
                        require(type(value) is int and type(index) is int and 0<=index<len(m['stations']) and preliminary in (0,1), f'Ungültiger Datensatz {full_date}')
                        station=m['stations'][index]
                        require(station['network']==('rr' if metric=='rs_high' else 'kl'), f'Falsches Messnetz {metric}')
                        if full:
                            require(station['state'] in AREAS[1:], f'Nicht verifizierter deutscher Standort {station["id"]}')
                        if full and area!='Deutschland':
                            require(station['state']==area, f'Falsches Bundesland {station["id"]}')
                        require(station['id'] not in seen, f'Doppeltes Stationsereignis {full_date} {metric}')
                        seen.add(station['id'])
                        current=(-value if direction=='desc' else value,station['id'])
                        require(previous is None or previous<=current, f'Falsche Rangfolge {full_date} {metric}')
                        previous=current
    require(seen_years==set(m['years']), 'Jahre in Datensätzen und Manifest unterscheiden sich')
    require(count==m['candidate_count'], 'Kandidatenzahl stimmt nicht')
    if full and m['last']>=1901:
        # Recent KL and RR feeds can differ by a few days. Never silently accept
        # gaps in a closed historical year, or before the latest common day.
        end=f'{m["last"]}-12-31'
        if m['last']==date.today().year:
            end=min(max(d for d,v in coverage.items() if 'rs_high' in v),
                    max(d for d,v in coverage.items() if v-{'rs_high'}))
            require(date.fromisoformat(end)>=date.today()-timedelta(days=7), 'Aktuelle Messdaten mehr als sieben Tage verzögert')
        verify_daily_coverage(coverage,m['first'],end)
    return m


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--full',action='store_true')
    a=p.parse_args();m=verify_archive(a.root,a.full)
    print(f'Verifiziert: {len(m["years"])} Jahre, {len(m["days"])} Kalendertage, {m["candidate_count"]:,} Rekordkandidaten')
