/* Winter-by-winter rankings calculated from observed NASA MERRA-2 / GEOS FP
   10 hPa zonal mean U at 60°N. No mock statistics; reject partial seasons. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const ROOT="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-data/data/stratosphere/";
const years=Array.from({length:47},(_,i)=>1979+i);
const minDate=year=>year+"-11-01",maxDate=year=>(year+1)+"-03-31";
const label=year=>year+"/"+String((year+1)%100).padStart(2,"0");
const signed=(v,d=1)=>Number.isFinite(v)?(v>0?"+":"")+v.toFixed(d):"–";
const fixed=(v,d=1)=>Number.isFinite(v)?v.toFixed(d):"–";
const oneDay=86400000;
let archive=null,busy=false,sort="winter",lastStat=null;
function tell(s){$("stratoWinterStatsStatus").textContent=s;}
function expectedDays(year){
 const leap=year+1;
 return 151+((leap%4===0&&(leap%100!==0||leap%400===0))?1:0);
}
function decode(text,year){
 const values=new Map(),begin=minDate(year),end=maxDate(year);
 for(const row of text.split(/\r?\n/)){
  const parts=row.trim().split(/\s+/);
  if(parts.length<9||!/^\d{4}-\d\d-\d\d$/.test(parts[0]))continue;
  const date=parts[0],v=Number(parts[1]),lead=parts.length>=10?Number(parts[9]):0;
  if(date>=begin&&date<=end && lead===0 && Number.isFinite(v) && v>-160&&v<170)
   values.set(date,v);
 }
 return values;
}
async function fetchSeason(year){
 const r=await fetch(ROOT+"u60n_10_"+year+"_merra2.txt?archive="+Math.floor(Date.now()/3600000));
 if(!r.ok)throw Error("HTTP "+r.status);
 return decode(await r.text(),year);
}
function analyze(year,series){
 const entries=[...series.entries()].sort((a,b)=>a[0].localeCompare(b[0]));
 const expected=expectedDays(year),missing=expected-entries.length;
 // NASA series systematically lacks some historical 29-Feb dates. Accept
 // at most two missing days, but never infer values at missing dates.
 const complete=missing>=0&&missing<=2&&entries.length>=149&&
  entries[0]?.[0]===minDate(year)&&entries.at(-1)?.[0]===maxDate(year);
 let sum=0,min=Infinity,max=-Infinity,daysE=0,longestWest=0,streakWest=0,
    prevDay=null;
 for(const [date,v] of entries){
  sum+=v;min=Math.min(min,v);max=Math.max(max,v);
  if(v<0)daysE++;
  const ms=Date.parse(date+"T00:00:00Z");
  const consecutive=prevDay!==null&&ms-prevDay===oneDay;
  streakWest=v>0?(consecutive?streakWest+1:1):0;
  longestWest=Math.max(longestWest,streakWest);
  prevDay=ms;
 }
 return {year,series,complete,count:entries.length,expected,missing,
   mean:entries.length?sum/entries.length:null,
   min:entries.length?min:null,max:entries.length?max:null,
   easterlyDays:daysE,longestWest};
}
function rankFor(item,field,descending=true){
 const available=archive.filter(row=>row.complete).sort((a,b)=>
  (descending?b[field]-a[field]:a[field]-b[field])||b.year-a.year);
 if(!item?.complete)return null;
 const r=available.findIndex(x=>x.year===item.year);
 return r<0?null:(r+1)+". von "+available.length;
}
function percentile(item,field){
 if(!item?.complete)return null;
 const all=archive.filter(x=>x.complete).map(x=>x[field]);
 const below=all.filter(v=>v<item[field]).length;
 return Math.round(100*(below+.5*all.filter(v=>v===item[field]).length)/all.length);
}
function analogues(item){
 if(!item?.complete)return [];
 return archive.filter(x=>x.complete&&x.year!==item.year).map(row=>{
  const reference=new Map([...item.series].map(([d,v])=>[d.slice(5),v]));
  let total=0,n=0;
  for(const [day,value] of row.series){
   const current=reference.get(day.slice(5));
   if(Number.isFinite(current)){total+=Math.abs(value-current);n++;}
  }
  return {year:row.year,days:n,mae:n>=145?total/n:null};
 }).filter(row=>row.mae!==null).sort((a,b)=>a.mae-b.mae).slice(0,5);
}
function kpi(id,value,details){
 $(id).textContent=value;
 $(id+"Note").textContent=details;
}
function render(){
 if(!archive)return;
 const year=Number($("season").value),item=archive.find(x=>x.year===year);
 lastStat=item;
 const complete=archive.filter(x=>x.complete);
 if(!item?.complete){
  const message="Für "+label(year)+" liegen "+(item?.count??0)+" / "+(item?.expected??expectedDays(year))+
    " analysierte Wintertage vor. Rang und Analogvergleich nur für vollständige Winter.";
  for(const name of ["Mean","Min","Easterly","West"])kpi("stratoRank"+name,"–",message);
  $("stratoWinterAnalogues").textContent=message;
 }else{
  const baseline=complete.filter(x=>x.year>=1990&&x.year<=2019);
  const clim=baseline.length?baseline.reduce((n,x)=>n+x.mean,0)/baseline.length:null;
  kpi("stratoRankMean",fixed(item.mean)+" m/s",rankFor(item,"mean")+" · "+
    (Number.isFinite(clim)?"Abweichung vom Wintermittel 1990/91–2019/20: "+signed(item.mean-clim)+" m/s":"Referenz noch nicht verfügbar"));
  kpi("stratoRankMin",fixed(item.min)+" m/s",rankFor(item,"min",false)+" · niedrigstes Wintertagesmittel");
  kpi("stratoRankEasterly",String(item.easterlyDays)+" Tage",rankFor(item,"easterlyDays")+" · Wind < 0 m/s (Nov–März)");
  kpi("stratoRankWest",String(item.longestWest)+" Tage",rankFor(item,"longestWest")+" · zusammenhängend U > 0 m/s");
  const list=analogues(item);
  $("stratoWinterAnalogues").textContent="Ähnlichste vollständige Winter (mittlere absolute Tagesabweichung, Nov–März): "+
   (list.length?list.map(x=>label(x.year)+" ("+fixed(x.mae)+" m/s)").join(" · "):"keine");
 }
 const ordered=[...archive].sort((a,b)=>{
  if(sort==="winter")return b.year-a.year;
  if(sort==="min")return (a.complete?0:1)-(b.complete?0:1)||a.min-b.min;
  if(sort==="mean")return (a.complete?0:1)-(b.complete?0:1)||a.mean-b.mean;
  return (a.complete?0:1)-(b.complete?0:1)||b.easterlyDays-a.easterlyDays;
 });
 const tbody=$("stratoWinterRankingRows");tbody.replaceChildren();
 for(const row of ordered){
  const tr=document.createElement("tr");
  if(row.year===year)tr.className="selected";
  const values=[label(row.year),row.complete?fixed(row.mean):"–",
    row.complete?fixed(row.min):"–",row.complete?fixed(row.max):"–",
    row.complete?String(row.easterlyDays):"–",
    row.complete?String(row.longestWest):"–",
    row.complete?rankFor(row,"mean"):"Datenlücke ("+row.count+"/"+row.expected+")"];
  for(const value of values){const td=document.createElement("td");td.textContent=value;tr.append(td);}
  const td=tr.firstElementChild,button=document.createElement("button");
  button.type="button";button.className="rank-winter-link";button.textContent=td.textContent;
  td.replaceChildren(button);
  button.addEventListener("click",()=>{
    $("season").value=String(row.year);
    $("season").dispatchEvent(new Event("change",{bubbles:true}));
  });
  tbody.append(tr);
 }
 tell(complete.length+" vollständige Winter ausgewertet, "+(archive.length-complete.length)+
   " mit Datenlücken. NASA MERRA-2 / GEOS FP · 60° N, 10 hPa · Stand "+new Date().toLocaleDateString("de-DE")+
   ". Perzentil der Wintermittelwerte: "+(item?.complete?percentile(item,"mean")+"." : "nur für vollständige Winter") );
}
async function load(){
 if(busy)return;
 busy=true;$("stratoWinterStatsLoad").disabled=true;
 const rows=[];
 let failures=0;
 for(let i=0;i<years.length;i+=6){
  const slice=years.slice(i,i+6);
  tell("Lade unabhängige NASA-Winteranalysen: "+(i+1)+"–"+Math.min(years.length,i+6)+" / "+years.length+" …");
  const outcomes=await Promise.allSettled(slice.map(fetchSeason));
  for(let j=0;j<slice.length;j++){
   const y=slice[j],r=outcomes[j];
   if(r.status==="fulfilled")rows.push(analyze(y,r.value));
   else{rows.push(analyze(y,new Map()));failures++;}
  }
 }
 archive=rows;busy=false;$("stratoWinterStatsLoad").disabled=false;
 render();
 if(failures)tell($("stratoWinterStatsStatus").textContent+" · "+failures+" Abrufe fehlgeschlagen.");
}
function download(){
 if(!archive)return;
 const lines=[["Saison","Vollstaendig","Analysetage","Erwartet","Mittel_m_s","Minimum_m_s",
  "Maximum_m_s","Ostwindtage","Laengste_Westwindphase_Tage","Rang_Wintermittel"]];
 for(const r of archive)lines.push([label(r.year),r.complete?"ja":"nein",r.count,r.expected,
   r.complete?fixed(r.mean,3):"",r.complete?fixed(r.min,3):"",
   r.complete?fixed(r.max,3):"",r.complete?r.easterlyDays:"",r.complete?r.longestWest:"",
   r.complete?rankFor(r,"mean"):""]);
 const blob=new Blob(["\ufeff"+lines.map(a=>a.join(";")).join("\r\n")],{type:"text/csv;charset=utf-8"});
 const url=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=url;a.download="Stratosphaere_Historische_Winterrangliste_U60_10hPa.csv";
 a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
}
$("stratoWinterStatsLoad").addEventListener("click",load);
$("stratoWinterRankingCsv").addEventListener("click",download);
$("stratoWinterRankSort").addEventListener("change",e=>{sort=e.target.value;render();});
$("season").addEventListener("change",()=>{if(archive)render();});
})();
