import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const source=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
new Function(source);
const keys=["temp","rain","wind","pressure","sun","sunDaily"];
const ids=["mosmixTempChart","mosmixRainChart","mosmixWindChart",
 "mosmixPressureChart","mosmixSunChart","mosmixSunDailyChart"];
for(const key of keys){
  assert.equal((source.match(new RegExp('data-mosmix-export-chart="'+key+'"',"g"))||[]).length,3,
    "Each chart must have one PNG, PDF and SVG button: "+key);
}
assert.match(source,/button\.dataset\.mosmixExportFormat,button\.dataset\.mosmixExportChart/);
const start=source.indexOf("  function setMeteogramExportReady(");
const end=source.indexOf("  async function loadStationDetail(",start);
assert.ok(start>0 && end>start);
const code=source.slice(start,end);
const downloaded=[],pdfFiles=[],titles=[],cloneSpecs=[];
class FakeCanvas {
 constructor(width=720,height=310){this.width=width;this.height=height;this.drawCalls=[];}
 getContext(){
  const target=this;
  return {
    fillStyle:"",strokeStyle:"",font:"",
    fillRect(...args){target.drawCalls.push(["fillRect",...args])},
    fillText(...args){target.drawCalls.push(["fillText",...args]);titles.push(String(args[0]))},
    beginPath(){},moveTo(){},lineTo(){},stroke(){},
    drawImage(...args){target.drawCalls.push(["drawImage",...args])},
  };
 }
 toDataURL(){return "data:image/png;base64,QUJD"}
}
const sources=Object.fromEntries(ids.map((id,i)=>[id,new FakeCanvas(720,i===5?200:310)]));
const labelsByKey=[["Temperatur","Taupunkt"],["3-h-Niederschlagssumme","Bewölkung"],["Wind","12-h-Maximalböe"],["Luftdruck","Ausgeblendet"],["Sonnenschein letzte 1 h (min)","Globalstrahlung (kJ/m², 1 h)"],["Sonnenschein pro Tag (h)","Vergleich"]];
const buttons=keys.flatMap(key=>["png","pdf","svg"].map(format=>({dataset:{mosmixExportChart:key,mosmixExportFormat:format},disabled:true})));
const globals={
 document:{
  getElementById(id){
   if(sources[id])return sources[id];
   if(id==="mosmixDiagramPng"||id==="mosmixDiagramPdf")return globals.exportButtons[id];
   if(id==="mosmixDiagramRange")return {selectedOptions:[{textContent:"Ab jetzt · 3 Tage"}]};
   if(id==="mosmixExportStatus")return globals.status;
   return null;
  },
  querySelectorAll(selector){assert.equal(selector,"[data-mosmix-export-chart]");return buttons},
  createElement(tag){
   if(tag==="canvas")return new FakeCanvas();
   if(tag==="a")return {href:"",download:"",click(){downloaded.push({name:this.download,href:this.href})},remove(){}};
   throw Error("Unexpected DOM node: "+tag);
  },
  body:{appendChild(){}}
 },
 exportButtons:{mosmixDiagramPng:{disabled:true},mosmixDiagramPdf:{disabled:true}},
 status:{textContent:""},
 window:{
  MosmixVectorExport:{
    buildScene(_chart,info){titles.push(info.title,info.station,info.range);return {}},
    drawPdf(){return []},
    toSvg(){return "<svg/>"},
    downloadSvg(_svg,name){downloaded.push({name:name+".svg",href:"blob:mock"})}
   },
   jspdf:{jsPDF:class {
   constructor(){this.internal={pageSize:{getWidth:()=>297,getHeight:()=>210}};}
   setFont(){}setFontSize(){}setDrawColor(){}line(){}addPage(){}addImage(){}
   text(...args){titles.push(String(args[0]))}
   save(name){pdfFiles.push(name)}
  }},
  Chart:class{
   constructor(canvas,config){cloneSpecs.push(config);this.canvas=canvas;this.config=config}
   update(){}destroy(){}
  }
 },
 meteogramCharts:ids.map((id,i)=>({
  canvas:sources[id],
  config:{type:i===1?undefined:"line",options:{scales:{x:{min:0,max:80}}}},
  data:{labels:["Mi","Do","Fr"],datasets:[
   {type:"line",label:labelsByKey[i][0],data:[1,2,3]},
   {type:"line",label:labelsByKey[i][1],data:[5,6,7]}
  ]},
  options:{scales:{x:{min:5,max:36}}},
  scales:{x:{min:5,max:36},y:{min:0,max:50}},
  isDatasetVisible:index=>index===0
 })),
 currentDetail:{parameters:{TTT:[10,11]}},
 data:{issue_time:"2026-11-11T12:00:00Z",stations:[]},
 selectedStation:{name:"Frankfurt am Main"},
 selectedStationKey:"FFM",
 rainPeriod:3,gustPeriod:12,
 fmtTime:s=>"11.11.2026, 12:00 UTC",
 ensurePdfLibrary:async()=>{},
  ensureVectorExport:async()=>{},
 console:{warn(){},error(...x){throw Error("Unexpected export error: "+x.join(","))}}
};
const api=new Function(...Object.keys(globals),code+
 "\nreturn {setMeteogramExportReady,meteogramExportSections,vectorMeteogramEntries,meteogramExportMeta,exportSinglePng,exportSinglePdf,exportCombinedPng,exportCombinedPdf,downloadMeteogram};")(...Object.values(globals));
