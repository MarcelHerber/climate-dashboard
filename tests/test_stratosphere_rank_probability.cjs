const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

function sampleContext(){
 const elements=new Map(),handlers=new Map();
 const getElementById=id=>{
   if(!elements.has(id))elements.set(id,{
     id,textContent:"",disabled:false,value:"",addEventListener(name,cb){
       handlers.set(id+":"+name,cb);
     }
   });
   return elements.get(id);
 };
 const document={getElementById};
 const window={addEventListener(name,cb){handlers.set("window:"+name,cb);}};
 return {elements,handlers,document,window,console,Date,Intl,
   Number,Math,Map,Set,Array,Object,JSON,Promise,Blob:class{},URL,
   Event:class Event{constructor(type){this.type=type;}},
   Chart:class Chart{
     constructor(el,options){window.lastChart={el,options};}
     destroy(){}
   }};
}
function instrument(file,target){
 const src=fs.readFileSync(file,"utf8");
 assert.match(src,/\}\)\(\);\s*$/);
 return src.replace(/\}\)\(\);\s*$/,"window.__test="+target+";})();");
}

test("historical statistics: 151-day and 152-day winters, no invented missing values",()=>{
 const context=sampleContext();
 vm.runInNewContext(instrument("stratosphere_winter_stats.js","{analyze,decode,expectedDays}"),context);
 const {analyze,decode,expectedDays}=context.window.__test;
 assert.equal(expectedDays(2022),151);
 assert.equal(expectedDays(2023),152);
 const data=new Map();
 for(let t=Date.parse("2023-11-01T00:00:00Z");t<=Date.parse("2024-03-31T00:00:00Z");t+=86400000){
   const iso=new Date(t).toISOString().slice(0,10);
   data.set(iso,iso<"2023-11-06"?-1:20);
 }
 const full=analyze(2023,data);
 assert.equal(full.complete,true);
 assert.equal(full.count,152);
 assert.equal(full.easterlyDays,5);
 assert.equal(full.min,-1);
 assert.equal(full.max,20);
 assert.equal(full.longestWest,147);
 const withoutLeap=new Map(data);
 withoutLeap.delete("2024-02-29");
 const gap=analyze(2023,withoutLeap);
 assert.equal(gap.complete,true);
 assert.equal(gap.count,151);
 const manyGaps=new Map(data);
 for(const d of ["2024-02-29","2024-02-28","2024-02-27"])manyGaps.delete(d);
 assert.equal(analyze(2023,manyGaps).complete,false);
 const incomplete=new Map(data);incomplete.delete("2023-11-01");
 assert.equal(analyze(2023,incomplete).complete,false);
 const lines=[
   "2023-11-01 -2 0 0 0 0 0 0 0",
   "2023-11-02 5 0 0 0 0 0 0 0 12",
   "2023-11-03 -3 0 0 0 0 0 0 0",
   "2024-05-01 99 0 0 0 0 0 0 0"
 ];
 const d=decode(lines.join("\n"),2023);
 assert.equal(d.size,2);
 assert.equal(d.get("2023-11-01"),-2);
 assert.equal(d.get("2023-11-03"),-3);
});

test("GEFS wind reversal: 31 independently counted members",()=>{
 const context=sampleContext();
 vm.runInNewContext(fs.readFileSync("stratosphere_gefs_probability.js","utf8"),context);
 const handler=context.handlers.get("window:stratosphere:gefs-loaded");
 assert.equal(typeof handler,"function");
 const dates=["2026-10-29","2026-10-30","2026-10-31","2026-11-01"];
 const members=Object.fromEntries(Array.from({length:31},(_,i)=>[
   i===0?"c00":"p"+String(i).padStart(2,"0"),
   [16,i<10?-5:3,i<10?-2:6,5]
 ]));
 context.window.stratoGefsEnsemble={
   provider:"NOAA GEFS",level_hpa:10,latitude_deg:60,
   cycle_utc:"2026-10-29T00:00:00Z",valid_dates:dates,members,
   member_count:31
 };
 handler();
 assert.equal(context.elements.get("stratoProbAny").textContent,"32 %");
 assert.match(context.elements.get("stratoProbPeak").textContent,/32 % · 2026-10-30/);
 const chart=context.window.lastChart.options.data.datasets[0].data;
 assert.equal(chart.length,4);
 assert.equal(chart[0],0);
 assert.ok(Math.abs(chart[1]-1000/31)<1e-9);
 context.window.stratoGefsEnsemble={provider:"NOAA GEFS",level_hpa:10,latitude_deg:60,valid_dates:dates,members:{c00:members.c00}};
 handler();
 assert.equal(context.elements.get("stratoProbAny").textContent,"–");
});
