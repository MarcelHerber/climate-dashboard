(function(){
"use strict";

const WORLD_STATION_RAW_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/world_stations/";
const WORLD_STATION_MANIFEST_URL=`${WORLD_STATION_RAW_BASE}index.json`;
const WORLD_STATION_TABLE_LIMIT=500;
const WORLD_STATION_REGION_LABELS={
  world:"Welt",Europe:"Europa",Africa:"Afrika",Asia:"Asien",
  "North America":"Nordamerika","South America":"Südamerika",Oceania:"Ozeanien",Antarctica:"Antarktis"
};
const WORLD_STATION_VIEWS={
  world:{center:[18,0],zoom:2},
  Europe:{bounds:[[34,-25],[72,45]]},
  Africa:{bounds:[[-38,-22],[38,58]]},
  Asia:{bounds:[[-12,25],[82,180]]},
  "North America":{bounds:[[5,-170],[84,-20]]},
  "South America":{bounds:[[-58,-92],[16,-30]]},
  Oceania:{center:[-16,155],zoom:3},
  Antarctica:{center:[-82,0],zoom:2}
};
const WORLD_STATION_METRIC_LABELS={
  tmax_highest:"Höchstes Tagesmaximum",tmin_lowest:"Tiefstes Tagesminimum",
  tmin_highest:"Höchstes Tagesminimum",tmax_lowest:"Tiefstes Tagesmaximum"
};

let worldStationManifest=null;
let worldStationManifestLoading=null;
const worldStationPackCache=new Map();
let worldStationCurrentPacks=[];
let worldStationMap=null;
let worldStationLayer=null;
let worldStationRenderer=null;
let worldStationVisibleLookup=new Map();
let worldStationSearchTimer=null;
let worldStationControlsInitialized=false;
let worldStationOriginalSwitchTab=null;

function worldStationEscape(value){return String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));}
function worldStationFormatInt(value){const n=Number(value);return Number.isFinite(n)?n.toLocaleString("de-DE"):"–";}
function worldStationFormatTempTenths(value){const n=Number(value);return Number.isFinite(n)?`${(n/10).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`:"–";}
function worldStationFormatTempC(value){const n=Number(String(value).replace(",","."));return Number.isFinite(n)?`${n.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`:"–";}
function worldStationDate(value){if(!value)return "–";const d=new Date(`${value}T12:00:00Z`);return Number.isNaN(d.getTime())?String(value):d.toLocaleDateString("de-DE");}
function worldStationYears(first,last){const a=Number(first),b=Number(last);return Number.isFinite(a)&&Number.isFinite(b)&&b>=a?b-a+1:0;}
function worldStationRecordStatusClass(status){if(status==="OFFICIAL_SOURCE_BACKED"||status==="OFFICIAL_COVERAGE_GAP")return "official";if(status==="SECONDARY_SOURCE_BACKED")return "secondary";if(status==="GHCN_CANDIDATE"||status==="GHCN_SOURCE_BACKED")return "ghcn";return "open";}
function worldStationRecordStatusLabel(status){return ({OFFICIAL_SOURCE_BACKED:"offiziell",OFFICIAL_COVERAGE_GAP:"offiziell · GHCN-Lücke",SECONDARY_SOURCE_BACKED:"sekundär belegt",GHCN_CANDIDATE:"GHCN-Kandidat",GHCN_SOURCE_BACKED:"GHCN belegt",UNRESOLVED_REVIEW:"noch offen"})[status]||status||"–";}

async function worldStationFetchGzipJson(url){
  const response=await fetch(url,{cache:"force-cache"});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const packed=new Uint8Array(await response.arrayBuffer());
  if(packed.length>=2&&packed[0]===0x1f&&packed[1]===0x8b){
    if(typeof DecompressionStream==="undefined")throw new Error("Der Browser unterstützt gzip-Dekompression nicht.");
    const stream=new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip"));
    return JSON.parse(new TextDecoder("utf-8").decode(new Uint8Array(await new Response(stream).arrayBuffer())));
  }
  return JSON.parse(new TextDecoder("utf-8").decode(packed));
}

async function ensureWorldStationManifest(){
  if(worldStationManifest)return worldStationManifest;
  if(worldStationManifestLoading)return worldStationManifestLoading;
  worldStationManifestLoading=fetch(`${WORLD_STATION_MANIFEST_URL}?v=1`,{cache:"no-store"})
    .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json();})
    .then(data=>{worldStationManifest=data;return data;})
    .finally(()=>{worldStationManifestLoading=null;});
  return worldStationManifestLoading;
}

