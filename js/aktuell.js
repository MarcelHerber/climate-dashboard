/* aktuell.js – Aktuell / DWD 10-Minuten
   Aus index.html ausgelagert (Schritt 2c). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= AKTUELL / DWD 10-MINUTEN =================
function currentNum(value,unit="",digits=1){
  if(value===null || value===undefined || value==="") return "–";
  const n=Number(value);
  if(!Number.isFinite(n)) return "–";
  return `${n.toLocaleString("de-DE",{minimumFractionDigits:digits,maximumFractionDigits:digits})}${unit?` ${unit}`:""}`;
}
function currentDateTime(value){
  if(!value) return "–";
  const date=new Date(value);
  return Number.isNaN(date.getTime())?String(value):date.toLocaleString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"});
}
function currentAgeMinutes(value){
  if(!value) return null;
  const ms=Date.now()-new Date(value).getTime();
  return Number.isFinite(ms)?Math.max(0,Math.round(ms/60000)):null;
}
async function currentFetchJson(path){
  const separator=path.includes("?")?"&":"?";
  const response=await fetch(`${CURRENT_LIVE_BASE}/${path}${separator}t=${Date.now()}`,{cache:"no-store"});
  if(!response.ok) throw new Error(`Live-Datei ${path} nicht erreichbar (${response.status})`);
  return response.json();
}
async function currentFetchFastJson(path){
  const separator=path.includes("?")?"&":"?";
  const response=await fetch(`${CURRENT_FAST_LIVE_BASE}/${path}${separator}t=${Date.now()}`,{cache:"no-store"});
  if(!response.ok) throw new Error(`Fast-Live-Datei ${path} nicht erreichbar (${response.status})`);
  return response.json();
}
function currentHasNumber(v){return v!==null&&v!==undefined&&v!==""&&Number.isFinite(Number(v));}
function currentDayIso(value){
  const date=new Date(value);
  return Number.isFinite(date.getTime())?date.toLocaleDateString("sv-SE",{timeZone:"Europe/Berlin"}):null;
}
function currentDayValue(s,key){
  if(!s||s.today_date&&s.today_date!==currentDayIso(Date.now()))return null;
  // Schema 4 only estimates temperature extremes from momentary TT_10.
  if((key==="today_max_c"||key==="today_min_c")&&currentLiveIndex?.schema_version<5)return null;
  return currentHasNumber(s[key])?Number(s[key]):null;
}
function currentNewerIso(a,b){
  if(!a) return b||null;
  if(!b) return a||null;
  return new Date(a).getTime()>=new Date(b).getTime()?a:b;
}
function currentFastStation(stationId){
  return currentFastByStation.get(String(stationId||''))||null;
}
function currentMergeFastIntoIndex(base,fast){
  const merged={...base};
  merged._cdc_latest_measurement_utc=base.latest_measurement_utc||null;
  merged._cdc_generated_at_utc=base.generated_at_utc||null;
  if(!fast || !Array.isArray(fast.stations)){
    merged.fast_live_available=false;
    return merged;
  }
  currentFastByStation=new Map(fast.stations.map(item=>[String(item.station_id||''),item]));
  merged.stations=(base.stations||[]).map(station=>{
    const out={...station};
    const f=currentFastStation(station.id);
    if(!f) return out;
    out.fast_live=true;
    out.fast_live_time_utc=f.time_utc||null;
    out.fast_live_wmo_id=f.wmo_id||null;
    out.cdc_latest_utc=station.latest_utc||null;
    out.cdc_latest_local=station.latest_local||null;
    const fastStamp=Date.parse(f.time_utc||"");
    const sourceIsOlder=(reference)=>{
      const base=Date.parse(reference||"");
      return !Number.isFinite(fastStamp)||(Number.isFinite(base)&&fastStamp<=base);
    };
    const tempNew=!sourceIsOlder(out.temperature_utc||out.latest_utc);
    const windNew=!sourceIsOlder(out.wind_utc||out.latest_utc);
    const gustNew=!sourceIsOlder(out.gust_utc||out.latest_utc);
    out.fast_live_temperature=tempNew&&currentHasNumber(f.temperature_c);
    out.fast_live_humidity=tempNew&&currentHasNumber(f.humidity_pct);
    out.fast_live_wind=windNew&&currentHasNumber(f.wind_speed_ms);
    out.fast_live_gust=gustNew&&currentHasNumber(f.gust_speed_ms);
    // Fast SYNOP only updates latest measurements, never TX_10/TN_10/FX_10 day peaks.
    if(out.fast_live_temperature)out.temperature_c=Number(f.temperature_c);
    if(tempNew&&currentHasNumber(f.dewpoint_c))out.dewpoint_c=Number(f.dewpoint_c);
    if(out.fast_live_humidity)out.humidity_pct=Number(f.humidity_pct);
    if(tempNew&&currentHasNumber(f.pressure_hpa))out.pressure_hpa=Number(f.pressure_hpa);
    if(out.fast_live_wind){
      out.wind_speed_ms=Number(f.wind_speed_ms);
      if(currentHasNumber(f.wind_direction_deg))out.wind_direction_deg=Number(f.wind_direction_deg);
    }
    if(out.fast_live_gust)out.gust_speed_ms=Number(f.gust_speed_ms);
    const mergedLatest=currentNewerIso(out.latest_utc,f.time_utc);
    if(mergedLatest===f.time_utc){out.latest_utc=f.time_utc;out.latest_local=null;}
    else out.latest_utc=mergedLatest;
    return out;
  });
  merged.fast_live_available=true;
  merged.fast_live_station_count=fast.station_count||fast.stations.length;
  merged.fast_live_latest_measurement_utc=fast.latest_measurement_utc||null;
  merged.fast_live_generated_at_utc=fast.generated_at_utc||null;
  merged.latest_measurement_utc=currentNewerIso(base.latest_measurement_utc,fast.latest_measurement_utc);
  return merged;
}
function currentMergeFastProfile(profile){
  const stationId=profile?.station?.id;
  const fast=currentFastStation(stationId);
  if(!fast) return profile;
  const merged={...profile,latest:{...(profile.latest||{})},today:{...(profile.today||{})},_fast_live:fast};
  const latest=merged.latest,today=merged.today;
  const fastTime=fast.time_utc||null;
  const baseTemperatureTime=latest.temperature_utc||latest.temperature_local||latest.utc||latest.local;
  const baseWindTime=latest.wind_utc||latest.wind_local||latest.utc||latest.local;
  const baseGustTime=latest.gust_utc||latest.gust_local||latest.utc||latest.local;
  const isNewer=(cdcTime)=>{
    if(!fastTime) return false;
    if(!cdcTime) return true;
    return new Date(fastTime).getTime()>new Date(cdcTime).getTime();
  };
  if(currentHasNumber(fast.temperature_c) && isNewer(baseTemperatureTime)){
    latest.temperature_c=Number(fast.temperature_c);latest.temperature_utc=fastTime;latest.temperature_local=null;latest.temperature_source='synop';
  }
  if(currentHasNumber(fast.dewpoint_c) && isNewer(baseTemperatureTime)){latest.dewpoint_c=Number(fast.dewpoint_c);latest.dewpoint_source='synop';}
  if(currentHasNumber(fast.humidity_pct) && isNewer(baseTemperatureTime)){latest.humidity_pct=Number(fast.humidity_pct);latest.humidity_source='synop';}
  if(currentHasNumber(fast.pressure_hpa) && isNewer(baseTemperatureTime)){latest.pressure_hpa=Number(fast.pressure_hpa);latest.pressure_source='synop';}
  if(currentHasNumber(fast.wind_speed_ms) && isNewer(baseWindTime)){
    latest.wind_speed_ms=Number(fast.wind_speed_ms);latest.wind_direction_deg=currentHasNumber(fast.wind_direction_deg)?Number(fast.wind_direction_deg):latest.wind_direction_deg;latest.wind_utc=fastTime;latest.wind_local=null;latest.wind_source='synop';
  }
  if(currentHasNumber(fast.gust_speed_ms) && isNewer(baseGustTime)){
    latest.gust_speed_ms=Number(fast.gust_speed_ms);latest.gust_direction_deg=currentHasNumber(fast.gust_direction_deg)?Number(fast.gust_direction_deg):latest.gust_direction_deg;latest.gust_utc=fastTime;latest.gust_local=null;latest.gust_source='synop';
  }
  latest.utc=currentNewerIso(latest.utc,fastTime);
  // Daily extrema remain from original DWD CDC intervals, not SYNOP snapshots.
  return merged;
}
const CURRENT_GERMAN_STATES=["Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen-Anhalt","Sachsen","Schleswig-Holstein","Thüringen"];
function currentNormalizeStationMeta(station){
  const normalized={...station};
  let name=String(normalized.name||"").trim().replace(/\s+Frei$/i,"").trim();
  let state=String(normalized.state||"").trim().replace(/^Frei$/i,"").trim();
  if(!state){
    const match=[...CURRENT_GERMAN_STATES].sort((a,b)=>b.length-a.length).find(candidate=>name===candidate||name.endsWith(` ${candidate}`));
    if(match){
      state=match;
      name=name.slice(0,-match.length).trim();
    }
  }
  normalized.name=name||normalized.name||`Station ${normalized.id||""}`;
  normalized.state=state;
  return normalized;
}
function currentTimeOnly(value){
  if(!value) return "–";
  const date=new Date(value);
  return Number.isNaN(date.getTime())?String(value):date.toLocaleTimeString("de-DE",{hour:"2-digit",minute:"2-digit"});
}
function currentOverviewStations(){
  if(!currentLiveIndex) return [];
  const state=document.getElementById("currentStateSelect")?.value||"";
  return (currentLiveIndex.stations||[]).filter(station=>!state || station.state===state);
}
function currentOverviewMax(stations,getter){
  let best=null;
  for(const station of stations){
    const raw=getter(station);
    if(!currentHasNumber(raw))continue;
    const value=Number(raw);
    if(!best || value>best.value) best={station,value};
  }
  return best;
}
function currentOverviewStationDetail(item){
  if(!item) return "keine aktuellen Werte";
  const s=item.station;
  return `${s.name||"Station"} (${s.id||"–"})${s.state?` · ${s.state}`:""}`;
}
function renderCurrentOverview(){
  if(!currentLiveIndex) return;
  const stations=currentOverviewStations();
  const state=document.getElementById("currentStateSelect")?.value||"";
  const title=document.getElementById("currentOverviewTitle");
  const subtitle=document.getElementById("currentOverviewSubtitle");
  if(title) title.textContent=`${state||"Deutschland"} aktuell`;
  if(subtitle) subtitle.textContent=`${stations.length.toLocaleString("de-DE")} Live-Temperaturstationen · Kenntage zählen Stationen, die die Schwelle heute bereits erreicht haben.`;

  const warmest=currentOverviewMax(stations,s=>s.temperature_c);
  const tmax=currentOverviewMax(stations,s=>currentDayValue(s,"today_max_c"));
  const gust=currentOverviewMax(stations,s=>currentDayValue(s,"today_max_gust_ms"));
  const rain=currentOverviewMax(stations,s=>currentDayValue(s,"today_precip_sum_mm"));

  const set=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
  set("currentOverviewWarmest",warmest?`${warmest.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`:"–");
  set("currentOverviewWarmestDetail",currentOverviewStationDetail(warmest));
  set("currentOverviewTmax",tmax?`${tmax.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`:"–");
  set("currentOverviewTmaxDetail",currentOverviewStationDetail(tmax));
  set("currentOverviewGust",gust?`${gust.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} m/s`:"–");
  set("currentOverviewGustDetail",currentOverviewStationDetail(gust));
  set("currentOverviewRain",rain?`${rain.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} mm`:"–");
  set("currentOverviewRainDetail",currentOverviewStationDetail(rain));

  const count=threshold=>stations.reduce((sum,s)=>{
    const value=currentDayValue(s,"today_max_c");
    return sum+(value!==null&&value>=threshold?1:0);
  },0);
  set("currentOverviewSummer",count(25).toLocaleString("de-DE"));
  set("currentOverviewHot",count(30).toLocaleString("de-DE"));
  set("currentOverviewDesert",count(35).toLocaleString("de-DE"));
  set("currentOverviewForty",count(40).toLocaleString("de-DE"));
}
function currentFilteredStations(){
  if(!currentLiveIndex) return [];
  const state=document.getElementById("currentStateSelect")?.value||"";
  const search=(document.getElementById("currentStationSearch")?.value||"").trim().toLocaleLowerCase("de-DE");
  return (currentLiveIndex.stations||[]).filter(station=>{
    if(state && station.state!==state) return false;
    if(!search) return true;
    return `${station.name||""} ${station.id||""} ${station.state||""}`.toLocaleLowerCase("de-DE").includes(search);
  });
}
function populateCurrentStations(preserve=true){
  const select=document.getElementById("currentStationSelect");
  if(!select || !currentLiveIndex) return;
  const previous=preserve?select.value:"";
  const rows=currentFilteredStations();
  select.innerHTML="";
  rows.forEach(station=>{
    const option=document.createElement("option");
    option.value=station.id;
    option.textContent=`${station.name||"Station"} (${station.id})${station.state?` · ${station.state}`:""}`;
    select.appendChild(option);
  });
  const saved=dashboardState.currentStationSelect;
  if(previous && rows.some(station=>station.id===previous)) select.value=previous;
  else if(saved && rows.some(station=>station.id===saved)) select.value=saved;
  if(!select.value && rows[0]) select.value=rows[0].id;
  if(select.value) loadCurrentStation(select.value);
  else renderCurrentEmpty("Keine Station entspricht dem Filter.");
  renderCurrentOverview();
  renderCurrentMap();
}
function currentMapMetricSpec(metric){
  const tempColors=["#313695","#4575b4","#74add1","#abd9e9","#fee090","#fdae61","#f46d43","#d73027"];
  const windColors=["#f1f5f9","#cfe8f3","#9fd0e0","#6fb6ca","#3f98b2","#1f6f93","#0d4f6b","#08354a"];
  const gustColors=["#fff4dd","#ffe0a6","#ffc46d","#f99e3a","#eb7a12","#cb5a04","#a24102","#7f3200"];
  switch(metric){
    case "today_temp_max":return {label:"Temperatur-Tagesmaximum",unit:"°C",digits:1,getter:s=>currentDayValue(s,"today_max_c"),breaks:[-5,0,10,20,25,30,35],colors:tempColors};
    case "today_temp_min":return {label:"Temperatur-Tagesminimum",unit:"°C",digits:1,getter:s=>currentDayValue(s,"today_min_c"),breaks:[-15,-10,-5,0,5,10,15],colors:tempColors};
    case "today_wind":return {label:"Wind-Tagesmaximum",unit:"m/s",digits:1,getter:s=>currentDayValue(s,"today_max_wind_ms"),breaks:[0,2,4,6,8,12,16],colors:windColors};
    case "today_gust":return {label:"Böen-Tagesmaximum",unit:"m/s",digits:1,getter:s=>currentDayValue(s,"today_max_gust_ms"),breaks:[0,4,8,12,16,20,25],colors:gustColors};
    case "today_humidity":return {label:"Tagesmaximum Feuchte",unit:"%",digits:0,getter:s=>currentDayValue(s,"today_max_humidity_pct"),breaks:[20,30,40,50,60,70,85],colors:["#fff7fb","#ece7f2","#d0d1e6","#a6bddb","#74a9cf","#3690c0","#0570b0","#034e7b"]};
    case "today_dewpoint":return {label:"Tagesmaximum Taupunkt",unit:"°C",digits:1,getter:s=>currentDayValue(s,"today_max_dewpoint_c"),breaks:[-10,-5,0,5,10,15,20],colors:tempColors};
    case "today_pressure":return {label:"Tagesmaximum Luftdruck",unit:"hPa",digits:1,getter:s=>currentDayValue(s,"today_max_pressure_hpa"),breaks:[950,970,990,1000,1010,1020,1035],colors:windColors};
    case "today_ground_temp":return {label:"Tagesmaximum 5-cm-Temperatur",unit:"°C",digits:1,getter:s=>currentDayValue(s,"today_max_ground_temp_c"),breaks:[-5,0,10,20,25,30,35],colors:tempColors};
    case "wind":return {label:"Wind",unit:"m/s",digits:1,getter:s=>s.wind_speed_ms,breaks:[0,2,4,6,8,12,16],colors:["#f1f5f9","#cfe8f3","#9fd0e0","#6fb6ca","#3f98b2","#1f6f93","#0d4f6b","#08354a"]};
    case "gust":return {label:"Böe",unit:"m/s",digits:1,getter:s=>s.gust_speed_ms,breaks:[0,4,8,12,16,20,25],colors:["#fff4dd","#ffe0a6","#ffc46d","#f99e3a","#eb7a12","#cb5a04","#a24102","#7f3200"]};
    case "precip_10min":return {label:"Niederschlag letzte 10 Min.",unit:"mm",digits:1,getter:s=>s.precip_10min_mm,breaks:[0,0.1,0.5,1,2,5,10],colors:["#f7fbff","#deebf7","#c6dbef","#9ecae1","#6baed6","#3182bd","#08519c","#08306b"]};
    case "today_precip":return {label:"Niederschlag heute",unit:"mm",digits:1,getter:s=>currentDayValue(s,"today_precip_sum_mm"),breaks:[0,1,5,10,20,40,60],colors:["#f7fbff","#deebf7","#c6dbef","#9ecae1","#6baed6","#3182bd","#08519c","#08306b"]};
    case "humidity":return {label:"Relative Feuchte",unit:"%",digits:0,getter:s=>s.humidity_pct,breaks:[20,30,40,50,60,70,85],colors:["#fff7fb","#ece7f2","#d0d1e6","#a6bddb","#74a9cf","#3690c0","#0570b0","#034e7b"]};
    case "temperature":
    default:return {label:"Temperatur",unit:"°C",digits:1,getter:s=>s.temperature_c,breaks:[-5,0,10,20,25,30,35],colors:["#313695","#4575b4","#74add1","#abd9e9","#fee090","#fdae61","#f46d43","#d73027"]};
  }
}
function currentMapMetricValue(station,metric){
  const spec=currentMapMetricSpec(metric);
  const value=spec.getter(station);
  return currentHasNumber(value)?Number(value):null;
}
function currentMapColor(metric,value){
  const spec=currentMapMetricSpec(metric);
  if(!Number.isFinite(value)) return '#cfd8dc';
  let index=0;
  while(index<spec.breaks.length && value>=spec.breaks[index]) index++;
  return spec.colors[Math.min(index,spec.colors.length-1)];
}
function currentMapLegendHtml(metric){
  const spec=currentMapMetricSpec(metric);
  const labels=[];
  const fmt=(n)=>Number(n).toLocaleString('de-DE',{maximumFractionDigits:spec.digits,minimumFractionDigits:spec.digits});
  for(let i=0;i<spec.colors.length;i++){
    let label='';
    if(i===0) label=`< ${fmt(spec.breaks[0])} ${spec.unit}`;
    else if(i===spec.colors.length-1) label=`≥ ${fmt(spec.breaks[spec.breaks.length-1])} ${spec.unit}`;
    else label=`${fmt(spec.breaks[i-1])}–${fmt(spec.breaks[i])} ${spec.unit}`;
    labels.push(`<span class="current-map-legend-item"><span class="current-map-legend-swatch" style="background:${spec.colors[i]}"></span>${label}</span>`);
  }
  return labels.join('');
}
function currentMapDisplayValue(metric,value){
  const spec=currentMapMetricSpec(metric);
  return Number(value).toLocaleString('de-DE',{minimumFractionDigits:spec.digits,maximumFractionDigits:spec.digits});
}
function currentMapMetricTime(station,metric=null){
  if(!station) return null;
  // Daily extrema and totals are CDC-derived, even when fast SYNOP is newer.
  if(String(metric||"").startsWith("today_"))
    return station.cdc_latest_utc||station.temperature_utc||station.latest_utc||station.latest_local||null;
  if(metric==='precip_10min' || metric==='today_precip') return station.cdc_latest_utc||station.cdc_latest_local||station.latest_utc||station.latest_local||null;
  if(metric==='temperature' && station.fast_live_temperature) return station.fast_live_time_utc||station.latest_utc||station.latest_local||null;
  if(metric==='humidity' && station.fast_live_humidity) return station.fast_live_time_utc||station.latest_utc||station.latest_local||null;
  if(metric==='wind' && station.fast_live_wind) return station.fast_live_time_utc||station.latest_utc||station.latest_local||null;
  if(metric==='gust' && station.fast_live_gust) return station.fast_live_time_utc||station.latest_utc||station.latest_local||null;
  return station.latest_utc||station.latest_local||null;
}
function currentMapMetricIsFast(station,metric){
  if(metric==='temperature') return Boolean(station?.fast_live_temperature);
  if(metric==='humidity') return Boolean(station?.fast_live_humidity);
  if(metric==='wind') return Boolean(station?.fast_live_wind);
  if(metric==='gust') return Boolean(station?.fast_live_gust);
  return false;
}
function currentMapAgeMinutes(station,metric=null){
  const stamp=currentMapMetricTime(station,metric);
  if(!stamp) return null;
  const age=(Date.now()-new Date(stamp).getTime())/60000;
  return Number.isFinite(age)?Math.max(0,Math.round(age)):null;
}
function currentMapAgeText(station,metric=null){
  const age=currentMapAgeMinutes(station,metric);
  if(age===null) return 'Datenalter unbekannt';
  if(age<=1) return 'gerade aktualisiert';
  return `${age} min alt`;
}
function currentMapHexRgb(hex){
  const clean=String(hex||'').replace('#','');
  if(!/^[0-9a-fA-F]{6}$/.test(clean)) return {r:255,g:255,b:255};
  return {r:parseInt(clean.slice(0,2),16),g:parseInt(clean.slice(2,4),16),b:parseInt(clean.slice(4,6),16)};
}
function currentMapContrastText(hex){
  const {r,g,b}=currentMapHexRgb(hex);
  const luminance=(0.299*r+0.587*g+0.114*b)/255;
  return luminance>0.61?'#111827':'#ffffff';
}
function currentMapDarken(hex,factor=.68){
  const {r,g,b}=currentMapHexRgb(hex);
  const part=n=>Math.max(0,Math.min(255,Math.round(n*factor))).toString(16).padStart(2,'0');
  return `#${part(r)}${part(g)}${part(b)}`;
}
function currentMapLabelIcon(metric,value,selected=false,stale=false){
  const color=currentMapColor(metric,value);
  const label=currentMapDisplayValue(metric,value);
  const background=stale?'#eceff1':color;
  const textColor=stale?'#667078':currentMapContrastText(color);
  const borderColor=stale?'#7b858d':currentMapDarken(color);
  return L.divIcon({
    className:'current-map-label-icon',
    html:`<div class="current-map-label-wrap" style="--label-color:${color};--label-bg:${background};--label-text:${textColor};--label-border:${borderColor}"><div class="current-map-label${selected?' selected':''}${stale?' stale':''}">${label}</div><div class="current-map-dot${stale?' stale':''}"></div></div>`,
    iconSize:[50,28],
    iconAnchor:[25,28],
    popupAnchor:[0,-25]
  });
}
function currentMapPopupHtml(station,metric,value){
  const spec=currentMapMetricSpec(metric);
  const valueLabel=`${currentMapDisplayValue(metric,value)} ${spec.unit}`;
  const age=currentMapAgeMinutes(station,metric);
  const ageStyle=age!==null&&age>60?'color:#6b7280;font-weight:700':'';
  const fast=currentMapMetricIsFast(station,metric);
  const stamp=currentMapMetricTime(station,metric);
  return `<strong>${station.name||'Station'} (${station.id})</strong><br>${station.state||''}${Number.isFinite(Number(station.elevation_m))?` · ${Number(station.elevation_m).toLocaleString('de-DE')} m`:''}<br><strong>${spec.label}:</strong> ${valueLabel}${fast?' <strong style="color:#0a806a">· Fast Live</strong>':''}<br><span>Messzeitpunkt: ${currentDateTime(stamp)}</span><br><span style="${ageStyle}">Datenalter: ${currentMapAgeText(station,metric)}</span>`;
}
function currentMapKeepLabel(point,kept,minDistance){
  return !kept.some(other=>Math.hypot(point.x-other.x,point.y-other.y)<minDistance);
}
function currentMapClimateDayThreshold(){
  const value=document.getElementById('currentMapClimateDaySelect')?.value||'all';
  if(value==='all') return null;
  const threshold=Number(value);
  return Number.isFinite(threshold)?threshold:null;
}
function currentMapClimateDayLabel(){
  const threshold=currentMapClimateDayThreshold();
  if(threshold===null) return 'alle Stationen';
  if(threshold===20) return 'Warmer Tag · Tmax ≥ 20 °C';
  if(threshold===25) return 'Sommertag · Tmax ≥ 25 °C';
  if(threshold===30) return 'Hitzetag · Tmax ≥ 30 °C';
  if(threshold===35) return 'Wüstentag · Tmax ≥ 35 °C';
  if(threshold===40) return '40-Grad-Tag · Tmax ≥ 40 °C';
  return `Tmax ≥ ${threshold.toLocaleString('de-DE')} °C`;
}
function currentMapBuildCandidates(metric){
  const threshold=currentMapClimateDayThreshold();
  return currentFilteredStations()
    .filter(station=>Number.isFinite(Number(station.lat))&&Number.isFinite(Number(station.lon)))
    .filter(station=>threshold===null || (currentDayValue(station,"today_max_c")!==null && currentDayValue(station,"today_max_c")>=threshold))
    .map(station=>({station,value:currentMapMetricValue(station,metric)}))
    .filter(item=>item.value!==null);
}
function currentRankingTitle(metric){
  if(String(metric).startsWith("today_"))return currentMapMetricSpec(metric).label;
  switch(metric){
    case "wind":return "Stärkster Wind aktuell";
    case "gust":return "Stärkste Böen aktuell";
    case "precip_10min":return "Höchster 10-Minuten-Niederschlag aktuell";
    case "today_precip":return "Höchster Tagesniederschlag heute";
    case "humidity":return "Höchste relative Feuchte aktuell";
    case "temperature":
    default:return "Höchste Temperaturen aktuell";
  }
}
function renderCurrentRanking(metric,candidates){
  const title=document.getElementById('currentRankingTitle');
  const subtitle=document.getElementById('currentRankingSubtitle');
  const tbody=document.querySelector('#currentRankingTable tbody');
  if(!tbody) return;
  const spec=currentMapMetricSpec(metric);
  const selectedId=document.getElementById('currentStationSelect')?.value||'';
  const ranked=[...(candidates||[])].sort((a,b)=>b.value-a.value).slice(0,15);
  if(title) title.textContent=currentRankingTitle(metric);
  const state=document.getElementById('currentStateSelect')?.value||'';
  const climateFilter=currentMapClimateDayThreshold();
  const filterText=climateFilter===null?'':` · ${currentMapClimateDayLabel()}`;
  if(subtitle) subtitle.textContent=`Top ${ranked.length}${state?` in ${state}`:' in Deutschland'}${filterText} · Klick auf eine Zeile öffnet die Station.`;
  if(!ranked.length){
    tbody.innerHTML='<tr><td colspan="5">Für den gewählten Parameter sind keine aktuellen Werte verfügbar.</td></tr>';
    return;
  }
  tbody.innerHTML=ranked.map((item,index)=>{
    const s=item.station;
    const value=`${currentMapDisplayValue(metric,item.value)} ${spec.unit}`;
    const time=currentTimeOnly(currentMapMetricTime(s,metric));
    const stale=currentMapAgeMinutes(s,metric)>60;
    return `<tr data-station-id="${s.id}" class="${s.id===selectedId?'selected':''}"${stale?' style="opacity:.67"':''}><td class="current-ranking-rank">${index+1}</td><td class="current-ranking-station"><strong>${s.name||'Station'}</strong> <span class="note">(${s.id})</span></td><td class="current-ranking-state">${s.state||'–'}</td><td class="current-ranking-value" style="color:${stale?'#6b7280':currentMapColor(metric,item.value)}">${value}</td><td class="current-ranking-time">${time}${stale?' · alt':''}</td></tr>`;
  }).join('');
  tbody.querySelectorAll('tr[data-station-id]').forEach(row=>row.addEventListener('click',()=>{
    const stationId=row.dataset.stationId;
    const select=document.getElementById('currentStationSelect');
    if(select && stationId){
      select.value=stationId;
      persistDashboardState('currentStationSelect',stationId);
      loadCurrentStation(stationId);
    }
  }));
}
function currentMapFallbackBoundary(){
  return [[47.28,10.45],[47.53,7.60],[48.15,7.58],[49.02,6.05],[50.15,6.00],[51.05,5.88],[52.15,6.72],[53.55,7.08],[54.88,8.45],[54.82,10.15],[54.55,11.55],[54.35,12.75],[53.85,14.35],[52.65,14.72],[51.35,15.02],[50.65,14.75],[50.18,12.35],[49.02,13.82],[48.56,13.82],[47.62,12.85],[47.28,10.45]];
}
function currentMapBoundaryStyle(feature){
  const selectedState=document.getElementById('currentStateSelect')?.value||'';
  const name=feature?.properties?.name||'';
  const selected=selectedState&&name===selectedState;
  return {color:selected?'#50616d':'#8d9aa3',weight:selected?2.1:1.15,fillColor:selected?'#e3eaee':'#f0f3f5',fillOpacity:selected?.58:.72};
}
async function currentMapEnsureBoundary(){
  if(currentLiveMapBoundaryData) return currentLiveMapBoundaryData;
  if(currentLiveMapBoundaryPromise) return currentLiveMapBoundaryPromise;
  currentLiveMapBoundaryPromise=fetch(CURRENT_MAP_BOUNDARY_URL,{cache:'force-cache'}).then(response=>{
    if(!response.ok) throw new Error(`Grenzdatei HTTP ${response.status}`);
    return response.json();
  }).then(data=>{currentLiveMapBoundaryData=data;return data;}).catch(error=>{
    console.warn('Bundeslandgrenzen konnten nicht geladen werden:',error);
    return null;
  }).finally(()=>{currentLiveMapBoundaryPromise=null;});
  return currentLiveMapBoundaryPromise;
}
function currentMapRenderBoundary(){
  if(!currentLiveMap) return;
  if(currentLiveMapBoundaryLayer){currentLiveMap.removeLayer(currentLiveMapBoundaryLayer);currentLiveMapBoundaryLayer=null;}
  if(currentLiveMapBoundaryData){
    currentLiveMapBoundaryLayer=L.geoJSON(currentLiveMapBoundaryData,{style:currentMapBoundaryStyle,interactive:false}).addTo(currentLiveMap);
    currentLiveMapBoundaryLayer.bringToBack();
    return;
  }
  currentLiveMapBoundaryLayer=L.polygon(currentMapFallbackBoundary(),{color:'#8d9aa3',weight:1.4,fillColor:'#f0f3f5',fillOpacity:.78,interactive:false}).addTo(currentLiveMap);
  currentLiveMapBoundaryLayer.bringToBack();
}
function currentMapFitView(candidates){
  if(!currentLiveMap) return;
  const selectedState=document.getElementById('currentStateSelect')?.value||'';
  if(selectedState&&currentLiveMapBoundaryData){
    const feature=currentLiveMapBoundaryData.features?.find(item=>item?.properties?.name===selectedState);
    if(feature){
      const temp=L.geoJSON(feature);
      const bounds=temp.getBounds();
      if(bounds.isValid()){currentLiveMap.fitBounds(bounds,{padding:[28,28],maxZoom:8});return;}
    }
  }
  if((document.getElementById('currentStationSearch')?.value||'').trim()&&candidates.length){
    const bounds=L.latLngBounds(candidates.map(item=>[Number(item.station.lat),Number(item.station.lon)]));
    if(bounds.isValid()){currentLiveMap.fitBounds(bounds,{padding:[35,35],maxZoom:8});return;}
  }
  currentLiveMap.setView([51.15,10.45],6,{animate:false});
}
function currentMapUpdateTitle(metric){
  const container=document.getElementById('currentMap');
  if(!container) return;
  let overlay=container.querySelector('.current-map-title-overlay');
  if(!overlay){overlay=document.createElement('div');overlay.className='current-map-title-overlay';container.appendChild(overlay);}
  const spec=currentMapMetricSpec(metric);
  const state=document.getElementById('currentStateSelect')?.value||'Deutschland';
  const latest=currentLiveIndex?.latest_measurement_utc?currentDateTime(currentLiveIndex.latest_measurement_utc):'–';
  const filter=currentMapClimateDayThreshold();
  const filterText=filter===null?'':` · Filter: ${currentMapClimateDayLabel()}`;
  overlay.innerHTML=`<strong>${spec.label} · ${state}</strong><span>DWD 10-Minuten-Livedaten · Stand ${latest}${filterText}</span>`;
}
function renderCurrentMap(){
  const container=document.getElementById('currentMap');
  const legend=document.getElementById('currentMapLegend');
  if(!container) return;
  if(!window.L){container.innerHTML='<div class="current-map-empty">Leaflet konnte nicht geladen werden.</div>';return;}
  const metric=document.getElementById('currentMapMetricSelect')?.value||'temperature';
  const displayMode=document.getElementById('currentMapDisplaySelect')?.value||'labels';
  const candidates=currentMapBuildCandidates(metric);
  if(legend){
    const climateFilter=currentMapClimateDayThreshold();
    const filterBadge=climateFilter===null?'':`<span class="current-map-legend-stale" style="border-style:solid">${currentMapClimateDayLabel()}</span>`;
    legend.innerHTML=currentMapLegendHtml(metric)+'<span class="current-map-legend-stale">älter als 60 min</span>'+filterBadge;
  }
  renderCurrentRanking(metric,candidates);
  if(container.querySelector('.current-map-empty') && currentLiveMap){container.innerHTML=''; currentLiveMap.remove(); currentLiveMap=null; currentLiveMapLayer=null;currentLiveMapBoundaryLayer=null;}
  if(!currentLiveMap){
    container.innerHTML='';
    currentLiveMap=L.map(container,{scrollWheelZoom:false,zoomControl:true,attributionControl:true,minZoom:5,maxZoom:10}).setView([51.15,10.45],6);
    currentLiveMap.attributionControl.setPrefix(false);
    currentLiveMapLayer=L.layerGroup().addTo(currentLiveMap);
    currentMapEnsureBoundary().then(()=>{if(currentLiveMap){currentMapRenderBoundary();currentMapFitView(currentMapBuildCandidates(document.getElementById('currentMapMetricSelect')?.value||'temperature'));}});
  }
  currentMapRenderBoundary();
  currentLiveMapLayer.clearLayers();
  currentMapUpdateTitle(metric);
  if(!candidates.length){
    currentLiveMapLayer.clearLayers();
    return;
  }
  currentMapFitView(candidates);
  currentLiveMap.invalidateSize(false);
  const selectedId=document.getElementById('currentStationSelect')?.value||'';
  const prioritized=[...candidates].sort((a,b)=>{
    if(a.station.id===selectedId) return -1;
    if(b.station.id===selectedId) return 1;
    return Math.abs(b.value)-Math.abs(a.value);
  });
  const minDistance=displayMode==='declutter'?24:0;
  const keptPoints=[];
  prioritized.forEach(item=>{
    const lat=Number(item.station.lat);
    const lon=Number(item.station.lon);
    const point=currentLiveMap.latLngToLayerPoint([lat,lon]);
    const selected=item.station.id===selectedId;
    const stale=(currentMapAgeMinutes(item.station,metric)??0)>60;
    if(minDistance>0 && !selected && !currentMapKeepLabel(point,keptPoints,minDistance)) return;
    keptPoints.push(point);
    const marker=L.marker([lat,lon],{icon:currentMapLabelIcon(metric,item.value,selected,stale),zIndexOffset:selected?1000:(stale?-10:0)});
    marker.bindPopup(currentMapPopupHtml(item.station,metric,item.value));
    marker.on('click',()=>{const select=document.getElementById('currentStationSelect'); if(select){select.value=item.station.id; persistDashboardState('currentStationSelect',item.station.id); loadCurrentStation(item.station.id);} });
    marker.addTo(currentLiveMapLayer);
  });
}
function currentMapSetFullscreenButton(){
  const button=document.getElementById('currentMapFullscreenButton');
  const mapElement=document.getElementById('currentMap');
  if(!button||!mapElement) return;
  const active=document.fullscreenElement===mapElement;
  button.textContent=active?'Vollbild schließen':'Vollbild';
}
function currentMapToggleFullscreen(){
  const mapElement=document.getElementById('currentMap');
  if(!mapElement) return;
  if(document.fullscreenElement===mapElement){document.exitFullscreen?.();return;}
  mapElement.requestFullscreen?.().catch(error=>console.warn('Vollbild nicht möglich:',error));
}
function currentMapHandleFullscreenChange(){
  currentMapSetFullscreenButton();
  window.setTimeout(()=>{if(currentLiveMap){currentLiveMap.invalidateSize(false);renderCurrentMap();}},120);
}
async function currentMapCaptureCanvas(){
  const mapElement=document.getElementById('currentMap');
  if(!mapElement) throw new Error('Karte nicht gefunden.');
  if(typeof html2canvas!=='function') throw new Error('Exportbibliothek konnte nicht geladen werden.');
  mapElement.classList.add('current-map-exporting');
  try{
    return await window.captureDashboardWithWhiteBackground(mapElement,{scale:3,backgroundColor:'#f8fafb',useCORS:true,logging:false});
  }finally{mapElement.classList.remove('current-map-exporting');}
}
async function currentMapExport(format){
  const metric=document.getElementById('currentMapMetricSelect')?.value||'temperature';
  const state=document.getElementById('currentStateSelect')?.value||'Deutschland';
  const filename=safeExportFilename(`Livekarte_${currentMapMetricSpec(metric).label}_${state}`,format);
  const buttons=[document.getElementById('currentMapPngButton'),document.getElementById('currentMapPdfButton')].filter(Boolean);
  buttons.forEach(button=>button.disabled=true);
  try{
    const canvas=await currentMapCaptureCanvas();
    if(format==='png'){
      const link=document.createElement('a');link.download=filename;link.href=canvas.toDataURL('image/png');document.body.appendChild(link);link.click();link.remove();
      return;
    }
    const {jsPDF}=window.jspdf||{};
    if(!jsPDF) throw new Error('PDF-Bibliothek konnte nicht geladen werden.');
    const pdf=new jsPDF({orientation:'landscape',unit:'mm',format:'a4'});
    const pageW=pdf.internal.pageSize.getWidth(),pageH=pdf.internal.pageSize.getHeight();
    const margin=8, maxW=pageW-margin*2,maxH=pageH-margin*2;
    const ratio=Math.min(maxW/canvas.width,maxH/canvas.height);
    const w=canvas.width*ratio,h=canvas.height*ratio;
    pdf.addImage(canvas.toDataURL('image/png'),'PNG',(pageW-w)/2,(pageH-h)/2,w,h,undefined,'FAST');
    pdf.save(filename);
  }finally{buttons.forEach(button=>button.disabled=false);}
}
function currentWindCompass(value){
  const deg=Number(value);
  if(!Number.isFinite(deg)) return "–";
  const names=["N","NNO","NO","ONO","O","OSO","SO","SSO","S","SSW","SW","WSW","W","WNW","NW","NNW"];
  return names[Math.round((((deg%360)+360)%360)/22.5)%16];
}
function currentMsToKmh(value){
  return currentHasNumber(value)?Number(value)*3.6:null;
}
function renderCurrentEmpty(message){
  document.getElementById("currentStationHeading").textContent=message;
  ["currentTemp","currentMinMax","currentHumidity","currentDewpoint","currentPressure","currentGroundTemp","currentWind","currentWindDirection","currentGust","currentPrecip"].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent="–";});
  ["currentWindDetail","currentWindDirectionDetail","currentGustDetail","currentPrecipDetail","currentHumidityMax","currentDewpointMax","currentPressureMax","currentGroundTempMax"].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent="–";});
  const tbody=document.querySelector("#currentTodayTable tbody");
  if(tbody) tbody.innerHTML=`<tr><td colspan="10">${message}</td></tr>`;
  if(currentConditionsChart){currentConditionsChart.destroy();currentConditionsChart=null;}
  if(currentWindChart){currentWindChart.destroy();currentWindChart=null;}
  if(currentPrecipChart){currentPrecipChart.destroy();currentPrecipChart=null;}
}
function currentPopulateStates(){
  const select=document.getElementById("currentStateSelect");
  if(!select || !currentLiveIndex) return;
  const previous=select.value;
  const states=[...new Set((currentLiveIndex.stations||[]).map(station=>station.state).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"de"));
  select.innerHTML='<option value="">Alle Bundesländer</option>'+states.map(state=>`<option value="${state}">${state}</option>`).join("");
  if(previous && states.includes(previous)) select.value=previous;
  else if(dashboardState.currentStateSelect && states.includes(dashboardState.currentStateSelect)) select.value=dashboardState.currentStateSelect;
}
function renderCurrentLiveStatus(){
  const status=document.getElementById("currentLiveStatus");
  const dot=document.getElementById("currentLiveDot");
  if(!status || !currentLiveIndex) return;
  const overallAge=currentAgeMinutes(currentLiveIndex.latest_measurement_utc);
  const cdcLatest=currentLiveIndex._cdc_latest_measurement_utc||currentLiveIndex.latest_measurement_utc;
  const cdcAge=currentAgeMinutes(cdcLatest);
  const fastLatest=currentLiveIndex.fast_live_latest_measurement_utc;
  const fastAge=currentAgeMinutes(fastLatest);
  const counts=currentLiveIndex.availability_counts||{};
  const extras=currentLiveIndex.schema_version>=2?` · CDC: Temperaturextreme ${counts.temperature_extrema||0}, Wind ${counts.wind||0}, Böen ${counts.gust||0}, Niederschlag ${counts.precipitation||0}`:"";
  const statusNote=cdcAge!==null&&cdcAge>90?" · Achtung: CDC-Werte veraltet":"";
  const precisionNote=currentLiveIndex.schema_version<5?" · Tages-TX/TN noch nicht aus Original-Extremen":"";
  if(currentLiveIndex.fast_live_available){
    status.textContent=`Fast Live SYNOP: ${currentLiveIndex.fast_live_station_count||0} Stationen · ${currentDateTime(fastLatest)}${fastAge!==null?` · ${fastAge} min alt`:""} · CDC-Stand ${currentDateTime(cdcLatest)}${cdcAge!==null?` · ${cdcAge} min alt`:""}${extras}${statusNote}${precisionNote}`;
  }else{
    status.textContent=`CDC Live: ${currentLiveIndex.station_count||0} Temperaturstationen · ${currentDateTime(cdcLatest)}${cdcAge!==null?` · ${cdcAge} min alt`:""}${extras}${statusNote}${precisionNote} · Fast Live noch nicht verfügbar`;
  }
  dot.className="current-live-dot"+(cdcAge!==null&&cdcAge>90||overallAge!==null&&overallAge>45?" stale":"");
}
async function ensureCurrentConditions(force=false){
  const now=Date.now();
  if(currentLiveLoading) return currentLiveLoading;
  if(!force && currentLiveIndex && now-currentLiveLastFetch<60000){renderCurrentLiveStatus();return;}
  const status=document.getElementById("currentLiveStatus");
  const dot=document.getElementById("currentLiveDot");
  if(status) status.textContent="Live-Daten werden geprüft …";
  currentLiveLoading=(async()=>{
    try{
      const [cdcIndex,fastIndex]=await Promise.all([
        currentFetchJson("current_index.json"),
        currentFetchFastJson("fast_current.json").catch(error=>{console.warn("Fast Live SYNOP noch nicht verfügbar:",error);return null;})
      ]);
      cdcIndex.stations=(cdcIndex.stations||[]).map(currentNormalizeStationMeta);
      currentFastIndex=fastIndex;
      currentFastByStation=new Map((fastIndex?.stations||[]).map(item=>[String(item.station_id||''),item]));
      currentLiveIndex=currentMergeFastIntoIndex(cdcIndex,fastIndex);
      currentLiveLastFetch=Date.now();
      currentPopulateStates();
      populateCurrentStations(true);
      renderCurrentLiveStatus();
      renderCurrentOverview();
      renderCurrentMap();
    }catch(error){
      console.error("Aktuellbereich:",error);
      if(status) status.textContent=`Aktuelle Daten noch nicht verfügbar: ${error.message}. Den Workflow „DWD 10-Minuten-Aktuellbereich aktualisieren“ einmal starten.`;
      if(dot) dot.className="current-live-dot error";
    }finally{currentLiveLoading=null;}
  })();
  return currentLiveLoading;
}
async function loadCurrentStation(stationId){
  if(!stationId) return;
  const heading=document.getElementById("currentStationHeading");
  if(heading) heading.textContent="Stationsdaten werden geladen …";
  try{
    const profile=await currentFetchJson(`stations/${stationId}.json`);
    if(document.getElementById("currentStationSelect")?.value!==stationId) return;
    currentLiveProfile=profile;
    renderCurrentStation(profile);
  }catch(error){
    console.error(error);
    renderCurrentEmpty(`Station ${stationId} konnte nicht geladen werden: ${error.message}`);
  }
}
function renderCurrentStation(profile){
  profile=currentMergeFastProfile(profile);
  const station=currentNormalizeStationMeta(profile.station||{});
  const latest=profile.latest||{};
  const today=profile.today?.date&&profile.today.date!==currentDayIso(Date.now())?{}:(profile.today||{});
  const availability=profile.availability||{};
  const availableLabels=[availability.wind?"Wind":null,availability.gust?"Böen":null,availability.precipitation?"Niederschlag":null].filter(Boolean);
  const fastInfo=profile._fast_live?.time_utc?`Fast Live SYNOP ${currentTimeOnly(profile._fast_live.time_utc)}`:"";
  const meta=[station.state,Number.isFinite(Number(station.elevation_m))?`${Number(station.elevation_m).toLocaleString("de-DE")} m`:"",fastInfo||`letzte Messung ${currentDateTime(latest.local||latest.utc)}`,availableLabels.length?`Zusatzdaten: ${availableLabels.join(", ")}`:"keine Zusatzparameter an dieser Stations-ID"].filter(Boolean).join(" · ");
  document.getElementById("currentStationHeading").innerHTML=`<strong>${station.name||"Station"} (${station.id||"–"})</strong><br><span class="note">${meta}</span>`;
  document.getElementById("currentTemp").textContent=currentNum(latest.temperature_c,"°C",1);
  document.getElementById("currentTempDetail").textContent=`${latest.temperature_source==='synop'?'Fast Live SYNOP · ':''}Messzeitpunkt ${currentDateTime(latest.temperature_local||latest.temperature_utc||latest.local||latest.utc)}`;
  document.getElementById("currentMinMax").textContent=`${currentNum(today.min_c,"°C",1)} / ${currentNum(today.max_c,"°C",1)}`;
  document.getElementById("currentMean").textContent=`Minimum / Maximum · Mittel der 10-Min-Werte ${currentNum(today.mean_10min_c,"°C",1)}`;
  document.getElementById("currentHumidity").textContent=currentNum(latest.humidity_pct,"%",0);
  document.getElementById("currentDewpoint").textContent=currentNum(latest.dewpoint_c,"°C",1);
  document.getElementById("currentPressure").textContent=currentNum(latest.pressure_hpa,"hPa",1);
  document.getElementById("currentGroundTemp").textContent=currentNum(latest.ground_temp_c,"°C",1);
  document.getElementById("currentHumidityMax").textContent="Tagesmaximum: "+currentNum(today.max_humidity_pct,"%",0);
  document.getElementById("currentDewpointMax").textContent="Tagesmaximum: "+currentNum(today.max_dewpoint_c,"°C",1);
  document.getElementById("currentPressureMax").textContent="Tagesmaximum: "+currentNum(today.max_pressure_hpa,"hPa",1);
  document.getElementById("currentGroundTempMax").textContent="Tagesmaximum: "+currentNum(today.max_ground_temp_c,"°C",1);

  document.getElementById("currentWind").textContent=currentNum(latest.wind_speed_ms,"m/s",1);
  const windKmh=currentMsToKmh(latest.wind_speed_ms);
  document.getElementById("currentWindDetail").textContent=`Tagesmaximum: ${currentNum(today.max_wind_ms,"m/s",1)} · aktuell ${currentNum(latest.wind_speed_ms,"m/s",1)} (${currentNum(windKmh,"km/h",1)}) · ${currentDateTime(latest.wind_local||latest.wind_utc)}`;
  const windDir=Number(latest.wind_direction_deg);
  document.getElementById("currentWindDirection").textContent=Number.isFinite(windDir)?`${currentWindCompass(windDir)} · ${Math.round(windDir)}°`:"–";
  document.getElementById("currentWindDirectionDetail").textContent=Number.isFinite(windDir)?"DD_10 · 10-Minuten-Mittel":"an dieser Stations-ID nicht verfügbar";
  document.getElementById("currentGust").textContent=currentNum(latest.gust_speed_ms,"m/s",1);
  const gustKmh=currentMsToKmh(latest.gust_speed_ms);
  document.getElementById("currentGustDetail").textContent=`Tagesmaximum: ${currentNum(today.max_gust_ms,"m/s",1)} (${currentNum(currentMsToKmh(today.max_gust_ms),"km/h",1)}) · aktuell ${currentNum(latest.gust_speed_ms,"m/s",1)} · ${currentDateTime(latest.gust_local||latest.gust_utc)}`;
  document.getElementById("currentPrecip").textContent=currentNum(today.precip_sum_mm,"mm",1);
  document.getElementById("currentPrecipDetail").textContent=`Summe seit 00 Uhr · letzte 10 Min ${currentNum(latest.precip_10min_mm,"mm",1)} · Datenstand ${currentDateTime(latest.precipitation_local||latest.precipitation_utc)}`;

  const liveNumber=value=>value===null||value===undefined||value===""?null:Number(value);
  const series=(profile.series||[]).map(row=>({
    time:row[0],temp:liveNumber(row[1]),humidity:liveNumber(row[2]),dew:liveNumber(row[3]),pressure:liveNumber(row[4]),ground:liveNumber(row[5]),
    wind:liveNumber(row[6]),windDir:liveNumber(row[7]),gust:liveNumber(row[8]),gustDir:liveNumber(row[9]),precip:liveNumber(row[10]),precipDuration:liveNumber(row[11]),precipIndicator:liveNumber(row[12])
  }));
  const cutoff=Date.now()-24*3600*1000;
  const chartRows=series.filter(row=>new Date(row.time).getTime()>=cutoff);
  const labels=chartRows.map(row=>new Date(row.time).toLocaleTimeString("de-DE",{weekday:"short",hour:"2-digit",minute:"2-digit"}));

  if(currentConditionsChart){currentConditionsChart.destroy();currentConditionsChart=null;}
  const canvas=document.getElementById("currentConditionsChart");
  if(canvas){
    const existing=Chart.getChart(canvas);if(existing)existing.destroy();
    currentConditionsChart=new Chart(canvas,{type:"line",data:{labels,datasets:[
      {label:"Temperatur",data:chartRows.map(row=>Number.isFinite(row.temp)?row.temp:null),borderColor:"#d7191c",borderWidth:2.2,pointRadius:0,tension:.12},
      {label:"Taupunkt",data:chartRows.map(row=>Number.isFinite(row.dew)?row.dew:null),borderColor:"#2166ac",borderWidth:1.6,borderDash:[5,4],pointRadius:0,tension:.12}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:`Temperatur und Taupunkt – ${station.name||station.id} – letzte 24 Stunden`,font:{size:17,weight:"bold"}},datalabels:{display:false}},scales:{x:{ticks:{maxTicksLimit:12,maxRotation:0}},y:{title:{display:true,text:"°C"}}}}});
  }

  if(currentWindChart){currentWindChart.destroy();currentWindChart=null;}
  const windCanvas=document.getElementById("currentWindChart");
  if(windCanvas){
    const existing=Chart.getChart(windCanvas);if(existing)existing.destroy();
    currentWindChart=new Chart(windCanvas,{type:"line",data:{labels,datasets:[
      {label:"Windmittel FF_10",data:chartRows.map(row=>Number.isFinite(row.wind)?row.wind:null),borderColor:"#2b6f92",borderWidth:2,pointRadius:0,tension:.1},
      {label:"Böe FX_10",data:chartRows.map(row=>Number.isFinite(row.gust)?row.gust:null),borderColor:"#b45f06",borderWidth:1.8,pointRadius:0,tension:.08}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:`Wind und Böen – ${station.name||station.id} – letzte 24 Stunden`,font:{size:17,weight:"bold"}},datalabels:{display:false},tooltip:{callbacks:{afterBody(items){const idx=items?.[0]?.dataIndex;if(idx===undefined)return "";const row=chartRows[idx];return Number.isFinite(row.windDir)?`Windrichtung: ${currentWindCompass(row.windDir)} (${Math.round(row.windDir)}°)`:"";}}}},scales:{x:{ticks:{maxTicksLimit:12,maxRotation:0}},y:{beginAtZero:true,title:{display:true,text:"m/s"}}}}});
  }

  if(currentPrecipChart){currentPrecipChart.destroy();currentPrecipChart=null;}
  const precipCanvas=document.getElementById("currentPrecipChart");
  if(precipCanvas){
    const existing=Chart.getChart(precipCanvas);if(existing)existing.destroy();
    currentPrecipChart=new Chart(precipCanvas,{type:"bar",data:{labels,datasets:[
      {label:"Niederschlag je 10 Minuten",data:chartRows.map(row=>Number.isFinite(row.precip)?Math.max(0,row.precip):null),backgroundColor:"rgba(31,119,180,.58)",borderColor:"#1f77b4",borderWidth:1}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:`10-Minuten-Niederschlag – ${station.name||station.id} – letzte 24 Stunden`,font:{size:17,weight:"bold"}},datalabels:{display:false}},scales:{x:{ticks:{maxTicksLimit:12,maxRotation:0}},y:{beginAtZero:true,title:{display:true,text:"mm / 10 min"}}}}});
  }

  const todayDate=today.date;
  const todayRows=series.filter(row=>{
    const local=String(row.time).slice(0,10);
    return !todayDate || local===todayDate;
  }).reverse();
  const tbody=document.querySelector("#currentTodayTable tbody");
  if(tbody) tbody.innerHTML=todayRows.length?todayRows.map(row=>`<tr><td>${new Date(row.time).toLocaleTimeString("de-DE",{hour:"2-digit",minute:"2-digit"})}</td><td>${currentNum(row.temp,"°C",1)}</td><td>${currentNum(row.humidity,"%",0)}</td><td>${currentNum(row.dew,"°C",1)}</td><td>${currentNum(row.pressure,"hPa",1)}</td><td>${currentNum(row.ground,"°C",1)}</td><td>${currentNum(row.wind,"m/s",1)}</td><td>${Number.isFinite(row.windDir)?`${currentWindCompass(row.windDir)} ${Math.round(row.windDir)}°`:"–"}</td><td>${currentNum(row.gust,"m/s",1)}</td><td>${currentNum(row.precip,"mm",1)}</td></tr>`).join(""):'<tr><td colspan="10">Für heute sind noch keine 10-Minuten-Werte vorhanden.</td></tr>';
  renderCurrentMap();
}
function initCurrentControls(){
  const state=document.getElementById("currentStateSelect");
  const search=document.getElementById("currentStationSearch");
  const select=document.getElementById("currentStationSelect");
  const refresh=document.getElementById("currentRefreshButton");
  const metric=document.getElementById("currentMapMetricSelect");
  const display=document.getElementById("currentMapDisplaySelect");
  const climateDay=document.getElementById("currentMapClimateDaySelect");
  const fullscreenButton=document.getElementById("currentMapFullscreenButton");
  const pngButton=document.getElementById("currentMapPngButton");
  const pdfButton=document.getElementById("currentMapPdfButton");
  state?.addEventListener("change",()=>populateCurrentStations(false));
  search?.addEventListener("input",()=>populateCurrentStations(false));
  select?.addEventListener("change",()=>{persistDashboardState("currentStationSelect",select.value);loadCurrentStation(select.value);});
  refresh?.addEventListener("click",()=>ensureCurrentConditions(true));
  metric?.addEventListener("change",()=>renderCurrentMap());
  display?.addEventListener("change",()=>renderCurrentMap());
  climateDay?.addEventListener("change",()=>renderCurrentMap());
  fullscreenButton?.addEventListener("click",()=>currentMapToggleFullscreen());
  pngButton?.addEventListener("click",()=>currentMapExport('png').catch(error=>{console.error(error);alert(`PNG-Export nicht möglich: ${error.message}`);}));
  pdfButton?.addEventListener("click",()=>currentMapExport('pdf').catch(error=>{console.error(error);alert(`PDF-Export nicht möglich: ${error.message}`);}));
  document.addEventListener("fullscreenchange",currentMapHandleFullscreenChange);
  currentMapSetFullscreenButton();
  window.setInterval(()=>{
    if(document.getElementById("current")?.classList.contains("active")) ensureCurrentConditions(true);
  },2*60*1000);
}
initCurrentControls();




