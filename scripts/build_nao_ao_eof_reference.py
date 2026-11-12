#!/usr/bin/env python3
"""Reproducible reference EOF patterns for experimental ECMWF NAO/AO indices.

AO: leading covariance EOF of NCEP/NCAR R1 1000-hPa monthly anomalies north
of 20N (1979-2000), approximately reproducing CPC's AO construction.
NAO: leading Atlantic-domain EOF of R1 Z500 anomalies (1950-2000), not
CPC's seasonally varying rotated, multivariate REOF regression.

Both modes are trained and scaled against observed CPC monthly averages and
independently checked over 2001-2020; never label them as official CPC indices.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import netCDF4
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis/Monthlies/pressure/hgt.mon.mean.nc"
OUT = ROOT / "data" / "nao_ao_forecast" / "eof_reference.json"


def normalized_corr(a, b):
    x=np.asarray(a,dtype=float);y=np.asarray(b,dtype=float)
    if len(x)<12 or np.std(x)<=0 or np.std(y)<=0:return float("nan")
    return float(np.corrcoef(x,y)[0,1])


def observations():
    sys.path.insert(0,str(ROOT/"scripts"))
    from update_climate_indices import download, parse_daily_csv, monthly_means, SOURCES
    result={}
    for index in ("ao","nao"):
        daily=parse_daily_csv(download(SOURCES[index]),index.upper())
        result[index]={row[0]:float(row[1]) for row in monthly_means(daily)}
    return result


def read_ncep():
    with netCDF4.Dataset(SOURCE) as f:
        lats=np.asarray(f.variables["lat"][:],dtype=float)
        lons=np.asarray(f.variables["lon"][:],dtype=float)
        levels=np.asarray(f.variables["level"][:],dtype=float)
        raw_time=f.variables["time"]
        times=netCDF4.num2date(raw_time[:],units=raw_time.units,calendar=getattr(raw_time,"calendar","standard"))
        years=np.asarray([int(t.year) for t in times])
        months=np.asarray([int(t.month) for t in times])
        keep=np.flatnonzero((years>=1950)&(years<=2020))
        assert len(keep)==71*12 and np.all(np.diff(keep)==1), "Incomplete 1950-2020 NCEP monthly series"
        start,end=int(keep[0]),int(keep[-1])+1
        fields={}
        for level in (500,1000):
            ix=np.where(levels==level)[0]
            assert len(ix)==1
            heights=np.ma.filled(f.variables["hgt"][start:end,int(ix[0]),:29,:],np.nan)
            heights=np.asarray(heights,dtype=np.float32)
            if not np.isfinite(heights).all() or heights.min()<-1000 or heights.max()>12000:
                raise RuntimeError(f"NCEP {level} hPa geopotential fields are invalid")
            fields[level]=heights
    return years[keep],months[keep],lats[:29],lons,fields


def build():
    years,months,lats,lons,fields=read_ncep()
    ref_cpc=observations()
    products={}
    for name,level,baseline,lon_window in (
        ("ao",1000,(1979,2000),None),
        ("nao",500,(1950,2000),(-90,40)),
    ):
        lon_mask=np.ones(len(lons),dtype=bool) if lon_window is None else (
            ((lons+180)%360-180>=lon_window[0]) &
            ((lons+180)%360-180<=lon_window[1])
        )
        lon_indices=np.flatnonzero(lon_mask)
        # Full latitude range 90 to 20 N; area weighting removes pole singularity.
        z=fields[level][:,:,lon_indices].astype(np.float64)
        train=(years>=baseline[0])&(years<=baseline[1])
        if train.sum()!=(baseline[1]-baseline[0]+1)*12:raise RuntimeError("NCEP missing calibration months")
        climatology=np.stack([
            np.mean(z[train & (months==month)],axis=0) for month in range(1,13)
        ])
        anomalies=z-climatology[months-1]
        # Weighted EOF: solve in time-space dual to avoid 4k-by-4k covariance.
        area=np.sqrt(np.clip(np.cos(np.deg2rad(lats)),0,1))[:,None] *np.ones((1,len(lon_indices)))
        weighted=anomalies.reshape(len(years),-1)*area.reshape(1,-1)
        training=weighted[train]
        gram=training @ training.T
        eigvals,eigvecs=np.linalg.eigh(gram)
        leading=eigvecs[:,-1]
        # Convert leading PC in time space back to spatial EOF vector.
        eigen=training.T@leading
        eigen=eigen/np.linalg.norm(eigen)
        projection=weighted @ eigen
        dates=np.array([f"{y:04d}-{m:02d}" for y,m in zip(years,months)])
        observed=np.array([ref_cpc[name].get(dt,np.nan) for dt in dates],dtype=float)
        calib=train & np.isfinite(observed)
        holdout=(years>=2001)&(years<=2020)&np.isfinite(observed)
        assert calib.sum()>220 and holdout.sum()>225,(name,calib.sum(),holdout.sum())
        slope,intercept=np.linalg.lstsq(np.column_stack([projection[calib],np.ones(calib.sum())]),
                                            observed[calib],rcond=None)[0]
        pred=projection*slope+intercept
        quality={
            "train_n":int(calib.sum()),
            "train_correlation":round(normalized_corr(pred[calib],observed[calib]),3),
            "holdout_n":int(holdout.sum()),
            "holdout_correlation":round(normalized_corr(pred[holdout],observed[holdout]),3),
            "holdout_rmse":round(float(np.sqrt(np.mean((pred[holdout]-observed[holdout])**2))),3),
            "holdout_bias":round(float(np.mean(pred[holdout]-observed[holdout])),3),
            "training_period":f"{baseline[0]}-{baseline[1]}",
            "validation_period":"2001-2020",
        }
        print(name.upper(),"independent CPC monthly check",quality,flush=True)
        if quality["holdout_correlation"]<.55 or quality["holdout_rmse"]>1.30:
            raise RuntimeError(f"{name.upper()} EOF not sufficiently comparable to CPC: {quality}")
        # Monthly NCEP R1 climatology and spatial EOF are supplied in the file.
        products[name]={
            "pressure_hpa":level,"source_grid_degrees":2.5,
            "latitude_deg_n":np.round(lats,3).tolist(),
            "longitude_deg_e":np.round(lons[lon_indices],3).tolist(),
            "climatology_gpm":np.round(climatology,3).tolist(),
            "weighted_eof":np.round(eigen.reshape(len(lats),len(lon_indices)),8).tolist(),
            "area_weight":np.round(area,8).tolist(),
            "cpc_fit_slope":float(slope),"cpc_fit_intercept":float(intercept),
            "baseline_years":list(baseline),"quality":quality,
            "method":("annual EOF; 1000 hPa anomalies north of 20N" if name=="ao" else
                      "single Atlantic-domain EOF; NOT the official CPC seasonal REOF"),
        }
    doc={"schema":1,"ready":True,"created_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "analysis_source":"NOAA PSL NCEP/NCAR Reanalysis 1 monthly geopotential height",
         "source_url":SOURCE,"observations_source":"NOAA/CPC daily indices aggregated to complete calendar months",
         "provenance":"Eigenberechnung. Diese Muster sind NICHT die originalen CPC-EOF/REOF-Dateien.",
         "validation":"out-of-sample monthly CPC comparison, 2001-2020, fixed 1950/1979-2000 fit",
         "indices":products}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    print("EOF patterns built:",OUT,OUT.stat().st_size,flush=True)
    return doc


if __name__=="__main__":
    build()
