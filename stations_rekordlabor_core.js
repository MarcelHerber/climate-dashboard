/* Phase 3 · pure calculations on original DWD CDC station observations.
   Can be imported by Node tests or used in the browser. No invented measurements. */
(function(root,factory){
  const api=factory();
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  root.RecordLaborCore=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
"use strict";
const MISSING=-32768,MS=86400000;
const finite=v=>typeof v==="number"&&Number.isFinite(v);
const leap=y=>y%4===0&&(y%100!==0||y%400===0);
const dayIndex=(y,md)=>{
 const [m,d]=md.split("-").map(Number);
 if(m<1||m>12||d<1||d>31)return -1;
 const t=Date.UTC(y,m-1,d),check=new Date(t);
 if(check.getUTCFullYear()!==y||check.getUTCMonth()!==m-1||check.getUTCDate()!==d)return -1;
 return Math.round((t-Date.UTC(y,0,1))/MS);
};
const mdAt=(y,idx)=>new Date(Date.UTC(y,0,idx+1)).toISOString().slice(5,10);
const readable=ymd=>ymd?ymd.slice(8,10)+"."+ymd.slice(5,7)+"."+ymd.slice(0,4):"—";
const climateSeason=(y,md)=>y+"-"+md;
function decodeRawTemperature(doc,buffer){
 if(doc?.format!=="dwd-tx-tn-tm-zlib16-v1"||!Array.isArray(doc.years))throw Error("Ungültiges DWD-Temperaturarchiv");
 const bytes=buffer instanceof ArrayBuffer?buffer:buffer.buffer.slice(buffer.byteOffset,buffer.byteOffset+buffer.byteLength);
 if(bytes.byteLength!==doc.years.length*366*3*2)throw Error("Temperaturarchiv abgeschnitten");
 const view=new DataView(bytes),map=new Map();
 doc.years.forEach((year,i)=>{
   const daily=new Array(leap(year)?366:365);
   daily.fill(null);
   for(let day=0;day<daily.length;day++){
     const off=(i*366*3+day*3)*2;
     daily[day]=[0,1,2].map(k=>{
       const n=view.getInt16(off+2*k,true);return n===MISSING?null:n/10;
     });
   }
   map.set(Number(year),daily);
 });
 return map;
}
async function decodeTemperature(doc){
 if(!doc||typeof doc.data!=="string")throw Error("Temperaturarchiv ohne Rohwerte");
 if(typeof DecompressionStream==="undefined")throw Error("Dieser Browser unterstützt keine zlib-Dekompression");
 const raw=Uint8Array.from(atob(doc.data),c=>c.charCodeAt(0));
 const stream=new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate"));
 const bytes=await new Response(stream).arrayBuffer();
 return decodeRawTemperature(doc,bytes);
}
function calendarTemperature(yearMap,md,metric){
 if(![0,1,2].includes(metric))throw Error("Temperaturmetrik ungültig");
 const rows=[];
 for(const [year,days] of yearMap){
   const i=dayIndex(year,md);if(i<0)continue;
   const value=days?.[i]?.[metric];
   if(finite(value))rows.push({date:climateSeason(year,md),year,value,quality:"historisch"});
 }
 return rows;
}
function snowCalendar(archive,md){
 if(!archive?.month_days||!Array.isArray(archive.years))return [];
 const idx=archive.month_days.indexOf(md);if(idx<0)return [];
 return archive.years.flatMap(yr=>{
   const v=yr.values?.[idx],year=Number(yr.year)-(md>="11-01"?1:0);
   if(!yr.accepted||!finite(v))return [];
   return [{date:climateSeason(year,md),year,value:v,quality:"qualitätsgeprüft"}];
 });
}
function sortedRecords(rows,direction,n=10){
 const valid=rows.filter(x=>finite(x.value));
 const ordered=valid.slice().sort((a,b)=>(direction==="min"?a.value-b.value:b.value-a.value)||a.date.localeCompare(b.date));
 return {records:ordered.slice(0,n),coverage:valid.length,
   first:valid.length?valid.reduce((a,b)=>a.year<b.year?a:b).year:null,
   last:valid.length?valid.reduce((a,b)=>a.year>b.year?a:b).year:null};
}
const mdInRange=(md,a,b)=>md>=a&&md<=b;
function tempSeason(yearMap,event){
 const specs={
  frostAutumn:{field:1,cmp:v=>v<0,start:"09-01",end:"12-31",pick:"first",rule:"Erster Frost im Herbst · Tmin < 0 °C"},
  frostSpring:{field:1,cmp:v=>v<0,start:"01-01",end:"06-30",pick:"last",rule:"Letzter Frost im Frühjahr · Tmin < 0 °C"},
  iceFirst:{field:0,cmp:v=>v<0,start:"09-01",end:"12-31",pick:"first",rule:"Erster Eistag im Herbst · Tmax < 0 °C"},
  iceLast:{field:0,cmp:v=>v<0,start:"01-01",end:"06-30",pick:"last",rule:"Letzter Eistag · Tmax < 0 °C"},
  summerFirst:{field:0,cmp:v=>v>=25,start:"01-01",end:"12-31",pick:"first",rule:"Frühester Sommertag · Tmax ≥ 25 °C"},
  summerLast:{field:0,cmp:v=>v>=25,start:"01-01",end:"12-31",pick:"last",rule:"Spätester Sommertag · Tmax ≥ 25 °C"},
  hotFirst:{field:0,cmp:v=>v>=30,start:"01-01",end:"12-31",pick:"first",rule:"Frühester heißer Tag · Tmax ≥ 30 °C"},
  hotLast:{field:0,cmp:v=>v>=30,start:"01-01",end:"12-31",pick:"last",rule:"Spätester heißer Tag · Tmax ≥ 30 °C"}
 };
 const s=specs[event];if(!s)throw Error("Jahreszeitenereignis unbekannt");
 const rows=[], excluded=[];
 for(const [year,arr] of yearMap){
   const from=dayIndex(year,s.start),to=dayIndex(year,s.end);
   const subset=arr.slice(from,to+1);
   const valid=subset.filter(row=>finite(row?.[s.field])).length;
   if(!subset.length||valid/subset.length<.95){excluded.push(year);continue;}
   const observed=[];
   for(let i=0;i<subset.length;i++){
     const v=subset[i]?.[s.field];
     if(finite(v)&&s.cmp(v))observed.push({idx:from+i,value:v});
   }
   if(!observed.length)continue;
   const row=s.pick==="first"?observed[0]:observed.at(-1);
   const md=mdAt(year,row.idx);
   rows.push({year,date:climateSeason(year,md),md,dayOfYear:dayIndex(2000,md)+1,
     value:row.value,coverage:valid/subset.length});
 }
 rows.sort((a,b)=>s.pick==="first"?a.dayOfYear-b.dayOfYear||a.year-b.year:
   b.dayOfYear-a.dayOfYear||a.year-b.year);
 return {label:s.rule,event,records:rows,excluded,qualifiedYears:rows.length,
  threshold:"95 % der erwarteten Messtage im Suchfenster"};
}
function snowSeason(archive,event){
 const defs={
  snowFirst:{first:"11-01",last:"03-31",pick:"first",label:"Erste messbare Schneedecke (≥ 1 cm) ab 1. November"},
  snowLast:{first:"02-01",last:"10-31",pick:"last",label:"Letzte messbare Schneedecke (≥ 1 cm) bis 31. Oktober"}
 };
 const s=defs[event];if(!s)throw Error("Schneeereignis unbekannt");
 const from=archive.month_days.indexOf(s.first),to=archive.month_days.indexOf(s.last);
 const records=[],excluded=[];
 for(const row of archive.years||[]){
   if(!row.accepted){excluded.push(row.year);continue;}
   const candidates=[];
   for(let i=from;i<=to;i++){
     const v=row.values?.[i];if(finite(v)&&v>=1)candidates.push(i);
   }
   if(!candidates.length)continue;
   const ix=s.pick==="first"?candidates[0]:candidates.at(-1);
   const md=archive.month_days[ix],year=Number(row.year)-(md>="11-01"?1:0);
   records.push({year:row.year,date:climateSeason(year,md),md,
     dayOfPeriod:ix+1,value:row.values[ix],
     atBoundary:ix===from,coverage:row.coverage});
 }
 records.sort((a,b)=>s.pick==="first"?a.dayOfPeriod-b.dayOfPeriod||a.year-b.year:
   b.dayOfPeriod-a.dayOfPeriod||a.year-b.year);
 return {label:s.label,event,records,excluded,
  threshold:"Nur als vollständig gekennzeichnete hydrologische Jahre"};
}
function longestRun(yearMap,field,predicate){
 const rows=[];
 for(const [year,days] of yearMap){
   const valid=days.filter(d=>finite(d?.[field])).length;
   if(valid/days.length<.95)continue;
   let start=null,best=null;
   function end(i){
     if(start===null)return;
     const length=i-start;
     if(!best||length>best.days)best={days:length,start:climateSeason(year,mdAt(year,start)),
       end:climateSeason(year,mdAt(year,i-1)),year};
     start=null;
   }
   days.forEach((day,i)=>{if(finite(day?.[field])&&predicate(day[field])){if(start===null)start=i;}else end(i);});
   end(days.length);
   if(best)rows.push(best);
 }
 return rows.sort((a,b)=>b.days-a.days||a.year-b.year);
}
function snowLongest(archive){
 const rows=[];
 for(const y of archive.years||[]){
   if(!y.accepted)continue;
   let start=null,best=null;
   function end(i){
     if(start===null)return;
     const length=i-start;
     if(!best||length>best.days){
       const from=archive.month_days[start],to=archive.month_days[i-1];
       best={year:y.year,days:length,
         start:climateSeason(y.year-(from>="11-01"?1:0),from),
         end:climateSeason(y.year-(to>="11-01"?1:0),to)};
     }
     start=null;
   }
   (y.values||[]).forEach((v,i)=>{if(finite(v)&&v>=1){if(start===null)start=i;}else end(i);});
   end(y.values?.length||0);
   if(best)rows.push(best);
 }
 return rows.sort((a,b)=>b.days-a.days||a.year-b.year);
}
function stationWindDifference(before,after){
 if(!finite(before?.speed)||!finite(after?.speed)||before.speed<3||after.speed<3 ||
    !finite(before.direction)||!finite(after.direction))return null;
 return Math.abs(((after.direction-before.direction+540)%360)-180);
}
return Object.freeze({leap,dayIndex,mdAt,readable,decodeRawTemperature,decodeTemperature,
 calendarTemperature,snowCalendar,sortedRecords,tempSeason,snowSeason,longestRun,snowLongest,stationWindDifference});
});
