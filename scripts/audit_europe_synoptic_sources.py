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
 "italiameteo_isobars":{"country":"Italien","url":"https://meteohub.agenziaitaliameteo.it/app/maps/meteotiles",
  "map":"icon2i_pressure_isobars_no_fronts","rights":"chart_specific_clearance_required","timestamp":"model_run_and_slider_not_image_verified",
  "details":"ItaliaMeteo-Originalkarten mit ICON-2I-Bodendruck/Isobaren, 00/12 UTC und +72h. Dataset CC BY, aber Kartenbildfreigabe und exaktes einzelnes Bildmapping fehlen.",
  "terms_url":"https://meteohub.agenziaitaliameteo.it/ui/about/"},
 "italiameteo_opendata":{"country":"Italien","url":"https://dati.agenziaitaliameteo.it/dataset/previsioni-meteorologiche-modello-icon-2i",
  "map":"open_model_pressure_data_not_a_chart","rights":"open_model_data_ccby","timestamp":"dataset_has_run_metadata_not_chart",
  "details":"Offene ICON-2I-Modellfelder unter CC BY; kein fertig gestaltetes Originalkartenbild. Daten könnten später separat für eigene Karten verwendet werden.",
  "terms_url":"https://dati.agenziaitaliameteo.it/dataset/previsioni-meteorologiche-modello-icon-2i"},
 "cyprus_dom_wrf":{"country":"Zypern","url":"https://www.dom.org.cy/WRF4/00Z/01/SLP_W10m_T2m/index.html",
  "map":"wrf_pressure_wind_temperature_no_fronts","rights":"chart_specific_clearance_required","timestamp":"pending_exact_init_and_valid_utc_image_ocr",
  "details":"DOM-Zypern WRF v4.1.3, 8-km-Druck-/Wind-/Temperaturkarten ohne Fronten. Statische GIF-Folgen für 00/12-UTC-Modellläufe enthalten kein Kalenderdatum im Dateinamen. Ein eigener Prüfer kontrolliert gedruckte INIT- und VALID-UTC-Zeit je Stichprobe. Die CC-BY-Freigabe bestimmter Zypern-Punktwert-Datensätze gilt nicht automatisch für diese Kartenbilder; Weiterverwendung bis zur konkreten Freigabe nur als Link.",
  "terms_url":"https://www.dom.org.cy/"},
 "arso_synoptic_archive":{"country":"Slowenien","url":"https://meteo.arso.gov.si/uploads/probase/www/climate/text/sl/weather_events/neurja-16sep2025.pdf",
  "map":"historical_europe_fronts_event_report","rights":"not_verified","timestamp":"printed_2025_event_date",
  "details":"ARSO-Bericht von 16.09.2025 mit Frontenanalyse im PDF; historisch, keine laufende Live-Kartenbereitstellung.",
  "terms_url":"https://meteo.arso.gov.si/"},
 "lvgmc_front_archive":{"country":"Lettland","url":"https://klimats.meteo.lv/enciklopedija/ekstremi/lietavas_rezekne_2017/Nokrisni_Latgale_2017-08.pdf",
  "map":"historical_europe_surface_front_analysis","rights":"not_verified","timestamp":"printed_2017_08_22_18_utc",
  "details":"LVĢMC-Originalanalyse 22.08.2017 18 UTC mit Isobaren und Fronten, veröffentlicht in einem archivierten Ereignisbericht.",
  "terms_url":"https://klimats.meteo.lv/"},
 "nimh_history":{"country":"Bulgarien","url":"https://www.weather.bg/1en/index.php?koiFail=zaNas&lng=0",
  "map":"documented_europe_balkans_frontal_analysis","rights":"permission_required",
  "timestamp":"no_public_machine_dated_chart",
  "details":"NIMH dokumentiert eigenständige 3-stündliche synoptische Karten mit Frontensystemen. Keine verifizierte öffentliche aktuelle Originalbildadresse.",
  "terms_url":"https://www.weather.bg/"},
 "albania_igeo":{"country":"Albanien","url":"https://geo.edu.al/MonitoringForecast/Hydrologic_Meteorological_Forecast/","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Amtliches Institut mit Modell-/Wetterberichten. Keine überprüfte eigenständige aktuelle Isobaren-/Frontenbildserie.","terms_url":"https://geo.edu.al/MonitoringForecast/Hydrologic_Meteorological_Forecast/"},
 "andorra_meteo":{"country":"Andorra","url":"https://www.meteo.ad/en","map":"regional_coverage","rights":"not_verified","timestamp":"not_machine_verified","details":"Offizielle Wetter- und Stationsdaten; keine eigenständige synoptische Europakarte nachgewiesen. Für regionale Isobaren AEMET/Météo-France nutzen.","terms_url":"https://www.meteo.ad/en"},
 "belarus_belhydromet":{"country":"Belarus","url":"https://pogoda.by/weather/synoptic/","map":"synoptic_viewer","rights":"permission_required","timestamp":"viewer_time_not_image_verified","details":"Offizieller Synoptikbereich; aktuelle Grafik-URL, vollständige UTC-Gültigkeit und Rechte noch ungeprüft.","terms_url":"https://pogoda.by/weather/synoptic/"},
 "bosnia_fhmz_gfs":{"country":"Bosnien und Herzegowina","url":"https://www.fhmzbih.gov.ba/latinica/METEO/GFSprognoza.php","map":"numerical_model_maps","rights":"permission_required","timestamp":"not_machine_verified","details":"Offizielle GFS-Modellprognosen in 3-Stunden-Schritten. Isobarenparameter, Modelllaufdatum und Originalbildrechte noch einzeln zu verifizieren; kein unabhängiges Analyseprodukt.","terms_url":"https://www.fhmzbih.gov.ba/latinica/METEO/GFSprognoza.php"},
 "liechtenstein_swiss":{"country":"Liechtenstein","url":"https://www.meteoschweiz.admin.ch/service-und-publikationen/applikationen/allgemeine-lage.html","map":"regional_coverage","rights":"not_verified","timestamp":"not_machine_verified","details":"Regionale Abdeckung durch MeteoSchweiz, bereits unter Schweiz vorhanden. Kein eigener liechtensteinischer Originalkartenherausgeber nachgewiesen.","terms_url":"https://www.meteoschweiz.admin.ch/service-und-publikationen/applikationen/allgemeine-lage.html"},
 "luxembourg_meteolux":{"country":"Luxemburg","url":"https://www.meteolux.lu/fr/produits-et-services/produits-aeronautiques/cartes-du-temps-significatif/","map":"registration_required","rights":"permission_required","timestamp":"login_required","details":"West-Europa-/Benelux-TEMSI-Karten mit Fronten und Druckzentren alle 3 Stunden; Registrierung nötig. Autoren Météo-France bzw. Skeyes, nicht unabhängiger Luxemburger Kartenherausgeber.","terms_url":"https://www.meteolux.lu/fr/produits-et-services/produits-aeronautiques/cartes-du-temps-significatif/"},
 "malta_metoffice":{"country":"Malta","url":"https://www.maltairport.com/weather/","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Staatlich beauftragter Luftfahrt-Wetterdienst. Historische handgezeichnete Karten dokumentiert, kein offener aktueller Isobarenbildfeed belegt.","terms_url":"https://www.maltairport.com/weather/"},
 "moldova_shs":{"country":"Moldau","url":"https://www.meteo.md/","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Offizieller Wetterdienst; operationelle Synoptik ist dokumentiert, aber keine überprüfte öffentliche Karte mit vollständigem UTC-Datum.","terms_url":"https://www.meteo.md/"},
 "monaco_france":{"country":"Monaco","url":"https://meteofrance.com/","map":"regional_coverage","rights":"not_verified","timestamp":"not_machine_verified","details":"Regional zuständiges französisches Wetterangebot. Kein unabhängiger amtlicher Monaco-Isobarenkartenherausgeber gefunden; Météo-France bereits erfasst.","terms_url":"https://meteofrance.com/"},
 "montenegro_zhms":{"country":"Montenegro","url":"https://www.meteo.co.me/","map":"numerical_model_maps","rights":"permission_required","timestamp":"not_machine_verified","details":"Nationaler hydrometeorologischer Dienst mit WRF-Modellkarten; konkretes MSLP-/Isobarenprodukt und Bildgültigkeit noch nicht nachgewiesen.","terms_url":"https://www.meteo.co.me/"},
 "northmacedonia_uhmr":{"country":"Nordmazedonien","url":"https://uhmr.gov.mk/","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Amtlicher hydrometeorologischer Dienst; keine nachgewiesene Original-Bodenanalyse mit öffentlicher UTC-Bildschnittstelle.","terms_url":"https://uhmr.gov.mk/"},
 "russia_hmc_analysis":{"country":"Russland","url":"https://meteoinfo.ru/mapsynop","map":"synoptic_analysis","rights":"permission_required","timestamp":"four_utc_slots_no_image_verified","details":"Echte amtliche Bodenanalysen zu vier UTC-Terminen täglich. Einzelbildadresse, vollständiges Kartendatum, Rechte und Zugriff noch separat prüfen.","terms_url":"https://meteoinfo.ru/mapsynop"},
 "russia_hmc_forecast":{"country":"Russland","url":"https://meteoinfo.ru/prognosticheskie-karty","map":"synoptic_forecast","rights":"permission_required","timestamp":"not_machine_verified","details":"Originale synoptische Bodenprognosen +24, +36, +60 h auf Basis 00 UTC. Bildverfügbarkeit und Copyright ungeprüft.","terms_url":"https://meteoinfo.ru/prognosticheskie-karty"},
 "sanmarino_italy":{"country":"San Marino","url":"https://www.meteoam.it/it/meteo-citta/front","map":"regional_coverage","rights":"not_verified","timestamp":"not_machine_verified","details":"Regionale Abdeckung durch italienische Frontenkarten; kein eigener staatlicher Europa-Synoptik-Bilddienst belegt.","terms_url":"https://www.meteoam.it/it/meteo-citta/front"},
 "ukraine_uhmc":{"country":"Ukraine","url":"https://www.meteo.gov.ua/en/","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Amtliche Wetter- und Prognoseprodukte; kein überprüfter aktueller Originalbildfeed für europäische Isobaren/Fronten.","terms_url":"https://www.meteo.gov.ua/en/"},
 "vatican_italy":{"country":"Vatikanstadt","url":"https://www.meteoam.it/it/meteo-citta/front","map":"regional_coverage","rights":"not_verified","timestamp":"not_machine_verified","details":"Rom-/Vatikanregion durch italienische Frontenkarten abgedeckt. Keine eigenständige amtliche Vatikan-Synoptikkarte bekannt.","terms_url":"https://www.meteoam.it/it/meteo-citta/front"},
 "kosovo_ihmk":{"country":"Kosovo","url":"https://ihmk-rks.net/","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Offizieller meteorologischer Dienst mit Stations- und Wetterdaten; keine nachgewiesene Europa-Isobarenkarte.","terms_url":"https://ihmk-rks.net/"},
 "armenia_hmc":{"country":"Armenien","url":"https://meteomonitoring.am/en/web","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Staatlicher Hydrometeorologiedienst; operationelle Wetter- und Modellprodukte, aktueller Original-Isobarenfeed nicht verifiziert.","terms_url":"https://meteomonitoring.am/en/web"},
 "armenia_archive":{"country":"Armenien","url":"https://www.new.meteomonitoring.am/web/information-platform/publications","map":"historical_publication_archive","rights":"permission_required","timestamp":"historical_pdf_not_live","details":"Historischer amtlicher Jahresbericht mit synoptischen Wetterkarten. Einzelne Karten nicht als aktuelle Live-Quelle ausgeben.","terms_url":"https://www.new.meteomonitoring.am/web/information-platform/publications"},
 "azerbaijan_nhms":{"country":"Aserbaidschan","url":"https://meteo.az/","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Amtlicher Dienst und meteorologische Karten; kein unabhängig datiertes Isobaren-/Frontenbild identifiziert.","terms_url":"https://meteo.az/"},
 "georgia_nea":{"country":"Georgien","url":"https://nea.gov.ge/En/Departments/Hydrometeorology","map":"official_portal","rights":"not_verified","timestamp":"not_machine_verified","details":"Nationale Wetter- und SYNOP-Produkte beschrieben; eigene aktuelle öffentliche Fronten-/Bodenanalysebilder ungeprüft.","terms_url":"https://nea.gov.ge/En/Departments/Hydrometeorology"},
 "kazakhstan_synoptic":{"country":"Kasachstan","url":"https://www.kazhydromet.kz/en/weather/sinopticheskie-karty-pogody","map":"synoptic_viewer","rights":"permission_required","timestamp":"viewer_time_not_image_verified","details":"Amtlicher Synoptikkartenviewer mit Datums-, UTC-Zeit- und Quelldateiauswahl. Vollständige Bild-UTC, API und Kartenrechte noch maschinell zu verifizieren.","terms_url":"https://www.kazhydromet.kz/en/weather/sinopticheskie-karty-pogody"},
 "rhmz":{"country":"Serbien","url":"https://hidmet.gov.rs/eng/osmotreni/analiza.php",
  "map":"synoptic_analysis_europe_and_balkans","rights":"permission_required","timestamp":"hours_without_full_date",
  "details":"RHMZ bietet synoptische Europaanalysen 00/12 UTC und weitere Balkananalysezeiten. Datum/Originalbildlizenz nicht gesichert; ohne Einwilligung keine Kopie.",
  "terms_url":"https://hidmet.gov.rs/eng/osmotreni/analiza.php"},
 "hnms":{"country":"Griechenland","url":"https://www.emy.gr/en/marine",
  "map":"surface_pressure_europe","rights":"not_verified","timestamp":"not_machine_verified",
  "details":"HNMS führt Europa-Bodendruckkarten im Marinebereich. Kein geprüfter datierter Originalbildabruf; Wiederverwendung offen.",
  "terms_url":"https://www.emy.gr/en/marine"},
 "imgw":{"country":"Polen","url":"https://meteo.imgw.pl/",
  "map":"official_europe_analysis_fronts","rights":"chart_specific_clearance_required","timestamp":"viewer_selects_00_12_without_image_date",
  "details":"Offizielle Europakarten mit Isobaren/Fronten, Wahl 00 und 12 UTC. Eine bestimmte Karte darf erst bei bestätigter vollständiger Gültigkeit UND bildspezifisch geklärten Rechten ins Panel.",
  "terms_url":"https://danepubliczne.imgw.pl/regulations"},
 "imgw_synoptic_forecast":{"country":"Polen","url":"https://meteo.imgw.pl/cmm/?page_id=19032",
  "map":"synoptic_day_night_forecast","rights":"chart_specific_clearance_required","timestamp":"day_night_without_machine_utc",
  "details":"Bis zu sieben Prognosetage mit Tages-/Nachtkarten. Kein geprüftes exaktes Originalbild-UTC-Mapping oder öffentliches Nutzungsrecht für die Bildübernahme.",
  "terms_url":"https://danepubliczne.imgw.pl/regulations"},
 "imgw_synoptic_archive":{"country":"Polen","url":"https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/Biuletyn_PSHM/",
  "map":"historical_selected_analyses_in_monthly_pdf","rights":"chart_specific_clearance_required","timestamp":"individual_printed_validity_within_pdf",
  "details":"Amtliche Monats-PDFs 2009 bis August 2026 geprüft. Einzelne Karten haben ausdrücklich gedruckte UTC-Gültigkeit, aber die Bildübernahme erfordert eine gesonderte Rechteprüfung.",
  "terms_url":"https://danepubliczne.imgw.pl/regulations"},
 "meteolt_synoptic_archive":{"country":"Litauen","url":"https://www.meteo.lt/app/uploads/2025/06/2024-METU-SHMR-compressed-2.pdf",
  "map":"historical_analysis_pdf","rights":"not_verified","timestamp":"archive_validity_known",
  "details":"Amtlicher Sturm-/Wetterbericht mit teilweise aus DWD-Archiv übernommenen synoptischen Bildern. Kein eigener Live-Feed.",
  "terms_url":"https://www.meteo.lt/"},
 "meteofrance_navicap":{"country":"Frankreich","url":"https://services.meteofrance.com/marine-et-offshore/marine/navicap-meteo-marine",
  "map":"commercial_marine_pressure_fronts","rights":"permission_required","timestamp":"not_machine_verified",
  "details":"Amtliche Marine-/Offshore-Druck-/Frontenkarte als professionelles Produkt. Keine offene Bildschnittstelle oder Freigabe.",
  "terms_url":"https://services.meteofrance.com/marine-et-offshore/marine/navicap-meteo-marine"},
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