async function worldStationLoadPack(continent){
  if(worldStationPackCache.has(continent))return worldStationPackCache.get(continent);
  const meta=worldStationManifest?.packs?.[continent];
  if(!meta?.file)throw new Error(`Kein Datenpaket für ${continent}.`);
  const promise=worldStationFetchGzipJson(`${WORLD_STATION_RAW_BASE}${meta.file}?v=${encodeURIComponent(worldStationManifest.generated_at_utc||"")}`)
    .then(pack=>{pack._idx=Object.fromEntries((pack.fields||[]).map((field,index)=>[field,index]));return pack;})
    .catch(error=>{worldStationPackCache.delete(continent);throw error;});
  worldStationPackCache.set(continent,promise);
  return promise;
}

function worldStationRegionValue(){return document.getElementById("worldStationContinent")?.value||"world";}
function worldStationSelectedContinents(){const region=worldStationRegionValue();return region==="world"?(worldStationManifest?.continents||[]):[region];}

async function worldStationLoadRegion(){
  const region=worldStationRegionValue();
  worldStationSetStatus(`${WORLD_STATION_REGION_LABELS[region]||region}: Stationsdaten werden geladen …`);
  const continents=worldStationSelectedContinents();
  worldStationCurrentPacks=await Promise.all(continents.map(worldStationLoadPack));
  worldStationPopulateCountries();
  worldStationApplyRegionView(region);
  worldStationRender();
}

function worldStationSetStatus(text,error=false){const el=document.getElementById("worldStationStatus");if(!el)return;el.textContent=text;el.classList.toggle("world-station-error",Boolean(error));}

function worldStationInitMap(){
  const container=document.getElementById("worldStationMap");if(!container||worldStationMap)return;
  worldStationMap=L.map(container,{preferCanvas:true,worldCopyJump:true,zoomControl:true,attributionControl:true,minZoom:1,maxZoom:11}).setView([18,0],2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:18,attribution:"&copy; OpenStreetMap"}).addTo(worldStationMap);
  worldStationRenderer=L.canvas({padding:.6});
  worldStationLayer=L.layerGroup().addTo(worldStationMap);
}

function worldStationApplyRegionView(region){
  if(!worldStationMap)return;
  const view=WORLD_STATION_VIEWS[region]||WORLD_STATION_VIEWS.world;
  window.setTimeout(()=>{
    worldStationMap.invalidateSize();
    if(view.bounds)worldStationMap.fitBounds(view.bounds,{padding:[12,12]});
    else worldStationMap.setView(view.center,view.zoom);
  },40);
}

function worldStationPopulateCountries(){
  const select=document.getElementById("worldStationCountry");if(!select)return;
  const previous=select.value;
  const countries=new Map();
  worldStationCurrentPacks.forEach(pack=>Object.entries(pack.countries||{}).forEach(([code,name])=>countries.set(code,name)));
  const sorted=[...countries.entries()].sort((a,b)=>String(a[1]).localeCompare(String(b[1]),"de"));
  select.innerHTML='<option value="">Alle Länder</option>'+sorted.map(([code,name])=>`<option value="${worldStationEscape(code)}">${worldStationEscape(name)}</option>`).join("");
  if(sorted.some(([code])=>code===previous))select.value=previous;else select.value="";
}

function worldStationRowCountry(pack,row){const code=String(row[pack._idx.country_code]||"");return {code,name:pack.countries?.[code]||code};}
function worldStationAvailability(pack,row,mode,minYears){
  const i=pack._idx;
  const ty=worldStationYears(row[i.tmax_first_year],row[i.tmax_last_year]);
  const ny=worldStationYears(row[i.tmin_first_year],row[i.tmin_last_year]);
  if(mode==="tmax")return ty>=minYears&&ty>0;
  if(mode==="tmin")return ny>=minYears&&ny>0;
  if(mode==="both")return ty>=minYears&&ny>=minYears&&ty>0&&ny>0;
  return Math.max(ty,ny)>=minYears&&Math.max(ty,ny)>0;
}

