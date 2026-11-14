"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

function harness(){
 const window={};
 vm.runInNewContext(fs.readFileSync("t850_vector_export.js","utf8"),{
  window,Number,Object,Array,Math,Error,String,console
 },{timeout:2500});
 const a=window.T850VectorExport;
 assert.ok(a);
 const chart={
  data:{
   labels:["13.11. 00Z","13.11. 06Z","13.11. 12Z","13.11. 18Z","14.11. 00Z"],
   datasets:[
    {label:"Member 1",data:[null,-1,2,null,4],borderColor:"rgba(71,85,105,.2)",spanGaps:false},
    {label:"Member 2",data:[-2,-1,3,4,5],borderColor:"#475569"},
    {label:"Ensemble-Mittel",data:[-1,0,1,2,3],borderColor:"#2563eb",borderWidth:3},
    {label:"1991–2020 ERA5",data:[0,0,0,0,0],borderColor:"#c62828",borderWidth:3}
   ]
  },scales:{x:{min:0,max:4},y:{min:-3,max:6}},
  isDatasetVisible(i){return i!==1}
 };
 const info={title:"GEFS & T850",axis:"Temperatur 850 hPa [°C]",
  metadata:["Ort: Frankfurt","Parameter: T850 [°C]","Auswertung: Member",
  "Ansicht: GEFS","Zeitachse: UTC (Z)","Quelle: Open-Meteo",
  "Erstellt: 13.11.2026"]};
 return {a,chart,info};
}
test("SVG uses true named Inkscape layers, no images, and independent member paths",()=>{
 const {a,chart,info}=harness();
 const scene=a.buildScene(chart,info);
 assert.equal(scene.series.length,3,"Hidden member must not export");
 assert.equal(scene.series[0].label,"Member 1");
 assert.equal(scene.series[0].points.length,1,"Null data must not be drawn as zero");
 const svg=a.toSvg([scene]);
 assert.match(svg,/xmlns:inkscape=/);
 assert.match(svg,/inkscape:groupmode="layer"/);
 assert.match(svg,/inkscape:label="GEFS &amp; T850 – Member 1"/);
 assert.match(svg,/inkscape:label="GEFS &amp; T850 – Ensemble-Mittel"/);
 assert.match(svg,/inkscape:label="GEFS &amp; T850 – 1991–2020 ERA5"/);
 assert.doesNotMatch(svg,/<image\b|data:image|<canvas/);
 assert.match(svg,/13.11. 06Z/);
 assert.match(svg,/Erstellt: 13.11.2026/);
 assert.match(svg,/clip-path="url\(#plotclip0\)"/);
 assert.ok(svg.match(/<path /g).length>=5);
});
test("four-panel SVG retains unique group/clip identities and one panel per chart",()=>{
 const {a,chart,info}=harness();
 const scene=a.buildScene(chart,info);
 const svg=a.toSvg([scene,scene,scene,scene,scene]);
 assert.match(svg,/height="4650"/);
 assert.equal((svg.match(/<clipPath/g)||[]).length,5);
 assert.match(svg,/id="panel4_series_0_Member_1"/);
 assert.match(svg,/plotclip4/);
});
test("vector PDF uses separate line commands and never embeds chart bitmaps",()=>{
 const {a,chart,info}=harness(),scene=a.buildScene(chart,info);
 const paths=[],words=[];
 const doc={
  internal:{pageSize:{getWidth(){return 420},getHeight(){return 297}}},
  setFillColor(){},rect(){},setFont(){},setFontSize(){},setTextColor(){},
  text(t){words.push(t)},setLineWidth(){},setDrawColor(){},line(){},
  setLineDashPattern(){},
  lines(commands,x,y){paths.push({commands,x,y})},
  addImage(){throw Error("Raster image embedded in vector PDF!")}
 };
 assert.equal(a.drawPdf(doc,scene),3);
 assert.ok(paths.length>=3,"Each chart curve must be an independent PDF path");
 assert.ok(paths.every(p=>p.commands.every(c=>c.length===2&&c.every(Number.isFinite))));
 assert.ok(words.some(t=>String(t).includes("Erstellt:")));
 assert.ok(words.some(t=>String(t).includes("UTC (Z)")));
});
test("out-of-range ensemble values are clipped to published axes, not moved",()=>{
 const {a,chart,info}=harness();
 chart.data.datasets=[{label:"Hauptlauf",data:[-200,0,1,2,200],borderColor:"#111827"}];
 const scene=a.buildScene(chart,info);
 const paths=scene.series[0].points;
 assert.ok(paths.length>0);
 for(const seg of paths)for(const p of seg){
  assert.ok(p[0]>=115-1e-5 && p[0]<=1325+1e-5);
  assert.ok(p[1]>=259-1e-5 && p[1]<=802+1e-5);
 }
 assert.equal(chart.data.datasets[0].data[0],-200);
});
test("source view stays untouched and missing charts do not produce misleading PDF",()=>{
 const {a,chart,info}=harness(),copy=JSON.stringify(chart.data);
 a.buildScene(chart,info);
 assert.equal(JSON.stringify(chart.data),copy);
 assert.throws(()=>a.buildScene({data:{datasets:[]},scales:{}},info),/Diagramm/);
 assert.throws(()=>a.toSvg([]),/Keine Diagramme/);
});

