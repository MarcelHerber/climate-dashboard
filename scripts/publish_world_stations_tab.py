#!/usr/bin/env python3
import argparse
import gzip
import json
import pickle
from pathlib import Path

TAB_MARKER = '<!-- ================= WELTWEITE STATIONEN · GHCN ================= -->'
JS_MARKER = '// ================= WELTWEITE STATIONEN · GHCN ================='
CSS_MARKER = '/* ================= WELTWEITE STATIONEN · GHCN ================= */'


def _record_value(block, key):
    record = (block or {}).get(key) or {}
    value = record.get('value_c')
    date = record.get('date') or record.get('first_date') or ''
    return value, date


def build_web_data(baseline_path: Path):
    with gzip.open(baseline_path, 'rb') as fh:
        baseline = pickle.load(fh)

    stations_src = baseline.get('stations') or {}
    countries = {}
    stations = []
    with_tmax = 0
    with_tmin = 0
    with_both = 0

    for station_id, s in stations_src.items():
        tmax = s.get('tmax') or {}
        tmin = s.get('tmin') or {}
        has_tmax = int(tmax.get('valid_count') or 0) > 0
        has_tmin = int(tmin.get('valid_count') or 0) > 0
        if not (has_tmax or has_tmin):
            continue

        with_tmax += int(has_tmax)
        with_tmin += int(has_tmin)
        with_both += int(has_tmax and has_tmin)

        cc = (s.get('country_code') or '').strip()
        country = (s.get('country') or cc).strip()
        if cc:
            countries[cc] = country

        tmax_value, tmax_date = _record_value(tmax, 'highest_record') if has_tmax else (None, '')
        tmin_value, tmin_date = _record_value(tmin, 'lowest_record') if has_tmin else (None, '')

        stations.append([
            station_id,
            cc,
            s.get('name') or '',
            s.get('latitude'),
            s.get('longitude'),
            s.get('elevation_m'),
            s.get('state') or '',
            s.get('wmo_id') or '',
            tmax.get('first_valid_date') if has_tmax else '',
            tmax.get('last_valid_date') if has_tmax else '',
            tmax_value,
            tmax_date,
            int(tmax.get('valid_count') or 0) if has_tmax else 0,
            tmin.get('first_valid_date') if has_tmin else '',
            tmin.get('last_valid_date') if has_tmin else '',
            tmin_value,
            tmin_date,
            int(tmin.get('valid_count') or 0) if has_tmin else 0,
        ])

    stations.sort(key=lambda r: (countries.get(r[1], r[1]).casefold(), str(r[2]).casefold(), r[0]))

    return {
        'schema_version': 2,
        'dataset': 'world_ghcn_temperature_stations_through_2025',
        'baseline_version': baseline.get('baseline_version', 'world_ghcn_baseline_through_2025_v1'),
        'baseline_through': '2025-12-31',
        'station_count': len(stations),
        'with_tmax': with_tmax,
        'with_tmin': with_tmin,
        'with_both': with_both,
        'country_codes': len(countries),
        'field_names': [
            'station_id','country_code','station_name','latitude','longitude','elevation_m','state','wmo_id',
            'tmax_first','tmax_last','tmax_record_c','tmax_record_date','tmax_valid_days',
            'tmin_first','tmin_last','tmin_record_c','tmin_record_date','tmin_valid_days'
        ],
        'countries': countries,
        'stations': stations,
        'note': 'Only highest TMAX and lowest TMIN station records are published here; lowest TMAX and highest TMIN are intentionally omitted.'
    }


