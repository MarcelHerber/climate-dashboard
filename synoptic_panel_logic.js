/* Pure, independently testable UTC-exact synoptic four-panel selection. */
(function(root){
 "use strict";
 const ORDER=["dwd","aemet","knmi","chmi","dhmz","noaa_opc","noaa_full","noaa_west","noaa_24","noaa_48","noaa_96"];
 const scoreSource=id=>{const i=ORDER.indexOf(id);return i<0?ORDER.length:i;};
 const forecast=r=>r.kind==="Prognose"||Number(r.forecast_hours)>0;
 const visible=(r,kind)=>kind==="forecast"?forecast(r):kind==="analysis"?!forecast(r):true;
 function chooseAt(charts,time,kind){
  if(!time||!Array.isArray(charts))return {time:time||"",ids:[],count:0,publishers:0};
  const bySource=new Map();
  for(const r of charts){
   if(r.valid_utc!==time||!visible(r,kind||"all")||!r.source_id)continue;
   if(!bySource.has(r.source_id))bySource.set(r.source_id,r);
  }
  const pool=[...bySource.values()].sort((a,b)=>scoreSource(a.source_id)-scoreSource(b.source_id)||a.source_id.localeCompare(b.source_id));
  const chosen=[],seen=new Set();
  // Prefer unique national weather services; several NOAA regions are the SAME publisher.
  for(const r of pool){
   const publisher=r.publisher_id||r.source_id;
   if(chosen.length>=4)break;
   if(!seen.has(publisher)){chosen.push(r);seen.add(publisher);}
  }
  for(const r of pool){if(chosen.length>=4)break;if(!chosen.includes(r))chosen.push(r);}
  return {time,ids:chosen.map(r=>r.source_id),count:chosen.length,
   publishers:new Set(chosen.map(r=>r.publisher_id||r.source_id)).size};
 }
 function best(charts,times,kind,now){
  let bestChoice=null,bestScore=-Infinity;
  for(const time of times||[]){
   const ms=Date.parse(time);
   if(!Number.isFinite(ms))continue;
   const candidate=chooseAt(charts,time,kind);
   if(!candidate.count)continue;
   const hours=Math.abs(ms-(Number.isFinite(now)?now:Date.now()))/3600000;
   // More real images is the primary objective; then independent publishers.
   // Proximity decides ties, not fabricated or shifted validity.
   const score=candidate.count*1000+candidate.publishers*130-Math.min(200,hours)*3;
   if(score>bestScore){bestChoice=candidate;bestScore=score;}
  }
  return bestChoice;
 }
 const api={chooseAt,best};
 if(typeof module!=="undefined"&&module.exports)module.exports=api;
 root.SynopticPanelLogic=api;
})(typeof globalThis!=="undefined"?globalThis:this);
