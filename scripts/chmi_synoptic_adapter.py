#!/usr/bin/env python3
"""ČHMÚ official playableImages synoptic chart adapter.

Date/time is taken EXCLUSIVELY from the provider's exact ISO8601 dateTime
field in its public /api/playableImages/init/synopticka-mapa response.
No hourly rounding, no guess from issue timestamps or HTTP modification date.
The provider API calls these playable images and returns base64-encoded PNGs.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime,timedelta,timezone

PAGE="https://www.chmi.cz/predpoved-pocasi/synopticka-situace"
API="https://data-provider.chmi.cz/api/playableImages/init/synopticka-mapa"
DATE_RE=re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
PNG_HEADER=bytes.fromhex("89504e470d0a1a0a")


def parse_chmi_json(payload,now):
    if not isinstance(payload,dict) or not isinstance(payload.get("data"),list):
        raise ValueError("ČHMÚ: unexpected playableImages payload")
    data=payload["data"]
    if not 1<=len(data)<=25:
        raise ValueError("ČHMÚ: unexpected chart count")
    if payload.get("type") not in (None,"image"):
        raise ValueError("ČHMÚ: unexpected API media type")
    records={}
    for item in data:
        if not isinstance(item,dict):continue
        rawdate=item.get("dateTime")
        encoded=item.get("image")
        if not isinstance(rawdate,str) or not DATE_RE.fullmatch(rawdate):
            continue
        valid=datetime.strptime(rawdate,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if not (now-timedelta(hours=48) <= valid <= now+timedelta(hours=96)):
            continue
        if not isinstance(encoded,str) or not encoded.startswith("image/png;base64,"):
            continue
        image_data=base64.b64decode(encoded.partition(",")[2],validate=True)
        if len(image_data)<18000 or len(image_data)>12_000_000 or not image_data.startswith(PNG_HEADER):
            raise ValueError("ČHMÚ: invalid PNG image in official payload")
        stamp=valid.isoformat(timespec="minutes")
        record={
            "source_id":"chmi",
            "publisher_id":"chmi",
            "kind":"Originalkarte",
            "valid_utc":stamp,
            "issued_utc":None,
            "source_url":API,
            "source_page":PAGE,
            "credit":"© ČHMÚ · CC BY 4.0 · technisch ins WebP-Format umgewandelt",
            "provider_time_semantics":"dateTime aus ČHMÚ-playableImages-API (UTC)",
            "is_forecast_start":item.get("isForecastStart"),
        }
        records[stamp]=(record,image_data)
    return [records[key] for key in sorted(records)]
