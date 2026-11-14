"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const datum=JSON.parse(fs.readFileSync("tests/fixtures/noaa_wpc_verified_20261114.json","utf8"));
const REAL_UTC=datum.valid_utc;
const now=Date.parse(REAL_UTC)+2*3600000;
const sat=new Date(now).toISOString().replace(".000Z","Z");
const later=new Date(now+600000).toISOString().replace(".000Z","Z");
class Clock extends Date{static now(){return now;}}
const sources=["satellite_isobar_geometry.js","satellite_map_export.js",
 "satellite_noaa_fronts.js","satellite_film_export.js"].map(p=>fs.readFileSync(p,"utf8"));
function fixture(record=datum){
 const strokes=[],texts=[];
 class El {
  constructor(id){this.id=id;this.attrs={};this.children=[];this.disabled=false;
   this.checked=id==="satShowWpcFronts";this.value=id==="satSource"?"mtgi1":"atlantic";
   this.textContent="";this.listeners={};}
  setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}
  get hidden(){return Object.hasOwn(this.attrs,"hidden");}
  replaceChildren(){this.children=[];}appendChild(el){this.children.push(el);}
  addEventListener(name,cb){this.listeners[name]=cb;}
 }
 const ids=["satWpcFrontSvg","satShowWpcFronts","satWpcFrontStatus","satWpcFrontUTC",
  "satWpcFrontSource","satRegion","satSource"];
 const nodes=new Map(ids.map(x=>[x,new El(x)]));
 nodes.get("satWpcFrontSvg").setAttribute("hidden","");
 const ctx={
  save(){},restore(){},beginPath(){},rect(){},clip(){},moveTo(){},lineTo(){},
  fillRect(){},strokeRect(){},drawImage(){},setLineDash(a){this.dash=[...a];},
  stroke(){strokes.push({color:this.strokeStyle,width:this.lineWidth,dash:this.dash||[]});},
  fillText(t){texts.push(String(t));},strokeText(t){texts.push(String(t));},
  measureText(t){return {width:String(t).length*7};},
  getImageData(x,y,w,h){return {data:new Uint8ClampedArray(w*h*4).fill(127)}}
 };
 const canvas=()=>({width:0,height:0,getContext(){return ctx;},
  toDataURL(){return "data:image/jpeg;base64,"+Buffer.from([255,216,255,217]).toString("base64");},
  toBlob(cb){cb(new Blob(["test-front-raster"],{type:"image/png"}));}
 });
 const document={getElementById:id=>nodes.get(id)||null,
  createElementNS:(ns,tag)=>new El(tag),
  createElement:()=>canvas()};
 const window={},sandbox={window,document,Blob,TextEncoder,Uint8Array,
  Uint8ClampedArray,ArrayBuffer,Date:Clock,URL,Intl,Math,Number,Object,String,
  console,atob:s=>Buffer.from(s,"base64").toString("binary"),
  setTimeout,clearTimeout,
  fetch:async()=>({ok:true,json:async()=>record})};
 for(const source of sources)vm.runInNewContext(source,sandbox,{timeout:5000});
 return {window,nodes,strokes,texts};
}
const pause=()=>new Promise(resolve=>setTimeout(resolve,20));
function pressure(time=sat){
 return {satelliteUTC:time,validUTC:time,runUTC:REAL_UTC,
  method:"Test: real source geometry with deterministic ECMWF mock",
  region:"atlantic",spacing:5,contours:[{hpa:1015,lines:[
   [[-63,48],[-61,49],[-59,50],[-57,51],[-55,52],[-53,53],[-51,54],[-49,55]]]}]};
}
function options(fronts,time=sat){
 return {image:{naturalWidth:240,naturalHeight:140},overlay:pressure(time),
  fronts,region:"atlantic",regionName:"Nordatlantik",product:"geocolour",
  productName:"GeoColour",credit:"EUMETSAT"};
}
test("Immutable fixture retains real WPC coordinate provenance, 46 lines and all known types",()=>{
 assert.equal(datum.provider,"NOAA WPC");
 assert.equal(datum.status,"verified");
 assert.equal(datum.front_source_format,"CODSUS-HIRES");
 assert.equal(datum.coordinate_reference_system,"EPSG:4326");
 assert.equal(datum.features.length,46);
 assert.deepEqual(Object.keys(Object.groupBy(datum.features,f=>f.properties.front_type)).sort(),
  ["cold","occluded","stationary","warm"]);
});
test("Satellite SVG and export use identical real NOAA longitude/latitude polylines",async()=>{
 const f=fixture();await pause();
 const api=f.window.SatelliteNOAAFronts;
 api.sync({time:sat,region:"atlantic",source:"mtgi1"});
 const snapshot=api.exportAt(sat,"atlantic");
 assert.ok(snapshot&&snapshot.features.length>=5);
 assert.equal(f.nodes.get("satWpcFrontSvg").children.length,snapshot.features.length*2);
 const first=snapshot.features[0];
 const xy=api.project(first.coords[0],[-70,15,35,75]);
 assert.match(f.nodes.get("satWpcFrontSvg").children[1].attrs.d,
  new RegExp("^M"+xy[0].toFixed(2)+" "+xy[1].toFixed(2)));
 assert.equal(f.window.SatelliteMapExport.frontFeatures(snapshot,"atlantic",sat).length,
  snapshot.features.length);
 f.nodes.get("satShowWpcFronts").checked=false;
 assert.equal(api.exportAt(sat,"atlantic"),null,"Deselected map layer must not enter exports");
 f.nodes.get("satShowWpcFronts").checked=true;
 assert.equal(api.exportAt(sat,"germany"),null,"Never fabricate a German WPC front");
 assert.equal(api.exportAt(new Date(now+24*3600000).toISOString(),"atlantic"),null,
  "Never project stale NOAA fronts on an unrelated satellite date");
});
test("Canvas PNG and PDF use actual NOAA data; PDF leaves paths editable and independent",async()=>{
 const f=fixture();await pause();
 const api=f.window.SatelliteNOAAFronts;api.sync({time:sat,region:"atlantic",source:"mtgi1"});
 const fronts=api.exportAt(sat,"atlantic"),exp=f.window.SatelliteMapExport;
 const png=await exp.renderPNG(options(fronts));
 assert.match(png.name,/_isobaren_noaa_fronten\.png$/);
 assert.equal(png.blob.type,"image/png");
 assert.ok(f.strokes.some(x=>x.color==="#48a8ff"||x.color==="#ff6262"||
  x.color==="#ce77f9"||x.color==="#ec73b6"));
 const pdf=await exp.renderPDF(options(fronts));
 const data=Buffer.from(await pdf.blob.arrayBuffer()).toString("latin1");
 assert.match(pdf.name,/_isobaren_noaa_fronten\.pdf$/);
 assert.match(data,/% NOAA WPC analyzed frontal vectors/);
 assert.match(data,/\/Subtype \/Image/);
 assert.match(data,/\bm\n/,"PDF vector lines use move-to commands, not embedded raster paths");
 assert.match(data,/\bl\n/,"PDF vector front segments remain separately selectable");
 assert.match(data,/\bRG/,"PDF front vectors specify independent stroke colors");
 assert.ok((data.match(/\nS\nQ/g)||[]).length>=fronts.features.length,
  "Each NOAA frontline must be a separate PDF stroke operation");
 assert.ok(data.includes("NOAA WPC Analyse"));
});
test("Provenance and UTC mismatches fail before any front vector can be exported",async()=>{
 const f=fixture();await pause();
 const api=f.window.SatelliteNOAAFronts;api.sync({time:sat,region:"atlantic",source:"mtgi1"});
 const snapshot=api.exportAt(sat,"atlantic"),ex=f.window.SatelliteMapExport;
 assert.ok(snapshot);
 for(const patch of [
  {source_url:"https://fake.example/fronts"},{provider:"DWD"},
  {coordinate_reference_system:"EPSG:3857"},{region:"germany"},
  {satelliteUTC:later},{valid_utc:"2026-11-12T00:00Z"}
 ]){
  assert.throws(()=>ex.frontFeatures({...snapshot,...patch},"atlantic",sat),/NOAA-Fronten/);
 }
 assert.throws(()=>ex.frontFeatures({...snapshot,features:[
  {type:"cold",coords:[[-200,50],[-45,55]]}]},"atlantic",sat),/koordinate/);
});
test("Animated GIF paints same true NOAA lines per UTC frame, and skips absent snapshots",async()=>{
 const f=fixture();await pause();
 const api=f.window.SatelliteNOAAFronts;api.sync({time:sat,region:"atlantic",source:"mtgi1"});
 const first=api.exportAt(sat,"atlantic"),second=api.exportAt(later,"atlantic");
 const input={frames:[{time:sat,img:{naturalWidth:240,naturalHeight:140}},
   {time:later,img:{naturalWidth:240,naturalHeight:140}}],
  isobarOverlays:[pressure(sat),pressure(later)],frontOverlays:[first,second],
  region:"atlantic",product:"geocolour",productName:"GeoColour",credit:"EUMETSAT",
  width:160,delayMs:400};
 const gif=await f.window.SatelliteFilmExport.exportGIF(input);
 assert.equal(gif.blob.type,"image/gif");
 assert.equal(Buffer.from(await gif.blob.arrayBuffer()).subarray(0,6).toString(),"GIF89a");
 assert.ok(f.strokes.some(x=>x.color==="#48a8ff"||x.color==="#ff6262"||
  x.color==="#ce77f9"||x.color==="#ec73b6"));
 assert.ok(f.texts.some(t=>t.includes("NOAA WPC")));
 const bad={...second,satelliteUTC:sat};
 await assert.rejects(f.window.SatelliteFilmExport.exportGIF({...input,frontOverlays:[first,bad]}),
  /NOAA-Fronten/);
 const noFront=await f.window.SatelliteFilmExport.exportGIF({...input,frontOverlays:[null,null]});
 assert.equal(noFront.blob.type,"image/gif","No fabricated fronts when official source is absent");
});
