"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("satellite_hd.js","utf8"),html=fs.readFileSync("satelliten.html","utf8");
const shell=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(ok,what,ms=3600){const end=Date.now()+ms;while(!ok()){if(Date.now()>end)throw Error("Timeout: "+what);await delay(15);}}
function setup(){
 const requests=[],els=new Map(),alerts={downloads:0,pdf:0,paintBorders:0,paintCities:0,paintIsobars:0},view={scale:1};
 class Element{
  constructor(id){this.id=id;this.value="";this.disabled=false;this.hidden=false;this.style={};this.children=[];this.listeners={};this.textContent="";this.attrs={};this.checked=false;}
  addEventListener(key,cb){this.listeners[key]=cb;}
  fire(key){this.listeners[key]?.();}
  replaceChildren(...items){this.children=items;}
  append(item){this.children.push(item);}
  getBoundingClientRect(){
   if(this.id==="satPictureFrame")return {left:0,right:1300,top:0,bottom:850,width:1300,height:850};
   if(this.id==="satImageStack"){const s=view.scale;return {left:650-650*s,right:650+650*s,top:425-425*s,bottom:425+425*s,width:1300*s,height:850*s};}
   return {left:0,right:1,top:0,bottom:1,width:1,height:1};
  }
 }
 for(const key of ["satHDTiles","satPictureFrame","satImageStack","satStillQuality","satHDStatus","satHDDownload","satHDPdf","satHDExportBorders","satHDExportCities","satHDExportIsobars","satIsobarSpacing","satSource","satProduct","satRegion"]){
  els.set(key,new Element(key));
 }
 els.get("satStillQuality").value="standard";
 els.get("satSource").value="mtgi1";els.get("satProduct").value="geocolour";els.get("satRegion").value="europe";
 els.get("satIsobarSpacing").value="5";
 const document={getElementById:id=>els.get(id),createElement(name){
  if(name==="canvas")return {width:0,height:0,getContext(){return {
   drawImage(){},save(){},restore(){},fillRect(){},fillText(){},beginPath(){},rect(){},clip(){},
   strokeText(){},strokeRect(){},moveTo(){},lineTo(){},stroke(){},measureText(t){return {width:t.length*10}},
   arc(){},fill(){}}},toBlob(cb){cb({size:12345})}};
  if(name==="a")return {click(){alerts.downloads++},remove(){},set href(v){},set download(v){}};
  throw Error("Unexpected element "+name);
 },body:{appendChild(){}}};
 class Image{
  constructor(){this.naturalWidth=0;this.onload=null;this.onerror=null;this.decoding="";this.style={};this.crossOrigin="";this.attrs={};}
  set src(value){this._src=value;if(!value)return;requests.push(value);setTimeout(()=>{if(!this._src)return;const params=new URL(value).searchParams;this.naturalWidth=+params.get("width");this.naturalHeight=+params.get("height");this.onload?.();},3);}
  get src(){return this._src}
  removeAttribute(name){if(name==="src")this._src="";}
 }
 const context={document,Image,window:{},URLSearchParams,URL:{createObjectURL:()=>"blob:test",revokeObjectURL(){}},Date,Math,Number,String,Array,Map,Set,Promise,Error,setTimeout,clearTimeout};
 context.window.SatelliteOverlay={
  paintBorders(){alerts.paintBorders++},paintCities(){alerts.paintCities++}
 };
 context.window.SatelliteIsobars={
  exportAt:async(time,place,spacing)=>({satelliteUTC:time,validUTC:time,spacing,region:place})
 };
 context.window.SatelliteMapExport={
  paintIsobars(){alerts.paintIsobars++},
  renderPDF:async()=>({blob:{size:2000},name:"hd_isobaren.pdf"}),
  download(){alerts.pdf++}
 };
 vm.runInNewContext(source,context,{timeout:2000});
 return {requests,els,context,view,alerts};
}
const UTC="2026-11-12T17:20:00Z";
function live(){return {time:UTC,region:"europe",source:"mtgi1",product:"geocolour",layer:"mtg_fd:rgb_geocolour",ready:true,cached:false};}
test("HD module is published and standard still uses verified 800px first",()=>{
 assert.ok(shell.includes("  satellite_hd.js\n"));
 assert.ok(shell.includes("node --check _site/satellite_hd.js"));
 assert.ok(html.includes('id="satStillQuality"'));
 assert.ok(html.includes('id="satHDDownload"'));
 assert.ok(html.includes('id="satHDTiles"'));
 assert.ok(html.includes('src="satellite_hd.js?'));
 const still=fs.readFileSync("satelliten.js","utf8");
 assert.match(still,/const widths=\[800,400,320\]/);
 assert.match(still,/image\.naturalWidth\+" × "\+image\.naturalHeight/);
 assert.match(still,/SatelliteHD\?\.sync/);
 const zoom=fs.readFileSync("satellite_view_options.js","utf8");
 assert.match(zoom,/SatelliteHD\?\.viewChanged/);
 assert.doesNotThrow(()=>new vm.Script(source));
});
test("HD bounding boxes are exact geographic fractions, top row is north",()=>{
 const f=setup().context.window.SatelliteHD.boundsForTile;
 const eps=1e-9;
 const bbox=[-27,24,49,73];
 const t=f(0,0,3,2,bbox),u=f(2,1,3,2,bbox);
 for(const [a,b] of [[t[0],-27],[t[1],48.5],[t[2],-27+76/3],[t[3],73],
                       [u[0],-27+2*76/3],[u[1],24],[u[2],49],[u[3],48.5]])
 assert.ok(Math.abs(a-b)<eps,"Unexpected WMS bbox coordinate "+a+" expected "+b);
});
test("HD requests independent georeferenced tiles and limits parallel requests",async()=>{
 const a=setup(),q=a.els.get("satStillQuality");q.value="hd";
 a.context.window.SatelliteHD.sync(live());
 await until(()=>a.requests.length===6,"six HD visible WMS tiles");
 await until(()=>a.els.get("satHDTiles").children.length===6,"six HD images decoded");
 const req=a.requests.map(x=>new URL(x));
 assert.ok(req.every(x=>x.searchParams.get("layers")==="mtg_fd:rgb_geocolour"&&x.searchParams.get("time")===UTC));
 assert.ok(req.every(x=>+x.searchParams.get("width")<=700));
 assert.ok(new Set(req.map(x=>x.searchParams.get("bbox"))).size===6,"Tiles must have different lat/lon bounds");
 assert.match(a.els.get("satHDStatus").textContent,/2048 × 1339 px/);
 assert.equal(a.els.get("satHDTiles").hidden,false);
});
test("Standard zoom asks smaller geobboxes; 4K requests 4096 raster without time shift",async()=>{
 const a=setup(),q=a.els.get("satStillQuality");
 a.context.window.SatelliteHD.sync(live());
 await delay(220);assert.equal(a.requests.length,0,"Standard 1x makes no tile calls");
 a.view.scale=3.5;a.context.window.SatelliteHD.viewChanged({scale:3.5});
 await until(()=>a.requests.length>0,"zoomed geographic crops");
 assert.ok(a.requests.every(url=>new URL(url).searchParams.get("bbox")!=="-27,24,49,73"));
 assert.ok(a.requests.length<20,"no full-disk tile preloading in zoom mode");
 q.value="4k";q.fire("change");a.view.scale=1;
 a.context.window.SatelliteHD.viewChanged({scale:1});
 await until(()=>a.requests.some(url=>+new URL(url).searchParams.get("width")>=1000),"4K tile");
 await until(()=>a.els.get("satHDTiles").children.length===12,"4K Europe tiles",6000);
 assert.match(a.els.get("satHDStatus").textContent,/4096 × 2678 px/);
});
test("Full 4K PNG is assembled only when every tile exists",async()=>{
 const a=setup(),q=a.els.get("satStillQuality");q.value="4k";
 a.context.window.SatelliteHD.sync(live());
 await until(()=>a.els.get("satHDTiles").children.length===12,"4K loaded");
 a.els.get("satHDDownload").fire("click");
 await until(()=>a.alerts.downloads===1,"real 4K export");
 assert.match(a.els.get("satHDStatus").textContent,/4096 × 2678 px/);
 a.context.window.SatelliteHD.cancel("Film");
 assert.equal(a.els.get("satHDTiles").hidden,true);
 assert.equal(a.els.get("satHDTiles").children.length,0);
});

