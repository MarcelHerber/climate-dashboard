"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const js=fs.readFileSync("satellite_hd.js","utf8"),html=fs.readFileSync("satelliten.html","utf8");
const cacheJs=fs.readFileSync("satellite_tile_cache.js","utf8");
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(ok,label,timeout=4300){
 const end=Date.now()+timeout;
 while(!ok()){if(Date.now()>end)throw Error("Timeout: "+label);await sleep(10);}
}
const UTC="2026-11-13T09:10:00Z";
function build({failOne=false,delayLast=false}={}){
 const els=new Map(),requests=[],listeners={},model={scale:1},stats={pending:0,maxPending:0};
 class Element{
  constructor(id){
   this.id=id;this.style={};this.hidden=true;this.disabled=false;this.value="";
   this.textContent="";this.children=[];this.listeners={};this.checked=false;
  }
  addEventListener(type,fn){this.listeners[type]=fn;}
  fire(type){return this.listeners[type]?.();}
  replaceChildren(...items){this.children=items;}
  append(el){this.children.push(el);}
  getBoundingClientRect(){
   if(this.id==="satPictureFrame")return {left:0,top:0,right:1300,bottom:850,width:1300,height:850};
   if(this.id==="satImageStack"){
    const s=model.scale;return {left:650-650*s,top:425-425*s,
     right:650+650*s,bottom:425+425*s,width:1300*s,height:850*s};
   }
   return {left:0,top:0,right:0,bottom:0,width:0,height:0};
  }
 }
 for(const id of ["satHDTiles","satPictureFrame","satImageStack","satStillQuality","satHDStatus",
 "satHDDownload","satHDPdf","satHDExportBorders","satHDExportCities","satHDExportIsobars",
 "satSource","satProduct","satRegion"]){els.set(id,new Element(id));}
 els.get("satSource").value="mtgi1";els.get("satProduct").value="geocolour";
 els.get("satRegion").value="europe";els.get("satStillQuality").value="standard";
 const document={getElementById:id=>els.get(id)||null};
 class Image{
  constructor(){this.style={};this.onload=null;this.onerror=null;this.naturalWidth=0;this.naturalHeight=0;}
  set src(value){
   this._src=value;
   if(!value)return;
   const url=new URL(value),w=+url.searchParams.get("width"),h=+url.searchParams.get("height");
   requests.push({url,w,h});
   stats.pending++;stats.maxPending=Math.max(stats.maxPending,stats.pending);
   const slow=delayLast&&w===682&&h===669;
   setTimeout(()=>{
    stats.pending--;
    if(this._src!==value)return;
    if(failOne&&w===682&&h===669){this.onerror?.();return;}
    this.naturalWidth=w;this.naturalHeight=h;this.onload?.();
   },slow?300:10);
  }
  get src(){return this._src;}
  removeAttribute(key){if(key==="src")this._src="";}
 }
 const environment={document,Image,window:{},URLSearchParams,Math,Date,Number,String,Map,Set,
  Promise,Error,setTimeout,clearTimeout};
 vm.runInNewContext(cacheJs,environment,{timeout:2000});
 vm.runInNewContext(js,environment,{timeout:2000});
 const scene=previewWidth=>({ready:true,cached:false,previewWidth,time:UTC,
  source:"mtgi1",region:"europe",product:"geocolour",layer:"mtg_fd:rgb_geocolour"});
 return {els,requests,stats,model,hd:environment.window.SatelliteHD,scene};
}
test("Automatic mode progressively upgrades a verified 800px still with geographically identical 2K tiles",async()=>{
 assert.match(html,/value="standard" selected>Automatisch/);
 assert.match(html,/value="economy">Datensparen/);
 const a=build({delayLast:true});a.hd.sync(a.scene(800));
 assert.equal(a.requests.length,0,"fast first image is never blocked by a WMS HD call");
 await sleep(260);assert.equal(a.requests.length,0,"background upgrade is deferred");
 await until(()=>a.requests.length===6,"6 WMS 2K tiles");
 assert.equal(a.els.get("satHDTiles").hidden,true,"no patchy automatic HD before entire mosaic");
 await until(()=>a.els.get("satHDTiles").children.length===6,"complete seamless 2K view");
 assert.equal(a.els.get("satHDTiles").hidden,false);
 assert.ok(a.requests.every(t=>t.url.searchParams.get("time")===UTC));
 assert.ok(a.requests.every(t=>t.url.searchParams.get("layers")==="mtg_fd:rgb_geocolour"));
 assert.ok(a.requests.every(t=>t.w<=700));
 assert.ok(a.stats.maxPending<=2,"do not overload official WMS");
 assert.equal(a.els.get("satHDDownload").disabled,true,"auto view must not change explicit download mode");
 assert.match(a.els.get("satHDStatus").textContent,/2048 × 1339 px/);
});
test("Automatic mode never pretends partially received HD is complete",async()=>{
 const a=build({failOne:true});a.hd.sync(a.scene(800));
 await until(()=>a.requests.length===6,"six WMS requests");
 await until(()=>a.els.get("satHDStatus").textContent.includes("nicht erreichbar"),"failed tile is reported");
 assert.equal(a.els.get("satHDTiles").hidden,true);
 assert.equal(a.els.get("satHDTiles").children.length,0);
 assert.match(a.els.get("satHDStatus").textContent,/Vorschau bleibt sichtbar/);
});
test("Automatic 4K requests appear only at 300% zoom, for visible geographic tiles",async()=>{
 const a=build();a.hd.sync(a.scene(800));
 await until(()=>a.els.get("satHDTiles").children.length===6,"auto HD completed");
 assert.equal(a.requests.length,6);
 a.model.scale=2.9;a.hd.viewChanged({scale:2.9});await sleep(240);
 assert.equal(a.requests.length,6,"below 300 percent retains auto 2K");
 a.model.scale=3.1;a.hd.viewChanged({scale:3.1});
 await until(()=>a.requests.length>6,"4K geographic zoom");
 const next=a.requests.slice(6);
 assert.ok(next.every(x=>x.w<=1024));
 assert.ok(next.every(x=>x.url.searchParams.get("time")===UTC));
 assert.match(a.els.get("satHDStatus").textContent,/4096 × 2678 px/);
 assert.equal(a.els.get("satHDDownload").disabled,true);
});
test("Reduced 400px fallback suspends automatic requests but still permits manual HD",async()=>{
 const a=build();a.hd.sync(a.scene(400));await sleep(950);
 assert.equal(a.requests.length,0);
 assert.match(a.els.get("satHDStatus").textContent,/wegen WMS-Rückfall pausiert/);
 a.els.get("satStillQuality").value="hd";
 a.els.get("satStillQuality").fire("change");
 await until(()=>a.requests.length>0,"manual HD starts even after fallback");
 assert.equal(a.els.get("satHDDownload").disabled,false);
});
test("Data saver mode prevents auto loading even with strong zoom; explicit 4K remains possible",async()=>{
 const a=build();a.els.get("satStillQuality").value="economy";a.hd.sync(a.scene(800));
 a.model.scale=3.5;a.hd.viewChanged({scale:3.5});
 await sleep(950);
 assert.equal(a.requests.length,0);
 assert.match(a.els.get("satHDStatus").textContent,/Datensparmodus/);
 a.els.get("satStillQuality").value="4k";a.els.get("satStillQuality").fire("change");
 await until(()=>a.requests.length>0,"manual full source detail starts");
 assert.ok(a.requests.every(x=>x.w<=1024));
});
test("Scene changes cancel previous progressive WMS requests and restore original preview",async()=>{
 const a=build({delayLast:true});a.hd.sync(a.scene(800));
 await until(()=>a.requests.length>=2,"progressive requests");
 a.hd.cancel("Film gestartet");
 assert.equal(a.els.get("satHDTiles").hidden,true);
 assert.equal(a.els.get("satHDTiles").children.length,0);
 await sleep(430);
 assert.equal(a.els.get("satHDTiles").children.length,0,
  "late arrivals from the old UTC can never paint onto a new scene");
});

