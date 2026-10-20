/* UTC-exact provider/chart selection for synoptic original maps. */
(function(root){
 "use strict";
 const ORDER=["dwd","aemet","knmi","chmi","dhmz","imo","noaa_opc","noaa_full","noaa_west","noaa_24","noaa_48","noaa_96","noaa_pace","noaa_pacw","noaa_pacfull","noaa_pac24","noaa_pac48","noaa_pac96"];
 // These are established products with fronts drawn on the published original maps.
 // Never infer fronts from arbitrary provider IDs or from a model pressure map.
 const FRONT_PRODUCTS=new Set(["dwd","aemet","knmi","chmi","dhmz",
    "noaa_opc","noaa_full","noaa_west","noaa_24","noaa_48","noaa_96","noaa_pace","noaa_pacw","noaa_pacfull","noaa_pac24","noaa_pac48","noaa_pac96"]);
 const label={
   analysis_fronts:"Bodenanalyse · mit Fronten",
   forecast_fronts:"Frontenprognose",
   isobars_only:"Modell-Isobaren · ohne Fronten",
   other:"Originalkarte · Kartentyp ungeklärt"
 };
 const scoreSource=id=>{const i=ORDER.indexOf(id);return i<0?ORDER.length:i;};
 const forecast=r=>r?.kind==="Prognose"||Number(r?.forecast_hours)>0;
 function classify(record){
   if(!record||!record.source_id)return "other";
   if(record.map_type==="isobars_model_forecast_no_fronts"||record.source_id==="imo")
     return "isobars_only";
   if(!FRONT_PRODUCTS.has(record.source_id))return "other";
   if(forecast(record))return "forecast_fronts";
   if(record.kind==="Analyse"||record.kind==="0-h-Bodenkarte")return "analysis_fronts";
   return "other";
 }
 function visible(r,kind){
   const type=classify(r);
   if(!kind||kind==="all")return true;
   // Backward-compatible aliases used by earlier tests and links.
   if(kind==="analysis")return !forecast(r);
   if(kind==="forecast")return forecast(r);
   return type===kind;
 }
 function chooseAt(charts,time,kind,options){
  if(!time||!Array.isArray(charts))return {time:time||"",ids:[],count:0,publishers:0};
  const unique=options?.uniquePublishers===true;
  const bySource=new Map();
  for(const r of charts){
   if(r.valid_utc!==time||!visible(r,kind)||!r.source_id)continue;
   if(!bySource.has(r.source_id))bySource.set(r.source_id,r);
  }
  const pool=[...bySource.values()].sort((a,b)=>scoreSource(a.source_id)-scoreSource(b.source_id)||a.source_id.localeCompare(b.source_id));
  const chosen=[],seen=new Set();
  for(const r of pool){
   const publisher=r.publisher_id||r.source_id;
   if(chosen.length>=4)break;
   if(!seen.has(publisher)){chosen.push(r);seen.add(publisher);}
  }
  if(!unique){
   for(const r of pool){if(chosen.length>=4)break;if(!chosen.includes(r))chosen.push(r);}
  }
  return {time,ids:chosen.map(r=>r.source_id),count:chosen.length,
   publishers:new Set(chosen.map(r=>r.publisher_id||r.source_id)).size};
 }
 function best(charts,times,kind,now,options){
  let top=null,topScore=-Infinity;
  for(const time of times||[]){
   const ms=Date.parse(time);
   if(!Number.isFinite(ms))continue;
   const candidate=chooseAt(charts,time,kind,options);
   if(!candidate.count)continue;
   const hours=Math.abs(ms-(Number.isFinite(now)?now:Date.now()))/3600000;
   // Only compare actual maps sharing precisely the same published valid_utc.
   // First maximize coverage, then independent publishers, then near-now.
   const score=candidate.count*1000+candidate.publishers*130-Math.min(200,hours)*3;
   if(score>topScore){top=candidate;topScore=score;}
  }
  return top;
 }
 const api={chooseAt,best,classify,visible,label};
 if(typeof module!=="undefined"&&module.exports)module.exports=api;
 root.SynopticPanelLogic=api;
})(typeof globalThis!=="undefined"?globalThis:this);
