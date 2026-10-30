/* Polar-vortex reversal diagnostics from complete original GEFS/ECMWF 60N,10hPa members.
   Only DAILY sampled U<0 episodes are observable. No hourly event times are inferred. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
if(!$("stratoDiagModel")||!$("stratoDiagCycle"))return;
const ROOT="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/";
const CONFIG={
 gefs:{provider:"NOAA GEFS",branch:"stratosphere-ensemble-data",directory:"data/stratosphere/ensemble/",
        index:"gefs_index.json",current:"gefs_current.json",members:31,perturbed:30,hours:[0,6,12,18]},
 eps:{provider:"ECMWF IFS ENS",branch:"stratosphere-ecmwf-ens-data",directory:"data/stratosphere/ecmwf/",
       index:"ens_index.json",current:"ens_current.json",members:51,perturbed:50,hours:[0,12]}
};
let available=[],active=null,analyses=null,onsetChart=null,durationChart=null,requestToken=0;
const stamp=s=>s.slice(0,16).replace("T"," ")+" UTC";
const fmt=n=>Number(n).toFixed(1).replace(".",",");
const pct=(n,total)=>100*n/total;
function cycleOK(s){
 return typeof s==="string"&&/^\d{4}-\d\d-\d\dT(?:00|06|12|18):00:00Z$/.test(s)&&
  !Number.isNaN(Date.parse(s))&&Date.parse(s)<=Date.now()&&Date.now()-Date.parse(s)<=10*86400000;
}
function verify(data,which){
 const cfg=CONFIG[which];
 if(!cfg||!data||data.schema_version!==1||data.provider!==cfg.provider||
 data.level_hpa!==10||data.latitude_deg!==60||data.units!=="m/s"||
 !cycleOK(data.cycle_utc)||!cfg.hours.includes(Number(data.cycle_utc.slice(11,13)))||
 data.member_count!==cfg.members)throw Error("Ungültige Modelldaten/Initialisierung");
 const days=data.forecast_horizon_days,init=Date.parse(data.cycle_utc);
 if(!Number.isInteger(days)||(which==="eps"?days!==15:
     (days!==16&&days!==35||days===35&&Number(data.cycle_utc.slice(11,13))!==0))||
 !Array.isArray(data.valid_dates)||data.valid_dates.length!==days+1||
 data.valid_dates.some((x,i)=>x!==new Date(init+i*86400000).toISOString().slice(0,10)))
 throw Error("Unvollständige 24-Stunden-Gültigkeit");
 if(which==="eps"&&(data.perturbed_count!==50||data.valid_hour_utc!==Number(data.cycle_utc.slice(11,13))||
   data.stream_ensemble!=="enfo/ef"||data.stream_control!=="oper/fc"||
   !Array.isArray(data.forecast_step_hours)||data.forecast_step_hours.length!==days+1||
   data.forecast_step_hours.some((x,i)=>x!==i*24)))
 throw Error("Unvollständige ECMWF-ENS-Struktur");
 const keys=["c00",...Array.from({length:cfg.perturbed},(_,i)=>"p"+String(i+1).padStart(2,"0"))];
 if(!data.members||Object.keys(data.members).length!==keys.length||
    keys.some(key=>!Object.hasOwn(data.members,key)||!Array.isArray(data.members[key])||
       data.members[key].length!==days+1||
       data.members[key].some(u=>typeof u!=="number"||!Number.isFinite(u)||u<=-160||u>=170)))
 throw Error("Unvollständige Original-Mitglieder");
 return data;
}
function analyzeMember(values,cycle,name){
 const start=Date.parse(cycle),n=values.length;
 const absoluteMinimum=Math.min(...values);
 const absoluteMinimumIndex=values.indexOf(absoluteMinimum);
 const startedNegative=values[0]<0;
 let firstCrossing=-1,anyCrossings=0;
 for(let i=1;i<n;i++)if(values[i-1]>=0&&values[i]<0){
  anyCrossings++;if(firstCrossing<0)firstCrossing=i;
 }
 // Use first newly observed reversal; if negative already at f0, that
 // baseline episode is left-censored and cannot count as a NEW crossing.
 // The first visible baseline-negative episode is left-censored.
 const onsetIndex=startedNegative?0:firstCrossing;
 let consecutiveNegative=0,recoveryIndex=-1,rightCensored=false;
 let maxNegativeRun=0,currentNegativeRun=0;
 for(const u of values){
  currentNegativeRun=u<0?currentNegativeRun+1:0;
  maxNegativeRun=Math.max(maxNegativeRun,currentNegativeRun);
 }
 let episodeMinimum=null;
 if(onsetIndex>=0){
  let end=onsetIndex;
  while(end<n&&values[end]<0){
   consecutiveNegative++;episodeMinimum=episodeMinimum===null?
     values[end]:Math.min(episodeMinimum,values[end]);end++;
  }
  if(end<n)recoveryIndex=end;
  else rightCensored=true;
 }
 let recoveryAfterNewIndex=-1,newCrossRightCensored=false;
 if(firstCrossing>=0){
  let end=firstCrossing;
  while(end<n&&values[end]<0)end++;
  recoveryAfterNewIndex=end<n?end:-1;
  newCrossRightCensored=end===n;
 }
 const time=i=>i<0?null:new Date(start+i*86400000).toISOString();
 return {name,startedNegative,firstCrossing,anyCrossings,
   onsetIndex,onsetTime:time(onsetIndex),newCrossTime:time(firstCrossing),
   consecutiveNegative,maxNegativeRun,recoveryIndex,recoveryTime:time(recoveryIndex),
   recoveryAfterNewIndex,recoveryAfterNewTime:time(recoveryAfterNewIndex),
   newCrossRightCensored,rightCensored,episodeMinimum,absoluteMinimum,
   absoluteMinimumIndex,absoluteMinimumTime:time(absoluteMinimumIndex)};
}
function analyze(data){
 const names=["c00",...Array.from({length:data.member_count-1},(_,i)=>"p"+String(i+1).padStart(2,"0"))];
 const members=names.map(name=>analyzeMember(data.members[name],data.cycle_utc,name));
 const n=members.length,days=data.valid_dates.length;
 const firstCrossingHistogram=Array(days).fill(0),durationRecovered=Array(days+1).fill(0),
       durationCensored=Array(days+1).fill(0);
 members.forEach(m=>{
  if(m.firstCrossing>=0)firstCrossingHistogram[m.firstCrossing]++;
  if(m.onsetIndex>=0){
    (m.rightCensored?durationCensored:durationRecovered)[m.consecutiveNegative]++;
  }
 });
 const newCrossings=members.filter(m=>m.firstCrossing>=0).length;
 const baseline=members.filter(m=>m.startedNegative).length;
 const long3=members.filter(m=>m.maxNegativeRun>=3).length;
 const long5=members.filter(m=>m.maxNegativeRun>=5).length;
 const recovery=members.filter(m=>m.firstCrossing>=0&&m.recoveryAfterNewIndex>=0).length;
 const unresolved=members.filter(m=>m.firstCrossing>=0&&m.newCrossRightCensored).length;
 const worst=members.reduce((a,b)=>a.absoluteMinimum<=b.absoluteMinimum?a:b);
 const onsetDate=Array.from({length:days},(_,i)=>
   new Date(Date.parse(data.cycle_utc)+i*86400000).toISOString());
 return {cycle:data.cycle_utc,days:days-1,total:n,members,firstCrossingHistogram,
   durationRecovered,durationCensored,onsetDate,newCrossings,baseline,long3,long5,recovery,unresolved,worst};
}
function status(s){$("stratoDiagStatus").textContent=s;}
function info(s){$("stratoDiagInfo").textContent=s;}
function destroyCharts(){
 if(onsetChart){onsetChart.destroy();onsetChart=null;}
 if(durationChart){durationChart.destroy();durationChart=null;}
 $("stratoDiagPng").disabled=true;
}
function release(){
 active=null;analyses=null;
 destroyCharts();$("stratoDiagCsv").disabled=true;
 $("stratoDiagTableBody").replaceChildren();
 for(const id of ["stratoDiagCross","stratoDiagBaseline","stratoDiagLong","stratoDiagMin","stratoDiagReturn"]){
  $(id).textContent="–";
 }
}
async function fetchJSON(url){
 const res=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
 if(!res.ok)throw Error("HTTP "+res.status);
 return res.json();
}
function root(which){const c=CONFIG[which];return ROOT+c.branch+"/"+c.directory;}
async function findRuns(which){
 const c=CONFIG[which],base=root(which);
 try{
  const index=await fetchJSON(base+c.index);
  if(index.schema_version!==1||index.provider!==c.provider||!Array.isArray(index.runs))throw Error("Ungültiger Index");
  const seen=new Set();
  return index.runs.filter(r=>{
   if(!r||!cycleOK(r.cycle_utc)||!c.hours.includes(Number(r.cycle_utc.slice(11,13)))||
      !/^runs\/\d{8}_\d{6}\.json$/.test(r.path)||seen.has(r.cycle_utc))return false;
   seen.add(r.cycle_utc);return true;
  }).sort((a,b)=>b.cycle_utc.localeCompare(a.cycle_utc));
 }catch(error){
  console.info("Stratosphäre-Diagnostik: Archivindex nicht verfügbar",error);
  return [];
 }
}
function setRunOptions(list){
 const select=$("stratoDiagCycle"),previous=select.value;select.replaceChildren();
 list.forEach(entry=>{
  const option=document.createElement("option");option.value=entry.cycle_utc;
  option.textContent=stamp(entry.cycle_utc)+" · "+entry.forecast_horizon_days+" Tage";
  select.add(option);
 });
 select.value=list.some(x=>x.cycle_utc===previous)?previous:list[0]?.cycle_utc||"";
}
async function refreshIndex(){
 const token=++requestToken,which=$("stratoDiagModel").value;
 release();status("Prüfe die veröffentlichten Ensemble-Laufarchive …");
 $("stratoDiagReload").disabled=true;
 available=await findRuns(which);
 if(token!==requestToken)return;
 setRunOptions(available);
 $("stratoDiagReload").disabled=false;
 await loadSelected(token);
}
async function loadSelected(token){
 const ownToken=token??++requestToken,which=$("stratoDiagModel").value;
 release();status("Lade 31 beziehungsweise 51 originale Ensemblemitglieder …");
 const entry=available.find(x=>x.cycle_utc===$("stratoDiagCycle").value);
 try{
  const data=verify(await fetchJSON(root(which)+(entry?entry.path:CONFIG[which].current)),which);
  if(ownToken!==requestToken)return;
  if(entry&&data.cycle_utc!==entry.cycle_utc)throw Error("Archivlauf nicht identisch");
  active=data;analyses=analyze(data);draw();
 }catch(error){
  if(ownToken!==requestToken)return;
  release();status("Keine gültigen vollständigen Original-Mitglieder für den ausgewählten Lauf: "+error.message);
  info("Bitte den Modelllauf oder die Modellart prüfen. Es werden keine fehlenden Daten simuliert.");
 }
}
function draw(){
 if(!active||!analyses)return;
 const a=analyses,den=a.total;
 $("stratoDiagCross").textContent=fmt(pct(a.newCrossings,den))+" % · "+a.newCrossings+"/"+den;
 $("stratoDiagBaseline").textContent=a.baseline+"/"+den;
 $("stratoDiagLong").textContent=fmt(pct(a.long3,den))+" % · "+a.long3+"/"+den;
 $("stratoDiagMin").textContent=fmt(a.worst.absoluteMinimum)+" m/s · "+a.worst.name;
 $("stratoDiagReturn").textContent=a.recovery+" zurück · "+a.unresolved+" rechtszensiert";
 const table=$("stratoDiagTableBody");table.replaceChildren();
 const label=x=>x?x.slice(0,10)+" "+x.slice(11,13)+" UTC":"–";
 for(const m of a.members){
  const tr=document.createElement("tr");
  const category=m.startedNegative?"Bereits zu Beginn negativ":
     m.firstCrossing>=0?"Neue Windumkehr":"Keine neue Windumkehr";
  const values=[m.name,category,label(m.onsetTime),
     m.onsetIndex>=0?m.consecutiveNegative+" Tageswerte"+(m.rightCensored?" · ≥":""):"–",
     label(m.recoveryTime),fmt(m.absoluteMinimum)+" m/s",
     label(m.absoluteMinimumTime),String(m.anyCrossings)];
  for(const v of values){const td=document.createElement("td");td.textContent=v;tr.appendChild(td);}
  table.appendChild(tr);
 }
 const onsetLabels=a.onsetDate.map(x=>x.slice(5,10).replace("-",".")+" · "+x.slice(11,13)+" UTC");
 const max=Number($("stratoDiagDays").value);
 const shown=a.onsetDate.map((_,i)=>i<=max);
 destroyCharts();
 if(typeof Chart==="function"){
  onsetChart=new Chart($("stratoDiagOnset"),{type:"bar",data:{
   labels:onsetLabels.filter((_,i)=>shown[i]),
   datasets:[{label:"Erster neuer Übergang zu Ostwind (% aller Mitglieder)",
    data:a.firstCrossingHistogram.filter((_,i)=>shown[i]).map(v=>pct(v,den)),
    backgroundColor:"rgba(174,64,57,.8)",borderRadius:3}]
  },options:{responsive:true,maintainAspectRatio:false,animation:false,
   plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>{
    const n=Math.round(ctx.parsed.y*den/100);
    return fmt(ctx.parsed.y)+" % · "+n+"/"+den+" Mitglieder";
   }}}},
   scales:{y:{beginAtZero:true,max:100,title:{display:true,text:"Erste Windumkehr je Tag (%)"}},
           x:{ticks:{maxTicksLimit:11,maxRotation:0},title:{display:true,text:"Nur neue Übergänge zwischen zwei aufeinanderfolgenden 24h-Terminen"}}}}});
  const end=Math.min(max,a.durationRecovered.length-1);
  const dLabels=Array.from({length:end},(_,i)=>String(i+1));
  durationChart=new Chart($("stratoDiagDuration"),{type:"bar",data:{labels:dLabels,datasets:[
   {label:"Rückkehr zum Westwind beobachtet",data:dLabels.map((_,i)=>a.durationRecovered[i+1]),
    backgroundColor:"rgba(33,120,173,.8)"},
   {label:"Am Prognoseende weiter negativ",data:dLabels.map((_,i)=>a.durationCensored[i+1]),
    backgroundColor:"rgba(211,131,44,.85)"}
  ]},options:{responsive:true,maintainAspectRatio:false,animation:false,
     plugins:{legend:{position:"bottom"}},
     scales:{x:{stacked:true,title:{display:true,text:"Anzahl aufeinanderfolgender negativer Tageswerte"}},y:{
         stacked:true,beginAtZero:true,ticks:{precision:0},title:{display:true,text:"Ensemblemitglieder"}}}}});
  $("stratoDiagPng").disabled=false;
 }
 $("stratoDiagCsv").disabled=false;
 status(CONFIG[$("stratoDiagModel").value].provider+" · "+
   stamp(a.cycle)+" · "+den+" vollständig geprüfte Mitglieder · "+a.days+
   " Tage (24-Stunden-Abtastung).");
 info("Neue Windumkehr: "+a.newCrossings+"/"+den+
  " Mitglieder; erste Übergänge an aufeinanderfolgenden Tageswerten. "+
  a.baseline+" Mitglieder sind bereits zum Start negativ (kein neu prognostizierter Übergang). "+
  a.long3+" Mitglieder haben mindestens drei aufeinanderfolgende negative Tageswerte in mindestens einer Episode; "+
  a.long5+" mindestens fünf. Die aufgeführte Dauer ist keine stundengenaue Dauer. "+
  "Bei am letzten Tag anhaltendem Ostwind ist sie rechtszensiert (Mindestdauer). "+
  "Das Windminimum ist jeweils das Minimum aller Tageswerte des gewählten Laufs.");
}
function csv(){
 if(!analyses)return "";
 const rows=["Modell;Lauf_UTC;Mitglied;Start_schon_negativ;Erster_neuer_Uebergang_UTC;Anzahl_Uebergaenge;Negative_Tageswerte_in_erster_Episode;Max_negative_Tageswerte_in_einer_Episode;Rueckkehr_erste_Episode_UTC;Erholung_nach_neuer_Windumkehr_UTC;Neue_Windumkehr_am_Ende_ohne_Erholung;Minimum_U_m_s;Minimum_gueltig_UTC"];
 const model=$("stratoDiagModel").value;
 for(const m of analyses.members){
  rows.push([model,analyses.cycle,m.name,m.startedNegative?"ja":"nein",m.newCrossTime||"",
   m.anyCrossings,m.consecutiveNegative,m.maxNegativeRun,m.recoveryTime||"",m.recoveryAfterNewTime||"",m.newCrossRightCensored?"ja":"nein",
   m.absoluteMinimum.toFixed(3),m.absoluteMinimumTime].join(";"));
 }
 return "\ufeff"+rows.join("\r\n");
}
function download(filename,content){
 const blob=new Blob([content],{type:"text/csv;charset=utf-8"}),url=URL.createObjectURL(blob);
 const link=document.createElement("a");link.href=url;link.download=filename;
 document.body.appendChild(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),2500);
}
$("stratoDiagModel").addEventListener("change",()=>void refreshIndex());
$("stratoDiagCycle").addEventListener("change",()=>void loadSelected());
$("stratoDiagDays").addEventListener("change",draw);
$("stratoDiagReload").addEventListener("click",()=>void refreshIndex());
$("stratoDiagCsv").addEventListener("click",()=>{
 if(!analyses)return;
 download("Stratosphaere_Windumkehr_Diagnostik_"+$("stratoDiagModel").value+"_"+analyses.cycle.slice(0,13)+".csv",csv());
});
$("stratoDiagPng").addEventListener("click",()=>{
 if(!onsetChart||!durationChart)return;
 const canvas=document.createElement("canvas");canvas.width=1550;canvas.height=1160;
 const ctx=canvas.getContext("2d");if(!ctx)return;
 ctx.fillStyle="#ffffff";ctx.fillRect(0,0,1550,1160);
 ctx.fillStyle="#1b354c";ctx.font="bold 25px sans-serif";
 ctx.fillText("Polarwirbel · Windumkehr-Diagnostik · "+CONFIG[$("stratoDiagModel").value].provider,38,48);
 ctx.font="16px sans-serif";ctx.fillText("Lauf "+stamp(analyses.cycle)+
 " · "+analyses.total+" Originalmitglieder · 60°N/10 hPa",38,82);
 ctx.drawImage($("stratoDiagOnset"),28,120,1490,430);
 ctx.drawImage($("stratoDiagDuration"),28,570,1490,430);
 ctx.font="14px sans-serif";ctx.fillStyle="#4e6170";
 ctx.fillText("24h-Abtastung · rechts-/linkszensierte Ereignisse getrennt gekennzeichnet · keine Major-SSW-Wahrscheinlichkeit",38,1080);
 const link=document.createElement("a");link.href=canvas.toDataURL("image/png");
 link.download="Stratosphaere_Windumkehr_Diagnostik_"+$("stratoDiagModel").value+".png";link.click();
});
void refreshIndex();
})();