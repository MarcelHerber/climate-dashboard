/* Verified 60N / 10 hPa zonal U-wind ensemble visualization.
   NOAA GEFS member series are zonal means, not speeds or synthetic traces.
   The chart NEVER treats climatological quantiles as ensemble uncertainty. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const root=$("stratoEnsembleCard");if(!root)return;
const WIND_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ensemble-data/data/stratosphere/ensemble/";
const WIND_SOURCE=WIND_BASE+"gefs_current.json";
const WIND_INDEX=WIND_BASE+"gefs_index.json";
const NASA_SOURCE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-data/data/stratosphere/";
const monthNames=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
let chart=null,forecast=null,climo=null,observed=new Map(),lastRows=[],lastForecastAt=null,nasaLoaded=false,cycleRows=[];

function day(date){return date.toISOString().slice(0,10);}
function dt(date){return new Date(date+"T00:00:00Z");}
function plus(date,offset){const value=dt(date);value.setUTCDate(value.getUTCDate()+offset);return day(value);}
function n(v){return typeof v==="number"&&Number.isFinite(v)&&v>=-160&&v<=170?v:null;}
function note(message){$("stratoEnsembleStatus").textContent=message;}
function defaultWindow(){
 if(forecast?.valid_dates?.length)return {
  from:forecast.valid_dates[0],to:forecast.valid_dates.at(-1)
 };
 const now=day(new Date());
 return {from:now,to:plus(now,35)};
}
function applyForecastHorizon(){
 if(!forecast)return;
 const selection=$("stratoEnsembleSpan").value;
 if(selection==="custom")return;
 const begin=forecast.valid_dates[0],end=forecast.valid_dates.at(-1);
 const until=selection==="all"?end:plus(begin,Math.max(0,Number(selection)-1));
 setRange(begin,until<end?until:end);
 draw();
}
function setRange(from,to){
 const a=$("stratoEnsembleFrom"),b=$("stratoEnsembleTo");
 a.value=from;b.value=to;
}
function parseNasa(body){
 const output=new Map();
 for(const row of body.split(/\r?\n/)){
  const parts=row.trim().split(/\s+/);
  if(parts.length<9||!/^\d{4}-\d\d-\d\d$/.test(parts[0]))continue;
  const value=Number(parts[1]);
  const lead=parts.length>=10?Number(parts[9]):0;
  if(lead===0&&n(value)!==null)output.set(parts[0],value);
 }
 return output;
}
function percentile(values,p){
 if(!values.length)return null;
 const s=[...values].sort((a,b)=>a-b),k=(s.length-1)*p;
 const a=Math.floor(k),b=Math.min(s.length-1,a+1);
 return s[a]+(s[b]-s[a])*(k-a);
}
function statsFor(index){
 if(!forecast)return null;
 const vals=Object.values(forecast.members).map(row=>n(row[index])).filter(v=>v!==null);
 if(vals.length<2)return null;
 const mean=vals.reduce((a,b)=>a+b,0)/vals.length;
 return {mean,p05:percentile(vals,.05),p25:percentile(vals,.25),p75:percentile(vals,.75),p95:percentile(vals,.95),count:vals.length};
}
function validateForecast(data){
 if(data?.schema_version!==1||data?.provider!=="NOAA GEFS"||data?.level_hpa!==10||
    data?.latitude_deg!==60||data?.units!=="m/s"||
    !/^\d{4}-\d\d-\d\dT\d\d:00:00Z$/.test(data.cycle_utc||"")||
    !Array.isArray(data.valid_dates)||data.valid_dates.length<8||
    !data.members||typeof data.members!=="object")throw Error("GEFS-Ensembledaten: ungültiges Format");
 const members=Object.entries(data.members);
 if(members.length!==31||!members.some(([id])=>id==="c00")||
    members.filter(([id])=>/^p\d{2}$/.test(id)).length!==30)throw Error("GEFS: 31 Ensemblemitglieder erforderlich");
 if(!data.valid_dates.every((x,i)=>/^\d{4}-\d\d-\d\d$/.test(x)&&
    (i===0||x>data.valid_dates[i-1])))throw Error("GEFS-Zeitachse fehlerhaft");
 for(const [key,values] of members){
  if(!Array.isArray(values)||values.length!==data.valid_dates.length||
     values.some(v=>n(v)===null))throw Error("GEFS-Mitglied "+key+" unvollständig");
 }
 const runAge=Date.now()-Date.parse(data.cycle_utc);
 if(!Number.isFinite(runAge)||runAge<0||runAge>72*3600000)throw Error("GEFS-Modelllauf veraltet (älter als 72 Stunden)");
 return data;
}
async function fetchNasa(){
 const year=new Date().getUTCMonth()>=6?new Date().getUTCFullYear():new Date().getUTCFullYear()-1;
 const names=[year-1,year];
 const result=await Promise.allSettled(names.map(async y=>{
  const r=await fetch(NASA_SOURCE+"u60n_10_"+y+"_merra2.txt?d="+Math.floor(Date.now()/3600000));
  if(!r.ok)throw Error("NASA "+y+": HTTP "+r.status);
  return parseNasa(await r.text());
 }));
 observed=new Map();
 for(const entry of result){if(entry.status==="fulfilled")for(const [key,value] of entry.value)observed.set(key,value);}
 try{
  const r=await fetch(NASA_SOURCE+"climatology_10hpa.json?d="+Math.floor(Date.now()/3600000));
  if(r.ok){const j=await r.json();climo=j.daily||null;}
 }catch(e){console.info("NASA Klimatologie vorübergehend nicht erreichbar",e);}
 nasaLoaded=true;
}
async function cycles(){
 const select=$("stratoGefsCycle");
 let entries=[];
 try{
  const response=await fetch(WIND_INDEX+"?d="+Date.now(),{cache:"no-store"});
  if(response.ok){
   const json=await response.json();
   if(json.provider==="NOAA GEFS"&&Array.isArray(json.runs)){
    entries=json.runs.filter(x=>/^\\d{4}-\\d\\d-\\d\\dT(?:00|06|12|18):00:00Z$/.test(x.cycle_utc||"")&&
      /^runs\\/\\d{8}_\\d{6}\\.json$/.test(x.path||"")&&
      Date.now()-Date.parse(x.cycle_utc)<72*3600000&&Date.parse(x.cycle_utc)<=Date.now());
   }
  }
 }catch(error){console.info("GEFS-Laufindex nicht verfügbar",error);}
 const selected=select.value;
 cycleRows=entries.sort((a,b)=>b.cycle_utc.localeCompare(a.cycle_utc));
 select.replaceChildren();
 if(!cycleRows.length){
  const opt=document.createElement("option");opt.value="current";
  opt.textContent="Neuester verfügbarer GEFS-Lauf";select.add(opt);
 }else{
  for(const x of cycleRows){
   const option=document.createElement("option");option.value=x.cycle_utc;
   option.textContent=x.cycle_utc.slice(0,16).replace("T"," ")+" UTC · "+x.forecast_horizon_days+" Tage";
   select.add(option);
  }
  select.value=cycleRows.some(x=>x.cycle_utc===selected)?selected:cycleRows[0].cycle_utc;
 }
}
async function getWind(){
 const choice=$("stratoGefsCycle").value;
 const item=cycleRows.find(x=>x.cycle_utc===choice);
 const url=item?WIND_BASE+item.path:WIND_SOURCE;
 const response=await fetch(url+"?d="+Date.now(),{cache:"no-store"});
 if(!response.ok)throw Error("NOAA-GEFS-Daten noch nicht veröffentlicht (HTTP "+response.status+")");
 const result=validateForecast(await response.json());
 if(item&&result.cycle_utc!==item.cycle_utc)throw Error("Modelllauf und Index stimmen nicht überein");
 return result;
}
async function reload(refreshIndex=true){
 note("Prüfe echte GEFS-Ensemblemitglieder und NASA-Analysen …");
 $("stratoEnsembleReload").disabled=true;
 if(refreshIndex)await cycles();
 const needsNasa=$("stratoClimo").checked||$("stratoShowAnalysis").checked;
 const result=await Promise.allSettled([
  getWind(),
  needsNasa&&!nasaLoaded?fetchNasa():Promise.resolve()
 ]);
 forecast=result[0].status==="fulfilled"?result[0].value:null;
 // Share precisely the same validated 31 original GEFS members with the
 // primary 60N/10hPa chart. Never use climatology as a member substitute.
 window.stratoGefsEnsemble=forecast;
 window.dispatchEvent(new CustomEvent("stratosphere:gefs-loaded"));
 if(!forecast)console.info("GEFS-Ensemble noch nicht freigegeben:",result[0].reason);
 if(forecast){
  lastForecastAt=forecast.cycle_utc;
  note("31/31 echte Ensemblemitglieder · GEFS-Lauf "+forecast.cycle_utc+
    " · "+forecast.forecast_horizon_days+" Tage Vorlauf · Prognose bis "+forecast.valid_dates.at(-1));
 }else{
  note("Ensemble-Prognose derzeit nicht verfügbar: "+(result[0].reason?.message||"kein geprüfter GEFS-Lauf")+
    ". NASA-Analyse und 1991–2020-Klimamittel bleiben sichtbar.");
 }
 $("stratoEnsembleReload").disabled=false;
 if(forecast)applyForecastHorizon();
 else draw();
}
function dailyRows(){
 const from=$("stratoEnsembleFrom").value,to=$("stratoEnsembleTo").value;
 if(!from||!to||from>to||Date.parse(to)-Date.parse(from)>365*86400000){
  note("Bitte einen gültigen Zeitraum wählen (maximal 366 Tage, Von ≤ Bis).");
  return [];
 }
 const index=new Map((forecast?.valid_dates||[]).map((date,i)=>[date,i]));
 const rows=[];
 for(let d=from;d<=to;d=plus(d,1)){
  const ix=index.get(d),ensemble=Number.isInteger(ix)?statsFor(ix):null;
  const climate=climo?.[d.slice(5)]?.mean;
  rows.push({date:d,obs:observed.get(d)??null,climo:n(climate),control:Number.isInteger(ix)?n(forecast.members.c00[ix]):null,
    stats:ensemble,memberIndex:ix??null});
 }
 return rows;
}
function line(label,values,color,width=2,props={}){
 return {label,data:values,pointRadius:0,pointHoverRadius:3,spanGaps:false,tension:0.12,
  borderColor:color,borderWidth:width,fill:false,...props};
}
function band(rows,low,high,label,rgba){
 return [
  line("_"+label+" Untergrenze",rows.map(r=>r.stats?.[low]??null),"rgba(0,0,0,0)",0,{order:12}),
  line(label,rows.map(r=>r.stats?.[high]??null),"rgba(0,0,0,0)",0,
       {fill:{target:"-1",above:rgba,below:rgba},order:11})
 ];
}
function draw(){
 if(typeof Chart!=="function"){note("Chart.js konnte nicht geladen werden.");return;}
 const rows=dailyRows();if(!rows.length)return;
 lastRows=rows;
 const labels=rows.map(r=>r.date);
 const datasets=[];
 if(forecast&&$("stratoBand90").checked){
  datasets.push(...band(rows,"p05","p95","Ensemble 5–95 %","rgba(112,145,202,.17)"));
  if($("stratoBand50").checked)
   datasets.push(...band(rows,"p25","p75","Ensemble 25–75 %","rgba(51,86,158,.29)"));
 }
 if(forecast&&$("stratoMembers").checked){
  datasets.push(line("31 GEFS-Mitglieder (einzeln)",rows.map(()=>null),"rgba(35,46,62,.75)",1.3,{order:7}));
  for(const [id,values] of Object.entries(forecast.members)){
   datasets.push(line("_"+id,rows.map(r=>Number.isInteger(r.memberIndex)?values[r.memberIndex]:null),
     "rgba(35,46,62,.48)",1.05,{order:7}));
  }
 }
 if(forecast){
  datasets.push(line("Ensemble-Mittel",rows.map(r=>r.stats?.mean??null),"#d62828",3.4,{order:0}));
  datasets.push(line("Kontrolllauf",rows.map(r=>r.control),"#ea9908",1.8,{borderDash:[6,4],order:2}));
 }
 if($("stratoShowAnalysis").checked)
  datasets.push(line("NASA-Analyse (MERRA-2/GEOS-FP)",rows.map(r=>r.obs),"#16803f",3,{order:0}));
 if($("stratoClimo").checked){
  datasets.push(line("Klimamittel 1991–2020",rows.map(r=>r.climo),"#b68d00",2,{order:3}));
 }
 datasets.push(line("0 m/s · Windumkehr",rows.map(()=>0),"#334155",1.2,{borderDash:[5,5],order:20}));
 const vals=datasets.flatMap(d=>d.data).filter(Number.isFinite);
 const ymin=vals.length?Math.floor((Math.min(...vals)-4)/5)*5:-20;
 const ymax=vals.length?Math.ceil((Math.max(...vals)+4)/5)*5:60;
 if(chart)chart.destroy();
 chart=new Chart($("stratoEnsembleCanvas"),{
  type:"line",data:{labels,datasets},
  options:{responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
   interaction:{mode:"index",intersect:false},
   plugins:{
    legend:{display:false},
    tooltip:{mode:"index",intersect:false,filter:item=>!item.dataset.label.startsWith("_")&&Number.isFinite(item.parsed.y),
      callbacks:{title:points=>points[0]?.label||"",label:item=>item.dataset.label+": "+item.parsed.y.toFixed(1)+" m/s"}}
   },
   scales:{
    x:{grid:{display:false},ticks:{maxTicksLimit:13,maxRotation:0,
     callback:(v,index)=>{const date=labels[index];if(!date)return "";const d=dt(date);return d.getUTCDate()===1||index%Math.max(1,Math.ceil(labels.length/12))===0?
      d.getUTCDate()+". "+monthNames[d.getUTCMonth()]:"";}},
      title:{display:true,text:"Datum (UTC) · gewählter Ausschnitt"}},
    y:{min:Math.min(-5,ymin),max:Math.max(10,ymax),
      grid:{color:"rgba(40,60,80,.11)"},title:{display:true,text:"Zonal gemittelter Wind [m/s]"}}
   }
  }
 });
 $("stratoEnsemblePng").disabled=false;
 $("stratoEnsembleCsv").disabled=false;
}
function download(filename,content,type){
 const blob=new Blob([content],{type}),a=document.createElement("a");
 const u=URL.createObjectURL(blob);a.href=u;a.download=filename;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(u),5000);
}
$("stratoEnsembleFrom").addEventListener("change",()=>{$("stratoEnsembleSpan").value="custom";draw();});
$("stratoEnsembleTo").addEventListener("change",()=>{$("stratoEnsembleSpan").value="custom";draw();});
$("stratoEnsembleSpan").addEventListener("change",()=>{
 if($("stratoEnsembleSpan").value==="custom"){
  document.querySelector("#stratoEnsembleCard .ensemble-more").open=true;
  return;
 }
 applyForecastHorizon();
});
for(const id of ["stratoMembers","stratoBand50","stratoBand90"]){
 $(id).addEventListener("change",draw);
}
for(const id of ["stratoClimo","stratoShowAnalysis"]){
 $(id).addEventListener("change",()=>{
  if(($("stratoClimo").checked||$("stratoShowAnalysis").checked)&&!nasaLoaded){
   void fetchNasa().then(draw).catch(error=>{console.warn("NASA unavailable",error);draw();});
  }else draw();
 });
}
$("stratoEnsembleReload").addEventListener("click",()=>reload(true));
$("stratoGefsCycle").addEventListener("change",()=>reload(false));
$("stratoEnsembleReset").addEventListener("click",()=>{
 $("stratoEnsembleSpan").value="all";applyForecastHorizon();
});
$("stratoEnsembleCsv").addEventListener("click",()=>{
 if(!lastRows.length)return;
 const memberKeys=forecast?Object.keys(forecast.members):[];
 const head=["Datum_UTC","NASA_Analyse_m_s","Klimamittel_1991_2020_m_s",
   "Ensemble_Mittel_m_s","Ensemble_P05_m_s","Ensemble_P25_m_s",
   "Ensemble_P75_m_s","Ensemble_P95_m_s","Kontrolllauf_m_s",...memberKeys];
 const rows=[head.join(";")];
 for(const row of lastRows){
  rows.push([row.date,row.obs??"",row.climo??"",row.stats?.mean??"",row.stats?.p05??"",
   row.stats?.p25??"",row.stats?.p75??"",row.stats?.p95??"",row.control??"",
   ...memberKeys.map(k=>Number.isInteger(row.memberIndex)?forecast.members[k][row.memberIndex]:"")].join(";"));
 }
 download("Stratosphaere_60N_10hPa_GEFS_Ensemble.csv","\ufeff"+rows.join("\r\n"),"text/csv;charset=utf-8");
});
$("stratoEnsemblePng").addEventListener("click",()=>{
 if(!chart)return;const canvas=chart.canvas,scale=Math.max(1,canvas.width/canvas.clientWidth);
 const header=Math.round(93*scale),output=document.createElement("canvas");
 output.width=canvas.width;output.height=canvas.height+header;
 const g=output.getContext("2d");g.fillStyle="#fff";g.fillRect(0,0,output.width,output.height);
 g.fillStyle="#16253c";g.textBaseline="top";g.font="bold "+Math.round(22*scale)+"px Arial";
 g.fillText("60°N / 10 hPa · Ensemble des zonalen Windes",19*scale,12*scale);
 g.fillStyle="#475569";g.font=Math.round(14*scale)+"px Arial";
 g.fillText("NOAA GEFS · "+(lastForecastAt||"ohne veröffentlichte Ensembleprognose")+" · "+$("stratoEnsembleFrom").value+
   " bis "+$("stratoEnsembleTo").value,19*scale,47*scale);
 g.font=Math.round(12*scale)+"px Arial";g.fillText("Einzelmitglieder und Ensemblequantile nur aus echten Modellfeldern · NASA Analyse · Quelle: NOAA/NASA",19*scale,71*scale);
 g.drawImage(canvas,0,header);
 const a=document.createElement("a");a.href=output.toDataURL("image/png");
 a.download="Stratosphaere_60N_10hPa_GEFS_Ensemble.png";
 document.body.appendChild(a);a.click();a.remove();
});
const range=defaultWindow();setRange(range.from,range.to);
window.addEventListener("stratosphere:view-changed",()=>{
 if(document.body.classList.contains("strato-forecast-only")&&forecast)draw();
});
void reload();
})();
