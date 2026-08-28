from __future__ import annotations

import gzip
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np

from era5_temperature_rank import (
    RANK_BOUNDARIES,
    RANK_CLASS_LABELS,
    RANK_COLORS,
    area_weighted_fraction,
    combine_history_temperature,
    decode_temperature_pack_values,
    temperature_rank_field,
)

ROOT=Path(__file__).resolve().parents[1]
INDEX_PATH=ROOT/'era5_land_europe'/'index.json'
HISTORY_INDEX_PATH=ROOT/'era5_land_europe'/'history_0p1'/'index.json'
CORE_PATH=ROOT/'scripts'/'update_era5_land_europe.py'
CACHE_DIR=ROOT/'.era5_cache'
MAP_DIR=ROOT/'era5_land_europe'/'maps'


class NoCDSClient:
    def retrieve(self,*args,**kwargs):
        raise RuntimeError('CACHE-ONLY: CDS-Zugriff ist für die Rangkarten gesperrt.')


def load_module(path:Path,name:str):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Modul konnte nicht geladen werden: {path}')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


def latest_complete_key(payload:dict)->tuple[int,int]:
    match=re.fullmatch(r'(\d{4})-(\d{2})',str(payload.get('latest_month_key') or ''))
    if not match:
        raise RuntimeError('latest_month_key fehlt oder ist ungültig.')
    year,month=int(match.group(1)),int(match.group(2))
    if not 1<=month<=12:
        raise RuntimeError(f'Ungültiger Monat: {month}')
    return year,month


def current_temperature_targets(payload:dict)->list[dict]:
    year,latest_month=latest_complete_key(payload)
    periods=payload.get('periods') if isinstance(payload.get('periods'),dict) else {}
    ids=['latest_month','summer']+[f'month_{m:02d}' for m in range(1,latest_month+1)]
    targets=[]
    for period_id in ids:
        period=periods.get(period_id)
        if not isinstance(period,dict) or period.get('historical_only'):
            continue
        try:
            period_year=int(period.get('year'))
        except (TypeError,ValueError):
            continue
        months=[int(m) for m in period.get('months',[])]
        if period_year!=year or not months or any(m<1 or m>latest_month for m in months):
            continue
        if not isinstance(period.get('temperature'),dict):
            continue
        targets.append({'id':period_id,'label':str(period.get('label') or period_id),'year':period_year,'months':months})
    return targets


def _current_cache_file(year:int,months:list[int])->Path:
    return CACHE_DIR/f"current_{year}_{'_'.join(f'{m:02d}' for m in months)}.nc"


def assert_cache_ready(year:int,latest_month:int)->None:
    months=list(range(1,latest_month+1));current=_current_cache_file(year,months)
    if not current.exists():
        raise RuntimeError(f'CACHE-ONLY: benötigte aktuelle ERA5-Datei fehlt: {current.name}')
    if not HISTORY_INDEX_PATH.exists():
        raise RuntimeError(f'0,1°-Historienindex fehlt: {HISTORY_INDEX_PATH}')


def load_history_temperature_month(archive:dict,month:int)->tuple[np.ndarray,np.ndarray,dict]:
    meta=((archive.get('variables') or {}).get('temperature') or {}).get(f'{month:02d}')
    if not isinstance(meta,dict):
        raise RuntimeError(f'0,1°-Temperaturhistorie für Monat {month:02d} fehlt.')
    path=ROOT/str(meta.get('file') or '')
    if not path.exists():
        raise RuntimeError(f'Historienpack fehlt: {path}')
    with gzip.open(path,'rb') as fh:
        raw=fh.read()
    values=decode_temperature_pack_values(raw,meta)
    years=np.arange(int(meta['year_start']),int(meta['year_end'])+1,dtype=int)
    if values.shape[0]!=years.size:
        raise RuntimeError(f'Historienjahre/Packgröße für Monat {month:02d} stimmen nicht überein.')
    return years,values,meta