api.setMeteogramExportReady(true);
assert.ok(buttons.every(b=>!b.disabled));
assert.equal(globals.exportButtons.mosmixDiagramPdf.disabled,false);
assert.deepEqual(api.meteogramExportSections().map(x=>x.mosmixExportKey),keys.slice(0,5));
assert.deepEqual(api.vectorMeteogramEntries().map(x=>x.key),keys.slice(0,5));
assert.equal(api.meteogramExportSections("temp")[0].mosmixExportTitle,"Temperatur");
assert.equal(api.vectorMeteogramEntries("temp")[0].title,"Temperatur");
assert.equal(api.meteogramExportSections("sunDaily").length,1);
assert.equal(api.meteogramExportSections("rain")[0].mosmixExportTitle,"Niederschlag · 3 h");
assert.equal(api.meteogramExportSections("wind")[0].mosmixExportTitle,"Wind");
assert.equal(api.meteogramExportSections("sun")[0].mosmixExportTitle,"Stündlicher Sonnenschein");
const legendFilter=cloneSpecs.at(-1).options.plugins.legend.labels.filter;
assert.equal(legendFilter({datasetIndex:0}),true);
assert.equal(legendFilter({datasetIndex:1}),false);
globals.meteogramCharts[0].isDatasetVisible=()=>false;
assert.deepEqual(api.meteogramExportSections().map(x=>x.mosmixExportKey),keys.slice(1,5));
assert.deepEqual(api.vectorMeteogramEntries().map(x=>x.key),keys.slice(1,5));
assert.throws(()=>api.meteogramExportSections('temp'),/Keine sichtbaren/);
globals.meteogramCharts[0].isDatasetVisible=i=>i===0;
assert.equal(cloneSpecs.at(-1).data.datasets[1].hidden,true);
assert.equal(cloneSpecs.at(-1).options.scales.x.min,5);
assert.equal(cloneSpecs.at(-1).options.scales.x.max,36);
assert.equal(cloneSpecs.at(-1).options.devicePixelRatio,2);
assert.throws(()=>api.meteogramExportSections("unknown"),/Unbekanntes/);
await api.downloadMeteogram("png","temp");
await api.downloadMeteogram("pdf","rain");
await api.downloadMeteogram("png","sunDaily");
await api.downloadMeteogram("pdf","wind");
await api.downloadMeteogram("svg","pressure");
await api.downloadMeteogram("png");
await api.downloadMeteogram("pdf");
assert.equal(downloaded.length,4);
assert.match(downloaded[0].name,/_temp\.png$/);
assert.match(downloaded[1].name,/_sunDaily\.png$/);
assert.match(downloaded[2].name,/_pressure\.svg$/);
assert.match(downloaded[3].name,/\.png$/);
assert.ok(!downloaded[3].name.endsWith("_temp.png"));
assert.equal(pdfFiles.length,3);
assert.match(pdfFiles[0],/_rain\.pdf$/);
assert.match(pdfFiles[1],/_wind\.pdf$/);
assert.match(pdfFiles[2],/\.pdf$/);
assert.ok(titles.some(t=>t.includes("Ab jetzt · 3 Tage")));
assert.ok(titles.some(t=>t.includes("Frankfurt am Main")));
assert.ok(titles.some(t=>t.includes("Niederschlag · 3 h")));
assert.ok(titles.some(t=>t==="Wind"));
api.setMeteogramExportReady(false);
assert.ok(buttons.every(b=>b.disabled));
assert.equal(globals.exportButtons.mosmixDiagramPdf.disabled,true);
console.log("PASS: Six individual charts, five combined charts, visible comparisons, current ranges, high-res PNG, vector PDF and SVG.");
