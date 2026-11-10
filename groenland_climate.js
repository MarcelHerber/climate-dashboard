/* DMI Greenland climate normals / anomalies / rankings and record-map overlays.
   Every anomaly references >=24 quality-screened 1991–2020 source years. */
(()=>{
"use strict";
const $=id=>document.getElementById(id),YEAR=new Date().getUTCFullYear();
const NOW=new Date(),MIN_REFERENCE_YEARS=24;
const MONTHS=["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
const MODES={
 high:{label:"Höchste Temperatur",unit:"°C",direction:"max"},
 low:{label:"Tiefste Temperatur",unit:"°C",direction:"min"},
 gust:{label:"Stärkste 3-s-Böe",unit:"m/s",direction:"max"},
 rain:{label:"Größter 24-h-Niederschlag",unit:"mm",direction:"max"}
};
const COLORS={positive:"#d96654",negative:"#347daf"};
const fmt=(n,dec=1)=>Number.isFinite(n)?n.toLocaleString("de-DE",{minimumFractionDigits:dec,maximumFractionDigits:dec}):"–";
const finite=n=>typeof n==="number"&&Number.isFinite(n);
const round=(n,d=3)=>Math.round(n*10**d)/10**d;
let stationId="",stationName="",rows=[],chart=null,climate=null,lastMode=null,yearSelect=0;
let fetchSerial=0,recordCache=null,climateCache=new Map(),activeView="",lastError="";
function checkCoverage(row,resolution,threshold,now=NOW){
 const year=Number(String(row.date).slice(0,4));
 if(!Number.isInteger(year)||year<1953||year>now.getUTCFullYear()||!finite(row.value))return false;
 let days;
 if(resolution==="year"){
  // Do not rank incomplete current-year annual products as finished years.
  if(year===now.getUTCFullYear())return false;
  days=(Date.UTC(year+1,0,1)-Date.UTC(year,0,1))/86400000;
 }else{
  const month=Number(String(row.date).slice(5,7));
  if(!Number.isInteger(month)||month<1||month>12)return false;
  if(year===now.getUTCFullYear()&&month>=now.getUTCMonth()+1)return false;
  days=new Date(Date.UTC(year,month,0)).getUTCDate();
 }
 // A DMI period with unknown aggregation coverage is *not* a verified complete period.
 return finite(row.count)&&row.count>=Math.ceil(days*threshold-1e-9);
}
function trend(values){
 if(values.length<15)return null;
 const xs=values.map(x=>x.year),ys=values.map(x=>x.anomaly);
 const n=values.length,x0=xs.reduce((a,b)=>a+b,0)/n,y0=ys.reduce((a,b)=>a+b,0)/n;
 const dx=xs.reduce((a,x)=>a+(x-x0)**2,0);
 if(dx<=0||Math.max(...xs)-Math.min(...xs)<20)return null;
 const slope=values.reduce((a,x)=>a+(x.year-x0)*(x.anomaly-y0),0)/dx;
 return {slopePerDecade:round(slope*10),slope,intercept:y0-slope*x0,years:n};
}
function calculate(rows,resolution,month,threshold,now=NOW){
 const eligible=rows.filter(x=>checkCoverage(x,resolution,threshold,now))
   .filter(x=>resolution==="year"||Number(x.date.slice(5,7))===month)
   .map(x=>({...x,year:Number(x.date.slice(0,4))}));
 const reference=eligible.filter(x=>x.year>=1991&&x.year<=2020);
 const years=new Set(reference.map(x=>x.year));
 if(years.size<MIN_REFERENCE_YEARS)
  return {normal:null,refCount:years.size,eligible,ranked:[],trend:null,
          error:"Für 1991–2020 sind nur "+years.size+" von mindestens "+
                MIN_REFERENCE_YEARS+" ausreichend abgedeckten Jahren verfügbar."};
 const normal=reference.reduce((acc,x)=>acc+x.value,0)/reference.length;
 const ranked=eligible.map(x=>({
  ...x,anomaly:round(x.value-normal),coverage:round(x.count/
   (resolution==="year"?(Date.UTC(x.year+1,0,1)-Date.UTC(x.year,0,1))/86400000:
     new Date(Date.UTC(x.year,month,0)).getUTCDate()),3)
 }));
 const byWarm=ranked.slice().sort((a,b)=>b.anomaly-a.anomaly||a.year-b.year);
 const byCold=ranked.slice().sort((a,b)=>a.anomaly-b.anomaly||a.year-b.year);
 return {normal:round(normal),refCount:reference.length,eligible,ranked,
  warm:byWarm,cold:byCold,trend:trend(ranked),error:null};
}
function setText(id,value){$(id).textContent=value;}
function status(message,isError=false){
 const e=$("grClimateStatus");e.textContent=message;e.classList.toggle("gr-error",isError);
}
function mapStatus(message,isError=false){
 const e=$("grMapRecordStatus");e.textContent=message;e.classList.toggle("gr-error",isError);
}
function modeValue(mode,value){
 return fmt(value)+" "+MODES[mode].unit;
}
function recordEntries(mode){
 const values=recordCache?.modes?.[mode]||{};
 const names=new Map((window.GreenlandDmiMap?.getCatalogue()||[]).map(s=>[s.id,s]));
 const ordered=Object.entries(values).filter(([sid,record])=>names.has(sid)&&finite(record.value))
  .sort((a,b)=>MODES[mode].direction==="min"?a[1].value-b[1].value:b[1].value-a[1].value);
 return {ordered,names};
}
function fillRanking(){
 const area=$("grMapRanking"),list=$("grMapRankingList");
 list.replaceChildren();
 if(lastMode==="latest"||!recordCache){area.hidden=true;return;}
 const {ordered,names}=recordEntries(lastMode);
 area.hidden=false;
 setText("grMapRankingTitle","Rangliste · "+MODES[lastMode].label);
 for(const [sid,record] of ordered.slice(0,12)){
  const li=document.createElement("li"),btn=document.createElement("button");
  btn.type="button";btn.className="gr-rank-station";
  btn.textContent=names.get(sid).name+" · "+modeValue(lastMode,record.value)+
   " ("+record.year+")";
  btn.addEventListener("click",()=>{
   // The station list supports search; remove filters before selecting from map ranks.
   $("grSearch").value="";$("grStatusFilter").value="all";
   window.GreenlandDmiMap?.selectStation(sid);
  });
  li.append(btn);list.append(li);
 }
 const own=$("grMapStationRanks");own.replaceChildren();
 if(stationId&&recordCache?.modes?.[lastMode]?.[stationId]){
  const value=recordCache.modes[lastMode][stationId];
  for(const point of value.top){
   const li=document.createElement("li");
   li.textContent=point.year+": "+modeValue(lastMode,point.value)+
     (point.qc==="manual"?"":" · vorläufig");
   own.append(li);
  }
  setText("grMapStationRanksTitle",stationName+
    " · "+value.count+" verfügbare Jahreswerte ("+value.first+"–"+value.last+")");
 }else{
  setText("grMapStationRanksTitle",stationName?stationName+" · keine verfügbaren Jahresrekorde":"Station auswählen");
 }
}
function applyMap(){
 lastMode=$("grMapMode").value;
 if(lastMode==="latest"){
  window.GreenlandDmiMap?.applyRecordMap("latest");
  $("grMapRanking").hidden=true;
  mapStatus("Farben zeigen die jüngsten gültigen DMI-Temperaturmittel; Grau = kein Wert.");
  return;
 }
 if(!recordCache){
  $("grMapRanking").hidden=true;
  mapStatus("Historische DMI-Rekorde sind derzeit nicht verfügbar. Es werden keine Ersatzwerte angezeigt.",true);
  window.GreenlandDmiMap?.applyRecordMap(lastMode,{});
  return;
 }
 const data=recordCache.modes[lastMode]||{};
 window.GreenlandDmiMap?.applyRecordMap(lastMode,data);
 const n=Object.keys(data).length;
 mapStatus(MODES[lastMode].label+" · "+n+" Stationen mit gültigen DMI-Jahresextremen."+
  " Quelle: jährliche Originalmesswerte; letzter Abruf "+recordCache.generated_utc.slice(0,10)+
  ". Fehlende Werte grau. Keine Werteinschätzung für Stationen ohne Daten.");
 fillRanking();
}
async function loadRecordsForMap(){
 try{
  const response=await fetch("data/dmi_greenland_records.json",{cache:"no-store"});
  if(!response.ok)throw Error("HTTP "+response.status);
  const doc=await response.json();
  if(doc.schema!==1||!doc.modes||Object.values(doc.modes).reduce((a,v)=>a+Object.keys(v).length,0)<60)
   throw Error("unvollständiger Datensatz");
  recordCache=doc;
  applyMap();
 }catch(err){
  recordCache=null;
  lastError=String(err.message);
  applyMap();
 }
}
function csvSave(filename,records){
 const bytes="\ufeff"+records.map(row=>row.map(x=>'"'+String(x??"").replace(/"/g,'""')+'"').join(";")).join("\r\n")+"\r\n";
 const href=URL.createObjectURL(new Blob([bytes],{type:"text/csv;charset=utf-8"}));
 const a=document.createElement("a");a.href=href;a.download=filename;
 document.body.append(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(href),3000);
}
function clearClimate(){
 if(chart){chart.destroy();chart=null;}
 climate=null;
 ["grClimateNormal","grClimateTrend","grClimateHot","grClimateCold"].forEach(k=>setText(k,"–"));
 ["grClimateNormalN","grClimateHotYear","grClimateColdYear"].forEach(k=>setText(k,""));
 $("grClimateWarmRanks").replaceChildren();$("grClimateColdRanks").replaceChildren();
 $("grClimateCsv").disabled=true;$("grClimatePng").disabled=true;
}
function showRanks(id,list){
 const el=$(id);el.replaceChildren();
 for(const x of list.slice(0,10)){
  const li=document.createElement("li");
  li.textContent=x.year+": "+(x.anomaly>=0?"+":"")+fmt(x.anomaly)+" °C"+
   " ("+fmt(x.value)+" °C)";
  el.append(li);
 }
}
function renderClimate(){
 clearClimate();
 if(!rows.length){status("Für die ausgewählte Station gibt es keine gültigen DMI-Temperaturwerte.",true);return;}
 const view=$("grClimateView").value,
  month=Number($("grClimateMonth").value),
  threshold=Number($("grClimateCoverage").value);
 climate=calculate(rows,view,month,threshold);
 if(climate.error){
  status(climate.error+" Keine scheinbaren Anomalien, Rekorde oder Trends.",true);
  setText("grClimateNormalN",climate.refCount+" ausreichend belegte Referenzjahre");
  return;
 }
 const {normal,refCount,ranked,trend:reg,warm,cold}=climate;
 setText("grClimateNormal",fmt(normal)+" °C");
 setText("grClimateNormalN",refCount+" Referenzjahre, 1991–2020");
 setText("grClimateTrend",reg?(reg.slopePerDecade>=0?"+":"")+fmt(reg.slopePerDecade)+" °C":"–");
 if(warm.length){
  setText("grClimateHot",(warm[0].anomaly>=0?"+":"")+fmt(warm[0].anomaly)+" °C");
  setText("grClimateHotYear",String(warm[0].year));
  setText("grClimateCold",(cold[0].anomaly>=0?"+":"")+fmt(cold[0].anomaly)+" °C");
  setText("grClimateColdYear",String(cold[0].year));
 }
 showRanks("grClimateWarmRanks",warm);
 showRanks("grClimateColdRanks",cold);
 if(typeof Chart==="undefined"){
  status("Chart.js nicht erreichbar – die geprüften Werte können dennoch als CSV exportiert werden.",true);
  $("grClimateCsv").disabled=false;
  return;
 }
 const byYear=new Map(ranked.map(x=>[x.year,x]));
 const first=Math.min(...ranked.map(x=>x.year)),last=Math.max(...ranked.map(x=>x.year));
 const labels=Array.from({length:last-first+1},(_,i)=>String(first+i));
 const anomaly=labels.map(year=>byYear.get(Number(year))?.anomaly??null);
 const trendLine=labels.map(year=>reg?round(reg.intercept+reg.slope*Number(year)):null);
 chart=new Chart($("grClimateChart"),{
  type:"bar",
  data:{labels,datasets:[
   {label:"Temperaturanomalie 1991–2020 (°C)",data:anomaly,
    backgroundColor:anomaly.map(x=>x===null?"transparent":x>=0?COLORS.positive:COLORS.negative),
    borderRadius:2,barPercentage:.83,categoryPercentage:.96,order:2},
   {type:"line",label:"Linearer Trend",data:trendLine,
    pointRadius:0,borderColor:"#23384b",backgroundColor:"#23384b",borderWidth:2,
    spanGaps:true,order:1}
  ]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,
   plugins:{legend:{display:true,position:"bottom",labels:{boxWidth:14,color:"#556b7e"}},
    tooltip:{callbacks:{label:item=>item.raw===null?"Keine ausreichende Messabdeckung":
     item.datasetIndex===0?"Abweichung: "+(item.raw>=0?"+":"")+fmt(item.raw)+" °C":
     "Trendwert: "+fmt(item.raw)+" °C"}}},
   scales:{
    x:{grid:{display:false},ticks:{maxTicksLimit:13,color:"#536b81",autoSkip:true,maxRotation:0}},
    y:{title:{display:true,text:"Abweichung (°C)",color:"#536b81"},
     ticks:{color:"#536b81"},grid:{color:"rgba(83,115,137,.15)"}}
   }}
 });
 $("grClimateCsv").disabled=false;$("grClimatePng").disabled=false;
 status(ranked.length+" ausreichend abgedeckte "+(view==="year"?"Jahres":"Monats")+
  "werte. Klimamittel aus "+refCount+" Jahren der Referenz 1991–2020."+
  (reg?" Trend: "+(reg.slopePerDecade>=0?"+":"")+fmt(reg.slopePerDecade)+" °C/Dekade auf "+reg.years+" Jahren.":
   " Für einen stabilen 20-Jahre-Trend ist die Datenreihe zu kurz.")+
  " Fehlende und unvollständige Intervalle sind ausgeschlossen.");
}
async function loadClimate(){
 if(!stationId)return;
 const seq=++fetchSerial,view=$("grClimateView").value;
 activeView=view;
 clearClimate();
 const p=view==="year"?"Jahreswerte":"Monatswerte";
 status("Lade historische DMI-"+p+" für "+stationName+" …");
 const key=stationId+"|"+view;
 try{
  let data=climateCache.get(key);
  if(!data){
   data=await window.GreenlandDmiMath.apiValues(stationId,"mean_temp",view,
     "1953-01-01",YEAR+"-12-31");
   // Cache verified results per station and resolution for quick reanalysis.
   if(data.length)climateCache.set(key,data);
  }
  if(seq!==fetchSerial)return;
  rows=data;
  renderClimate();
 }catch(err){
  if(seq!==fetchSerial)return;
  rows=[];clearClimate();
  status("DMI-Klimadaten nicht erreichbar: "+err.message+". Keine geschätzten Anomalien.",true);
 }
}
function csvClimate(){
 if(!stationId||!climate?.normal)return;
 const view=$("grClimateView").value,month=$("grClimateMonth").value;
 csvSave("DMI_Groenland_Klimaanomalien_"+stationId+"_"+view+(view==="month"?"_"+month:"")+".csv",[
  ["DMI-Station","Zeitraum","DMI-Temperatur °C","Messungstage","Tagesabdeckung","Referenz 1991–2020 °C","Anomalie °C","DMI QC"],
  ...climate.ranked.map(x=>[stationId,x.date,x.value,x.count,x.coverage,
    climate.normal,x.anomaly,x.qc])
 ]);
}
function pngClimate(){
 if(!chart||!stationId||!climate)return;
 const source=chart.canvas,scale=2;
 const canvas=document.createElement("canvas");
 canvas.width=source.width*scale;
 canvas.height=(source.height+105)*scale;
 const ctx=canvas.getContext("2d");
 ctx.fillStyle="#fff";ctx.fillRect(0,0,canvas.width,canvas.height);
 ctx.fillStyle="#1e3345";ctx.font="bold 30px Arial";
 ctx.fillText("DMI Grönland · "+stationName+" · Anomalien 1991–2020",28,50);
 ctx.fillStyle="#5e7389";ctx.font="20px Arial";
 ctx.fillText("Klimamittel "+fmt(climate.normal)+" °C · "+climate.refCount+
  " Referenzjahre · Mindestabdeckung "+$("grClimateCoverage").value,28,87);
 ctx.drawImage(source,0,130,source.width*scale,source.height*scale);
 ctx.fillStyle="#5e7389";ctx.font="17px Arial";
 ctx.fillText("Quelle: DMI Climate Data API · nur qualifizierte Originalwerte",28,canvas.height-25);
 const a=document.createElement("a");a.href=canvas.toDataURL("image/png");
 a.download="DMI_Groenland_Klimaanomalie_"+stationId+".png";
 document.body.append(a);a.click();a.remove();
}
function selected(event){
 stationId=event.detail.id;stationName=event.detail.name;
 fillRanking();
 loadClimate();
}
function init(){
 $("grMapMode").addEventListener("change",applyMap);
 $("grClimateView").addEventListener("change",()=>{
  const monthly=$("grClimateView").value==="month";
  $("grClimateMonth").disabled=!monthly;
  loadClimate();
 });
 $("grClimateMonth").addEventListener("change",renderClimate);
 $("grClimateCoverage").addEventListener("change",renderClimate);
 $("grClimateCsv").addEventListener("click",csvClimate);
 $("grClimatePng").addEventListener("click",pngClimate);
 window.addEventListener("grdmi:station-selected",selected);
 window.addEventListener("grdmi:map-ready",applyMap);
 loadRecordsForMap();
}
window.GreenlandClimateMath={checkCoverage,calculate,trend,MIN_REFERENCE_YEARS,
 getState:()=>({stationId,view:activeView,hasNormal:finite(climate?.normal),
  normal:climate?.normal??null,points:climate?.ranked?.length||0,
  referenceYears:climate?.refCount||0,hasChart:!!chart,
  recordModes:recordCache?Object.keys(recordCache.modes):[],recordMapMode:lastMode})};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
