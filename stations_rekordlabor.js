/* DWD Phase 3. Real archives only. Never fill missing measurements or compare
   a monthly precipitation aggregate to historical daily records. */
(function(){
"use strict";
const $=id=>document.getElementById(id),C=window.RecordLaborCore;
const RAW="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/";
const TODAY=new Date(),YEAR=TODAY.getUTCFullYear();
const tabs={calendar:["rlTabCalendar","rlCalendar"],seasons:["rlTabSeasons","rlSeasons"],
 changes:["rlTabChanges","rlChanges"]};
const state={catalog:null,klIndex:new Map(),station:null,view:"calendar",temp:null,snow:null,kl:null,
  stationSerial:0,weatherIndex:null,weather:null,weatherSerial:0,
  selectedEvent:null,csv:[],fileName:"",chart:null,chartCanvas:null,chartLabel:"",status:""};
const num=(n,max=1)=>Number(n).toLocaleString("de-DE",{maximumFractionDigits:max});
const finite=Number.isFinite,esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&quot;","'":"&#39;"}[c]));
const count=(s)=>s?num(s,0):"0";
const metricOpts={tmax:{i:0,label:"Tmax",unit:"°C"},tmin:{i:1,label:"Tmin",unit:"°C"},
 tmean:{i:2,label:"Tagesmittel",unit:"°C"},rain:{label:"Tagesniederschlag",unit:"mm"},sun:{label:"Sonnenscheindauer",unit:"h"},snow:{label:"Schneehöhe",unit:"cm"}};
function message(target,s){$(target).textContent=s;}
async function fetchJson(path,optional=false){
 for(const url of [path,RAW+path]){
  try{const response=await fetch(url,{cache:"no-store"});if(response.ok)return await response.json();}
  catch(e){/* static Pages may be reachable when raw mirror is not */ }
 }
 if(optional)return null;
 throw Error("DWD-Datensatz nicht erreichbar: "+path);
}
function validStation(st){
 return st && (st.temp||st.snow);
}
// Original DWD station coordinates from the compact Pages catalogue. Markers
// use Leaflet's canvas renderer for thousands of archive stations; no estimated
// coordinates or generic city centroids are ever generated.
let stationMap=null,markedStationId=null;
const stationMarkers=new Map();
const normalMarker={radius:3.8,color:"#356c97",fillColor:"#3c91ba",fillOpacity:.63,weight:1};
const activeMarker={radius:8,color:"#b63926",fillColor:"#e4543d",fillOpacity:.95,weight:2};
const klMarker={radius:5.4,color:"#8a5b27",fillColor:"#c98d33",fillOpacity:.82,weight:1.3};
function initMap(){
 const node=$("rlMap"),feedback=$("rlMapStatus");
 if(!node||!state.catalog)return;
 if(!window.L){feedback.textContent="Karte momentan nicht verfügbar; Stationssuche und Rekordauswertung funktionieren weiterhin.";return;}
 const stations=state.catalog.stations.filter(st=>validStation(st)&&
    finite(st.lat)&&finite(st.lon)&&st.lat>=45&&st.lat<=57&&st.lon>=4&&st.lon<=17);
 if(!stations.length){
  feedback.textContent="Für den Stationskatalog sind keine amtlich verorteten Koordinaten verfügbar.";
  return;
 }
 try{
  stationMap=L.map(node,{zoomControl:true,scrollWheelZoom:false,preferCanvas:true})
   .setView([51.2,10.4],6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{
   maxZoom:13,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(stationMap);
  const renderer=L.canvas({padding:.2});
  for(const st of stations){
   const style=state.klIndex.has(st.id)?klMarker:normalMarker;
   const marker=L.circleMarker([st.lat,st.lon],{...style,renderer})
     .addTo(stationMap);
   marker.bindTooltip(st.name+" · DWD "+st.id);
   marker.on("click",()=>{
     $("rlSearch").value=st.name;
     void selectStation(st);
     stationMap.setView([st.lat,st.lon],Math.max(8,stationMap.getZoom()));
   });
   stationMarkers.set(st.id,marker);
  }
  const klMapped=stations.filter(st=>state.klIndex.has(st.id)).length;
  feedback.textContent=stations.length.toLocaleString("de-DE")+
   " Stationsstandorte mit Originalkoordinaten · "+klMapped+
   " davon mit historischen Niederschlags-/Sonnenreihen (ockerfarbene Punkte) · Punkt anklicken.";
  setTimeout(()=>stationMap?.invalidateSize(),200);
 }catch(err){feedback.textContent="Karte konnte nicht initialisiert werden: "+err.message;}
}
function highlightStation(st){
 if(!stationMap)return;
 if(markedStationId&&stationMarkers.has(markedStationId))
   stationMarkers.get(markedStationId).setStyle(state.klIndex.has(markedStationId)?klMarker:normalMarker);
 markedStationId=st?.id;
 if(stationMarkers.has(markedStationId))
   stationMarkers.get(markedStationId).setStyle(activeMarker).bringToFront();
}

function renderSuggestions(){
 const query=$("rlSearch").value.trim().normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase();
 const stateName=$("rlState").value,onlyKL=$("rlOnlyKL").checked;
 const list=(state.catalog?.stations||[]).filter(st=>validStation(st)&&(!stateName||st.state===stateName))
  .filter(st=>!onlyKL||state.klIndex.has(st.id))
  .filter(st=>!query||(st.name+" "+st.id+" "+st.state).normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().includes(query))
  .slice(0,18);
 $("rlSuggestions").replaceChildren();
 for(const st of list){
  const b=document.createElement("button");b.type="button";
  b.classList.toggle("active",st.id===state.station?.id);
  b.innerHTML="<strong>"+esc(st.name)+"</strong><small>"+esc(st.state)+" · "+esc(st.id)+
   " · "+(st.temp?"Temperatur ":"")+(st.snow?"Schnee ":"")+
   (state.klIndex.has(st.id)?" · Niederschlag/Sonne (KL)":"")+"</small>";
  b.addEventListener("click",()=>{selectStation(st);$("rlSearch").value=st.name;if(stationMap&&finite(st.lat)&&finite(st.lon))stationMap.setView([st.lat,st.lon],8);});
  $("rlSuggestions").append(b);
 }
}
function showTab(which){
 state.view=which;
 for(const [key,[btn,area]] of Object.entries(tabs)){
  $(btn).setAttribute("aria-selected",String(key===which));
  $(area).hidden=key!==which;
 }
 if(which==="changes"){void initWeather();}else if(state.station)render();
}
function destroyChart(){
 if(state.chart){state.chart.destroy();state.chart=null;state.chartCanvas=null;}
}
function addChart(canvasId,title,labels,data,yTitle,color="#2d79ad"){
 destroyChart();
 state.chartCanvas=$(canvasId);
 if(!window.Chart||!state.chartCanvas)return;
 const main=[{label:title,data,borderColor:color,backgroundColor:color,
  borderWidth:2.2,pointRadius:labels.length>140?1:3,pointHoverRadius:5,
  tension:0,spanGaps:false,fill:false}];
 state.chart=new Chart(state.chartCanvas,{type:"line",data:{labels,datasets:main},options:{
  responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
  interaction:{mode:"nearest",intersect:false},plugins:{legend:{display:false},
  tooltip:{callbacks:{label:context=>context.parsed.y===null?"Fehlwert":
    title+": "+num(context.parsed.y,1)+" "+yTitle}}},
  scales:{x:{type:"category",ticks:{autoSkip:true,maxTicksLimit:13,maxRotation:0}},
    y:{type:"linear",title:{display:true,text:yTitle}}}
 }});
 state.chartLabel=title;
}
function kpis(id,entries){
 $(id).innerHTML=entries.map(x=>'<div class="rl-kpi"><strong>'+esc(x.value)+
  '</strong><small>'+esc(x.label)+'</small></div>').join("");
}
function tableRows(id,rows){
 $(id).innerHTML=rows.length?rows.join(""):'<tr><td colspan="5">Keine ausreichenden Originalmessdaten für diese Auswahl.</td></tr>';
}
function setExportState(ready){
 for(const b of document.querySelectorAll("#"+tabs[state.view][1]+" [data-rl-export]"))b.disabled=!ready;
}
async function selectStation(st){
 state.station=st;state.temp=null;state.snow=null;state.kl=null;highlightStation(st);const id=++state.stationSerial;
 message("rlStation",st.name+" · "+st.id+" · "+st.state+" · geprüfte Daten werden geladen …");
 renderSuggestions();
 for(const [value,option] of [["tmax","tmax"],["tmin","tmin"],["tmean","tmean"],["snow","snow"],["rain","rain"],["sun","sun"]]){
  const el=$("rlCalMetric").querySelector('option[value="'+option+'"]');if(el)el.disabled=value==="snow"?!st.snow:(value==="rain"||value==="sun")?true:!st.temp;
 }
 const snowOnly=!st.temp&&st.snow;
 if(snowOnly){$("rlCalMetric").value="snow";$("rlSeasonMetric").value="snowFirst";}
 else if($("rlCalMetric").value==="snow"&&!st.snow)$("rlCalMetric").value="tmax";
 setExportState(false);
 try{
  const tasks=[
    st.temp?fetchJson(st.temp_file).then(C.decodeTemperature):Promise.resolve(null),
    st.snow?fetchJson(st.snow_file).then(doc=>{
       if(!Array.isArray(doc?.years)||!Array.isArray(doc?.month_days))throw Error("Schneehöhenarchiv ungültig");
       return doc;
     }):Promise.resolve(null),
    (state.klIndex.has(st.id)?fetchJson("data/rekordlabor/calendar/"+st.id+".json",true):
      Promise.resolve(null)).then(async doc=>{
      if(!doc?.metrics||String(doc.station_id)!==st.id)return null;
      const [rain,sun]=await Promise.all([
        doc.metrics.rain?C.decodeDailyMetric(doc,"rain"):Promise.resolve(null),
        doc.metrics.sun?C.decodeDailyMetric(doc,"sun"):Promise.resolve(null)
      ]);
      return {rain,sun,source:doc.source};
    })
  ];
  // Only current station should be allowed to render on delayed network replies.
  const values=await Promise.allSettled(tasks);
  if(id!==state.stationSerial)return;
  state.temp=values[0].status==="fulfilled"?values[0].value:null;
  state.snow=values[1].status==="fulfilled"?values[1].value:null;
  state.kl=values[2].status==="fulfilled"?values[2].value:null;
  for(const value of ["rain","sun"]){
    const op=$("rlCalMetric").querySelector('option[value="'+value+'"]');
    if(op)op.disabled=!state.kl?.[value];
  }
  if($("rlCalMetric").selectedOptions[0]?.disabled)
    $("rlCalMetric").value=state.temp?"tmax":state.snow?"snow":state.kl?.rain?"rain":"sun";
  const errors=values.map(v=>v.status==="rejected"?v.reason.message:null).filter(Boolean);
  message("rlStation",st.name+" · DWD-ID "+st.id+" · "+st.state+
    " · Temperatur: "+(state.temp?state.temp.size+" historische Jahre":"nicht verfügbar")+
    " · Schneehöhe: "+(state.snow?state.snow.years.filter(y=>y.accepted).length+" vollständige hydrol. Jahre":"nicht verfügbar")+
    " · Niederschlag historisch: "+(state.kl?.rain?"ja":"kein geprüftes KL-Archiv")+
    " · Sonne historisch: "+(state.kl?.sun?"ja":"kein geprüftes KL-Archiv")+
    (errors.length?" · Einschränkung: "+errors.join(" / "):""));
  render();
 }catch(e){if(id===state.stationSerial)message("rlStation","Ladefehler: "+e.message);}
}
function calendarRender(){
 const metric=$("rlCalMetric").value,md=$("rlDay").value,order=$("rlCalOrder").value;
 const spec=metricOpts[metric],station=state.station;
 if(!station)return;
 const rows=metric==="snow"?(state.snow?C.snowCalendar(state.snow,md):[]):
   (metric==="rain"||metric==="sun")?C.calendarKL(state.kl?.[metric],md):
   (state.temp?C.calendarTemperature(state.temp,md,spec.i):[]);
 const sorted=C.sortedRecords(rows,order,10);
 const title=spec.label+" · "+md.slice(3)+"."+md.slice(0,2)+". · "+station.name;
 const sortedByYear=rows.slice().sort((a,b)=>a.year-b.year);
 const first=sortedByYear[0]?.year,last=sortedByYear.at(-1)?.year;
 message("rlCalendarMeta",rows.length?
   "Quelle: DWD CDC "+(metric==="snow"?"Schneehöhe SHK_TAG":
     metric==="rain"?"historische DWD KL Tagesniederschläge RSK (korrigiert)":
     metric==="sun"?"historische DWD KL Sonnenscheindauer SDK":"Tageswerte TXK/TNK/TMK")+
   " · "+rows.length+" echte, gültige Kalenderjahresmessungen · "+first+"–"+last+
   " · "+(metric==="snow"?"nur als vollständig markierte Schnee-Hydrojahre":"originale geprüfte CDC-Tageswerte, keine Lückenfüllung"):
   "Keine gültigen Tageswerte für diesen Kalendertag oder Parameter.");
 kpis("rlCalendarKpis",[{value:rows.length?num(sorted.records[0].value)+" "+spec.unit:"—",label:"Rang 1 · "+(order==="max"?"Maximum":"Minimum")},
   {value:count(rows.length),label:"Beobachtete Jahre"},
   {value:rows.length?C.readable(sorted.records[0].date):"—",label:"Datum des Rang-1-Werts"}]);
 tableRows("rlCalendarTable",sorted.records.map((r,i)=>"<tr><td>"+(i+1)+"</td><td>"+esc(C.readable(r.date))+
  "</td><td><strong>"+num(r.value)+" "+spec.unit+"</strong></td><td>"+r.year+"</td></tr>"));
 tableRows("rlCalendarAllYears",sortedByYear.map(r=>"<tr><td>"+esc(C.readable(r.date))+
  "</td><td>"+num(r.value)+" "+spec.unit+"</td></tr>"));
 state.csv=[["Datum","Jahr",spec.label+" ("+spec.unit+")"],...sortedByYear.map(r=>[r.date,r.year,r.value])];
 state.fileName="DWD_Rekordkalender_"+station.id+"_"+md+"_"+metric;
 addChart("rlChart",title,sortedByYear.map(r=>String(r.year)),sortedByYear.map(r=>r.value),spec.unit);
 setExportState(sortedByYear.length>1);
}
function seasonRender(){
 const event=$("rlSeasonMetric").value,st=state.station;
 if(!st)return;
 const snow=event.startsWith("snow"),run=event.endsWith("Run");
 let result=null,records=[],label="",unit="Kalendertag";
 if(snow){
  if(!state.snow){message("rlSeasonMeta","Kein qualitätsgeprüftes Tages-Schneehöhenarchiv für "+st.name);clearSeason();return;}
  if(run){
   records=C.snowLongest(state.snow).map(r=>({...r,value:r.days}));
   label="Längste zusammenhängende Schneedecke ab 1 cm";
  }else{
   result=C.snowSeason(state.snow,event);records=result.records;
   label=result.label;
  }
 }else{
  if(!state.temp){message("rlSeasonMeta","Kein historisches DWD-Temperaturarchiv für "+st.name);clearSeason();return;}
  if(run){
   const hot=event==="hotRun";
   records=C.longestRun(state.temp,hot?0:1,hot?v=>v>=30:v=>v<0)
      .map(r=>({...r,value:r.days}));
   label=hot?"Längste Folge heißer Tage (Tmax ≥ 30 °C)":"Längste Folge von Frosttagen (Tmin < 0 °C)";
  }else{
   result=C.tempSeason(state.temp,event);records=result.records;label=result.label;
  }
 }
 if(run)unit="Tage";
 else unit=snow?"Tag im hydrologischen Jahr":"Tag im Kalenderjahr";
 message("rlSeasonMeta","Quelle: DWD CDC · "+label+" · "+records.length+
  " auswertbare Jahre · "+(result?.threshold||"Mindestens 95 % gültige Tage im Messjahr")+
  (result?.excluded.length?" · "+result.excluded.length+" unvollständige/ausgeschlossene Jahre":"")+
  (records.some(r=>r.atBoundary)?" · Achtung: Schnee am 1. November bereits vorhanden (linkszensiert).":""));
 const top=records.slice(0,20),byYear=records.slice().sort((a,b)=>a.year-b.year);
 const rankValue=r=>run?String(r.days)+" Tage":r.md.slice(3)+"."+r.md.slice(0,2)+".";
 kpis("rlSeasonKpis",[{value:top.length?rankValue(top[0]):"—",label:"Historischer Rang 1"},
   {value:top.length?String(top[0].year):"—",label:"Jahr des Rangs 1"},
   {value:count(records.length),label:"Ausgewertete Jahre mit Ereignis"}]);
 tableRows("rlSeasonTable",top.map((r,i)=>"<tr><td>"+(i+1)+"</td><td>"+r.year+"</td><td>"+
  esc(run?C.readable(r.start)+" bis "+C.readable(r.end):C.readable(r.date))+
  "</td><td>"+(run?r.days+" Tage":num(r.value)+(snow?" cm":" °C")+(r.atBoundary?" · bereits vorhanden":""))+"</td></tr>"));
 const values=byYear.map(r=>run?r.days:snow?r.dayOfPeriod:r.dayOfYear);
 state.csv=[["Jahr","Ereignis","Datum/Start","Ende","Dauer/Wert", "Tag-im-Zeitraum"],
   ...byYear.map(r=>[r.year,label,r.date||r.start||"",r.end||"",run?r.days:r.value,
     snow?r.dayOfPeriod:r.dayOfYear])];
 state.fileName="DWD_Jahreszeitenrekord_"+st.id+"_"+event;
 addChart("rlSeasonChart",label+" · "+st.name,byYear.map(r=>String(r.year)),values,unit,"#b44e46");
 setExportState(byYear.length>1);
}
function clearSeason(){
 kpis("rlSeasonKpis",[]);tableRows("rlSeasonTable",[]);
 destroyChart();setExportState(false);
}
function render(){
 if(state.view==="calendar")calendarRender();
 else if(state.view==="seasons")seasonRender();
}
function updateWeatherStationOptions(){
 const index=state.weatherIndex;
 if(!index)return;
 const region=$("rlChangeState").value;
 const query=$("rlChangeSearch").value.trim().normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase();
 const options=$("rlChangeStation"),previous=options.value;
 const selected=index.stations.filter(s=>(!region||s.state===region)&&
  (!query||(s.name+" "+s.id+" "+s.state).normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().includes(query)));
 $("rlChangeCount").textContent=selected.length.toLocaleString("de-DE")+
  " von "+index.stations.length.toLocaleString("de-DE")+" geprüften Stundenstationen";
 options.replaceChildren();
 let group=null,last="";
 for(const s of selected){
  const name=s.state||"Ohne Bundesland";
  if(name!==last){
   group=document.createElement("optgroup");
   group.label=name;options.append(group);last=name;
  }
  const o=document.createElement("option");o.value=s.id;
  o.textContent=s.name+" ("+s.id+")";group.append(o);
 }
 const fallback=selected.find(s=>s.id===state.station?.id);
 options.value=selected.some(s=>s.id===previous)?previous:
  fallback?.id||selected[0]?.id||"";
}
async function initWeather(){
 if(state.weatherIndex){weatherRender();return;}
 message("rlChangeMeta","DWD-Stundenarchiv wird geprüft …");
 try{
  const doc=await fetchJson("data/rekordlabor/weather_turns/index.json",true);
  if(!doc?.ready||!Array.isArray(doc.stations)||!doc.stations.length){
   message("rlChangeMeta","Für die historischen Stundenänderungen ist noch kein vollständig verifiziertes DWD-Stundenarchiv veröffentlicht. Es werden keine Rekorde geschätzt oder erfunden.");
   $("rlChangesCoverage").textContent="DWD-CDC-Originalarchiv noch nicht veröffentlicht. Dieser Bereich zeigt bis zur erfolgreichen Messdatenprüfung bewusst keine Ranglisten.";
   setExportState(false);return;
  }
  state.weatherIndex=doc;
  const regions=$("rlChangeState");regions.replaceChildren();
  const all=document.createElement("option");all.value="";all.textContent="Alle Bundesländer";regions.append(all);
  for(const name of [...new Set(doc.stations.map(s=>s.state).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"de"))){
   const option=document.createElement("option");option.value=name;option.textContent=name;regions.append(option);
  }
  updateWeatherStationOptions();
  $("rlChangesCoverage").textContent="Historisches DWD-CDC-Stundenmessarchiv · "+
   doc.stations.length+" geprüfte Stationen in "+(regions.options.length-1)+
   " Bundesländern. Die Stationen sind regional ausgewählt und nicht flächendeckend. Nur tatsächliche Originalmessungen, stationsbezogene Messzeiträume und dokumentierte Datenlücken.";
  await loadWeather();
 }catch(e){message("rlChangeMeta","Stundenarchiv konnte nicht geprüft werden: "+e.message);}
}
async function loadWeather(){
 if(!state.weatherIndex)return;
 const station=state.weatherIndex.stations.find(x=>x.id===$("rlChangeStation").value);
 if(!station){
  state.weather=null;message("rlChangeMeta","Keine passende Stundenstation gefunden – Suchbegriff oder Bundesland ändern.");
  kpis("rlChangeKpis",[]);tableRows("rlChangeTable",[]);destroyChart();setExportState(false);
  return;
 }
 for(const option of $("rlChangeMetric").options)
  option.disabled=!station.metrics.includes(option.value);
 if(!station.metrics.includes($("rlChangeMetric").value))
  $("rlChangeMetric").value=station.metrics[0];
 const id=++state.weatherSerial;state.weather=null;setExportState(false);
 message("rlChangeMeta","Lade historische DWD-Stundenmessungen für "+station.name+" …");
 try{
  const doc=await fetchJson("data/rekordlabor/weather_turns/"+station.id+".json");
  if(id!==state.weatherSerial)return;
  if(doc?.station_id!==station.id||!doc.metrics)throw Error("Unvollständige Originaldaten");
  state.weather=doc;weatherRender();
 }catch(e){if(id===state.weatherSerial)message("rlChangeMeta","Fehler: "+e.message);}
}
function weatherRender(){
 const doc=state.weather;if(!doc){setExportState(false);return;}
 const metric=$("rlChangeMetric").value,hours=$("rlChangeHours").value;
 const dir=metric==="wind_direction"?"up":$("rlChangeDirection").value;
 const group=doc.metrics?.[metric],rank=group?.windows?.[hours]?.[dir];
 // DWD pressure P0 is STATION-HEIGHT pressure, not mean-sea-level
 // pressure (P). Block every legacy P0 dataset before displaying/exporting
 // misleading historical pressure comparisons.
 if(metric==="pressure"&&!(group?.source_column==="P"&&
    group?.pressure_reference==="sea_level"&&group?.source?.endsWith(" · P"))){
   message("rlChangeMeta",doc.name+" · Luftdruckdaten werden auf den korrekten DWD-Parameter P (auf Meereshöhe reduzierter Druck) umgestellt. Historische P0-Werte auf Stationshöhe werden ausdrücklich nicht mehr als Luftdruckrekorde gezeigt.");
   tableRows("rlChangeTable",[]);kpis("rlChangeKpis",[]);destroyChart();setExportState(false);return;
 }
 if(metric==="wind_direction"){
  $("rlChangeDirection").value="up";$("rlChangeDirection").disabled=true;
 }else $("rlChangeDirection").disabled=false;
 if(!Array.isArray(rank)||!rank.length){
  message("rlChangeMeta",doc.name+" · Für "+metric+" bei "+hours+
   " Stunden liegen keine verifizierten Originalmesswert-Paare vor.");
  tableRows("rlChangeTable",[]);kpis("rlChangeKpis",[]);destroyChart();setExportState(false);return;
 }
 const src=group.source,dates=group.period||{},cover=group.windows?.[hours]?.coverage||{};
 message("rlChangeMeta",doc.name+" · "+(metric==="pressure"?"auf Meereshöhe reduzierter Luftdruck (NN) · ":"")+src+" · Beobachtungen: "+(dates.start||"—")+" bis "+(dates.end||"—")+
  " UTC · "+num(cover.pairs||0,0)+" geprüfte Messwertpaare im "+hours+"-h-Fenster"+
  " · UTC-Zeitstempel, keine Lückeninterpolation · Archivdaten: "+(doc.generated_at||"—"));
 const scale=metric==="wind_direction"?"°":metric==="pressure"?"hPa":"°C";
 const top=rank[0];
 kpis("rlChangeKpis",[{value:(top.delta>0&&metric!=="wind_direction"?"+":"")+num(top.delta)+ " "+scale,label:"Größte Änderung im gewählten Archiv"},
  {value:top.end?.replace("T"," ").slice(0,16)+" UTC",label:"Endzeitpunkt"},
  {value:count(cover.pairs),label:"Verglichene Messwertpaare"}]);
 tableRows("rlChangeTable",rank.slice(0,20).map((r,i)=>{
   const tr=document.createElement("tr");tr.dataset.event=String(i);return '<tr data-rl-event="'+i+'"><td>'+(i+1)+'</td><td>'+esc(r.end)+"</td><td>"+
    num(r.delta)+" "+scale+"</td><td>"+num(r.before)+" → "+num(r.after)+" "+scale+"</td></tr>";
 }));
 const selected=state.selectedEvent;
 const target=Number.isInteger(selected)&&selected>=0&&selected<rank.length?rank[selected]:top;
 state.currentChange={metric,hours,dir,rank,top:target};
 const trace=Array.isArray(target.trace)?target.trace:[];
 state.csv=[["Zeitpunkt UTC",metric+" ("+scale+")"],...trace.map(r=>[r[0],r[1]])];
 state.fileName="DWD_Wetterumschwung_"+doc.station_id+"_"+metric+"_"+hours+"h";
 addChart("rlChangeChart","Wetterumschwung · "+doc.name+" · "+metric,
   trace.map(row=>row[0].slice(5).replace("T"," ")),trace.map(row=>row[1]),scale,"#bc6545");
 setExportState(trace.length>2);
 for(const row of $("rlChangeTable").querySelectorAll("tr[data-rl-event]"))
  row.addEventListener("click",()=>{state.selectedEvent=Number(row.dataset.event);weatherRender();});
}
async function exportChart(type){
 if(!state.chart||!state.csv.length)return;
 const file=state.fileName;
 if(type==="csv"){
  const q=x=>'"'+String(x??"").replace(/"/g,'""')+'"';
  const content="\ufeff"+state.csv.map(r=>r.map(q).join(";")).join("\r\n")+"\r\n";
  const blob=new Blob([content],{type:"text/csv;charset=utf-8"});
  saveBlob(blob,file+".csv");return;
 }
 if(type==="png"){
  const a=document.createElement("a");a.href=state.chart.toBase64Image("image/png",1);
  a.download=file+".png";document.body.append(a);a.click();a.remove();return;
 }
 try{
  if(!window.T850VectorExport)throw Error("Wissenschaftlicher Vektorexport nicht geladen");
  const exp=window.T850VectorExport,scene=exp.buildScene(state.chart,{
   title:state.chartLabel,subtitle:"DWD CDC · Originalstationsmessungen",
   axis:state.chart.options.scales.y.title.text,
   source:"Quelle: Deutscher Wetterdienst, Climate Data Center",
   metadata:["Stationsauswertung · "+state.fileName,"Nur echte Messwerte; Datenlücken bleiben erhalten",
    "Erstellt: "+new Date().toLocaleString("de-DE")]});
  if(type==="svg")exp.saveSvg([scene],file+".svg");
  else{
   const PDF=window.jspdf?.jsPDF;if(!PDF)throw Error("PDF-Bibliothek nicht verfügbar");
   const pdf=new PDF({orientation:"landscape",unit:"mm",format:"a3"});
   exp.drawPdf(pdf,scene);pdf.save(file+".pdf");
  }
 }catch(e){alert("Exportfehler: "+e.message);}
}
function saveBlob(blob,name){
 const href=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=href;a.download=name;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(href),2000);
}
function initDates(){
 const out=$("rlDay");
 for(let i=0;i<366;i++){
  const d=new Date(Date.UTC(2000,0,i+1)),md=d.toISOString().slice(5,10);
  const opt=document.createElement("option");
  opt.value=md;opt.textContent=d.toLocaleDateString("de-DE",{day:"numeric",month:"long",timeZone:"UTC"});
  out.append(opt);
 }
 out.value="11-14";
}
async function init(){
 initDates();
 Object.keys(tabs).forEach(key=>$(tabs[key][0]).addEventListener("click",()=>showTab(key)));
 for(const id of ["rlDay","rlCalMetric","rlCalOrder","rlSeasonMetric"])
  $(id).addEventListener("change",render);
 for(const id of ["rlChangeMetric","rlChangeHours","rlChangeDirection"])
  $(id).addEventListener("change",()=>{state.selectedEvent=null;weatherRender();});
 $("rlChangeStation").addEventListener("change",()=>{state.selectedEvent=null;loadWeather();});
 $("rlChangeState").addEventListener("change",()=>{state.selectedEvent=null;updateWeatherStationOptions();loadWeather();});
 $("rlChangeSearch").addEventListener("input",()=>{state.selectedEvent=null;updateWeatherStationOptions();loadWeather();});
 $("rlSearch").addEventListener("input",renderSuggestions);
 $("rlState").addEventListener("change",renderSuggestions);
 $("rlOnlyKL").addEventListener("change",renderSuggestions);
 for(const b of document.querySelectorAll("[data-rl-export]")){
  b.disabled=true;b.addEventListener("click",()=>exportChart(b.dataset.rlExport));
 }
 try{
  const [doc,klCatalogue]=await Promise.all([
    fetchJson("station_jahresanalyse_catalog.json"),
    fetchJson("data/rekordlabor/calendar/index.json",true)
  ]);
  state.klIndex=new Map((klCatalogue?.ready&&Array.isArray(klCatalogue.stations)?
    klCatalogue.stations:[]).map(row=>[String(row.id).padStart(5,"0"),row]));
  const totalKL=state.klIndex.size;
  const countRain=[...state.klIndex.values()].filter(st=>st.metrics?.rain).length;
  const countSun=[...state.klIndex.values()].filter(st=>st.metrics?.sun).length;
  $("rlKlCount").textContent=totalKL.toLocaleString("de-DE")+
    " DWD-Stationen mit geprüften KL-Reihen · "+countRain+
    " Niederschlag · "+countSun+" Sonne";
  if(doc.schema!==1||!doc.stations?.length)throw Error("Unvollständiger DWD-Stationskatalog");
  state.catalog=doc;
  const names=[...new Set(doc.stations.map(s=>s.state).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"de"));
  for(const name of names){const op=document.createElement("option");op.value=name;op.textContent=name;$("rlState").append(op);}
  const wanted=new URLSearchParams(location.search).get("station");
  const initial=doc.stations.find(s=>s.id===wanted&&validStation(s))||
    doc.stations.find(s=>s.id==="01420")||doc.stations.find(validStation);
  initMap();renderSuggestions();if(initial)await selectStation(initial);
 }catch(e){message("rlStation","Stationskatalog nicht verfügbar: "+e.message);}
 const tab=new URLSearchParams(location.search).get("view");
 if(tabs[tab])showTab(tab);
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
})();
