(function(root){
"use strict";
const periods={day:"Kalendertag",decade:"Monatsdekade",month:"Monat",season:"Jahreszeit",year:"Jahr"};
function bucket(d,p){
 const m=+d.slice(5,7), day=+d.slice(8,10);
 if(p==="day")return d.slice(5);
 if(p==="decade")return m+"-"+Math.min(3,Math.ceil(day/10));
 if(p==="month")return m;
 if(p==="season")return Math.floor(m%12/3);
 return 0;
}
function compare(series,target,p,direction){
 const current=series.find(x=>x.date===target);
 if(!current||!Number.isFinite(current.value))return null;
 const previous=series.filter(x=>x.date<target&&Number.isFinite(x.value)&&bucket(x.date,p)===bucket(target,p));
 const equalOrMore=previous.filter(x=>direction==="low"?x.value<=current.value:x.value>=current.value);
 const strict=equalOrMore.filter(x=>x.value!==current.value);
 const last=equalOrMore.reduce((a,b)=>!a||b.date>a.date?b:a,null);
 const years=new Set(previous.map(x=>x.date.slice(0,4)));
 return {value:current.value,rank:strict.length+1,ties:equalOrMore.length-strict.length,last,days:previous.length,years:years.size};
}
function coverage(series,target,p){
 const dates=new Set(series.filter(x=>Number.isFinite(x.value)).map(x=>x.date));
 let first=target;
 const dt=new Date(target+"T00:00:00Z");
 const min=series.reduce((a,b)=>b.date<a?b.date:a,target);
 while(dt.toISOString().slice(0,10)>min){
   dt.setUTCDate(dt.getUTCDate()-1);
   const d=dt.toISOString().slice(0,10);
   if(bucket(d,p)!==bucket(target,p))continue;
   if(!dates.has(d))break;
   first=d;
 }
 return first;
}
const api={periods,bucket,compare,coverage};
if(typeof module!=="undefined")module.exports=api;else root.BundeslaenderRecords=api;
})(typeof globalThis!=="undefined"?globalThis:this);
