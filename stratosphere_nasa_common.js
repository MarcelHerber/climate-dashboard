/* Genuine NASA Ozone Watch daily U60N analyses and 1991–2020 climatology.
   Common strict, cached source for joined history and five-level analysis. */
(()=>{
'use strict';
const ROOT='https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-data/data/stratosphere/';
const LEVELS=[10,30,50,70,100];
const cache=new Map();
function dateISO(iso,offset) {
  const d=new Date(iso+'T00:00:00Z');
  if(Number.isNaN(d.getTime()))throw Error('Invalid ISO date');
  d.setUTCDate(d.getUTCDate()+offset);
  return d.toISOString().slice(0,10);
}
function season(date){const y=Number(date.slice(0,4)),month=Number(date.slice(5,7));return month>=7?y:y-1;}
function valid(value){return Number.isFinite(value)&&value>-160&&value<170;}
function parse(text){
  const found=new Map();
  for(const raw of text.split(/\r?\n/)){
    const parts=raw.trim().split(/\s+/);
    if(parts.length<9||!/^\d{4}-\d\d-\d\d$/.test(parts[0]))continue;
    const value=Number(parts[1]),lead=parts.length>=10?Number(parts[9]):0;
    if(lead!==0||!valid(value))continue;
    found.set(parts[0],value);
  }
  return found;
}
async function json(url) {
  const response=await fetch(url+'?v='+Math.floor(Date.now()/3600000),{cache:'no-store'});
  if(!response.ok)throw Error('NASA '+response.status+' für '+url.split('/').at(-1));
  return response.json();
}
async function text(url) {
  const response=await fetch(url+'?v='+Math.floor(Date.now()/3600000),{cache:'no-store'});
  if(!response.ok)throw Error('NASA '+response.status+' für '+url.split('/').at(-1));
  return response.text();
}
function request(id,work){
  if(!cache.has(id))cache.set(id,Promise.resolve().then(work).catch(err=>{cache.delete(id);throw err;}));
  return cache.get(id);
}
const observation=(level,year)=>request('obs-'+level+'-'+year,async()=>parse(
  await text(ROOT+'u60n_'+level+'_'+year+'_merra2.txt')));
const climatology=level=>request('ref-'+level,async()=>{
  const result=await json(ROOT+'climatology_'+level+'hpa.json');
  if(result.level_hpa!==level||!result.daily)throw Error('NASA Referenz für '+level+' hPa ungültig');
  return result;
});
async function load(levels,from,to){
  if(!Array.isArray(levels)||!levels.every(l=>LEVELS.includes(l)))throw Error('Ungültige Druckniveaus');
  const yrs=new Set();
  for(let d=from;d<=to;d=dateISO(d,1))yrs.add(season(d));
  const output=new Map();
  await Promise.all(levels.map(async level=>{
    const years=[...yrs];
    const [references,...archives]=await Promise.all([
      climatology(level),...years.map(y=>observation(level,y).catch(()=>new Map()))
    ]);
    const observations=new Map(archives.flatMap(m=>[...m.entries()]));
    output.set(level,{observations,reference:references.daily,
      referenceLabel:references.reference||'Winter 1990/91–2019/20'});
  }));
  return output;
}
const climate=(data,date,key)=> {
  const row=data?.reference?.[date.slice(5)];
  const value=row?.[key];
  return typeof value==='number'&&Number.isFinite(value)?value:null;
};
window.stratoNASAData={load,dateISO,season,parse,climate,LEVELS};
})();