function worldStationFiltered(){
  const country=document.getElementById("worldStationCountry")?.value||"";
  const status=document.getElementById("worldStationStatusFilter")?.value||"active";
  const availability=document.getElementById("worldStationAvailability")?.value||"any";
  const minYears=Number(document.getElementById("worldStationMinYears")?.value)||0;
  const search=String(document.getElementById("worldStationSearch")?.value||"").trim().toLowerCase();
  const result=[];
  worldStationCurrentPacks.forEach(pack=>{
    const i=pack._idx;
    (pack.rows||[]).forEach(row=>{
      const c=worldStationRowCountry(pack,row);
      if(country&&c.code!==country)return;
      if(status==="active"&&Number(row[i.active])!==1)return;
      if(!worldStationAvailability(pack,row,availability,minYears))return;
      if(search){const hay=`${row[i.id]||""} ${row[i.name]||""} ${c.code} ${c.name}`.toLowerCase();if(!hay.includes(search))return;}
      result.push({pack,row,country:c});
    });
  });
  return result;
}

function worldStationPopup(item){
  const {pack,row,country}=item,i=pack._idx;
  const tmaxPeriod=[row[i.tmax_first_year],row[i.tmax_last_year]].filter(v=>v!=null).join("–")||"–";
  const tminPeriod=[row[i.tmin_first_year],row[i.tmin_last_year]].filter(v=>v!=null).join("–")||"–";
  return `<div class="world-station-popup"><strong>${worldStationEscape(row[i.name]||row[i.id])}</strong><div class="muted">${worldStationEscape(country.name)} · ${worldStationEscape(row[i.id])}</div><div class="muted">TMAX ${tmaxPeriod} · TMIN ${tminPeriod}</div><div class="extreme"><b>TMAX max:</b> ${worldStationFormatTempTenths(row[i.tmax_high_tenths])} · ${worldStationDate(row[i.tmax_high_date])}</div><div class="extreme"><b>TMIN min:</b> ${worldStationFormatTempTenths(row[i.tmin_low_tenths])} · ${worldStationDate(row[i.tmin_low_date])}</div><div class="extreme"><b>TMIN max:</b> ${worldStationFormatTempTenths(row[i.tmin_high_tenths])} · ${worldStationDate(row[i.tmin_high_date])}</div><div class="extreme"><b>TMAX min:</b> ${worldStationFormatTempTenths(row[i.tmax_low_tenths])} · ${worldStationDate(row[i.tmax_low_date])}</div></div>`;
}

function worldStationSelect(item){
  const el=document.getElementById("worldStationSelected");if(!el)return;
  const {pack,row,country}=item,i=pack._idx;
  const elevation=Number(row[i.elevation_m]);
  const tmaxPeriod=[row[i.tmax_first_year],row[i.tmax_last_year]].filter(v=>v!=null).join("–")||"–";
  const tminPeriod=[row[i.tmin_first_year],row[i.tmin_last_year]].filter(v=>v!=null).join("–")||"–";
  el.innerHTML=`<h3>${worldStationEscape(row[i.name]||row[i.id])}</h3><p class="note">${worldStationEscape(country.name)} · ${worldStationEscape(row[i.id])}</p><div class="world-station-selected-grid"><div><div class="label">Status</div><div class="value">${Number(row[i.active])===1?"aktiv bis 2025":"historisch"}</div></div><div><div class="label">Höhe</div><div class="value">${Number.isFinite(elevation)?`${elevation.toLocaleString("de-DE",{maximumFractionDigits:0})} m`:"–"}</div></div><div><div class="label">TMAX-Reihe</div><div class="value">${tmaxPeriod}</div></div><div><div class="label">TMIN-Reihe</div><div class="value">${tminPeriod}</div></div><div><div class="label">TMAX max</div><div class="value">${worldStationFormatTempTenths(row[i.tmax_high_tenths])}<br>${worldStationDate(row[i.tmax_high_date])}</div></div><div><div class="label">TMIN min</div><div class="value">${worldStationFormatTempTenths(row[i.tmin_low_tenths])}<br>${worldStationDate(row[i.tmin_low_date])}</div></div><div><div class="label">TMIN max</div><div class="value">${worldStationFormatTempTenths(row[i.tmin_high_tenths])}<br>${worldStationDate(row[i.tmin_high_date])}</div></div><div><div class="label">TMAX min</div><div class="value">${worldStationFormatTempTenths(row[i.tmax_low_tenths])}<br>${worldStationDate(row[i.tmax_low_date])}</div></div></div>`;
}