test("percentile envelope edges have distinct named vector layers",()=>{
 const {a,chart,info}=harness();
 chart.data.datasets=[
  {label:"10.–90. Perzentil",data:[0,1,1,2,3],borderColor:"transparent"},
  {label:"10.–90. Perzentil",data:[2,2,3,4,5],borderColor:"transparent"},
  {label:"25.–75. Perzentil",data:[1,1,2,2,3],borderColor:"transparent"},
  {label:"25.–75. Perzentil",data:[2,3,3,4,4],borderColor:"transparent"}
 ];
 chart.isDatasetVisible=()=>true;
 const scene=a.buildScene(chart,info);
 assert.deepEqual(Array.from(scene.series,s=>s.label),
  ["10. Perzentil","90. Perzentil","25. Perzentil","75. Perzentil"]);
 const svg=a.toSvg([scene]);
 for(const name of ["10.","90.","25.","75."])
  assert.ok(svg.includes(name+" Perzentil"),name);
});

test("one renderer keeps DWD / ECMWF data sources and units in scientific vector exports",()=>{
 const {a,chart,info}=harness();
 const input={...info,title:"DWD Schneehöhe",axis:"Schneehöhe [cm]",
  subtitle:"Stationsmessungen und Klimareferenz",source:"Quelle: DWD Climate Data Center"};
 const original=JSON.stringify(chart.data);
 const scene=a.buildScene(chart,input);
 const svg=a.toSvg([scene]);
 assert.match(svg,/DWD Climate Data Center/);
 assert.match(svg,/Schneehöhe \[cm\]/);
 assert.match(svg,/Stationsmessungen und Klimareferenz/);
 assert.doesNotMatch(svg,/Quelle: Open-Meteo/);
 assert.equal(JSON.stringify(chart.data),original);
 const words=[];
 const doc={internal:{pageSize:{getWidth(){return 420},getHeight(){return 297}}},
  setFillColor(){},rect(){},setFont(){},setFontSize(){},setTextColor(){},
  text(t){words.push(String(t))},setLineWidth(){},setDrawColor(){},line(){},
  setLineDashPattern(){},lines(){},addImage(){throw Error("Raster PDF")}
 };
 a.drawPdf(doc,scene);
 assert.ok(words.some(t=>t.includes("DWD Climate Data Center")));
 assert.ok(words.some(t=>t.includes("Schneehöhe [cm]")));
});

