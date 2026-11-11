/* DWD station annual curves. Only measured observations; missing values remain null. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const NOW=new Date(),CURRENT=NOW.getUTCFullYear(),MISSING=-32768;
const RAW="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/";
const COLORS=["#c64f44","#1c82bc","#7e58b6","#2b9778","#cc8e30"];
const AXIS=Array.from({length:365},(_,i)=>{
 const d=new Date(Date.UTC(2001,0,i+1));return d.toISOString().slice(5,10);
});
const MONTHS=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
const cache=new Map();
let stations=[],station=null,kind="temp",mode="daily",metric=2,years=[],selected=new Set();
let payload=null,chart=null,serial=0,lastExport=null,fillYear=null;
const WARM_FILL="rgba(222,44,41,0.58)",COLD_FILL="rgba(31,96,217,0.58)";
const number=n=>Number.isFinite(n)?n.toLocaleString("de-DE",{maximumFractionDigits:1}):"–";
const isNumber=n=>typeof n==="number"&&Number.isFinite(n);
const text=(id,value)=>{$(id).textContent=value;};
function status(message,error=false){text("sjaStatus",message);$("sjaStatus").classList.toggle("error",error);}
const clean=s=>String(s||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLocaleLowerCase("de").trim();
const fromDate=d=>d.slice(5,10);
function isLeap(y){return y%4===0&&(y%100!==0||y%400===0);}
function slot(y,md){
 if(md==="02-29")return -1;
 const m=Number(md.slice(0,2)),d=Number(md.slice(3,5));
 const date=Date.UTC(y,m-1,d),begin=Date.UTC(y,0,1);
 const index=Math.round((date-begin)/86400000);
 return index-((isLeap(y)&&m>2)?1:0);
}
async function request(path,optional=false){
 if(cache.has(path))return cache.get(path);
 const promise=(async()=>{
  for(const url of [path,RAW+path]){
   try{
    const response=await fetch(url,{cache:"force-cache"});
    if(response.ok)return response.json();
   }catch(_){/* github pages or raw mirror may be temporarily inaccessible */}
  }
  if(optional)return null;
  throw Error("Datenquelle nicht erreichbar: "+path);
 })();
 cache.set(path,promise);
 try{return await promise;}catch(e){cache.delete(path);throw e;}
}
function png(){
 if(!chart||!station)return;
 const source=chart.canvas;
 const c=document.createElement("canvas"),scale=2;
 c.width=Math.max(1200,source.width*scale);c.height=source.height*scale+175;
 const ctx=c.getContext("2d");
 ctx.fillStyle="#fff";ctx.fillRect(0,0,c.width,c.height);
 ctx.fillStyle="#162d40";ctx.font="bold 28px Arial";
 ctx.fillText("DWD · "+station.name+" · "+$("sjaChartTitle").textContent,25,42,c.width-50);
 ctx.font="17px Arial";ctx.fillStyle="#4e687d";
 ctx.fillText("Climate Dashboard Deutschland · Messwerte ohne synthetische Ergänzungen",25,76,c.width-50);
 if(kind==="temp"&&Number.isInteger(fillYear)){
  ctx.fillStyle="#de2c29";ctx.fillRect(25,93,15,15);
  ctx.fillStyle="#4e687d";ctx.font="16px Arial";
  ctx.fillText("Wärmer als 1991–2020",46,106);
  ctx.fillStyle="#1f60d9";ctx.fillRect(270,93,15,15);
  ctx.fillStyle="#4e687d";ctx.fillText("Kühler als 1991–2020 · Fläche für "+fillYear,291,106);
 }
 ctx.drawImage(source,0,136,c.width,source.height*scale);
 ctx.fillText("Quelle: DWD CDC · Referenz 1991–2020 · fehlende Werte bleiben Lücken",25,c.height-16,c.width-50);
 const a=document.createElement("a");a.download="DWD_Jahresanalyse_"+station.id+"_"+kind+".png";
 a.href=c.toDataURL("image/png");document.body.append(a);a.click();a.remove();
}
function csv(){
 if(!lastExport||!station)return;
 const {labels,datasets}=lastExport;
 const quote=v=>'"'+String(v??"").replace(/"/g,'""')+'"';
 const rows=[["Zeitraum",...datasets.map(d=>d.label)]];
 labels.forEach((label,i)=>rows.push([label,...datasets.map(d=>d.data[i]??"")]));
 const blob=new Blob(["\ufeff"+rows.map(row=>row.map(quote).join(";")).join("\r\n")+"\r\n"],{type:"text/csv;charset=utf-8"});
 const url=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=url;a.download="DWD_Jahresanalyse_"+station.id+"_"+kind+".csv";document.body.append(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),3000);
}
function makeChart(labels,datasets,title,unit,chartType="line",note=""){
 if(chart){chart.destroy();chart=null;}
 if(typeof Chart==="undefined"){status("Chart.js konnte nicht geladen werden – Diagramm nicht verfügbar.",true);return;}
 lastExport={labels,datasets:datasets.map(d=>({label:d.label,data:[...d.data]}))};
 const theme=window.matchMedia?.("(prefers-color-scheme: dark)").matches&&document.documentElement.dataset.theme==="dark";
 const color=theme?"#d5e3ed":"#405971";
 const records=datasets.map(d=>({
   label:d.label,data:d.data,type:d.type||chartType,
   borderColor:d.color||"#777",backgroundColor:d.fillColor||d.color||"#777",
   fill:d.fillConfig||false,
   borderWidth:d.borderWidth??2,tension:0,spanGaps:false,pointRadius:0,
   pointHoverRadius:4,barPercentage:.85,categoryPercentage:.8,
   borderDash:d.dash||[],order:d.order??1,
 }));
 chart=new Chart($("sjaChart"),{
  type:chartType,data:{labels,datasets:records},
  options:{responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
   interaction:{mode:"index",intersect:false},plugins:{
    filler:{propagate:false},
    legend:{position:"bottom",labels:{color,boxWidth:14,usePointStyle:true}},
    tooltip:{callbacks:{label:ctx=>ctx.dataset.label+": "+(isNumber(ctx.raw)?number(ctx.raw)+" "+unit:"keine Messung")}}
   },scales:{x:{grid:{display:false},ticks:{color,maxTicksLimit:13,maxRotation:0,autoSkip:true}},
    y:{ticks:{color},title:{display:true,text:unit,color},grid:{color:theme?"#3b526855":"#6d8ca32c"}}}}
 });
 text("sjaChartTitle",title);
 $("sjaPng").disabled=false;$("sjaCsv").disabled=false;
 if(note)status(note);
}
function populateModes(){
 const options=kind==="temp"?[["daily","Tagesverlauf"]]:
   kind==="precip"?[["cumulative","Kumulierte Monatssummen"],["monthly","Monatssummen"],["daily","Aktuelle Tageswerte"]]:
   [["daily","Hydrologischer Jahresgang"]];
 $("sjaMode").replaceChildren();
 for(const [value,label] of options){const o=document.createElement("option");o.value=value;o.textContent=label;$("sjaMode").append(o);}
 mode=options[0][0];
 $("sjaMetricWrap").hidden=kind!=="temp";
 $("sjaFillControls").hidden=kind!=="temp";
}
function renderYearOptions(available,initial){
 const old=new Set(selected);
 years=available.slice().sort((a,b)=>b-a);
 selected=new Set(years.filter(y=>old.has(y)).slice(0,5));
 if(!selected.size)for(const y of initial.filter(y=>years.includes(y)).slice(0,2))selected.add(y);
 if(!selected.size)years.slice(0,2).forEach(y=>selected.add(y));
 const area=$("sjaYears");area.replaceChildren();
 for(const year of years){
  const label=document.createElement("label"),input=document.createElement("input");
  input.type="checkbox";input.checked=selected.has(year);input.value=String(year);
  input.addEventListener("change",()=>{
   if(input.checked&&selected.size>=5){input.checked=false;status("Bitte höchstens fünf Vergleichsjahre wählen.",true);return;}
   if(input.checked)selected.add(year);else selected.delete(year);
   render();
  });
  label.append(input,document.createTextNode(String(year)+(kind==="snow"&&year===CURRENT+1?" (aktuell)":"")));
  area.append(label);
 }
 text("sjaYearHint",kind==="snow"?"Hydrologische Jahre · bis zu fünf gleichzeitig":"Kalenderjahre · bis zu fünf gleichzeitig");
}
async function temperatureArchive(st){
 const doc=await request(st.temp_file);
 if(doc?.format!=="dwd-tx-tn-tm-zlib16-v1"||!Array.isArray(doc.years)||!doc.data)
  throw Error("Unbekanntes Temperatur-Archivformat.");
 if(typeof DecompressionStream==="undefined")throw Error("Der Browser unterstützt die nötige Deflate-Dekompression nicht.");
 const bin=Uint8Array.from(atob(doc.data),c=>c.charCodeAt(0));
 const bytes=await new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream("deflate"))).arrayBuffer();
 if(bytes.byteLength!==doc.years.length*366*3*2)throw Error("Temperaturarchiv unvollständig.");
 const view=new DataView(bytes),map=new Map();
 for(let j=0;j<doc.years.length;j++){
  const a=Array.from({length:365},()=>[null,null,null]);
  for(let i=0;i<365;i++){
   const idx=slot(Number(doc.years[j]),AXIS[i]);
   for(let k=0;k<3;k++){
    const raw=view.getInt16((j*366*3+idx*3+k)*2,true);
    a[i][k]=raw===MISSING?null:raw/10;
   }
  }
  map.set(Number(doc.years[j]),a);
 }
 return map;
}
async function currentTemperature(st){
 const result=Array.from({length:365},()=>[null,null,null]);
 const tasks=[];
 for(let month=1;month<=NOW.getUTCMonth()+1;month++)tasks.push(request(
   "station_climate_days_current/"+CURRENT+"-"+String(month).padStart(2,"0")+".json",true));
 const docs=await Promise.all(tasks);
 for(const doc of docs){
  if(!doc||Number(doc.year)!==CURRENT)continue;
  const values=doc.stations?.[st.id];
  if(!Array.isArray(values))continue;
  values.forEach((pair,i)=>{
   const md=String(doc.month).padStart(2,"0")+"-"+String(i+1).padStart(2,"0");
   const index=slot(CURRENT,md);
   if(index<0||index>=365||!Array.isArray(pair))return;
   for(let k=0;k<3;k++)result[index][k]=isNumber(pair[k+2])?pair[k+2]/10:null;
  });
 }
 return result;
}
function referenceTemp(history,k){
 return AXIS.map((_,i)=>{
  const values=[];for(let y=1991;y<=2020;y++){const v=history.get(y)?.[i]?.[k];if(isNumber(v))values.push(v);}
  return values.length>=15?Math.round(values.reduce((a,b)=>a+b,0)/values.length*10)/10:null;
 });
}
async function loadTemp(st){
 const history=await temperatureArchive(st);
 history.set(CURRENT,await currentTemperature(st));
 return {history};
}
async function loadPrecip(st){
 const profile=await request(st.precip_file);
 const daily=Array(365).fill(null),months=Array(12).fill(null);
 const tasks=[];
 for(let m=1;m<=NOW.getUTCMonth()+1;m++)tasks.push(request("station_precip_current/"+String(m).padStart(2,"0")+".json",true));
 const files=await Promise.all(tasks);
 for(const doc of files){
  if(!doc||Number(doc.year)!==CURRENT)continue;
  const month=Number(doc.month)-1,values=doc.stations?.[st.id];
  if(!Array.isArray(values))continue;
  let sum=0,complete=true;
  values.forEach((v,i)=>{
   const md=String(month+1).padStart(2,"0")+"-"+String(i+1).padStart(2,"0");
   const index=slot(CURRENT,md);if(index>=0&&index<365)daily[index]=isNumber(v)?v:null;
   if(!isNumber(v))complete=false;else sum+=v;
  });
  // Only finished, fully measured calendar months may enter annual sums.
  if(complete&&values.length===new Date(Date.UTC(CURRENT,month+1,0)).getUTCDate())
   months[month]=Math.round(sum*10)/10;
 }
 return {profile,daily,months};
}
async function loadSnow(st){
 const [archive,profile,current]=await Promise.all([
  request(st.snow_file),request(st.snow_profile,true),request(st.snow_current,true)
 ]);
 if(!Array.isArray(archive?.years)||!Array.isArray(archive?.month_days))throw Error("Hydrologisches Schnee-Tagesarchiv fehlt.");
 return {archive,profile,current};
}
async function load(){
 if(!station)return;
 const id=++serial,st=station,what=kind;
 if(chart){chart.destroy();chart=null;}lastExport=null;
 $("sjaPng").disabled=true;$("sjaCsv").disabled=true;
 status("Lade geprüfte DWD-"+(what==="temp"?"Temperatur":what==="precip"?"Niederschlags":"Schneehöhen")+"daten …");
 populateModes();
 try{
  let doc;
  if(what==="temp")doc=await loadTemp(st);
  else if(what==="precip")doc=await loadPrecip(st);
  else doc=await loadSnow(st);
  if(id!==serial)return;
  payload=doc;
  if(what==="temp"){
   const list=[...doc.history.keys()].sort((a,b)=>b-a);
   const nonempty=list.filter(y=>doc.history.get(y)?.some(row=>row.some(isNumber)));
   renderYearOptions(nonempty,[CURRENT,CURRENT-1]);
  }else if(what==="precip"){
   const historical=(doc.profile.monthly_history||[]).filter(row=>row.months?.some(isNumber)).map(row=>Number(row.year));
   renderYearOptions([CURRENT,...historical],[CURRENT,CURRENT-1]);
  }else{
   const historical=doc.archive.years.filter(row=>row.values?.some(isNumber)).map(row=>Number(row.year));
   const currentYear=Number(doc.current?.hydrological_year);
   renderYearOptions(Number.isInteger(currentYear)&&doc.current?.rows?.length?[currentYear,...historical]:historical,
     [currentYear,Math.max(...historical)]);
  }
  render();
 }catch(err){if(id!==serial)return;payload=null;$("sjaYears").replaceChildren();status(err.message,true);}
}
function cumulative(values){
 let sum=0,good=true;return values.map(v=>{
  if(!isNumber(v))good=false;
  if(!good)return null;
  sum+=v;return Math.round(sum*10)/10;
 });
}
// Per-calendar-position all-time bounds from genuinely observed historical values.
// No interpolation, no zeros for gaps, and no incomplete current year in records.
function historicalExtremes(curves,size){
 const minimum=Array(size).fill(null),maximum=Array(size).fill(null);
 for(const curve of curves){
  if(!Array.isArray(curve))continue;
  for(let i=0;i<size;i++){
   const value=curve[i];
   if(!isNumber(value))continue;
   if(minimum[i]===null||value<minimum[i])minimum[i]=value;
   if(maximum[i]===null||value>maximum[i])maximum[i]=value;
  }
 }
 return {minimum,maximum};
}
function addExtremes(datasets,values,unitLabel){
 const {minimum,maximum}=values;
 if(!minimum.some(isNumber)&&!maximum.some(isNumber))return false;
 const dash=[8,5];
 datasets.push(
  {label:"Absolutes Minimum · "+unitLabel,data:minimum,color:"#397ab9",dash,borderWidth:1.7,order:2},
  {label:"Absolutes Maximum · "+unitLabel,data:maximum,color:"#ba6b34",dash,borderWidth:1.7,order:2}
 );
 return true;
}
function updateTemperatureFillYear(){
 const candidates=[...selected].sort((a,b)=>b-a);
 if(!candidates.includes(fillYear))fillYear=candidates[0]??null;
 const control=$("sjaFillControls"),picker=$("sjaFillYear");
 control.hidden=candidates.length===0;
 picker.replaceChildren();
 for(const year of candidates){
  const option=document.createElement("option");option.value=String(year);
  option.textContent=String(year)+(year===CURRENT?" (aktuell)":"");
  picker.append(option);
 }
 if(fillYear!==null)picker.value=String(fillYear);
 return fillYear;
}
function renderTemp(){
 const {history}=payload,k=Number($("sjaMetric").value),name=["Tmax","Tmin","Tagesmittel"][k];
 const reference=referenceTemp(history,k);
 const highlightedYear=updateTemperatureFillYear();
 const datasets=[{label:"1991–2020 · Mittel",data:reference,color:"#525e6b",dash:[5,5],borderWidth:2,order:3}];
 let observed=0;
 [...selected].sort((a,b)=>a-b).forEach((year,i)=>{
  const data=history.get(year)?.map(row=>row[k])||Array(365).fill(null);
  observed+=data.filter(isNumber).length;
  datasets.push({
   label:String(year)+(year===CURRENT?" · vorläufig":""),data,color:COLORS[i%COLORS.length],order:1,
   // Chart.js filler: absolute target index 0 is the 1991–2020 daily mean.
   // Only one year is shaded; other selected years remain clean line plots.
   fillConfig:year===highlightedYear?{target:0,above:WARM_FILL,below:COLD_FILL}:false
  });
 });
 const historical=[...history.entries()].filter(([year])=>year<CURRENT)
  .map(([,rows])=>rows.map(row=>row[k]));
 addExtremes(datasets,historicalExtremes(historical,365),"Kalendertag");
 makeChart(AXIS.map(x=>x.slice(3)+"."+x.slice(0,2)),datasets,
  name+" · Tagesverlauf", "°C","line",
  observed+" echte Tagesmesswerte in den gewählten Jahren. Referenzkurve aus den verfügbaren Jahren 1991–2020 (mindestens 15 Werte je Kalendertag). "+(highlightedYear===null?"":"Abweichungsfläche "+highlightedYear+": Rot = wärmer, Blau = kühler. ")+"Gestrichelt: absolutes Tagesminimum und Tagesmaximum der vorhandenen historischen Messreihe (ohne laufendes Jahr). Fehlende Werte bleiben Lücken.");
 text("sjaStats", "");
}
function precipBaseline(profile){
 const curve=profile.climate_mean_cumulative||[];
 const ends=[31,59,90,120,151,181,212,243,273,304,334,365],out=[];let prev=0;
 for(const end of ends){
  const value=curve[end-1];
  out.push(isNumber(value)?Math.round((value-prev)*10)/10:null);
  if(!isNumber(value))prev=NaN;else prev=value;
 }
 return out;
}
function renderPrecip(){
 const {profile,daily,months}=payload;
 const monthlyMap=new Map((profile.monthly_history||[]).map(row=>[Number(row.year),row.months]));
 const climatology=precipBaseline(profile);
 let datasets=[],labels=MONTHS,unit="mm",type="line",note="";
 const selectedYears=[...selected].sort((a,b)=>a-b);
 const allHistorical=(profile.monthly_history||[]).filter(row=>Number(row.year)<CURRENT&&Array.isArray(row.months));
 if(mode==="daily"){
  labels=AXIS.map(md=>md.slice(3)+"."+md.slice(0,2));
  datasets=[{label:String(CURRENT)+" · Tagesniederschlag",data:daily,color:"#247bb3",type:"bar"}];
  type="bar";
  note="Aktuelle RR-Tagesmessungen "+CURRENT+" (vorläufig). Für ältere Jahre sind in diesem Archiv nur vollständige Monatssummen verfügbar; historische Tages-Minima/-Maxima sind deshalb hier nicht seriös darstellbar.";
 }else{
  const baseline=mode==="cumulative"?cumulative(climatology):climatology;
  datasets=[{label:"1991–2020 · Mittel",data:baseline,color:"#536374",dash:[5,5],type:"line",order:4}];
  for(let i=0;i<selectedYears.length;i++){
   const year=selectedYears[i];
   const raw=year===CURRENT?months:(monthlyMap.get(year)||Array(12).fill(null));
   datasets.push({label:String(year)+(year===CURRENT?" · vorläufig":""),data:mode==="cumulative"?cumulative(raw):raw,
    color:COLORS[i%COLORS.length],type:mode==="cumulative"?"line":"bar"});
  }
  // For running sums only full historical calendar years qualify for records;
  // for month totals each month must be fully observed, independently.
  const observed=mode==="cumulative"?
   allHistorical.filter(row=>row.months.length===12&&row.months.every(isNumber))
    .map(row=>cumulative(row.months)):
   allHistorical.map(row=>row.months);
  addExtremes(datasets,historicalExtremes(observed,12),
   mode==="cumulative"?"kumuliert, Monatsende":"Kalendermonat");
  type=mode==="cumulative"?"line":"bar";
  note="Historische Monatssummen aus vollständig beobachteten DWD-RR-Monaten. Gestrichelt: absolute Monats-Minima/-Maxima"+(mode==="cumulative"?" aus vollständig beobachteten Kalenderjahren":"")+" der vorhandenen Messreihe. Laufende und fehlende Monate werden nicht als vollständige Summen gerechnet.";
 }
 makeChart(labels,datasets,mode==="daily"?"Tagesniederschlag "+CURRENT:mode==="monthly"?"Monatsniederschlag":"Niederschlag · kumuliertes Kalenderjahr",unit,type,note);
 text("sjaStats","");
}
function renderSnow(){
 const {archive,profile,current}=payload;
 const axis=archive.month_days,med=new Map((profile?.daily||[]).map(row=>[row[0],row[2]]));
 const labels=axis.map(md=>md.slice(3)+"."+md.slice(0,2));
 const datasets=[
  {label:"1991–2020 · Tagesmedian",data:axis.map(md=>isNumber(med.get(md))?med.get(md):null),color:"#516577",dash:[5,5],order:3},
 ];
 // Consistent bounds: only quality-approved (>=98%) historical hydrological years,
 // matching the snow climatology's accepted-year population.
 const accepted=(archive.years||[]).filter(row=>row.accepted===true&&
  Array.isArray(row.values)&&row.values.length===axis.length).map(row=>row.values);
 addExtremes(datasets,historicalExtremes(accepted,axis.length),"Hydrologischer Tag");
 const yearMap=new Map(archive.years.map(row=>[Number(row.year),row]));
 const currentYear=Number(current?.hydrological_year);
 const curDays=new Map((current?.rows||[]).map(row=>[fromDate(row[0]),row[1]]));
 let count=0;
 [...selected].sort((a,b)=>a-b).forEach((year,i)=>{
  const values=year===currentYear&&curDays.size?
    axis.map(md=>isNumber(curDays.get(md))?curDays.get(md):null):
    (yearMap.get(year)?.values||axis.map(()=>null));
  count+=values.filter(isNumber).length;
  datasets.push({label:"Hydrol. Jahr "+year+(year===currentYear?" · aktuell":yearMap.get(year)?.accepted?"":" · unvollständig"),
   data:values,color:COLORS[i%COLORS.length],order:1});
 });
 makeChart(labels,datasets,"Schneehöhe · 1. November bis 31. Oktober","cm","line",
  count+" beobachtete Tageswerte in den gewählten hydrologischen Jahren. Median 1991–2020; gestrichelt: absolutes Tagesminimum und Tagesmaximum aus qualitätsgeprüften historischen Jahren (≥98 %). Unvollständige Jahre sind gekennzeichnet. Keine Lückenfüllung.");
 text("sjaStats","");
}
function render(){
 if(!payload||!station)return;
 mode=$("sjaMode").value;
 if(kind==="temp")renderTemp();
 else if(kind==="precip")renderPrecip();
 else renderSnow();
}
function choose(st){
 station=st;
 text("sjaSelected",st.name+" · Station "+st.id+(st.state?" · "+st.state:""));
 for(const type of ["temp","precip","snow"]){
  const button=$("sja"+type[0].toUpperCase()+type.slice(1));
  button.disabled=!st[type];
 }
 if(!st[kind])kind=st.temp?"temp":st.precip?"precip":"snow";
 for(const button of document.querySelectorAll("[data-kind]")){
  const active=button.dataset.kind===kind;
  button.classList.toggle("active",active);button.setAttribute("aria-pressed",String(active));
 }
 selected=new Set();fillYear=null;renderMatches();load();
}
function renderMatches(){
 const query=clean($("sjaSearch").value),region=$("sjaState").value;
 let matches=stations.filter(s=>(!region||s.state===region)&&(!query||clean(s.name+" "+s.id+" "+s.state).includes(query)));
 if(!query&&station)matches=[station,...matches.filter(s=>s.id!==station.id)];
 matches=matches.slice(0,25);
 const root=$("sjaMatches");root.replaceChildren();
 for(const st of matches){
  const button=document.createElement("button");button.type="button";
  button.className=st.id===station?.id?"active":"";
  const title=document.createElement("strong");title.textContent=st.name;
  const details=document.createElement("small");details.textContent=st.id+" · "+st.state+" · "+
   ["temp","precip","snow"].filter(k=>st[k]).map(k=>({temp:"Temp.",precip:"Niederschlag",snow:"Schnee"})[k]).join(" / ");
  button.append(title,details);button.addEventListener("click",()=>choose(st));root.append(button);
 }
 if(!matches.length){const el=document.createElement("span");el.textContent="Keine passende Station mit veröffentlichter Jahresreihe.";root.append(el);}
}
async function init(){
 $("sjaSearch").addEventListener("input",renderMatches);$("sjaState").addEventListener("change",renderMatches);
 $("sjaMetric").addEventListener("change",render);$("sjaMode").addEventListener("change",render);
 $("sjaFillYear").addEventListener("change",()=>{fillYear=Number($("sjaFillYear").value);render();});
 $("sjaPng").addEventListener("click",png);$("sjaCsv").addEventListener("click",csv);
 for(const b of document.querySelectorAll("[data-kind]"))b.addEventListener("click",()=>{
  if(!station||!station[b.dataset.kind])return;
  kind=b.dataset.kind;selected=new Set();choose(station);
 });
 try{
  const doc=await request("station_jahresanalyse_catalog.json");
  if(doc.schema!==1||!Array.isArray(doc.stations)||!doc.stations.length)throw Error("Stationskatalog unvollständig.");
  stations=doc.stations;
  const names=[...new Set(stations.map(s=>s.state).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"de"));
  for(const name of names){const o=document.createElement("option");o.value=name;o.textContent=name;$("sjaState").append(o);}
  text("sjaInventory",stations.length.toLocaleString("de-DE")+" Stationen · "+doc.totals.temp+" Temperatur · "+doc.totals.precip+" Niederschlag · "+doc.totals.snow+" Schnee");
  const wanted=(new URLSearchParams(location.search)).get("station");
  const initial=stations.find(s=>s.id===wanted)||stations.find(s=>s.id==="01420")||stations[0];
  choose(initial);
 }catch(e){status("Stationskatalog nicht erreichbar: "+e.message,true);text("sjaInventory","Keine Stationsdaten");}
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
