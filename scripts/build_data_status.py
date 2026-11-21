#!/usr/bin/env python3
"""Build an evidence-based, public data freshness manifest for GitHub Pages.

Do not infer successful observations from GitHub Actions conclusions.
All dataset dates and coverage counts come from the committed archive metadata.
"""
from __future__ import annotations
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import argparse
import base64
import math
import re
import time
from http.client import HTTPException
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parent.parent


def read_json(rel):
    path = ROOT / rel
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def valid_date(value):
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 7:
            return date.fromisoformat(value + "-01")
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def result(id, label, group, date_value, updated, coverage, note="", cadence="daily",
           allowed_delay=5, incomplete=False, expires_utc=None):
    today = datetime.now(timezone.utc).date()
    latest = valid_date(date_value)
    if not latest:
        status, lag = "unknown", None
    elif latest > today:
        status, lag = "unknown", None
        note = (note + " · Zukunftsdatum im Archiv").strip(" ·")
    elif cadence == "hourly":
        try:
            timestamp = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            delta = (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600
            lag = round(max(0, delta), 1)
            status = "unknown" if delta < -1 else ("delayed" if delta > allowed_delay else "current")
        except ValueError:
            lag, status = None, "unknown"
    elif cadence == "monthly":
        lag = (today.year - latest.year)*12 + today.month - latest.month
        status = "delayed" if lag > allowed_delay else "current"
    else:
        lag = (today - latest).days
        status = "delayed" if lag > allowed_delay else "current"
    if expires_utc and status != "unknown" and datetime.now(timezone.utc) >= datetime.fromisoformat(expires_utc):
        status = "delayed"
    if incomplete and status == "current":
        status = "incomplete"
    return {
        "id": id, "label": label, "group": group,
        "latest": date_value if latest else None,
        "updated": updated if isinstance(updated, str) else None,
        "coverage": str(coverage), "note": note,
        "cadence": cadence, "lag": lag, "status": status,
        "allowed_delay": allowed_delay, "incomplete": bool(incomplete), "expires_utc": expires_utc,
    }


def fetch_archive_json(url):
    """Retry transient source/network failures, but not missing or private archives."""
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "ClimateDashboard-Status/1"})
            with urlopen(req, timeout=12) as response:
                data = response.read(24 * 1024 * 1024 + 1)
            if not data or len(data) > 24 * 1024 * 1024:
                raise ValueError("Archive size not supported")
            obj = json.loads(data)
            if not isinstance(obj, dict):
                raise ValueError("Archive metadata is not an object")
            return obj
        except HTTPError as exc:
            if exc.code != 429 and not 500 <= exc.code < 600:
                raise
            if attempt == 2:
                raise
        except (OSError, URLError, TimeoutError, HTTPException):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def external_archives():
    """Best-effort snapshot of separately published public data branches.

    Pages stays deployable even if an external branch is absent or unavailable.
    No API token and no GitHub access from the public browser are required.
    """
    base = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/"
    sources = {
        "mosmix": "mosmix-data/data/mosmix/manifest.json",
        "mosmix_quality": "mosmix-data/data/mosmix/quality_status.json",
        "sun_monthly": "state-monthly-sun/state_monthly_sun.json",
        "state_monthly": "state-monthly-ensemble/state_monthly_ensemble.json",
        "fast_live": "fast-live/fast_state.json",
        "europe_tmax": "europe-tmax-lab-data/data/europe-tmax-lab/current.json",
        "europe_tmin": "europe-tmin-lab-data/data/europe-tmin-lab/current.json",
        "icon": "icon-hazards-data/data/icon-hazards/current.json",
        "sst": "sst-archive/manifest.json",
        "opera": "opera-radar-data/data/opera/current.json",
        "ssw": "stratosphere-data/data/stratosphere/ssw_catalog.json",
        "hyras_precip": "hyras-data/hyras_index.json",
        **{f"hyras_{p}": f"hyras-data/{p}/regions/index.json" for p in ("tmean", "tmax", "tmin")},
        "strato_ifs": "stratosphere-ecmwf-data/data/stratosphere/ecmwf/ifs_runs.json",
        "strato_eps": "stratosphere-ecmwf-ens-data/data/stratosphere/ecmwf/ens_current.json",
        "strato_gefs": "stratosphere-ensemble-data/data/stratosphere/ensemble/gefs_current.json",
        "saharastaub": "saharastaub-data/data/saharastaub/current.json",
    }
    def fetch(item):
        name, suffix = item
        try:
            obj = fetch_archive_json(base + suffix)
            print(f"Externer Datenbestand {name}: geladen")
            return name, obj
        except (OSError, ValueError, HTTPError, URLError, TimeoutError, HTTPException) as exc:
            print(f"Externer Datenbestand {name}: nicht prüfbar ({type(exc).__name__})")
            return name, None
    with ThreadPoolExecutor(max_workers=4) as pool:
        return {name: obj for name, obj in pool.map(fetch, sources.items()) if obj is not None}


def common_latest(*values):
    valid = [v for v in values if isinstance(v, str) and valid_date(v)]
    return min(valid) if len(valid) == len(values) else None


def sst_region_status(manifest, regions):
    dates = manifest.get("dates") or {}
    if not isinstance(dates, dict):
        return None, 0, 0
    complete = []
    for iso, day in dates.items():
        if not valid_date(iso) or not isinstance(day, dict):
            continue
        region_data = day.get("regions") or {}
        if not isinstance(region_data, dict):
            continue
        if all(isinstance(region_data.get(k), dict)
               and all(isinstance(region_data[k].get(view), str)
                       and region_data[k][view] for view in ("absolute", "anomaly"))
               for k in regions):
            complete.append(iso)
    if not complete:
        return None, 0, 0
    latest = max(complete)
    last = date.fromisoformat(latest)
    complete_dates = set(complete)
    recent = sum((last - timedelta(days=i)).isoformat() in complete_dates
                 for i in range(21))
    return latest, len(complete), recent


def add_state_monthly_model_status(items, document):
    doc = document if isinstance(document, dict) else {}
    models = (doc.get("regions") or {}).get("Deutschland", {}).get("models") or {}
    for key, label in (("gefs", "GFS / GEFS"), ("ifs", "ECMWF IFS ENS"),
                       ("aifs", "ECMWF AIFS ENS"), ("icon_eu", "DWD ICON-EU EPS")):
        model = models.get(key) or {}
        run = model.get("run")
        coverage = f"{model.get('member_count', '–')} Member" if model else "Modell fehlt"
        items.append(result(f"state_monthly_{key}", f"Monatsausblick · {label}", "Vorhersagen",
            run, doc.get("generated_at"), coverage,
            "Modellinitialisierung · Warnschwelle 24 h (nicht das Erstellungsdatum der JSON-Datei)",
            cadence="hourly", allowed_delay=24))