test("Revisiting an unchanged UTC frame reuses all decoded 2K tiles without another WMS request",async()=>{
 const a=build();
 a.hd.sync(a.scene(800));
 await until(()=>a.els.get("satHDTiles").children.length===6,"initial HD complete");
 assert.equal(a.requests.length,6);
 const before=a.hd.cacheStats();
 assert.equal(before.entries,6);
 a.hd.sync(a.scene(800));
 await until(()=>a.els.get("satHDTiles").children.length===6,"6 cached tiles restored");
 assert.equal(a.requests.length,6,"exact same EUMETSAT UTC/region/quality must not refetch");
 assert.equal(a.hd.cacheStats().hits-before.hits,6);
 assert.match(a.els.get("satHDStatus").textContent,/6 Kacheln aus Bildcache/);
});
test("Zoom 2K → 4K → 2K restores original WMS tiles from memory",async()=>{
 const a=build();
 a.hd.sync(a.scene(800));
 await until(()=>a.els.get("satHDTiles").children.length===6,"2K complete");
 const initial=a.requests.length;
 a.model.scale=3.2;a.hd.viewChanged({scale:3.2});
 await until(()=>a.requests.length>initial,"4K visible tiles requested");
 const countAfter4k=a.requests.length;
 a.model.scale=1;a.hd.viewChanged({scale:1});
 await until(()=>a.els.get("satHDTiles").children.length===6,"2K cached after zoom out");
 assert.equal(a.requests.length,countAfter4k,"no new 2K tile downloads on zoom back");
 assert.ok(a.hd.cacheStats().hits>=6);
});
test("Changing UTC or WMS layer never reuses unrelated pixels, but returning to prior UTC hits cache",async()=>{
 const a=build();
 a.hd.sync(a.scene(800));
 await until(()=>a.els.get("satHDTiles").children.length===6,"first UTC");
 const first=a.requests.length;
 const later={...a.scene(800),time:"2026-11-13T09:20:00Z"};
 a.hd.sync(later);
 await until(()=>a.els.get("satHDTiles").children.length===6,"later UTC");
 assert.equal(a.requests.length,first+6,"different UTC must fetch new satellite pixels");
 assert.ok(a.requests.slice(first).every(v=>v.url.searchParams.get("time")===later.time));
 const afterTwo=a.requests.length;
 a.hd.sync(a.scene(800));
 await until(()=>a.els.get("satHDTiles").children.length===6,"previous UTC from cache");
 assert.equal(a.requests.length,afterTwo);
 a.els.get("satProduct").value="ir105";
 a.hd.sync({...a.scene(800),product:"ir105",layer:"mtg_fd:ir105_hrfi"});
 await until(()=>a.els.get("satHDTiles").children.length===6,"different product");
 assert.equal(a.requests.length,afterTwo+6,"different product must not be faked with GeoColour");
});
test("User can clear in-memory cache without losing the currently visible HD picture",async()=>{
 const a=build();
 a.hd.sync(a.scene(800));
 await until(()=>a.els.get("satHDTiles").children.length===6,"initial HD");
 assert.equal(a.hd.cacheStats().entries,6);
 const visible=a.els.get("satHDTiles").children.length;
 a.hd.clearTileCache();
 assert.equal(a.hd.cacheStats().entries,0);
 assert.equal(a.els.get("satHDTiles").children.length,visible,"onscreen HD not discarded");
 a.hd.sync(a.scene(800));
 await until(()=>a.requests.length>=12,"cache emptied means real WMS refetch");
});
