(()=>{
"use strict";
const $=id=>document.getElementById(id), core=window.BundeslaenderRecords;
const base="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/bundeslaender-data-";
const regions=["Deutschland","Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"];
const params={tmin:"°C",tmax:"°C",tmean:"°C",precipitation:"mm",sunshine:"h"};
let archive=null,token=0,rows=[],annualRows=[];
for(const r of regions)$("region").add(new Option(r,r));
$("region").value="Deutschland";
const fmt=(v,n=2)=>v.toLocaleString("de-DE",{minimumFractionDigits:n,maximumFractionDigits:n});
const german=d=>d?d.split("-").reverse().join("."):"—";
async function get(url){const r=await fetch(url,{cache:"no-cache"});if(!r.ok)throw Error("HTTP "+r.status);return r.json();}
function fullYears(a,b){let n=+b.slice(0,4)- +a.slice(0,4);if(b.slice(5)<a.slice(5))n--;return Math.max(0,n);}
async function load(){
 const t=++token,p=$("parameter").value,mode=$("source").value,station=mode==="station",extreme=mode==="extreme";
 if(extreme&&!$("direction").value)$("direction").value="low";
 $("direction").options[0].disabled=extreme;
 const dir=$("direction").value;
 const url=extreme?"https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/bundeslaender-station-data/extremes/"+p+"/"+dir:station?"https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/bundeslaender-station-data/"+p:base+p;
 $("annual").hidden=true;$("annualRows").replaceChildren();$("annualCsv").disabled=true;annualRows=[];
 $("valueHeading").textContent=extreme?"Stations-Extremwert":station?"Stationsmittel":"Flächenmittel";archive=null;rows=[];$("rows").replaceChildren();$("csv").disabled=true;$("day").disabled=true;
 $("status").textContent="Beobachtungsarchiv wird geladen …";
 try{
  const idx=await get(url+"/index.json"), docs=[], failed=[];
  if(t!==token)return;
  for(let i=0;i<idx.years.length;i+=8){
   const batch=idx.years.slice(i,i+8);
   await Promise.all(batch.map(async y=>{try{const d=await get(url+"/"+y+".json");if(d.year!==y||d.parameter!==p||!Array.isArray(d.dates)||!d.regions)throw Error("Schema");docs.push(d);}catch(e){failed.push(y);}}));
   if(t!==token)return;
   $("status").textContent="Archiv laden: "+Math.min(i+8,idx.years.length)+"/"+idx.years.length+" Jahre …";
  }
  if(!docs.length)throw Error("Keine Jahresdatei verfügbar");
  docs.sort((a,b)=>a.year-b.year);
  const series=Object.fromEntries(regions.map(r=>[r,[]]));
  for(const doc of docs)for(const r of regions)for(let i=0;i<doc.dates.length;i++){
   const v=doc.regions[r]?.[i];series[r].push({date:doc.dates[i],value:Number.isFinite(v)?v:null,stationId:doc.station_ids?.[r]?.[i]??null,count:doc.counts?.[r]?.[i]??null});
  }
  const dates=[...new Set(docs.flatMap(d=>d.dates))].sort();
  archive={p,idx,series,dates,failed,station,extreme,dir};
  $("day").min=dates[0];$("day").max=dates.at(-1);if(!dates.includes($("day").value))$("day").value=dates.at(-1);
  $("day").disabled=false;render();
 }catch(e){if(t!==token)return;$("status").textContent=p==="sunshine"?"Sonnenscheinarchiv noch nicht veröffentlicht; keine historischen Rekordaussagen verfügbar.":"Datenarchiv noch nicht verfügbar ("+e.message+").";}
}
function render(){
 if(!archive)return;const {p,idx,series,dates,failed,station,extreme}=archive,target=$("day").value;
 rows=[];$("rows").replaceChildren();$("csv").disabled=true;
 const summary="DWD "+(extreme?"KL · beobachtete Stations-Extremwerte (wechselndes Netz)":station?"KL · festes Stationspanel (kein Flächenmittel)":p==="sunshine"?"DUETT":"HYRAS")+" · "+german(dates[0])+" bis "+german(dates.at(-1))+" · "+(idx.years.length-failed.length)+" geladene Jahre · "+(failed.length?"Fehlende Downloads: "+failed.join(", ")+" · ":"")+"Archiv im Aufbau; vollständige Vergleichszeit je Zeile.";
 $("status").textContent=summary;
 if(!dates.includes(target)){$("status").textContent+=" Kein Beobachtungswert am gewählten Datum.";return;}
 renderAnnual();
 const periods=$("period").value?[$("period").value]:Object.keys(core.periods);
 const directions=$("direction").value?[$("direction").value]:["low","high"];
 const threshold=+$("years").value;
 for(const r of regions){
  if($("region").value&&$("region").value!==r)continue;
  const s=series[r];
  for(const period of periods){
   const first=core.coverage(s,target,period);
   const valid=s.filter(x=>x.date>=first&&x.date<=target);
   for(const dir of directions){
    const v=core.compare(valid,target,period,dir);if(!v)continue;
    const since=v.last?.date||first, duration=fullYears(since,target);
    if(duration<threshold)continue;
    rows.push({r,period,dir,value:v.value,last:v.last?.date||"",duration,rank:v.rank,days:v.days+1,ties:v.ties,first});
   }
  }
 }
 rows.sort((a,b)=>b.duration-a.duration||a.rank-b.rank||a.r.localeCompare(b.r,"de"));
 const frag=document.createDocumentFragment();
 for(const x of rows){
  const tr=document.createElement("tr"), values=[x.r+(station?" ("+(idx.station_counts?.[x.r]||0)+" St.)":""),core.periods[x.period],x.dir==="low"?"Niedrigste":"Höchste",fmt(x.value)+" "+params[p],x.last?german(x.last):"Kein früherer Wert im belegten Zeitraum",x.duration+(x.last?"":" (mind.)"),x.rank+" / "+x.days,x.ties,german(x.first)];
  values.forEach((v,i)=>{const td=document.createElement("td");td.textContent=v;if(i===3)td.className=x.dir==="low"?"cold":"warm";tr.append(td);});frag.append(tr);
 }
 $("rows").append(frag);$("csv").disabled=!rows.length;$("status").textContent+=" · "+rows.length+" Treffer.";
}
function renderAnnual(){
 $("annual").hidden=!archive?.extreme;annualRows=[];$("annualRows").replaceChildren();$("annualCsv").disabled=true;
 if(!archive?.extreme)return;
 const {series,idx,dir}=archive,target=$("day").value,r=$("region").value||"Deutschland",period=$("period").value||"month";
 const list=series[r],today=list.find(x=>x.date===target);
 const prior=core.annualExtremes(list,target,period,dir);
 const current=list.filter(x=>x.date<=target&&x.date.slice(0,4)===target.slice(0,4)&&core.bucket(x.date,period)===core.bucket(target,period)&&Number.isFinite(x.value)).reduce((a,x)=>!a||(dir==="low"?x.value<a.value:x.value>a.value)?x:a,null);
 const last=prior.find(x=>x.entry&&today&&Number.isFinite(today.value)&&(dir==="low"?x.entry.value<=today.value:x.entry.value>=today.value));
 const name=x=>x?.stationId?(idx.station_names?.[x.stationId]||x.stationId)+" ("+x.stationId+")":"—";
 $("annualSummary").textContent=r+" · "+core.periods[period]+(period==="month"?" "+new Date(target+"T12:00:00Z").toLocaleString("de-DE",{month:"long",timeZone:"UTC"}):"")+" · "+german(target)+": "+(today&&Number.isFinite(today.value)?fmt(today.value,1)+" °C · "+name(today):"keine Messung")+(last?" · Vorjahr zuletzt gleich/extremer: "+last.year:" · Kein gleich/extremer Vorjahreswert im geladenen Archiv");
 annualRows=[{year:target.slice(0,4)+" · Stichtag",entry:today},{year:target.slice(0,4)+" · bisher",entry:current},...prior];
 for(const row of annualRows){
  const x=row.entry,tr=document.createElement("tr");
  [row.year,x&&Number.isFinite(x.value)?fmt(x.value,1)+" °C":"—",german(x?.date),name(x),x?.count??"—"].forEach((v,i)=>{const td=document.createElement("td");td.textContent=v;if(i===1&&x&&Number.isFinite(x.value))td.className=dir==="low"?"cold":"warm";tr.append(td);});$("annualRows").append(tr);
 }
 $("annualCsv").disabled=false;
}
$("annualCsv").addEventListener("click",()=>{
 const r=$("region").value||"Deutschland",p=$("period").value||"month";
 const data=[["Gebiet","Parameter","Vergleich","Richtung","Stichtag","Jahr","Wert °C","Datum","Stations-ID","Station","Stationszahl"],...annualRows.map(row=>{const x=row.entry;return [r,archive.p,p,archive.dir,$("day").value,row.year,x?.value??"",x?.date??"",x?.stationId??"",archive.idx.station_names?.[x?.stationId]??"",x?.count??""];})];
 const csv=data.map(a=>a.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(";")).join("\r\n");
 const url=URL.createObjectURL(new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"})),a=document.createElement("a");a.href=url;a.download="stations-extreme-jahresliste.csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$("csv").addEventListener("click",()=>{
 const headers=["Gebiet","Datenbasis","Stationszahl","Vergleich","Richtung","Datum","Wert","Einheit","Zuletzt gleich/extremer","Volle Jahre","Rang","Tage","Gleichstände","Belegt ab"];
 const data=[headers,...rows.map(x=>[x.r,archive.extreme?"DWD KL Stations-Extremwert":archive.station?"DWD KL Stationsmittel":archive.p==="sunshine"?"DUETT":"HYRAS",archive.station?archive.idx.station_counts?.[x.r]??"":"",core.periods[x.period],x.dir,$("day").value,String(x.value).replace(".",","),params[archive.p],x.last,x.duration,x.rank,x.days,x.ties,x.first])];
 const csv=data.map(a=>a.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(";")).join("\r\n");
 const url=URL.createObjectURL(new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"})),a=document.createElement("a");a.href=url;a.download="bundeslaender-rekorde-"+archive.p+"-"+$("day").value+".csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$("parameter").addEventListener("change",()=>{if(["precipitation","sunshine"].includes($("parameter").value))$("source").value="grid";load();});
$("source").addEventListener("change",()=>{if($("source").value!=="grid"&&["precipitation","sunshine"].includes($("parameter").value))$("parameter").value="tmin";load();});
for(const id of ["day","region","period","years"])$(id).addEventListener("change",render);
$("direction").addEventListener("change",()=>{$("source").value==="extreme"?load():render();});
load();
})();