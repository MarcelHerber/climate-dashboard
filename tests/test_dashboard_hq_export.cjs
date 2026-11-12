const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

function setup(){
  const text=[],images=[],exports=[];
  const ctx={
    fillRect(){},fillText(value){text.push(String(value));},
    beginPath(){},moveTo(){},lineTo(){},stroke(){},
    drawImage(...args){images.push(args);},
    measureText(value){return {width:String(value).length*10}}
  };
  const document={createElement(type){
    assert.equal(type,"canvas");
    return {width:0,height:0,getContext(){return ctx;}};
  }};
  class FakeChart{
    constructor(canvas,configuration){
      this.config=configuration;
      exports.push(configuration);
    }
    update(){}
    destroy(){this.destroyed=true;}
  }
  const window={Chart:FakeChart};
  const js=fs.readFileSync("dashboard_export_hq.js","utf8");
  vm.runInNewContext(js,{window,document,Date,WeakMap,Object,Number,String,Array,Math,Error});
  return {api:window.DashboardExportHQ,text,images,exports};
}
test("re-renders chart at fixed print resolution, never mobile canvas size",()=>{
  const {api,exports,text}=setup();
  const dataset={label:"2025",data:[1,null,3],borderColor:"#111111"};
  const original={
    canvas:{width:390,height:240,id:"snow"},
    config:{type:"line",_config:{options:{
      responsive:true,scales:{x:{ticks:{maxTicksLimit:5,maxRotation:0}}},
      plugins:{title:{display:true,text:"Schnee"}}
    }}},
    data:{labels:["1","2","3"],datasets:[dataset]},
    isDatasetVisible(){return false}
  };
  const out=api.renderChart(original,{title:"Schnee – DWD",source:"DWD CDC"});
  assert.equal(out.width,2200);
  assert.equal(out.height,1470);
  assert.equal(exports.length,1);
  assert.equal(exports[0].options.responsive,false);
  assert.equal(exports[0].options.plugins.climateMobileLegibilityV1,false);
  assert.ok(exports[0].options.scales.x.ticks.maxTicksLimit>=17);
  assert.equal(exports[0].data.datasets[0].hidden,true);
  assert.deepEqual(Array.from(exports[0].data.datasets[0].data),[1,null,3]);
  assert.equal(original.config._config.options.scales.x.ticks.maxTicksLimit,5);
  assert.equal(dataset.hidden,undefined);
  assert.ok(text.some(t=>t.includes("DWD CDC")));
});
test("map compositor has white background, geographic source and export timestamp",()=>{
  const {api,text,images}=setup();
  const source={width:1000,height:500};
  const out=api.composeCanvas(source,{title:"Gefahren Europa",source:"DWD ICON-EU"});
  assert.equal(out.width,2200);
  assert.equal(out.height,1470);
  assert.equal(images.length,1);
  assert.equal(images[0][0],source);
  assert.ok(text.some(t=>t.includes("Gefahren Europa")));
  assert.ok(text.some(t=>t.includes("DWD ICON-EU")));
  assert.ok(text.some(t=>t.startsWith("Erstellt:")));
});
test("Phase 2 export uses a parameter subtitle and wraps long source notes",()=>{
  const {api,text,images}=setup();
  const note=("Quelle DWD und ECMWF mit unveränderter Zeitreferenz. ").repeat(8);
  const output=api.composeCanvas({width:900,height:500},
    {title:"Vergleich",subtitle:"DWD-Gebietsmittel · 1991–2020",source:note});
  assert.equal(output.width,2200);
  assert.ok(text.includes("DWD-Gebietsmittel · 1991–2020"));
  assert.ok(text.filter(t=>t.startsWith("Quelle DWD")).length>=1);
  assert.ok(text.some(t=>t.startsWith("Erstellt:")&&t.includes("Climate Dashboard Deutschland")));
  assert.equal(images.length,1);
});
test("snow selector retains shared years instead of resetting on station change",()=>{
  const html=fs.readFileSync("index.html","utf8");
  const body=html.slice(html.indexOf("function stationSnowPopulateYearPicker("),
    html.indexOf("function stationSnowDailyObjects("));
  assert.match(body,/const stationChanged=stationSnowYearStationId!==station.id/);
  assert.match(body,/const yearsAtStation=new Set\(available.map/);
  assert.match(body,/if\(!yearsAtStation.has\(selected\)\)stationSnowSelectedYears.delete\(selected\)/);
  assert.doesNotMatch(body,/stationSnowSelectedYears.clear\(\)/);
  assert.match(html,/DashboardExportHQ.renderChart/);
  assert.match(html,/DashboardExportHQ.composeCanvas/);
});
test("ICON hazard map has PDF and PNG controls from same map renderer",()=>{
  const page=fs.readFileSync("wettergefahren.html","utf8");
  const code=fs.readFileSync("wettergefahren_export.js","utf8");
  assert.match(page,/id="exportPng"/);
  assert.match(page,/id="exportPdf"/);
  assert.match(code,/async function renderExportCanvas/);
  assert.match(code,/async function makePDF/);
  assert.match(code,/async function makePNG/);
});
