(()=>{"use strict";
const ROOT="data/synoptic_charts/";
const $=id=>document.getElementById(id);
const slots=["panel0","panel1","panel2","panel3"];
const INITIAL=["dwd","aemet","noaa_opc","chmi"];
let catalog=null;
let europeSourceAudit=null;
let imoDiagnostic=null;
let europeanViewerProbe=null;
let rhmzProbe=null;
let cyprusProbe=null;
let automaticChoice=null;
const isoDE=s=>{const d=new Date(s);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat("de-DE",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",timeZone:"UTC",hourCycle:"h23"}).format(d)+" UTC":"–";};
const node=(tag,cls,txt)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined)n.textContent=txt;return n;};
const source=id=>sourceDirectory().find(s=>s.id===id);
const sourceList=()=>sourceDirectory();
const showRecord=x=>globalThis.SynopticPanelLogic?.visible(x,$("chartKind").value)===true;
const recordType=x=>globalThis.SynopticPanelLogic?.label?.[globalThis.SynopticPanelLogic.classify(x)]||"Originalkarte";
const cardsAt=(id,time)=>(catalog?.charts||[]).filter(x=>x.source_id===id&&x.valid_utc===time&&showRecord(x));
const CURATED_SOURCES=[{"id":"dwd","name":"DWD · Bodenanalyse","country":"Deutschland","url":"https://www.dwd.de/DWD/wetter/wv_spez/hobbymet/wetterkarten/bwk_bodendruck_na_ana.png","note":"Direkter Link zum aktuellen Bild; automatischer Abruf erfolgt separat über DWD Open Data."},{"id":"aemet","name":"AEMET · Frontenkarten","country":"Spanien","url":"https://www.aemet.es/es/eltiempo/prediccion/mapa_frentes","note":"Amtliche Boden- und Frontenkarten."},{"id":"chmi","name":"ČHMÚ · Synoptische Situation","country":"Tschechien","url":"https://www.chmi.cz/predpoved-pocasi/synopticka-situace","note":"Amtliche synoptische Analyse und Prognose."},{"id":"dhmz","name":"DHMZ · Frontenprognose","country":"Kroatien","url":"https://meteo.hr/prognoze_e.php?param=web_fronte_sutra12&section=prognoze_model","note":"Amtliche Europa-Frontenprognose; Bildabruf nur mit geprüftem Druckdatum."},{"id":"knmi","name":"KNMI · Analysen und Prognosen","country":"Niederlande","url":"https://www.knmi.nl/nederland-nu/weer/waarschuwingen-en-verwachtingen/weerkaarten","note":"Automatischer Original-GIF-Abruf mit datierten UTC-Terminen; Veröffentlichung nur nach erfolgreichem Datenlauf.","category":"auto"},{"id":"knmi_archiv","name":"KNMI · Wetterkartenarchiv","country":"Niederlande","url":"https://www.knmi.nl/nederland-nu/klimatologie/daggegevens/weerkaarten","category":"archive","note":"Historisches Wetterkartenarchiv ab 2003."},{"id":"kmi","name":"KMI · Frontenkarten","country":"Belgien","url":"https://www.meteo.be/de/wetter/vorhersage/frontenkarten","category":"viewer","note":"Offizielle Frontenprognosen, jedoch noch keine gesicherte automatisch abrufbare Einzelbildzeit."},{"id":"dmi","name":"DMI · Analyse und Prognose","country":"Dänemark","url":"https://www.dmi.dk/vejret/frontkort","category":"viewer","note":"Amtliche Analyse- und Prognosekarten; DMI erlaubt ohne schriftliche Freigabe keine Übernahme von Kartenbildern auf andere Websites.","type":"external"},{"id":"metie","name":"Met Éireann · Bodenanalyse","country":"Irland","url":"https://www.met.ie/latest-reports/surface-analysis","category":"viewer","note":"Bodendruck- und Frontenanalyse für den Nordatlantik. Nur Originalseite verlinkt; keine automatische Bildübernahme."},{"id":"metoffice","name":"Met Office · Surface Pressure","country":"Großbritannien","url":"https://weather.metoffice.gov.uk/maps-and-charts/surface-pressure","category":"viewer","note":"Offizieller Bodendruck- und Frontenkartenviewer; extern öffnen."},{"id":"meteofrance","name":"Météo-France · Isofronts","country":"Frankreich","url":"https://meteofrance.com/isofronts","category":"viewer","note":"Isofronts-Kartenansicht des französischen Wetterdienstes."},{"id":"meteociel","name":"Météociel · Frontenanalyse","country":"Frankreich","url":"https://www.meteociel.fr/fronts/index.php","category":"viewer","note":"Externe Kartenansicht eines Drittanbieters, mit Animation."},{"id":"hungaromet","name":"HungaroMet · Frontenkarte","country":"Ungarn","url":"https://www.met.hu/en/idojaras/aktualis_idojaras/front/","category":"viewer","note":"Offizieller Frontenviewer; Datierung des Einzelbilds und Verwendung für automatische Kopien nicht abgesichert."},{"id":"shmu","name":"SHMÚ · Bodenwetterkarte","country":"Slowakei","url":"https://www.shmu.sk/en/?page=980","category":"viewer","note":"Amtliche datierte Bodenanalyse. SHMÚ gestattet Kopien nicht pauschal außerhalb privater Nutzung – daher nur externe Originalansicht.","type":"external"},{"id":"ilmateenistus","name":"Ilmateenistus · Wetterkarte","country":"Estland","url":"https://www.ilmateenistus.ee/ilm/prognoosid/ilmakaart/?lang=en","category":"unverified","note":"Wetterkartenansicht; Isobaren und UTC-Gültigkeit noch nicht gesichert."},{"id":"fmi","name":"FMI · Europäische Wetterlage","country":"Finnland","url":"https://en.ilmatieteenlaitos.fi/weather-in-europe","category":"unverified","note":"Wetterlagen-Seite; konkretes Isobarenbild nicht bestätigt."},{"id":"meteoam","name":"MeteoAM · amtliche Fronten- und Bodenkarten","country":"Italien","url":"https://www.meteoam.it/it/meteo-citta/front","category":"viewer","note":"Amtlicher italienischer Fronten-Kartenviewer; JavaScript-abhängig. Konkrete Bildschnittstelle, Bildgültigkeit und Wiederverwendung nicht nachgewiesen. Zusätzlich liefert ItaliaMeteo offene modellbasierte Druckkarten."},{"id":"mgm","name":"MGM · Synoptikkarten","country":"Türkei","url":"https://hezarfen.mgm.gov.tr/HzUsr/SinHarita/Default.aspx","category":"unverified","note":"Synoptikkarten-Bereich, noch kein verifiziertes aktuelles Kartenbild."},{"id":"smhi","name":"SMHI · tägliche Bodenanalysen im Monatsarchiv","country":"Schweden","url":"https://www.smhi.se/klimat/klimatet-da-och-nu/manadens-vader-och-vatten-i-sverige","category":"archive","note":"Amtliche historische Bodenanalysen mit Fronten und Druckzentren: zwei Karten je Tag, 00 und 12 UTC, seit Januar 2026 in den Monatsrückblicken. Kein tagesaktueller Live-Feed."},{"id":"imo","name":"IMO · Atlantik-Isobaren (ECMWF)","country":"Island","url":"https://en.vedur.is/weather/shipping/atlantic/","category":"unverified","note":"Nordatlantische ECMWF-Isobaren- und Windprognosen ohne eingezeichnete Fronten. Ein automatisches Panelbild erscheint ausschließlich, wenn Originaldatei und beide aufgedruckten Zeitangaben unabhängig übereinstimmen."},{"id":"metno","name":"MET Norway · Wetter und Klima","country":"Norwegen","url":"https://www.met.no/en/weather-and-climate","category":"unverified","note":"Allgemeine Wetterseite; kein bestätigter Isobaren-Direktlink."},{"id":"imgw","name":"IMGW-PIB · aktuelle Europa-Bodenanalysen","country":"Polen","url":"https://meteo.imgw.pl/","category":"viewer","note":"IMGW zeigt originale synoptische Europakarten mit Fronten und Isobaren für 00 und 12 UTC. Datum/Uhrzeit werden beim Wetterdienst gewählt; keine automatische Bildübernahme oder Gleichzeitigkeit im Vierer-Panel nachgewiesen.","type":"external"},{"id":"geosphere","name":"GeoSphere Austria · Frontenkarte in Überarbeitung","country":"Österreich","url":"https://geosphere.at/de/ueber-uns/faq","category":"unverified","note":"GeoSphere Austria erklärt ausdrücklich, dass die frühere ZAMG-Frontenwetterkarte derzeit überarbeitet wird und erst später in die Website zurückkehren soll. Kein aktueller freigegebener Direktbild-Abruf."},{"id":"ipma","name":"IPMA · Numerische Karten","country":"Portugal","url":"https://www.ipma.pt/pt/otempo/prev.numerica/index.jsp","category":"unverified","note":"Numerische Wetterkarten; Fronten-/Isobareninhalt nicht sicher bestätigt."},{"id":"ipma_history","name":"IPMA · Historische Bodenanalyse","country":"Portugal","url":"https://observar.ipma.pt/superficie-frontal-fria/","category":"archive","note":"Historische Karte aus einer Fallstudie, nicht die aktuelle Wetterlage."},{"id":"nimh_history","name":"NIMH · Europa-/Balkananalysen dokumentiert","country":"Bulgarien","url":"https://www.weather.bg/1en/index.php?koiFail=zaNas&lng=0","category":"unverified","note":"Bulgarisches NIMH dokumentiert operationelle synoptische Europakarten mit analysierten Fronten auf Basis 3-stündlicher SYNOP-Beobachtungen. Öffentliche aktuelle Bildschnittstelle und volles UTC-Datum nicht gefunden: offizieller Quellennachweis, keine Live-Karte."},{"id":"anm_history","name":"ANM · Historische Analyse","country":"Rumänien","url":"https://www.meteoromania.ro/wp-content/uploads/comunicate/30_NOIEMBRIE_ANALIZ%C4%82%20SINOPTIC%C4%82%20%C8%98I%20IMPACT%20METEOROLOGIC%20AL%20CICLONULUI%20MEDITERANEAN%20ADEL%20%C3%8EN%20PERIOADA%2026-30%20NOIEMBRIE%202025.pdf","category":"archive","note":"Fallbericht mit Bodenkarte vom 29.11.2025; keine aktuelle Analyse."},{"id":"noaa_wpc","name":"NOAA WPC · Bodenwetterkarten","country":"USA","url":"https://www.weather.gov/forecastmaps","category":"viewer","note":"Nordamerika-Analyse und Prognosen."},{"id":"noaa_pacific","name":"NOAA OPC · Pazifik","country":"USA","url":"https://ocean.weather.gov/Pac_tab.php","category":"viewer","note":"Pazifische Bodenanalysen und Prognosen."},{"id":"eccc","name":"ECCC · Nordhemisphäre","country":"Kanada","url":"https://weather.gc.ca/analysis/index_e.html","category":"unverified","note":"Nordhemisphären-Kartenbereich; Zeitstempel für Bildabruf offen."},{"id":"meteoswiss","name":"MeteoSchweiz · Allgemeine Lage","country":"Schweiz","url":"https://www.meteoschweiz.admin.ch/service-und-publikationen/applikationen/allgemeine-lage.html","type":"external","category":"viewer","note":"Fronten- und Großwetterlagenkarte in der Allgemeinen Lage; UTC-Termin und Übernahmerechte noch nicht verifiziert."},{"id":"metie_forecast","name":"Met Éireann · Atlantik-Druckprognosen","country":"Irland","url":"https://www.met.ie/forecasts/atlantic-charts/precipitation-pressure","type":"external","category":"viewer","note":"Offizieller Atlantik-Kartenviewer mit Druck- und Niederschlagsprognosen; nur direkt verlinkt, ohne Bildkopie."},{"id":"hnms","name":"HNMS · Europa-Bodendruckkarte","country":"Griechenland","url":"https://www.emy.gr/en/marine","category":"viewer","type":"external","note":"Amtlicher griechischer Marinebereich mit dem Menüpunkt „Surface pressure Europe“. Einzelbild-URL, UTC-Gültigkeit und Bildrechte sind für die automatische Übernahme noch nicht verifiziert."},{"id":"imgw_synoptic_forecast","name":"IMGW-PIB · synoptische Tages-/Nachtprognosen","country":"Polen","url":"https://meteo.imgw.pl/cmm/?page_id=19032","category":"viewer","type":"external","note":"Amtliche synoptische Tages-/Nachtprognosen über bis zu sieben Prognosetage. Tages- und Nachtwahl ist kein verifiziertes numerisches UTC-Image-API. Bitte die gültige Zeit auf der Originalkarte prüfen."},{"id":"imgw_synoptic_archive","name":"IMGW-PIB · historisches Synoptik-Bulletinarchiv","country":"Polen","url":"https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/Biuletyn_PSHM/","category":"archive","type":"external","note":"Offizielles Verzeichnis monatlicher PSHM-Bulletins seit 2009, aktuell bis August 2026 nachgewiesen. Die Berichte enthalten ausgewählte datierte Europakarten mit Isobaren und Fronten, kein lückenloses Tageskartenarchiv."},{"id":"meteolt_synoptic_archive","name":"Meteo LT · Ereignisanalysen","country":"Litauen","url":"https://www.meteo.lt/app/uploads/2025/06/2024-METU-SHMR-compressed-2.pdf","category":"archive","type":"external","note":"Amtlicher meteorologischer Ereignisbericht mit datierten synoptischen Europakarten. Mindestens eine Karte ist ausdrücklich ein übernommener DWD-Archivkartenausschnitt – kein eigenständiger Live-Dienst."},{"id":"meteofrance_navicap","name":"Météo-France · Marine-Druck- und Frontenkarten","country":"Frankreich","url":"https://services.meteofrance.com/marine-et-offshore/marine/navicap-meteo-marine","category":"viewer","type":"external","note":"Amtliches Marineprodukt mit Europa-/Atlantik-Druck- und Frontenkarten als Dienstleistung. Kein frei freigegebenes Einzelkartenbild; nicht automatisch übernehmen."},{"id":"rhmz","name":"RHMZ · Synoptische Analysen Europa/Balkan","country":"Serbien","url":"https://hidmet.gov.rs/eng/osmotreni/analiza.php","category":"viewer","type":"external","note":"Amtliche europäische synoptische Karten für 00 und 12 UTC sowie Balkankarten für weitere Termine. Einzelbild-Datum und Wiederverwendung noch ungeprüft; ausschließlich Originalansicht."},{"id":"italiameteo_isobars","name":"ItaliaMeteo · ICON-2I-Bodendruck und Isobaren","country":"Italien","url":"https://meteohub.agenziaitaliameteo.it/app/maps/meteotiles","type":"external","category":"viewer","note":"Offizielle ICON-2I-Modellprognose für Italien und Nachbarregionen: Bodendruck als Isobaren oder Druckfeld. Modellläufe 00/12 UTC, Prognosen bis +72 h; keine gezeichneten Fronten. Modellkartenviewer, nicht eine unabhängige handanalysierte Frontenkarte."},{"id":"italiameteo_opendata","name":"ItaliaMeteo · ICON-2I-Druckfelder (Open Data)","country":"Italien","url":"https://dati.agenziaitaliameteo.it/dataset/previsioni-meteorologiche-modello-icon-2i","type":"external","category":"viewer","note":"Amtliches ICON-2I-Datenangebot für italienischen Modellbereich (2,2 km), u. a. Druckfelder; Datensatz unter CC BY. GRIB-Modelldaten sind keine fertigen Original-Frontenkarten."},{"id":"cyprus_dom_wrf","name":"DOM Zypern · Östliches Mittelmeer WRF-Bodendruck","country":"Zypern","url":"https://www.dom.org.cy/WRF4/00Z/01/SLP_W10m_T2m/index.html","type":"external","category":"viewer","note":"Amtlicher WRF-v4.1.3-Kartenviewer (8 km, östliches Mittelmeer) für 00Z- und 12Z-Läufe: Bodendruck, 10-m-Wind und 2-m-Temperatur, ohne Fronten. Bildfolgen enthalten kein vollständiges Datum im Dateinamen. Nur direkte Originalseiten; exakte Karten-UTC und Bildfreigabe werden separat geprüft. Keine amtliche Wettervorhersage."},{"id":"arso_synoptic_archive","name":"ARSO · datierte Europa-Frontenanalyse (Ereignisarchiv)","country":"Slowenien","url":"https://meteo.arso.gov.si/uploads/probase/www/climate/text/sl/weather_events/neurja-16sep2025.pdf","type":"external","category":"archive","note":"Amtlicher Bericht zum 16.09.2025 mit datierter synoptischer Europakarte einschließlich Fronten und Isobaren (Seite 3). Einzelner historischer Fall, kein aktueller oder lückenloser Kartenfeed."},{"id":"lvgmc_front_archive","name":"LVĢMC · datierte Europa-Frontenanalyse (Ereignisarchiv)","country":"Lettland","url":"https://klimats.meteo.lv/enciklopedija/ekstremi/lietavas_rezekne_2017/Nokrisni_Latgale_2017-08.pdf","type":"external","category":"archive","note":"Amtliche LVĢMC-Frontalanalyse mit Isobaren, Fronten und SYNOP-Daten vom 22.08.2017, 18 UTC (PDF Seite 3). Historischer Nachweis, nicht als Live-Quelle geeignet."},{"id":"albania_igeo","name":"IGEO · meteorologische Vorhersagen","country":"Albanien","url":"https://geo.edu.al/MonitoringForecast/Hydrologic_Meteorological_Forecast/","category":"unverified","type":"external","note":"Amtliches Institut mit Modell-/Wetterberichten. Keine überprüfte eigenständige aktuelle Isobaren-/Frontenbildserie."},{"id":"andorra_meteo","name":"Meteo Andorra · staatlicher Wetterdienst","country":"Andorra","url":"https://www.meteo.ad/en","category":"unverified","type":"external","note":"Offizielle Wetter- und Stationsdaten; keine eigenständige synoptische Europakarte nachgewiesen. Für regionale Isobaren AEMET/Météo-France nutzen."},{"id":"belarus_belhydromet","name":"Belhydromet · Synoptik","country":"Belarus","url":"https://pogoda.by/weather/synoptic/","category":"viewer","type":"external","note":"Offizieller Synoptikbereich; aktuelle Grafik-URL, vollständige UTC-Gültigkeit und Rechte noch ungeprüft."},{"id":"bosnia_fhmz_gfs","name":"FHMZ · GFS-Modellprognosen","country":"Bosnien und Herzegowina","url":"https://www.fhmzbih.gov.ba/latinica/METEO/GFSprognoza.php","category":"viewer","type":"external","note":"Offizielle GFS-Modellprognosen in 3-Stunden-Schritten. Isobarenparameter, Modelllaufdatum und Originalbildrechte noch einzeln zu verifizieren; kein unabhängiges Analyseprodukt."},{"id":"liechtenstein_swiss","name":"Landesverwaltung / MeteoSchweiz","country":"Liechtenstein","url":"https://www.meteoschweiz.admin.ch/service-und-publikationen/applikationen/allgemeine-lage.html","category":"unverified","type":"external","note":"Regionale Abdeckung durch MeteoSchweiz, bereits unter Schweiz vorhanden. Kein eigener liechtensteinischer Originalkartenherausgeber nachgewiesen."},{"id":"luxembourg_meteolux","name":"MeteoLux · TEMSI-Fronten-/Druckkarten","country":"Luxemburg","url":"https://www.meteolux.lu/fr/produits-et-services/produits-aeronautiques/cartes-du-temps-significatif/","category":"viewer","type":"external","note":"West-Europa-/Benelux-TEMSI-Karten mit Fronten und Druckzentren alle 3 Stunden; Registrierung nötig. Autoren Météo-France bzw. Skeyes, nicht unabhängiger Luxemburger Kartenherausgeber."},{"id":"malta_metoffice","name":"Malta Airport · Meteorological Office","country":"Malta","url":"https://www.maltairport.com/weather/","category":"unverified","type":"external","note":"Staatlich beauftragter Luftfahrt-Wetterdienst. Historische handgezeichnete Karten dokumentiert, kein offener aktueller Isobarenbildfeed belegt."},{"id":"moldova_shs","name":"SHS · Staatlicher Hydrometeorologischer Dienst","country":"Moldau","url":"https://www.meteo.md/","category":"unverified","type":"external","note":"Offizieller Wetterdienst; operationelle Synoptik ist dokumentiert, aber keine überprüfte öffentliche Karte mit vollständigem UTC-Datum."},{"id":"monaco_france","name":"Météo-France · regionale Abdeckung Monaco","country":"Monaco","url":"https://meteofrance.com/","category":"unverified","type":"external","note":"Regional zuständiges französisches Wetterangebot. Kein unabhängiger amtlicher Monaco-Isobarenkartenherausgeber gefunden; Météo-France bereits erfasst."},{"id":"montenegro_zhms","name":"ZHMS · WRF- und Wetterprognosen","country":"Montenegro","url":"https://www.meteo.co.me/","category":"viewer","type":"external","note":"Nationaler hydrometeorologischer Dienst mit WRF-Modellkarten; konkretes MSLP-/Isobarenprodukt und Bildgültigkeit noch nicht nachgewiesen."},{"id":"northmacedonia_uhmr","name":"UHMR · nationaler Wetterdienst","country":"Nordmazedonien","url":"https://uhmr.gov.mk/","category":"unverified","type":"external","note":"Amtlicher hydrometeorologischer Dienst; keine nachgewiesene Original-Bodenanalyse mit öffentlicher UTC-Bildschnittstelle."},{"id":"russia_hmc_analysis","name":"Hydrometcenter · Bodenanalysen 00/06/12/18 UTC","country":"Russland","url":"https://meteoinfo.ru/mapsynop","category":"viewer","type":"external","note":"Echte amtliche Bodenanalysen zu vier UTC-Terminen täglich. Einzelbildadresse, vollständiges Kartendatum, Rechte und Zugriff noch separat prüfen."},{"id":"russia_hmc_forecast","name":"Hydrometcenter · Bodenprognosekarten","country":"Russland","url":"https://meteoinfo.ru/prognosticheskie-karty","category":"viewer","type":"external","note":"Originale synoptische Bodenprognosen +24, +36, +60 h auf Basis 00 UTC. Bildverfügbarkeit und Copyright ungeprüft."},{"id":"sanmarino_italy","name":"Italienische Wetterkarten · San Marino regional","country":"San Marino","url":"https://www.meteoam.it/it/meteo-citta/front","category":"unverified","type":"external","note":"Regionale Abdeckung durch italienische Frontenkarten; kein eigener staatlicher Europa-Synoptik-Bilddienst belegt."},{"id":"ukraine_uhmc","name":"Ukrainischer Hydrometeorologischer Dienst","country":"Ukraine","url":"https://www.meteo.gov.ua/en/","category":"unverified","type":"external","note":"Amtliche Wetter- und Prognoseprodukte; kein überprüfter aktueller Originalbildfeed für europäische Isobaren/Fronten."},{"id":"vatican_italy","name":"Italienische Wetterkarten · Vatikan regional","country":"Vatikanstadt","url":"https://www.meteoam.it/it/meteo-citta/front","category":"unverified","type":"external","note":"Rom-/Vatikanregion durch italienische Frontenkarten abgedeckt. Keine eigenständige amtliche Vatikan-Synoptikkarte bekannt."},{"id":"kosovo_ihmk","name":"IHMK · Hydrometeorologisches Institut","country":"Kosovo","url":"https://ihmk-rks.net/","category":"unverified","type":"external","note":"Offizieller meteorologischer Dienst mit Stations- und Wetterdaten; keine nachgewiesene Europa-Isobarenkarte."},{"id":"armenia_hmc","name":"Hydrometeorology and Monitoring Center","country":"Armenien","url":"https://meteomonitoring.am/en/web","category":"unverified","type":"external","note":"Staatlicher Hydrometeorologiedienst; operationelle Wetter- und Modellprodukte, aktueller Original-Isobarenfeed nicht verifiziert."},{"id":"armenia_archive","name":"HMC · historische Bodenanalysen (Jahresbericht)","country":"Armenien","url":"https://meteomonitoring.am/file/globalFiles/annual-2024.pdf","category":"archive","type":"external","note":"Historischer amtlicher Jahresbericht mit synoptischen Wetterkarten. Einzelne Karten nicht als aktuelle Live-Quelle ausgeben."},{"id":"azerbaijan_nhms","name":"Nationaler Hydrometeorologischer Dienst","country":"Aserbaidschan","url":"https://meteo.az/","category":"unverified","type":"external","note":"Amtlicher Dienst und meteorologische Karten; kein unabhängig datiertes Isobaren-/Frontenbild identifiziert."},{"id":"georgia_nea","name":"NEA · Hydrometeorologie","country":"Georgien","url":"https://nea.gov.ge/En/Departments/Hydrometeorology","category":"unverified","type":"external","note":"Nationale Wetter- und SYNOP-Produkte beschrieben; eigene aktuelle öffentliche Fronten-/Bodenanalysebilder ungeprüft."},{"id":"kazakhstan_synoptic","name":"Kazhydromet · synoptische Originalkarten","country":"Kasachstan","url":"https://www.kazhydromet.kz/en/weather/sinopticheskie-karty-pogody","category":"viewer","type":"external","note":"Amtlicher Synoptikkartenviewer mit Datums-, UTC-Zeit- und Quelldateiauswahl. Vollständige Bild-UTC, API und Kartenrechte noch maschinell zu verifizieren."}];
const collator=new Intl.Collator("de",{sensitivity:"base"});
const AUTO_FALLBACK=new Set(["dwd","aemet","chmi","dhmz","knmi"]);
function sourceDirectory(){
 const merged=new Map();
 for(const s of CURATED_SOURCES)merged.set(s.id,{...s});
 for(const s of catalog?.sources||[]){
  const curated=merged.get(s.id);
  merged.set(s.id,{...s,...curated,
   type:s.type,
   url:curated?.url||s.url,
   note:curated?.note||(s.type==="auto"?"Offizielle Originalkarten mit UTC-Gültigkeitszeit.":s.license||"Offizieller Kartenbereich."),
   category:s.type==="auto"?"auto":(curated?.category||"viewer")});
 }
 for(const policy of europeSourceAudit?.providers||[]){
  const existing=merged.get(policy.id);
  if(existing){
   const reason=policy.details||"";
   merged.set(policy.id,{...existing,source_policy:policy,
     note:reason||existing.note});
  }
 }
 if(imoDiagnostic&&merged.has("imo")){
  const provider=merged.get("imo");
  const total=imoDiagnostic.forecast_filename_candidates?.length||0;
  const published=(catalog?.charts||[]).filter(x=>x.source_id==="imo").length;
  const since=imoDiagnostic.checked_utc?isoDE(imoDiagnostic.checked_utc):"–";
  const state=published?
    published+" Modellprognose(n) mit bestätigtem UTC-Gültigkeitstermin eingebunden":
    imoDiagnostic.state==="source_unreachable"?
    "Quellenseiten beim letzten Abruf nicht erreichbar":
    "Bilder werden erst nach OCR-Prüfung beider aufgedruckter Zeitangaben übernommen";
  merged.set("imo",{...provider,
   note:"IMO Atlantik · ECMWF-basierte Isobarenprognosen ohne Fronten. Letzter technischer Abruf: "+
    since+" · "+total+" Prognose-Dateinamen gefunden · "+state+
    ". Keine geschätzten Laufzeiten im Vierer-Panel."});
 }
 for(const probe of europeanViewerProbe?.sources||[]){
  const existing=merged.get(probe.id);
  if(existing&&probe.ready_for_automatic_charts===false)
   merged.set(probe.id,{...existing,viewer_probe:probe});
 }
 if(merged.has("cyprus_dom_wrf")&&cyprusProbe?.reports){
  const old=merged.get("cyprus_dom_wrf");
  merged.set("cyprus_dom_wrf",{...old,cyprus_probe:cyprusProbe});
 }
 if(merged.has("rhmz")&&rhmzProbe?.records){
  const previous=merged.get("rhmz");
  merged.set("rhmz",{...previous,rhmz_probe:rhmzProbe,
    note:"Amtliche synoptische Bodenanalysen mit Isobaren, Fronten und Stationsdaten. Europa 00/12 UTC sowie Balkan 06/09/12/15 UTC. Bilddateien werden nicht kopiert; alte Karten werden am aufgedruckten Datum erkannt."});
 }
 for(const id of AUTO_FALLBACK){
  const s=merged.get(id);
  if(s&&!s.category)s.category= (catalog?.sources||[]).some(x=>x.id===id&&x.type==="auto")?"auto":"unverified";
 }
 return [...merged.values()].sort((a,b)=>{
  const region=c=>["USA","Kanada"].includes(c)?1:0;
  return region(a.country)-region(b.country)||collator.compare(a.country||"",b.country||"")||collator.compare(a.name||"",b.name||"");
 });
}
function renderDataHealth(){
 const el=$("dataHealth");
 if(!catalog){el.className="health-summary error";el.textContent="Kartenindex nicht erreichbar: Die Quellenlinks sind weiterhin nutzbar, aber keine Aktualität des Kartenbestands kann bestätigt werden.";return;}
 const stamp=Date.parse(catalog.generated_utc),hours=(Date.now()-stamp)/3600000;
 const invalid=!Number.isFinite(stamp)||hours< -1;
 const stale=invalid||hours>30;
 const aging=hours>12;
 const bad=Object.entries(catalog.source_status||{}).filter(([,st])=>st.state!=="available");
 const good=Object.values(catalog.source_status||{}).filter(st=>st.state==="available").length;
 el.className="health-summary"+(stale?" error":aging||bad.length?" warn":"");
 const state=invalid?"Ungültiges Ausgabedatum":stale?"Veralteter Datenlauf":aging?"Datenlauf verspätet":"Datenlauf aktuell";
 const problems=bad.length?" · ohne gültige Karte: "+bad.map(([id,st])=>id+" ("+(st.reason||"keine geprüfte Quelle").slice(0,65)+")").join(", "):"";
 el.textContent=state+" · letzter Index: "+isoDE(catalog.generated_utc)+" · "+catalog.chart_count+" geprüfte Bilder · "+good+" von "+Object.keys(catalog.source_status||{}).length+" automatisch geprüften Produkten verfügbar"+problems+".";
}
function fillSources(){
 const container=$("sourceCatalog"),q=($("sourceSearch")?.value||"").trim().toLocaleLowerCase("de"),
  filter=$("sourceFilter")?.value||"all";
 const list=sourceDirectory().filter(s=>{
  const category=s.category||(s.type==="auto"?"auto":"viewer");
  const matches=filter==="all"|| (filter==="other"&&["archive","unverified"].includes(category))||category===filter;
  return matches&&(!q||[s.name,s.country,s.note].join(" ").toLocaleLowerCase("de").includes(q));
 });
 container.replaceChildren();
 $("sourceSummary").textContent=list.length+" von "+sourceDirectory().length+" Quellen angezeigt · Europa alphabetisch, weitere Regionen am Ende.";
 if(!list.length){container.append(node("p","help","Keine Quellen zur Auswahl gefunden."));return;}
 for(const s of list){
  const category=s.category||(s.type==="auto"?"auto":"viewer"),
   n=(catalog?.charts||[]).filter(x=>x.source_id===s.id).length,
   title=node("strong","",s.name+" · "+s.country),
   article=node("article","source"),
   tag=node("span","source-tag "+category,category==="auto"?(n?n+" Karten eingebunden":"Automatischer Abruf · keine Karte"):category==="viewer"?"Kartenansicht":category==="archive"?"Archiv / historisch":"Nicht als Live-Karte bestätigt");
  const state=catalog?.source_status?.[s.id];
  const statusDetail=category==="auto"&&state?.state==="unavailable"?
   " Aktueller Abruf fehlgeschlagen: "+(state.reason||"keine gültige Originalkarte").slice(0,160):"";
  article.append(title,tag);
  const p=s.source_policy;
  if(p){
   const tagLabel=p.rights==="permission_required"?"Bildübernahme nur mit Erlaubnis":
    p.rights==="original_unmodified_only"?"Archiv · Original unverändert":
    p.rights==="reuse_with_attribution"?"Nutzung mit Quellenangabe":
    p.rights==="map_not_covered_by_ogd"?"OGD gilt nicht pauschal für Karten":
    p.rights==="chart_specific_clearance_required"?"Bildfreigabe noch offen":"Originalbild nicht freigegeben";
   const policyBadge=node("span","source-rights",tagLabel);
   article.append(policyBadge);
  }
  article.append(node("p","",(s.note||s.license||"")+statusDetail));
  if(s.viewer_probe){
   const status=s.viewer_probe.state==="html_inspected"?
    "Offizielle Quellenseite technisch erreichbar; Kartenbild/UTC noch nicht freigegeben":
    "Quellenseite beim letzten Prüflauf nicht erfolgreich analysiert";
   const tick=s.viewer_probe.checked_utc?" · geprüft "+isoDE(s.viewer_probe.checked_utc):"";
   article.append(node("span","source-inspection",status+tick));
  }
  const a=node("a","",category==="archive"?"Archiv / Bericht öffnen":category==="unverified"?"Quelle prüfen":"Karten öffnen");
  a.href=s.url;a.target="_blank";a.rel="noopener noreferrer";article.append(a);
  if(s.id==="rhmz"){
   const links=[
    {product:"europe00",label:"Europa-Analyse · 00 UTC",url:"https://www.hidmet.gov.rs/data/analiza/EVROPA/evropa00_JPG.jpg"},
    {product:"europe12",label:"Europa-Analyse · 12 UTC",url:"https://www.hidmet.gov.rs/data/analiza/EVROPA/evropa12_JPG.jpg"},
    {product:"balkan06",label:"Balkan-Analyse · 06 UTC",url:"https://www.hidmet.gov.rs/data/analiza/BALKAN/balkan06_JPG.jpg"},
    {product:"balkan09",label:"Balkan-Analyse · 09 UTC",url:"https://www.hidmet.gov.rs/data/analiza/BALKAN/balkan09_JPG.jpg"},
    {product:"balkan12",label:"Balkan-Analyse · 12 UTC",url:"https://www.hidmet.gov.rs/data/analiza/BALKAN/balkan12_JPG.jpg"},
    {product:"balkan15",label:"Balkan-Analyse · 15 UTC",url:"https://www.hidmet.gov.rs/data/analiza/BALKAN/balkan15_JPG.jpg"}
   ];
   const group=node("div","official-deep-links");
   for(const item of links){
    const probe=s.rhmz_probe?.records?.find(r=>r.product===item.product&&r.image_url===item.url);
    const match=probe?.state==="printed_utc_verified"&&probe.valid_utc;
    const stale=probe?.state==="unverified"&&/stale|future-dated|outdated/i.test(probe.reason||"");
    const label=item.label+(match?" · "+isoDE(probe.valid_utc):stale?" · Bild ist veraltet":" · Bilddatum noch nicht bestätigt");
    const link=node("a","",label+" ↗");
    link.href=item.url;link.target="_blank";link.rel="noopener noreferrer";
    group.append(link);
   }
   article.append(group);
   if(s.rhmz_probe?.generated_utc)article.append(node("span","source-inspection",
     "RHMZ-Kartenprüfung vom "+isoDE(s.rhmz_probe.generated_utc)+"; amtliche Bilder werden nicht auf dieser Website gespeichert."));
  }
  if(s.id==="cyprus_dom_wrf"){
   const group=node("div","official-deep-links");
   const pages=[
    {run:"00",name:"WRF 00 UTC · Originalkarten",page:"https://www.dom.org.cy/WRF4/00Z/01/SLP_W10m_T2m/index.html"},
    {run:"12",name:"WRF 12 UTC · Originalkarten",page:"https://www.dom.org.cy/WRF4/12Z/01/SLP_W10m_T2m/index.html"}
   ];
   for(const model of pages){
    const report=s.cyprus_probe?.reports?.find(x=>x.run_hour_utc===model.run&&x.page===model.page);
    const link=node("a","",model.name+" ↗");
    link.href=model.page;link.target="_blank";link.rel="noopener noreferrer";
    group.append(link);
    if(report){
     const verified=report.sample_maps?.filter(x=>
       ["printed_valid_utc_verified","printed_init_and_valid_utc_verified"].includes(x.state))||[];
     const verifiedCadence=report.sampled_cadence==="two_printed_frames_confirm_three_hour_intervals";
     const status=report.state==="unreachable"?"Quelle beim letzten Lauf nicht erreichbar":
       report.frame_count+" Original-GIFs gefunden · "+
       (verified.length?verified.length+" Bild-Uhrzeit(en) bestätigt"+
         (verifiedCadence?" · 3-h-Schritte in Stichprobe bestätigt":""):
        "exakte UTC-Gültigkeit noch nicht nachgewiesen");
     group.append(node("span","source-inspection",status));
     if(report.printed_run_anchor_utc&&verifiedCadence)
      group.append(node("span","source-inspection",
       "Datum des geprüften Modellstarts: "+isoDE(report.printed_run_anchor_utc)+
       " (nur verifizierte Stichproben, nicht automatisch alle 41 Bilder)."));
    }
   }
   article.append(group);
   if(s.cyprus_probe?.generated_utc)
    article.append(node("span","source-inspection",
     "Prüfung vom "+isoDE(s.cyprus_probe.generated_utc)+". Keine Kopie der Kartenbilder; Bildfreigabe noch offen."));
  }
  if(s.id==="imgw"){
   article.append(node("span","source-inspection",
    "Amtliche Auswahl: Europa-Bodenanalyse · 00 UTC / 12 UTC. Vollständige Datumsangabe auf der Karte prüfen."));
  }
  if(s.id==="imgw_synoptic_forecast"){
   article.append(node("span","source-inspection",
    "Amtliche Tages-/Nachtkarten bis Tag 7; Prognosezeit nicht als feste UTC-Stunde annehmen."));
  }
  if(s.id==="imgw_synoptic_archive"){
   const archive=node("div","official-deep-links");
   const latest=node("a","","Letzter nachgewiesener Monatsbericht · August 2026 ↗");
   latest.href="https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/Biuletyn_PSHM/Biuletyn_PSHM_2026_08_%28sierpien%29.pdf";
   latest.target="_blank";latest.rel="noopener noreferrer";
   archive.append(latest);
   article.append(archive);
  }
  const imgwTerms=["imgw","imgw_synoptic_forecast","imgw_synoptic_archive"].includes(s.id)?
   "https://danepubliczne.imgw.pl/regulations":null;
  const termsUrl=s.source_policy?.terms_url||imgwTerms;
  if(termsUrl){
   const terms=node("a","source-policy-link","Nutzungsbedingungen ↗");
   terms.href=termsUrl;terms.target="_blank";terms.rel="noopener noreferrer";
   article.append(terms);
  }
  container.append(article);
 }
}
const PANEL_PREF=["dwd","aemet","knmi","chmi","dhmz","noaa_opc","noaa_full","noaa_west","noaa_24","noaa_48","noaa_96"];
function optionValue(select,id){return [...select.options].some(o=>o.value===id);}
function panelAutomatic(){return $("fourPolicy").value==="auto";}
function availableTimes(){
 return (catalog?.time_slots||[]).filter(t=>(catalog?.charts||[]).some(r=>r.valid_utc===t&&showRecord(r)));
}
function rebuildTimes(prefer,preserve=true){
 const picker=$("validTime"),previous=picker.value;
 const times=availableTimes();
 picker.replaceChildren();
 if(!times.length){picker.add(new Option("Keine geprüften Termine",""));return;}
 for(const time of times.slice().reverse()){
  const records=catalog.charts.filter(r=>r.valid_utc===time&&showRecord(r));
  const count=new Set(records.map(r=>r.publisher_id||r.source_id)).size;
  picker.add(new Option(isoDE(time)+" · "+records.length+" Bilder / "+count+" Dienste",time));
 }
 if(preserve&&times.includes(previous)){picker.value=previous;return;}
 const now=Date.now(),recent=times.slice().sort((a,b)=>{
  const fav=t=>prefer&&catalog.charts.some(r=>r.source_id===prefer&&r.valid_utc===t&&showRecord(r))?1:0;
  return fav(b)-fav(a)||Math.abs(Date.parse(a)-now)-Math.abs(Date.parse(b)-now);
 });
 picker.value=recent[0];
}
function nearestTimeFor(ids){
 const times=availableTimes(),now=Date.now();
 if(!times.length)return;
 const chosen=times.slice().sort((a,b)=>{
  const hits=t=>ids.filter(id=>cardsAt(id,t).length>0).length;
  return hits(b)-hits(a)||Math.abs(Date.parse(a)-now)-Math.abs(Date.parse(b)-now);
 })[0];
 if(chosen)$("validTime").value=chosen;
}
function fillPickers(){
 const single=$("singleSource"),oldSingle=single.value,
  previous=slots.map(id=>$(id).value);
 const sources=sourceList();
 single.replaceChildren();
 for(const s of sources)single.add(new Option(s.name+" · "+s.country,s.id));
 single.value=optionValue(single,oldSingle)?oldSingle:"dwd";
 for(let i=0;i<slots.length;i++){
  const select=$(slots[i]);
  select.replaceChildren();
  for(const s of sources)select.add(new Option(s.name+" · "+s.country,s.id));
  const backup=PANEL_PREF[i];
  select.value=optionValue(select,previous[i])?previous[i]:backup;
 }
 rebuildTimes(single.value);
 if($("chartMode").value==="four"&&panelAutomatic())autoBestPanels();
}
function panelSettings(){return {uniquePublishers:$("uniquePublishers").checked};}
function panelChoiceAt(time){
 const logic=globalThis.SynopticPanelLogic;
 if(!logic)throw new Error("Das Kartenvergleich-Modul konnte nicht geladen werden");
 return logic.chooseAt(catalog?.charts||[],time,$("chartKind").value,panelSettings());
}
function setSelectedPanels(choice){
 automaticChoice=choice||null;
 const matched=choice?.ids||[];
 matched.forEach((id,i)=>{if(slots[i]&&optionValue($(slots[i]),id))$(slots[i]).value=id;});
 $("autoChoiceHint").textContent=choice?.count?
  choice.count+" zeitgleiche Originalbilder für "+isoDE(choice.time)+" · "+
  choice.publishers+" unabhängige Dienste. Nur verfügbare Bilder werden dargestellt.":
  "Für den gewählten Filter ist keine zeitgleiche Originalkarte vorhanden.";
}
function autoAtCurrentTime(){
 if(!catalog)return;
 setSelectedPanels(panelChoiceAt($("validTime").value));
}
function autoBestPanels(){
 if(!catalog)return;
 const logic=globalThis.SynopticPanelLogic;
 if(!logic)throw new Error("Das Kartenvergleich-Modul konnte nicht geladen werden");
 const choice=logic.best(catalog.charts,availableTimes(),$("chartKind").value,Date.now(),panelSettings());
 if(choice)$("validTime").value=choice.time;
 setSelectedPanels(choice);
}
function updatePanelControls(){
 const isFour=$("chartMode").value==="four";
 $("fourOptions").hidden=!isFour;
 $("fourSelectors").hidden=!isFour||panelAutomatic();
 $("singleSourceWrap").hidden=isFour;
 slots.forEach(id=>$(id).disabled=isFour&&panelAutomatic());
 $("optimizePanels").disabled=!catalog;
 if(!panelAutomatic()&&isFour)
  $("autoChoiceHint").textContent="Manueller Vergleich: Karten und UTC-Termin bleiben ausgewählt. Nicht verfügbare Bilder und doppelte Dienste (falls aktiviert) werden ausgeblendet.";
}
function currentProviders(){
 return $("chartMode").value==="four"?
   (panelAutomatic()?automaticChoice?.ids||[]:slots.map(id=>$(id).value)):
   [$("singleSource").value];
}
function visibleSelection(){
 const selected=currentProviders(),seen=new Set();
 const shown=[];let unavailable=0,duplicate=0;
 const time=$("validTime").value;
 const four=$("chartMode").value==="four";
 for(const id of selected){
  const match=cardsAt(id,time)[0];
  const pub=match?.publisher_id||match?.source_id||id;
  if(four&&$("uniquePublishers").checked&&seen.has(pub)){duplicate++;continue;}
  // External original links remain usable; unavailable auto-image tiles do not.
  const external=source(id)?.type!=="auto";
  if(!match&&four&&!external){unavailable++;continue;}
  shown.push(id);
  if(match||external)seen.add(pub);
 }
 return {selected,shown,unavailable,duplicate};
}
function card(provider,time){
 const s=source(provider);
 const record=cardsAt(provider,time)[0];
 const article=node("article","chart");
 const heading=node("div","chart-header");
 heading.append(node("strong","",s?s.name:"Unbekannte Quelle"));
 heading.append(node("small","",record?(record.kind+(record.forecast_hours?" +"+record.forecast_hours+" h":""))+" · "+isoDE(record.valid_utc):(s?.type!=="auto"?"Externe Kartenansicht · nicht synchronisiert":"Für diesen Termin nicht vorhanden")));
 if(record)heading.append(node("span","chart-category",recordType(record)));
 article.append(heading);
 const content=node("div","chart-body");
 if(record){
  const img=node("img");
  img.src=ROOT+record.image;
  img.alt=s.name+" Originalkarte · "+record.kind+" · gültig "+isoDE(record.valid_utc);
  img.loading="lazy";
  img.onerror=()=>{
   const unavailable=node("div","empty");
   unavailable.append(node("strong","","Originalbild nicht erreichbar"));
   unavailable.append(node("span","","Die Kartendatei aus dem veröffentlichten Index konnte nicht geladen werden. Kein Ersatzbild und keine abweichende UTC-Zeit."));
   const link=node("a","source-panel-link","Originalquelle prüfen ↗");
   link.href=record.source_page||s.url;link.target="_blank";link.rel="noopener noreferrer";
   unavailable.append(link);content.replaceChildren(unavailable);
  };
  content.append(img);
 }else{
  const empty=node("div","empty");
  const external=s&&s.type!=="auto";
  empty.append(node("strong","",external?"Originalkarte beim Wetterdienst öffnen":"Kein zeitgleiches Kartenbild"));
  empty.append(node("span","",external?"Für diese Quelle liegt kein freigegebenes, zeitgestempeltes Kartenbild zur Wiedergabe vor. Sie gehört deshalb nicht zum UTC-synchronen Bildvergleich.":"Für genau diesen UTC-Termin wurde keine überprüfbare Originalkarte publiziert."));
  if(external&&/^https:\/\//.test(s.url)){
   const link=node("a","source-panel-link","Originalkarten direkt öffnen ↗");
   link.href=s.url;link.target="_blank";link.rel="noopener noreferrer";
   empty.append(link);
  }
  content.append(empty);
 }
 article.append(content);
 const footer=node("div","chart-footer");
 footer.append(node("span","",record?record.credit:(s?.type!=="auto"?"Originalquelle · keine Bildübernahme":"Keine Karte für "+isoDE(time))));
 if(s){
  if(record?.terms_url){
   const terms=node("a","","Nutzungsbedingungen");
   terms.href=record.terms_url;terms.target="_blank";terms.rel="noopener noreferrer";footer.append(terms);
  }
  if(record?.license_url){
   const license=node("a","","CC BY 4.0");
   license.href=record.license_url;license.target="_blank";license.rel="noopener noreferrer";footer.append(license);
  }
  const link=node("a","",record?"Originalquelle":"Beim Wetterdienst ansehen");
  link.href=record?.source_page||s.url;
  link.target="_blank";link.rel="noopener noreferrer";footer.append(link);
 }
 article.append(footer);
 return article;
}
function refreshView(){
 const isFour=$("chartMode").value==="four";
 updatePanelControls();
 const grid=$("chartGrid");
 grid.classList.toggle("four",isFour);
 grid.replaceChildren();
 const validity=$("validTime").value;
 if(!catalog||!validity){
  grid.classList.toggle("compact-one",false);
  grid.classList.toggle("compact-three",false);
  grid.append(node("div","empty",!catalog?"Kartenindex nicht erreichbar – unten bleiben die Originalquellen verfügbar.":"Für diesen Karteninhalt liegen keine überprüften UTC-Termine vor."));
  $("exportPng").disabled=true;
  return;
 }
 const selection=visibleSelection();
 const ids=selection.shown;
 const matched=ids.filter(id=>cardsAt(id,validity).length>0).length;
 grid.classList.toggle("compact-one",isFour&&ids.length===1);
 grid.classList.toggle("compact-three",isFour&&ids.length===3);
 for(const id of ids)grid.append(card(id,validity));
 if(!ids.length){
  const msg=node("div","empty");
  msg.append(node("strong","","Keine zeitgleichen Originalkarten für die Auswahl"));
  msg.append(node("span","","Den UTC-Termin, den Karteninhalt oder die unabhängigen Wetterdienste ändern. Keine Ersatzkarten aus anderen Laufzeiten."));
  grid.append(msg);
 }
 $("exportPng").disabled=matched===0;
 const publishers=new Set(ids.flatMap(id=>cardsAt(id,validity).map(x=>x.publisher_id||x.source_id)));
 const external=ids.filter(id=>source(id)?.type!=="auto").length;
 const older=Date.now()-Date.parse(catalog.generated_utc)>12*3600000;
 const hidden=selection.unavailable+selection.duplicate;
 $("chartStatus").textContent=isoDE(validity)+" · "+matched+(matched===1?" Originalbild":" Originalbilder")+
  (isFour?" in "+ids.length+(ids.length===1?" sichtbarer Kachel":" sichtbaren Kacheln"):"")+
  " · "+publishers.size+(publishers.size===1?" unabhängiger Dienst":" unabhängige Dienste")+
  (external?" · "+external+" externe Verweise":"")+
  (hidden?" · "+hidden+" nicht passende/doppelte Kacheln ausgeblendet":"")+
  (older?" · Achtung: Index älter als 12 Stunden":"");
 $("syncHint").textContent=isFour?
  (matched?
   "Alle angezeigten Originalbilder haben exakt denselben UTC-Gültigkeitstermin. "+
   (ids.length<4?"Der Vergleich zeigt nur "+ids.length+(ids.length===1?" belegte Kachel":" belegte Kacheln")+", keine leeren Platzhalter. ":"")+
   ($("uniquePublishers").checked?"Jeder Wetterdienst zählt höchstens einmal.":"Mehrere Produkte desselben Wetterdienstes sind erlaubt.")+
   (external?" Externe Kartenlinks sind nicht Teil des zeitgleichen Bildvergleichs.":""):
   "Für diesen Kartentyp und Zeitpunkt sind keine eingebundenen Originalbilder verfügbar. Externe Links sind keine synchronisierten Karten."):
  (matched?"Originalkarte des gewählten Wetterdienstes für den ausgewiesenen UTC-Termin.":"Für diese Quelle zum gewählten Zeitpunkt kein freigegebenes Originalbild vorhanden.");
}
async function pngExport(){
 const validity=$("validTime").value;
 // Export precisely the images shown on screen, never empty/export-only panels.
 const ids=visibleSelection().shown.filter(id=>cardsAt(id,validity).length>0);
 if(!ids.length)return;
 const four=$("chartMode").value==="four";
 const cols=four&&ids.length>1?2:1,rows=Math.ceil(ids.length/cols);
 const W=cols===2?1640:1180,H=rows===2?1320:1010;
 const canvas=document.createElement("canvas");canvas.width=W;canvas.height=H;
 const ctx=canvas.getContext("2d");if(!ctx)return;
 ctx.fillStyle="#fff";ctx.fillRect(0,0,W,H);
 ctx.fillStyle="#172e46";ctx.font="bold 32px Arial";
 ctx.fillText("Isobaren & Fronten · Originalkarten",35,55);
 ctx.fillStyle="#455f79";ctx.font="19px Arial";
 ctx.fillText("Gültig: "+isoDE(validity)+" · alle Karten exakt UTC-synchron",35,87);
 const pad=24,top=118,footer=92;
 const baseW=(W-pad*(cols+1))/cols,cellH=(H-top-footer-pad*(rows-1))/rows;
 let loaded=0;
 for(let i=0;i<ids.length;i++){
  const spread=cols===2&&ids.length===3&&i===2;
  const cellW=spread?W-pad*2:baseW;
  const x=spread?pad:pad+(i%cols)*(baseW+pad);
  const y=top+Math.floor(i/cols)*(cellH+pad);
  ctx.fillStyle="#f6f8fa";ctx.fillRect(x,y,cellW,cellH);
  ctx.strokeStyle="#cfdae4";ctx.strokeRect(x,y,cellW,cellH);
  const provider=source(ids[i]),record=cardsAt(ids[i],validity)[0];
  ctx.fillStyle="#18364f";ctx.font="bold 20px Arial";ctx.fillText(provider?.name||ids[i],x+15,y+27);
  ctx.fillStyle="#556c7e";ctx.font="14px Arial";
  ctx.fillText(recordType(record)+" · "+record.kind+(record.forecast_hours?" +"+record.forecast_hours+" h":""),x+15,y+49);
  try{
   const img=new Image();img.src=ROOT+record.image;
   await img.decode();
   const maxW=cellW-26,maxH=cellH-86,scale=Math.min(maxW/img.naturalWidth,maxH/img.naturalHeight);
   const ww=img.naturalWidth*scale,hh=img.naturalHeight*scale;
   ctx.drawImage(img,x+(cellW-ww)/2,y+60+(maxH-hh)/2,ww,hh);loaded++;
  }catch(e){ctx.fillText("Originalbild nicht erreichbar",x+20,y+89);}
 }
 if(!loaded)return;
 ctx.font="14px Arial";ctx.fillStyle="#5a7083";
 const providers=[...new Set(ids.map(id=>source(id)?.name||id))].join(" · ");
 ctx.fillText(("Quellen: "+providers).slice(0,145),32,H-49);
 ctx.fillText("Originalbilder mit Quellenangaben und Bildgültigkeit; Reprojektion und künstliche Fronten wurden nicht vorgenommen.",32,H-30);
 if(ids.some(id=>id==="chmi")){
  ctx.fillText("ČHMÚ · CC BY 4.0 · https://creativecommons.org/licenses/by/4.0/ · PNG→WebP / Anordnung",32,H-11);
 }
 const a=document.createElement("a");
 a.download="Synoptik_Originalkarten_"+validity.slice(0,16).replace(/[-:]/g,"")+(four?"_vergleich":"")+".png";
 a.href=canvas.toDataURL("image/png");document.body.append(a);a.click();a.remove();
}
async function load(){
 $("chartStatus").textContent="Prüfe die neuesten veröffentlichten Originalkarten …";
 try{
  const resp=await fetch(ROOT+"index.json?v="+Date.now(),{cache:"no-store"});
  if(!resp.ok)throw new Error("Kartenindex nicht erreichbar (HTTP "+resp.status+")");
  const data=await resp.json();
  if(data.schema_version!==1||!data.ready||!Array.isArray(data.charts)||
     !Array.isArray(data.sources)||!Array.isArray(data.time_slots)||
     !data.source_status||!Number.isFinite(Date.parse(data.generated_utc)))throw new Error("Quellenindex ungültig");
  for(const rec of data.charts){
   if(!/^(?:dwd|aemet|noaa_opc|noaa_full|noaa_west|noaa_24|noaa_48|noaa_96|chmi|dhmz|knmi|imo)$/.test(rec.source_id)||!/^images\/[a-z0-9_]+\.webp$/.test(rec.image))throw new Error("Ungültige Bildreferenz");
   if(!Number.isFinite(Date.parse(rec.valid_utc)))throw new Error("Ungültiger Gültigkeitstermin");
  }
  catalog=data;
  try{
   const check=await fetch(ROOT+"europe_source_audit.json?v="+Date.now(),{cache:"no-store"});
   if(check.ok){
    const candidate=await check.json();
    europeSourceAudit=candidate.schema_version===1&&candidate.no_live_check&&Array.isArray(candidate.providers)?candidate:null;
   }else europeSourceAudit=null;
  }catch(_e){europeSourceAudit=null;}
  try{
   const response=await fetch(ROOT+"imo_probe.json?v="+Date.now(),{cache:"no-store"});
   if(response.ok){
    const report=await response.json();
    imoDiagnostic=report.schema_version===1&&
     report.ready_for_automated_chart_ingestion===false&&
     Array.isArray(report.pages)?report:null;
   }else imoDiagnostic=null;
  }catch(_e){imoDiagnostic=null;}
  try{
   const response=await fetch(ROOT+"europe_viewer_probe.json?v="+Date.now(),{cache:"no-store"});
   if(response.ok){
    const result=await response.json();
    europeanViewerProbe=result.schema_version===1&&result.no_auto_ingestion===true&&
      Array.isArray(result.sources)?result:null;
   }else europeanViewerProbe=null;
  }catch(_e){europeanViewerProbe=null;}
  try{
   const res=await fetch(ROOT+"rhmz_probe.json?v="+Date.now(),{cache:"no-store"});
   if(res.ok){
    const audit=await res.json();
    rhmzProbe=audit.schema_version===1&&audit.only_external_links===true&&
     Array.isArray(audit.records)&&audit.records.length===6?audit:null;
   }else rhmzProbe=null;
  }catch(_e){rhmzProbe=null;}
  try{
   const response=await fetch(ROOT+"cyprus_wrf_probe.json?v="+Date.now(),{cache:"no-store"});
   if(response.ok){
    const candidate=await response.json();
    cyprusProbe=candidate.schema_version===1&&candidate.no_images_persisted===true&&
      candidate.ready_for_automatic_image_reuse===false&&Array.isArray(candidate.reports)&&
      candidate.reports.length===2?candidate:null;
   }else cyprusProbe=null;
  }catch(_e){cyprusProbe=null;}
  renderDataHealth();
  fillSources();
  fillPickers();
  refreshView();
 }catch(err){
  catalog=null;europeSourceAudit=null;imoDiagnostic=null;europeanViewerProbe=null;rhmzProbe=null;cyprusProbe=null;
  $("chartStatus").textContent="Kartenindexfehler: "+err.message;
  renderDataHealth();
  $("chartGrid").replaceChildren(node("div","empty","Keine erfundenen Ersatzkarten: Der Kartenindex ist aktuell nicht verfügbar. Die Links zu den Wetterdiensten sind weiterhin unten erreichbar."));
  $("exportPng").disabled=true;
  fillSources();
  updatePanelControls();
 }
}
function init(){
 $("reload").addEventListener("click",load);
 ["sourceSearch","sourceFilter"].forEach(id=>$(id)?.addEventListener(id==="sourceSearch"?"input":"change",fillSources));
 $("chartMode").addEventListener("change",()=>{
  if(catalog){
   if($("chartMode").value==="four"&&panelAutomatic())autoBestPanels();
   else if($("chartMode").value==="single")nearestTimeFor([$("singleSource").value]);
  }
  refreshView();
 });
 $("uniquePublishers").addEventListener("change",()=>{
  if(catalog&&$("chartMode").value==="four"&&panelAutomatic())autoBestPanels();
  refreshView();
 });
 $("fourPolicy").addEventListener("change",()=>{
  if(catalog&&panelAutomatic())autoBestPanels();
  refreshView();
 });
 $("optimizePanels").addEventListener("click",()=>{
  $("fourPolicy").value="auto";
  autoBestPanels();
  refreshView();
 });
 $("validTime").addEventListener("change",()=>{
  if(catalog&&$("chartMode").value==="four"&&panelAutomatic())autoAtCurrentTime();
  refreshView();
 });
 $("singleSource").addEventListener("change",()=>{
  if(catalog)nearestTimeFor([$("singleSource").value]);
  refreshView();
 });
 slots.forEach(id=>$(id).addEventListener("change",()=>{
  // In manual mode neither the other sources nor the UTC time are overwritten.
  if($("chartMode").value==="four"&&panelAutomatic())$("fourPolicy").value="manual";
  refreshView();
 }));
 $("chartKind").addEventListener("change",()=>{
  if(!catalog)return;
  rebuildTimes($("singleSource").value,false);
  if($("chartMode").value==="four"&&panelAutomatic())autoBestPanels();
  else if($("chartMode").value==="single")nearestTimeFor([$("singleSource").value]);
  else nearestTimeFor(currentProviders());
  refreshView();
 });
 $("exportPng").addEventListener("click",pngExport);
 load();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();