test("HD raster and vector PDF apply chosen layers only after all exact-time tiles are complete",async()=>{
 const a=setup(),q=a.els.get("satStillQuality");q.value="hd";
 a.els.get("satHDExportBorders").checked=true;
 a.els.get("satHDExportCities").checked=true;
 a.els.get("satHDExportIsobars").checked=true;
 a.context.window.SatelliteHD.sync(live());
 await until(()=>a.els.get("satHDTiles").children.length===6,"HD image ready");
 await a.context.window.SatelliteHD.exportImage("png");
 assert.equal(a.alerts.downloads,1);
 assert.equal(a.alerts.paintBorders,1);
 assert.equal(a.alerts.paintCities,1);
 assert.equal(a.alerts.paintIsobars,1);
 await a.context.window.SatelliteHD.exportImage("pdf");
 assert.equal(a.alerts.pdf,1);
 assert.equal(a.alerts.paintBorders,2);
 assert.equal(a.alerts.paintCities,2);
 assert.equal(a.alerts.paintIsobars,1,"PDF has editable isobars, never pre-rasterizes them");
 assert.ok(html.includes('id="satHDPdf"'));
 for(const id of ["satHDExportBorders","satHDExportCities","satHDExportIsobars"])
  assert.ok(html.includes('id="'+id+'"'));
});
test("Non-divisible edge tile geographic coordinates match exact pixel raster",async()=>{
 const a=setup(),q=a.els.get("satStillQuality");q.value="hd";
 a.context.window.SatelliteHD.sync(live());
 await until(()=>a.requests.length===6,"all requests");
 const tiles=a.requests.map(t=>{
  const url=new URL(t),b=url.searchParams.get("bbox").split(",").map(Number);
  return {b,w:Number(url.searchParams.get("width")),h:Number(url.searchParams.get("height"))};
 });
 const north=tiles.filter(t=>Math.abs(t.b[3]-73)<1e-8).sort((x,y)=>x.b[0]-y.b[0]);
 assert.equal(north.reduce((n,t)=>n+t.w,0),2048);
 assert.equal(north[0].w,683);
 assert.equal(north.at(-1).w,682);
 for(let i=1;i<north.length;i++){
  assert.ok(Math.abs(north[i].b[0]-north[i-1].b[2])<1e-10);
  const leftRate=(north[i-1].b[2]-north[i-1].b[0])/north[i-1].w;
  const rightRate=(north[i].b[2]-north[i].b[0])/north[i].w;
  assert.ok(Math.abs(leftRate-rightRate)<1e-10,"No geographic jump at seam");
 }
});
