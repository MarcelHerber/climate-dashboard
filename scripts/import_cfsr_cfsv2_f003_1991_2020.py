#!/usr/bin/env python3
"""Import official NCEI monthly CFSR/CFSv2 TMP2M GRIB2 into verified annual samples.

Only 00/06/12/18 UTC initialisations, forecast step +3 hours. A missing or incompatible field fails
the year. No forecast, ERA5, CPC or interpolated *time* values are substituted.

Large NCEI monthly GRIB2 files are streamed to a temporary disk file and
deleted immediately after extracting Europe's 0.5-degree target grid.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time

import numpy as np
import requests

try:
    from scripts.build_gfs_cfsr_f003_1991_2020 import expected_days
except ModuleNotFoundError:  # directly executed as a script
    from build_gfs_cfsr_f003_1991_2020 import expected_days

H, W = 76, 140
TARGET_LAT = 71.75 - np.arange(H) * 0.5
TARGET_LON = (-24.75 + np.arange(W) * 0.5) % 360
OUT = Path("gfs_analysis_europe/reference_sources_f003")
NCEI = "https://www.ncei.noaa.gov/thredds/fileServer"


def product_for_month(year: int, month: int) -> str:
    if not (1991 <= year <= 2020 and 1 <= month <= 12):
        raise ValueError("Outside 1991–2020")
    return "CFSR" if (year, month) < (2011, 4) else "CFSv2"


def source_url(year: int, month: int) -> str:
    ym = f"{year:04d}{month:02d}"
    if product_for_month(year, month) == "CFSR":
        return f"{NCEI}/model-cfs_reanl_ts/{ym}/tmp2m.gdas.{ym}.grb2"
    return f"{NCEI}/model-cfs_v2_anl_ts/{year}/{ym}/tmp2m.gdas.{ym}.grib2"


def alternate_source_urls(year: int, month: int) -> list[str]:
    """The same original high-resolution TMP2M time series, from NCAR GDEX.

    Never use the *.l.gdas (low-resolution) archive as a replacement.
    """
    ym=f"{year:04d}{month:02d}"
    dataset="d093001" if (year, month) < (2011,4) else "d094001"
    filename=(f"tmp2m.gdas.{ym}.grb2" if dataset=="d093001"
              else f"tmp2m.cdas1.{ym}.grb2")
    return [f"https://tds.gdex.ucar.edu/thredds/fileServer/files/g/{dataset}/{year}/{filename}"]


def year_product(year: int) -> str:
    return "CFSR" if year <= 2010 else ("CFSR+CFSv2" if year == 2011 else "CFSv2")


def interpolate_europe(values: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Spatial bilinear interpolation to *fixed* CPC centres; never changes resolution."""
    if values.ndim != 2 or lats.shape != values.shape or lons.shape != values.shape:
        raise ValueError("Unexpected source grid dimensions")
    source_lat = lats[:, 0].astype(np.float64)
    source_lon = lons[0, :].astype(np.float64) % 360
    if (not np.allclose(lats, source_lat[:, None], atol=0.005)
        or not np.allclose(lons % 360, source_lon[None, :], atol=0.005)):
        raise ValueError("Source grid is not regular/gaussian row-major lat-lon")
    # GRIB producers may use south-to-north rows and -180..180 longitudes.
    # Normalize axes before interpolation to avoid shifted country anomalies.
    lat = source_lat
    if np.all(np.diff(lat) > 0):
        lat = lat[::-1]
        values = values[::-1, :]
    if not np.all(np.diff(lat) < 0):
        raise ValueError("Source grid latitude axis is not strictly monotonic")
    lon_order = np.argsort(source_lon)
    lon = source_lon[lon_order]
    values = values[:, lon_order]
    if not np.all(np.diff(lon) > 0):
        raise ValueError("Source grid longitude axis has duplicate or invalid cells")
    if not (lat[-1] < min(TARGET_LAT) < max(TARGET_LAT) < lat[0]):
        raise ValueError("Source latitude grid does not cover Europe")
    # Account for periodicity: 359.75 must interpolate across the dateline.
    long_ext = np.concatenate((lon, [lon[0] + 360]))
    target_lon = TARGET_LON.copy()
    target_lon[target_lon < lon[0]] += 360
    j1 = np.clip(np.searchsorted(-lat, -TARGET_LAT), 1, len(lat)-1)
    j0 = j1 - 1
    i1 = np.searchsorted(long_ext, target_lon, side="right")
    i1 = np.clip(i1, 1, len(long_ext)-1)
    i0 = i1 - 1
    wx = (target_lon - long_ext[i0]) / (long_ext[i1] - long_ext[i0])
    wy = (lat[j0] - TARGET_LAT) / (lat[j0] - lat[j1])
    i0 %= len(lon)
    i1 %= len(lon)
    a, b, c, d = (values[j0[:,None], i0[None,:]], values[j0[:,None], i1[None,:]],
                  values[j1[:,None], i0[None,:]], values[j1[:,None], i1[None,:]])
    upper = a * (1-wx[None,:]) + b * wx[None,:]
    lower = c * (1-wx[None,:]) + d * wx[None,:]
    result = upper * (1-wy[:,None]) + lower * wy[:,None]
    if (result.shape != (H,W) or not np.isfinite(result).all()
        or np.any((result < 170) | (result > 340))):
        raise ValueError("Invalid real 2m temperatures after grid remapping")
    return result.astype(np.float32) - 273.15


def download_original(url: str, target: Path) -> str:
    digest = sha256()
    size = 0
    with requests.get(url, timeout=(45, 150), stream=True, headers={
        "User-Agent": "climate-dashboard/1.0 research CFSR CFSv2",
    }) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > 2_000_000_000:
                    raise ValueError("Monthly source exceeds 2GB safety cap")
                digest.update(chunk)
                f.write(chunk)
    if size < 1_000_000:
        raise ValueError(f"Incomplete original NCEI GRIB2: {size} bytes")
    return digest.hexdigest()


