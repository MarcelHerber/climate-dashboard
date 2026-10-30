/* Run-to-run diagnostics based exclusively on archived original GEFS and ECMWF ENS members.
   All comparisons match exact UTC valid timestamps; missing cycles stay missing.
   U<0 is a signed 60N/10hPa wind reversal, not a Major SSW diagnosis. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const canvas=$("stratoTrendCanvas");
if(!canvas||!$("stratoTrendModel"))return;
const ROOT="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/";
const MODELS={
 gefs:{name:"NOAA GEFS",branch:"stratosphere-ensemble-data",directory:"data/stratosphere/ensemble/",
   index:"gefs_index.json",current:"gefs_current.json",hours:[0,6,12,18],total:31,perturbed:30},
 eps:{name:"ECMWF IFS ENS",branch:"stratosphere-ecmwf-ens-data",directory:"data/stratosphere/ecmwf/",
   index:"ens_index.json",current:"ens_current.json",hours:[0,12],total:51,perturbed:50}
};
const palette=["#d32f2f","#1875bc","#007f76","#a45d1d","#6d529c","#777b83","#bc4d8c","#647b34","#825a52","#34676e"];
let indexes={gefs:[],eps:[]},runs=[],chart=null,displayRows=[],viewKey=0,loadState="initial",loadFailures=0,lastModel="",heatmapState=null,heatmapSelection=null;
const valid=value=>typeof value==="number"&&Number.isFinite(value)&&value>-160&&value<170;
const isoCycle=cycle=>typeof cycle==="string"&&/^\d{4}-\d\d-\d\dT(?:00|06|12|18):00:00Z$/.test(cycle)&&
 Number.isFinite(Date.parse(cycle))&&Date.parse(cycle)<=Date.now()&&Date.now()-Date.parse(cycle)<10*86400000;
const percent=(n,d)=>100*n/d;
const fixed=(x,n=1)=>Number(x).toFixed(n).replace(".",",");
const stamp=iso=>iso.replace("T"," ").slice(0,16)+" UTC";
function config(which){return MODELS[which]||MODELS.gefs;}
function base(which){const m=config(which);return ROOT+m.branch+"/"+m.directory;}
function verify(data,model,expectedCycle){
 const m=config(model);
 if(!data||data.schema_version!==1||data.provider!==m.name||data.level_hpa!==10||
    data.latitude_deg!==60||data.units!=="m/s"||data.member_count!==m.total||
    !isoCycle(data.cycle_utc)||expectedCycle&&data.cycle_utc!==expectedCycle)throw Error("Datenformat oder Modelllauf ungültig");
 const init=new Date(data.cycle_utc);
 if(!m.hours.includes(init.getUTCHours()))throw Error("Dieser Modellzyklus gehört nicht zum Modell");
 const days=model==="eps"?15:data.forecast_horizon_days;
 if(!Number.isInteger(days)||(model==="gefs"&&![16,35].includes(days))||
    (model==="gefs"&&days===35&&init.getUTCHours()!==0)||
    (model==="eps"&&(data.forecast_horizon_days!==15||data.valid_hour_utc!==init.getUTCHours()||
       data.stream_ensemble!=="enfo/ef"||data.stream_control!=="oper/fc"||
       data.perturbed_count!==50)))throw Error("Ungültiger Ensemblehorizont");
 if(!Array.isArray(data.valid_dates)||data.valid_dates.length!==days+1||
    data.valid_dates.some((d,i)=>d!==new Date(+init+i*86400000).toISOString().slice(0,10)))throw Error("Ungültige Gültigkeitszeiten");
 if(model==="eps"&&(!Array.isArray(data.forecast_step_hours)||
   data.forecast_step_hours.length!==days+1||
   data.forecast_step_hours.some((n,i)=>n!==24*i)))throw Error("Ungültige ECMWF-Prognoseschritte");
 const names=["c00",...Array.from({length:m.perturbed},(_,i)=>"p"+String(i+1).padStart(2,"0"))];
 if(!data.members||Object.keys(data.members).length!==m.total||
    names.some(name=>!Object.hasOwn(data.members,name)||!Array.isArray(data.members[name])||
      data.members[name].length!==days+1||!data.members[name].every(valid)))
      throw Error("Unvollständige Original-Ensemblemitglieder");
 return data;
}
function extract(data){
 const vals=Object.values(data.members),init=Date.parse(data.cycle_utc);
 return data.valid_dates.map((date,i)=>{
  const values=vals.map(a=>a[i]),count=values.filter(v=>v<0).length;
  return {key:new Date(init+i*86400000).toISOString(),date,
    count,total:vals.length,prob:percent(count,vals.length),
    mean:values.reduce((a,b)=>a+b,0)/vals.length};
 });
}
function parseIndex(data,model){
 const m=config(model);
 if(!data||data.schema_version!==1||data.provider!==m.name||!Array.isArray(data.runs))return [];
 const candidates=data.runs.filter(r=>r&&isoCycle(r.cycle_utc)&&
    /^runs\/\d{8}_\d{6}\.json$/.test(r.path)&&
    m.hours.includes(Number(r.cycle_utc.slice(11,13)))&&
    (r.forecast_horizon_days===(model==="eps"?15:r.forecast_horizon_days)));
 const dedup=new Map();
 for(const r of candidates){
  const old=dedup.get(r.cycle_utc);
  if(!old||r.forecast_horizon_days>old.forecast_horizon_days)dedup.set(r.cycle_utc,r);
 }
 return [...dedup.values()].sort((a,b)=>b.cycle_utc.localeCompare(a.cycle_utc));
}
async function json(url){
 const res=await fetch(url+"?t="+Date.now(),{cache:"no-store"});
 if(!res.ok)throw Error("HTTP "+res.status);
 return res.json();
}
async function loadIndex(model){
 const m=config(model);
 try{
  const data=await json(base(model)+m.index);
  return parseIndex(data,model);
 }catch(error){
  console.info("Stratosphäre: Laufarchiv noch nicht veröffentlicht",model,error);
  return [];
 }
}
async function loadRun(model,entry){
 const source=entry?base(model)+entry.path:base(model)+config(model).current;
 const data=verify(await json(source),model,entry?.cycle_utc);
 return {cycle:data.cycle_utc,days:data.forecast_horizon_days,rows:extract(data),data};
}
function modelChoices(){
 const model=$("stratoTrendModel").value,m=config(model);
 const hour=$("stratoTrendHour"),old=hour.value;
 hour.replaceChildren();
 const source=indexes[model];
 for(const n of m.hours){
  const option=document.createElement("option");
  option.value=String(n).padStart(2,"0");
  const available=source.filter(x=>Number(x.cycle_utc.slice(11,13))===n).length;
  option.textContent=String(n).padStart(2,"0")+" UTC"+(available?" · "+available+" Läufe":" · noch kein Archiv");
  hour.add(option);
 }
 const possible=m.hours.find(n=>source.some(r=>Number(r.cycle_utc.slice(11,13))===n));
 const supported=m.hours.map(n=>String(n).padStart(2,"0"));
 // Keep a deliberate "not yet archived" hour selection; on model switches,
 // prefer an actually available initialization time.
 hour.value=lastModel===model&&supported.includes(old)?old:
    String(possible??m.hours[0]).padStart(2,"0");
 lastModel=model;
}
function validTimeSelection(){
 const selected=$("stratoTrendValid").value;
 const select=$("stratoTrendValid");select.replaceChildren();
 const available=[...new Set(runs.flatMap(run=>run.rows.map(x=>x.key)))]
     .filter(t=>runs[0]&&Date.parse(t)>=Date.parse(runs[0].cycle)&&
          Date.parse(t)<=Date.parse(runs[0].cycle)+Number($("stratoTrendHorizon").value)*86400000)
     .sort();
 for(const key of available){
  const o=document.createElement("option");o.value=key;
  o.textContent=key.slice(0,10)+" · "+key.slice(11,13)+" UTC";select.add(o);
 }
 if(available.length){
  select.value=available.includes(selected)?selected:available[Math.min(available.length-1,7)];
 }
}
function comparisons(){
 if(!runs.length)return [];
 const limit=Number($("stratoTrendHorizon").value);
 const from=Date.parse(runs[0].cycle),to=from+limit*86400000;
 const unique=[...new Set(runs.flatMap(r=>r.rows.map(x=>x.key)))].filter(t=>{
  const ms=Date.parse(t);return ms>=from&&ms<=to;
 }).sort();
 return unique.map(key=>{
  const vals=runs.map(r=>r.rows.find(x=>x.key===key)||null);
  const newest=vals[0],previous=vals[1];
  return {key,date:key.slice(0,10),vals,
          delta:newest&&previous?newest.prob-previous.prob:null,
          newest,previous};
 });
}
/* Color bins are fixed at 0/20/40/60/80/100% for comparability between cycles. */
function heatmapBucket(p){
 if(p===0)return 0;
 if(p<=20)return 1;
 if(p<=40)return 2;
 if(p<=60)return 3;
 if(p<=80)return 4;
 return 5;
}
function heatmapMatrix(modelRuns,days){
 if(!modelRuns.length)return {dates:[],rows:[],total:0,missing:0};
 const cycle=modelRuns[0].cycle;
 const init=Date.parse(cycle),hour=cycle.slice(11,13);
 if(!Number.isInteger(days)||days<1||days>35||!Number.isFinite(init))
   throw Error("Invalid heatmap validity interval");
 const dates=Array.from({length:days+1},(_,i)=>new Date(init+i*86400000).toISOString());
 const rows=modelRuns.map(run=>{
  if(run.cycle.slice(11,13)!==hour)throw Error("Different UTC hours cannot share a heatmap grid");
  const byTime=new Map(run.rows.map(v=>[v.key,v]));
  return {cycle:run.cycle,cells:dates.map(key=>byTime.get(key)??null)};
 });
 const total=rows.length*dates.length;
 const missing=rows.reduce((sum,r)=>sum+r.cells.filter(v=>v===null).length,0);
 return {dates,rows,total,missing};
}
function heatmapDetail(matrix,rowIndex,colIndex){
 const row=matrix.rows[rowIndex],cell=row?.cells[colIndex],date=matrix.dates[colIndex];
 if(!row||!cell||!date)return null;
 const older=matrix.rows[rowIndex+1]?.cells[colIndex]??null;
 const pp=older?cell.prob-older.prob:null;
 return {cycle:row.cycle,key:date,count:cell.count,total:cell.total,
         probability:cell.prob,mean:cell.mean,change:pp,
         olderCycle:older?matrix.rows[rowIndex+1].cycle:null};
}
function heatmapStatus(text){$("stratoHeatStatus").textContent=text;}
function heatmapSummary(detail){
 if(!detail){
  $("stratoHeatDetail").textContent="Zelle anklicken, um Originalwerte, Ensemble-Mittel und gegebenenfalls die Änderung zum vorigen Archivlauf zu sehen.";
  return;
 }
 const model=config($("stratoTrendModel").value).name;
 const diff=detail.change===null?"Kein unmittelbar vorheriger Archivlauf mit identischem Gültigkeitstermin.":
  "Änderung zum Archivlauf "+stamp(detail.olderCycle)+": "+
    (detail.change>=0?"+":"")+fixed(detail.change)+" Prozentpunkte.";
 $("stratoHeatDetail").textContent=model+" · Lauf "+stamp(detail.cycle)+
  " · gültig "+stamp(detail.key)+" · U < 0 m/s: "+
  detail.count+"/"+detail.total+" = "+fixed(detail.probability)+" % · Ensemble-Mittel: "+
  fixed(detail.mean,2)+" m/s. "+diff;
}
function drawHeatmap(){
 const table=$("stratoHeatTable");
 if(!table)return;
 table.replaceChildren();
 const exportReady=Boolean(runs.length);
 $("stratoHeatCsv").disabled=!exportReady;
 $("stratoHeatPng").disabled=!exportReady;
 if(!exportReady){
  heatmapState=null;
  heatmapSummary(null);
  heatmapStatus(loadState==="loading"?"Lade die verifizierten Modellläufe …":
    "Noch keine archivierten Original-Ensembles für diese Auswahl. Fehlende Läufe werden nicht ergänzt.");
  return;
 }
 const days=Number($("stratoTrendHorizon").value);
 const matrix=heatmapMatrix(runs,days);
 heatmapState=matrix;
 const head=document.createElement("thead"),top=document.createElement("tr");
 const label=document.createElement("th");label.textContent="Modelllauf · UTC";
 label.className="strato-heat-sticky";
 label.scope="col";top.appendChild(label);
 for(const date of matrix.dates){
  const th=document.createElement("th");th.scope="col";
  th.textContent=date.slice(8,10)+"."+date.slice(5,7)+".";
  th.title=date.slice(0,16).replace("T"," ")+" UTC";
  top.appendChild(th);
 }
 head.appendChild(top);table.appendChild(head);
 const body=document.createElement("tbody");
 let matched=false;
 for(let row=0;row<matrix.rows.length;row++){
  const tr=document.createElement("tr");
  const header=document.createElement("th");header.scope="row";
  header.className="strato-heat-sticky";
  header.textContent=matrix.rows[row].cycle.slice(5,10)+" "+
                     matrix.rows[row].cycle.slice(11,13)+" UTC";
  header.title=stamp(matrix.rows[row].cycle);
  tr.appendChild(header);
  for(let col=0;col<matrix.dates.length;col++){
   const td=document.createElement("td"),point=matrix.rows[row].cells[col];
   if(point){
    const button=document.createElement("button");button.type="button";
    button.className="strato-heat-cell strato-heat-bin-"+heatmapBucket(point.prob);
    button.textContent=String(Math.round(point.prob));
    button.title=stamp(matrix.rows[row].cycle)+" · gültig "+stamp(matrix.dates[col])+
      " · "+point.count+"/"+point.total+" mit U < 0 m/s = "+fixed(point.prob)+" %";
    button.setAttribute("aria-label",button.title);
    const selected=heatmapSelection?.cycle===matrix.rows[row].cycle&&
      heatmapSelection?.key===matrix.dates[col];
    if(selected){button.classList.add("is-selected");matched=true;}
    button.addEventListener("click",()=>{
     heatmapSelection={cycle:matrix.rows[row].cycle,key:matrix.dates[col]};
     drawHeatmap();
    });
    td.appendChild(button);
   }else{
    const span=document.createElement("span");span.className="strato-heat-empty";
    span.textContent="–";span.title="Kein Original-Prognosewert für diese Gültigkeitszeit";
    td.appendChild(span);
   }
   tr.appendChild(td);
  }
  body.appendChild(tr);
 }
 table.appendChild(body);
 if(!matched){
  const r=matrix.rows[0],col=r.cells.findIndex(v=>v!==null);
  heatmapSelection=col<0?null:{cycle:r.cycle,key:matrix.dates[col]};
  if(col>=0){
   const selected=body.children[0]?.children[col+1]?.firstChild;
   if(selected?.classList)selected.classList.add("is-selected");
  }
 }
 const rindex=matrix.rows.findIndex(r=>r.cycle===heatmapSelection?.cycle);
 const cindex=matrix.dates.indexOf(heatmapSelection?.key);
 heatmapSummary(heatmapDetail(matrix,rindex,cindex));
 const available=matrix.total-matrix.missing;
 heatmapStatus(config($("stratoTrendModel").value).name+" · "+
  matrix.rows.length+" echte Modellläufe · "+matrix.dates.length+
  " feste "+$("stratoTrendHour").value+"-UTC-Gültigkeitszeiten · "+
  available+"/"+matrix.total+" belegte Felder; "+matrix.missing+
  " ohne Originalwert. Farben stets 0–100 %."+
  (matrix.rows.length<2?" Für eine zeitliche Laufentwicklung fehlt noch mindestens ein weiterer Lauf.":""));
}
function heatmapCSV(matrix){
 const model=$("stratoTrendModel").value;
 const rows=["Modell;Modelllauf_UTC;Gueltig_UTC;Originaldaten_vorhanden;U_negativ_n;Mitglieder_n;U_negativ_Prozent;Ensemble_Mittel_m_s;Delta_zum_vorherigen_Archivlauf_pp"];
 matrix.rows.forEach((r,i)=>r.cells.forEach((value,j)=>{
  const older=matrix.rows[i+1]?.cells[j];
  rows.push([model,r.cycle,matrix.dates[j],value?"ja":"nein",
    value?.count??"",value?.total??"",value?value.prob.toFixed(4):"",
    value?value.mean.toFixed(4):"",value&&older?(value.prob-older.prob).toFixed(4):""].join(";"));
 }));
 return "\ufeff"+rows.join("\r\n");
}
function heatmapPng(matrix){
 if(!matrix.rows.length||!matrix.dates.length)return null;
 const wCell=54,hCell=35,left=168,top=104,bottom=106,pad=20,scale=2;
 const width=Math.max(830,left+wCell*matrix.dates.length+pad),height=top+hCell*matrix.rows.length+bottom;
 const element=document.createElement("canvas");element.width=width*scale;element.height=height*scale;
 const ctx=element.getContext("2d");
 if(!ctx)return null;
 ctx.scale(scale,scale);
 ctx.fillStyle="#ffffff";ctx.fillRect(0,0,width,height);
 ctx.fillStyle="#1a354b";ctx.font="bold 16px sans-serif";
 ctx.fillText(config($("stratoTrendModel").value).name+
  " · Windumkehrwahrscheinlichkeit U < 0 m/s",17,29);
 ctx.font="12px sans-serif";
 ctx.fillText("60°N / 10 hPa · 31 GEFS / 51 ECMWF ENS Originalmitglieder · "+$("stratoTrendHour").value+" UTC",17,49);
 ctx.fillText("Feste Gültigkeitstermine, fehlende Originalwerte bleiben grau",17,66);
 for(let j=0;j<matrix.dates.length;j++){
  ctx.fillStyle="#435d73";ctx.font="11px sans-serif";
  ctx.fillText(matrix.dates[j].slice(8,10)+"."+matrix.dates[j].slice(5,7),
               left+j*wCell+5,top-12);
 }
 matrix.rows.forEach((r,i)=>{
  const y=top+i*hCell;
  ctx.fillStyle="#24455f";ctx.font="bold 12px sans-serif";
  ctx.fillText(r.cycle.slice(5,10)+" "+r.cycle.slice(11,13)+" UTC",18,y+24);
  r.cells.forEach((value,j)=>{
   const x=left+j*wCell,bucket=value?heatmapBucket(value.prob):-1;
   const colors=["#edf3f8","#c5def1","#85bbdd","#e9d476","#ed9859","#b92d3e"];
   ctx.fillStyle=bucket<0?"#e9eaed":colors[bucket];
   ctx.fillRect(x+1,y+2,wCell-3,hCell-4);
   ctx.fillStyle=bucket===5?"#ffffff":"#16334c";
   ctx.font="bold 12px sans-serif";
   ctx.fillText(value?String(Math.round(value.prob)):"–",x+11,y+24);
  });
 });
 const legendY=top+matrix.rows.length*hCell+25;
 const legend=["0 %","0–20 %","20–40 %","40–60 %","60–80 %","80–100 %","kein Wert"];
 const colors=["#edf3f8","#c5def1","#85bbdd","#e9d476","#ed9859","#b92d3e","#e9eaed"];
 legend.forEach((label,i)=>{
  const x=18+i*110;ctx.fillStyle=colors[i];ctx.fillRect(x,legendY,14,13);
  ctx.fillStyle="#40586d";ctx.font="11px sans-serif";ctx.fillText(label,x+19,legendY+11);
 });
 ctx.fillStyle="#536c80";ctx.font="11px sans-serif";
 ctx.fillText("Quelle: NOAA GEFS / ECMWF IFS ENS Original-Archiv · Climate Dashboard · keine Major-SSW-Wahrscheinlichkeit",18,height-21);
 return element.toDataURL("image/png");
}

