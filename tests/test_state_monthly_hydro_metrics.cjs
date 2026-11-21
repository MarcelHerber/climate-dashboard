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
  stateMonthlyReference:select("1991-2020",["1991-2020","1961-1990"]),
  stateMonthlyRegion:select("Deutschland",["Deutschland","Hessen","Saarland"]),
  stateMonthlyMetric:select("absolute",["absolute","anomaly","percent"]),
  stateMonthlyPeriod:select("month",["month","season","year"]),
  stateMonthlyView:select("ifs",["four","gefs","ifs","aifs","icon_eu"]),
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
    setOldReference(kind,doc){oldReferences[kind]=doc;},
    setTemperature(doc){data=doc;},
    transformHydroValue,dailyHydroRunning,hydroReferenceDatasets,
    displayDatasets,chartBounds,chartOptions,syncParameterControls,temperatureRunning,filename,fetchOldReference,exportPng,exportPdf
  };})();`);
vm.runInNewContext(injected,context,{filename:"state_monthly_ensemble.js"});
const api=context.window.__metricTest;
assert.ok(api);
const ALL_REGIONS=["Deutschland","Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"];
function oldDailyFixture(){
  const months={};
  for(let month=1;month<=12;month++){
    const key=String(month).padStart(2,"0"),dates=Array.from({length:new Date(Date.UTC(2000,month,0)).getUTCDate()},(_,i)=>`${key}-${String(i+1).padStart(2,"0")}`);
    const running=dates.map((_,i)=>i===0?1:2*i+2),daily=running.map((value,i)=>value-(running[i-1]??0));
    months[key]={dates,regions:Object.fromEntries(ALL_REGIONS.map(name=>[name,{daily_mm:daily.slice(),running_mm:running.slice()}]))};
  }
  return {schema_version:1,reference_period:"1961-1990",product:"state_monthly_daily_precip_climatology",parameter:"precipitation",unit:"mm",daily_climatology_available:true,regions_order:ALL_REGIONS.slice(),months};
}

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
    models:{gefs:{forecast_through:iso[3],stats:modelStats(),control:[null,null,7,11]}}};
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
  assert.equal(nodes.stateMonthlyView.value,"four");
  assert.equal(nodes.stateMonthlyView.options.find(x=>x.value==="ifs").disabled,true);
  assert.equal(nodes.stateMonthlyView.options.find(x=>x.value==="gefs").disabled,false);
  assert.equal(nodes.stateMonthlyMetric.disabled,false);
  assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="percent").disabled,false);
  assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="anomaly").disabled,false);
  assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="absolute").textContent,`Gesamtsumme (${unit})`);
  const abs=api.displayDatasets("gefs",r);
  {
    const obsOnly=api.displayDatasets("gefs",{...r,models:{}});
    assert.equal(obsOnly[0].data[1],3);
    assert.ok(!obsOnly.some(d=>d.label==="Ensemble-Mittel"));
  }
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
assert.equal(nodes.stateMonthlyView.options.find(x=>x.value==="ifs").disabled,false);
assert.equal(nodes.stateMonthlyMetric.value,"absolute");
assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="anomaly").disabled,false);
assert.equal(nodes.stateMonthlyMetric.options.find(x=>x.value==="percent").disabled,true);

// The old reference must never use cached 1991-2020 data while loading.
for(const param of ["precipitation","sunshine"]){
  const r=fixture(param);
  nodes.stateMonthlyReference.value="1961-1990";
  nodes.stateMonthlyMetric.value="anomaly";
  api.syncParameterControls();
  assert.equal(nodes.stateMonthlyMetric.value,"absolute");
  assert.equal(api.dailyHydroRunning("Deutschland"),null);
  assert.equal(api.displayDatasets("gefs",r)[0].data[1],3);
  assert.equal(api.hydroReferenceDatasets().length,0);
  api.setOldReference(param,{reference_period:"1961-1990",months:{"11":{
    dates:["11-01","11-02","11-03","11-04"],regions:{Deutschland:param==="precipitation"?{running_mm:[1,4,6,8]}:{running_h:[1,4,6,8]}}
  }}});
  api.setOldReference("monthly",{reference_period:"1961-1990",months:{"11":{[param]:{Deutschland:{month_total:80}}}}});
  nodes.stateMonthlyMetric.value="anomaly";
  api.syncParameterControls();
  const old=api.displayDatasets("gefs",r);
  assert.equal(old[0].data[1],-1);
  assert.equal(old.find(d=>d.label==="Ensemble-Mittel").data[2],2);
  assert.match(old.find(d=>d.isDailyClimate).label,/1961–1990/);
  assert.match(nodes.stateMonthlyExportDescription.textContent,/1961–1990/);
  assert.match(api.filename("png"),/1961-1990/);
  nodes.stateMonthlyMetric.value="percent";
  assert.equal(api.displayDatasets("gefs",r)[0].data[1],75);
  nodes.stateMonthlyMetric.value="absolute";
  assert.equal(api.displayDatasets("gefs",r)[0].data[1],3);
  assert.equal(api.displayDatasets("gefs",r).find(d=>d.label==="Ensemble-Mittel").data[2],8);
  assert.ok(api.hydroReferenceDatasets().some(d=>d.label.includes("80,0")));
  nodes.stateMonthlyReference.value="1991-2020";
  nodes.stateMonthlyMetric.value="anomaly";
  assert.equal(api.displayDatasets("gefs",r)[0].data[1],1);
  api.setOldReference("monthly",null);
}

// Temperature day normals must be averaged over the actual calendar dates,
// not approximated by the full-month baseline or an old year constant.
nodes.stateMonthlyParameter.value="temperature";
nodes.stateMonthlyPeriod.value="season";
const temp={climatology_running:[4,6,8,10],climatology_month_mean:10,
  observed_running:[2,4,null,null],models:{gefs:{forecast_through:'2024-03-02',stats:modelStats(),control:[null,null,7,11]}}};
api.setTemperature({year:2024,month:2,periods:{season:{dates:["2024-02-28","2024-02-29","2024-03-01","2024-03-02"]}},regions:{Deutschland:{periods:{season:temp}}}});
nodes.stateMonthlyReference.value="1961-1990";
nodes.stateMonthlyMetric.value="anomaly";
api.syncParameterControls();
assert.equal(nodes.stateMonthlyMetric.value,"absolute");
assert.equal(api.displayDatasets("gefs",temp).some(d=>d.isTemperatureClimate),false);
api.setOldReference("temperature",{reference:"1961-1990",regions:{Deutschland:{"02-28":2,"02-29":4,"03-01":6,"03-02":8}}});
assert.deepEqual(Array.from(api.temperatureRunning(temp)),[2,3,4,5]);
nodes.stateMonthlyMetric.value="anomaly";
api.syncParameterControls();
assert.equal(api.displayDatasets("gefs",temp)[0].data[1],1);
assert.equal(api.displayDatasets("gefs",temp).find(d=>d.label==="Ensemble-Mittel").data[2],4);
assert.match(api.chartOptions({min:-5,max:5}).scales.y.title.text,/1961–1990/);
assert.match(nodes.stateMonthlyExportDescription.textContent,/1961–1990/);
nodes.stateMonthlyReference.value="1991-2020";
assert.equal(api.displayDatasets("gefs",temp)[0].data[1],-2);
nodes.stateMonthlyPeriod.value="month";

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
async function testTemperatureReference(file){
  const ref=JSON.parse(fs.readFileSync(file,"utf8"));
  const names=Object.keys(ref.regions),dates=Array.from({length:30},(_,i)=>`2026-11-${String(i+1).padStart(2,"0")}`);
  assert.equal(ref.reference,"1961-1990");
  assert.equal(names.length,17);
  // Exercise the actual fetch/validation code, not only manually injected mocks.
  context.fetch=async(url)=>{
    assert.match(url,/hyras-data\/tmean\/regions\/climate_1961_1990\.json/);
    return {ok:true,json:async()=>ref};
  };
  nodes.stateMonthlyParameter.value="temperature";
  nodes.stateMonthlyPeriod.value="month";
  nodes.stateMonthlyReference.value="1961-1990";
  api.setTemperature({year:2026,month:11,dates,regions:{}});
  api.setOldReference("temperature",null);
  assert.ok(await api.fetchOldReference("temperature"));
  for(const name of names){
    const days=ref.regions[name];
    assert.equal(Object.keys(days).length,366);
    nodes.stateMonthlyRegion.value=name;
    const running=api.temperatureRunning({});
    assert.equal(running.length,30);
    assert.equal(running[0],days["11-01"]);
    assert.ok(running.every(Number.isFinite));
    const mean=dates.reduce((total,date)=>total+days[date.slice(5)],0)/30;
    assert.ok(Math.abs(running.at(-1)-mean)<1e-8);
    if(name==="Deutschland")assert.ok(Math.abs(running.at(-1)-3.9719)<.001,`DE November 1961-1990 is ${running.at(-1)} °C`);
  }
  console.log("LIVE 1961–1990 HYRAS temperature reference: 17 regions, 366 days, November running means OK");
}
async function testReferenceFetchRace(){
  const oldDaily=oldDailyFixture();
  nodes.stateMonthlyReference.value="1991-2020";
  fixture("precipitation");
  api.setOldReference("precipitation",null);
  let release;
  context.fetch=async()=>await new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>oldDaily});});
  nodes.stateMonthlyReference.value="1961-1990";
  const request=api.fetchOldReference("precipitation");
  nodes.stateMonthlyReference.value="1991-2020";
  release();
  await request;
  assert.equal(api.dailyHydroRunning("Deutschland")[1],2,"old reference fetched in background must not overwrite current baseline");
  nodes.stateMonthlyReference.value="1961-1990";
  assert.equal(api.dailyHydroRunning("Deutschland")[1],4);
  nodes.stateMonthlyReference.value="1991-2020";
}
async function testMalformedOldReference(){
  nodes.stateMonthlyReference.value="1961-1990";
  // Expected rejection warnings must not obscure unexpected test failures.
  context.console={...console,warn(){}};
  for(const mutate of [
    doc=>{doc.reference_period="1991-2020";},
    doc=>{doc.regions_order[0]="Nirgendwo";},
    doc=>{doc.months["02"].dates.pop();},
    doc=>{delete doc.months["11"].regions.Deutschland;},
    doc=>{doc.months["11"].regions.Deutschland.running_mm[2]=0;},
    doc=>{doc.months["11"].regions.Deutschland.daily_mm[2]=null;}
  ]){
    const doc=oldDailyFixture();mutate(doc);
    api.setOldReference("precipitation",null);
    context.fetch=async()=>({ok:true,json:async()=>doc});
    assert.equal(await api.fetchOldReference("precipitation"),null,"wrong or incomplete reference must be rejected");
    assert.equal(api.dailyHydroRunning("Deutschland"),null);
  }
  // No anomaly when the selected calendar has only partial valid coverage.
  api.setOldReference("precipitation",{months:{"11":{dates:["11-01","11-02","11-03","11-04"],regions:{Deutschland:{running_mm:[1,2,null,3]}}}}});
  nodes.stateMonthlyMetric.value="anomaly";
  api.syncParameterControls();
  assert.equal(nodes.stateMonthlyMetric.value,"absolute");
  nodes.stateMonthlyReference.value="1991-2020";
  context.console=console;
}
async function testExportReferenceSnapshot(){
  const downloads=[];
  context.URL={createObjectURL:()=>"blob:fixture",revokeObjectURL(){}};
  context.setTimeout=fn=>fn();
  document.body={appendChild(){}};
  document.createElement=()=>({click(){downloads.push(this.download);},remove(){}});
  context.window.html2canvas=true;
  let finish;
  context.window.captureDashboardWithWhiteBackground=()=>new Promise(resolve=>{finish=resolve;});
  fixture("precipitation");
  nodes.stateMonthlyReference.value="1961-1990";
  nodes.stateMonthlyMetric.value="absolute";
  const png=api.exportPng();
  assert.equal(nodes.stateMonthlyReference.disabled,true);
  nodes.stateMonthlyReference.value="1991-2020"; // programmatic change bypasses the UI lock
  finish({toBlob(callback){callback({});}});
  await png;
  assert.match(downloads[0],/1961-1990.*\.png$/);
  assert.equal(nodes.stateMonthlyReference.disabled,false);
  context.window.jspdf={jsPDF:class{
    internal={pageSize:{getWidth:()=>297,getHeight:()=>210}};
    addImage(){}
    save(name){downloads.push(name);}
  }};
  nodes.stateMonthlyReference.value="1961-1990";
  const pdf=api.exportPdf();
  assert.equal(nodes.stateMonthlyReference.disabled,true);
  nodes.stateMonthlyReference.value="1991-2020";
  finish({width:1000,height:800,toDataURL:()=>"fixture"});
  await pdf;
  assert.match(downloads[1],/1961-1990.*\.pdf$/);
  assert.equal(nodes.stateMonthlyReference.disabled,false);
}
(async()=>{
  const args=process.argv.slice(2),tempIndex=args.indexOf("--temp-reference");
  if(tempIndex!==-1){
    const [,file]=args.splice(tempIndex,2);
    assert.ok(file,"--temp-reference requires path to real HYRAS JSON");
    await testTemperatureReference(file);
    nodes.stateMonthlyReference.value="1991-2020";
  }
  testLiveFiles(args);
  await testReferenceFetchRace();
  await testMalformedOldReference();
  await testExportReferenceSnapshot();
  console.log("Monthly outlook hydro metric tests passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
