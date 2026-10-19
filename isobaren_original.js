(()=>{"use strict";
const ROOT="data/synoptic_charts/";
const $=id=>document.getElementById(id);
const slots=["panel0","panel1","panel2","panel3"];
const INITIAL=["dwd","aemet","noaa_opc","chmi"];
let catalog=null;
let europeSourceAudit=null;
let imoDiagnostic=null;
let automaticChoice=null;
const isoDE=s=>{const d=new Date(s);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat("de-DE",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",timeZone:"UTC",hourCycle:"h23"}).format(d)+" UTC":"–";};
const node=(tag,cls,txt)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined)n.textContent=txt;return n;};
const source=id=>sourceDirectory().find(s=>s.id===id);
const sourceList=()=>sourceDirectory();
const showRecord=x=>globalThis.SynopticPanelLogic?.visible(x,$("chartKind").value)===true;
const recordType=x=>globalThis.SynopticPanelLogic?.label?.[globalThis.SynopticPanelLogic.classify(x)]||"Originalkarte";
const cardsAt=(id,time)=>(catalog?.charts||[]).filter(x=>x.source_id===id&&x.valid_utc===time&&showRecord(x));
const CURATED_SOURCES=[{"id":"dwd","name":"DWD · Bodenanalyse","country":"Deutschland","url":"https://www.dwd.de/DWD/wetter/wv_spez/hobbymet/wetterkarten/bwk_bodendruck_na_ana.png","note":"Direkter Link zum aktuellen Bild; automatischer Abruf erfolgt separat über DWD Open Data."},{"id":"aemet","name":"AEMET · Frontenkarten","country":"Spanien","url":"https://www.aemet.es/es/eltiempo/prediccion/mapa_frentes","note":"Amtliche Boden- und Frontenkarten."},{"id":"chmi","name":"ČHMÚ · Synoptische Situation","country":"Tschechien","url":"https://www.chmi.cz/predpoved-pocasi/synopticka-situace","note":"Amtliche synoptische Analyse und Prognose."},{"id":"dhmz","name":"DHMZ · Frontenprognose","country":"Kroatien","url":"https://meteo.hr/prognoze_e.php?param=web_fronte_sutra12&section=prognoze_model","note":"Amtliche Europa-Frontenprognose; Bildabruf nur mit geprüftem Druckdatum."},{"id":"knmi","name":"KNMI · Analysen und Prognosen","country":"Niederlande","url":"https://www.knmi.nl/nederland-nu/weer/waarschuwingen-en-verwachtingen/weerkaarten","note":"Automatischer Original-GIF-Abruf mit datierten UTC-Terminen; Veröffentlichung nur nach erfolgreichem Datenlauf.","category":"auto"},{"id":"knmi_archiv","name":"KNMI · Wetterkartenarchiv","country":"Niederlande","url":"https://www.knmi.nl/nederland-nu/klimatologie/daggegevens/weerkaarten","category":"archive","note":"Historisches Wetterkartenarchiv ab 2003."},{"id":"kmi","name":"KMI · Frontenkarten","country":"Belgien","url":"https://www.meteo.be/de/wetter/vorhersage/frontenkarten","category":"viewer","note":"Offizielle Frontenprognosen, jedoch noch keine gesicherte automatisch abrufbare Einzelbildzeit."},{"id":"dmi","name":"DMI · Analyse und Prognose","country":"Dänemark","url":"https://www.dmi.dk/vejret/frontkort","category":"viewer","note":"Amtliche Analyse- und Prognosekarten; DMI erlaubt ohne schriftliche Freigabe keine Übernahme von Kartenbildern auf andere Websites.","type":"external"},{"id":"metie","name":"Met Éireann · Bodenanalyse","country":"Irland","url":"https://www.met.ie/latest-reports/surface-analysis","category":"viewer","note":"Bodendruck- und Frontenanalyse für den Nordatlantik. Nur Originalseite verlinkt; keine automatische Bildübernahme."},{"id":"metoffice","name":"Met Office · Surface Pressure","country":"Großbritannien","url":"https://weather.metoffice.gov.uk/maps-and-charts/surface-pressure","category":"viewer","note":"Offizieller Bodendruck- und Frontenkartenviewer; extern öffnen."},{"id":"meteofrance","name":"Météo-France · Isofronts","country":"Frankreich","url":"https://meteofrance.com/isofronts","category":"viewer","note":"Isofronts-Kartenansicht des französischen Wetterdienstes."},{"id":"meteociel","name":"Météociel · Frontenanalyse","country":"Frankreich","url":"https://www.meteociel.fr/fronts/index.php","category":"viewer","note":"Externe Kartenansicht eines Drittanbieters, mit Animation."},{"id":"hungaromet","name":"HungaroMet · Frontenkarte","country":"Ungarn","url":"https://www.met.hu/en/idojaras/aktualis_idojaras/front/","category":"viewer","note":"Offizieller Frontenviewer; Datierung des Einzelbilds und Verwendung für automatische Kopien nicht abgesichert."},{"id":"shmu","name":"SHMÚ · Bodenwetterkarte","country":"Slowakei","url":"https://www.shmu.sk/en/?page=980","category":"viewer","note":"Amtliche datierte Bodenanalyse. SHMÚ gestattet Kopien nicht pauschal außerhalb privater Nutzung – daher nur externe Originalansicht.","type":"external"},{"id":"ilmateenistus","name":"Ilmateenistus · Wetterkarte","country":"Estland","url":"https://www.ilmateenistus.ee/ilm/prognoosid/ilmakaart/?lang=en","category":"unverified","note":"Wetterkartenansicht; Isobaren und UTC-Gültigkeit noch nicht gesichert."},{"id":"fmi","name":"FMI · Europäische Wetterlage","country":"Finnland","url":"https://en.ilmatieteenlaitos.fi/weather-in-europe","category":"unverified","note":"Wetterlagen-Seite; konkretes Isobarenbild nicht bestätigt."},{"id":"meteoam","name":"Aeronautica Militare · Suolo","country":"Italien","url":"https://www.meteoam.it/it/suolo","category":"viewer","note":"Amtlicher Bodenwetterkartenbereich; aktuelle Kartenzeit nicht unabhängig bestätigt."},{"id":"mgm","name":"MGM · Synoptikkarten","country":"Türkei","url":"https://hezarfen.mgm.gov.tr/HzUsr/SinHarita/Default.aspx","category":"unverified","note":"Synoptikkarten-Bereich, noch kein verifiziertes aktuelles Kartenbild."},{"id":"smhi","name":"SMHI · Tageskartenarchiv","country":"Schweden","url":"https://www.smhi.se/klimat/klimatet-da-och-nu/manadens-vader-och-vatten-i-sverige","category":"archive","note":"Erläuterung zum Tageskartenarchiv, kein direkter Live-Viewer."},{"id":"imo","name":"IMO · Atlantik-Isobaren (ECMWF)","country":"Island","url":"https://en.vedur.is/weather/shipping/atlantic/","category":"unverified","note":"Nordatlantische ECMWF-Isobaren- und Windprognosen ohne eingezeichnete Fronten. Ein automatisches Panelbild erscheint ausschließlich, wenn Originaldatei und beide aufgedruckten Zeitangaben unabhängig übereinstimmen."},{"id":"metno","name":"MET Norway · Wetter und Klima","country":"Norwegen","url":"https://www.met.no/en/weather-and-climate","category":"unverified","note":"Allgemeine Wetterseite; kein bestätigter Isobaren-Direktlink."},{"id":"imgw","name":"IMGW · Wetterportal","country":"Polen","url":"https://meteo.imgw.pl/","category":"unverified","note":"Wetterportal; aktueller Karten-Direktlink nicht bestätigt."},{"id":"geosphere","name":"GeoSphere Austria · Wetterkarte","country":"Österreich","url":"https://www.zamg.ac.at/cms/de/wetter/wetterkarte","category":"unverified","note":"Ältere ZAMG-Adresse; Ziel und aktueller Karteninhalt nicht gesichert."},{"id":"ipma","name":"IPMA · Numerische Karten","country":"Portugal","url":"https://www.ipma.pt/pt/otempo/prev.numerica/index.jsp","category":"unverified","note":"Numerische Wetterkarten; Fronten-/Isobareninhalt nicht sicher bestätigt."},{"id":"ipma_history","name":"IPMA · Historische Bodenanalyse","country":"Portugal","url":"https://observar.ipma.pt/superficie-frontal-fria/","category":"archive","note":"Historische Karte aus einer Fallstudie, nicht die aktuelle Wetterlage."},{"id":"nimh_history","name":"NIMH · Synoptik-Hintergrund","country":"Bulgarien","url":"https://storm.cfd.meteo.bg/weather/1en/index.php?koiFail=zaNas&lng=0","category":"unverified","note":"Beschreibung der synoptischen Analyse, kein Live-Kartenbild."},{"id":"anm_history","name":"ANM · Historische Analyse","country":"Rumänien","url":"https://www.meteoromania.ro/wp-content/uploads/comunicate/30_NOIEMBRIE_ANALIZ%C4%82%20SINOPTIC%C4%82%20%C8%98I%20IMPACT%20METEOROLOGIC%20AL%20CICLONULUI%20MEDITERANEAN%20ADEL%20%C3%8EN%20PERIOADA%2026-30%20NOIEMBRIE%202025.pdf","category":"archive","note":"Fallbericht mit Bodenkarte vom 29.11.2025; keine aktuelle Analyse."},{"id":"noaa_wpc","name":"NOAA WPC · Bodenwetterkarten","country":"USA","url":"https://www.weather.gov/forecastmaps","category":"viewer","note":"Nordamerika-Analyse und Prognosen."},{"id":"noaa_pacific","name":"NOAA OPC · Pazifik","country":"USA","url":"https://ocean.weather.gov/Pac_tab.php","category":"viewer","note":"Pazifische Bodenanalysen und Prognosen."},{"id":"eccc","name":"ECCC · Nordhemisphäre","country":"Kanada","url":"https://weather.gc.ca/analysis/index_e.html","category":"unverified","note":"Nordhemisphären-Kartenbereich; Zeitstempel für Bildabruf offen."},{"id":"meteoswiss","name":"MeteoSchweiz · Allgemeine Lage","country":"Schweiz","url":"https://www.meteoschweiz.admin.ch/service-und-publikationen/applikationen/allgemeine-lage.html","type":"external","category":"viewer","note":"Fronten- und Großwetterlagenkarte in der Allgemeinen Lage; UTC-Termin und Übernahmerechte noch nicht verifiziert."},{"id":"metie_forecast","name":"Met Éireann · Atlantik-Druckprognosen","country":"Irland","url":"https://www.met.ie/forecasts/atlantic-charts/precipitation-pressure","type":"external","category":"viewer","note":"Offizieller Atlantik-Kartenviewer mit Druck- und Niederschlagsprognosen; nur direkt verlinkt, ohne Bildkopie."}];
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
    p.rights==="map_not_covered_by_ogd"?"OGD gilt nicht pauschal für Karten":"Originalbild nicht freigegeben";
   const policyBadge=node("span","source-rights",tagLabel);
   article.append(policyBadge);
  }
  article.append(node("p","",(s.note||s.license||"")+statusDetail));
  const a=node("a","",category==="archive"?"Archiv / Bericht öffnen":category==="unverified"?"Quelle prüfen":"Karten öffnen");
  a.href=s.url;a.target="_blank";a.rel="noopener noreferrer";article.append(a);
  if(s.source_policy?.terms_url){
   const terms=node("a","source-policy-link","Nutzungsbedingungen ↗");
   terms.href=s.source_policy.terms_url;terms.target="_blank";terms.rel="noopener noreferrer";
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
 $("chartStatus").textContent=isoDE(validity)+" · "+matched+" Originalbilder"+
  (isFour?" in "+ids.length+" sichtbaren Kacheln":"")+
  " · "+publishers.size+" unabhängige Dienste"+
  (external?" · "+external+" externe Verweise":"")+
  (hidden?" · "+hidden+" nicht passende/doppelte Kacheln ausgeblendet":"")+
  (older?" · Achtung: Index älter als 12 Stunden":"");
 $("syncHint").textContent=isFour?
  (matched?
   "Alle angezeigten Originalbilder haben exakt denselben UTC-Gültigkeitstermin. "+
   (ids.length<4?"Der Vergleich zeigt nur "+ids.length+" belegte Kacheln, keine leeren Platzhalter. ":"")+
   ($("uniquePublishers").checked?"Jeder Wetterdienst zählt höchstens einmal.":"Mehrere Produkte desselben Wetterdienstes sind erlaubt.")+
   (external?" Externe Kartenlinks sind nicht Teil des zeitgleichen Bildvergleichs.":""):
   "Für diesen Kartentyp und Zeitpunkt sind keine eingebundenen Originalbilder verfügbar. Externe Links sind keine synchronisierten Karten."):
  (matched?"Originalkarte des gewählten Wetterdienstes für den ausgewiesenen UTC-Termin.":"Für diese Quelle zum gewählten Zeitpunkt kein freigegebenes Originalbild vorhanden.");
}
async function pngExport(){
 const validity=$("validTime").value;
 const ids=currentProviders(),four=ids.length===4;
 const W=four?1640:1180,H=four?1320:1010;
 const canvas=document.createElement("canvas");canvas.width=W;canvas.height=H;
 const ctx=canvas.getContext("2d");if(!ctx)return;
 ctx.fillStyle="#fff";ctx.fillRect(0,0,W,H);
 ctx.fillStyle="#172e46";ctx.font="bold 32px Arial";ctx.fillText("Isobaren & Fronten · Originalkarten",35,55);
 ctx.fillStyle="#455f79";ctx.font="19px Arial";ctx.fillText("Gültig: "+isoDE(validity)+" · identische UTC-Gültigkeit",35,87);
 const pad=24,top=118,cellW=(W-pad*3)/(four?2:1),cellH=(H-top-72-pad*(four?2:1))/(four?2:1);
 let loaded=0;
 for(let i=0;i<ids.length;i++){
  const x=pad+(i%(four?2:1))*(cellW+pad),y=top+Math.floor(i/(four?2:1))*(cellH+pad);
  ctx.fillStyle="#f6f8fa";ctx.fillRect(x,y,cellW,cellH);
  ctx.strokeStyle="#cfdae4";ctx.strokeRect(x,y,cellW,cellH);
  const provider=source(ids[i]),record=cardsAt(ids[i],validity)[0];
  ctx.fillStyle="#18364f";ctx.font="bold 21px Arial";ctx.fillText(provider?.name||ids[i],x+15,y+28);
  ctx.fillStyle="#556c7e";ctx.font="14px Arial";ctx.fillText(record?record.kind+" · "+record.credit:"Kein zeitgleiches Bild / Originalseite öffnen",x+15,y+51);
  if(!record)continue;
  try{
   const img=new Image();
   img.src=ROOT+record.image;
   await img.decode();
   const maxW=cellW-24,maxH=cellH-82,scale=Math.min(maxW/img.naturalWidth,maxH/img.naturalHeight);
   const ww=img.naturalWidth*scale,hh=img.naturalHeight*scale;
   ctx.drawImage(img,x+(cellW-ww)/2,y+60+(maxH-hh)/2,ww,hh);loaded++;
  }catch(e){ctx.fillText("Originalbild nicht erreichbar",x+20,y+86);}
 }
 if(!loaded)return;
 ctx.font="14px Arial";ctx.fillStyle="#5a7083";
 const providers=[...new Set(ids.filter(id=>cardsAt(id,validity).length).map(id=>source(id)?.name||id))].join(" · ");
 ctx.fillText(("Quellen: "+providers).slice(0,160),32,H-34);
 if(ids.some(id=>id==="chmi"&&cardsAt(id,validity).length)){
  ctx.fillText("ČHMÚ · CC BY 4.0 · https://creativecommons.org/licenses/by/4.0/ · PNG→WebP, Panelanordnung",32,H-14);
 }
 const a=document.createElement("a");
 a.download="Synoptik_Originalkarten_"+validity.slice(0,16).replace(/[-:]/g,"")+(four?"_4er":"")+".png";
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
  renderDataHealth();
  fillSources();
  fillPickers();
  refreshView();
 }catch(err){
  catalog=null;europeSourceAudit=null;imoDiagnostic=null;
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