def add_external(items, remote):
    add_state_monthly_model_status(items, remote.get("state_monthly"))
    mos = remote.get("mosmix")
    if mos:
        steps = mos.get("timesteps") or []
        count = mos.get("station_count", 0)
        count = count if isinstance(count, int) else 0
        good = mos.get("product") == "DWD MOSMIX-L" and count >= 100 and len(steps) >= 24
        quality = remote.get("mosmix_quality") or {}
        quality_ok = (quality.get("quality") == "passed"
                      and quality.get("issue_time") == mos.get("issue_time"))
        note = ("Letzter Modelllauf · DWD MOSMIX-L · "
                + ("Qualitätsprüfung bestätigt" if quality_ok else
                   "Qualitätsnachweis nicht aktuell oder nicht erreichbar"))
        items.append(result("mosmix", "MOSMIX-L", "Vorhersagen",
            mos.get("issue_time"), mos.get("generated_at"),
            f"{count} Prognosepunkte · {len(steps)} Zeitschritte",
            note, cadence="hourly", allowed_delay=12,
            incomplete=not (good and quality_ok)))
    else:
        items.append(result("mosmix", "MOSMIX-L", "Vorhersagen", None, None,
            "Laufmetadaten fehlen", "Datenzweig vorübergehend nicht prüfbar"))

    # Sunshine observation cutoff is NOT the date of the forecast horizon.
    # Count only available real ensemble products and the 17 DUETT regions.
    sunshine = remote.get("sun_monthly")
    if isinstance(sunshine, dict):
        keys = sunshine.get("models_order") or []
        regions = sunshine.get("regions") or {}
        order = sunshine.get("regions_order") or []
        required = {"gefs", "ifs", "aifs", "icon_eu"}
        valid_models = (isinstance(keys, list) and set(keys) == required
                        and len(keys) == len(required))
        valid_regions = (isinstance(regions, dict) and isinstance(order, list)
                         and len(order) == 17 and len(set(order)) == 17
                         and set(regions) == set(order)
                         and all(isinstance(regions.get(k), dict)
                                 and set(regions[k].get("models") or {}) == set(keys)
                                 for k in order))
        errors = sunshine.get("model_errors") or {}
        healthy = (sunshine.get("schema_version") == 1
                   and sunshine.get("parameter") == "sunshine"
                   and sunshine.get("unit") == "h"
                   and valid_models and valid_regions and not errors)
        items.append(result(
            "sun_monthly", "Monatsausblick · DUETT Sonnenschein", "Vorhersagen",
            sunshine.get("observation_data_through"), sunshine.get("generated_at"),
            f"{len(regions)}/17 Regionen · {len(keys)}/4 Ensemblemodelle",
            "Beobachtung: DWD DUETT, Prognose: GEFS, ECMWF IFS/AIFS und ICON-EU"
            + (" · Ensemblefehler gemeldet" if errors else ""),
            allowed_delay=4, incomplete=not healthy,
        ))
    else:
        items.append(result(
            "sun_monthly", "Monatsausblick · DUETT Sonnenschein", "Vorhersagen",
            None, None, "Sonnenschein-Datenbranch nicht prüfbar",
            "Kein veröffentlichter DUETT-Beobachtungs- und Ensemble-Nachweis",
        ))

    # Separate real (not simulated) station and raster checks for the private
    # five-day experiment. A valid ICON field does not imply every city has TN/TX.
    for mode, title, value_key in (
        ("tmax", "Europa Tmax · MOSMIX/ICON-EU", "tmax_c"),
        ("tmin", "Europa Tmin · MOSMIX/ICON-EU", "tmin_c"),
    ):
        archive = remote.get("europe_" + mode)
        if not isinstance(archive, dict):
            items.append(result("europe_" + mode, title, "Vorhersagen", None, None,
                "Labor-Prognosemanifest nicht erreichbar",
                "Die gesonderte fünftägige Modell- und Stationsprüfung ist nicht möglich"))
            continue
        days = archive.get("days") or []
        valid_counts = [
            sum(s.get(value_key) is not None for s in day.get("stations", [])
                if isinstance(s, dict))
            for day in days if isinstance(day, dict)
        ]
        raster_ok = all(isinstance(day, dict) and
                        isinstance(day.get("coverage"), (float, int)) and
                        day["coverage"] >= .80 and
                        day.get("icon_png") and day.get("icon_raw_png")
                        for day in days)
        good = (archive.get("schema") == 2 and len(days) == 5
                and len(valid_counts) == 5 and min(valid_counts, default=0) >= 25
                and raster_ok and archive.get("stations_catalog_count", 0) >= 1000)
        cycle = archive.get("icon_cycle")
        try:
            cycle_date = datetime.strptime(cycle, "%Y%m%d%H").replace(
                tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError):
            cycle_date = None
        missing = sorted({
            s.get("city") for day in days if isinstance(day, dict)
            for s in day.get("stations", [])
            if isinstance(s, dict) and s.get(value_key) is None and s.get("city")
        })
        first = days[0].get("date") if days and isinstance(days[0], dict) else "–"
        last = days[-1].get("date") if days and isinstance(days[-1], dict) else "–"
        missing_note = (f" · Fehlende Stadtwerte: {', '.join(missing[:5])}" +
                        (" …" if len(missing) > 5 else "")) if missing else ""
        expires_utc = (datetime.fromisoformat(cycle_date.replace("Z", "+00:00")) + timedelta(hours=18)).isoformat() if mode == "tmin" and cycle_date else None
        items.append(result("europe_" + mode, title, "Vorhersagen",
            cycle_date, archive.get("built_utc"),
            f"{len(days)}/5 Tage · {min(valid_counts, default=0)}–{max(valid_counts, default=0)}/31 Städte · "
            f"Raster mindestens {min((round(day.get('coverage', 0)*100) for day in days if isinstance(day, dict)), default=0)} %",
            f"ICON-Modelllauf {cycle or '–'} · Prognosen {first} bis {last}{missing_note} · "
            "Datenbranch-Manifest, kein Browser-Bildtest",
            cadence="hourly", allowed_delay=24, incomplete=not good, expires_utc=expires_utc))

    fast = remote.get("fast_live")
    if isinstance(fast, dict) and fast.get("station_count", 0) > 0:
        items.append(result("fast_live", "DWD SYNOP Fast Live", "Stationen",
            fast.get("latest_measurement_utc"), fast.get("generated_at_utc"),
            f"{fast.get('station_count')} SYNOP/CDC-zugeordnete Stationen · "
            f"{fast.get('source_file_count', 0)} DWD-Dateien",
            "Ergänzung zu den DWD-10-Minuten-Messungen · aktuelle SYNOP-Veröffentlichung",
            cadence="hourly", allowed_delay=.75))
    else:
        items.append(result("fast_live", "DWD SYNOP Fast Live", "Stationen",
            None, None, "Fast-Live-Datenbranch ohne prüfbaren Stationsbestand",
            "SYNOP-Import nicht verfügbar; DWD-CDC-10-Minuten-Daten getrennt betrachten"))

    icon = remote.get("icon")
    if icon:
        periods = icon.get("periods") or []
        if not isinstance(periods, list):
            periods = []
        ranges = [(p.get("start_h"), p.get("end_h")) for p in periods if isinstance(p, dict)]
        duration = int(icon.get("duration_h", 24))
        expected = [(h, h + 24) for h in range(0, 120, 24)]
        good = (icon.get("schema") in (1, 2) and duration == 24
                and ranges == expected and bool(icon.get("grid")))
        items.append(result("icon_hazards", "ICON-EU Wettergefahren", "Vorhersagen",
            icon.get("run_utc"), icon.get("generated_utc"),
            f"{len(periods)}/5 Vorhersagefenster · 0 bis 120 Stunden",
            "Modellbasierter Gefahrenmonitor, keine amtliche Warnung",
            cadence="hourly", allowed_delay=12, incomplete=not good))
    else:
        items.append(result("icon_hazards", "ICON-EU Wettergefahren", "Vorhersagen",
            None, None, "Laufmetadaten fehlen", "Datenzweig vorübergehend nicht prüfbar"))

    # An advertised MeteoGate timestamp is not evidence of a published COG.
    # Report only frames that the OPERA ingest actually downloaded and verified.
    opera = remote.get("opera")
    for kind, label, max_delay in (
        ("dbzh", "OPERA Europa · Radarreflektivität", .75),
        ("rate", "OPERA Europa · Niederschlagsrate", 1.0),
    ):
        product = ((opera.get("products") or {}).get(kind) or {}) if isinstance(opera, dict) else {}
        frames = product.get("frames") or []
        verified = sorted(
            f["utc"] for f in frames if isinstance(f, dict)
            and isinstance(f.get("utc"), str) and valid_date(f["utc"])
        ) if isinstance(frames, list) else []
        if verified:
            items.append(result("opera_" + kind, label, "Radar",
                verified[-1], opera.get("updated_utc"),
                f"{len(verified)} überprüfte Echtzeitbilder",
                "EUMETNET OPERA / MeteoGate · nur erfolgreich validierte COG-Dateien",
                cadence="hourly", allowed_delay=max_delay, incomplete=len(verified)<4))
        else:
            items.append(result("opera_" + kind, label, "Radar", None,
                opera.get("updated_utc") if isinstance(opera, dict) else None,
                "Keine verifizierten Radarframes im Datenarchiv",
                "OPERA-Datenbranch fehlt oder enthält keine gültigen Bilddaten"))

    ssw = remote.get("ssw")
    if ssw and ssw.get("schema_version") == 1:
        evaluated = ssw.get("evaluated_seasons", ssw.get("complete_seasons", 0))
        items.append(result("ssw_catalog", "Polarwirbel · historischer SSW-Katalog", "Atmosphäre",
            ssw.get("analysis_through"), ssw.get("generated_utc"),
            f"{evaluated} auswertbare Winter · {ssw.get('event_count', '–')} Major-SSW-Ereignisse",
            f"NASA-MERRA-2-Winddaten · {ssw.get('leap_gap_seasons', 0)} Winter mit fehlendem 29. Februar",
            allowed_delay=8, incomplete=bool(ssw.get("incomplete_seasons",0))))
    else:
        items.append(result("ssw_catalog", "Polarwirbel · historischer SSW-Katalog",
            "Atmosphäre", None, None, "Katalogmetadaten nicht erreichbar",
            "Das Windarchiv wird getrennt von GitHub Pages aktualisiert"))

    manifest = remote.get("sst")
    groups = [
        ("sst_europe", "Meeresoberflächentemperatur Europa",
         ("europe", "mediterranean", "north_atlantic", "nordic_seas")),
        ("sst_oceans", "Meeresoberflächentemperatur Ozeane",
         ("pacific", "nino34", "indian_ocean")),
    ]
    for key, label, regions in groups:
        if manifest:
            latest, count, recent = sst_region_status(manifest, regions)
            items.append(result(key, label, "Ozean", latest,
                manifest.get("generated_at"),
                f"{count} vollständige Kartentage · {len(regions)} Regionen · letzte 21 Tage: {recent}/21",
                "Beide Ansichten (absolut und Anomalie) je Region; historische Lücken separat",
                allowed_delay=5, incomplete=bool(latest) and recent < 21))
        else:
            items.append(result(key, label, "Ozean", None, None,
                "Manifest fehlt", "SST-Datenzweig vorübergehend nicht prüfbar"))


