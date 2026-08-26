#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import gzip
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
import xarray as xr

import scripts.update_hyras_maps as precip
import scripts.build_hyras_temperature_live_reference as temp

REFERENCE_PERIODS = ((1991, 2020), (1961, 1990))
DEFAULT_REFERENCE = (1991, 2020)
TARGET_REFERENCE = (1961, 1990)
MISSING = -32768
TEMP_SCALE = 100


def reference_label(reference: tuple[int, int]) -> str:
    return f"{int(reference[0])}-{int(reference[1])}"


def reference_slug(reference: tuple[int, int]) -> str:
    return reference_label(reference).replace("-", "_")


def daily_reference_cache_path(root: Path, factor: int, reference: tuple[int, int]) -> Path:
    return root / f"hyras_daily_reference_{reference_slug(reference)}_web{factor}_v1.npz"


def temperature_cache_path(root: Path, c: temp.Config, month: int, reference: tuple[int, int]) -> Path:
    return root / f"{c.key}_month_{month:02d}_{reference_slug(reference)}.npz"


def _decode_precip_png(path: Path, scale: int = 10) -> np.ndarray:
    image = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
    valid = image[..., 3] > 0
    q = (
        image[..., 0].astype(np.uint32) * 65536
        + image[..., 1].astype(np.uint32) * 256
        + image[..., 2].astype(np.uint32)
    )
    values = q.astype(np.float32) / float(scale)
    values[~valid] = np.nan
    return values


def _finite_stats(current: np.ndarray, reference: np.ndarray) -> dict[str, float | None]:
    mask = np.isfinite(current) & np.isfinite(reference) & (reference > 0.1)
    if not mask.any():
        return {
            "current_mean_mm": None,
            "reference_mean_mm": None,
            "percent_of_reference": None,
            "anomaly_mean_mm": None,
        }
    cur = float(np.mean(current[mask]))
    ref = float(np.mean(reference[mask]))
    return {
        "current_mean_mm": round(cur, 1),
        "reference_mean_mm": round(ref, 1),
        "percent_of_reference": round(cur / ref * 100.0, 1) if ref else None,
        "anomaly_mean_mm": round(cur - ref, 1),
    }


