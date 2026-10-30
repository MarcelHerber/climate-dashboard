const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const script=fs.readFileSync("stratosphere_reversal_diagnostics.js","utf8");
const html=fs.readFileSync("stratosphaere.html","utf8");
function isolated(){
 const nodes=new Map();
 const document={
  getElementById(id){
   if(!nodes.has(id))nodes.set(id,{id,value:id==="stratoDiagModel"?"gefs":id==="stratoDiagDays"?"15":"",
    disabled:false,textContent:"",children:[],
    addEventListener(){},replaceChildren(){this.children=[]},add(v){this.children.push(v)},
    appendChild(v){this.children.push(v)}});
   return nodes.get(id);
  },createElement(name){return {name,value:"",textContent:"",children:[],appendChild(v){this.children.push(v)}}}
 };
 const window={};
 const sandbox={window,document,Date,Math,Number,Object,JSON,Array,Set,Map,Promise,
  console:{info(){}},fetch:()=>new Promise(()=>{}),Blob:class {},URL,Chart:class {}};
 const instrumented=script.replace(/\}\)\(\);\s*$/,
  "window.__diagnostics={verify,analyze,analyzeMember,cycleOK,findRuns,draw,csv};})();");
 assert.notEqual(script,instrumented);
 vm.runInNewContext(instrumented,sandbox,{timeout:2000});
 return {f:window.__diagnostics,nodes};
}
function fixture(which="gefs",hour=0,days=which==="eps"?15:16){
 const cycle=new Date();
 cycle.setUTCDate(cycle.getUTCDate()-1);
 cycle.setUTCHours(hour,0,0,0);
 const count=which==="gefs"?31:51;
 const names=["c00",...Array.from({length:count-1},(_,i)=>"p"+String(i+1).padStart(2,"0"))];
 return {schema_version:1,provider:which==="gefs"?"NOAA GEFS":"ECMWF IFS ENS",
  level_hpa:10,latitude_deg:60,units:"m/s",
  cycle_utc:cycle.toISOString().slice(0,19)+"Z",member_count:count,forecast_horizon_days:days,
  valid_dates:Array.from({length:days+1},(_,i)=>new Date(+cycle+i*86400000).toISOString().slice(0,10)),
  members:Object.fromEntries(names.map(k=>[k,Array(days+1).fill(10)])),
  ...(which==="eps"?{perturbed_count:50,valid_hour_utc:hour,
   stream_ensemble:"enfo/ef",stream_control:"oper/fc",
   forecast_step_hours:Array.from({length:days+1},(_,i)=>24*i)}:{})};
}
test("diagnostic interface and CSV/PNG controls deployed",()=>{
 for(const id of ["stratoReversalDiagnostics","stratoDiagModel","stratoDiagCycle","stratoDiagOnset",
   "stratoDiagDuration","stratoDiagTableBody","stratoDiagStatus","stratoDiagCross",
   "stratoDiagBaseline","stratoDiagLong","stratoDiagMin","stratoDiagReturn","stratoDiagPng","stratoDiagCsv"]){
  assert.ok(html.includes('id="'+id+'"'),id);
 }
 assert.ok(html.includes("stratosphere_reversal_diagnostics.js"));
});
test("all 31 genuine GEFS and 51 ECMWF members, valid 00/06/12/18 and 00/12",()=>{
 const {f}=isolated();
 for(const hr of [0,6,12,18])assert.equal(f.verify(fixture("gefs",hr),"gefs").member_count,31);
 for(const hr of [0,12])assert.equal(f.verify(fixture("eps",hr),"eps").member_count,51);
 assert.throws(()=>f.verify(fixture("eps",6),"eps"));
 const bad=fixture("gefs");delete bad.members.p30;
 assert.throws(()=>f.verify(bad,"gefs"));
});
test("one crossing at daily sample: onset, two negative samples, recovery and min",()=>{
 const {f}=isolated(),d=fixture(),init=d.cycle_utc;
 const series=[12,8,-3,-7,2,4,-1,3,...Array(9).fill(10)];
 const r=f.analyzeMember(series,init,"p01");
 assert.equal(r.firstCrossing,2);
 assert.equal(r.anyCrossings,2);
 assert.equal(r.consecutiveNegative,2);
 assert.equal(r.recoveryIndex,4);
 assert.equal(r.rightCensored,false);
 assert.equal(r.episodeMinimum,-7);
 assert.equal(r.absoluteMinimum,-7);
 assert.equal(r.absoluteMinimumIndex,3);
 assert.ok(r.onsetTime.endsWith("00:00:00.000Z"));
});
test("negative at forecast initialization is separately left-censored",()=>{
 const {f}=isolated(),d=fixture();
 d.members.c00=[-2,-4,3,3,...Array(13).fill(5)];
 const results=f.analyze(f.verify(d,"gefs"));
 const row=results.members[0];
 assert.equal(row.startedNegative,true);
 assert.equal(row.firstCrossing,-1);
 assert.equal(row.consecutiveNegative,2);
 assert.equal(row.recoveryIndex,2);
 assert.equal(results.newCrossings,0);
 assert.equal(results.baseline,1);
 assert.equal(results.long3,0);
});
test("end-of-forecast negative episode is right-censored; no invented recovery",()=>{
 const {f}=isolated(),d=fixture();
 d.members.p01[d.members.p01.length-2]=-1;
 d.members.p01[d.members.p01.length-1]=-8;
 const a=f.analyze(f.verify(d,"gefs"));
 const m=a.members.find(x=>x.name==="p01");
 assert.equal(m.firstCrossing,15);
 assert.equal(m.consecutiveNegative,2);
 assert.equal(m.rightCensored,true);
 assert.equal(m.recoveryTime,null);
 assert.equal(a.unresolved,1);
 assert.equal(a.recovery,0);
});
test("first-onset histogram counts independent members once and never calls it Major SSW",()=>{
 const {f}=isolated(),d=fixture("eps",12);
 d.members.c00[1]=-1;
 d.members.c00[2]=6;
 d.members.c00[4]=-3; // same member second crossing: no second count
 d.members.p01[1]=-4;
 d.members.p02[3]=-8;
 const a=f.analyze(f.verify(d,"eps"));
 assert.equal(a.total,51);
 assert.equal(a.newCrossings,3);
 assert.equal(a.firstCrossingHistogram[1],2);
 assert.equal(a.firstCrossingHistogram[3],1);
 assert.equal(a.firstCrossingHistogram[4],0);
 assert.ok(script.includes("keine Major-SSW-Wahrscheinlichkeit"));
});
test("all non-negative members: no fabricated episodes or transitions",()=>{
 const {f}=isolated(),d=fixture();
 const a=f.analyze(f.verify(d,"gefs"));
 assert.equal(a.newCrossings,0);
 assert.equal(a.long3,0);
 assert.equal(a.baseline,0);
 assert.equal(a.unresolved,0);
 assert.ok(a.members.every(x=>x.consecutiveNegative===0&&x.onsetTime===null));
 assert.equal(a.firstCrossingHistogram.reduce((x,y)=>x+y,0),0);
});