def history_temperature_period(archive:dict,months:list[int])->tuple[np.ndarray,np.ndarray,dict]:
    month_fields={};years_ref=None;meta_ref=None
    for month in months:
        years,values,meta=load_history_temperature_month(archive,month)
        if years_ref is None:
            years_ref=years;meta_ref=meta
        elif not np.array_equal(years_ref,years):
            raise RuntimeError('Historienjahre der Temperaturmonate sind nicht deckungsgleich.')
        month_fields[month]=values
    assert years_ref is not None and meta_ref is not None
    combined=combine_history_temperature(month_fields,years_ref,months)
    return years_ref,combined,meta_ref


def rank_style(total:int):
    from matplotlib.colors import BoundaryNorm,ListedColormap
    total=max(1,int(total))
    ranges=[
        (1,1),(2,2),(3,3),(4,9),(10,20),(21,40),(41,60),(61,76),(77,None),
    ]
    colors=[]
    labels=[]
    ticks=[]
    boundaries=[0.5]
    for index,(start,end) in enumerate(ranges):
        if start>total:
            break
        stop=total if end is None else min(int(end),total)
        if stop<start:
            continue
        colors.append(RANK_COLORS[index])
        labels.append(str(start) if start==stop else f'{start}–{stop}')
        ticks.append((start+stop)/2.0)
        boundaries.append(float(stop)+0.5)
    cmap=ListedColormap(colors,name='era5_europe_temperature_rank')
    norm=BoundaryNorm(boundaries,cmap.N,clip=True)
    return cmap,norm,boundaries,ticks,labels


def render_rank_map(core,rank:np.ndarray,lat:np.ndarray,lon:np.ndarray,*,label:str,year:int,history_start:int,history_end:int,filename:Path,total_rank_positions:int|None=None)->None:
    filename.parent.mkdir(parents=True,exist_ok=True)
    core.cartopy.config['data_dir']=str(core.CARTOPY_DIR);core.CARTOPY_DIR.mkdir(parents=True,exist_ok=True)
    total=int(total_rank_positions) if total_rank_positions is not None else history_end-history_start+2
    cmap,norm,boundaries,ticks,labels=rank_style(total)
    fig=core.plt.figure(figsize=(13.2,8.1),dpi=150)
    ax=fig.add_axes([0.07,0.18,0.89,0.66],projection=core.ccrs.PlateCarree())
    ax.set_extent([core.AREA[1],core.AREA[3],core.AREA[2],core.AREA[0]],crs=core.ccrs.PlateCarree())
    data=np.ma.masked_invalid(np.asarray(rank,dtype=float))
    mesh=ax.pcolormesh(lon,lat,data,transform=core.ccrs.PlateCarree(),cmap=cmap,norm=norm,shading='auto')
    ax.add_feature(core.cfeature.COASTLINE.with_scale('50m'),linewidth=.55,edgecolor='#39434a')
    ax.add_feature(core.cfeature.BORDERS.with_scale('50m'),linewidth=.4,edgecolor='#66727a')
    ax.add_feature(core.cfeature.LAKES.with_scale('50m'),facecolor='#f4f7f8',edgecolor='#89949a',linewidth=.25,zorder=3)
    ax.set_facecolor('#eef3f5')
    gl=ax.gridlines(draw_labels=True,linewidth=.25,color='#7f8c92',alpha=.45,linestyle='--');gl.top_labels=False;gl.right_labels=False;gl.xlabel_style={'size':8,'color':'#59656c'};gl.ylabel_style={'size':8,'color':'#59656c'}
    cax=fig.add_axes([0.14,0.085,0.75,0.032])
    cbar=core.plt.colorbar(mesh,cax=cax,orientation='horizontal',boundaries=boundaries,ticks=ticks,spacing='uniform')
    cbar.set_label(f'Historischer Temperaturrang {history_start}–{year} · 1 = wärmster',fontsize=10);cbar.ax.tick_params(labelsize=7);cbar.ax.set_xticklabels(labels)
    fig.suptitle(f'ERA5-Land Europa · Historischer Temperaturrang · {label}',x=.075,y=.97,ha='left',va='top',fontsize=17,fontweight='bold')
    fig.text(.075,.925,f'Rang jedes 0,1°-Gitterpunkts · Vergleich {history_start}–{year} · Rang 1 = wärmster Wert',ha='left',va='top',fontsize=10,color='#56636a')
    fig.text(.075,.025,'Quelle: Copernicus Climate Change Service / ECMWF · ERA5-Land · 0,1° · Historie verlustarm quantisiert',ha='left',va='bottom',fontsize=8,color='#68757c')
    core.plt.savefig(filename,facecolor='white');core.plt.close(fig)