test("true 5–95 and 25–75 percentile fill uses the original 0.17/0.29 alpha",()=>{
 const {a,chart,info}=harness();
 chart.data.datasets=[
  {label:"_90% min",data:[-2,-3,-3,-4,-4],borderColor:"transparent"},
  {label:"_90% max",data:[3,4,4,3,3],borderColor:"transparent",
   fill:{target:"-1",above:"rgba(71,126,183,.18)",below:"rgba(71,126,183,.18)"}},
  {label:"_50% min",data:[-1,-2,-2,-2,-2],borderColor:"transparent"},
  {label:"_50% max",data:[1,2,2,2,2],borderColor:"transparent",
   fill:{target:"-1",above:"rgba(71,126,183,.30)",below:"rgba(71,126,183,.30)"}},
  {label:"EPS-Mittel",data:[0,0,0,0,0],borderColor:"#d62828"}
 ];
 chart.isDatasetVisible=()=>true;
 const original=JSON.stringify(chart.data);
 const scene=a.buildScene(chart,info);
 assert.equal(scene.fills.length,2);
 assert.ok(scene.fills.every(f=>f.areas.length>=1));
 assert.equal(scene.fills[0].areas[0].opacity,.18);
 assert.equal(scene.fills[1].areas[0].opacity,.30);
 assert.equal(scene.fills[0].areas[0].hex.toLowerCase(),"#477eb7");
 const svg=a.toSvg([scene]);
 assert.match(svg,/Fläche: _90% max → _90% min/);
 assert.match(svg,/fill-opacity="0.18"/);
 assert.match(svg,/fill-opacity="0.3"/);
 assert.doesNotMatch(svg,/<image\b/);
 assert.equal(JSON.stringify(chart.data),original);
});
test("warm and cold 1991–2020 anomaly polygons cross the mean without bridging missing days",()=>{
 const {a,chart,info}=harness();
 chart.data.labels=["1","2","3","4","5","6","7","8"];
 chart.scales.x={min:0,max:7};
 chart.scales.y={min:-5,max:5};
 chart.data.datasets=[
  {label:"1991–2020 · Mittel",data:[0,0,0,0,0,0,0,0],borderColor:"#333333"},
  {label:"2026",data:[-3,3,2,null,1,-1,-2,2],borderColor:"#c64f44",
   fill:{target:0,above:"rgba(222,44,41,0.58)",below:"rgba(31,96,217,0.58)"}}
 ];
 chart.isDatasetVisible=()=>true;
 const scene=a.buildScene(chart,info);
 assert.equal(scene.fills.length,1);
 const areas=scene.fills[0].areas;
 assert.ok(areas.some(o=>o.side==="above"&&o.hex==="#de2c29"));
 assert.ok(areas.some(o=>o.side==="below"&&o.hex==="#1f60d9"));
 assert.ok(areas.some(o=>o.points.some(p=>Math.abs(p[0]-(115+1210/7/2))<0.5)),
    "Crossing between first two days must be interpolated exactly");
 // Every drawn polygon must come from consecutive non-missing original days.
 const x3=115+1210*3/7, x4=115+1210*4/7;
 assert.ok(areas.every(o=>o.points.every(p=>p[0]<=x3+1e-5||p[0]>=x4-1e-5)),
    "No arbitrary bridge over missing data");
 assert.ok(areas.every(o=>o.points.every(p=>p[0]>=115-1e-5&&p[0]<=1325+1e-5
   &&p[1]>=259-1e-5&&p[1]<=802+1e-5)));
 const svg=a.toSvg([scene]);
 assert.match(svg,/fill-opacity="0.58"/);
 assert.match(svg,/data-side="above"/);
 assert.match(svg,/data-side="below"/);
});
test("filled area is hidden if reference dataset is not visible",()=>{
 const {a,chart,info}=harness();
 chart.data.datasets=[
  {label:"Baseline",data:[0,0,0,0,0]},
  {label:"2026",data:[1,2,3,2,1],fill:{target:0,above:"#ff0000",below:"#0000ff"}}
 ];
 chart.isDatasetVisible=i=>i===1;
 const scene=a.buildScene(chart,info);
 assert.equal(scene.fills.length,0);
});
test("vector PDF produces independent filled polygons with non-opaque jsPDF GState",()=>{
 const {a,chart,info}=harness();
 chart.data.datasets=[
  {label:"Base",data:[0,0,0,0,0],borderColor:"#999999"},
  {label:"2026",data:[-1,1,2,-2,3],borderColor:"#ed2233",
   fill:{target:0,above:"rgba(222,44,41,.58)",below:"rgba(31,96,217,.58)"}}
 ];
 chart.isDatasetVisible=()=>true;
 const scene=a.buildScene(chart,info),ops=[];
 const doc={
  GState:class{constructor(v){ops.push(["gstate",v]);}},
  internal:{pageSize:{getWidth(){return 420},getHeight(){return 297}}},
  saveGraphicsState(){ops.push(["save"])},
  restoreGraphicsState(){ops.push(["restore"])},
  setGState(){ops.push(["setalpha"])},
  setFillColor(){},rect(){},setFont(){},setFontSize(){},setTextColor(){},text(){},
  setLineWidth(){},setDrawColor(){},line(){},setLineDashPattern(){},lines(){},
  path(commands,mode){ops.push([mode,commands])},
  addImage(){throw Error("Raster embedded")}
 };
 a.drawPdf(doc,scene);
 const fills=ops.filter(o=>o[0]==="F");
 assert.ok(fills.length>=2);
 assert.ok(fills.every(o=>o[1].at(-1).op==="h"),"PDF polygons must be closed");
 assert.ok(ops.some(o=>o[0]==="gstate"&&o[1].opacity===.58));
 assert.equal(ops.filter(o=>o[0]==="save").length,fills.length);
 assert.equal(ops.filter(o=>o[0]==="restore").length,fills.length);
});