def _month_segments(start_s: str, end_s: str) -> list[tuple[int, int, int, int]]:
    start = datetime.strptime(start_s, "%Y-%m-%d").date()
    end = datetime.strptime(end_s, "%Y-%m-%d").date()
    out: list[tuple[int, int, int, int]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        last = calendar.monthrange(cursor.year, cursor.month)[1]
        a = start.day if (cursor.year, cursor.month) == (start.year, start.month) else 1
        b = end.day if (cursor.year, cursor.month) == (end.year, end.month) else last
        out.append((cursor.year, cursor.month, a, b))
        cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return out


def _build_precip_monthly_reference(data_root: Path, reference: tuple[int, int]) -> dict[int, Path]:
    label = reference_label(reference)
    target_root = data_root / "historical_1km" / f"reference_{reference_slug(reference)}"
    target_root.mkdir(parents=True, exist_ok=True)
    result: dict[int, Path] = {}
    for month in range(1, 13):
        target = target_root / f"month_{month:02d}.png"
        result[month] = target
        if target.exists():
            continue
        total = None
        count = None
        for year in range(reference[0], reference[1] + 1):
            source = data_root / "historical_1km" / str(year) / f"month_{month:02d}.png"
            if not source.exists():
                raise RuntimeError(f"HYRAS-Niederschlag {label}: historisches Monatsraster fehlt: {source}")
            arr = _decode_precip_png(source)
            if total is None:
                total = np.zeros(arr.shape, dtype=np.float64)
                count = np.zeros(arr.shape, dtype=np.uint16)
            valid = np.isfinite(arr)
            total[valid] += arr[valid]
            count[valid] += 1
        assert total is not None and count is not None
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = (total / np.where(count > 0, count, np.nan)).astype(np.float32)
        precip.encode_precip_png(mean, target)
        print(f"Niederschlag: Monatsreferenz {label} {month:02d} erzeugt", flush=True)
    return result


def _build_precip_daily_reference(
    *, cache_root: Path, work: Path, factor: int, needed_dates: list[str],
    reference: tuple[int, int], expected_width: int, expected_height: int,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    cache_root.mkdir(parents=True, exist_ok=True)
    cache = daily_reference_cache_path(cache_root, factor, reference)
    needed_md: list[tuple[int, int]] = []
    for iso in needed_dates:
        dt = datetime.strptime(iso, "%Y-%m-%d")
        md = (dt.month, dt.day)
        if md not in needed_md:
            needed_md.append(md)
    if cache.exists():
        with np.load(cache, allow_pickle=False) as z:
            daily = np.asarray(z["daily_mean"], dtype=np.float32)
            months = np.asarray(z["months"], dtype=np.int16)
            days = np.asarray(z["days"], dtype=np.int16)
            cached_md = list(zip(months.tolist(), days.tolist()))
        if daily.shape[1:] == (expected_height, expected_width) and all(md in cached_md for md in needed_md):
            print(f"Niederschlag: Tagesreferenz {reference_label(reference)} aus Cache", flush=True)
            return daily, cached_md

    lookup = {md: i for i, md in enumerate(needed_md)}
    sums = np.zeros((len(needed_md), expected_height, expected_width), dtype=np.float32)
    counts = np.zeros((len(needed_md), expected_height, expected_width), dtype=np.uint8)
    listing = precip.directory_text(precip.DAILY_BASE + "/")
    file_map = precip.daily_file_map(listing, range(reference[0], reference[1] + 1))
    ref_work = work / "precip_reference_years"
    ref_work.mkdir(parents=True, exist_ok=True)

    for pos, year in enumerate(range(reference[0], reference[1] + 1), 1):
        filename = file_map[year]
        target = ref_work / filename
        if not target.exists():
            precip.download(f"{precip.DAILY_BASE}/{filename}", target)
        with xr.open_dataset(target, decode_times=True) as ds:
            vals, dates, _x, _y = precip.sample_daily_for_web(precip.pick_precip_var(ds), factor)
        if vals.shape[1:] != (expected_height, expected_width):
            raise RuntimeError(f"Niederschlag: Referenzraster {year} hat falsche Größe {vals.shape[1:]}")
        for i, iso in enumerate(dates):
            dt = datetime.strptime(iso, "%Y-%m-%d")
            idx = lookup.get((dt.month, dt.day))
            if idx is None:
                continue
            arr = vals[i]
            valid = np.isfinite(arr)
            sums[idx][valid] += arr[valid]
            counts[idx][valid] += 1
        target.unlink(missing_ok=True)
        if pos == 1 or pos % 5 == 0 or pos == 30:
            print(f"Niederschlag: Referenz {reference_label(reference)} {pos}/30 Jahre", flush=True)

    with np.errstate(invalid="ignore", divide="ignore"):
        daily = (sums / np.where(counts > 0, counts, np.nan)).astype(np.float32)
    np.savez_compressed(
        cache,
        daily_mean=daily,
        months=np.asarray([m for m, _ in needed_md], dtype=np.int16),
        days=np.asarray([d for _, d in needed_md], dtype=np.int16),
    )
    print(f"Niederschlag: Tagesreferenz gespeichert: {cache}", flush=True)
    return daily, needed_md


def build_precipitation_reference(
    *, data_root: Path, cache_root: Path, work: Path, reference: tuple[int, int] = TARGET_REFERENCE,
    build_reference_only: bool = False,
) -> None:
    index_path = data_root / "hyras_index.json"
    web_path = data_root / "hyras_web_manifest.json"
    hist_path = data_root / "hyras_historical_manifest.json"
    if not index_path.exists() or not web_path.exists() or not hist_path.exists():
        raise RuntimeError("HYRAS-Niederschlagsmanifeste fehlen im hyras-data-Stand")

    web = json.loads(web_path.read_text(encoding="utf-8"))
    dates = list((web.get("current_files") or {}).keys())
    factor = int(web.get("web_sampling_km") or 2)
    daily, template = _build_precip_daily_reference(
        cache_root=cache_root,
        work=work,
        factor=factor,
        needed_dates=dates,
        reference=reference,
        expected_width=int(web["width"]),
        expected_height=int(web["height"]),
    )
    if build_reference_only:
        return

    label = reference_label(reference)
    lookup = {md: i for i, md in enumerate(template)}
    sequence = []
    for iso in dates:
        dt = datetime.strptime(iso, "%Y-%m-%d")
        sequence.append(daily[lookup[(dt.month, dt.day)]])
    stack = np.stack(sequence, axis=0).astype(np.float32)
    mask = np.any(np.isfinite(stack), axis=0)
    cumulative = np.cumsum(np.where(np.isfinite(stack), stack, 0.0), axis=0, dtype=np.float32)
    cumulative[:, ~mask] = np.nan
    files: dict[str, str] = {}
    for i, iso in enumerate(dates):
        rel = f"web/reference_{reference_slug(reference)}/cum_{iso}.png"
        precip.encode_precip_png(cumulative[i], data_root / rel)
        files[iso] = rel
    by_period = dict(web.get("reference_files_by_period") or {})
    by_period[reference_label(DEFAULT_REFERENCE)] = web.get("reference_files") or {}
    by_period[label] = files
    web["reference_files_by_period"] = by_period
    web["references"] = [reference_label(x) for x in REFERENCE_PERIODS]
    web["default_reference"] = reference_label(DEFAULT_REFERENCE)
    web_path.write_text(json.dumps(web, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    monthly = _build_precip_monthly_reference(data_root, reference)
    historical = json.loads(hist_path.read_text(encoding="utf-8"))
    hist_by_period = dict(historical.get("reference_files_by_period") or {})
    hist_by_period[reference_label(DEFAULT_REFERENCE)] = historical.get("reference_files") or {}
    hist_by_period[label] = {str(m): str(monthly[m].relative_to(data_root)).replace("\\", "/") for m in range(1, 13)}
    historical["reference_files_by_period"] = hist_by_period
    historical["references"] = [reference_label(x) for x in REFERENCE_PERIODS]
    historical["default_reference"] = reference_label(DEFAULT_REFERENCE)
    hist_path.write_text(json.dumps(historical, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    idx = json.loads(index_path.read_text(encoding="utf-8"))
    for period in idx.get("periods", []):
        if period.get("daily_live"):
            continue
        segments = _month_segments(str(period.get("start_date")), str(period.get("end_date")))
        if not segments or any(a != 1 or b != calendar.monthrange(y, m)[1] for y, m, a, b in segments):
            continue
        ref_arr = None
        for _year, month, _a, _b in segments:
            arr = _decode_precip_png(monthly[month])
            ref_arr = arr.copy() if ref_arr is None else ref_arr + arr
        if ref_arr is None:
            continue
        interactive = period.setdefault("interactive", {})
        current_rel = interactive.get("current")
        if not current_rel:
            continue
        rel = f"interactive/presets/{period['key']}_reference_{reference_slug(reference)}.png"
        precip.encode_precip_png(ref_arr, data_root / rel)
        refs = dict(interactive.get("references") or {})
        if interactive.get("reference"):
            refs[reference_label(DEFAULT_REFERENCE)] = interactive["reference"]
        refs[label] = rel
        interactive["references"] = refs
        current = _decode_precip_png(data_root / current_rel)
        stats_by_ref = dict(period.get("stats_by_reference") or {})
        stats_by_ref[reference_label(DEFAULT_REFERENCE)] = period.get("stats") or {}
        stats_by_ref[label] = _finite_stats(current, ref_arr)
        period["stats_by_reference"] = stats_by_ref
        period["references"] = [reference_label(x) for x in REFERENCE_PERIODS]

    idx["references"] = [reference_label(x) for x in REFERENCE_PERIODS]
    idx["default_reference"] = reference_label(DEFAULT_REFERENCE)
    idx["reference"] = reference_label(DEFAULT_REFERENCE)
    index_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Niederschlag: Referenz {label} vollständig ergänzt", flush=True)


def latest_temperature_clim(c: temp.Config, month: int, reference: tuple[int, int]) -> str:
    abbr = temp.MONTH_ABBR[month]
    label = reference_slug(reference)
    pat = re.compile(rf'href="(?P<f>{c.prefix}_hyras_1_{label}_v(?P<a>\d+)-(?P<b>\d+)_de_{abbr}\.nc)"')
    items = [
        (int(m.group("a")), int(m.group("b")), m.group("f"))
        for m in pat.finditer(temp.listing(c.clim_base))
    ]
    if not items:
        raise RuntimeError(f"Keine {c.key}-Klimadatei {reference_label(reference)} für {abbr}")
    return sorted(items)[-1][2]


def _build_temperature_month_cache(
    *, c: temp.Config, month: int, cache_root: Path, work: Path,
    expected_x: np.ndarray, expected_y: np.ndarray, reference: tuple[int, int],
) -> np.ndarray:
    cache_root.mkdir(parents=True, exist_ok=True)
    path = temperature_cache_path(cache_root, c, month, reference)
    if path.exists():
        with np.load(path, allow_pickle=False) as z:
            x = np.asarray(z["x"], dtype=float)
            y = np.asarray(z["y"], dtype=float)
            daily = np.asarray(z["daily"], dtype=np.float32)
        if temp.same_grid(x, y, expected_x, expected_y):
            print(f"{c.label}: Tagesreferenz {reference_label(reference)} Monat {month:02d} aus Cache", flush=True)
            return daily

    files = temp.annual_files(c)
    missing = [y for y in range(reference[0], reference[1] + 1) if y not in files]
    if missing:
        raise RuntimeError(f"{c.key}: fehlende Referenzjahre {missing}")
    nd = calendar.monthrange(2000, month)[1]
    sums = np.zeros((nd, len(expected_y), len(expected_x)), dtype=np.float32)
    counts = np.zeros((nd, len(expected_y), len(expected_x)), dtype=np.uint8)
    ref_work = work / f"{c.key}_reference_years"
    ref_work.mkdir(parents=True, exist_ok=True)

    for pos, year in enumerate(range(reference[0], reference[1] + 1), 1):
        fn = files[year]
        target = ref_work / fn
        if not target.exists():
            temp.download(f"{c.daily_base}/{fn}", target)
        with xr.open_dataset(target, decode_times=True) as ds:
            da, tdim, x, y = temp.prep(ds, c)
            dates = da[tdim].values.astype("datetime64[D]")
            for day in range(1, nd + 1):
                try:
                    wanted = np.datetime64(date(year, month, day).isoformat())
                except ValueError:
                    continue
                where = np.flatnonzero(dates == wanted)
                if len(where) != 1:
                    continue
                arr, nx, ny = temp.norm(np.asarray(da.isel({tdim: int(where[0])}).values, np.float32), x, y)
                if not temp.same_grid(nx, ny, expected_x, expected_y):
                    raise RuntimeError(f"{c.key}: Rasterabweichung in {fn}")
                valid = np.isfinite(arr)
                sums[day - 1][valid] += arr[valid]
                counts[day - 1][valid] += 1
        target.unlink(missing_ok=True)
        if pos == 1 or pos % 5 == 0 or pos == 30:
            print(f"{c.label}: Referenz {reference_label(reference)} {pos}/30 Jahre", flush=True)

    daily = np.full(sums.shape, np.nan, dtype=np.float32)
    valid = counts > 0
    daily[valid] = sums[valid] / counts[valid].astype(np.float32)
    np.savez_compressed(path, daily=daily, x=expected_x, y=expected_y)
    print(f"{c.label}: Cache gespeichert: {path}", flush=True)
    return daily


def _temperature_static_month(
    *, c: temp.Config, month: int, reference: tuple[int, int], work: Path,
    expected_x: np.ndarray, expected_y: np.ndarray,
) -> np.ndarray:
    fn = latest_temperature_clim(c, month, reference)
    target = work / "clim" / fn
    if not target.exists():
        temp.download(f"{c.clim_base}/{fn}", target)
    arr, x, y = temp.static_clim(target, c)
    if not temp.same_grid(x, y, expected_x, expected_y):
        raise RuntimeError(f"{c.key}: Klimaraster {fn} passt nicht")
    return arr


def _temperature_current_period(
    *, c: temp.Config, start_s: str, end_s: str, work: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    start = datetime.strptime(start_s, "%Y-%m-%d").date()
    end = datetime.strptime(end_s, "%Y-%m-%d").date()
    files = temp.annual_files(c)
    total = None
    counts = None
    expected_x = expected_y = None
    for year in range(start.year, end.year + 1):
        fn = files.get(year)
        if not fn:
            raise RuntimeError(f"{c.key}: Jahresdatei {year} fehlt")
        target = work / "current_years" / fn
        if not target.exists():
            temp.download(f"{c.daily_base}/{fn}", target)
        with xr.open_dataset(target, decode_times=True) as ds:
            da, tdim, x, y = temp.prep(ds, c)
            sel = da.where(
                (da[tdim] >= np.datetime64(start_s)) & (da[tdim] <= np.datetime64(end_s)),
                drop=True,
            )
            if sel.sizes.get(tdim, 0) == 0:
                continue
            raw_sum = np.asarray(sel.sum(tdim, skipna=True).values, dtype=np.float32)
            raw_count = np.asarray(sel.notnull().sum(tdim).values, dtype=np.float32)
            arr_sum, nx, ny = temp.norm(raw_sum, x, y)
            arr_count, cx, cy = temp.norm(raw_count, x, y)
        if expected_x is None:
            expected_x, expected_y = nx, ny
            total = np.zeros(arr_sum.shape, dtype=np.float64)
            counts = np.zeros(arr_sum.shape, dtype=np.float64)
        if not temp.same_grid(nx, ny, expected_x, expected_y) or not temp.same_grid(cx, cy, expected_x, expected_y):
            raise RuntimeError(f"{c.key}: Rasterwechsel im aktuellen Zeitraum")
        valid = np.isfinite(arr_sum) & np.isfinite(arr_count) & (arr_count > 0)
        total[valid] += arr_sum[valid]
        counts[valid] += arr_count[valid]
    if total is None or counts is None or expected_x is None or expected_y is None:
        raise RuntimeError(f"{c.key}: keine aktuellen Daten {start_s}–{end_s}")
    current = np.full(total.shape, np.nan, dtype=np.float32)
    valid = counts > 0
    current[valid] = (total[valid] / counts[valid]).astype(np.float32)
    return current, expected_x, expected_y


def _temperature_reference_period(
    *, c: temp.Config, start_s: str, end_s: str, cache_root: Path, work: Path,
    expected_x: np.ndarray, expected_y: np.ndarray, reference: tuple[int, int],
) -> np.ndarray:
    weighted = None
    weight = 0
    daily_cache: dict[int, np.ndarray] = {}
    for year, month, a, b in _month_segments(start_s, end_s):
        nd = calendar.monthrange(year, month)[1]
        days = b - a + 1
        if a == 1 and b == nd:
            part = _temperature_static_month(
                c=c, month=month, reference=reference, work=work,
                expected_x=expected_x, expected_y=expected_y,
            )
        else:
            if month not in daily_cache:
                daily_cache[month] = _build_temperature_month_cache(
                    c=c, month=month, cache_root=cache_root, work=work,
                    expected_x=expected_x, expected_y=expected_y, reference=reference,
                )
            part = np.nanmean(daily_cache[month][a - 1:b], axis=0).astype(np.float32)
        weighted = part * days if weighted is None else weighted + part * days
        weight += days
    if weighted is None or weight == 0:
        raise RuntimeError(f"{c.key}: leere Referenzperiode")
    return (weighted / float(weight)).astype(np.float32)


def _render_temperature_anomaly(
    *, anomaly: np.ndarray, output: Path, c: temp.Config, label: str,
    start_s: str, end_s: str, overlay: Path | None, reference: tuple[int, int],
) -> None:
    cmap, norm = temp.anomaly_style()
    fig = plt.figure(figsize=(7.4, 9.4), dpi=150)
    ax = fig.add_axes([.055, .125, .89, .78])
    ax.imshow(anomaly, cmap=cmap, norm=norm, interpolation="nearest")
    ax.set_axis_off()
    if overlay and overlay.exists():
        ov = np.asarray(Image.open(overlay).convert("RGBA"))
        if ov.shape[:2] == anomaly.shape:
            ax.imshow(ov, interpolation="nearest")
    ref_label = reference_label(reference).replace("-", "–")
    fig.suptitle(f"HYRAS {c.label} · {label}", fontsize=15, fontweight="bold", y=.965)
    fig.text(.5, .925, f"Abweichung zum Mittel {ref_label} · {start_s} bis {end_s}", ha="center", fontsize=9)
    temp.draw_legend(fig)
    fig.text(.055, .012, f"Quelle: Deutscher Wetterdienst · {c.source_label} · Referenz {ref_label}", fontsize=7, color="#555555")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor="white", bbox_inches="tight", pad_inches=.12)
    plt.close(fig)


def _temperature_paths(data_root: Path, c: temp.Config):
    if c.key == "tmean":
        index_path = data_root / "tmean" / "index.json"
        maps_path = data_root / "tmean" / "regions" / "map_downloads.json"
    else:
        index_path = data_root / c.key / "regions" / "index.json"
        maps_path = data_root / c.key / "regions" / "map_downloads.json"
    return index_path, maps_path


def build_temperature_reference(
    *, data_root: Path, cache_root: Path, work: Path, parameter: str,
    reference: tuple[int, int] = TARGET_REFERENCE, build_reference_only: bool = False,
    month: int | None = None,
) -> None:
    c = temp.CFG[parameter]
    index_path, maps_path = _temperature_paths(data_root, c)
    idx = json.loads(index_path.read_text(encoding="utf-8"))
    through = str(idx["data_through"])
    current_month = month or int(through[5:7])
    probe = f"{int(idx['year'])}-{current_month:02d}-01"
    _probe, ex, ey = _temperature_current_period(c=c, start_s=probe, end_s=probe, work=work)
    _build_temperature_month_cache(
        c=c, month=current_month, cache_root=cache_root, work=work,
        expected_x=ex, expected_y=ey, reference=reference,
    )
    if build_reference_only:
        return

    maps = json.loads(maps_path.read_text(encoding="utf-8"))
    overlay = temp.overlay_path(data_root)
    label = reference_label(reference)
    for period in idx.get("periods", []):
        start_s = str(period.get("start_date") or "")
        end_s = str(period.get("end_date") or "")
        if not start_s or not end_s:
            continue
        try:
            current, x, y = _temperature_current_period(c=c, start_s=start_s, end_s=end_s, work=work)
            reference_arr = _temperature_reference_period(
                c=c, start_s=start_s, end_s=end_s, cache_root=cache_root, work=work,
                expected_x=x, expected_y=y, reference=reference,
            )
        except Exception as exc:
            print(f"{c.label}: {period.get('key')} für {label} übersprungen: {exc}", flush=True)
            continue
        anomaly = current - reference_arr
        key = str(period["key"])
        rel = f"download_maps/{key}_anomaly_{reference_slug(reference)}.png"
        _render_temperature_anomaly(
            anomaly=anomaly,
            output=data_root / c.key / rel,
            c=c,
            label=str(period.get("label", key)),
            start_s=start_s,
            end_s=end_s,
            overlay=overlay,
            reference=reference,
        )
        map_info = maps.setdefault("periods", {}).setdefault(key, {"label": period.get("label", key)})
        by_ref = dict(map_info.get("anomaly_by_reference") or {})
        if map_info.get("anomaly"):
            by_ref[reference_label(DEFAULT_REFERENCE)] = map_info["anomaly"]
        by_ref[label] = rel
        map_info["anomaly_by_reference"] = by_ref
        map_info["references"] = [reference_label(x) for x in REFERENCE_PERIODS]

        if c.key == "tmean":
            raster_rel = f"current/{key}_anomaly_{reference_slug(reference)}.i16.gz"
            temp.qwrite(data_root / "tmean" / raster_rel, anomaly)
            p_by_ref = dict(period.get("anomaly_by_reference") or {})
            if period.get("anomaly"):
                p_by_ref[reference_label(DEFAULT_REFERENCE)] = period["anomaly"]
            p_by_ref[label] = raster_rel
            period["anomaly_by_reference"] = p_by_ref
            stats_by_ref = dict(period.get("stats_by_reference") or {})
            stats_by_ref[reference_label(DEFAULT_REFERENCE)] = {
                "reference_mean_c": (period.get("stats") or {}).get("reference_mean_c"),
                "anomaly_mean_k": (period.get("stats") or {}).get("anomaly_mean_k"),
            }
            stats_by_ref[label] = {
                "reference_mean_c": round(float(np.nanmean(reference_arr)), 2),
                "anomaly_mean_k": round(float(np.nanmean(anomaly)), 2),
            }
            period["stats_by_reference"] = stats_by_ref
            period["references"] = [reference_label(x) for x in REFERENCE_PERIODS]
        print(f"{c.label}: {key} gegen {label} erzeugt", flush=True)

    idx["references"] = [reference_label(x) for x in REFERENCE_PERIODS]
    idx["default_reference"] = reference_label(DEFAULT_REFERENCE)
    maps["references"] = [reference_label(x) for x in REFERENCE_PERIODS]
    maps["default_reference"] = reference_label(DEFAULT_REFERENCE)
    index_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    maps_path.write_text(json.dumps(maps, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="/tmp/hyras-data")
    parser.add_argument("--cache-root", default="/tmp/hyras-reference-1961-1990-cache")
    parser.add_argument("--work", default="/tmp/hyras-reference-1961-1990-work")
    parser.add_argument("--parameter", choices=("all", "precipitation", "tmean", "tmax", "tmin"), default="all")
    parser.add_argument("--build-reference-only", action="store_true")
    parser.add_argument("--month", type=int)
    args = parser.parse_args()

    root = Path(args.data_root)
    cache = Path(args.cache_root)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    if args.parameter in ("all", "precipitation"):
        build_precipitation_reference(
            data_root=root,
            cache_root=cache / "precipitation",
            work=work / "precipitation",
            build_reference_only=args.build_reference_only,
        )
    if args.parameter == "all":
        params = ("tmean", "tmax", "tmin")
    elif args.parameter in temp.CFG:
        params = (args.parameter,)
    else:
        params = ()
    for key in params:
        build_temperature_reference(
            data_root=root,
            cache_root=cache / key,
            work=work / key,
            parameter=key,
            build_reference_only=args.build_reference_only,
            month=args.month,
        )

    if not args.build_reference_only:
        meta = {
            "schema_version": 1,
            "references": [reference_label(x) for x in REFERENCE_PERIODS],
            "default_reference": reference_label(DEFAULT_REFERENCE),
            "added_reference": reference_label(TARGET_REFERENCE),
        }
        (root / "_reference_periods.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
