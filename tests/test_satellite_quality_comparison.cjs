"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const hd=fs.readFileSync("satellite_hd.js","utf8");
const comparison=fs.readFileSync("satellite_quality_comparison.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");
const deploy=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const UTC="2026-11-12T17:20:00Z";
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(condition,label,timeout=2600){
 const stop=Date.now()+timeout;
 while(!condition()){if(Date.now()>stop)throw Error("Timeout: "+label);await sleep(10);}
}
function setup({fail4k=false}={}){
 const els=new Map(),requests=[],draws=[],outstanding={active:0,peak:0};
 class Element{
  constructor(id){this.id=id;this.style={};this.checked=false;this.hidden=true;this.disabled=false;
   this.complete=true;this.value="";this.textContent="";this.children=[];this.listeners={};}
  addEventListener(type,fn){this.listeners[type]=fn;}
  fire(type){return this.listeners[type]?.();}
  replaceChildren(...children){this.children=children;}
  append(child){this.children.push(child);}
  getBoundingClientRect(){return this.id==="satPictureFrame"||this.id==="satImageStack"?
   {left:0,right:1300,top:0,bottom:850,width:1300,height:850}:{left:0,top:0,right:1,bottom:1,width:1,height:1};}
 }
 class Canvas extends Element{
  constructor(id){super(id);this.width=0;this.height=0;this.calls=[];}
  getContext(){const canvas=this;return {
   clearRect(){},drawImage(...args){canvas.calls.push(args);draws.push({id:canvas.id,args});},
   save(){},restore(){},fillRect(){},fillText(){},beginPath(){},rect(){},clip(){}
  };}
 }
 for(const id of ["satHDTiles","satPictureFrame","satImageStack","satStillQuality","satHDStatus","satHDDownload",
  "satHDPdf","satHDExportBorders","satHDExportCities","satHDExportIsobars","satSource","satProduct",
  "satRegion","satImage","satFilmStage","satCompareRun","satCompareClose","satCompareCrop",
  "satCompareStatus","satCompareGrid","satCompareBox","satCompareInfoStandard","satCompareInfoHD",
  "satCompareInfo4K"]){els.set(id,new Element(id));}
 for(const id of ["satCompareStandard","satCompareHD","satCompare4K"])els.set(id,new Canvas(id));
 els.get("satStillQuality").value="standard";
 els.get("satSource").value="mtgi1";els.get("satProduct").value="geocolour";
 els.get("satRegion").value="europe";els.get("satCompareCrop").value="center";
 els.get("satFilmStage").hidden=true;
 const still=els.get("satImage");
 still.naturalWidth=800;still.naturalHeight=523;
 still.src="https://view.eumetsat.int/geoserver/wms?"+
  new URLSearchParams({request:"GetMap",service:"WMS",version:"1.1.1",layers:"mtg_fd:rgb_geocolour",
   format:"image/png",srs:"EPSG:4326",bbox:"-27,24,49,73",width:"800",height:"523",time:UTC});
 class FakeImage{
  constructor(){this.onload=null;this.onerror=null;this.crossOrigin="";this.decoding="";
   this.complete=false;this.naturalWidth=0;this.naturalHeight=0;this.style={};}
  set src(value){
   this._src=value;if(!value)return;
   const u=new URL(value);
   requests.push(u);outstanding.active++;outstanding.peak=Math.max(outstanding.active,outstanding.peak);
   setTimeout(()=>{
    outstanding.active--;
    if(!this._src)return;
    const w=Number(u.searchParams.get("width")),h=Number(u.searchParams.get("height"));
    if(fail4k&&w>=1000){this.onerror?.();return;}
    this.naturalWidth=w;this.naturalHeight=h;this.complete=true;this.onload?.();
   },3);
  }
  get src(){return this._src;}
  removeAttribute(name){if(name==="src")this._src="";}
 }
 const document={
  getElementById(id){return els.get(id)||null;},
  createElement(tag){if(tag!=="canvas")throw Error("Unexpected element "+tag);return new Canvas("mosaic");}
 };
 const sandbox={window:{},document,Image:FakeImage,URL,URLSearchParams,Date,Math,Number,String,Array,
  Set,Map,Promise,Error,setTimeout,clearTimeout};
 vm.runInNewContext(hd,sandbox,{timeout:2000});
 vm.runInNewContext(comparison,sandbox,{timeout:2000});
 const live={time:UTC,region:"europe",source:"mtgi1",product:"geocolour",
  layer:"mtg_fd:rgb_geocolour",ready:true,cached:false};
 return {els,requests,draws,sandbox,live,outstanding};
}
test("Versioned comparison assets are published, accessible and syntax-valid",()=>{
 assert.ok(html.includes('id="satCompareRun"'));
 assert.ok(html.includes('id="satCompareStatus"'));
 assert.ok(html.includes('id="satCompareGrid"'));
 assert.ok(html.includes('id="satCompareBox"'));
 assert.ok(html.includes('src="satellite_quality_comparison.js?'));
 assert.ok(deploy.includes("  satellite_quality_comparison.js\n"));
 assert.ok(deploy.includes("node --check _site/satellite_quality_comparison.js"));
 for(const id of ["satCompareStandard","satCompareHD","satCompare4K","satCompareCrop"])
  assert.ok(html.includes('id="'+id+'"'));
 assert.doesNotThrow(()=>new vm.Script(comparison));
});
test("Comparison is strictly opt-in and uses same verified time, layer, extent for 800/HD/4K",async()=>{
 const a=setup();
 assert.equal(a.els.get("satCompareRun").disabled,true);
 a.sandbox.window.SatelliteHD.sync(a.live);
 await sleep(210);
 assert.equal(a.requests.length,0,"HD and 4K must never load before explicit action");
 assert.equal(a.els.get("satCompareRun").disabled,false);
 await a.els.get("satCompareRun").fire("click");
 await until(()=>a.els.get("satCompareStatus").textContent.includes("verifiziert"),"same UTC quality report");
 assert.equal(a.requests.length,18,"6 genuine HD and 12 genuine 4K WMS tiles");
 assert.ok(a.requests.every(u=>u.searchParams.get("time")===UTC));
 assert.ok(a.requests.every(u=>u.searchParams.get("layers")==="mtg_fd:rgb_geocolour"));
 assert.ok(a.requests.every(u=>u.searchParams.get("srs")==="EPSG:4326"));
 assert.ok(a.requests.every(u=>u.searchParams.get("bbox")!== "-27,24,49,73"));
 assert.equal(a.outstanding.peak<=2,true,"at most two WMS requests concurrently");
 assert.equal(a.els.get("satCompareGrid").hidden,false);
 for(const id of ["satCompareStandard","satCompareHD","satCompare4K"])
  assert.equal(a.els.get(id).hidden,false,id+" must show real raster");
 const first=a.els.get("satCompareStandard").calls[0];
 assert.equal(first[3],176,"standard crop uses actual 800px source");
 assert.ok(a.els.get("satCompareHD").calls.length>0);
 assert.ok(a.els.get("satCompare4K").calls.length>0);
 const cropPixels=id=>Number(a.els.get(id).textContent.match(/mit (\\d+) ×/)[1]);
 assert.ok(cropPixels("satCompareInfoStandard")<cropPixels("satCompareInfoHD"));
 assert.ok(cropPixels("satCompareInfoHD")<cropPixels("satCompareInfo4K"));
 assert.ok(a.els.get("satCompareHD").calls.every(args=>args[7]>=0&&args[7]<=620),
  "screen crop is assembled from its genuine WMS tiles");
 assert.match(a.els.get("satCompareInfoStandard").textContent,/800 × 523 WMS-Pixel/);
 assert.match(a.els.get("satCompareInfoHD").textContent,/2048 × 1339 WMS-Pixel/);
 assert.match(a.els.get("satCompareInfo4K").textContent,/4096 × 2678 WMS-Pixel/);
 assert.match(a.els.get("satCompareStatus").textContent,/keine höhere Sensorauflösung/);
 assert.equal(a.els.get("satStillQuality").value,"standard","original viewer quality stays intact");
});
test("Choosing another matched geographic crop redraws samples without reloading EUMETSAT",async()=>{
 const a=setup();
 a.sandbox.window.SatelliteHD.sync(a.live);
 await a.els.get("satCompareRun").fire("click");
 const oldRequests=a.requests.length;
 const oldCropCount=a.els.get("satCompareHD").calls.length;
 a.els.get("satCompareCrop").value="northeast";
 a.els.get("satCompareCrop").fire("change");
 assert.equal(a.requests.length,oldRequests);
 assert.ok(a.els.get("satCompareHD").calls.length>oldCropCount);
 assert.ok(Number(a.els.get("satCompareBox").style.left.slice(0,-1))>50);
 a.sandbox.window.SatelliteHD.cancel("Film gestartet");
 assert.equal(a.els.get("satCompareGrid").hidden,true);
 assert.equal(a.els.get("satCompareRun").disabled,true);
 assert.equal(a.els.get("satCompareBox").hidden,true);
});
test("An unavailable 4K WMS tile never masquerades as a sharp comparison image",async()=>{
 const a=setup({fail4k:true});
 a.sandbox.window.SatelliteHD.sync(a.live);
 await a.els.get("satCompareRun").fire("click");
 assert.equal(a.els.get("satCompareStandard").hidden,false);
 assert.equal(a.els.get("satCompareHD").hidden,false);
 assert.equal(a.els.get("satCompare4K").hidden,true);
 assert.match(a.els.get("satCompareInfo4K").textContent,/Nicht verfügbar/);
 assert.match(a.els.get("satCompareStatus").textContent,/4K nicht verfügbar/);
});
test("An archived, wrong-time, wrong-layer or switched image is never falsely compared",async()=>{
 const a=setup();
 a.sandbox.window.SatelliteHD.sync(a.live);
 a.els.get("satImage").src="data:image/png;base64,AA==";
 await a.els.get("satCompareRun").fire("click");
 assert.equal(a.requests.length,0);
 assert.match(a.els.get("satCompareStatus").textContent,/nicht möglich/);
 const b=setup();
 b.sandbox.window.SatelliteHD.sync(b.live);
 b.els.get("satImage").src=b.els.get("satImage").src.replace("17%3A20","18%3A20");
 await b.els.get("satCompareRun").fire("click");
 assert.equal(b.requests.length,0);
 assert.match(b.els.get("satCompareStatus").textContent,/UTC-Zeitpunkt/);
});
