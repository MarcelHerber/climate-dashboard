const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const source=fs.readFileSync("stratosphere_ecmwf_ens.js","utf8");
const html=fs.readFileSync("stratosphaere.html","utf8");

function isolated(){
 const handlers=new Map(),els=new Map();
 const document={getElementById(id){
   if(!els.has(id))els.set(id,{id,textContent:"",disabled:false,hidden:false,
     value:"all",checked:true,setAttribute(){},addEventListener(name,fn){handlers.set(id+":"+name,fn);}});
   return els.get(id);
 }};
 const window={addEventListener(name,fn){handlers.set(name,fn);}};
 const sandbox={window,document,Date,Math,Number,Object,JSON,Array,Set,Map,
    Promise,console,fetch:()=>new Promise(()=>{}),URL,Blob:class {},Chart:class {}};
 const instrumented=source.replace(/\}\)\(\);\s*$/,
    "window.__epsTest={validData,compute,goodGefs};})();");
 assert.notEqual(instrumented,source);
 vm.runInNewContext(instrumented,sandbox,{timeout:2000});
 return {f:window.__epsTest,window,handlers,els};
}
function fixture(){
 const cycle=new Date();cycle.setUTCHours(0,0,0,0);
 const dates=Array.from({length:16},(_,i)=>new Date(+cycle+i*86400000).toISOString().slice(0,10));
 const members=Object.fromEntries(["c00",...Array.from({length:50},(_,i)=>
   "p"+String(i+1).padStart(2,"0"))].map((key,i)=>[
    key,Array.from({length:16},(_,j)=>i<5&&j>1?-4:15)]));
 return {schema_version:1,provider:"ECMWF IFS ENS",latitude_deg:60,level_hpa:10,
    units:"m/s",stream_ensemble:"enfo/ef",stream_control:"oper/fc",
    member_count:51,perturbed_count:50,valid_hour_utc:0,cycle_utc:cycle.toISOString().slice(0,10)+"T00:00:00Z",
    valid_dates:dates,forecast_step_hours:Array.from({length:16},(_,i)=>i*24),members};
}
test("three genuine distinct model tabs and same-time comparison",()=>{
 for(const id of ["stratoGefsTab","stratoEpsTab","stratoEcmwfTab",
  "stratoEpsView","stratoEpsCanvas","stratoCompareCanvas",
  "stratoCompareGefs","stratoCompareEps","stratoCompareCsv"]){
  assert.ok(html.includes('id="'+id+'"'),id);
 }
 assert.ok(html.indexOf('id="stratoGefsTab"')<html.indexOf('id="stratoEpsTab"'));
 assert.ok(html.indexOf('id="stratoEpsTab"')<html.indexOf('id="stratoEcmwfTab"'));
});
test("EPS accepts exactly 50 perturbations and 1 control, not IFS run history",()=>{
 const {f}=isolated(),data=fixture();
 assert.equal(f.validData(data),data);
 assert.throws(()=>f.validData({...data,members:{c00:data.members.c00}}));
 assert.throws(()=>f.validData({...data,provider:"ECMWF IFS"}));
 assert.throws(()=>f.validData({...data,member_count:50}));
 assert.throws(()=>f.validData({...data,forecast_step_hours:[0,6]}));
});
test("daily subzero fraction uses all 51 members and counts new crossings",()=>{
 const {f}=isolated(),data=fixture();
 const result=f.compute(data);
 assert.equal(result.total,51);
 assert.equal(result.crossed,5);
 assert.equal(result.rows[1].count,0);
 assert.equal(result.rows[2].count,5);
 assert.ok(Math.abs(result.rows[2].p-500/51)<1e-9);
 assert.equal(result.rows[2].control,-4);
});
