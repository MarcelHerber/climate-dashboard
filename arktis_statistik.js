/* DMI +80°N: historical records, percentiles, monthly and seasonal rankings. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const good=v=>typeof v==="number"&&Number.isFinite(v);
const mn=["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
const fmt=v=>good(v)?v.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–";
const signed=v=>good(v)?(v>0?"+":"")+fmt(v):"–";
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
const quantile=(sorted,p)=>{const pos=(sorted.length-1)*p,lo=Math.floor(pos),hi=Math.ceil(pos);return sorted[lo]+(sorted[hi]-sorted[lo])*(pos-lo);};
const dayIdx=(doc,m,d)=>doc.days.indexOf(String(m).padStart(2,"0")+"-"+String(d).padStart(2,"0"));
const monthSlots=(doc,m)=>doc.days.map((d,i)=>d.startsWith(String(m).padStart(2,"0")+"-")?i:-1).filter(i=>i>=0);
function daily(doc,index,year){
 const values=Object.entries(doc.years).map(([y,series])=>({year:Number(y),value:series[index]})).filter(x=>good(x.value)).sort((a,b)=>a.value-b.value||a.year-b.year);
 const selected=values.find(x=>x.year===Number(year)); const sorted=values.map(x=>x.value);
 return {count:values.length,min:values[0]||null,max:values[values.length-1]||null,
   p10:values.length>=5?quantile(sorted,.10):null,p90:values.length>=5?quantile(sorted,.90):null,
   rank:selected?values.filter(x=>x.value>selected.value).length+1:null,
   selected:selected||null,highest:values.slice(-10).reverse(),lowest:values.slice(0,10)};
}
function period(doc,year,definition){
 const slots=[];
 for(const [offset,month] of definition){
   const y=year+offset, series=doc.years[String(y)];
   if(!series)return null;
   const indices=monthSlots(doc,month).filter(i=>!(doc.days[i]==="02-29"&& !(y%4===0&&(y%100!==0||y%400===0))));
   for(const index of indices){if(!good(series[index]))return null;slots.push(series[index]);}
 }
 return slots.length?mean(slots):null;
}
const periods=[
 ...mn.map((label,i)=>({id:"m"+(i+1),label,def:[[0,i+1]]})),
 {id:"djf",label:"Winter (DJF)",def:[[-1,12],[0,1],[0,2]]},
 {id:"mam",label:"Frühling (MAM)",def:[[0,3],[0,4],[0,5]]},
 {id:"jja",label:"Sommer (JJA)",def:[[0,6],[0,7],[0,8]]},
 {id:"son",label:"Herbst (SON)",def:[[0,9],[0,10],[0,11]]}
];
function periodStats(doc,chosen,year){
 const list=Object.keys(doc.years).map(Number).map(y=>({year:y,value:period(doc,y,chosen.def)})).filter(x=>good(x.value));
 const desc=list.slice().sort((a,b)=>b.value-a.value||a.year-b.year),asc=list.slice().sort((a,b)=>a.value-b.value||a.year-b.year);
 const current=list.find(x=>x.year===Number(year));
 return {count:list.length,selected:current||null,rank:current?list.filter(x=>x.value>current.value).length+1:null,
   mean:list.length?mean(list.map(x=>x.value)):null,warmest:desc.slice(0,10),coldest:asc.slice(0,10)};
}
window.Arctic80StatsMath={daily,period,periodStats,quantile,periods};
let doc;
const tableRows=(list,year)=>list.map((x,i)=>'<tr'+(x.year===Number(year)?' class="arctic-selected"':'')+'><td>'+(i+1)+'.</td><td>'+x.year+'</td><td>'+fmt(x.value)+' °C</td></tr>').join("");
function render(){
 if(!doc)return;
 const year=$("arcticYear").value,parts=$("arcticRecordDay").value.split("-").map(Number);
 const index=dayIdx(doc,parts[0],parts[1]);
 if(index<0)return;
 const dailyValues=daily(doc,index,year),picked=dailyValues.selected;
 $("arcticRecordSummary").textContent=picked?
  fmt(picked.value)+" °C · "+dailyValues.rank+". wärmster Wert von "+dailyValues.count+" Jahren":
  "Für "+year+" liegt an diesem Kalendertag kein Wert vor ("+dailyValues.count+" Vergleichsjahre).";
 $("arcticRecordMeta").textContent="Historische Spanne "+(dailyValues.min?fmt(dailyValues.min.value)+" °C ("+dailyValues.min.year+")":"–")+
   " bis "+(dailyValues.max?fmt(dailyValues.max.value)+" °C ("+dailyValues.max.year+")":"–")+
   " · P10 "+fmt(dailyValues.p10)+" °C · P90 "+fmt(dailyValues.p90)+" °C";
 $("arcticRecordHot").innerHTML=tableRows(dailyValues.highest,year);
 $("arcticRecordCold").innerHTML=tableRows(dailyValues.lowest,year);
 const p=periods.find(x=>x.id===$("arcticPeriod").value)||periods[0],s=periodStats(doc,p,year);
 $("arcticPeriodSummary").textContent=s.selected?fmt(s.selected.value)+" °C · Platz "+s.rank+" (warm) von "+s.count+" vollständigen Perioden":
   "Für "+year+" ist diese Periode nicht vollständig verfügbar.";
 $("arcticPeriodMeta").textContent="Historischer Durchschnitt der vollständigen "+p.label+"-Perioden: "+fmt(s.mean)+" °C"+
   (s.selected?" · Abweichung: "+signed(s.selected.value-s.mean)+" K":"")+
   (p.id==="djf"?" · Winterjahr bezeichnet Januar/Februar":"");
 $("arcticPeriodHot").innerHTML=tableRows(s.warmest,year);
 $("arcticPeriodCold").innerHTML=tableRows(s.coldest,year);
}
function acceptData(incoming){
 if(!incoming||!incoming.years||!Array.isArray(incoming.days)||incoming.days.length!==366)return false;
 doc=incoming;
 const year=String(doc.latest_year);
 const latest=doc.years[year]||[];
 const last=latest.findLastIndex(v=>good(v));
 const current=$("arcticRecordDay").value;
 if(!current||current==="01-01")$("arcticRecordDay").value=last>=0?doc.days[last]:"11-01";
 render();
 return true;
}
async function init(){
 const ids=["arcticRecordDay","arcticPeriod","arcticYear"];
 if(!ids.every(id=>$(id)))return;
 const sel=$("arcticPeriod");
 periods.forEach(p=>{const o=document.createElement("option");o.value=p.id;o.textContent=p.label;sel.append(o);});
 sel.value="m11";
 for(const id of ids)$(id).addEventListener("change",render);
 // Existing main charts publish the exact data they already loaded successfully.
 window.addEventListener("arctic80:data-ready",event=>acceptData(event.detail));
 if(acceptData(window.Arctic80LoadedData))return;
 const paths=["data/arctic80_temperature.json",
   "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/data/arctic80_temperature.json"];
 for(const path of paths){
   try{
     const response=await fetch(path,{cache:"no-store"});
     if(!response.ok)throw Error("HTTP "+response.status);
     const incoming=await response.json();
     if(acceptData(incoming))return;
   }catch(error){console.warn("DMI stats loading "+path,error);}
 }
 if(!doc){
   $("arcticRecordSummary").textContent="Keine Statistikdaten geladen. Bitte Seite neu laden oder Datenstatus prüfen.";
   $("arcticPeriodSummary").textContent="Keine Statistikdaten geladen. Bitte Seite neu laden oder Datenstatus prüfen.";
 }
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
