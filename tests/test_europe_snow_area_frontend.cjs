"use strict";
const test=require("node:test"),assert=require("node:assert/strict");
const vm=require("node:vm"),fs=require("node:fs");
const source=fs.readFileSync("eurasia_snow.js","utf8");

async function settle(){for(let i=0;i<16;i++)await new Promise(r=>setImmediate(r))}
function data(europe=false){
  const mean=europe?1.0:8.0,obs=europe?1.2:9.5;
  const november=Array.from({length:30},(_,i)=>({
    day:i+1,mean:i===8?mean:null,stddev:i===8?.2:null,
    min:i===8?mean-.3:null,max:i===8?mean+.3:null,
    min_year:i===8?2017:null,max_year:i===8?2024:null,
    years:i===8?11:0,min_years:10
  }));
  return {
    schema:1,source:{doi:"10.7265/N52R3PMC"},
    analysis:{region:europe?{lat_south:35,lat_north:75,lon_west:-25,lon_east:70}:{}},
    generated_utc:"2026-11-10T04:00:00Z",
    daily:{"2026-11-09":obs,"2026-11-10":obs-.1,"2025-11-09":mean},
    seasons:[2026,2025],calendar_years:[2026,2025],
    climatology_by_month:{"11":november},
    status:{n_climatology_days_year:1}
  };
}
function browser(missingEurope=false){
  class Element{
    constructor(id){
      this.id=id;this.children=[];this.dataset={};this.handlers={};
      this.value=id==="seriesRegion"?"eurasia":id==="month"?"year":"";
      this.checked=id==="showExtremes"||id==="showTrend";
      this.hidden=false;this.disabled=false;this.textContent="";
    }
    addEventListener(ev,callback){this.handlers[ev]=callback}
    replaceChildren(...children){this.children=children;this.value=children[0]?.value||""}
    append(option){this.children.push(option);if(this.children.length===1)this.value=option.value}
    get options(){return this.children}
    setAttribute(){}
    change(){this.handlers.change?.()}
  }
  const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id)};
  const docs={eurasia:data(false),europe:data(true)};
  const calls=[];
  const document={
    getElementById:get,title:"",createElement:()=>new Element("anchor")
  };
  const chart={data:{labels:[],datasets:[]},options:{plugins:{title:{text:""}},scales:{x:{title:{}},y:{title:{}}}},update(){}};
  const sandbox={document,console,Date,Intl,Math,Number,Array,Set,Map,Option:class{constructor(text,value){this.text=text;this.value=value}},
    Chart:class{constructor(){return chart}},fetch:async url=>{
      calls.push(url);const isEurope=url.includes("europe_index.json");
      if(isEurope&&missingEurope)return {ok:false,status:404};
      return {ok:true,json:async()=>isEurope?docs.europe:docs.eurasia};
    },
    setTimeout:()=>0,Blob,URL:{createObjectURL:()=>"blob:fake",revokeObjectURL:()=>{}}
  };
  vm.runInNewContext(source,sandbox);
  return {get,chart,calls,docs};
}
function observation(chart){
  return chart.data.datasets.find(item=>item.label.startsWith("NOAA IMS"));
}
test("Europe selection uses its original native-raster series, not Eurasian areas",async()=>{
  const b=browser();await settle();
  b.get("month").value="11";b.get("month").change();
  assert.equal(observation(b.chart).data[8],9.5);
  b.get("seriesRegion").value="europe";b.get("seriesRegion").change();await settle();
  assert.equal(observation(b.chart).data[8],1.2);
  assert.match(b.get("plotTitle").textContent,/Europas/);
  assert.match(b.get("latest").textContent,/1.20/);
  assert.match(b.get("currentAreaAnomaly").textContent,/\+0.20/);
  assert.equal(b.calls.filter(url=>url.includes("europe_index.json")).length,1);
  b.get("seriesRegion").value="eurasia";b.get("seriesRegion").change();
  assert.equal(observation(b.chart).data[8],9.5);
});
test("Anomaly graph is a million km2 difference and never fills absent baselines",async()=>{
  const b=browser();await settle();
  b.get("seriesRegion").value="europe";b.get("seriesRegion").change();await settle();
  b.get("month").value="11";b.get("month").change();
  b.get("showAreaAnomaly").checked=true;b.get("showAreaAnomaly").change();
  assert.ok(Math.abs(observation(b.chart).data[8]-.2)<1e-9);
  assert.equal(observation(b.chart).data[9],null);
  assert.equal(b.chart.options.scales.y.min,undefined);
  const lo=b.chart.data.datasets.find(d=>d.label==="Historisches Tagesminimum");
  const hi=b.chart.data.datasets.find(d=>d.label==="Historisches Tagesmaximum");
  assert.ok(Math.abs(lo.data[8]+.3)<1e-9);
  assert.ok(Math.abs(hi.data[8]-.3)<1e-9);
  assert.equal(lo.recordYears[8],2017);
  assert.equal(hi.recordYears[8],2024);
});
test("Missing Europe raw-data file never silently shows Eurasian series",async()=>{
  const b=browser(true);await settle();
  b.get("seriesRegion").value="europe";b.get("seriesRegion").change();await settle();
  assert.equal(b.chart.data.datasets.length,0);
  assert.match(b.get("message").textContent,/Europa-Schneeflächenarchiv/);
  assert.equal(b.get("message").dataset.kind,"warn");
});
test("Page names region choices and preserves separate map and series controls",()=>{
  const html=fs.readFileSync("eurasia_snow.html","utf8");
  assert.match(html,/id="seriesRegion"/);
  assert.match(html,/id="showAreaAnomaly"/);
  assert.match(html,/id="snowMapRegion"/);
  assert.match(html,/id="currentAreaAnomaly"/);
});
