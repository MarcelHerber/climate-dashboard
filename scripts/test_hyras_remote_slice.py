#!/usr/bin/env python3
from __future__ import annotations

import numpy as np
import xarray as xr
import fsspec

URL = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_mean/tas_hyras_1_2020_v6-1_de.nc"
TARGET_DATE = np.datetime64("2020-08-21")


def main() -> int:
    print("Teste HTTP-Range-Zugriff auf HYRAS-NetCDF …", flush=True)
    with fsspec.open(
        URL,
        mode="rb",
        block_size=2 * 1024 * 1024,
        cache_type="readahead",
    ) as remote:
        with xr.open_dataset(remote, engine="h5netcdf", decode_times=True) as ds:
            da = ds["tas"] if "tas" in ds.data_vars else next(iter(ds.data_vars.values()))
            td = next(d for d in da.dims if d.lower() == "time")
            dates = da[td].values.astype("datetime64[D]")
            matches = np.where(dates == TARGET_DATE)[0]
            if len(matches) != 1:
                raise RuntimeError(f"Zieldatum nicht eindeutig gefunden: {TARGET_DATE}")
            day = da.isel({td: int(matches[0])}).load()
            arr = np.asarray(day.values, dtype=np.float32)
            arr[arr > 100] -= 273.15
            print("Remote-Slice OK")
            print("Datum:", str(TARGET_DATE))
            print("Form:", arr.shape)
            print("Mittel:", round(float(np.nanmean(arr)), 3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
