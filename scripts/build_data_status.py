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
           allowed_delay=5, incomplete=False):
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
            status = "unknown" if delta < -1 else ("delayed" if lag > allowed_delay else "current")
        except ValueError:
            lag, status = None, "unknown"
    elif cadence == "monthly":
        lag = (today.year - latest.year)*12 + today.month - latest.month
        status = "delayed" if lag > allowed_delay else "current"
    else:
        lag = (today - latest).days
        status = "delayed" if lag > allowed_delay else "current"
    if incomplete and status == "current":
        status = "incomplete"
    return {
        "id": id, "label": label, "group": group,
        "latest": date_value if latest else None,
        "updated": updated if isinstance(updated, str) else None,
        "coverage": str(coverage), "note": note,
        "cadence": cadence, "lag": lag, "status": status,
    }


def external_archives():
    """Best-effort snapshot of separately published public data branches.

    Pages stays deployable even if an external branch is absent or unavailable.
    No API token and no GitHub access from the public browser are required.
    """
    base = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/"
    sources = {
        "mosmix": "mosmix-data/data/mosmix/manifest.json",
        "mosmix_quality": "mosmix-data/data/mosmix/quality_status.json",
        "fast_live": "fast-live/fast_state.json",
        "europe_tmax": "europe-tmax-lab-data/data/europe-tmax-lab/current.json",
        "europe_tmin": "europe-tmin-lab-data/data/europe-tmin-lab/current.json",
        "icon": "icon-hazards-data/data/icon-hazards/current.json",
        "sst": "sst-archive/manifest.json",
        "ssw": "stratosphere-data/data/stratosphere/ssw_catalog.json",
    }
    result = {}
    for name, suffix in sources.items():
        try:
            req = Request(base + suffix, headers={"User-Agent": "ClimateDashboard-Status/1"})
            with urlopen(req, timeout=12) as response:
                # Reject unexpectedly huge or empty payloads, without breaking deployment.
                data = response.read(24 * 1024 * 1024 + 1)
            if not data or len(data) > 24 * 1024 * 1024:
                raise ValueError("Archive size not supported")
            obj = json.loads(data)
            if not isinstance(obj, dict):
                raise ValueError("Archive metadata is not an object")
            result[name] = obj
            print(f"Externer Datenbestand {name}: geladen ({len(data)} Bytes)")
        except (OSError, ValueError, HTTPError, URLError, TimeoutError) as exc:
            print(f"Externer Datenbestand {name}: nicht prüfbar ({type(exc).__name__})")
    return result


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


def add_external(items, remote):
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
            note, allowed_delay=2, incomplete=not (good and quality_ok)))
    else:
        items.append(result("mosmix", "MOSMIX-L", "Vorhersagen", None, None,
            "Laufmetadaten fehlen", "Datenzweig vorübergehend nicht prüfbar"))

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
            cycle_date = datetime.strptime(cycle, "%Y%m%d%H").date().isoformat()
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
        items.append(result("europe_" + mode, title, "Vorhersagen",
            cycle_date, archive.get("built_utc"),
            f"{len(days)}/5 Tage · {min(valid_counts, default=0)}–{max(valid_counts, default=0)}/31 Städte · "
            f"Raster mindestens {min((round(day.get('coverage', 0)*100) for day in days if isinstance(day, dict)), default=0)} %",
            f"ICON-Modelllauf {cycle or '–'} · Prognosen {first} bis {last}{missing_note} · "
            "Datenbranch-Manifest, kein Browser-Bildtest",
            allowed_delay=2, incomplete=not good))

    fast = remote.get("fast_live")
    if isinstance(fast, dict) and fast.get("station_count", 0) > 0:
        items.append(result("fast_live", "DWD SYNOP Fast Live", "Stationen",
            fast.get("latest_measurement_utc"), fast.get("generated_at_utc"),
            f"{fast.get('station_count')} SYNOP/CDC-zugeordnete Stationen · "
            f"{fast.get('source_file_count', 0)} DWD-Dateien",
            "Ergänzung zu den DWD-10-Minuten-Messungen · aktuelle SYNOP-Veröffentlichung",
            cadence="hourly", allowed_delay=3))
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
            allowed_delay=2, incomplete=not good))
    else:
        items.append(result("icon_hazards", "ICON-EU Wettergefahren", "Vorhersagen",
            None, None, "Laufmetadaten fehlen", "Datenzweig vorübergehend nicht prüfbar"))

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


def add_climate_indices(items):
    p = read_json("climate_indices/index.json")
    if not p or not p.get("ready"):
        items.append(result("noaa_indices", "Atmosphärische Indizes", "Indizes",
                            None, None, "Indexarchiv fehlt oder unvollständig",
                            "NAO, AO, ENSO, QBO und MJO noch nicht überprüfbar"))
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
    keys=("scand","ea","eawr","gbi")
    sources=[europe.get(key) or {} for key in keys]
    items.append(result("circulation", "SCAND, EA, EA/WR und GBI", "Indizes",
        common_latest(*(v.get("latest_month") for v in sources)), stamp,
        "4 monatliche Zirkulationsindizes",
        "Datenstand des ältesten der vier Indizes", cadence="monthly", allowed_delay=4,
        incomplete=any(len(v.get("monthly") or [])<300 for v in sources)))
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
        items.append(result("snow", "Stationsschneehöhe", "Stationen",
            snow.get("data_through"), snow.get("generated_at"),
            f'{observed}/{possible} Stationen mit Saisonwerten',
            "Fehlende Stationsmeldungen werden nicht als 0 cm gewertet", allowed_delay=5,
            incomplete=bool(possible and observed is not None and observed < possible)))

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
        items.append(result("era5_strat", "ERA5 Stratosphäre", "Atmosphäre",
            estrat.get("data_through"), estrat.get("generated_at"),
            f'Referenz 1991–2020: {complete}/30 Jahre vollständig',
            "Historische Referenz unvollständig" if complete < 30 else "Historische Referenz vollständig",
            allowed_delay=14, incomplete=complete < 30))

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
        items.append(result("synoptic_original", "Isobaren & Fronten · Originalkarten", "Europa",
            original.get("generated_utc"), original.get("generated_utc"),
            f"{len(charts)} Originalkarten · {len(set(x.get('publisher_id') or x['source_id'] for x in charts))} unabhängige Wetterdienste",
            f"Letzte Prognosegültigkeit {latest} · Erstellungszeit statt Zukunftsdatum für Aktualitätsprüfung",
            allowed_delay=3))
    else:
        items.append(result("synoptic_original", "Isobaren & Fronten · Originalkarten", "Europa",
            None, None, "Erster bestätigter Bildabruf steht aus",
            "DWD Open Data und AEMET, Frontenkarten mit echten UTC-Zeiten"))

    add_climate_indices(items)
    add_external(items, remote or {})
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