function status(message){
 $("stratoTrendStatus").textContent=message;
}
function clearChart(){
 if(chart){chart.destroy();chart=null;}
 $("stratoTrendPng").disabled=true;
}
function draw(){
 drawHeatmap();
 if(!runs.length){
  clearChart();displayRows=[];$("stratoTrendValid").replaceChildren();
  $("stratoTrendCsv").disabled=true;
  $("stratoTrendTableBody").replaceChildren();
  $("stratoTrendMeta").textContent="Noch kein gültiges Ensemble-Laufarchiv ausgewählt.";
  status(loadState==="loading"?"Lade Laufarchive …":"Keine verifizierten Modellläufe. Es werden keine Prognosen simuliert.");
  return;
 }
 validTimeSelection();
 displayRows=comparisons();
 const selected=$("stratoTrendValid").value;
 const latest=runs[0],previous=runs[1];
 const gapDays=previous?Math.round((Date.parse(latest.cycle)-Date.parse(previous.cycle))/86400000):0;
 const mode=$("stratoTrendMode").value;
 const availableDelta=previous&&displayRows.some(r=>r.delta!==null);
 const table=$("stratoTrendTableBody");table.replaceChildren();
 const selectedRows=runs.map((run,i)=>{
  const row=run.rows.find(x=>x.key===selected);
  const prior=runs[i+1]?.rows.find(x=>x.key===selected);
  return {run,row,prior};
 });
 for(let i=0;i<selectedRows.length;i++){
  const r=selectedRows[i],tr=document.createElement("tr");
  const change=r.row&&r.prior?fixed(r.row.prob-r.prior.prob)+" pp":"–";
  for(const value of [stamp(r.run.cycle),r.row?fixed(r.row.prob)+" % ("+r.row.count+"/"+r.row.total+")":"–",
        change,r.row?fixed(r.row.mean)+" m/s":"–"]){
   const cell=document.createElement("td");cell.textContent=value;tr.appendChild(cell);
  }
  table.appendChild(tr);
 }
 const chosen=displayRows.find(r=>r.key===selected);
 const deltaText=chosen?.delta===null||chosen?.delta===undefined?"kein gemeinsamer Termin":(chosen.delta>=0?"+":"")+fixed(chosen.delta)+" Prozentpunkte";
 $("stratoTrendMeta").textContent=config($("stratoTrendModel").value).name+
    " · "+String($("stratoTrendHour").value).padStart(2,"0")+" UTC · "+
    runs.length+" vollständig verifizierte Läufe · neuester Lauf "+stamp(latest.cycle)+
    (previous?" · vorheriger archivierter "+stamp(previous.cycle)+(gapDays>1?" · "+gapDays+" Tage Abstand":""):" · Vergleichslauf fehlt")+
    " · gewählter Termin: "+(selected?selected.slice(0,16).replace("T"," ")+" UTC":"–")+
    " · Änderung: "+deltaText+".";
 $("stratoTrendCsv").disabled=false;
 if(mode==="delta"&&!availableDelta){
  clearChart();
  status("Für den Differenzvergleich sind mindestens zwei Läufe mit identischen UTC-Gültigkeitszeiten erforderlich. Bisher ist nur ein vollständiger Lauf verfügbar.");
  return;
 }
 if(typeof Chart!=="function"){status("Chart.js ist nicht verfügbar; die tabellarischen Originaldaten bleiben sichtbar.");return;}
 const labels=displayRows.map(r=>r.date),datasets=[];
 if(mode==="delta"){
  datasets.push({type:"bar",label:"Änderung zum vorherigen Archivlauf (Prozentpunkte)",
    data:displayRows.map(r=>r.delta),
    backgroundColor:displayRows.map(r=>r.delta===null?"transparent":r.delta>=0?"rgba(190,63,49,.72)":"rgba(28,108,169,.72)"),
    borderWidth:0,barPercentage:.85,categoryPercentage:.8});
  datasets.push({type:"line",label:"Keine Änderung",data:labels.map(()=>0),
    borderColor:"#5b6d7d",borderDash:[5,4],borderWidth:1,pointRadius:0,fill:false});
 }else{
  runs.forEach((run,i)=>{
   const lookup=new Map(run.rows.map(r=>[r.key,r]));
   datasets.push({type:"line",label:stamp(run.cycle),
     data:displayRows.map(row=>lookup.get(row.key)?.prob??null),
     borderColor:palette[i%palette.length],backgroundColor:palette[i%palette.length],
     borderWidth:i===0?3.4:1.8,pointRadius:i===0?2:0,pointHoverRadius:5,
     spanGaps:false,fill:false,tension:0});
  });
 }
 clearChart();
 chart=new Chart(canvas,{type:"line",data:{labels,datasets},options:{
  responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
  interaction:{mode:"index",intersect:false},
  plugins:{legend:{display:true,position:"bottom",labels:{boxWidth:15}},
   tooltip:{callbacks:{label:context=>{
    const value=context.parsed.y;
    if(!Number.isFinite(value))return "";
    if(mode==="delta"){
      const row=displayRows[context.dataIndex];
      return context.datasetIndex===0?
        "Änderung: "+(value>=0?"+":"")+fixed(value)+" pp · "+
        fixed(row.newest.prob)+" % statt "+fixed(row.previous.prob)+" %":
        "0 pp";
    }
    const row=displayRows[context.dataIndex],member=row.vals[context.datasetIndex];
    return context.dataset.label+": "+fixed(value)+" % ("+member.count+"/"+member.total+")";
   }}}},
  scales:{x:{grid:{display:false},ticks:{maxTicksLimit:13,maxRotation:0},
            title:{display:true,text:"Exakte Gültigkeit · "+$("stratoTrendHour").value+" UTC"}},
   y:{min:mode==="delta"?undefined:0,max:mode==="delta"?undefined:100,
     title:{display:true,text:mode==="delta"?"Änderung gegenüber Vorlauf (Prozentpunkte)":"Anteil der Ensemblemitglieder mit U < 0 m/s (%)"},
     ticks:{callback:v=>v+(mode==="delta"?" pp":" %")}}}
 }});
 $("stratoTrendPng").disabled=false;
 status("Originalprognosen: "+runs.length+" Läufe; "+displayRows.length+
  " überprüfte Gültigkeitszeitpunkte."+(loadFailures?" "+loadFailures+" Archivrufe nicht verfügbar.":"")+
  (previous?" Differenzen ausschließlich für exakt übereinstimmende Termine.":" Für die Laufänderung wird ein zweiter verfügbarer Archivlauf benötigt."));
}
async function refresh(force=false){
 const token=++viewKey,model=$("stratoTrendModel").value;
 loadState="loading";status("Prüfe archivierte Original-Ensembles …");
 runs=[];displayRows=[];clearChart();drawHeatmap();
 $("stratoTrendTableBody").replaceChildren();
 $("stratoTrendMeta").textContent="Prüfe die Originaldaten des gewählten Modellzyklus …";
 $("stratoTrendCsv").disabled=true;
 $("stratoTrendReload").disabled=true;
 if(force||!indexes[model].length)indexes[model]=await loadIndex(model);
 if(token!==viewKey)return;
 modelChoices();
 const hour=$("stratoTrendHour").value;
 const wanted=Number($("stratoTrendCount").value);
 let entries=indexes[model].filter(r=>r.cycle_utc.slice(11,13)===hour).slice(0,wanted);
 loadFailures=0;
 let loaded=[];
 if(entries.length){
  const results=await Promise.allSettled(entries.map(r=>loadRun(model,r)));
  if(token!==viewKey)return;
  loaded=results.filter(r=>r.status==="fulfilled").map(r=>r.value);
  loadFailures=results.filter(r=>r.status==="rejected").length;
 }else{
  try{
   const current=await loadRun(model,null);
   if(token!==viewKey)return;
   if(current.cycle.slice(11,13)===hour)loaded=[current];
  }catch(error){loadFailures=1;console.info("Kein gültiger aktueller Ensemble-Lauf",model,error);}
 }
 if(token!==viewKey)return;
 runs=loaded.sort((a,b)=>b.cycle.localeCompare(a.cycle));
 loadState="ready";
 $("stratoTrendReload").disabled=false;
 draw();
}
function download(name,text,type){
 const blob=new Blob([text],{type}),url=URL.createObjectURL(blob);
 const link=document.createElement("a");link.href=url;link.download=name;
 document.body.appendChild(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),3500);
}
$("stratoHeatCsv").addEventListener("click",()=>{
 if(!heatmapState)return;
 download("Stratosphaere_Windumkehr_Heatmap_"+$("stratoTrendModel").value+"_"+
  $("stratoTrendHour").value+"UTC.csv",heatmapCSV(heatmapState),"text/csv;charset=utf-8");
});
$("stratoHeatPng").addEventListener("click",()=>{
 if(!heatmapState)return;
 const dataUrl=heatmapPng(heatmapState);if(!dataUrl)return;
 const link=document.createElement("a");
 link.href=dataUrl;link.download="Stratosphaere_Windumkehr_Heatmap_"+
  $("stratoTrendModel").value+"_"+$("stratoTrendHour").value+"UTC.png";
 link.click();
});
$("stratoTrendModel").addEventListener("change",()=>{indexes[$("stratoTrendModel").value]=[];void refresh(true);});
$("stratoTrendHour").addEventListener("change",()=>void refresh(false));
$("stratoTrendCount").addEventListener("change",()=>void refresh(false));
$("stratoTrendHorizon").addEventListener("change",draw);
$("stratoTrendMode").addEventListener("change",draw);
$("stratoTrendValid").addEventListener("change",draw);
$("stratoTrendReload").addEventListener("click",()=>void refresh(true));
$("stratoTrendPng").addEventListener("click",()=>{
 if(!chart)return;
 const link=document.createElement("a");link.href=chart.toBase64Image("image/png",1);
 link.download="Stratosphaere_Laufentwicklung_"+$("stratoTrendModel").value+"_"+$("stratoTrendHour").value+"UTC.png";
 link.click();
});
$("stratoTrendCsv").addEventListener("click",()=>{
 if(!displayRows.length)return;
 const header=["Gueltig_UTC","Modell","Modelllaeufe_UTC","Member","U_negativ_Anzahl","U_negativ_Prozent","Mittelwind_m_s","Delta_zum_vorherigen_Archivlauf_pp"];
 const records=[header.join(";")];
 for(const row of displayRows){
  runs.forEach((run,i)=>{
   const p=row.vals[i];if(!p)return;
   const before=row.vals[i+1];
   records.push([row.key,$("stratoTrendModel").value,run.cycle,p.total,p.count,
     p.prob.toFixed(4),p.mean.toFixed(4),before?(p.prob-before.prob).toFixed(4):""].join(";"));
  });
 }
 download("Stratosphaere_Laufentwicklung_"+$("stratoTrendModel").value+"_"+$("stratoTrendHour").value+"UTC.csv",
          "\ufeff"+records.join("\r\n"),"text/csv;charset=utf-8");
});
void refresh(true);
})();