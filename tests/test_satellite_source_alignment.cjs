"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
function fakeDOM(){
 const listeners=new Map();
 class Element{
  constructor(id){this.id=id;this.hidden=true;this.checked=false;this.value="1";this.textContent="";this.children=[];this.style={};this.src="";}
  addEventListener(type,fn){listeners.set(this.id+":"+type,fn)}
  replaceChildren(...items){this.children=items}
  removeAttribute(name){if(name==="src")this.src=""}
 }
 const elements=new Map();
 const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)};
 const document={getElementById:get,createElement(name){
  if(name!=="canvas")throw Error("Unexpected createElement: "+name);
  return {width:0,height:0,getContext:()=>({drawImage(){}}),toDataURL:()=>"data:image/png;base64,AA=="};
 }};
 class FakeImage{
  constructor(){this.naturalWidth=0;this.crossOrigin="";this.decoding="";this.onload=null;this.onerror=null;this.style={};this.complete=false;}
  set src(url){this._src=url;this.complete=false;setTimeout(()=>{this.naturalWidth=256;this.complete=true;this.onload?.();},0)}
  get src(){return this._src}
 }
 return {document,get,FakeImage,listeners};
}
async function waitFor(predicate,description){
 for(let i=0;i<120;i++){if(predicate())return;await new Promise(r=>setTimeout(r,10));}
 throw Error("Timeout waiting for "+description);
}
test("LI monitor's real root-level lightning schema supplies matched 5/15 minute overlays",async()=>{
 const ui=fakeDOM(),requests=[];
 ui.get("satShowLightning").checked=true;
 ui.get("satLightningWindow").value="3";
 ui.get("satFilmStage").hidden=true;
 ui.get("satRegion").value="europe";ui.get("satSource").value="mtgi1";
 const rounded=Math.floor(Date.now()/300000)*300000;
 const latest=new Date(rounded-10*60000).toISOString();
 const times=Array.from({length:5},(_,i)=>new Date(rounded-(30-i*5)*60000).toISOString());
 const report={generated_at:new Date().toISOString(),capabilities_ok:true,
  lightning:{layer:"mtg_fd:li_afa",map_ok:true,available_times:times,latest_verified_time:times.at(-1)}};
 class ImageWithUrls extends ui.FakeImage{
  set src(url){requests.push(url);super.src=url}
  get src(){return super.src}
 }
 const context={window:{},document:ui.document,Image:ImageWithUrls,URLSearchParams,Date,Math,Set,Number,String,Promise,setTimeout,clearTimeout,
  fetch:async()=>({ok:true,json:async()=>report})};
 vm.runInNewContext(fs.readFileSync("satellite_lightning.js","utf8"),context);
 await context.window.SatelliteLightning.sync({time:latest,region:"europe",source:"mtgi1"});
 await waitFor(()=>!ui.get("satLightningOverlay").hidden,"LI overlay");
 assert.equal(ui.get("satLightningOverlay").children.length,3);
 assert.equal(requests.length,3);
 assert.ok(requests.every(url=>url.includes("mtg_fd%3Ali_afa")&&url.includes("time=")));
 assert.match(ui.get("satLightningStatus").textContent,/15 Minuten/);
});
test("RainViewer's current hashed radar paths are accepted and rendered at matched UTC",async()=>{
 const ui=fakeDOM(),requested=[];
 ui.get("satShowRadar").checked=true;ui.get("satRadarOpacity").value="70";
 ui.get("satFilmStage").hidden=true;
 const stamp=Math.floor((Date.now()-10*60000)/600000)*600;
 const frame={time:stamp,path:"/v2/radar/b88a4c65784c"};
 const report={host:"https://tilecache.rainviewer.com",radar:{past:[frame]}};
 class ImageWithUrls extends ui.FakeImage{
  set src(url){requested.push(url);super.src=url}
  get src(){return super.src}
 }
 const context={window:{},document:ui.document,Image:ImageWithUrls,URLSearchParams,Date,Math,Number,Array,
  setTimeout,clearTimeout,fetch:async()=>({ok:true,json:async()=>report})};
 vm.runInNewContext(fs.readFileSync("satellite_radar.js","utf8"),context);
 await context.window.SatelliteRadar.sync({
  time:new Date((stamp+10*60)*1000).toISOString(),region:"germany",source:"mtgi1"});
 assert.equal(ui.get("satRadarOverlay").hidden,false);
 assert.ok(ui.get("satRadarOverlay").src.startsWith("data:image/png"));
 assert.ok(requested.length>0&&requested.every(u=>u.includes("/v2/radar/b88a4c65784c/")));
 assert.match(ui.get("satRadarStatus").textContent,/RainViewer-Radarkomposit/);
});
test("No radar or LI data are fabricated if verified inputs are absent",()=>{
 const radar=fs.readFileSync("satellite_radar.js","utf8");
 const li=fs.readFileSync("satellite_lightning.js","utf8");
 assert.match(radar,/Kein Radarbild innerhalb der letzten 20 Minuten/);
 assert.match(li,/entry\.map_ok/);
 assert.match(li,/info\.lightning\|\|info\.products\?\.lightning/);
});
