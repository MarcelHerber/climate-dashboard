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