function worldStationRenderMap(items){
  worldStationInitMap();if(!worldStationMap||!worldStationLayer)return;
  worldStationLayer.clearLayers();
  worldStationVisibleLookup=new Map();
  items.forEach(item=>{
    const {pack,row}=item,i=pack._idx;
    const lat=Number(row[i.lat]),lon=Number(row[i.lon]);if(!Number.isFinite(lat)||!Number.isFinite(lon))return;
    const active=Number(row[i.active])===1;
    const marker=L.circleMarker([lat,lon],{renderer:worldStationRenderer,radius:active?3:2.4,weight:.55,color:active?"#1f6b49":"#7e878e",fillColor:active?"#3aa06a":"#9da5ab",fillOpacity:active?.62:.34});
    marker.bindPopup(()=>worldStationPopup(item),{maxWidth:340});
    marker.on("click",()=>worldStationSelect(item));
    marker.addTo(worldStationLayer);
    worldStationVisibleLookup.set(String(row[i.id]),item);
  });
}

function worldStationRenderTable(items){
  const tbody=document.querySelector("#worldStationTable tbody");if(!tbody)return;
  const sorted=[...items].sort((a,b)=>a.country.name.localeCompare(b.country.name,"de")||String(a.row[a.pack._idx.name]).localeCompare(String(b.row[b.pack._idx.name]),"de"));
  const shown=sorted.slice(0,WORLD_STATION_TABLE_LIMIT);
  if(!shown.length){tbody.innerHTML='<tr><td colspan="9">Keine Stationen für diese Filterkombination.</td></tr>';}
  else tbody.innerHTML=shown.map(item=>{const {pack,row,country}=item,i=pack._idx;const tmax=[row[i.tmax_first_year],row[i.tmax_last_year]].filter(v=>v!=null).join("–")||"–";const tmin=[row[i.tmin_first_year],row[i.tmin_last_year]].filter(v=>v!=null).join("–")||"–";return `<tr data-world-station-id="${worldStationEscape(row[i.id])}"><td class="name">${worldStationEscape(row[i.name]||row[i.id])}</td><td>${worldStationEscape(row[i.id])}</td><td class="country">${worldStationEscape(country.name)}</td><td>${Number(row[i.active])===1?'<span class="active-dot"></span>aktiv':'<span class="inactive-dot"></span>historisch'}</td><td>${tmax}</td><td>${tmin}</td><td>${worldStationFormatTempTenths(row[i.tmax_high_tenths])}</td><td>${worldStationFormatTempTenths(row[i.tmin_low_tenths])}</td><td>${Number.isFinite(Number(row[i.elevation_m]))?`${Number(row[i.elevation_m]).toLocaleString("de-DE",{maximumFractionDigits:0})} m`:"–"}</td></tr>`;}).join("");
  tbody.querySelectorAll("tr[data-world-station-id]").forEach(tr=>tr.addEventListener("click",()=>{const item=worldStationVisibleLookup.get(tr.dataset.worldStationId);if(!item)return;worldStationSelect(item);const i=item.pack._idx;worldStationMap?.setView([Number(item.row[i.lat]),Number(item.row[i.lon])],Math.max(worldStationMap.getZoom(),6));}));
  const note=document.getElementById("worldStationTableNote");if(note)note.textContent=items.length>WORLD_STATION_TABLE_LIMIT?`${worldStationFormatInt(items.length)} Treffer · Tabelle zeigt die ersten ${WORLD_STATION_TABLE_LIMIT}; die Karte enthält alle gefilterten Stationen.`:`${worldStationFormatInt(items.length)} Stationen in der Tabelle.`;
}

function worldStationCountryRecordsMap(){
  const fields=worldStationManifest?.country_record_fields||[];const idx=Object.fromEntries(fields.map((field,index)=>[field,index]));const map=new Map();
  (worldStationManifest?.country_records||[]).forEach(row=>{const code=String(row[idx.country_code]||"");if(!map.has(code))map.set(code,[]);map.get(code).push({row,idx});});return map;
}

