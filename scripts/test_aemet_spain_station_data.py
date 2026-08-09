#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

API_ROOT = "https://opendata.aemet.es/opendata/api"
INVENTORY_PATH = "/valores/climatologicos/inventarioestaciones/todasestaciones"
DAILY_ALL_PATH = (
    "/valores/climatologicos/diarios/datos/"
    "fechaini/{start}/fechafin/{end}/todasestaciones"
)

USER_AGENT = "climate-dashboard-aemet-probe/1.0"
MAX_TRIES = 6


def request_json(url: str, *, api_key: str | None = None, label: str = "AEMET") -> Any:
    if api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode({'api_key': api_key})}"

    last_error: Exception | None = None
    for attempt in range(1, MAX_TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "Cache-Control": "no-cache",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                raw = response.read()
            text = raw.decode("utf-8-sig", errors="replace").strip()
            if not text:
                raise RuntimeError(f"{label}: leere HTTP-Antwort.")
            return json.loads(text)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 401:
                raise RuntimeError(f"{label}: HTTP 401 – AEMET_API_KEY nicht akzeptiert.") from exc
            if exc.code == 403:
                raise RuntimeError(f"{label}: HTTP 403 – Zugriff verweigert.") from exc
            if exc.code == 404:
                body = exc.read().decode("utf-8", errors="replace")[:800]
                raise RuntimeError(f"{label}: HTTP 404 – {body}") from exc
            if exc.code == 429:
                wait = max(70, 20 * attempt)
                print(f"{label}: HTTP 429 – Limit erreicht; warte {wait}s …", flush=True)
                time.sleep(wait)
                continue
            if exc.code >= 500:
                wait = min(120, 10 * attempt)
                print(f"{label}: HTTP {exc.code}; warte {wait}s …", flush=True)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt == MAX_TRIES:
                break
            wait = min(60, 5 * attempt)
            print(f"{label}: Versuch {attempt}/{MAX_TRIES} fehlgeschlagen: {exc}; warte {wait}s …", flush=True)
            time.sleep(wait)

    raise RuntimeError(f"{label}: nach {MAX_TRIES} Versuchen fehlgeschlagen: {last_error}")


def fetch_data_url(api_path: str, api_key: str, label: str) -> Any:
    meta_url = API_ROOT + api_path
    meta = request_json(meta_url, api_key=api_key, label=f"{label} Metadaten")

    if not isinstance(meta, dict):
        raise RuntimeError(f"{label}: unerwartete Metadatenantwort: {type(meta).__name__}")

    estado = meta.get("estado")
    if estado not in (None, 200, "200"):
        raise RuntimeError(
            f"{label}: AEMET estado={estado}: {meta.get('descripcion', 'keine Beschreibung')}"
        )

    data_url = meta.get("datos")
    if not isinstance(data_url, str) or not data_url.strip():
        raise RuntimeError(f"{label}: AEMET lieferte keine 'datos'-URL.")

    return request_json(data_url.strip(), label=f"{label} Daten")


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NULL", "-"}:
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def normalized_daily_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        # Defensive handling in case AEMET returns an object wrapper.
        if isinstance(payload.get("datos"), list):
            payload = payload["datos"]
        else:
            payload = [payload]

    if not isinstance(payload, list):
        raise RuntimeError(f"Tagesdaten: unerwarteter Typ {type(payload).__name__}")

    rows: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue

        sid = str(raw.get("indicativo", "")).strip()
        day = str(raw.get("fecha", "")).strip()
        tmax = parse_number(raw.get("tmax"))
        tmin = parse_number(raw.get("tmin"))

        if not sid or len(day) < 10:
            continue
        if tmax is None and tmin is None:
            continue

        rows.append(
            {
                "indicativo": sid,
                "fecha": day[:10],
                "nombre": str(raw.get("nombre", "")).strip(),
                "provincia": str(raw.get("provincia", "")).strip(),
                "tmax": tmax,
                "tmin": tmin,
            }
        )
    return rows


def self_test() -> None:
    sample = [
        {
            "fecha": "2022-07-15",
            "indicativo": "TEST1",
            "nombre": "TEST",
            "provincia": "TEST",
            "tmax": "40,1",
            "tmin": "22,3",
        },
        {
            "fecha": "2022-07-15",
            "indicativo": "TEST2",
            "tmax": "",
            "tmin": "17.2",
        },
    ]
    rows = normalized_daily_rows(sample)
    assert len(rows) == 2
    assert rows[0]["tmax"] == 40.1
    assert rows[0]["tmin"] == 22.3
    assert rows[1]["tmax"] is None
    assert rows[1]["tmin"] == 17.2
    print("AEMET Spain probe self-test OK")


def live_probe(api_key: str) -> None:
    print("=== AEMET SPANIEN · LIVE-PROBE ===", flush=True)

    inventory = fetch_data_url(
        INVENTORY_PATH,
        api_key,
        "Stationsinventar",
    )
    if not isinstance(inventory, list):
        raise RuntimeError("Stationsinventar ist keine Liste.")
    inventory_ids = {
        str(row.get("indicativo", "")).strip()
        for row in inventory
        if isinstance(row, dict) and str(row.get("indicativo", "")).strip()
    }
    print(f"AEMET Stationsinventar: {len(inventory_ids):,} Stationskennungen.", flush=True)
    if len(inventory_ids) < 100:
        raise RuntimeError("AEMET Stationsinventar unerwartet klein.")

    # Bekannter heißer Zeitraum; bewusst nur 11 Kalendertage.
    start = "2022-07-10T00:00:00UTC"
    end = "2022-07-20T23:59:59UTC"
    path = DAILY_ALL_PATH.format(start=start, end=end)

    payload = fetch_data_url(path, api_key, "Tagesklimatologie 10.–20.07.2022")
    rows = normalized_daily_rows(payload)

    station_ids = {row["indicativo"] for row in rows}
    tmax_values = [row["tmax"] for row in rows if row["tmax"] is not None]
    tmin_values = [row["tmin"] for row in rows if row["tmin"] is not None]
    days = sorted({row["fecha"] for row in rows})

    print(f"Tagesdatensätze mit TMAX/TMIN: {len(rows):,}", flush=True)
    print(f"Stationen mit Daten: {len(station_ids):,}", flush=True)
    print(f"Kalendertage: {len(days)} ({days[0] if days else '-'} bis {days[-1] if days else '-'})", flush=True)
    print(f"TMAX-Werte: {len(tmax_values):,}", flush=True)
    print(f"TMIN-Werte: {len(tmin_values):,}", flush=True)

    if not rows:
        raise RuntimeError("AEMET lieferte keine verwertbaren TMAX/TMIN-Tageswerte.")
    if len(station_ids) < 100:
        raise RuntimeError(f"Nur {len(station_ids)} Stationen mit Daten – unerwartet wenig.")
    if len(days) < 8:
        raise RuntimeError(f"Nur {len(days)} Tage im 11-Tage-Testfenster.")
    if not tmax_values or not tmin_values:
        raise RuntimeError("TMAX oder TMIN fehlt vollständig.")

    max_row = max((r for r in rows if r["tmax"] is not None), key=lambda r: r["tmax"])
    min_row = min((r for r in rows if r["tmin"] is not None), key=lambda r: r["tmin"])

    print(
        "Höchste TMAX im Probezeitraum: "
        f"{max_row['tmax']:.1f} °C | {max_row['fecha']} | "
        f"{max_row['nombre'] or max_row['indicativo']} ({max_row['indicativo']})",
        flush=True,
    )
    print(
        "Niedrigste TMIN im Probezeitraum: "
        f"{min_row['tmin']:.1f} °C | {min_row['fecha']} | "
        f"{min_row['nombre'] or min_row['indicativo']} ({min_row['indicativo']})",
        flush=True,
    )

    # Sanity bounds only, not climatological assertions.
    if not (35.0 <= max_row["tmax"] <= 55.0):
        raise RuntimeError(f"Unplausible höchste TMAX: {max_row['tmax']}")
    if not (-20.0 <= min_row["tmin"] <= 35.0):
        raise RuntimeError(f"Unplausible niedrigste TMIN: {min_row['tmin']}")

    overlap = len(station_ids & inventory_ids)
    print(f"Direkte Treffer im Inventar: {overlap:,}/{len(station_ids):,}", flush=True)
    if overlap < max(50, int(len(station_ids) * 0.8)):
        raise RuntimeError("Zu wenige Tagesdaten-Stationen lassen sich dem Inventar zuordnen.")

    print("AEMET SPAIN LIVE-PROBE OK", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    api_key = os.environ.get("AEMET_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AEMET_API_KEY fehlt.")

    live_probe(api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