WORLD_CSS = r'''
/* ================= WELTWEITE STATIONEN · GHCN ================= */
.world-stations-kpis{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin:0 0 16px}
.world-stations-kpi{background:#fff;border:1px solid #d8e0e5;border-radius:10px;padding:12px 14px;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.world-stations-kpi .label{font-size:10px;text-transform:uppercase;letter-spacing:.35px;color:#68737b;font-weight:800}
.world-stations-kpi .value{font-size:22px;font-weight:850;color:#1f2a31;margin-top:5px}
.world-stations-kpi .detail{font-size:11px;color:var(--muted);margin-top:2px;line-height:1.4}
.world-stations-controls{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px;padding:14px 16px;margin-bottom:14px;background:#fff;border-radius:9px;box-shadow:var(--shadow)}
.world-stations-controls .control-group{min-width:180px}
.world-stations-controls .world-search{min-width:min(360px,100%);flex:1}
.world-stations-controls input{width:100%;padding:9px 10px;border:1px solid #bbb;border-radius:6px;background:#fff;font:inherit}
.world-stations-map-shell{position:relative;margin:0 0 16px;background:#fff;border-radius:10px;box-shadow:var(--shadow);overflow:hidden;border:1px solid #d8e0e5}
.world-stations-map{height:620px;background:#eef2f4}
.world-stations-map-status{position:absolute;left:12px;bottom:12px;z-index:500;max-width:min(520px,calc(100% - 24px));padding:8px 10px;border-radius:7px;background:rgba(255,255,255,.94);border:1px solid rgba(60,70,78,.2);box-shadow:0 2px 8px rgba(0,0,0,.12);font-size:11px;color:#3f4a52;line-height:1.4}
.world-stations-legend{display:flex;flex-wrap:wrap;gap:10px 14px;margin:8px 2px 14px;color:#56616a;font-size:11px}
.world-stations-legend-item{display:flex;align-items:center;gap:6px}
.world-stations-dot{width:10px;height:10px;border-radius:50%;display:inline-block;border:1px solid rgba(0,0,0,.22)}
.world-stations-dot.both{background:#376f9e}.world-stations-dot.tmax{background:#b46b32}.world-stations-dot.tmin{background:#6d8d55}
.world-stations-result-note{margin:8px 1px 10px;color:var(--muted);font-size:12px;line-height:1.45}
.world-stations-table-wrap{max-height:62vh;overflow:auto;border:1px solid var(--border);border-radius:9px;background:#fff;box-shadow:var(--shadow)}
.world-stations-table{margin:0;min-width:1320px;font-variant-numeric:tabular-nums}
.world-stations-table thead th{position:sticky;top:0;z-index:3;background:#292f35;color:#fff;font-size:11px;white-space:nowrap}
.world-stations-table td{text-align:left;vertical-align:middle;font-size:12px}
.world-stations-table td.num{text-align:right;white-space:nowrap}.world-stations-table td.date{white-space:nowrap}
.world-stations-table tr[data-station-id]{cursor:pointer}.world-stations-table tr[data-station-id]:hover td{background:#f3f7fa}
.world-stations-pager{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:10px 0 0;padding:10px 12px;background:#fff;border-radius:8px;box-shadow:var(--shadow);font-size:12px}
.world-stations-pager-actions{display:flex;gap:8px}.world-stations-pager button{padding:7px 11px;border:1px solid #aeb7be;border-radius:6px;background:#fff;cursor:pointer;font-weight:700}.world-stations-pager button:disabled{opacity:.45;cursor:default}
.world-station-popup{min-width:265px;line-height:1.45}.world-station-popup h3{font-size:15px;margin:0 0 3px}.world-station-popup .sub{font-size:11px;color:#69747c;margin-bottom:8px}.world-station-popup-grid{display:grid;grid-template-columns:1fr auto;gap:4px 12px;font-size:12px}.world-station-popup-grid strong{text-align:right}.world-station-popup-section{margin-top:8px;padding-top:7px;border-top:1px solid #e1e5e8}.world-station-popup-section b{font-size:12px}
@media(max-width:900px){.world-stations-kpis{grid-template-columns:1fr 1fr}.world-stations-map{height:520px}}
@media(max-width:560px){.world-stations-kpis{grid-template-columns:1fr}.world-stations-controls .control-group{min-width:100%}.world-stations-map{height:470px}.world-stations-pager{align-items:flex-start;flex-direction:column}}
'''