function worldStationRenderCountryRecords(){
  const target=document.getElementById("worldStationCountryRecords");if(!target)return;
  const code=document.getElementById("worldStationCountry")?.value||"";
  if(!code){target.innerHTML=`<p class="note">Wähle ein Land aus. Dann erscheinen hier die vier Länderrekord-Metriken aus dem Stage-9-QC-Master. Publishable: ${worldStationFormatInt(worldStationManifest?.country_record_publishable_count)} von ${worldStationFormatInt(worldStationManifest?.country_records?.length)} Länder-/Metrikzeilen.</p>`;return;}
  const records=worldStationCountryRecordsMap().get(code)||[];
  const order=["tmax_highest","tmin_lowest","tmin_highest","tmax_lowest"];
  records.sort((a,b)=>order.indexOf(a.row[a.idx.metric])-order.indexOf(b.row[b.idx.metric]));
  if(!records.length){target.innerHTML='<p class="note">Für dieses Land liegen im Stage-9-Master keine Rekordzeilen vor.</p>';return;}
  target.innerHTML=records.map(({row,idx})=>{const metric=row[idx.metric],status=row[idx.master_status],publishable=String(row[idx.publishable]||"").toLowerCase()==="yes",source=String(row[idx.source]||"");const sourceHtml=source.startsWith("http")?`<a href="${worldStationEscape(source)}" target="_blank" rel="noopener">Quelle öffnen</a>`:worldStationEscape(source||"–");return `<div class="world-country-record"><div class="head"><div class="metric">${worldStationEscape(WORLD_STATION_METRIC_LABELS[metric]||metric)}</div><span class="world-record-status ${worldStationRecordStatusClass(status)}">${worldStationEscape(worldStationRecordStatusLabel(status))}</span></div><div class="record-value">${publishable?worldStationFormatTempC(row[idx.value_c]):"noch offen"}</div><div class="record-detail">${publishable?`${worldStationEscape(row[idx.site]||"Ort nicht angegeben")} · ${worldStationDate(row[idx.date])}`:"Dieser Wert wird noch nicht als veröffentlichter Länderrekord verwendet."}</div><div class="source">${sourceHtml}</div></div>`;}).join("");
}

function worldStationRenderSummary(items){
  const active=items.reduce((n,item)=>n+(Number(item.row[item.pack._idx.active])===1?1:0),0);
  const countries=new Set(items.map(item=>item.country.code));
  const region=worldStationRegionValue();
  const total=worldStationManifest?.station_count;
  const map={worldStationShown:items.length,worldStationActiveShown:active,worldStationCountriesShown:countries.size};
  Object.entries(map).forEach(([id,value])=>{const el=document.getElementById(id);if(el)el.textContent=worldStationFormatInt(value);});
  const data=document.getElementById("worldStationDataStatus");if(data)data.textContent=`${WORLD_STATION_REGION_LABELS[region]||region} · ${worldStationFormatInt(total)} Stationen weltweit`;
}

function worldStationRender(){
  const items=worldStationFiltered();
  worldStationRenderSummary(items);worldStationRenderMap(items);worldStationRenderTable(items);worldStationRenderCountryRecords();
  const region=WORLD_STATION_REGION_LABELS[worldStationRegionValue()]||worldStationRegionValue();
  worldStationSetStatus(`${region}: ${worldStationFormatInt(items.length)} Stationen nach Filter · GHCN-Daily bis ${worldStationManifest?.baseline_cutoff_year||2025}.`);
}

function worldStationInitControls(){
  if(worldStationControlsInitialized)return;worldStationControlsInitialized=true;
  ["worldStationCountry","worldStationStatusFilter","worldStationAvailability","worldStationMinYears"].forEach(id=>document.getElementById(id)?.addEventListener("change",worldStationRender));
  document.getElementById("worldStationContinent")?.addEventListener("change",()=>worldStationLoadRegion().catch(error=>{console.error(error);worldStationSetStatus(`Weltweite Stationen konnten nicht geladen werden: ${error.message}`,true);}));
  document.getElementById("worldStationSearch")?.addEventListener("input",()=>{clearTimeout(worldStationSearchTimer);worldStationSearchTimer=setTimeout(worldStationRender,120);});
}

async function ensureWorldStationMap(){
  try{
    worldStationInitControls();worldStationInitMap();
    const manifest=await ensureWorldStationManifest();
    const base=document.getElementById("worldStationBaselineInfo");if(base)base.textContent=`GHCN ${manifest.ghcn_version||""} · historischer Cutoff ${manifest.baseline_cutoff_year||2025}`;
    await worldStationLoadRegion();
    window.setTimeout(()=>worldStationMap?.invalidateSize(),80);
  }catch(error){console.error(error);worldStationSetStatus(`Weltweite Stationen konnten nicht geladen werden: ${error.message}`,true);}
}

window.ensureWorldStationMap=ensureWorldStationMap;
worldStationOriginalSwitchTab=window.switchTab;
if(typeof worldStationOriginalSwitchTab==="function"){
  window.switchTab=function(tab,options){const result=worldStationOriginalSwitchTab(tab,options);if(tab==="worldStations")window.setTimeout(()=>ensureWorldStationMap(),0);return result;};
}
})();