MTG_PRODUCTS = ("geocolour", "dust", "ir105", "firetemperature")


def obj(value):
    return value if isinstance(value, dict) else {}


def arr(value):
    return value if isinstance(value, list) else []


def genuine_timestamp(value):
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo and parsed <= datetime.now(timezone.utc) else None
    except ValueError:
        return None


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def grid_complete(data, *keys, count=1):
    w, h = data.get("width"), data.get("height")
    if not all(type(v) is int and v > 0 for v in (w, h, count)) or w*h*count > 50_000_000:
        return False
    try:
        return all(len(base64.b64decode(data.get(k, ""), validate=True)) == w*h*count*2 for k in keys)
    except (TypeError, ValueError):
        return False


def reference_complete(data):
    ref = obj(data.get("reference_metadata"))
    return (ref.get("years") == 30 and ref.get("source_months") == 360
            and ref.get("forecast_hour") == 3 and "1991–2020" in str(data.get("reference")))


def add_extended_products(items, remote):
    """Use actual archive coverage and observation/model cycle rather than generation time."""
    def emit(key, label, group, data, latest, coverage, note, good, *, cadence="daily", delay=4):
        if not data:
            latest, coverage, note = None, "Archivmetadaten fehlen", "Noch nicht prüfbar · " + note
        elif cadence == "hourly" and not genuine_timestamp(latest):
            latest = None
        items.append(result(key, label, group, latest,
            data.get("generated_utc") or data.get("generated_at"), coverage, note,
            cadence=cadence, allowed_delay=delay, incomplete=not good))

    for key, label in (("precip", "Niederschlag"), ("tmean", "Temperaturmittel"),
                       ("tmax", "Tagesmaximum"), ("tmin", "Tagesminimum")):
        data = obj(remote.get("hyras_" + key))
        regions = arr(data.get("regions"))
        periods = arr(data.get("periods"))
        if key == "precip":
            good = data.get("product") == "DWD HYRAS-DE-PR" and bool(periods) and data.get("resolution_km") == 1
            coverage = f"{len(periods)} Perioden · 1-km-Raster"
        else:
            good = data.get("parameter") == key and len(set(v for v in regions if isinstance(v, str))) == 17
            coverage = f"{len(regions)}/17 Regionen · Tagesgebietsmittel"
        emit("hyras_"+key, "HYRAS · "+label, "Deutschland", data, data.get("data_through"), coverage,
             "DWD · aktueller Beobachtungstag", good, delay=4)

    for key, path, label, cadence, delay in (
        ("era5_land_monthly", "era5_land_europe/index.json", "Monatsmittel", "monthly", 2),
        ("era5_land_running", "era5_land_europe/running/index.json", "laufende Zeiträume", "daily", 9),
    ):
        data = obj(read_json(path)); periods = obj(data.get("periods"))
        latest = data.get("latest_month_key") if cadence == "monthly" else data.get("data_through")
        expected = "latest_month" if cadence == "monthly" else "running_month"
        good = data.get("ready") is True and expected in periods and "1991" in str(data.get("reference_period"))
        emit(key, "ERA5-Land · "+label, "Europa", data, latest, f"{len(periods)} Perioden · 0,1°",
             "Copernicus · tatsächlicher gemeinsamer Datenstand", good, cadence=cadence, delay=delay)

    data = obj(read_json("gfs_analysis_europe/index_f003.json")); dates = arr(data.get("dates"))
    good = (data.get("reference_ready") is True and reference_complete(data) and bool(dates)
            and all(valid_date(d) for d in dates) and dates == sorted(set(dates))
            and data.get("data_through") == dates[-1]
            and grid_complete(data, "temperature_q10_b64", "anomaly_q10_b64", count=len(dates)))
    emit("gfs_f003", "GFS · f003-Temperaturanomalie", "Europa", data, data.get("data_through"),
         f"{len(dates)} Kartentage · CFSR/CFSv2 1991–2020", "Modellanalyse aus 4 echten +3-h-Prognosen pro Tag", good)
    data = obj(read_json("gfs_analysis_europe/weekly_f003_extended.json")) or obj(read_json("gfs_analysis_europe/weekly_f003.json"))
    sources = arr(data.get("sources")); cycle = genuine_timestamp(data.get("run_utc"))
    good = (cycle is not None and data.get("sample_count") == 28 and reference_complete(data)
            and [obj(s).get("forecast_hour") for s in sources] == list(range(3,166,6))
            and grid_complete(data, "forecast_mean_q10_b64", "anomaly_mean_q10_b64"))
    emit("gfs_weekly", "GFS · 7-Tage-Temperaturanomalie", "Vorhersagen", data, data.get("run_utc"),
         f"{len(sources)}/28 Originalfelder · CFSR/CFSv2 1991–2020", "Laufzeit statt prognostizierter Gültigkeit", good, cadence="hourly", delay=18)

    data = obj(read_json("data/satellite_wms_times.json")); products = obj(data.get("products"))
    verified = [obj(products.get(p)).get("latest_verified_time") for p in MTG_PRODUCTS
                if obj(products.get(p)).get("map_ok") is True and genuine_timestamp(obj(products.get(p)).get("latest_verified_time"))]
    emit("satellite_mtg", "EUMETSAT · MTG-Satellitenbilder", "Europa", data, min(verified, key=genuine_timestamp) if verified else None,
         f"{len(verified)}/4 Kernprodukte bestätigt", "Älteste bestätigte Bildzeit der vier Produkte, nicht Prüfzeit", len(verified)==4, cadence="hourly", delay=3)

    for key, path, title in (
        ("snow_eurasia", "eurasia_snow/index.json", "Schneebedeckung Eurasien"),
        ("snow_europe", "eurasia_snow/europe_index.json", "Schneebedeckung Europa"),
    ):
        data = obj(read_json(path))
        daily = {d: v for d, v in obj(data.get("daily")).items() if valid_date(d) and finite(v)}
        latest = max(daily, default=None)
        emit(key, title, "Schnee", data, latest, f"{len(daily)} Beobachtungstage",
             "NOAA/NSIDC IMS · beobachtete Schneefläche", data.get("schema")==1 and latest is not None and latest == data.get("observed_latest"), delay=3)
    data = obj(read_json("eurasia_snow/maps/index.json"))
    maps = [m for m in arr(data.get("maps")) if isinstance(m,dict) and valid_date(m.get("date"))
            and all(isinstance(m.get(k),str) and m[k] for k in ("cover","anomaly","europe_cover","europe_anomaly"))]
    latest = max((m["date"] for m in maps),default=None)
    emit("snow_maps", "Schneebedeckung · Karten und Abweichung", "Schnee", data, latest,
         f"{len(maps)} vollständige Kartentage · Europa und Eurasien", "IMS-Schneefläche und Abweichung · Datenstand der vollständigen vier Karten",
         data.get("schema")==1 and latest is not None and latest == data.get("latest"), delay=3)

    data = obj(read_json("data/dmi_greenland_stations.json"))
    active = {s.get("id") for s in arr(data.get("stations")) if isinstance(s,dict) and s.get("status")=="Active" and isinstance(s.get("id"),str) and s.get("id")}
    observed = {sid: max((v["date"] for v in obj(values).values() if isinstance(v,dict) and valid_date(v.get("date")) and finite(v.get("value"))),default=None)
                for sid,values in obj(data.get("latest")).items() if sid in active}
    latest = max((v for v in observed.values() if v), default=None)
    cutoff = (datetime.now(timezone.utc).date()-timedelta(days=3)).isoformat()
    fresh = sum(v is not None and v>=cutoff for v in observed.values())
    emit("dmi_greenland", "DMI · Grönland-Stationen", "Arktis", data, latest,
         f"{fresh}/{len(active)} aktive Stationen mit Werten der letzten drei Tage",
         "Tatsächliche Stationsbeobachtungen, nicht Ende des Abfragefensters", bool(active) and fresh/len(active)>=.8 and not data.get("fetch_errors"), delay=3)

    data = obj(remote.get("strato_ifs")); runs = [r for r in arr(data.get("runs")) if isinstance(r, dict)]
    run = max(runs, key=lambda r: str(r.get("cycle_utc", "")), default={})
    cycle = run.get("cycle_utc"); steps = arr(run.get("steps_hours")); values = arr(run.get("values"))
    good = (data.get("provider") == "ECMWF IFS" and cycle == data.get("latest_cycle_utc")
            and data.get("level_hpa") == 10 and data.get("latitude_deg") == 60
            and steps == list(range(0,361,12)) and len(values) == len(steps) and all(finite(v) for v in values))
    emit("strato_ifs", "Stratosphäre · ECMWF IFS", "Atmosphäre", data, cycle, f"{len(values)}/31 Zeitschritte",
         "60°N / 10 hPa · Original-Modelllauf", good, cadence="hourly", delay=24)
    for key, label, provider, count, min_days, max_days, delay in (
        ("strato_eps", "ECMWF ENS", "ECMWF IFS ENS", 51, 15, 15, 30),
        ("strato_gefs", "NOAA GEFS", "NOAA GEFS", 31, 16, 35, 24)):
        data = obj(remote.get(key)); members = obj(data.get("members")); dates = arr(data.get("valid_dates"))
        cycle = genuine_timestamp(data.get("cycle_utc")); horizon = data.get("forecast_horizon_days")
        ids = {"c00", *(f"p{i:02d}" for i in range(1,count))}
        good = (cycle is not None and data.get("provider")==provider and data.get("level_hpa")==10
                and data.get("latitude_deg")==60 and data.get("member_count")==count and set(members)==ids
                and type(horizon) is int and min_days <= horizon <= max_days and len(dates)==horizon+1
                and dates == [(cycle.date()+timedelta(days=i)).isoformat() for i in range(len(dates))]
                and all(isinstance(v,list) and len(v)==len(dates) and all(finite(x) and -160<x<170 for x in v) for v in members.values()))
        emit(key, "Stratosphäre · "+label, "Atmosphäre", data, data.get("cycle_utc"), f"{len(members)}/{count} Mitglieder · {len(dates)} Zeitpunkte",
             "60°N / 10 hPa · vollständige Originalmitglieder", good, cadence="hourly", delay=delay)

    data = obj(remote.get("saharastaub")); frames = arr(data.get("frames")); grid = obj(data.get("grid"))
    total = grid.get("rows", 0)*grid.get("cols", 0) if type(grid.get("rows")) is int and type(grid.get("cols")) is int else 0
    def rle_ok(encoded):
        try:
            b = base64.b64decode(encoded, validate=True)
            return len(b)%3==0 and 0<total<=500000 and sum(b[i+1]+256*b[i+2] for i in range(0,len(b),3))==total and all((b[i]<=9 or b[i]==255) and (b[i+1] or b[i+2]) for i in range(0,len(b),3))
        except (TypeError, ValueError):
            return False
    good_frames = sum(all(rle_ok(obj(f).get(k)) for k in ("taod","column","surface")) for f in frames)
    good = data.get("source") == "DWD ICON-ART-EU" and len(frames)>=21 and good_frames==len(frames)
    emit("saharastaub", "Saharastaub · ICON-ART-EU", "Vorhersagen", data, data.get("run_utc"),
         f"{good_frames}/{len(frames)} vollständige Rasterzeiten", "AOD, Luftsäule und bodennahe Konzentration", good, cadence="hourly", delay=18)