WORLD_HTML = r'''
<!-- ================= WELTWEITE STATIONEN · GHCN ================= -->
<div id="worldStations" class="tab-content">
  <div class="section-header">
    <h2>Weltweite Stationen</h2>
    <p>GHCN-Daily-Temperaturstationen weltweit. Angezeigt werden ausschließlich der höchste Tageshöchstwert (TMAX) und der tiefste Tagesminimumwert (TMIN) jeder Station.</p>
    <span class="section-status">Historische Basis bis 31.12.2025 · GHCN-Daily</span>
  </div>
  <div id="worldStationsLoading" class="record-loading">Weltweite Stationsdaten werden beim ersten Öffnen geladen …</div>
  <div id="worldStationsContent" hidden>
    <div id="worldStationsKpis" class="world-stations-kpis"></div>
    <div class="world-stations-controls">
      <div class="control-group world-search">
        <label for="worldStationsSearch">Station suchen</label>
        <input id="worldStationsSearch" type="search" placeholder="Name, Stations-ID, WMO-ID oder Land …" autocomplete="off">
      </div>
      <div class="control-group">
        <label for="worldStationsCountry">Land / Gebiet</label>
        <select id="worldStationsCountry"><option value="">Alle Länder / Gebiete</option></select>
      </div>
      <div class="control-group">
        <label for="worldStationsAvailability">Daten vorhanden</label>
        <select id="worldStationsAvailability">
          <option value="all">TMAX oder TMIN</option>
          <option value="both">TMAX + TMIN</option>
          <option value="tmax">TMAX</option>
          <option value="tmin">TMIN</option>
        </select>
      </div>
      <button id="worldStationsReset" class="action" type="button">Filter zurücksetzen</button>
    </div>

    <div class="world-stations-map-shell">
      <div id="worldStationsMap" class="world-stations-map" role="img" aria-label="Weltkarte der GHCN-Temperaturstationen"></div>
      <div id="worldStationsMapStatus" class="world-stations-map-status">Stationspunkte werden vorbereitet …</div>
    </div>
    <div class="world-stations-legend">
      <span class="world-stations-legend-item"><span class="world-stations-dot both"></span>TMAX + TMIN</span>
      <span class="world-stations-legend-item"><span class="world-stations-dot tmax"></span>nur TMAX</span>
      <span class="world-stations-legend-item"><span class="world-stations-dot tmin"></span>nur TMIN</span>
    </div>

    <div id="worldStationsResultNote" class="world-stations-result-note"></div>
    <div class="world-stations-table-wrap">
      <table class="world-stations-table">
        <thead><tr><th>Land / Gebiet</th><th>Station</th><th>Stations-ID</th><th>TMAX</th><th>Datum TMAX</th><th>TMAX-Zeitraum</th><th>TMIN</th><th>Datum TMIN</th><th>TMIN-Zeitraum</th></tr></thead>
        <tbody id="worldStationsTableBody"></tbody>
      </table>
    </div>
    <div class="world-stations-pager">
      <div id="worldStationsPageInfo">–</div>
      <div class="world-stations-pager-actions"><button id="worldStationsPrev" type="button">Zurück</button><button id="worldStationsNext" type="button">Weiter</button></div>
    </div>
    <p class="note">TMAX = höchstes gültiges Tagesmaximum der Station bis Ende 2025. TMIN = tiefstes gültiges Tagesminimum der Station bis Ende 2025. Höchstes TMIN und niedrigstes TMAX werden in diesem Reiter bewusst nicht geführt.</p>
  </div>
</div>
'''

