"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("satellite_fullhd_film.js","utf8");
const encoder=fs.readFileSync("satellite_film_export.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");
function harness(){
 const requests=[],captures=[],state={active:0,maxActive:0};
 class FakeImage{
  constructor(){this.naturalWidth=0;this.naturalHeight=0;this.onload=null;this.onerror=null;this.style={};}
  set src(value){
   this._src=value;if(!value)return;
   const url=new URL(value),w=Number(url.searchParams.get("width")),h=Number(url.searchParams.get("height"));
   requests.push(url);state.active++;state.maxActive=Math.max(state.active,state.maxActive);
   setTimeout(()=>{if(!this._src)return;state.active--;this.naturalWidth=w;this.naturalHeight=h;this.onload?.();},2);
  }
  get src(){return this._src;}
  removeAttribute(n){if(n==="src")this._src="";}
 }
 const document={createElement(name){
  if(name!=="canvas")throw Error("Unexpected "+name);
  const canvas={width:0,height:0};
  const context={drawImage(...args){captures.push(args)}};
  canvas.getContext=()=>context;
  return canvas;
 }};
 const sandbox={window:{},document,Image:FakeImage,URLSearchParams,Date,Math,Number,String,Array,
  Promise,Set,Error,setTimeout,clearTimeout};
 vm.runInNewContext(source,sandbox);
 return {fhd:sandbox.window.SatelliteFHD,requests,captures,state};
}
const UTC=["2026-11-12T18:00:00Z","2026-11-12T18:10:00Z"];
test("Full HD loader constructs true 1920px source mosaics at verified UTC with max 2 WMS requests",async()=>{
 const h=harness(),out=await h.fhd.loadFrames({
  region:"europe",layer:"mtg_fd:rgb_geocolour",
  frames:UTC.map((time,index)=>({time,index}))
 });
 assert.equal(out.length,2);
 assert.equal(out[0].img.width,1920);
 assert.equal(out[0].img.height,1255);
 assert.equal(h.state.maxActive<=2,true);
 assert.equal(h.requests.length,12);
 assert.ok(h.requests.every(r=>r.searchParams.get("width")==="640"));
 for(const time of UTC){
  const urls=h.requests.filter(u=>u.searchParams.get("time")===time);
  assert.equal(urls.length,6);
  assert.equal(new Set(urls.map(u=>u.searchParams.get("bbox"))).size,6);
  assert.ok(urls.every(url=>url.searchParams.get("srs")==="EPSG:4326"));
 }
 assert.equal(h.captures.length,12);
});
test("MP4 source loader refuses fabricated timestamps, unauthorized layers, and >12 frame overload",async()=>{
 const h=harness();
 await assert.rejects(h.fhd.loadFrames({region:"europe",layer:"mtg_fd:rgb_geocolour",
  frames:Array.from({length:13},(_,i)=>({time:UTC[0],index:i}))}),/2 bis 12/);
 await assert.rejects(h.fhd.loadFrames({region:"disk",layer:"mtg_fd:rgb_geocolour",
  frames:UTC.map(time=>({time}))}),/geografisch/);
 await assert.rejects(h.fhd.loadFrames({region:"europe",layer:"bad_layer",
  frames:UTC.map(time=>({time}))}),/WMS-Layer/);
 await assert.rejects(h.fhd.loadFrames({region:"europe",layer:"mtg_fd:rgb_geocolour",
  frames:[{time:"invalid"},{time:UTC[0]}]}),/UTC-Zeit/);
 const guard=()=>false;
 await assert.rejects(h.fhd.loadFrames({region:"europe",layer:"mtg_fd:rgb_geocolour",
  frames:UTC.map(time=>({time})),validate:guard}),/geändert/);
 assert.equal(h.requests.length,0);
});
test("Full HD MP4 has genuine 1920x1080 canvas, 8Mbps and valid MP4 ftyp payload",async()=>{
 const captures={canvas:null,bitrate:null,frames:0};
 class FakeCanvas{
  constructor(){this.width=0;this.height=0;captures.canvas=this;}
  getContext(){return {fillRect(){},drawImage(){},fillText(){}};}
  captureStream(){return {getVideoTracks:()=>[{requestFrame(){captures.frames++},stop(){}}]};}
 }
 class MediaRecorder{
  static isTypeSupported(type){return type.startsWith("video/mp4");}
  constructor(stream,opts){captures.bitrate=opts.videoBitsPerSecond;this.mimeType="video/mp4";this.state="inactive";}
  start(){this.state="recording";}
  stop(){this.state="inactive";this.ondataavailable?.({data:new Blob([new Uint8Array([0,0,0,8,102,116,121,112,0,0,0,0])],{type:"video/mp4"})});this.onstop?.();}
 }
 const doc={createElement(name){assert.equal(name,"canvas");return new FakeCanvas();}};
 const sandbox={window:{},document:doc,Blob,Uint8Array,MediaRecorder,HTMLCanvasElement:FakeCanvas,
  String,Number,Math,Date,Array,Error,Promise,setTimeout,clearTimeout};
 vm.runInNewContext(encoder,sandbox);
 const img={width:1920,height:1255};
 const result=await sandbox.window.SatelliteFilmExport.exportMP4({
  width:1920,fullHD:true,frames:UTC.map(time=>({time,img})),
  product:"geocolour",productName:"GeoColour",region:"europe",credit:"© EUMETSAT",delayMs:150
 });
 assert.equal(captures.canvas.width,1920);
 assert.equal(captures.canvas.height,1080);
 assert.equal(captures.bitrate,8000000);
 assert.equal(captures.frames,2);
 assert.equal(result.name.endsWith(".mp4"),true);
 assert.equal(result.blob.type,"video/mp4");
});
test("Full HD UI stays separate from quick preview playback and only runs on opt-in",()=>{
 assert.ok(html.includes('id="satMp4Quality"'));
 assert.ok(html.includes('value="fhd"'));
 assert.ok(html.includes('src="satellite_fullhd_film.js?'));
 const js=fs.readFileSync("satelliten.js","utf8");
 assert.match(js,/SatelliteFHD\.loadFrames/);
 assert.match(js,/images\.length>12/);
 assert.match(js,/format==="mp4"/);
});
