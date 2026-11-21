/* europa-stationen.js – Europa-Stationen (Rekorde, Kalendertag, Karte)
   Aus index.html ausgelagert (Schritt 5). Klassisches Skript, gemeinsamer globaler Scope. */
function europeStationEscapeHtml(value){return String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]||ch));}
function europeStationNormalize(value){return String(value??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLocaleLowerCase("de-DE").trim();}
function setEuropeStationStatus(message,state=""){
  const el=document.getElementById("europeStationStatus");
  if(!el)return;
  el.textContent=message;
  el.className=`europe-station-status${state?` ${state}`:""}`;
}
function initEuropeStationMap(){
  const target=document.getElementById("europeStationMap");
  if(!target||europeStationMap||!window.L)return;
  europeStationMap=L.map(target,{preferCanvas:true,zoomControl:true,minZoom:3,maxZoom:13,worldCopyJump:false,attributionControl:true});
  if(typeof window.attachEuropeStationBasemap==="function")window.attachEuropeStationBasemap(europeStationMap);
  else L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:'&copy; OpenStreetMap-Mitwirkende'}).addTo(europeStationMap);
  europeStationMap.fitBounds([[34,-25],[72,45]],{padding:[8,8]});
  europeStationRenderer=L.canvas({padding:.55});
  europeStationLayer=L.layerGroup().addTo(europeStationMap);
}
function europeStationCoordinates(station){
  const lat=Number(station.lat ?? station.latitude),lon=Number(station.lon ?? station.longitude);
  return Number.isFinite(lat)&&Number.isFinite(lon)?[lat,lon]:null;
}
function europeStationDateIntToText(value){
  if(!value)return "–";const s=String(value).replace(/\D/g,"");if(s.length!==8)return String(value);return `${s.slice(6,8)}.${s.slice(4,6)}.${s.slice(0,4)}`;
}
function europeStationIsoToText(value){
  if(!value)return "–";const m=String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);return m?`${m[3]}.${m[2]}.${m[1]}`:String(value);
}
function europeStationAnyDateToText(value){
  if(!value)return "–";const digits=String(value).replace(/\D/g,"");return digits.length===8&&!String(value).includes("-")?europeStationDateIntToText(value):europeStationIsoToText(value);
}
function europeStationFormatTemp(value){return Number.isFinite(Number(value))?`${Number(value).toFixed(1).replace(".",",")} °C`:"–";}
function europeStationElementBlock(station,param){return param==="tmin"?station?.tmin:station?.tmax;}
function europeStationCurrentYearMeta(station){return station?.new_current_year||station?.new_2026||{};}
function europeStationCurrentYear(){return Number(europeStationData?.current_year)||new Date().getFullYear();}
function europeStationFlagValue(value,param){
  if(value&&typeof value==="object"&&!Array.isArray(value)){
    if(Object.prototype.hasOwnProperty.call(value,param))return europeStationFlagValue(value[param],param);
    if(Object.prototype.hasOwnProperty.call(value,"value"))return europeStationFlagValue(value.value,param);
  }
  if(typeof value==="boolean")return value;
  if(typeof value==="number"&&Number.isFinite(value))return value!==0;
  if(typeof value==="string"){
    const s=value.trim().toLowerCase();
    if(["1","true","yes","ja","active","aktiv","current"].includes(s))return true;
    if(["0","false","no","nein","inactive","inaktiv","closed"].includes(s))return false;
  }
  return null;
}
function europeStationDateYear(value){
  if(value===null||value===undefined||value==="")return NaN;
  if(typeof value==="number"&&Number.isFinite(value)){
    const s=String(Math.trunc(value));
    if(s.length>=4)return Number(s.slice(0,4));
  }
  const m=String(value).match(/(18|19|20|21)\d{2}/);
  return m?Number(m[0]):NaN;
}
function europeStationIsActive(station,param){
  const block=europeStationElementBlock(station,param)||{};
  const explicit=[
    station?.active,station?.is_active,station?.active_current_year,station?.current_year_active,
    station?.active_now,station?.status,station?.active_parameters,
    block?.active,block?.is_active,block?.active_current_year,block?.current_year_active,block?.status
  ];
  for(const candidate of explicit){
    if(Array.isArray(candidate)){
      const normalized=candidate.map(v=>String(v).toLowerCase());
      if(normalized.includes(param.toLowerCase()))return true;
      continue;
    }
    const flag=europeStationFlagValue(candidate,param);
    if(flag!==null)return flag;
  }
  const currentYear=europeStationCurrentYear();
  const endCandidates=[
    block?.end,block?.last_date,block?.data_end,block?.latest_date,block?.end_date,
    station?.end,station?.last_date,station?.data_end,station?.latest_date,station?.end_date,
    station?.last_observation,station?.latest_observation
  ];
  let latestYear=NaN;
  for(const candidate of endCandidates){
    const year=europeStationDateYear(candidate);
    if(Number.isFinite(year)&&( !Number.isFinite(latestYear)||year>latestYear))latestYear=year;
  }
  // Der historische Europa-Basiscache reicht regulär bis zum Vorjahr.
  // Deshalb gilt eine Reihe mit Daten im laufenden Jahr ODER Vorjahr als aktiv.
  return Number.isFinite(latestYear)&&latestYear>=currentYear-1;
}
function europeStationSelectedMmdd(){
  const input=document.getElementById("europeStationDate");
  const value=input?.value||"";const m=value.match(/^\d{4}-(\d{2})-(\d{2})$/);return m?`${m[1]}-${m[2]}`:"01-01";
}
function europeStationMmddLabel(mmdd){const m=String(mmdd).match(/^(\d{2})-(\d{2})$/);return m?`${Number(m[2])}.${Number(m[1])}.`:mmdd;}
function europeStationRecordColor(year,param,isNew=false){
  if(isNew)return param==="tmin"?"#245d9c":"#c83d31";
  const current=europeStationCurrentYear();const age=Number.isFinite(year)?current-year:999;
  if(param==="tmin"){
    if(age<=5)return "#3e76b7";if(age<=15)return "#6f9fc9";if(age<=30)return "#9bbbd5";return "#bac8d3";
  }
  if(age<=5)return "#c9473b";if(age<=15)return "#d97869";if(age<=30)return "#dea59b";return "#cdbdb8";
}
function europeStationChaseColor(view,param){
  if(view?.isNew)return param==="tmin"?"#174f88":"#a62d25";
  if(view?.isTie)return "#76518d";
  const d=Number(view?.distance);
  if(param==="tmin"){
    if(d<=.5)return "#3979b8";if(d<=1)return "#6e9fcb";if(d<=2)return "#9ebbd4";return "#c2cdd6";
  }
  if(d<=.5)return "#c84b3d";if(d<=1)return "#dc7b68";if(d<=2)return "#e5aa98";return "#d7c7c2";
}
function europeStationRecordYear(dateValue){if(!dateValue)return NaN;const s=String(dateValue);return Number(s.slice(0,4));}
function europeStationMarkerRadius(years,mode){if(mode==="newCurrent")return 5;if(mode==="recordChase")return 4.8;return years>=75?4.3:years>=50?3.8:years>=30?3.4:3;}
async function europeStationFetchGzipJson(url){
  const response=await fetch(url,{cache:"force-cache"});if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const packed=new Uint8Array(await response.arrayBuffer());let bytes=packed;
  if(packed.length>=2&&packed[0]===0x1f&&packed[1]===0x8b){
    if(typeof DecompressionStream==="undefined")throw new Error("Der Browser unterstützt gzip-Dekompression für die Tagesrekorde nicht.");
    const stream=new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip"));bytes=new Uint8Array(await new Response(stream).arrayBuffer());
  }
  return JSON.parse(new TextDecoder("utf-8").decode(bytes));
}
async function loadEuropeStationCalendar(mmdd){
  if(europeStationCalendarCache.has(mmdd))return europeStationCalendarCache.get(mmdd);
  const pattern=europeStationData?.calendar_url_pattern||"europe_stations/calendar/{mmdd}.json.gz";
  const path=pattern.replace("{mmdd}",mmdd);const promise=europeStationFetchGzipJson(`${EUROPE_STATION_RAW_BASE}${path}?v=${encodeURIComponent(europeStationData?.generated_at||"")}`).catch(error=>{europeStationCalendarCache.delete(mmdd);throw error;});
  europeStationCalendarCache.set(mmdd,promise);return promise;
}
function europeStationCalendarMap(pack,param){
  const source=param==="tmin"?pack?.tmin:pack?.tmax;const map=new Map();(Array.isArray(source)?source:[]).forEach(row=>map.set(Number(row[0]),row));return map;
}
function europeStationCalendarView(row,years){
  if(!row)return null;
  const finalValue=Number(row[1])/10,recordDate=row[2],prevValue=row[3]==null?null:Number(row[3])/10,prevDate=row[4],currentValue=row[5]==null?null:Number(row[5])/10,currentDate=row[6],isNew=Number(row[7])===1,delta=row[8]==null?null:Number(row[8])/10;
  return {value:finalValue,date:recordDate,years,isNew,previous:prevValue==null?null:{value:prevValue,date:prevDate},current:currentValue==null?null:{value:currentValue,date:currentDate},delta,record:{value:finalValue,date:recordDate}};
}
function europeStationValueForView(station,index,param,mode,calendarMap){
  const block=europeStationElementBlock(station,param);const years=Number(block?.years)||0;
  if(mode==="absolute"){
    const rec=block?.record;if(!rec||!Number.isFinite(Number(rec.value)))return null;
    return {value:Number(rec.value),date:rec.date,years,isNew:Boolean(block?.new_absolute_current_year),previous:block?.previous,current:null,delta:block?.new_absolute_delta,record:rec};
  }
  if(mode==="newCurrent"){
    const meta=europeStationCurrentYearMeta(station);const count=Number(param==="tmin"?meta.tmin_calendar:meta.tmax_calendar)||0;if(count<=0)return null;
    const last=param==="tmin"?meta.tmin_last:meta.tmax_last;return {value:count,date:last,years,isNew:true,count,record:null};
  }
  const row=calendarMap?.get(index);const baseView=europeStationCalendarView(row,years);if(!baseView)return null;
  if(mode==="calendar")return baseView;
  if(mode==="recordChase"){
    if(!baseView.current||!baseView.previous||!Number.isFinite(Number(baseView.current.value))||!Number.isFinite(Number(baseView.previous.value)))return null;
    const currentValue=Number(baseView.current.value),recordValue=Number(baseView.previous.value);
    const signedDistance=param==="tmin"?currentValue-recordValue:recordValue-currentValue;
    const distance=Math.max(0,signedDistance),improvement=Math.max(0,-signedDistance),isTie=Math.abs(signedDistance)<1e-9&&!baseView.isNew;
    return {...baseView,value:currentValue,date:baseView.current.date,recordValue,recordDate:baseView.previous.date,distance,improvement,isTie};
  }
  return baseView;
}
function europeStationPopup(station,param,mode,view,mmdd){
  const block=europeStationElementBlock(station,param)||{};const currentYear=europeStationCurrentYear();const paramLabel=param==="tmin"?"TMIN · tiefstes Minimum":"TMAX · höchstes Maximum";
  let recordHtml="";
  if(mode==="newCurrent"){
    recordHtml=`<div class="record">${Number(view.count||0).toLocaleString("de-DE")} Rekorde</div><div class="record-detail">neue Kalendertagsrekorde ${currentYear}${view.date?` · zuletzt ${europeStationEscapeHtml(europeStationIsoToText(view.date))}`:""}</div>`;
  }else if(mode==="recordChase"){
    recordHtml=`<div class="record">${europeStationFormatTemp(view.value)}</div><div class="record-detail">${currentYear} am ${europeStationEscapeHtml(europeStationMmddLabel(mmdd))} · bisheriger Rekord ${europeStationFormatTemp(view.recordValue)} (${europeStationEscapeHtml(europeStationAnyDateToText(view.recordDate))})</div>`;
    if(view.isNew)recordHtml+=`<div class="new-record">Neuer Rekord · um ${Number(view.improvement||0).toFixed(1).replace(".",",")} °C verbessert</div>`;
    else if(view.isTie)recordHtml+=`<div class="chase">Bestehenden Rekord eingestellt</div>`;
    else recordHtml+=`<div class="chase">Noch ${Number(view.distance||0).toFixed(1).replace(".",",")} °C bis zum Rekord</div>`;
  }else{
    const dateText=mode==="calendar"?europeStationAnyDateToText(view.date):europeStationIsoToText(view.date);
    recordHtml=`<div class="record">${europeStationFormatTemp(view.value)}</div><div class="record-detail">${mode==="calendar"?`Rekord für ${europeStationEscapeHtml(europeStationMmddLabel(mmdd))}`:"Absoluter Stationsrekord"} · ${europeStationEscapeHtml(dateText)}</div>`;
    if(mode==="calendar"&&view.current){recordHtml+=`<div class="record-detail">${currentYear}: ${europeStationFormatTemp(view.current.value)}</div>`;}
    if(view.isNew){
      let comparison="";
      if(mode==="calendar"&&view.previous)comparison=` · vorher ${europeStationFormatTemp(view.previous.value)}`;
      else if(mode==="absolute"&&block.previous)comparison=` · vorher ${europeStationFormatTemp(block.previous.value)}`;
      const delta=Number(view.delta);recordHtml+=`<div class="new-record">Neuer Rekord ${currentYear}${Number.isFinite(delta)?` · um ${delta.toFixed(1).replace(".",",")} °C verbessert`:""}${comparison}</div>`;
    }
  }
  const period=[block.start?europeStationIsoToText(block.start):null,block.end?europeStationIsoToText(block.end):null].filter(Boolean).join(" – ");
  return `<div class="europe-station-popup"><strong>${europeStationEscapeHtml(String(station.name||station.id))}</strong><div class="muted">${europeStationEscapeHtml(String(station.country||station.country_code||""))} · ${europeStationEscapeHtml(paramLabel)}</div>${recordHtml}<div class="record-detail" style="margin-top:7px">Messreihe: ${europeStationEscapeHtml(period||"–")} · ${Number(block.years||0).toLocaleString("de-DE")} Messjahre${Number.isFinite(Number(station.elevation))?`<br>Höhe: ${Math.round(Number(station.elevation))} m`:""}<br>Stations-ID: ${europeStationEscapeHtml(String(station.source_id||station.id||"–"))}</div><div class="source">Quelle: ${europeStationEscapeHtml(String(station.source||europeStationData?.source||"GHCN-Daily"))} · ${europeStationEscapeHtml(String(station.quality_rule||europeStationData?.quality_rule||"Qualitätsregeln der jeweiligen Datenquelle werden angewendet."))}</div></div>`;
}
function europeStationUpdateLegend(param,mode){
  const el=document.getElementById("europeStationLegend");if(!el)return;
  if(mode==="newCurrent"){
    const color=param==="tmin"?"#245d9c":"#c83d31";el.innerHTML=`<div class="europe-station-legend-row"><span class="europe-station-legend-dot" style="background:${color}"></span>mind. ein neuer Rekord ${europeStationCurrentYear()}</div>`;return;
  }
  if(mode==="recordChase"){
    const colors=param==="tmin"?["#174f88","#76518d","#3979b8","#6e9fcb","#9ebbd4","#c2cdd6"]:["#a62d25","#76518d","#c84b3d","#dc7b68","#e5aa98","#d7c7c2"];
    const labels=["Rekord gebrochen","Rekord eingestellt","≤ 0,5 °C Abstand","≤ 1,0 °C Abstand","≤ 2,0 °C Abstand","> 2,0 °C Abstand"];
    el.innerHTML=labels.map((label,i)=>`<div class="europe-station-legend-row"><span class="europe-station-legend-dot" style="background:${colors[i]}"></span>${label}</div>`).join("");return;
  }
  const colors=param==="tmin"?["#3e76b7","#6f9fc9","#9bbbd5","#bac8d3"]:["#c9473b","#d97869","#dea59b","#cdbdb8"];
  el.innerHTML=["≤ 5 Jahre","6–15 Jahre","16–30 Jahre","> 30 Jahre"].map((label,i)=>`<div class="europe-station-legend-row"><span class="europe-station-legend-dot" style="background:${colors[i]}"></span>${label} Rekordalter</div>`).join("");
}
function europeStationUpdateControls(){
  const mode=document.getElementById("europeStationMode")?.value||"absolute";const dateGroup=document.getElementById("europeStationDateGroup");if(dateGroup)dateGroup.hidden=!(mode==="calendar"||mode==="recordChase");
}
function europeStationSearchMatches(station,query){
  if(!query)return true;const hay=europeStationNormalize(`${station?.name||""} ${station?.id||""} ${station?.source_id||""} ${station?.country||""} ${station?.country_code||""}`);return hay.includes(query);
}
function europeStationRankSort(rows,param,mode){
  const copy=[...rows];
  if(mode==="newCurrent")return copy.sort((a,b)=>Number(b.view.count||0)-Number(a.view.count||0)||String(a.station.name||"").localeCompare(String(b.station.name||""),"de"));
  if(mode==="recordChase")return copy.sort((a,b)=>{
    const group=x=>x.view.isNew?0:x.view.isTie?1:2;const g=group(a)-group(b);if(g)return g;
    const d=Number(a.view.distance||0)-Number(b.view.distance||0);if(d)return d;
    return param==="tmin"?Number(a.view.value)-Number(b.view.value):Number(b.view.value)-Number(a.view.value);
  });
  return copy.sort((a,b)=>param==="tmin"?Number(a.view.value)-Number(b.view.value):Number(b.view.value)-Number(a.view.value));
}
function europeStationRankValue(view,mode){
  if(mode==="newCurrent")return `${Number(view.count||0).toLocaleString("de-DE")} Rek.`;
  if(mode==="recordChase"){
    if(view.isNew)return `REKORD +${Number(view.improvement||0).toFixed(1).replace(".",",")} °C`;
    if(view.isTie)return "eingestellt";
    return `noch ${Number(view.distance||0).toFixed(1).replace(".",",")} °C`;
  }
  return europeStationFormatTemp(view.value);
}
function europeStationCountryRecordCounts(rows,mode){
  const counts=new Map();
  rows.forEach(row=>{
    const amount=mode==="newCurrent"?Number(row.view.count||0):(row.view.isNew?1:0);if(amount<=0)return;
    const key=row.station.country||row.station.country_code||"Unbekannt";counts.set(key,(counts.get(key)||0)+amount);
  });
  return [...counts.entries()].sort((a,b)=>b[1]-a[1]||String(a[0]).localeCompare(String(b[0]),"de"));
}
function europeStationFocusById(stationId){
  const marker=europeStationMarkerById.get(String(stationId));if(!marker||!europeStationMap)return;
  const latlng=marker.getLatLng();europeStationMap.flyTo(latlng,Math.max(7,europeStationMap.getZoom()),{duration:.45});
  marker.openPopup();if(marker.bringToFront)marker.bringToFront();
}
function renderEuropeStationRanking(rows,param,mode,mmdd){
  const title=document.getElementById("europeStationRankingTitle"),subtitle=document.getElementById("europeStationRankingSubtitle"),list=document.getElementById("europeStationTop20"),countryEl=document.getElementById("europeStationCountryRanking");if(!list||!countryEl)return;
  const currentYear=europeStationCurrentYear();
  if(title)title.textContent=mode==="newCurrent"?`Top 20 · Rekordstationen ${currentYear}`:mode==="recordChase"?`Rekordjagd · ${europeStationMmddLabel(mmdd)}`:mode==="calendar"?`Top 20 · ${europeStationMmddLabel(mmdd)}`:"Top 20 · Stationsrekorde";
  if(subtitle)subtitle.textContent=mode==="recordChase"?`${currentYear}-Wert gegen bisherigen Kalendertagsrekord · kleinster Abstand zuerst`:mode==="newCurrent"?"Stationen mit den meisten neuen Kalendertagsrekorden":"Ranking reagiert auf Aktivstatus, Land, Messlänge und Stationssuche";
  const ranked=europeStationRankSort(rows,param,mode).slice(0,20);
  if(!ranked.length)list.innerHTML='<div class="europe-station-empty">Für diesen Filter gibt es keine passenden Stationen.</div>';
  else list.innerHTML=ranked.map((row,i)=>{
    const detail=mode==="recordChase"?`${row.station.country||"–"} · ${europeStationFormatTemp(row.view.value)} vs. ${europeStationFormatTemp(row.view.recordValue)}`:mode==="newCurrent"?`${row.station.country||"–"}${row.view.date?` · zuletzt ${europeStationIsoToText(row.view.date)}`:""}`:`${row.station.country||"–"} · ${europeStationAnyDateToText(row.view.date)}`;
    return `<div class="europe-station-rank-row" data-station-id="${europeStationEscapeHtml(String(row.station.id))}"><div class="europe-station-rank-num">${i+1}</div><div class="europe-station-rank-name"><strong>${europeStationEscapeHtml(String(row.station.name||row.station.id))}</strong><span>${europeStationEscapeHtml(detail)}</span></div><div class="europe-station-rank-value">${europeStationEscapeHtml(europeStationRankValue(row.view,mode))}</div></div>`;
  }).join("");
  list.querySelectorAll("[data-station-id]").forEach(el=>el.addEventListener("click",()=>europeStationFocusById(el.dataset.stationId)));
  const countryRows=europeStationCountryRecordCounts(rows,mode).slice(0,10);
  countryEl.innerHTML=countryRows.length?countryRows.map(([name,count])=>`<div class="europe-station-country-row"><strong>${europeStationEscapeHtml(name)}</strong><span>${Number(count).toLocaleString("de-DE")}</span></div>`).join(""):'<div class="europe-station-empty">Keine neuen Rekorde im aktuellen Filter.</div>';
}
async function renderEuropeStations(){
  initEuropeStationMap();if(!europeStationMap||!europeStationLayer||!europeStationData)return;
  const token=++europeStationRenderToken;const param=document.getElementById("europeStationParameter")?.value||"tmax";const mode=document.getElementById("europeStationMode")?.value||"absolute";const country=document.getElementById("europeStationCountry")?.value||"";const minYears=Number(document.getElementById("europeStationMinYears")?.value)||0;const activeOnly=document.getElementById("europeStationActiveOnly")?.checked===true;const mmdd=europeStationSelectedMmdd();const search=europeStationNormalize(document.getElementById("europeStationSearch")?.value||"");
  europeStationUpdateControls();setEuropeStationStatus((mode==="calendar"||mode==="recordChase")?`Tagesdaten für ${europeStationMmddLabel(mmdd)} werden geladen …`:"Stationsrekorde werden dargestellt …");
  let calendarMap=null;
  if(mode==="calendar"||mode==="recordChase"){
    try{const pack=await loadEuropeStationCalendar(mmdd);if(token!==europeStationRenderToken)return;calendarMap=europeStationCalendarMap(pack,param);}catch(error){console.error(error);setEuropeStationStatus(`Tagesarchiv ${mmdd} konnte nicht geladen werden: ${error.message}`,"error");return;}
  }
  europeStationLayer.clearLayers();europeStationMarkerById=new Map();const stations=Array.isArray(europeStationData.stations)?europeStationData.stations:[];let shown=0,newCount=0,extreme=null,extremeStation=null,currentExtreme=null,currentExtremeStation=null,nearRecordCount=0;const bounds=[],rows=[],visibleCountries=new Set();
  stations.forEach((station,index)=>{
    if(country&&station.country!==country)return;if(!europeStationSearchMatches(station,search))return;if(activeOnly&&!europeStationIsActive(station,param))return;
    const block=europeStationElementBlock(station,param);if((Number(block?.years)||0)<minYears)return;const coords=europeStationCoordinates(station);if(!coords)return;const view=europeStationValueForView(station,index,param,mode,calendarMap);if(!view)return;
    shown++;visibleCountries.add(station.country||station.country_code||"–");if(view.isNew)newCount+=mode==="newCurrent"?Number(view.count||0):1;
    if(mode!=="newCurrent"&&mode!=="recordChase"&&Number.isFinite(Number(view.value))){
      if(extreme===null||(param==="tmin"?Number(view.value)<extreme:Number(view.value)>extreme)){extreme=Number(view.value);extremeStation=station;}
    }
    const currentValue=mode==="recordChase"?Number(view.value):mode==="calendar"&&view.current?Number(view.current.value):NaN;
    if(Number.isFinite(currentValue)&&(currentExtreme===null||(param==="tmin"?currentValue<currentExtreme:currentValue>currentExtreme))){currentExtreme=currentValue;currentExtremeStation=station;}
    if(mode==="recordChase"&&Number(view.distance)<=1)nearRecordCount++;
    const year=europeStationRecordYear(view.date);const color=mode==="recordChase"?europeStationChaseColor(view,param):europeStationRecordColor(year,param,view.isNew);const radius=europeStationMarkerRadius(view.years,mode);const marker=L.circleMarker(coords,{renderer:europeStationRenderer,radius,weight:1.05,color:"#fff",fillColor:color,fillOpacity:(mode==="newCurrent"||mode==="recordChase")?.9:.78,opacity:.95,className:"europe-station-dot"});
    marker.bindPopup(europeStationPopup(station,param,mode,view,mmdd),{maxWidth:350});marker.addTo(europeStationLayer);europeStationMarkerById.set(String(station.id),marker);bounds.push(coords);rows.push({station,index,view,coords});
  });
  europeStationLastRows=rows;
  document.getElementById("europeStationShown").textContent=shown.toLocaleString("de-DE");
  const extremeLabel=document.getElementById("europeStationExtremeLabel"),extremeEl=document.getElementById("europeStationExtreme"),extremeDetail=document.getElementById("europeStationExtremeDetail");
  if(mode==="newCurrent"){
    if(extremeLabel)extremeLabel.textContent="Rekordtage";if(extremeEl)extremeEl.textContent=newCount.toLocaleString("de-DE");if(extremeDetail)extremeDetail.textContent=`Summe neuer Kalendertagsrekorde ${europeStationCurrentYear()}`;
  }else if(mode==="recordChase"){
    if(extremeLabel)extremeLabel.textContent="≤ 1 °C am Rekord";if(extremeEl)extremeEl.textContent=nearRecordCount.toLocaleString("de-DE");if(extremeDetail)extremeDetail.textContent=`am ${europeStationMmddLabel(mmdd)} · inkl. Rekorde`;
  }else{
    if(extremeLabel)extremeLabel.textContent=param==="tmin"?"Tiefstes Minimum":"Höchstes Maximum";if(extremeEl)extremeEl.textContent=extreme===null?"–":europeStationFormatTemp(extreme);if(extremeDetail)extremeDetail.textContent=extremeStation?.name||"–";
  }
  document.getElementById("europeStationNewRecords").textContent=newCount.toLocaleString("de-DE");document.getElementById("europeStationNewRecordsDetail").textContent=mode==="newCurrent"?`Rekordtage ${europeStationCurrentYear()}`:`sichtbare neue Rekorde ${europeStationCurrentYear()}`;
  const currentLabel=document.getElementById("europeStationCurrentExtremeLabel"),currentEl=document.getElementById("europeStationCurrentExtreme"),currentDetail=document.getElementById("europeStationCurrentExtremeDetail");
  if(mode==="calendar"||mode==="recordChase"){
    if(currentLabel)currentLabel.textContent=`${europeStationCurrentYear()}-${param==="tmin"?"TMIN":"TMAX"}`;if(currentEl)currentEl.textContent=currentExtreme===null?"–":europeStationFormatTemp(currentExtreme);if(currentDetail)currentDetail.textContent=currentExtremeStation?`${currentExtremeStation.name} · ${europeStationMmddLabel(mmdd)}`:"noch kein Wert für diesen Tag";
  }else if(mode==="newCurrent"){
    const countriesWithRecords=europeStationCountryRecordCounts(rows,mode).length;if(currentLabel)currentLabel.textContent="Länder mit Rekord";if(currentEl)currentEl.textContent=countriesWithRecords.toLocaleString("de-DE");if(currentDetail)currentDetail.textContent=`mind. ein neuer Rekord ${europeStationCurrentYear()}`;
  }else{
    if(currentLabel)currentLabel.textContent="Länder";if(currentEl)currentEl.textContent=visibleCountries.size.toLocaleString("de-DE");if(currentDetail)currentDetail.textContent="im aktuellen Filter";
  }
  europeStationUpdateLegend(param,mode);renderEuropeStationRanking(rows,param,mode,mmdd);
  if((country||search)&&bounds.length){if(bounds.length===1)europeStationMap.flyTo(bounds[0],8,{duration:.4});else europeStationMap.fitBounds(L.latLngBounds(bounds).pad(.08),{maxZoom:7});}
  const modeText=mode==="absolute"?"absolute Rekorde":mode==="calendar"?`Kalendertag ${europeStationMmddLabel(mmdd)}`:mode==="recordChase"?`Rekordjagd ${europeStationMmddLabel(mmdd)}`:`neue Rekorde ${europeStationCurrentYear()}`;
  setEuropeStationStatus(`${shown.toLocaleString("de-DE")} Stationen · ${param==="tmin"?"TMIN":"TMAX"} · ${modeText}${activeOnly?" · nur aktive Stationen":""}${search?` · Suche „${document.getElementById("europeStationSearch")?.value||""}“`:""} · Ranking und Punkte sind anklickbar`,"ready");
}
function initEuropeStationControls(){
  const param=document.getElementById("europeStationParameter"),mode=document.getElementById("europeStationMode"),country=document.getElementById("europeStationCountry"),years=document.getElementById("europeStationMinYears"),activeOnly=document.getElementById("europeStationActiveOnly"),date=document.getElementById("europeStationDate"),search=document.getElementById("europeStationSearch"),toggle=document.getElementById("europeStationRankingToggle"),body=document.getElementById("europeStationRankingBody");
  const today=new Date(),yyyy=europeStationCurrentYear();if(date&&!date.value){const mm=String(today.getMonth()+1).padStart(2,"0"),dd=String(today.getDate()).padStart(2,"0");date.value=`${yyyy}-${mm}-${dd}`;}
  if(param?.dataset.stationV2Bound==="1")return;
  [param,mode,country,years,activeOnly,date].forEach(el=>el?.addEventListener("change",()=>{if(el===mode)europeStationUpdateControls();renderEuropeStations();}));
  search?.addEventListener("input",()=>{window.clearTimeout(europeStationSearchTimer);europeStationSearchTimer=window.setTimeout(()=>renderEuropeStations(),140);});
  search?.addEventListener("keydown",event=>{if(event.key!=="Enter")return;event.preventDefault();renderEuropeStations().then(()=>{if(europeStationLastRows.length)europeStationFocusById(europeStationLastRows[0].station.id);});});
  toggle?.addEventListener("click",()=>{if(!body)return;body.hidden=!body.hidden;toggle.textContent=body.hidden?"Ausklappen":"Einklappen";toggle.setAttribute("aria-expanded",body.hidden?"false":"true");});
  if(param)param.dataset.stationV2Bound="1";europeStationUpdateControls();
}
function populateEuropeStationCountries(){
  const select=document.getElementById("europeStationCountry");if(!select||!europeStationData)return;const current=select.value;const countries=[...new Set((europeStationData.stations||[]).map(s=>s.country).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"de"));select.innerHTML='<option value="">Alle Länder</option>'+countries.map(c=>`<option value="${europeStationEscapeHtml(String(c))}">${europeStationEscapeHtml(String(c))}</option>`).join("");if(countries.includes(current))select.value=current;
}
async function preloadEuropeStationData(){
  if(europeStationLoaded&&europeStationData)return europeStationData;
  if(europeStationLoading)return europeStationLoading;
  europeStationLoading=(async()=>{
    try{
      const response=await fetch(`${EUROPE_STATION_DATA_URL}?v=${Date.now()}`,{cache:"no-store"});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const payload=await response.json();
      if(![1,2,3,4,5].includes(Number(payload?.payload_version)))console.warn("Unerwartete Stations-Payload-Version",payload?.payload_version);
      europeStationData=payload;
      populateEuropeStationCountries();
      initEuropeStationControls();
      europeStationLoaded=true;
      return payload;
    }catch(error){
      console.warn("Europa-Stationsdaten konnten beim Seitenstart nicht vorgeladen werden",error);
      setEuropeStationStatus("Stationsdaten fehlen oder konnten nicht geladen werden. Bitte den Europa-Workflow prüfen.","warn");
      throw error;
    }finally{
      europeStationLoading=null;
    }
  })();
  return europeStationLoading;
}
async function ensureEuropeStationMap(){
  try{
    if(!window.L && typeof window.ensureEuropeStationLeaflet==="function")
      await window.ensureEuropeStationLeaflet();
  }catch(error){
    console.warn("Europa-Stationskarte: Leaflet konnte nicht geladen werden",error);
    setEuropeStationStatus("Kartenbibliothek derzeit nicht erreichbar. Karte erneut öffnen oder später erneut versuchen.","warn");
    return;
  }
  initEuropeStationMap();
  if(!europeStationMap){
    setEuropeStationStatus("Kartenbibliothek noch nicht bereit. Bitte die Europa-Stationen erneut öffnen.","warn");
    return;
  }
  window.setTimeout(()=>europeStationMap?.invalidateSize(),80);
  if(europeStationLoaded){renderEuropeStations();return;}
  if(europeStationLoading){await europeStationLoading;if(europeStationLoaded)await renderEuropeStations();return;}
  europeStationLoading=(async()=>{
    try{
      const response=await fetch(`${EUROPE_STATION_DATA_URL}?v=${Date.now()}`,{cache:"no-store"});if(!response.ok)throw new Error(`HTTP ${response.status}`);const payload=await response.json();if(![1,2,3,4,5].includes(Number(payload?.payload_version)))console.warn("Unerwartete Stations-Payload-Version",payload?.payload_version);europeStationData=payload;populateEuropeStationCountries();initEuropeStationControls();europeStationLoaded=true;await renderEuropeStations();
    }catch(error){console.warn("Europa-Stationskarte: Daten nicht verfügbar",error);setEuropeStationStatus("Stationsdaten fehlen oder konnten nicht geladen werden. Bitte den Europa-Workflow prüfen.","warn");}
    finally{europeStationLoading=null;}
  })();return europeStationLoading;
}