WORLD_JS = r'''
// ================= WELTWEITE STATIONEN · GHCN =================
let worldStationsLoaded=false;
let worldStationsLoadingPromise=null;
let worldStationsData=null;
let worldStationsRows=[];
let worldStationsFiltered=[];
let worldStationsPage=0;
let worldStationsMap=null;
let worldStationsLayer=null;
let worldStationsRenderer=null;
let worldStationMarkerById=new Map();
const WORLD_STATIONS_PAGE_SIZE=150;

function worldStationsEscape(value){
  return String(value??"").replace(/[&<>\"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'\"':"&quot;","'":"&#39;"}[char]));
}
function worldStationsFormatTemp(value){
  return Number.isFinite(Number(value))?`${Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`:"–";
}
function worldStationsFormatPeriod(first,last){
  if(!first && !last) return "–";
  return `${first||"?"} – ${last||"?"}`;
}
function worldStationsDecode(row){
  return {
    id:row[0],cc:row[1],country:worldStationsData?.countries?.[row[1]]||row[1],name:row[2],lat:row[3],lon:row[4],elev:row[5],state:row[6],wmo:row[7],
    txFirst:row[8],txLast:row[9],tx:row[10],txDate:row[11],txCount:row[12]||0,
    tnFirst:row[13],tnLast:row[14],tn:row[15],tnDate:row[16],tnCount:row[17]||0
  };
}
function worldStationsAvailabilityClass(s){
  if(s.txCount>0 && s.tnCount>0) return "both";
  if(s.txCount>0) return "tmax";
  return "tmin";
}
function worldStationsPopupHtml(s){
  const coords=(Number.isFinite(Number(s.lat))&&Number.isFinite(Number(s.lon)))?`${Number(s.lat).toFixed(4)}, ${Number(s.lon).toFixed(4)}`:"–";
  const elev=Number.isFinite(Number(s.elev))?`${Number(s.elev).toLocaleString("de-DE",{maximumFractionDigits:1})} m`:"–";
  const state=s.state?` · ${worldStationsEscape(s.state)}`:"";
  const wmo=s.wmo?` · WMO ${worldStationsEscape(s.wmo)}`:"";
  return `<div class="world-station-popup">
    <h3>${worldStationsEscape(s.name||s.id)}</h3>
    <div class="sub">${worldStationsEscape(s.country)}${state} · ${worldStationsEscape(s.id)}${wmo}</div>
    <div class="world-station-popup-grid"><span>Koordinaten</span><strong>${coords}</strong><span>Höhe</span><strong>${elev}</strong></div>
    <div class="world-station-popup-section"><b>TMAX · höchstes Tagesmaximum</b><div class="world-station-popup-grid"><span>Rekord</span><strong>${worldStationsFormatTemp(s.tx)}</strong><span>Datum</span><strong>${worldStationsEscape(s.txDate||"–")}</strong><span>Datenzeitraum</span><strong>${worldStationsEscape(worldStationsFormatPeriod(s.txFirst,s.txLast))}</strong></div></div>
    <div class="world-station-popup-section"><b>TMIN · tiefstes Tagesminimum</b><div class="world-station-popup-grid"><span>Rekord</span><strong>${worldStationsFormatTemp(s.tn)}</strong><span>Datum</span><strong>${worldStationsEscape(s.tnDate||"–")}</strong><span>Datenzeitraum</span><strong>${worldStationsEscape(worldStationsFormatPeriod(s.tnFirst,s.tnLast))}</strong></div></div>
  </div>`;
}
function renderWorldStationsKpis(){
  const box=document.getElementById("worldStationsKpis");
  if(!box || !worldStationsData) return;
  box.innerHTML=`
    <div class="world-stations-kpi"><div class="label">Temperaturstationen</div><div class="value">${Number(worldStationsData.station_count||0).toLocaleString("de-DE")}</div><div class="detail">mindestens ein gültiger TMAX-/TMIN-Wert bis 2025</div></div>
    <div class="world-stations-kpi"><div class="label">Mit TMAX</div><div class="value">${Number(worldStationsData.with_tmax||0).toLocaleString("de-DE")}</div><div class="detail">höchstes Tagesmaximum verfügbar</div></div>
    <div class="world-stations-kpi"><div class="label">Mit TMIN</div><div class="value">${Number(worldStationsData.with_tmin||0).toLocaleString("de-DE")}</div><div class="detail">tiefstes Tagesminimum verfügbar</div></div>
    <div class="world-stations-kpi"><div class="label">TMAX + TMIN</div><div class="value">${Number(worldStationsData.with_both||0).toLocaleString("de-DE")}</div><div class="detail">beide Parameter vorhanden</div></div>`;
}
function populateWorldStationsCountries(){
  const select=document.getElementById("worldStationsCountry");
  if(!select || !worldStationsData) return;
  const current=select.value;
  const items=Object.entries(worldStationsData.countries||{}).sort((a,b)=>a[1].localeCompare(b[1],"de"));
  select.innerHTML='<option value="">Alle Länder / Gebiete</option>'+items.map(([code,name])=>`<option value="${worldStationsEscape(code)}">${worldStationsEscape(name)} (${worldStationsEscape(code)})</option>`).join("");
  if(items.some(([code])=>code===current)) select.value=current;
}
function getFilteredWorldStations(){
  const q=(document.getElementById("worldStationsSearch")?.value||"").trim().toLocaleLowerCase("de");
  const cc=document.getElementById("worldStationsCountry")?.value||"";
  const availability=document.getElementById("worldStationsAvailability")?.value||"all";
  return worldStationsRows.filter(s=>{
    if(cc && s.cc!==cc) return false;
    if(availability==="both" && !(s.txCount>0 && s.tnCount>0)) return false;
    if(availability==="tmax" && !(s.txCount>0)) return false;
    if(availability==="tmin" && !(s.tnCount>0)) return false;
    if(q){
      const hay=[s.id,s.wmo,s.name,s.country,s.cc,s.state].join(" ").toLocaleLowerCase("de");
      if(!hay.includes(q)) return false;
    }
    return true;
  });
}
function renderWorldStationsTable({resetPage=false}={}){
  const tbody=document.getElementById("worldStationsTableBody");
  if(!tbody) return;
  if(resetPage) worldStationsPage=0;
  worldStationsFiltered=getFilteredWorldStations();
  const total=worldStationsFiltered.length;
  const pages=Math.max(1,Math.ceil(total/WORLD_STATIONS_PAGE_SIZE));
  if(worldStationsPage>=pages) worldStationsPage=pages-1;
  const start=worldStationsPage*WORLD_STATIONS_PAGE_SIZE;
  const pageRows=worldStationsFiltered.slice(start,start+WORLD_STATIONS_PAGE_SIZE);
  tbody.innerHTML=pageRows.length?pageRows.map(s=>`<tr data-station-id="${worldStationsEscape(s.id)}" title="Auf der Karte anzeigen">
    <td><strong>${worldStationsEscape(s.country)}</strong><br><span class="note">${worldStationsEscape(s.cc)}</span></td>
    <td>${worldStationsEscape(s.name||"–")}</td>
    <td>${worldStationsEscape(s.id)}${s.wmo?`<br><span class="note">WMO ${worldStationsEscape(s.wmo)}</span>`:""}</td>
    <td class="num"><strong>${worldStationsFormatTemp(s.tx)}</strong></td>
    <td class="date">${worldStationsEscape(s.txDate||"–")}</td>
    <td>${worldStationsEscape(worldStationsFormatPeriod(s.txFirst,s.txLast))}</td>
    <td class="num"><strong>${worldStationsFormatTemp(s.tn)}</strong></td>
    <td class="date">${worldStationsEscape(s.tnDate||"–")}</td>
    <td>${worldStationsEscape(worldStationsFormatPeriod(s.tnFirst,s.tnLast))}</td>
  </tr>`).join(""):'<tr><td colspan="9" style="padding:24px;text-align:center;color:#68737b">Keine passenden Stationen gefunden.</td></tr>';
  const note=document.getElementById("worldStationsResultNote");
  if(note) note.textContent=`${total.toLocaleString("de-DE")} von ${worldStationsRows.length.toLocaleString("de-DE")} Stationen entsprechen dem Filter. Die Karte zeigt weiterhin den vollständigen weltweiten Stationsbestand.`;
  const info=document.getElementById("worldStationsPageInfo");
  if(info) info.textContent=total?`Seite ${(worldStationsPage+1).toLocaleString("de-DE")} von ${pages.toLocaleString("de-DE")} · Stationen ${(start+1).toLocaleString("de-DE")}–${Math.min(start+WORLD_STATIONS_PAGE_SIZE,total).toLocaleString("de-DE")} von ${total.toLocaleString("de-DE")}`:"0 Stationen";
  const prev=document.getElementById("worldStationsPrev");
  const next=document.getElementById("worldStationsNext");
  if(prev) prev.disabled=worldStationsPage<=0;
  if(next) next.disabled=worldStationsPage>=pages-1 || total===0;
}
function focusWorldStation(id){
  const marker=worldStationMarkerById.get(id);
  if(marker && worldStationsMap){
    const ll=marker.getLatLng();
    worldStationsMap.setView(ll,Math.max(worldStationsMap.getZoom(),7),{animate:true});
    marker.openPopup();
    document.getElementById("worldStationsMap")?.scrollIntoView({behavior:"smooth",block:"center"});
  }
}
function bindWorldStationsControls(){
  const search=document.getElementById("worldStationsSearch");
  let timer=null;
  if(search && !search.dataset.worldBound){
    search.addEventListener("input",()=>{window.clearTimeout(timer);timer=window.setTimeout(()=>renderWorldStationsTable({resetPage:true}),180);});
    search.dataset.worldBound="1";
  }
  ["worldStationsCountry","worldStationsAvailability"].forEach(id=>{
    const el=document.getElementById(id);
    if(el && !el.dataset.worldBound){el.addEventListener("change",()=>renderWorldStationsTable({resetPage:true}));el.dataset.worldBound="1";}
  });
  const reset=document.getElementById("worldStationsReset");
  if(reset && !reset.dataset.worldBound){reset.addEventListener("click",()=>{if(search) search.value="";const c=document.getElementById("worldStationsCountry");if(c)c.value="";const a=document.getElementById("worldStationsAvailability");if(a)a.value="all";renderWorldStationsTable({resetPage:true});});reset.dataset.worldBound="1";}
  const prev=document.getElementById("worldStationsPrev");
  if(prev && !prev.dataset.worldBound){prev.addEventListener("click",()=>{if(worldStationsPage>0){worldStationsPage--;renderWorldStationsTable();}});prev.dataset.worldBound="1";}
  const next=document.getElementById("worldStationsNext");
  if(next && !next.dataset.worldBound){next.addEventListener("click",()=>{const pages=Math.ceil(worldStationsFiltered.length/WORLD_STATIONS_PAGE_SIZE);if(worldStationsPage<pages-1){worldStationsPage++;renderWorldStationsTable();}});next.dataset.worldBound="1";}
  const tbody=document.getElementById("worldStationsTableBody");
  if(tbody && !tbody.dataset.worldBound){tbody.addEventListener("click",ev=>{const tr=ev.target.closest("tr[data-station-id]");if(tr) focusWorldStation(tr.dataset.stationId);});tbody.dataset.worldBound="1";}
}
async function buildWorldStationsMap(){
  const el=document.getElementById("worldStationsMap");
  const status=document.getElementById("worldStationsMapStatus");
  if(!el || typeof L==="undefined") return;
  if(!worldStationsMap){
    worldStationsMap=L.map(el,{preferCanvas:true,worldCopyJump:true,minZoom:1,maxZoom:12,zoomControl:true}).setView([18,5],2);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(worldStationsMap);
    worldStationsRenderer=L.canvas({padding:.45});
    worldStationsLayer=L.layerGroup().addTo(worldStationsMap);
  }
  if(worldStationMarkerById.size){window.setTimeout(()=>worldStationsMap.invalidateSize(false),80);return;}
  const total=worldStationsRows.length;
  const batch=1200;
  for(let i=0;i<total;i+=batch){
    const end=Math.min(total,i+batch);
    for(let j=i;j<end;j++){
      const s=worldStationsRows[j];
      if(!Number.isFinite(Number(s.lat)) || !Number.isFinite(Number(s.lon))) continue;
      const cls=worldStationsAvailabilityClass(s);
      const fill=cls==="both"?"#376f9e":cls==="tmax"?"#b46b32":"#6d8d55";
      const marker=L.circleMarker([Number(s.lat),Number(s.lon)],{renderer:worldStationsRenderer,radius:2.35,weight:.45,color:"#24313a",opacity:.55,fillColor:fill,fillOpacity:.68});
      marker.bindPopup(()=>worldStationsPopupHtml(s),{maxWidth:360});
      marker.addTo(worldStationsLayer);
      worldStationMarkerById.set(s.id,marker);
    }
    if(status) status.textContent=`Stationskarte wird aufgebaut: ${end.toLocaleString("de-DE")} / ${total.toLocaleString("de-DE")} Stationen …`;
    await new Promise(resolve=>window.requestAnimationFrame(()=>resolve()));
  }
  if(status) status.textContent=`${worldStationMarkerById.size.toLocaleString("de-DE")} GHCN-Temperaturstationen auf der Karte · historische Werte bis 31.12.2025.`;
  window.setTimeout(()=>worldStationsMap.invalidateSize(false),80);
}
function ensureWorldStationsMobileOption(){
  const mobile=document.getElementById("mobileTabSelect");
  if(!mobile || mobile.querySelector('option[value="worldStations"]')) return;
  const option=document.createElement("option");
  option.value="worldStations";option.textContent="Weltweite Stationen";mobile.appendChild(option);
}
async function ensureWorldStationsLoaded(){
  ensureWorldStationsMobileOption();
  if(worldStationsLoaded){window.setTimeout(()=>worldStationsMap?.invalidateSize(false),80);return;}
  if(worldStationsLoadingPromise) return worldStationsLoadingPromise;
  const loading=document.getElementById("worldStationsLoading");
  const content=document.getElementById("worldStationsContent");
  worldStationsLoadingPromise=(async()=>{
    try{
      const response=await fetch("data/world_stations_stage9.json",{cache:"no-store"});
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      worldStationsData=await response.json();
      worldStationsRows=(worldStationsData.stations||[]).map(worldStationsDecode);
      renderWorldStationsKpis();
      populateWorldStationsCountries();
      bindWorldStationsControls();
      renderWorldStationsTable({resetPage:true});
      if(loading) loading.hidden=true;
      if(content) content.hidden=false;
      worldStationsLoaded=true;
      await buildWorldStationsMap();
    }catch(error){
      console.error("Weltweite Stationsdaten konnten nicht geladen werden:",error);
      if(loading){loading.hidden=false;loading.textContent=`Weltweite Stationsdaten konnten nicht geladen werden: ${error.message}`;}
    }finally{worldStationsLoadingPromise=null;}
  })();
  return worldStationsLoadingPromise;
}
window.addEventListener("load",()=>window.setTimeout(ensureWorldStationsMobileOption,0));
'''