def add_gbi(items, legacy=None, stamp=None):
    data = obj(read_json("climate_indices/gbi_era5.json"))
    if data:
        rows = arr(data.get("monthly"))
        complete = False
        try:
            from update_era5_gbi import validate_archive
            validate_archive(data)
            complete = True
        except (ImportError, ValueError, TypeError, KeyError):
            pass
        items.append(result("gbi", "GBI · ERA5", "Indizes", data.get("latest_month"), data.get("generated_at"),
            f"{len(rows)} Monatswerte · Referenz 1991–2020", "Copernicus ERA5 · Z500 · flächengewichtet", cadence="monthly", allowed_delay=2, incomplete=not complete))
    else:
        items.append(result("gbi", "GBI · ERA5", "Indizes", None, None, "ERA5-Archiv noch nicht aufgebaut", "NOAA-Historie bleibt getrennt verfügbar", cadence="monthly"))
    if legacy:
        items.append(result("gbi_noaa", "GBI · NOAA (Historie)", "Indizes", legacy.get("latest_month"), stamp,
            f"{len(arr(legacy.get('monthly')))} historische Monatswerte", "NOAA/PSL · Referenz 1981–2010 · Quellverzug, nicht mit ERA5 kombiniert", cadence="monthly", allowed_delay=4))


