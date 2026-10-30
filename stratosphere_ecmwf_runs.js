/* ECMWF IFS run-by-run, 10hPa/60N. Only independently verified original GRIB fields. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const tabEcmwf=$("stratoEcmwfTab"),tabGefs=$("stratoGefsTab");
if(!tabEcmwf||!tabGefs)return;
const DATA_URL="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ecmwf-data/data/stratosphere/ecmwf/ifs_runs.json";
const NASA="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-data/data/stratosphere/";
const COLORS=["#f59e0b","#84cc16","#16a34a","#14b8a6","#38bdf8","#2563eb","#9955e8","#db4c91"];
let archive=null,chart=null,observations=new Map(),climatology=null,lastData=[];
function title(text){$("stratoEcmwfStatus").textContent=text;}
function dateOf(cycle,hours){return new Date(Date.parse(cycle)+hours*3600000);}
function dateKey(d){return d.toISOString().slice(0,10);}
function validWind(value){return typeof value==="number"&&Number.isFinite(value)&&value>-160&&value<170;}
function isRun(item){
 if(!/^\d{4}-\d\d-\d\dT(?:00|12):00:00Z$/.test(item?.cycle_utc||""))return false;
 const steps=item.steps_hours,values=item.values;
 return Array.isArray(steps)&&steps.length===31&&steps.every((n,i)=>n===i*12)&&
  Array.isArray(values)&&values.length===steps.length&&values.every(validWind);
}
function validate(d){
 if(d?.schema_version!==1||d.provider!=="ECMWF IFS"||d.units!=="m/s"||
    d.latitude_deg!==60||d.level_hpa!==10||d.horizon_hours!==360||
    !Array.isArray(d.runs)||!d.runs.length||d.runs.length>61||
    !d.runs.every(isRun))throw Error("Noch keine gültigen ECMWF-IFS-Modelllaufdaten");
 const runs=[...d.runs].sort((a,b)=>b.cycle_utc.localeCompare(a.cycle_utc));
 if(new Set(runs.map(r=>r.cycle_utc)).size!==runs.length)
   throw Error("Doppelte ECMWF-Modelllaufzeiten");
 const age=Date.now()-Date.parse(runs[0].cycle_utc);
 if(!Number.isFinite(age)||age<0||age>72*3600000)
   throw Error("ECMWF-Laufarchiv veraltet (>72 h)");
 return {...d,runs};
}
function parseNASA(contents){
 const found=new Map();
 for(const row of contents.split(/\r?\n/)){
  const p=row.trim().split(/\s+/);
  if(p.length<9||!/^\d{4}-\d\d-\d\d$/.test(p[0]))continue;
  const lead=p.length>=10?Number(p[9]):0,value=Number(p[1]);
  if(lead===0&&validWind(value))found.set(p[0],value);
 }
 return found;
}
async function loadNASA(){
 const year=new Date().getUTCFullYear();
 const outputs=await Promise.allSettled([year-1,year].map(async y=>{
   const r=await fetch(NASA+"u60n_10_"+y+"_merra2.txt?m="+Math.floor(Date.now()/3600000));
   if(!r.ok)throw Error("NASA "+y+" HTTP "+r.status);
   return parseNASA(await r.text());
 }));
 observations=new Map();
 for(const x of outputs)if(x.status==="fulfilled")
   for(const [date,value] of x.value)observations.set(date,value);
 try{
  const response=await fetch(NASA+"climatology_10hpa.json?m="+Math.floor(Date.now()/3600000));
  if(response.ok){const j=await response.json();climatology=j.daily||null;}
 }catch(error){console.info("ECMWF plot NASA climate line unavailable",error);}
}
function valuePoints(run){
 const output=new Map();
 run.steps_hours.forEach((lead,i)=>{
  const d=dateOf(run.cycle_utc,lead);
  // Every forecast line uses 12 UTC exactly, never mix 00/12 daily values.
  if(d.getUTCHours()===12)output.set(dateKey(d),run.values[i]);
 });
 return output;
}
function line(name,values,color,more={}){
 return {label:name,data:values,spanGaps:false,tension:0,pointRadius:2,
  pointHoverRadius:5,borderWidth:2,borderColor:color,backgroundColor:color,
  fill:false,...more};
}
function selectedRuns(){
 const limit=$("stratoEcmwfCount").value;
 return limit==="all"?archive.runs:archive.runs.slice(0,Math.max(1,Number(limit)));
}
function renderModelDiagnostics(){
 if(!archive)return;
 const el=$("stratoModelDiagnostics");el.replaceChildren();
 const heading=document.createElement("strong");heading.textContent="IFS-Laufstabilität und GEFS-Vergleich · 60°N / 10 hPa";el.append(heading);
 const p=document.createElement("p");p.textContent="IFS bei 12 UTC, GEFS bei 00 UTC: unterschiedliche Gültigkeitszeiten (12 Stunden). Die Laufänderung vergleicht ausschließlich IFS-Prognosen für denselben 12-UTC-Termin; GEFS wird nur daneben angezeigt.";el.append(p);
 const newest=archive.runs[0],older=archive.runs[1];
 const current=valuePoints(newest),previous=older?valuePoints(older):new Map();
 const gefs=window.stratoGefsEnsemble;
 const good=gefs?.provider==="NOAA GEFS"&&gefs.member_count===31&&
  Array.isArray(gefs.valid_dates)&&Array.isArray(gefs.quantiles?.mean);
 const lookup=new Map(good?gefs.valid_dates.map((date,i)=>[date,i]):[]);
 const table=document.createElement("table"),head=document.createElement("tr");
 for(const label of ["Gültigkeit","IFS aktuell · 12 UTC","IFS vorher · 12 UTC","IFS Änderung","GEFS-Mittel · 00 UTC"]){
  const cell=document.createElement("th");cell.textContent=label;head.append(cell);
 }table.append(head);
 const fmt=v=>Number.isFinite(v)?v.toFixed(1)+" m/s":"–";
 for(const step of [72,168,240]){
  let time=dateOf(newest.cycle_utc,step);
  if(time.getUTCHours()!==12)time=dateOf(newest.cycle_utc,step+12);
  const date=dateKey(time),n=current.get(date),o=previous.get(date);
  const gi=lookup.get(date),g=Number.isInteger(gi)?gefs.quantiles.mean[gi]:null;
  const tr=document.createElement("tr");
  for(const value of [date,fmt(n),fmt(o),fmt(Number.isFinite(n)&&Number.isFinite(o)?n-o:null),fmt(g)]){
    const cell=document.createElement("td");cell.textContent=value;tr.append(cell);
  }table.append(tr);
 }
 el.append(table);
 const note=document.createElement("p");note.className="legendnotes";
 note.textContent="IFS aktuell "+newest.cycle_utc+(older?" · voriger IFS "+older.cycle_utc:"")+
  (good?" · GEFS "+gefs.cycle_utc:" · GEFS derzeit nicht geladen")+
  ". Kein direkter 12-UTC-/00-UTC-Modellfehlervergleich.";el.append(note);
}
function render(){
 if(!archive || typeof Chart!=="function")return;
 const newest=archive.runs[0];
 const horizon=Number($("stratoEcmwfHorizon").value);
 const earliest=dateOf(newest.cycle_utc,-horizon*86400/3600);
 const end=dateOf(newest.cycle_utc,15*24);
 const labels=[],begin=Date.UTC(earliest.getUTCFullYear(),earliest.getUTCMonth(),earliest.getUTCDate());
 for(let t=begin;t<=end.getTime();t+=86400000)labels.push(new Date(t).toISOString().slice(0,10));
 const index=new Map(labels.map((s,i)=>[s,i]));
 const data=[];
 const runs=selectedRuns().filter(r=>Date.now()-Date.parse(r.cycle_utc)<=32*86400000)
   .sort((a,b)=>a.cycle_utc.localeCompare(b.cycle_utc));
 const showOlder=$("stratoEcmwfOlder").checked;
 const recent=runs.slice(-8);
 if(showOlder){
  for(const run of runs.slice(0,Math.max(0,runs.length-8))){
   const vals=valuePoints(run);
   data.push(line("Älter "+run.cycle_utc.slice(5,16).replace("T"," ")+" UTC",
      labels.map(day=>vals.get(day)??null),"rgba(111,128,151,.23)",{
       borderWidth:1.1,pointRadius:1,pointHoverRadius:2}));
  }
 }
 for(const [i,run] of recent.entries()){
  const newestRun=run.cycle_utc===newest.cycle_utc;
  const vals=valuePoints(run);
  data.push(line((newestRun?"Neuester IFS ":"IFS ")+run.cycle_utc.replace("T"," ").slice(5,16)+" UTC",
    labels.map(day=>vals.get(day)??null),newestRun?"#db212c":COLORS[i%COLORS.length],{
      borderWidth:newestRun?3.5:2,pointRadius:newestRun?4:2.5,
      order:newestRun?0:4}));
 }
 if($("stratoEcmwfAnalysis").checked)
  data.push(line("NASA 10 hPa / 60°N Analyse (Tageswert)",
    labels.map(day=>observations.get(day)??null),"#152638",{
      pointRadius:0,borderWidth:3.1,order:0}));
 if($("stratoEcmwfClimo").checked)
  data.push(line("1991–2020 Klimamittel (NASA)",
    labels.map(day=>{const v=climatology?.[day.slice(5)]?.mean;return validWind(v)?v:null;}),
    "#475569",{borderDash:[7,6],pointRadius:0,borderWidth:1.8,order:7}));
 data.push(line("0 m/s · Windumkehr",labels.map(()=>0),"#303846",{
    borderWidth:1.3,pointRadius:0,order:10}));
 if(chart)chart.destroy();
 chart=new Chart($("stratoEcmwfCanvas"),{
   type:"line",data:{labels,datasets:data},
   options:{responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
    interaction:{mode:"nearest",intersect:false},
    plugins:{
      legend:{position:"bottom",labels:{boxWidth:22,font:{size:11},filter:item=>
        !item.text.startsWith("Älter ")&&item.text!=="0 m/s · Windumkehr"}},
      tooltip:{callbacks:{title:points=>points[0]?.label+" (12 UTC-Prognose, NASA-Analyse als Tageswert)",
       label:point=>point.dataset.label+": "+point.parsed.y.toFixed(1)+" m/s"}}
    },
    scales:{x:{ticks:{maxTicksLimit:13,maxRotation:0},title:{display:true,text:"Gültigkeitsdatum (UTC)"}},
      y:{title:{display:true,text:"Zonal gemittelter U-Wind · 60°N / 10 hPa (m/s)"},
        grid:{color:"rgba(30,60,95,.13)"}}}
   }
 });
 const first=archive.runs[0].cycle_utc;
 const last=archive.runs.at(-1).cycle_utc;
 $("stratoEcmwfSummary").textContent="ECMWF IFS · "+archive.run_count+
   " archivierte echte 00/12-UTC-Modellläufe (keine EPS-Mitglieder) · neuester "+first+
   " · ältester "+last+" · Prognose bis +360 h";
 lastData=runs;
 renderModelDiagnostics();
 $("stratoEcmwfPng").disabled=false;
 $("stratoEcmwfCsv").disabled=false;
}
async function reload(){
 title("Prüfe ECMWF IFS 10 hPa / 60°N Originalprognosen …");
 $("stratoEcmwfReload").disabled=true;
 const results=await Promise.allSettled([
   fetch(DATA_URL+"?t="+Date.now(),{cache:"no-store"}).then(async r=>{
     if(!r.ok)throw Error("ECMWF-Laufarchiv noch nicht veröffentlicht (HTTP "+r.status+")");
     return validate(await r.json());
   }),
   loadNASA()
 ]);
 archive=results[0].status==="fulfilled"?results[0].value:null;
 if(archive){
  title("ECMWF IFS: "+archive.run_count+" verifizierte Modellläufe · 60°N/10hPa · 12-UTC-Validierungen");
  render();
 }else{
  if(chart){chart.destroy();chart=null;}
  $("stratoEcmwfSummary").textContent="Kein geprüfter IFS-Lauf veröffentlicht.";
  title("ECMWF noch nicht verfügbar: "+(results[0].reason?.message||"kein gültiger IFS-Datensatz")+
    ". Die GEFS-Prognosen sind weiterhin im anderen Reiter verfügbar.");
 }
 $("stratoEcmwfReload").disabled=false;
}
function downloadText(filename,text,kind){
 const blob=new Blob(["\ufeff",text],{type:kind}),a=document.createElement("a");
 a.href=URL.createObjectURL(blob);a.download=filename;a.click();
 setTimeout(()=>URL.revokeObjectURL(a.href),2500);
}
for(const id of ["stratoEcmwfCount","stratoEcmwfHorizon","stratoEcmwfOlder",
                 "stratoEcmwfAnalysis","stratoEcmwfClimo"]){
 $(id).addEventListener("change",render);
}
$("stratoEcmwfReload").addEventListener("click",reload);
$("stratoEcmwfCsv").addEventListener("click",()=>{
 if(!archive)return;
 const rows=["initialisierung_UTC;gueltig_UTC;vorlauf_h;u_60N_10hPa_m_s"];
 for(const run of selectedRuns())
  run.steps_hours.forEach((step,i)=>rows.push([
    run.cycle_utc,dateOf(run.cycle_utc,step).toISOString(),step,run.values[i]
  ].join(";")));
 downloadText("ECMWF_IFS_Polarwirbel_U60_10hPa_Runs.csv",rows.join("\r\n"),
   "text/csv;charset=utf-8");
});
$("stratoEcmwfPng").addEventListener("click",()=>{
 if(!chart)return;
 const img=document.createElement("a");img.href=chart.toBase64Image("image/png",1);
 img.download="ECMWF_IFS_Polarwirbel_U60_10hPa_Runs.png";img.click();
});
function choose(which){
 const isEcmwf=which==="ecmwf";
 $("stratoEcmwfView").hidden=!isEcmwf;
 $("stratoGefsView").hidden=isEcmwf;
 tabEcmwf.setAttribute("aria-pressed",String(isEcmwf));
 tabGefs.setAttribute("aria-pressed",String(!isEcmwf));
 if(isEcmwf){
  if(!archive)void reload();
  else render();
 }else window.dispatchEvent(new CustomEvent("stratosphere:view-changed"));
}
window.addEventListener("stratosphere:gefs-loaded",()=>{if(archive)renderModelDiagnostics();});
tabEcmwf.addEventListener("click",()=>choose("ecmwf"));
tabGefs.addEventListener("click",()=>choose("gefs"));
})();