def insert_once(text, marker, needle, payload, where='before'):
    if marker in text:
        return text, False
    if needle not in text:
        raise RuntimeError(f'Einfügemarke nicht gefunden: {needle[:100]}')
    replacement = payload + '\n' + needle if where == 'before' else needle + '\n' + payload
    return text.replace(needle, replacement, 1), True


def patch_index(text: str):
    changed = False
    text, c = insert_once(text, CSS_MARKER, '</style>', WORLD_CSS.rstrip(), 'before'); changed |= c

    nav_button = '      <button class="nav-link tab-button" data-nav-group="world" onclick="switchTab(\'worldStations\')">Weltweite Stationen</button>'
    if "switchTab('worldStations')" not in text:
        nav_anchor = '      <button class="nav-link tab-button" data-nav-group="compare" onclick="switchTab(\'compare\')">Vergleiche</button>'
        if nav_anchor not in text:
            raise RuntimeError('Navigationsanker Vergleiche nicht gefunden.')
        text = text.replace(nav_anchor, nav_button + '\n\n' + nav_anchor, 1)
        changed = True

    text, c = insert_once(text, TAB_MARKER, '<!-- ================= VERGLEICHE ================= -->', WORLD_HTML.rstrip(), 'before'); changed |= c

    lazy = '  if(tab==="worldStations") ensureWorldStationsLoaded();'
    if lazy not in text:
        lazy_anchor = '  if(tab==="europeStations") ensureEuropeStationMap();'
        if lazy_anchor not in text:
            raise RuntimeError('switchTab-Anker europeStations nicht gefunden.')
        text = text.replace(lazy_anchor, lazy_anchor + '\n' + lazy, 1)
        changed = True

    text, c = insert_once(text, JS_MARKER, 'function switchTab(tab,{persist=true}={}){', WORLD_JS.rstrip() + '\n\n', 'before'); changed |= c

    return text, changed


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--index', default='index.html')
    p.add_argument('--baseline-pickle', required=True)
    p.add_argument('--output-json', default='data/world_stations_stage9.json')
    args = p.parse_args()

    index_path = Path(args.index)
    baseline_path = Path(args.baseline_pickle)
    out_path = Path(args.output_json)

    data = build_web_data(baseline_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')

    original = index_path.read_text(encoding='utf-8')
    patched, changed = patch_index(original)
    if changed:
        index_path.write_text(patched, encoding='utf-8')

    print(json.dumps({
        'index_changed': changed,
        'station_count': data['station_count'],
        'with_tmax': data['with_tmax'],
        'with_tmin': data['with_tmin'],
        'with_both': data['with_both'],
        'country_codes': data['country_codes'],
        'output_json': str(out_path),
        'output_bytes': out_path.stat().st_size,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