def add_climate_indices(items):
    p = read_json("climate_indices/index.json")
    if not p or not p.get("ready"):
        items.append(result("noaa_indices", "Atmosphärische Indizes", "Indizes",
                            None, None, "Indexarchiv fehlt oder unvollständig",
                            "NAO, AO, ENSO, QBO und MJO noch nicht überprüfbar"))
        add_gbi(items)
        return
    stamp = p.get("generated_at")
    tele = p.get("teleconnections") or {}
    for key, label in (("nao", "NAO · Nordatlantische Oszillation"),
                       ("ao", "AO · Arktische Oszillation")):
        v = tele.get(key) or {}
        rows = v.get("daily") or []
        items.append(result(key, label, "Indizes",
            v.get("latest_date"), stamp, f"{len(rows)} Tageswerte",
            "NOAA/CPC Tagesindex", allowed_delay=7,
            incomplete=len(rows)<2000))
    enso = p.get("enso") or {}
    oni, roni = enso.get("oni") or {}, enso.get("roni") or {}
    latest = common_latest(oni.get("latest_season"), roni.get("latest_season"))
    items.append(result("enso", "ENSO · ONI / RONI", "Indizes", latest, stamp,
        f"ONI: {len(oni.get('seasons') or [])} · RONI: {len(roni.get('seasons') or [])} gleitende 3-Monatszeiten",
        "Monatsangabe ist das Zentrum der überlappenden 3-Monatsperiode",
        cadence="monthly", allowed_delay=3,
        incomplete=min(len(oni.get("seasons") or []),len(roni.get("seasons") or []))<300))
    extra = p.get("enso_extra") or {}
    soi, mei = extra.get("soi") or {}, extra.get("mei") or {}
    items.append(result("soi_mei", "ENSO · SOI / MEI.v2", "Indizes",
        common_latest(soi.get("latest_month"), mei.get("latest_month")), stamp,
        f"SOI: {len(soi.get('monthly') or [])} · MEI.v2: {len(mei.get('monthly') or [])} Monatswerte",
        "Monatliche ENSO-Indizes; Datenstand des älteren Produkts",
        cadence="monthly", allowed_delay=4,
        incomplete=min(len(soi.get("monthly") or []),len(mei.get("monthly") or []))<300))
    qbo = p.get("qbo") or {}
    q30,q50=qbo.get("u30") or {},qbo.get("u50") or {}
    items.append(result("qbo", "QBO · 30 / 50 hPa", "Indizes",
        common_latest(q30.get("latest_month"),q50.get("latest_month")), stamp,
        f"30 hPa: {len(q30.get('monthly') or [])} · 50 hPa: {len(q50.get('monthly') or [])} Monate",
        "NOAA/CPC monatlicher Zonalwind", cadence="monthly",allowed_delay=3,
        incomplete=min(len(q30.get("monthly") or []),len(q50.get("monthly") or []))<300))
    europe = p.get("europe") or {}
    # Each index has its own publisher cadence. NOAA/PSL's NCEP/NCAR GBI
    # source can be months behind CPC teleconnections; never make all four
    # indices look delayed because only the independently sourced GBI lags.
    for key,label in (
        ("scand", "SCAND · Skandinavisches Muster"),
        ("ea", "EA · Ostatlantisches Muster"),
        ("eawr", "EA/WR · Ostatlantik/Westrussland"),
    ):
        dataset = europe.get(key) or {}
        rows = dataset.get("monthly") or []
        note = "NOAA/CPC monatlicher Zirkulationsindex"
        items.append(result(key, label, "Indizes",
            dataset.get("latest_month"), stamp, f"{len(rows)} Monatswerte",
            note, cadence="monthly", allowed_delay=4, incomplete=len(rows)<300))
    add_gbi(items, europe.get("gbi"), stamp)
    mjo=p.get("mjo") or {}
    items.append(result("mjo","MJO · Wheeler–Hendon RMM","Indizes",
        mjo.get("latest_date"),stamp,
        f"{len(mjo.get('daily') or [])} Tageswerte",
        "BOM Beobachtungsindex; Veröffentlichungslatenz möglich",allowed_delay=14,
        incomplete=len(mjo.get("daily") or [])<1000))