def main()->int:
    payload=json.loads(INDEX_PATH.read_text(encoding='utf-8'))
    year,latest_month=latest_complete_key(payload);targets=current_temperature_targets(payload)
    if not targets:
        raise RuntimeError('Keine aktuellen Temperaturzeiträume für Rangkarten gefunden.')
    assert_cache_ready(year,latest_month)
    archive=json.loads(HISTORY_INDEX_PATH.read_text(encoding='utf-8'))
    core=load_module(CORE_PATH,'update_era5_land_europe_rank_cache_only')
    months_all=list(range(1,latest_month+1));current=core.load_current_months(NoCDSClient(),year,months_all,False)
    print('=== ERA5-LAND · HISTORISCHE TEMPERATUR-RANGKARTEN · CACHE-ONLY ===')
    print(f'Jahr {year} · Historie {archive.get("year_start")}–{archive.get("year_end")} · CDS-Zugriff gesperrt')
    for target in targets:
        pmonths=target['months'];lat=np.asarray(current[pmonths[0]][0],dtype=float);lon=np.asarray(current[pmonths[0]][1],dtype=float)
        current_temp=core.combine_temperature({m:current[m][2] for m in pmonths},year,pmonths)
        years,history,_=history_temperature_period(archive,pmonths)
        if history.shape[1:]!=current_temp.shape:
            raise RuntimeError(f'0,1°-Gitter stimmt für {target["id"]} nicht überein: Historie {history.shape[1:]} vs aktuell {current_temp.shape}')
        rank=temperature_rank_field(current_temp,history);valid=np.isfinite(rank)
        rank1=area_weighted_fraction(rank<=1,valid,lat);top3=area_weighted_fraction(rank<=3,valid,lat)
        filename=MAP_DIR/f'temperature_{target["id"]}_rank.png'
        render_rank_map(core,rank,lat,lon,label=target['label'],year=year,history_start=int(years[0]),history_end=int(years[-1]),filename=filename)
        period=payload['periods'][target['id']];temperature=period['temperature']
        temperature['rank']={
            'file':filename.relative_to(ROOT).as_posix(),'unit':'Rang','label':f'Historischer Rang {int(years[0])}–{year}',
            'history_start':int(years[0]),'history_end':year,'rank_direction':'1 = wärmster',
            'note':f'Historischer Temperaturrang am 0,1°-Gitterpunkt für denselben Zeitraum {int(years[0])}–{year}. Rang 1 ist der wärmste Wert; die Historienfelder stammen aus dem kompakten 0,1°-Archiv.',
            'stats':{'rank_area_percent':rank1,'top3_area_percent':top3,'valid_gridpoints':int(valid.sum())},
        }
        print(f'Render: {target["id"]} · Rang 1 Fläche {rank1:.2f}% · Top 3 {top3:.2f}%')
        del history,rank
    core.atomic_write_json(INDEX_PATH,payload)
    print(f'Fertig: {len(targets)} Temperatur-Rangkarten erzeugt und index.json aktualisiert.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
