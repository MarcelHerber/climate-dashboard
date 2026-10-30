const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const script=fs.readFileSync("stratosphere_run_trends.js","utf8");
const html=fs.readFileSync("stratosphaere.html","utf8");
function context(){
 const els=new Map(),listeners=new Map();
 const document={
  getElementById(id){
   if(!els.has(id)){
    const e={id,value:"",disabled:false,textContent:"",children:[],checked:false,
     addEventListener(name,cb){listeners.set(id+":"+name,cb);},
     replaceChildren(){this.children=[];this.value="";},
     add(node){this.children.push(node);},
     appendChild(node){this.children.push(node);}};
    els.set(id,e);
   }
   return els.get(id);
  },
  createElement(name){return {name,textContent:"",value:"",children:[],appendChild(node){this.children.push(node);}};},
 };
 const ids=["stratoTrendModel","stratoTrendHour","stratoTrendCount","stratoTrendHorizon","stratoTrendMode"];
 const defaults=["gefs","00","5","15","probability"];
 ids.forEach((id,i)=>{document.getElementById(id).value=defaults[i];});
 const window={};
 const sandbox={window,document,Date,Math,Number,Object,JSON,Array,Set,Map,
    Promise,console,fetch:()=>new Promise(()=>{}),
    URL,Blob:class {},Chart:class {}};
 const patched=script.replace(/\}\)\(\);\s*$/,
   "window.__trendsTest={verify,extract,parseIndex,comparisons,setRuns:r=>runs=r,setModel:m=>document.getElementById('stratoTrendModel').value=m};})();");
 assert.notEqual(patched,script,"Must instrument exactly one IIFE");
 vm.runInNewContext(patched,sandbox,{timeout:2500});
 return {methods:window.__trendsTest,els};
}
function fixture(model,hour=0,days=model==="eps"?15:16,ageDays=1){
 const cycle=new Date();
 cycle.setUTCDate(cycle.getUTCDate()-ageDays);
 cycle.setUTCHours(hour,0,0,0);
 const count=model==="eps"?51:31,dates=Array.from({length:days+1},(_,i)=>
   new Date(+cycle+i*86400000).toISOString().slice(0,10));
 const members=Object.fromEntries(["c00",...Array.from({length:count-1},(_,i)=>
   "p"+String(i+1).padStart(2,"0"))].map((name)=>[name,Array(days+1).fill(10)]));
 return {schema_version:1,provider:model==="eps"?"ECMWF IFS ENS":"NOAA GEFS",
   level_hpa:10,latitude_deg:60,units:"m/s",member_count:count,
   forecast_horizon_days:days,
   cycle_utc:cycle.toISOString().slice(0,19)+"Z",
   valid_dates:dates,members,
   ...(model==="eps"?{perturbed_count:50,valid_hour_utc:hour,
     stream_ensemble:"enfo/ef",stream_control:"oper/fc",
     forecast_step_hours:Array.from({length:days+1},(_,i)=>i*24)}:{})};
}
test("run comparison UI and dedicated asset exist",()=>{
 for(const id of ["stratoRunTrends","stratoTrendModel","stratoTrendHour",
  "stratoTrendCount","stratoTrendHorizon","stratoTrendMode","stratoTrendValid",
  "stratoTrendCanvas","stratoTrendMeta","stratoTrendTableBody",
  "stratoTrendPng","stratoTrendCsv","stratoTrendReload"]){
  assert.ok(html.includes('id="'+id+'"'),id);
 }
 assert.match(html,/stratosphere_run_trends\.js/);
 assert.match(script,/Promise\.allSettled/);
});
test("GEFS archive accepts 31 original members on 00/06/12/18UTC only",()=>{
 const {methods:f}=context();
 for(const hour of [0,6,12,18]){
  const data=fixture("gefs",hour);
  assert.equal(f.verify(data,"gefs"),data);
 }
 const data=fixture("gefs",0);
 assert.throws(()=>f.verify({...data,member_count:30},"gefs"));
 assert.throws(()=>f.verify({...data,members:{c00:data.members.c00}},"gefs"));
 assert.throws(()=>f.verify({...data,forecast_horizon_days:35},"gefs"));
 assert.throws(()=>f.verify({...data,provider:"ECMWF IFS ENS"},"gefs"));
 const future=fixture("gefs",0,16,-2);
 assert.throws(()=>f.verify(future,"gefs"),/Modelllauf|Datenformat/);
});
test("ECMWF EPS accepts exactly 50 perturbed plus control and the 12UTC horizon",()=>{
 const {methods:f}=context();
 for(const hour of [0,12]){
  const d=fixture("eps",hour);
  assert.equal(f.verify(d,"eps"),d);
 }
 const data=fixture("eps",12);
 assert.throws(()=>f.verify({...data,valid_hour_utc:0},"eps"));
 assert.throws(()=>f.verify({...data,forecast_step_hours:[0,12]},"eps"));
 assert.throws(()=>f.verify({...data,stream_ensemble:"oper/fc"},"eps"));
 assert.throws(()=>f.verify(fixture("eps",6),"eps"));
});
test("wind reversal probability is ensemble fraction including control, not a synthetic forecast",()=>{
 const {methods:f}=context(),d=fixture("eps",12);
 for(let i=1;i<=7;i++)d.members["p"+String(i).padStart(2,"0")][2]=-2;
 d.members.c00[2]=-1;
 const rows=f.extract(f.verify(d,"eps"));
 assert.equal(rows[2].count,8);
 assert.equal(rows[2].total,51);
 assert.ok(Math.abs(rows[2].prob-800/51)<1e-9);
 assert.equal(rows[0].prob,0);
 d.members.p01[1]=NaN;
 assert.throws(()=>f.verify(d,"eps"));
});
test("compare only exact UTC validity and compute percentage-point changes",()=>{
 const {methods:f,els}=context();
 const newer=fixture("gefs",0,16,1);
 const older=fixture("gefs",0,16,2);
 newer.members.c00[1]=-1;newer.members.p01[1]=-1;
 older.members.c00[2]=-1;
 const a={cycle:newer.cycle_utc,rows:f.extract(f.verify(newer,"gefs"))};
 const b={cycle:older.cycle_utc,rows:f.extract(f.verify(older,"gefs"))};
 f.setRuns([a,b]);els.get("stratoTrendHorizon").value="7";
 const row=f.comparisons().find(x=>x.key===a.rows[1].key);
 assert.ok(row);
 assert.equal(row.vals[0].count,2);
 assert.equal(row.vals[1].count,1);
 assert.ok(Math.abs(row.delta-100/31)<1e-9);
 const different=fixture("gefs",6,16,2);
 f.setRuns([a,{cycle:different.cycle_utc,rows:f.extract(different)}]);
 const mismatch=f.comparisons().find(x=>x.key===a.rows[1].key);
 assert.equal(mismatch.previous,null);
 assert.equal(mismatch.delta,null);
});
test("one historical run and invalid archive index never imply an invented trend",()=>{
 const {methods:f,els}=context();
 const data=fixture("gefs"),run={cycle:data.cycle_utc,rows:f.extract(data)};
 f.setRuns([run]);els.get("stratoTrendHorizon").value="15";
 assert.ok(f.comparisons().every(row=>row.delta===null));
 const index={schema_version:1,provider:"NOAA GEFS",runs:[
  {cycle_utc:data.cycle_utc,path:"runs/20261030_000000.json",forecast_horizon_days:16},
  {cycle_utc:data.cycle_utc,path:"runs/20261030_000000.json",forecast_horizon_days:16},
  {cycle_utc:data.cycle_utc,path:"../secret.json",forecast_horizon_days:16},
  {cycle_utc:"not-a-time",path:"runs/20261030_000000.json",forecast_horizon_days:16}
 ]};
 const parsed=f.parseIndex(index,"gefs");
 assert.equal(parsed.length,1);
 assert.equal(f.parseIndex({...index,provider:"ECMWF IFS ENS"},"gefs").length,0);
});