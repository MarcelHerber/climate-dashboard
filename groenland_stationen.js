/* Greenland station and climate records monitor: genuine DMI Climate Data only. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const API="https://opendataapi.dmi.dk/v2/climateData/collections";
const PARAMS={
 mean_temp:{label:"Temperaturmittel",unit:"°C",direction:"max"},
 max_temp_w_date:{label:"Temperaturmaximum",unit:"°C",direction:"max"},
 min_temp:{label:"Temperaturminimum",unit:"°C",direction:"min"},
 acc_precip:{label:"Niederschlag",unit:"mm",direction:"max"},
 max_wind_speed_3sec:{label:"3-s-Böe",unit:"m/s",direction:"max"},
 mean_wind_speed:{label:"Windmittel",unit:"m/s",direction:"max"},
 mean_pressure:{label:"Luftdruckmittel",unit:"hPa",direction:"max"},
 max_precip_24h:{label:"Max. Tagesniederschlag",unit:"mm",direction:"max"}
};
const RECORD_TYPES=[
 ["High","max_temp_w_date",true],["Low","min_temp",false],
 ["Gust","max_wind_speed_3sec",true],["Rain","max_precip_24h",true]
];
const YEAR=new Date().getUTCFullYear();
const fmt=(x,d=1)=>Number.isFinite(x)?x.toLocaleString("de-DE",{minimumFractionDigits:d,maximumFractionDigits:d}):"–";
const dateLabel=s=>s&&/^\d{4}-\d{2}-\d{2}$/.test(s)?s.slice(8)+"."+s.slice(5,7)+"."+s.slice(0,4):"–";
const cleanName=s=>String(s||"").trim();
const isNumber=x=>typeof x==="number"&&Number.isFinite(x);
const validParam=id=>Object.prototype.hasOwnProperty.call(PARAMS,id);
let catalogue=[],latest={},station=null,map=null,markers=new Map(),chart=null,series=[],records=[],serial=0;
let cachedStamp="",markerGroup=null;
let recordMode="latest",mapRecords={},markerDetails=new Map();
const RECORD_MAP_SETTINGS={
 latest:{label:"Jüngstes Tagesmittel",unit:"°C",levels:[-30,-15,-5,5]},
 high:{label:"Historisches Temperaturmaximum",unit:"°C",levels:[-10,0,10,20]},
 low:{label:"Historisches Temperaturminimum",unit:"°C",levels:[-45,-35,-25,-15]},
 gust:{label:"Historische stärkste 3-s-Böe",unit:"m/s",levels:[10,20,30,40]},
 rain:{label:"Historischer größter 24-h-Niederschlag",unit:"mm",levels:[5,15,30,60]}
};
const RECORD_COLORS=["#4b448f","#2479b0","#44a3b9","#e1b14b","#d85c4a"];
function recordColor(mode,value){
 if(!isNumber(value))return "#748398";
 if(mode==="latest")return tempColor(value);
 const levels=RECORD_MAP_SETTINGS[mode]?.levels;
 if(!levels)return "#748398";
 for(let i=0;i<levels.length;i++)if(value<levels[i])return RECORD_COLORS[i];
 return RECORD_COLORS[4];
}
function mapValue(s){return recordMode==="latest"?latestFor(s.id,"mean_temp"):mapRecords[s.id];}
function applyRecordMap(mode,data={}){
 if(!Object.prototype.hasOwnProperty.call(RECORD_MAP_SETTINGS,mode))return;
 recordMode=mode;mapRecords=data||{};
 for(const s of catalogue){
  const marker=markers.get(s.id);
  if(!marker)continue;
  const value=mapValue(s);
  marker.setStyle({
   fillColor:recordColor(mode,recordMode==="latest"?value?.value:value?.value),
   fillOpacity:value?.value===undefined?.5:.9,
   color:station?.id===s.id?"#0b2236":"#fff",
   weight:station?.id===s.id?3:1
  });
  marker.setRadius(value?.value===undefined?4.3:6);
  const detail=markerDetails.get(s.id);
  if(detail)detail.textContent=markerTitle(s);
  marker.bindTooltip(markerTitle(s),{direction:"top",opacity:.93});
 }
 renderList();
}

const statuses={active:"Aktive Station",all:"Historische Station"};

function status(text,error=false){
 const el=$("grStatus");el.textContent=text;el.classList.toggle("gr-error",error);
}
function pickStatus(el,text,error=false){
 $(el).textContent=text;$(el).classList.toggle("gr-error",error);
}
function urlFor(collection,query){
 return API+"/"+collection+"/items?"+new URLSearchParams(query).toString();
}
async function getJSON(url,timeout=35000){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
 try{
  const result=await fetch(url,{cache:"no-store",signal:controller.signal,mode:"cors"});
  if(!result.ok)throw Error("DMI HTTP "+result.status);
  const json=await result.json();
  if(!Array.isArray(json.features))throw Error("Ungültige DMI-GeoJSON-Antwort");
  return json;
 }finally{clearTimeout(timer);}
}
async function apiValues(id,param,resolution,from,to){
 if(!/^[0-9A-Za-z_-]{3,24}$/.test(id)||!validParam(param))throw Error("Ungültige DMI-Abfrage");
 const limit=resolution==="year"?1000:resolution==="month"?3000:32000;
 const url=urlFor("stationValue",{
  stationId:id,parameterId:param,timeResolution:resolution,
  datetime:from+"T00:00:00Z/"+to+"T23:59:59Z",limit:String(limit)
 });
 const data=await getJSON(url,70000);
 // DMI returns rel=next even when the page contains fewer than limit rows.
 // A smaller result is complete; only an actual full page needs re-querying.
 if(data.features.length>=limit){
  throw Error("DMI-Abfrage erreicht das Abfragelimit. Bitte kleineren Zeitraum auswählen.");
 }
 return normalize(data.features,param,resolution);
}
function normalize(features,param,resolution){
 const unique=new Map();
 for(const row of features){
  const p=row.properties||{},date=String(p.from||"").slice(0,10);
  if(p.parameterId!==param||p.timeResolution!==resolution||p.validity===false||
     !isNumber(p.value)||!/^\d{4}-\d{2}-\d{2}$/.test(date))continue;
  if(param==="acc_precip"||param==="max_precip_24h"){
   if(p.value<-.1)continue;
  }
  const key=resolution==="year"?date.slice(0,4):resolution==="month"?date.slice(0,7):date;
  const record={
   date:key,value:p.value===-.1&&["acc_precip","max_precip_24h"].includes(param)?0:p.value,
   raw:p.value,trace:p.value===-.1&&["acc_precip","max_precip_24h"].includes(param),
   qc:p.qcStatus||"none",created:p.created||"",count:p.noValuesInCalculation??null
  };
  const previous=unique.get(key);
  // In DMI duplicates the most recently created version supersedes older ones.
  if(!previous||record.created>previous.created)unique.set(key,record);
 }
 return [...unique.values()].sort((a,b)=>a.date.localeCompare(b.date));
}
function prepareCatalogue(features){
 const stations=new Map();
 for(const f of features){
  const p=f.properties||{},c=f.geometry?.coordinates||[];
  const id=String(p.stationId||"");
  if(p.country!=="GRL"||!id||c.length<2||!isNumber(c[0])||!isNumber(c[1]))continue;
  if(c[0]<-75||c[0]>-10||c[1]<59||c[1]>84)continue;
  const row={
   id,name:cleanName(p.name)||id,lon:c[0],lat:c[1],status:p.status||"",
   type:p.type||"",from:String(p.operationFrom||"").slice(0,10),
   to:String(p.operationTo||"").slice(0,10),
   height_m:isNumber(p.stationHeight)?p.stationHeight:null,
   parameters:Array.isArray(p.parameterId)?p.parameterId:[]
  };
  const prev=stations.get(id);
  if(!prev||row.from>prev.from)stations.set(id,row);
 }
 return [...stations.values()].sort((a,b)=>a.name.localeCompare(b.name,"de"));
}
function tempColor(value){
 if(!isNumber(value))return "#748398";
 if(value<=-30)return "#4f468c";
 if(value<=-15)return "#2676b3";
 if(value<=-5)return "#449db9";
 if(value<=5)return "#dfb252";
 return "#d75a48";
}
function latestFor(id,param){return latest[id]?.[param];}
function markerTitle(s){
 const t=mapValue(s);
 if(!t||!isNumber(t.value))return s.name+" · "+s.id+" · keine Werte für "+RECORD_MAP_SETTINGS[recordMode].label;
 if(recordMode==="latest")
  return s.name+" · "+s.id+" · "+fmt(t.value)+" °C ("+dateLabel(t.date)+")";
 return s.name+" · "+s.id+" · "+RECORD_MAP_SETTINGS[recordMode].label+
  ": "+fmt(t.value)+" "+RECORD_MAP_SETTINGS[recordMode].unit+
  " · "+t.year+" · "+t.count+" DMI-Jahreswerte";
}
function selectStation(id,scroll=true,focusMap=true){
 const s=catalogue.find(x=>x.id===id);if(!s)return;
 station=s;serial++;
 $("grStationTitle").textContent=s.name+" · "+s.id;
 $("grStationMeta").textContent=(s.status==="Active"?"aktiv":"historisch")+
  " · "+(s.from?dateLabel(s.from):"Beginn unbekannt")+
  (s.to?" bis "+dateLabel(s.to):"")+
  (s.height_m!==null?" · "+fmt(s.height_m,0)+" m ü. NN":"")+
  " · "+s.type;
 for(const [key,m] of markers)m.setStyle({weight:key===s.id?3:1,opacity:key===s.id?1:.82});
 const marker=markers.get(id);
 if(marker&&map&&focusMap){
  // Keep station coordinates fixed; do not land on an empty ocean tile when a
  // small-screen map is currently zoomed out to show all of Greenland.
  map.invalidateSize({pan:false});
  map.setView(marker.getLatLng(),Math.max(5,map.getZoom()),{animate:false});
  marker.openPopup();
 }
 renderList();
 $("grSeriesStatus").textContent="Lade historische Originalwerte für "+s.name+" …";
 $("grRecordStatus").textContent="Prüfe DMI-Jahresextreme für "+s.name+" …";
 resetParameterIfUnsupported();
 loadBoth();
 window.dispatchEvent(new CustomEvent("grdmi:station-selected",{detail:{id:s.id,name:s.name}}));
 if(scroll&&matchMedia("(max-width: 740px)").matches)$("grStationTitle").scrollIntoView({behavior:"smooth",block:"start"});
}
function filteredStations(){
 const term=$("grSearch").value.toLocaleLowerCase("de").trim();
 const activeOnly=$("grStatusFilter").value==="active";
 return catalogue.filter(s=>(!activeOnly||s.status==="Active")&&
  (!term||(s.name+" "+s.id).toLocaleLowerCase("de").includes(term)));
}
function renderList(){
 const entries=filteredStations(),root=$("grStationList");root.replaceChildren();
 $("grStationCount").textContent=entries.length+" Stationen";
 $("grMapCount").textContent=entries.length+" Standorte";
 $("grStationListNote").textContent="Angezeigt: "+entries.length+" von "+catalogue.length+
  " Stationen. Ein Klick auf einen Eintrag lädt dessen Messreihe und Rekorde.";
 if(!entries.length){const p=document.createElement("p");p.className="gr-empty";p.textContent="Keine passenden DMI-Stationen gefunden.";root.append(p);}
 const frag=document.createDocumentFragment();
 for(const s of entries){
  const button=document.createElement("button");button.type="button";button.className="gr-station"+(station?.id===s.id?" selected":"");
  button.setAttribute("role","option");button.setAttribute("aria-selected",String(station?.id===s.id));
  const name=document.createElement("strong");name.textContent=s.name;
  const meta=document.createElement("span");meta.textContent=s.id+" · "+(s.status==="Active"?"aktiv":"historisch");
  const val=document.createElement("small"),t=mapValue(s);
  val.textContent=t&&isNumber(t.value)?
    fmt(t.value)+" "+RECORD_MAP_SETTINGS[recordMode].unit+
     " · "+(recordMode==="latest"?dateLabel(t.date):String(t.year)):
    "Keine Werte";
  button.append(name,meta,val);button.addEventListener("click",()=>selectStation(s.id));
  frag.append(button);
 }
 root.append(frag);
 for(const [id,m] of markers){
  const visible=entries.some(s=>s.id===id);
  if(visible)markerGroup?.addLayer(m);else markerGroup?.removeLayer(m);
 }
}
function fitStationBounds(){
 if(!map||!markerGroup||!markerGroup.getLayers().length)return;
 map.invalidateSize({pan:false});
 map.fitBounds(markerGroup.getBounds(),{padding:[28,28],maxZoom:4,animate:false});
}
function resetMap(){
 if(!map)return;
 $("grSearch").value="";
 $("grStatusFilter").value="active";
 map.closePopup();
 renderList();
 fitStationBounds();
}
function makeMap(){
 if(typeof L==="undefined"){
  $("grMap").textContent="Kartengrundlage konnte nicht geladen werden. Die Stationsliste ist weiterhin nutzbar.";
  return;
 }
 map=L.map("grMap",{scrollWheelZoom:false,zoomControl:true}).setView([71.4,-42],3);
 L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{
  maxZoom:12,attribution:"© OpenStreetMap-Mitwirkende"
 }).addTo(map);
 markerGroup=L.featureGroup().addTo(map);
 for(const s of catalogue){
  const t=latestFor(s.id,"mean_temp");
  const m=L.circleMarker([s.lat,s.lon],{
   radius:t?6:4.3,color:station?.id===s.id?"#071c31":"#fff",
   fillColor:tempColor(t?.value),fillOpacity:.9,weight:1
  });
  const content=document.createElement("div");
  const strong=document.createElement("strong");strong.textContent=s.name;
  const detail=document.createElement("p");detail.textContent=markerTitle(s);
  const b=document.createElement("button");b.type="button";b.textContent="Station auswählen";
  b.addEventListener("click",()=>selectStation(s.id));
  markerDetails.set(s.id,detail);
  content.append(strong,detail,b);m.bindPopup(content);
  m.on("click",()=>selectStation(s.id,false));
  markers.set(s.id,m);
 }
 renderList();
 window.dispatchEvent(new Event("grdmi:map-ready"));
 $("grMapReset").disabled=false;
 fitStationBounds();
 // Browsers can finish mobile navigation layout after the map has initialized.
 // Recalculate its tile grid once the final responsive container size is known.
 setTimeout(()=>map.invalidateSize({pan:false}),200);
 if(typeof ResizeObserver!=="undefined"){
  const observer=new ResizeObserver(()=>map?.invalidateSize({pan:false}));
  observer.observe($("grMap"));
 }
}
function resetParameterIfUnsupported(){
 const allowed=station?.parameters||[];
 for(const option of $("grParameter").options){
  option.disabled=allowed.length>0&&!allowed.includes(option.value);
 }
 if(allowed.length>0&&!allowed.includes($("grParameter").value)){
  const first=[...$("grParameter").options].find(x=>!x.disabled);
  if(first)$("grParameter").value=first.value;
 }
}
function fillYears(){
 const from=$("grFromYear"),to=$("grToYear");
 for(let year=YEAR;year>=1953;year--){
  for(const select of [from,to]){
   const opt=document.createElement("option");opt.value=year;opt.textContent=year;select.append(opt);
  }
 }
 from.value="1953";to.value=String(YEAR);
}
function setDefaultRange(){
 const resolution=$("grResolution").value;
 $("grFromYear").value=resolution==="day"?String(YEAR-2):resolution==="month"?String(YEAR-15):"1953";
 $("grToYear").value=String(YEAR);
}
function downsample(rows,max=1800){
 if(rows.length<=max)return rows;
 const window=Math.ceil(rows.length/(max/2)),out=[];
 for(let i=0;i<rows.length;i+=window){
  const block=rows.slice(i,i+window),sorted=block.slice().sort((a,b)=>a.value-b.value);
  const lo=sorted[0],hi=sorted.at(-1);
  out.push(...(lo.date<=hi.date?[lo,hi]:[hi,lo]));
 }
 return out;
}
// A missing period must appear as a real chart break, never a straight interpolation.
// Reduce only continuous segments; protect gaps and each segment's extrema.
function nextPeriod(date,resolution){
 if(resolution==="year")return String(Number(date)+1);
 if(resolution==="month"){
  const [y,m]=date.split("-").map(Number);
  return new Date(Date.UTC(y,m,1)).toISOString().slice(0,7);
 }
 const d=new Date(date+"T00:00:00Z");
 return new Date(d.getTime()+86400000).toISOString().slice(0,10);
}
function plotWithGaps(rows,resolution){
 if(!rows.length)return [];
 const parts=[];let segment=[rows[0]];
 for(let i=1;i<rows.length;i++){
  if(nextPeriod(rows[i-1].date,resolution)!==rows[i].date){
   parts.push(segment);segment=[];
  }
  segment.push(rows[i]);
 }
 parts.push(segment);
 const budget=Math.max(12,Math.ceil(1800/parts.length));
 const result=[];
 for(let i=0;i<parts.length;i++){
  if(i){
   result.push({date:nextPeriod(parts[i-1].at(-1).date,resolution),value:null,missing:true});
  }
  result.push(...downsample(parts[i],budget));
 }
 return result;
}
function drawSeries(){
 if(chart)chart.destroy();chart=null;
 if(typeof Chart==="undefined"){pickStatus("grSeriesStatus","Chart.js nicht erreichbar – CSV-Download bleibt verfügbar.",true);return;}
 const canvas=$("grChart"),p=$("grParameter").value,meta=PARAMS[p];
 const plot=plotWithGaps(series,$("grResolution").value);
 const isDaily=$("grResolution").value==="day";
 chart=new Chart(canvas,{
  type:"line",data:{datasets:[{
   label:meta.label+" ("+meta.unit+")",data:plot.map(x=>({x:x.date,y:x.value,trace:x.trace})),
   borderColor:"#1971a5",backgroundColor:"rgba(34,121,162,.12)",
   pointRadius:isDaily?0:1.5,pointHoverRadius:5,borderWidth:2,tension:0,spanGaps:false
  }]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,
   interaction:{intersect:false,mode:"nearest"},
   plugins:{legend:{display:false},tooltip:{callbacks:{
    title:items=>items[0]?.raw?.x||"",
    label:item=>item.raw?.trace?"Niederschlagsspur (<0,1 mm)":fmt(item.raw?.y)+" "+meta.unit
   }}},
   scales:{
    x:{type:"category",labels:plot.map(x=>x.date),ticks:{autoSkip:true,maxTicksLimit:12,color:"#728194",maxRotation:0},
       grid:{display:false}},
    y:{ticks:{color:"#728194"},title:{display:true,text:meta.unit,color:"#728194"},
       grid:{color:"rgba(100,124,145,.16)"}}
   }
  }
 });
}
function seriesKpis(){
 if(!series.length){
  ["grFirst","grLast","grExtreme","grValidCount"].forEach(k=>$(k).textContent="–");return;
 }
 const p=$("grParameter").value,meta=PARAMS[p];
 const ranked=series.slice().sort((a,b)=>meta.direction==="min"?a.value-b.value:b.value-a.value);
 $("grFirst").textContent=series[0].date;
 $("grLast").textContent=series.at(-1).date;
 $("grExtreme").textContent=fmt(ranked[0].value)+" "+meta.unit+" ("+ranked[0].date+")";
 $("grValidCount").textContent=series.length.toLocaleString("de-DE");
}
async function loadSeries(id,sequence){
 const param=$("grParameter").value,resolution=$("grResolution").value;
 const from=Number($("grFromYear").value),to=Number($("grToYear").value);
 if(from>to){pickStatus("grSeriesStatus","Von-Jahr muss vor Bis-Jahr liegen.",true);return;}
 series=[];$("grCsv").disabled=true;$("grPng").disabled=true;
 pickStatus("grSeriesStatus","Lade "+resolution+"-Werte direkt aus der DMI-API …");
 try{
  const rows=await apiValues(id,param,resolution,from+"-01-01",to+"-12-31");
  if(sequence!==serial)return;
  series=rows;
  if(!rows.length){
   seriesKpis();if(chart)chart.destroy();chart=null;
   pickStatus("grSeriesStatus","Für diese Station, Messgröße und Zeitspanne hat DMI keine gültigen "+resolution+"-Werte.",true);return;
  }
  seriesKpis();drawSeries();
  const provisional=rows.filter(x=>x.qc!=="manual").length;
  pickStatus("grSeriesStatus",rows.length.toLocaleString("de-DE")+" gültige DMI-Originalwerte ("+
   rows[0].date+" bis "+rows.at(-1).date+"). "+
   (provisional?provisional+" Einträge ohne Kennzeichen ‚manuell geprüft‘.":"Alle Einträge als manuell geprüft gekennzeichnet.")+
   (rows.length>1800?" Zur flotten Anzeige ist nur der Diagrammpfad verdichtet, CSV enthält alle Werte.":""));
  $("grCsv").disabled=false;$("grPng").disabled=chart===null;
 }catch(e){
  if(sequence!==serial)return;
  pickStatus("grSeriesStatus","DMI-Zeitreihe derzeit nicht abrufbar ("+e.message+"). Station und verfügbare Tageswerte bleiben sichtbar.",true);
  if(chart)chart.destroy();chart=null;seriesKpis();
 }
}
async function loadRecords(id,sequence){
 records=[];
 $("grRecordCsv").disabled=true;
 for(const key of ["High","Low","Gust","Rain"]){$("grRec"+key).textContent="–";$("grRec"+key+"Year").textContent="–";}
 pickStatus("grRecordStatus","Lade DMI-Jahresextreme über alle verfügbaren Jahre …");
 const values=await Promise.allSettled(RECORD_TYPES.map(async([key,param,isMax])=>{
  const points=await apiValues(id,param,"year","1953-01-01",YEAR+"-12-31");
  if(!points.length)return{key,param,available:0};
  const best=points.reduce((a,b)=>(isMax?b.value>a.value:b.value<a.value)?b:a,points[0]);
  return{key,param,available:points.length,value:best.value,year:best.date.slice(0,4),
   start:points[0].date.slice(0,4),end:points.at(-1).date.slice(0,4),qc:best.qc};
 }));
 if(sequence!==serial)return;
 const errors=[];
 for(let i=0;i<values.length;i++){
  const result=values[i],k=RECORD_TYPES[i][0];
  if(result.status==="rejected"){errors.push(k+": "+result.reason?.message);continue;}
  const item=result.value;
  if(!item.available)continue;
  records.push(item);
  $("grRec"+k).textContent=fmt(item.value)+" "+PARAMS[item.param].unit;
  $("grRec"+k+"Year").textContent="Jahr "+item.year+" · "+item.available+
   " Jahreswerte ("+item.start+"–"+item.end+")";
  if(k==="Gust")$("grRecGustYear").textContent+=" · "+fmt(item.value*3.6)+" km/h";
 }
 pickStatus("grRecordStatus",records.length+" von 4 Rekordparametern mit gültigen DMI-Jahreswerten."+
  (errors.length?" Nicht abrufbar: "+errors.join("; "):"")+
  " Kein Ersatzwert für fehlende Parameter.",records.length===0);
 $("grRecordCsv").disabled=records.length===0;
}
function loadBoth(){
 if(!station)return;
 const id=station.id,sequence=++serial;
 loadSeries(id,sequence);
 loadRecords(id,sequence);
}
function csvDownload(name,rows){
 const body="\ufeff"+rows.map(row=>row.map(x=>'"'+String(x??"").replace(/"/g,'""')+'"').join(";")).join("\r\n")+"\r\n";
 const blob=new Blob([body],{type:"text/csv;charset=utf-8"}),url=URL.createObjectURL(blob);
 const a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),5000);
}
function saveSeries(){
 if(!station||!series.length)return;
 const p=$("grParameter").value;
 csvDownload("DMI_Groenland_"+station.id+"_"+p+"_"+$("grResolution").value+".csv",[
  ["DMI Stations-ID","Parameter","Auflösung","Zeitraum","Messwert","Einheit","DMI QC","Niederschlagsspur"],
  ...series.map(x=>[station.id,p,$("grResolution").value,x.date,x.raw,PARAMS[p].unit,x.qc,x.trace?"ja":"nein"])
 ]);
}
function saveRecords(){
 if(!station||!records.length)return;
 csvDownload("DMI_Groenland_Rekorde_"+station.id+".csv",[
  ["Stations-ID","Parameter","Rekordwert","Einheit","Jahr des Jahreswerts","Anzahl verfügbarer Jahre","Erstes Jahr","Letztes Jahr","DMI QC"],
  ...records.map(x=>[station.id,x.param,x.value,PARAMS[x.param].unit,x.year,x.available,x.start,x.end,x.qc])
 ]);
}
function savePng(){
 if(!chart||!station)return;
 const source=chart.canvas,ratio=2,c=document.createElement("canvas");
 c.width=source.width*ratio;c.height=(source.height+100)*ratio;
 const ctx=c.getContext("2d");ctx.fillStyle="#fff";ctx.fillRect(0,0,c.width,c.height);
 ctx.fillStyle="#1b3449";ctx.font="bold 32px Arial";
 ctx.fillText("DMI Grönland · "+station.name+" ("+station.id+")",35,59);
 ctx.fillStyle="#536a7c";ctx.font="22px Arial";
 ctx.fillText(PARAMS[$("grParameter").value].label+" · "+$("grResolution").value+
  " · "+$("grFromYear").value+"–"+$("grToYear").value,35,100);
 ctx.drawImage(source,0,145,source.width*ratio,source.height*ratio);
 ctx.fillStyle="#536a7c";ctx.font="18px Arial";ctx.fillText("Quelle: DMI Climate Data API · gültige Originalwerte, keine Interpolation",35,c.height-28);
 const a=document.createElement("a");a.href=c.toDataURL("image/png");
 a.download="DMI_Groenland_"+station.id+"_"+$("grParameter").value+".png";
 document.body.append(a);a.click();a.remove();
}
async function loadCatalogue(){
 try{
  let doc=null;
  try{
   const r=await fetch("data/dmi_greenland_stations.json",{cache:"no-store"});
   if(r.ok){const payload=await r.json();
    if(payload.schema===1&&Array.isArray(payload.stations)&&payload.stations.length>=10)doc=payload;}
  }catch(e){console.warn("DMI Greenland local cache:",e);}
  if(doc){
   catalogue=doc.stations;latest=doc.latest||{};
   cachedStamp=doc.generated_utc||"";
   $("grUpdated").textContent=catalogue.length+" Stationen";
   $("grCoverage").textContent="Tageswerte: "+(doc.window_start||"–")+" bis "+(doc.window_end||"–")+
    (doc.fetch_errors?.length?" · Teilabfrage ausgefallen":"");
   status("DMI-Stationen aus dem geprüften GitHub-Cache geladen. Historische Reihen werden direkt beim DMI abgefragt.");
  }else{
   status("Noch kein GitHub-Snapshot vorhanden. Lade Stationsstandorte direkt beim DMI …");
   const all=[];
   let offset=0;
   for(let k=0;k<10;k++){
    const data=await getJSON(urlFor("station",{bbox:"-75,59,-10,84",limit:"5000",offset:String(offset)}));
    all.push(...data.features);offset+=data.features.length;
    if(data.features.length<5000&&!data.links?.some(l=>l.rel==="next"))break;
   }
   catalogue=prepareCatalogue(all);
   $("grUpdated").textContent=catalogue.length+" Stationen";
   $("grCoverage").textContent="Direktabruf DMI · jüngste Tageswerte ohne Cache nicht verfügbar";
   status("DMI-Stationsstandorte live geladen. Aktuelle Tageswerte folgen mit der nächsten geprüften Cache-Aktualisierung.");
  }
  if(!catalogue.length)throw Error("keine originalen DMI-GRÖNLAND-Stationen");
  makeMap();
  const current=catalogue.find(s=>s.status==="Active"&&latestFor(s.id,"mean_temp"))||
                catalogue.find(s=>s.status==="Active")||catalogue[0];
  if(current)selectStation(current.id,false,false);
 }catch(e){
  $("grUpdated").textContent="Keine Daten";
  status("DMI-Stationskatalog derzeit nicht verfügbar: "+e.message+
   ". Es werden keine erfundenen Stationsdaten angezeigt.",true);
  $("grStationList").textContent="Der offizielle DMI-Katalog ist momentan nicht erreichbar.";
 }
}
function init(){
 fillYears();
 $("grResolution").addEventListener("change",()=>{setDefaultRange();loadBoth();});
 $("grParameter").addEventListener("change",loadBoth);
 $("grApply").addEventListener("click",loadBoth);
 $("grSearch").addEventListener("input",renderList);
 $("grStatusFilter").addEventListener("change",renderList);
 $("grMapReset").addEventListener("click",resetMap);
 $("grCsv").addEventListener("click",saveSeries);
 $("grRecordCsv").addEventListener("click",saveRecords);
 $("grPng").addEventListener("click",savePng);
 loadCatalogue();
}
window.GreenlandDmiMap={
 applyRecordMap, getCatalogue:()=>catalogue.slice(),
 getState:()=>({mode:recordMode,visibleMarkers:markerGroup?.getLayers().length||0})
};
window.GreenlandDmiMath={normalize,prepareCatalogue,downsample,plotWithGaps,PARAMS,apiValues,
 getState:()=>({stationId:station?.id||"",stations:catalogue.length,
  records:records.length,series:series.length,hasMap:!!map,
  markerCount:markerGroup?.getLayers().length||0,mapZoom:map?.getZoom()??null,dataStamp:cachedStamp})};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
