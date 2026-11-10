#!/usr/bin/env node
const test=require("node:test"),assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const script=fs.readFileSync(path.join(__dirname,"../groenland_climate.js"),"utf8");
const ctx={window:{},document:{readyState:"loading",addEventListener(){}},Date,Number,
 Math,String,Map,Set,Array,Intl,URLSearchParams,console};
vm.createContext(ctx);vm.runInContext(script,ctx);
const m=ctx.window.GreenlandClimateMath;
const today=new Date(Date.UTC(2026,10,10));
function annual(y,extra=0,count=null){
 return {date:String(y),value:5+(y-1991)*.03+extra,count:count??(y%4===0&&y%100!==0?366:365),qc:"manual"};
}
function monthly(y,mon,v=0,count=30){
 const days=new Date(Date.UTC(y,mon,0)).getUTCDate();
 return {date:String(y)+"-"+String(mon).padStart(2,"0"),value:v+5+(y-1991)*.1,
 count:count===30?days:count,qc:"manual"};
}
test("DMI yearly 80% coverage uses calendar year, rejects current unfinished year",()=>{
 assert.equal(m.checkCoverage(annual(2016,0,300),"year",.8,today),true);
 assert.equal(m.checkCoverage(annual(2016,0,292),"year",.8,today),false);
 assert.equal(m.checkCoverage(annual(2018,0,292),"year",.8,today),true);
 assert.equal(m.checkCoverage(annual(2026,0,365),"year",.8,today),false);
 assert.equal(m.checkCoverage({date:"2000",value:1,count:null},"year",.8,today),false);
});
test("DMI monthly February coverage is leap-year-aware, not interpolated",()=>{
 assert.equal(m.checkCoverage(monthly(2020,2,-5,23),"month",.8,today),false);
 assert.equal(m.checkCoverage(monthly(2020,2,-5,24),"month",.8,today),true);
 assert.equal(m.checkCoverage(monthly(2019,2,-5,23),"month",.8,today),true);
 assert.equal(m.checkCoverage(monthly(2026,11,-5,30),"month",.8,today),false);
});
test("1991–2020 baseline requires >=24 independent sufficiently covered years",()=>{
 const input=Array.from({length:30},(_,i)=>annual(1991+i));
 const full=m.calculate(input,"year",1,.8,today);
 assert.equal(full.refCount,30);
 assert.ok(full.normal!==null);
 assert.ok(full.ranked.every(x=>Number.isFinite(x.anomaly)));
 const partial=input.filter((_,i)=>i>=6);
 assert.equal(m.calculate(partial,"year",1,.8,today).refCount,24);
 const insufficient=m.calculate(partial.slice(1),"year",1,.8,today);
 assert.equal(insufficient.refCount,23);
 assert.equal(insufficient.normal,null);
 assert.equal(insufficient.ranked.length,0);
 assert.equal(insufficient.trend,null);
});
test("1980s values can be ranked but never shift the 1991–2020 reference",()=>{
 const input=[annual(1980,-10),...Array.from({length:30},(_,i)=>annual(1991+i))];
 const full=m.calculate(input,"year",1,.8,today);
 assert.equal(full.refCount,30);
 assert.equal(full.cold[0].year,1980);
 assert.equal(full.warm[0].year,2020);
 const withoutOld=m.calculate(input.slice(1),"year",1,.8,today);
 assert.equal(full.normal,withoutOld.normal);
});
test("Linear climate trend returns signed °C/decade over observed years",()=>{
 const rows=Array.from({length:30},(_,i)=>annual(1991+i,0));
 const result=m.calculate(rows,"year",1,.8,today);
 assert.ok(result.trend);
 assert.equal(result.trend.slopePerDecade,.3);
});
test("Monthly climate normal uses selected month only, no seasonal mixing",()=>{
 const input=Array.from({length:30},(_,i)=>[
  monthly(1991+i,1,-20),
  monthly(1991+i,7,20)
 ]).flat();
 const jan=m.calculate(input,"month",1,.8,today),jul=m.calculate(input,"month",7,.8,today);
 assert.equal(jan.refCount,30);assert.equal(jul.refCount,30);
 assert.ok(jul.normal-jan.normal>30);
 assert.ok(jan.ranked.every(x=>x.date.endsWith("-01")));
});
test("Real DMI Greenland record cache has ranked year extremes and missing stations excluded",()=>{
 const file=path.join(__dirname,"../data/dmi_greenland_records.json");
 if(!fs.existsSync(file))return;
 const doc=JSON.parse(fs.readFileSync(file,"utf8"));
 assert.equal(doc.schema,1);
 for(const [mode,items] of Object.entries(doc.modes)){
  assert.ok(["high","low","rain","gust"].includes(mode));
  assert.ok(Object.keys(items).length>=15);
  for(const item of Object.values(items)){
   const max=mode!=="low";
   assert.ok(item.count>=item.top.length);
   assert.ok(item.top.every(x=>Number.isFinite(x.value)));
   assert.ok(item.top.every(x=>max?x.value<=item.value:x.value>=item.value));
  }
 }
});