def decode_month(path: Path, year: int, month: int) -> dict[date, np.ndarray]:
    import eccodes as ec

    values: dict[date, dict[int, np.ndarray]] = {}
    # Select the same genuine +3h CFS model forecast for all 30 reference years.
    with path.open("rb") as f:
        while (gid := ec.codes_grib_new_from_file(f)) is not None:
            try:
                def get(k):
                    return ec.codes_get(gid, k)
                if (int(get("edition")) != 2 or int(get("discipline")) != 0
                    or int(get("parameterCategory")) != 0
                    or int(get("parameterNumber")) != 0
                    or str(get("typeOfLevel")) != "heightAboveGround"
                    or int(get("level")) != 2 or int(get("forecastTime")) != 3):
                    continue
                if str(get("stepRange")) not in ("3", "3-3"):
                    continue
                cycle = int(get("dataTime")) // 100
                d = date.fromisoformat(str(int(get("dataDate"))))
                if d.year != year or d.month != month or cycle not in (0,6,12,18):
                    continue
                if (int(get("dataTime")) != 100 * cycle
                    or int(get("validityDate")) != int(get("dataDate"))
                    or int(get("validityTime")) != 100 * cycle + 300):
                    continue
                ni, nj = int(get("Ni")), int(get("Nj"))
                temp = np.asarray(ec.codes_get_values(gid), dtype=np.float32).reshape(nj,ni)
                latitude = np.asarray(ec.codes_get_array(gid,"latitudes")).reshape(nj,ni)
                longitude = np.asarray(ec.codes_get_array(gid,"longitudes")).reshape(nj,ni)
                field = interpolate_europe(temp,latitude,longitude)
                row = values.setdefault(d,{})
                if cycle in row:
                    raise ValueError(f"Duplicate f003 CFS 2m field {d} {cycle} UTC")
                row[cycle] = field
            finally:
                ec.codes_release(gid)
    result: dict[date,np.ndarray] = {}
    ndays = calendar.monthrange(year,month)[1]
    for day in range(1,ndays+1):
        d = date(year,month,day)
        hours = values.get(d,{})
        if set(hours) != {0,6,12,18}:
            raise ValueError(
                f"{d}: expected 4 genuine CFS TMP2M step=3 samples; "
                f"found {sorted(hours)}. Archive may only contain short forecasts."
            )
        if (d.month,d.day) != (2,29):
            result[d] = np.stack([hours[h] for h in (0,6,12,18)])
    return result


def import_year(year: int, output: Path = OUT) -> Path:
    if not 1991 <= year <= 2020:
        raise ValueError("Reference year must be 1991–2020")
    days, provenance = {}, []
    for month in range(1,13):
        original_url=source_url(year,month)
        urls=[original_url]+alternate_source_urls(year,month)
        print(f"Reading verified original {year}-{month:02d}: {original_url}",flush=True)
        with tempfile.TemporaryDirectory(prefix="ncei-cfs-") as dirname:
            source=Path(dirname)/"tmp2m.grib2"
            fields=None
            failure_messages=[]
            for url in urls:
                for attempt in range(3):
                    try:
                        checksum=download_original(url,source)
                        fields=decode_month(source,year,month)
                        print(f"Verified official original {year}-{month:02d}: {url}",flush=True)
                        break
                    except requests.HTTPError as exc:
                        failure_messages.append(f"{url}: {exc}")
                        # Missing NOAA original => move to same high-res series at NCAR.
                        if exc.response is not None and exc.response.status_code in (404,410):
                            print(f"Original missing at this archive, checking other official high-res host: {url}",flush=True)
                            break
                        if attempt==2: break
                        time.sleep(10*(attempt+1))
                    except (OSError, requests.RequestException) as exc:
                        failure_messages.append(f"{url}: {exc}")
                        if attempt==2: break
                        time.sleep(10*(attempt+1))
                if fields is not None:
                    break
            if fields is None:
                raise RuntimeError(f"No complete original high-res CFS TMP2M month {year}-{month:02d}. "
                                   + " | ".join(failure_messages[-5:]))
            days.update(fields)
        provenance.append({
            "month":month,
            "product":product_for_month(year,month),
            "primary_source_url":url,
            "primary_source_sha256":checksum,
            "days":len(fields),
        })
    keys = expected_days(year)
    if sorted(d.isoformat() for d in days) != keys:
        raise ValueError(f"Missing or duplicated CFS days in {year}")
    out = output / f"t2m_6h_{year}.npz"
    out.parent.mkdir(parents=True,exist_ok=True)
    meta = {
        "year":year, "product":year_product(year),
        "hours_utc":[3,9,15,21],"cycles_utc":[0,6,12,18],"forecast_hour":3,
        "parameter":"2m temperature", "units":"degC",
        "primary_source_url":provenance[0]["primary_source_url"],
        "primary_source_sha256":provenance[0]["primary_source_sha256"],
        "source_files":provenance,
        "remapping":"bilinear spatial to 76x140 CPC-centred 0.5deg Europe grid",
    }
    arr=np.stack([days[date.fromisoformat(day)] for day in keys])
    np.savez_compressed(out,temp_c=arr.astype(np.float32),
                        dates=np.asarray(keys),metadata_json=json.dumps(meta))
    print("Verified CFS reference input:",out,arr.shape,flush=True)
    return out


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--year",type=int,required=True)
    parser.add_argument("--output",type=Path,default=OUT)
    args=parser.parse_args()
    import_year(args.year,args.output)