def build(remote=None):
    items = []
    dwd = read_json("update_status.json")
    if dwd:
        stamp = dwd.get("updated_at")
        monthly = dwd.get("monthly") or {}
        items.append(result("dwd_monthly", "DWD Gebietsmittel", "Deutschland",
            monthly.get("latest_complete_month"), stamp,
            f'{monthly.get("area_count", "–")} Regionen · {monthly.get("records", "–")} Monatswerte',
            "Temperatur, Niederschlag und Sonnenschein; Angaben zu vollständigen Monaten",
            cadence="monthly", allowed_delay=2))
        daily = dwd.get("daily") or {}
        items.append(result("dwd_daily", "DWD Tageshöchstwerte", "Deutschland",
            daily.get("latest_date"), stamp,
            f'{daily.get("records", "–")} Tageswerte · {daily.get("latest_station_count", "–")} meldende Stationen am letzten Tag',
            "Stationsmaximum, kein flächiges Deutschlandmittel", allowed_delay=4))
        for key, label, coverage in [
            ("station_records", "Stationsrekorde", "KL- und RR-Stationsnetz"),
            ("station_precip", "Stationsniederschlag", "RR-Stationsnetz"),
            ("station_climate_days", "Stations-Kenntage", "KL-Stationsnetz"),
            ("station_heatwaves", "Stations-Hitzewellen", "KL-Stationsnetz"),
        ]:
            x = dwd.get(key) or {}
            items.append(result(key, label, "Stationen", x.get("data_through"), stamp,
                f'{x.get("station_count", "–")} Stationen' if x.get("station_count") else coverage,
                "Aktuelles Datenende; historische Bestände separat", allowed_delay=4))
    else:
        items.append(result("dwd_monthly", "DWD Gebietsmittel", "Deutschland", None, None,
            "Archivmetadaten fehlen", "update_status.json nicht verfügbar"))

    snow = read_json("station_snow_height_current_index.json")
    if snow:
        observed = snow.get("stations_with_current_season_values")
        possible = snow.get("profile_station_count")
        # An active station can be missing measurements in the young snow
        # season without invalidating verified data from the other stations.
        # Keep partial coverage visible and reserve "incomplete" for systemic gaps.
        coverage_ratio = (observed / possible if isinstance(observed, int)
                          and isinstance(possible, int) and possible > 0 else 0)
        missing_stations = max(0, possible - observed) if (
            isinstance(observed, int) and isinstance(possible, int)) else None
        items.append(result("snow", "Stationsschneehöhe", "Stationen",
            snow.get("data_through"), snow.get("generated_at"),
            f'{observed}/{possible} Stationen mit Saisonwerten'
            + (f' · {missing_stations} ohne Saisonmessung' if missing_stations is not None else ''),
            "Fehlende Stationsmeldungen werden nicht als 0 cm gewertet",
            allowed_delay=5,
            incomplete=not (snow.get("ready") is True and coverage_ratio >= .8)))

    era = read_json("era5_europe/index.json")
    if era:
        periods = era.get("available_periods", [])
        items.append(result("era5_monthly", "ERA5 Atmosphäre Europa", "Europa",
            era.get("data_through") or era.get("latest_month_key"), era.get("generated_at"),
            f'{len(periods)} Monatsperioden im aktuellen Index; historische Jahre separat ausgewiesen',
            "Verfügbare Perioden im Index bedeuten nicht automatisch vollständige historische Karten",
            cadence="monthly", allowed_delay=2,
            incomplete=not bool(era.get("ready"))))

    estrat = read_json("era5_stratosphere/index.json")
    if estrat:
        complete = estrat.get("reference_years_completed", 0)
        reference = estrat.get("reference") or {}
        # A climate-calendar day qualifies only with ALL 30 actual yearly
        # samples (8 on 29 February); partial values never become a normal.
        temp_fields = tuple(f"tcap_{level}" for level in (10,30,50,100))
        wind_fields = tuple(f"u60_{level}" for level in (10,30,50,100))
        def complete_days(fields):
            return len(set.intersection(*(
                set(reference.get(field) or {}) for field in fields)))
        tdays = complete_days(temp_fields)
        udays = complete_days(wind_fields)
        wind_years = estrat.get("reference_wind_years_completed")
        wind_years_label = f"{wind_years}/30" if isinstance(wind_years,int) else "noch nicht ermittelt"
        # Show incremental real-day progress instead of 0/366 until all
        # historical years are finally complete. Full-sample climate normals
        # remain strict and independent of this progress indicator.
        from calendar import isleap
        total_wind_reference_days = sum(366 if isleap(y) else 365 for y in range(1991, 2021))
        verified_wind_reference_days = sum(
            all(isinstance(row.get(field), (int, float))
                and not isinstance(row[field], bool)
                and abs(row[field]) < float("inf") for field in wind_fields)
            for row in (estrat.get("series") or [])
            if isinstance(row, dict) and isinstance(row.get("date"), str)
            and "1991-01-01" <= row["date"] <= "2020-12-31"
        )
        latest_day = estrat.get("data_through")
        latest_row = next((r for r in reversed(estrat.get("series") or [])
                           if isinstance(r, dict) and r.get("date") == latest_day), None)
        current_fields = (*temp_fields, *wind_fields)
        daily_complete = bool(latest_row) and all(
            isinstance(latest_row.get(k), (float, int))
            and not isinstance(latest_row[k], bool)
            and abs(latest_row[k]) < float("inf") for k in current_fields)
        items.append(result("era5_strat", "ERA5 Stratosphäre · Tageswerte", "Atmosphäre",
            latest_day, estrat.get("generated_at"),
            f"{len(estrat.get('series') or [])} echte Tage · "
            f"letzter Tag: {sum(isinstance((latest_row or {}).get(k), (int,float)) for k in wind_fields)}/4 Windhöhen · "
            f"{sum(isinstance((latest_row or {}).get(k), (int,float)) for k in temp_fields)}/4 Temperaturhöhen",
            "ERA5-Tagesdaten · unabhängig von der historischen Klimareferenz",
            allowed_delay=9, incomplete=not daily_complete))
        items.append(result("era5_strat_reference", "ERA5 Stratosphäre · Klimareferenz", "Atmosphäre",
            latest_day, estrat.get("generated_at"),
            f"1991–2020 · Temperatur: {tdays}/366 Klimatologietage · "
            f"Zonalwind: {udays}/366 vollständige Klimatologietage · "
            f"Windtageswerte: {verified_wind_reference_days}/{total_wind_reference_days} · "
            f"vollständige Temperaturjahre: {complete}/30",
            f"Windjahre: {wind_years_label} · "
            + ("Historische Referenz unvollständig" if complete < 30 or wind_years != 30 or tdays < 366 or udays < 366
               else "Temperatur- und Zonalwindreferenz vollständig"),
            allowed_delay=9, incomplete=complete < 30 or wind_years != 30 or tdays < 366 or udays < 366))

    # DMI index and ERA5 Arctic map archive are independent products.
    # Count only validated observations and complete three-region map days.
    dmi = read_json("data/arctic80_temperature.json")
    if isinstance(dmi, dict) and dmi.get("schema") == 1:
        day_keys = dmi.get("days") or []
        years = dmi.get("years") or {}
        valid_years = {year: values for year, values in years.items()
                       if str(year).isdigit() and isinstance(values, list)
                       and len(values) == len(day_keys) == 366}
        dates = [f"{year}-{day_keys[i]}" for year, values in valid_years.items()
                 for i, value in enumerate(values)
                 if isinstance(value, (int, float)) and not isinstance(value, bool)
                 and value == value and abs(value) < 200
                 and valid_date(f"{year}-{day_keys[i]}")]
        latest = max(dates, default=None)
        claimed = dmi.get("last_date")
        verified = bool(latest and claimed == latest and len(valid_years) >= 60)
        items.append(result("dmi_arctic", "DMI Temperaturindex nördlich 80°N", "Arktis",
            latest, dmi.get("updated_utc"),
            f"{len(valid_years)} validierte Jahrgänge · {len(dates)} Tageswerte",
            "ERA-40/ECMWF-Analysearchiv · kein flächengewichtetes Temperaturmittel"
            + ("" if verified else " · Letzter Datentag/Archivstruktur bitte prüfen"),
            allowed_delay=5, incomplete=not verified))
    else:
        items.append(result("dmi_arctic", "DMI Temperaturindex nördlich 80°N", "Arktis",
            None, None, "DMI-Index nicht verfügbar", "Messdaten können unabhängig erreichbar sein"))

    arctic = read_json("data/arctic_era5_maps/index.json")
    if isinstance(arctic, dict) and arctic.get("schema") == 2:
        mapped = []
        for day in arctic.get("days") or []:
            if not isinstance(day, dict) or not valid_date(day.get("date")):
                continue
            regions = day.get("regions") or {}
            complete = True
            for cap in ("60", "70", "80"):
                layer = regions.get(cap) or {}
                prefix = f"maps/"
                date_tag = day["date"].replace("-", "")
                if (layer.get("temperature_png") != f"{prefix}t2m_{cap}n_{date_tag}.png"
                    or layer.get("anomaly_png") != f"{prefix}anomaly_{cap}n_{date_tag}.png"
                    or not all(isinstance(layer.get(k), (int, float))
                               and not isinstance(layer.get(k), bool)
                               and abs(layer[k]) < 200 and layer[k] == layer[k]
                               for k in ("mean_c", "mean_anomaly_k"))):
                    complete = False
                    break
            if complete:
                mapped.append(day["date"])
        mapped = sorted(set(mapped))
        latest = mapped[-1] if mapped else None
        span = (date.fromisoformat(latest) - date.fromisoformat(mapped[0])).days + 1 if latest else 0
        gaps = max(0, span - len(mapped))
        target = arctic.get("target_days", 30)
        target = target if isinstance(target, int) and target > 0 else 30
        complete_archive = bool(arctic.get("ready") is True
            and len(mapped) >= target and gaps == 0
            and arctic.get("latest_date") == latest)
        items.append(result("era5_arctic_maps", "ERA5 Arktis · tägliche Temperaturkarten",
            "Arktis", latest, arctic.get("generated_utc"),
            f"{len(mapped)}/{target} vollständig kartierte Tage · 60/70/80–90°N"
            + (f" · {gaps} Lücken im Archivzeitraum" if gaps else ""),
            "Copernicus ERA5 · reale Rasterdaten · feste Temperaturskalen"
            + ("" if arctic.get("latest_date") == latest else " · Indexdatum weicht ab"),
            allowed_delay=8, incomplete=not complete_archive))
    else:
        items.append(result("era5_arctic_maps", "ERA5 Arktis · tägliche Temperaturkarten",
            "Arktis", None, None, "Kartenindex nicht verfügbar",
            "Die Karten werden nicht durch simulierte Daten ersetzt"))

    ice = read_json("sea_ice/index.json")
    if ice:
        for key, label in (("north", "Meereis Arktis"), ("south", "Meereis Antarktis")):
            hemi = ice.get(key) or {}
            count = len(hemi.get("years") or {})
            ready = ice.get("ready") and len(hemi.get("normal") or []) == 366
            items.append(result("ice_"+key, label, "Ozean",
                hemi.get("latest_date"), ice.get("created_utc"),
                f'{count} Jahrgänge · 366 Klimatologie-Kalendertage',
                "NSIDC Sea Ice Index v4 · Referenz 1991–2020",
                allowed_delay=6, incomplete=not ready))

    polar = read_json("data/polar_vortex/current.json")
    if polar and polar.get("ready") is True and polar.get("forecast") is False:
        items.append(result("polar_vortex", "Polarwirbel · 10-hPa-Karte", "Atmosphäre",
            polar.get("analysis_date"), polar.get("generated_utc"),
            "Eine statische Nordpolkarte · 25–90° N · ERA5-Tagesmittel",
            "Reanalyse mit mehrtägigem Veröffentlichungsverzug, keine Prognose",
            allowed_delay=13))
    else:
        items.append(result("polar_vortex", "Polarwirbel · 10-hPa-Karte", "Atmosphäre",
            None, None, "Noch keine verifizierte Karte veröffentlicht",
            "Karte folgt nach dem ersten erfolgreichen ERA5-Datenlauf"))

    block = read_json("data/blocking/current.json")
    if block and block.get("ready") is True and block.get("forecast") is False:
        items.append(result("blocking", "Europa · Blocking-Monitor", "Atmosphäre",
            block.get("analysis_date"), block.get("generated_utc"),
            f"{block.get('days_analysed', 0)} ERA5-Tagesfelder · {len(block.get('persistent_sectors') or [])} persistente Längengradsektoren",
            "Tibaldi-Molteni-artige Gradientendiagnose, keine Modellprognose",
            allowed_delay=13, incomplete=not block.get("history_complete",False)))
    else:
        items.append(result("blocking", "Europa · Blocking-Monitor", "Atmosphäre",
            None, None, "Noch keine verifizierte ERA5-Blocking-Karte",
            "Initialer CDS-Datenlauf und Kartenveröffentlichung ausstehend"))

    original = read_json("data/synoptic_charts/index.json")
    if original and original.get("ready") is True and original.get("charts"):
        charts=original["charts"]
        latest=max(x.get("valid_utc","") for x in charts)
        # Forecast valid times may be in the future; freshness belongs to the
        # published chart index, not the last forecast's target date.
        source_checks = original.get("source_status") or {}
        reported = [v for v in source_checks.values() if isinstance(v, dict)] if isinstance(source_checks, dict) else []
        working = sum(v.get("state") == "available" for v in reported)
        unavailable = [key for key,v in source_checks.items()
                       if isinstance(v, dict) and v.get("state") != "available"] if isinstance(source_checks, dict) else []
        items.append(result("synoptic_original", "Isobaren & Fronten · Originalkarten", "Europa",
            original.get("generated_utc"), original.get("generated_utc"),
            f"{len(charts)} Originalkarten · {len(set(x.get('publisher_id') or x['source_id'] for x in charts))} unabhängige Wetterdienste"
            + (f" · {working}/{len(reported)} geprüfte Quellen erreichbar" if reported else ""),
            f"Letzte Prognosegültigkeit {latest} · Erstellungszeit statt Zukunftsdatum"
            + (f" · Nicht verfügbar: {', '.join(unavailable[:4])}" if unavailable else ""),
            allowed_delay=3, incomplete=bool(unavailable)))
    else:
        items.append(result("synoptic_original", "Isobaren & Fronten · Originalkarten", "Europa",
            None, None, "Erster bestätigter Bildabruf steht aus",
            "DWD Open Data und AEMET, Frontenkarten mit echten UTC-Zeiten"))

    add_climate_indices(items)
    add_external(items, remote or {})
    add_extended_products(items, remote or {})
    # Ensembles are fetched per chosen location/model in the browser, not as a
    # central saved archive. No representative run date can be honestly asserted.
    items.append(result("ensembles", "Modell-Ensembles", "Vorhersagen", None, None,
        "ECMWF, AIFS, ICON-EU EPS und GEFS · standortbezogen",
        "Vorhersagedaten werden beim Ortsaufruf geladen; kein zentraler Modelllauf-Nachweis"))

    status_counts = {key: sum(x["status"] == key for x in items)
                     for key in ("current", "incomplete", "delayed", "unknown")}
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meaning": "Dataset metadata only; not a guarantee of error-free observations or complete backfills",
        "counts": status_counts,
        "datasets": items,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="_site/data/status/status.json")
    args = parser.parse_args()
    payload = build(external_archives())
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Datenstatus: {len(payload['datasets'])} Produkte, {payload['counts']}, nach {out}")


if __name__ == "__main__":
    main()

