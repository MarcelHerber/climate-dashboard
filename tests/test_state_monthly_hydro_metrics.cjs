#!/usr/bin/env node
"use strict";
/* Test real monthly-outlook JS without browser dependencies. No source edits. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

function select(value,options){
  const list=options.map(v=>({value:v,textContent:v,disabled:false}));
  return {value,options:list,disabled:false,title:"",
    querySelectorAll(type){assert.equal(type,"option");return list;},
    querySelector(query){const m=/^option\[value="([^"]+)"\]$/.exec(query);
      return m?list.find(o=>o.value===m[1])||null:null;}
  };
}
const nodes={
  stateMonthlyParameter:select("precipitation",["temperature","precipitation","sunshine"]),
  stateMonthlyRegion:select("Deutschland",["Deutschland","Hessen","Saarland"]),
  stateMonthlyMetric:select("absolute",["absolute","anomaly","percent"]),
  stateMonthlyPeriod:select("month",["month","season","year"]),
  stateMonthlyExportDescription:{textContent:""}
};
const document={
  readyState:"loading",
  getElementById(id){return nodes[id]||null;},
  addEventListener(){},
};
const context={window:{},document,console,Date,Intl,MutationObserver:function(){}};
const source=fs.readFileSync(path.join(__dirname,"..","state_monthly_ensemble.js"),"utf8");
assert.match(source,/\}\)\(\);\s*$/,"Expected end of monthly-outlook closure");
const injected=source.replace(/\}\)\(\);\s*$/,
  `window.__metricTest={
    setHydro(param,doc,reference,monthly){
      hydro[param]=doc;
      if(param==="precipitation")dailyRainReference=reference;
      if(param==="sunshine")dailySunReference=reference;
      monthlyNormals=monthly;
    },
    transformHydroValue,dailyHydroRunning,hydroReferenceDatasets,
    displayDatasets,chartBounds,chartOptions,syncParameterControls
  };})();`);
vm.runInNewContext(injected,context,{filename:"state_monthly_ensemble.js"});
const api=context.window.__metricTest;
assert.ok(api);

function monthlyNormal(param,month,region,value){
  return {reference_period:"1991-2020",months:{
    [month]:{[param]:{[region]:{month_total:value}}}
  }};
}
function modelStats(n){
  const base=[null,null,8,12];
  return {min:base.map(v=>v===null?null:v-2),
    p05:base.map(v=>v===null?null:v-1),
    p20:base.map(v=>v===null?null:v-.4),
    mean:base,
    p80:base.map(v=>v===null?null:v+.4),
    p95:base.map(v=>v===null?null:v+1),
    max:base.map(v=>v===null?null:v+2)};
}
function fixture(param){
  const iso=["2026-11-01","2026-11-02","2026-11-03","2026-11-04"];
  const region={observed_through:iso[1],observed_running:[1,3,null,null],observed_current:3,
    models:{gefs:{stats:modelStats(),control:[null,null,7,11]}}};
  const doc={year:2026,month:11,dates:iso,regions:{Deutschland:region}};
  const reference={months:{"11":{dates:["11-01","11-02","11-03","11-04"],
    regions:{Deutschland:param==="precipitation"?{running_mm:[0,2,4,6]}:{running_h:[0,2,4,6]}}}}};
  api.setHydro(param,doc,reference,monthlyNormal(param,"11","Deutschland",60));
  nodes.stateMonthlyParameter.value=param;nodes.stateMonthlyRegion.value="Deutschland";
  return region;
}
for(const param of ["precipitation","sunshine"]){
  const r=fixture(param),unit=param==="sunshine"?"h":"mm";
  nodes.stateMonthlyMetric.value="absolute";
  api.syncParameterControls();
  assert.equal(nodes.stateMonthlyMetric.disabled,false);
  assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="percent").disabled,false);
  assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="anomaly").disabled,false);
  assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="absolute").textContent,`Gesamtsumme (${unit})`);
  const abs=api.displayDatasets("gefs",r);
  assert.equal(abs[0].data[1],3);
  assert.equal(abs.filter(d=>d.isDailyClimate).length,1);
  assert.ok(abs.some(d=>d.label.includes("vollständiger Monat")));
  assert.equal(abs[1].data[2],4);

  nodes.stateMonthlyMetric.value="anomaly";
  api.syncParameterControls();
  const ds=api.displayDatasets("gefs",r);
  assert.equal(ds[0].data[1],1);
  assert.equal(ds[0].data[0],1); // 0-mm/h daily reference: anomaly is valid
  assert.equal(ds.find(d=>d.isDailyClimate).data[1],0);
  assert.equal(ds.find(d=>d.label==="Ensemble-Mittel").data[2],4);
  assert.equal(ds.find(d=>d.label==="Kontroll-/Basislauf").data[2],3);
  assert.equal(ds.find(d=>d.label==="5–95 %").data[2],5);
  assert.equal(ds.find(d=>d.label==="5–95 % Untergrenze").data[2],3);
  assert.ok(!ds.some(d=>d.label.includes("vollständiger Monat")));
  assert.ok(api.chartBounds(ds).min<0 || api.chartBounds([
    {data:[-15,0,3]}]).min<0,"Anomaly y-axis must allow negative values");
  assert.match(api.chartOptions({min:-5,max:8}).scales.y.title.text,/Tagesklimareferenz/);
  assert.match(nodes.stateMonthlyExportDescription.textContent,/Abweichung/);

  nodes.stateMonthlyMetric.value="percent";
  api.syncParameterControls();
  const pct=api.displayDatasets("gefs",r);
  assert.equal(pct[0].data[0],null,"0 baseline should never yield fake infinity");
  assert.equal(pct[0].data[1],150);
  assert.equal(pct.find(d=>d.isDailyClimate).data[1],100);
  assert.equal(pct.find(d=>d.isDailyClimate).data[0],null);
  assert.equal(pct.find(d=>d.label==="Ensemble-Mittel").data[2],200);
  assert.equal(pct.find(d=>d.label==="5–95 %").data[2],225);
  assert.equal(api.chartBounds(pct).min,0,"Relative hydro plots start at 0%");
  assert.match(api.chartOptions({min:0,max:300}).scales.y.title.text,/%/);
  assert.match(nodes.stateMonthlyExportDescription.textContent,/Prozent/);

  assert.equal(api.transformHydroValue(null,2,"percent"),null);
  assert.equal(api.transformHydroValue(2,null,"anomaly"),null);
  assert.equal(api.transformHydroValue(2,0,"percent"),null);
  assert.equal(api.transformHydroValue(0,0,"anomaly"),0);
  assert.equal(api.transformHydroValue(-1,3,"percent"),-33.333); // method is pure; physical validation is upstream
  assert.equal(api.transformHydroValue(6,3,"percent"),200);
  assert.equal(api.transformHydroValue(6,3,"anomaly"),3);

  // Missing climate source must disable derived views, not re-use monthly total.
  api.setHydro(param,api===null?null:{...{year:2026,month:11,dates:["2026-11-01"],regions:{Deutschland:r}}},null,
    monthlyNormal(param,"11","Deutschland",60));
  nodes.stateMonthlyMetric.value="percent";
  api.syncParameterControls();
  assert.equal(nodes.stateMonthlyMetric.value,"absolute");
  assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="percent").disabled,true);
}
// Temperature retains its Kelvin anomaly and cannot select hydro percentage.
nodes.stateMonthlyParameter.value="temperature";
nodes.stateMonthlyMetric.value="percent";
api.syncParameterControls();
assert.equal(nodes.stateMonthlyMetric.value,"absolute");
assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="anomaly").disabled,false);
assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="percent").disabled,true);

function testLiveFiles(args){
  if(!args.length)return;
  assert.equal(args.length,4,"Usage: test JS [rain_forecast.json rain_reference.json sun_forecast.json sun_reference.json]");
  const pairs=[
    ["precipitation",args[0],args[1]],
    ["sunshine",args[2],args[3]],
  ];
  for(const [param,forecastFile,referenceFile] of pairs){
    const d=JSON.parse(fs.readFileSync(forecastFile,"utf8"));
    const ref=JSON.parse(fs.readFileSync(referenceFile,"utf8"));
    assert.equal(d.parameter,param);
    assert.equal(ref.parameter,param);
    assert.equal(ref.reference_period,"1991-2020");
    assert.equal(d.regions_order.length,17);
    for(const name of d.regions_order){
      const region=d.regions[name];
      nodes.stateMonthlyParameter.value=param;
      nodes.stateMonthlyRegion.value=name;
      api.setHydro(param,d,ref,null);
      const daily=api.dailyHydroRunning(name);
      assert.equal(daily.length,d.dates.length);
      assert.equal(daily.every(v=>v===null||v>=0),true);
      const end=d.dates.indexOf(d.observation_data_through);
      assert.ok(end>=0);
      const observed=region.observed_running[end],reference=daily[end];
      assert.ok(typeof observed==="number");
      assert.ok(typeof reference==="number");
      nodes.stateMonthlyMetric.value="anomaly";
      api.syncParameterControls();
      for(const modelKey of Object.keys(region.models)){
        const out=api.displayDatasets(modelKey,region);
        const actual=out[0].data[end];
        const expected=Math.round((observed-reference)*1000)/1000;
        assert.ok(Math.abs(actual-expected)<.002,`${param} ${name} anomaly ${actual} vs ${expected}`);
        nodes.stateMonthlyMetric.value="percent";
        const percent=api.displayDatasets(modelKey,region)[0].data[end];
        assert.ok(reference>0?Math.abs(percent-observed/reference*100)<.002:percent===null);
        nodes.stateMonthlyMetric.value="anomaly";
      }
    }
    console.log("LIVE monthly outlook:",param,"17 real regions, day-aligned anomalies and percentages OK");
  }
}
testLiveFiles(process.argv.slice(2));
console.log("Monthly outlook hydro metric tests passed");
