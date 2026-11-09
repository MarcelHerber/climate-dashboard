#!/usr/bin/env node
const test=require("node:test"),assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const js=fs.readFileSync(path.join(__dirname,"../groenland_stationen.js"),"utf8");
const fakeDoc={readyState:"loading",addEventListener:()=>{},getElementById:()=>null};
const ctx={window:{},document:fakeDoc,console,Date,Number,String,Map,Set,Array,Intl,URLSearchParams};
vm.createContext(ctx);
vm.runInContext(js,ctx);
const m=ctx.window.GreenlandDmiMath;
test("DMI Greenland module exposes trusted, offline-testable transformations",()=>{
 assert.ok(m);
 assert.equal(m.PARAMS.max_wind_speed_3sec.unit,"m/s");
 assert.equal(m.PARAMS.mean_temp.unit,"°C");
});
test("Invalid values, duplicates and wrong parameters are excluded; precipitation traces retained",()=>{
 const row=(date,val,created,opts={})=>({
   properties:{parameterId:"acc_precip",timeResolution:"day",from:date+"T06:00:00Z",
      value:val,created,qcStatus:"manual",...opts}
 });
 const rows=m.normalize([
   row("2026-11-01",2,"2026-11-02"),
   row("2026-11-01",5,"2026-11-03"),
   row("2026-11-02",-0.1,"2026-11-03"),
   row("2026-11-03",990,"2026-11-03",{validity:false}),
   row("2026-11-04",4,"2026-11-04",{parameterId:"mean_temp"}),
   row("2026-11-05",-8,"2026-11-05"),
 ],"acc_precip","day");
 assert.deepEqual(Array.from(rows,x=>x.date),["2026-11-01","2026-11-02"]);
 assert.equal(rows[0].value,5);
 assert.equal(rows[1].value,0);assert.equal(rows[1].raw,-.1);
 assert.equal(rows[1].trace,true);
});
test("Yearly values have one point per year, no fabricated intervening years",()=>{
 const rows=m.normalize([
  {properties:{parameterId:"min_temp",timeResolution:"year",from:"1980-01-01T06:00:00Z",value:-33,created:"1981"}},
  {properties:{parameterId:"min_temp",timeResolution:"year",from:"1985-01-01T06:00:00Z",value:-38,created:"1986"}},
 ],"min_temp","year");
 assert.deepEqual(Array.from(rows,x=>x.date),["1980","1985"]);
});
test("Station list is Greenland-only, within geographical extent and deduplicated",()=>{
 const feat=(id,country,lon,lat,from="1991-01-01")=>({geometry:{type:"Point",coordinates:[lon,lat]},
  properties:{stationId:id,country,name:"Station "+id,status:"Active",operationFrom:from,parameterId:["mean_temp"]}});
 const rows=m.prepareCatalogue([
  feat("04220","GRL",-52.85,68.71),feat("04220","GRL",-52.84,68.72,"2000-01-01"),
  feat("10000","DNK",12,56),feat("04230","GRL",-48,65),feat("99999","GRL",-80,70)]);
 assert.equal(rows.length,2);
 assert.equal(rows.find(x=>x.id==="04220").lat,68.72);
});
test("Map decimation preserves exact original samples for CSV and extrema",()=>{
 const input=Array.from({length:2500},(_,i)=>({date:String(i).padStart(4,"0"),value:Math.sin(i)}));
 input[100].value=-150;input[1700].value=150;
 const drawn=m.downsample(input,800);
 assert.ok(drawn.length<=900);
 assert.ok(drawn.some(x=>x.value===-150));
 assert.ok(drawn.some(x=>x.value===150));
 assert.equal(input.length,2500);
});
test("Real station catalogue JSON has valid DMI metadata and genuine recent values",()=>{
 const file=path.join(__dirname,"../data/dmi_greenland_stations.json");
 if(!fs.existsSync(file))return;
 const cache=JSON.parse(fs.readFileSync(file,"utf8"));
 assert.equal(cache.schema,1);
 assert.ok(cache.stations.length>=10);
 assert.ok(Object.keys(cache.latest).length>=1);
 const seen=new Set();
 for(const s of cache.stations){
  assert.ok(!seen.has(s.id));seen.add(s.id);
  assert.ok(s.lon>=-75&&s.lon<=-10&&s.lat>=59&&s.lat<=84);
 }
 assert.ok(cache.stations.some(s=>s.status==="Active"));
 for(const row of Object.values(cache.latest))for(const x of Object.values(row)){
  assert.ok(Number.isFinite(x.value));
  assert.match(x.date,/^20\d\d-\d\d-\d\d$/);
 }
});
