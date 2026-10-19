#!/usr/bin/env python3
"""Fail-closed rights and timestamp gate for possible European synoptic sources.

This is an admission audit, NOT a copyright waiver and NOT a web scraper.
Adding a provider here NEVER copies its images: only verified, source-specific
image parsers may eventually activate it in the actual UTC chart index.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"synoptic_charts"/"europe_source_audit.json"
SOURCES={
 "dmi":{"country":"Dänemark","url":"https://www.dmi.dk/vejret/frontkort",
  "map":"analysis_forecast","rights":"permission_required","timestamp":"not_machine_verified",
  "details":"Direkter Originalkarten-Viewer. Kartenbilder nicht ohne schriftliche Einwilligung übernehmen.",
  "terms_url":"https://www.dmi.dk/"},
 "shmu":{"country":"Slowakei","url":"https://www.shmu.sk/en/?page=980",
  "map":"analysis","rights":"permission_required","timestamp":"image_printed",
  "details":"Datum im Bild und URL bekannt. Öffentliche Bildweiterverwendung nicht pauschal lizenziert.",
  "terms_url":"https://www.shmu.sk/en/?page=980"},
 "kmi":{"country":"Belgien","url":"https://www.meteo.be/de/wetter/vorhersage/frontenkarten",
  "map":"forecast","rights":"permission_required","timestamp":"not_machine_verified",
  "details":"Täglich aktualisierte Frontenkarten; Veröffentlichung/Kopien ohne schriftliche Genehmigung untersagt.",
  "terms_url":"https://fr.meteo.be/de/uber-das-kmi/rechtsinformation/disclaimer"},
 "hungaromet":{"country":"Ungarn","url":"https://www.met.hu/en/idojaras/aktualis_idojaras/front/",
  "map":"fronts","rights":"permission_required","timestamp":"iframe_not_verified",
  "details":"Fronteniframe vorhanden; Bilder dürfen nicht ohne schriftliche Erlaubnis weiterverbreitet werden.",
  "terms_url":"https://www.met.hu/methu/szerzoi_jogok/"},
 "meteoswiss":{"country":"Schweiz","url":"https://www.meteoschweiz.admin.ch/service-und-publikationen/applikationen/allgemeine-lage.html",
  "map":"general_situation","rights":"map_not_covered_by_ogd","timestamp":"not_machine_verified",
  "details":"Offene MeteoSchweiz-Daten sind nutzbar, aber fertige Karten nicht automatisch Open Data.",
  "terms_url":"https://opendatadocs.meteoswiss.ch/de/general/terms-of-use"},
 "metie":{"country":"Irland","url":"https://www.met.ie/latest-reports/surface-analysis",
  "map":"analysis","rights":"permission_required","timestamp":"page_display_only",
  "details":"Originalanalyse; Website-Bilder derzeit nur extern verlinkt.",
  "terms_url":"https://www.met.ie/"},
 "metie_forecast":{"country":"Irland","url":"https://www.met.ie/forecasts/atlantic-charts/precipitation-pressure",
  "map":"forecast","rights":"permission_required","timestamp":"page_display_only",
  "details":"Atlantikprognosen; keine Freigabe zur automatischen Bildkopie.",
  "terms_url":"https://www.met.ie/"},
 "metoffice":{"country":"Großbritannien","url":"https://weather.metoffice.gov.uk/maps-and-charts/surface-pressure",
  "map":"analysis_forecast","rights":"permission_required","timestamp":"not_machine_verified",
  "details":"Originalkarten verlinken; kein automatisiertes Kopieren der Met-Office-Grafiken.",
  "terms_url":"https://www.metoffice.gov.uk/about-us/legal"},
 "smhi":{"country":"Schweden","url":"https://www.smhi.se/klimat/klimatet-da-och-nu/manadens-vader-och-vatten-i-sverige",
  "map":"archive","rights":"original_unmodified_only","timestamp":"archive_validity_known",
  "details":"2 Analysen je Tag im Monatsrückblick; Originalkarten mit Quellenangabe ohne Bearbeitung, kein tagesaktueller Feed.",
  "terms_url":"https://www.smhi.se/en/about-smhi/about-this-website/copyright-on-smhis-website"},
 "imo":{"country":"Island","url":"https://en.vedur.is/weather/shipping/atlantic/",
  "map":"pressure_forecast_no_fronts","rights":"reuse_with_attribution","timestamp":"printed_run_and_validity_ocr",
  "details":"ECMWF-Isobarenprognose ohne Fronten. Nur Bilder mit übereinstimmenden aufgedruckten Validitätsterminen und gedruckter UTC-Modelllaufzeit plus Prognosestunde sind zur automatischen Darstellung zugelassen.",
  "terms_url":"https://en.vedur.is/about-imo/the-web/conditions/"},
 "fmi":{"country":"Finnland","url":"https://en.ilmatieteenlaitos.fi/weather-in-europe",
  "map":"general_situation","rights":"not_verified","timestamp":"not_machine_verified",
  "details":"Verifizierte Kartenbildadresse fehlt, Symbollegende ist keine Wetterkarte.",
  "terms_url":"https://en.ilmatieteenlaitos.fi/"},
 "meteoam":{"country":"Italien","url":"https://www.meteoam.it/it/suolo",
  "map":"analysis","rights":"not_verified","timestamp":"javascript_only",
  "details":"Suolo-Kartenansicht; UTC-Gültigkeit und Weiterverwendung noch ungeklärt.",
  "terms_url":"https://www.meteoam.it/"},
 "meteofrance":{"country":"Frankreich","url":"https://meteofrance.com/isofronts",
  "map":"analysis_forecast","rights":"not_verified","timestamp":"not_machine_verified",
  "details":"Isofronts-Kartenviewer; prüfbare datierte Originalbild-API und Freigabe fehlen.",
  "terms_url":"https://meteofrance.com/"},
}
def image_admissible(policy:dict, has_valid_utc:bool=False, independently_dated:bool=False)->bool:
    """A map must have both rights and independently verifiable exact validity."""
    return (policy.get("rights") in {"reuse_with_attribution","open_chart_license"}
            and has_valid_utc and independently_dated
            and policy.get("timestamp") not in {"not_machine_verified","image_printed_only","javascript_only","iframe_not_verified"})
def build(now:datetime|None=None)->dict:
    now=now or datetime.now(timezone.utc)
    entries=[]
    for provider,policy in sorted(SOURCES.items()):
        entries.append({"id":provider,**policy,
            "reproduction_ready":image_admissible(policy),
            "status":"Originalbild nicht automatisch freigegeben",
            "audit_note":"Lizenz- und Zeitstempelprüfung anhand der dokumentierten Dienstbedingungen; KEIN Live-Verfügbarkeitstest."})
    return {"schema_version":1,"checked_utc":now.isoformat(timespec="seconds"),
            "method":"static_provider_terms_and_timestamp_readiness",
            "no_live_check":True,"providers":entries}
def main(output:Path=OUT):
    data=build()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"European source readiness: {len(data['providers'])} examined, no unverified images admitted")
    return data
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=OUT)
    main(p.parse_args().output)
