"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const source=fs.readFileSync("satelliten.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");

function fixture(){
 const nodes=new Map(),requests=[],fetches=[],preloaded=[],state={active:0,maxActive:0};
 const options=["satSource","satProduct","satRegion","satTime","satImage","satEmpty","satStatus",
   "satPrev","satNext","satPlay","satPng","satTimeline","satTimelineLabel","satFilmStage",
   "satFilmLength","satFilmQuality","satFilmSpeed","satFilmProgress","satFilmProgressLabel",
   "satFilmProgressWrap","satRawImage","satMapTitle","satValid","satImageInfo",
   "satOfficial","satAttribution","satReload"];
 class Element{
  constructor(){this.hidden=false;this.disabled=false;this.value="";this.textContent="";this.options=[];
    this.children=[];this.listeners=new Map();this.attrs={};this.dataset={};}
  addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,[]);this.listeners.get(type).push(fn);}
  dispatch(type){for(const cb of this.listeners.get(type)||[])cb({type});}
  replaceChildren(...children){this.children=children;this.options=[];}
  add(option){this.options.push(option);}
  setAttribute(name,value){this.attrs[name]=value;}
 }
 class FakeImage extends Element{
  constructor(){super();this._src="";this.naturalWidth=0;this.naturalHeight=0;this.onload=null;this.onerror=null;
   this.decoding="auto";preloaded.push(this);}
  set src(value){
   this._src=value;
   if(!value)return;
   requests.push({url:value,img:this});
   const params=new URL(value).searchParams;
   if(params.get("request")!=="GetMap")return;
   const isSmall=Number(params.get("width"))<=720;
   if(isSmall){state.active++;state.maxActive=Math.max(state.maxActive,state.active);}
   setTimeout(()=>{
    this.naturalWidth=Number(params.get("width"));
    this.naturalHeight=Number(params.get("height"));
    if(isSmall)state.active--;
    this.onload?.();
   },isSmall?7:3);
  }
  get src(){return this._src;}
 }
 for(const key of options)nodes.set(key,key==="satImage"?new FakeImage():new Element());
 nodes.get("satSource").value="mtgi1";
 nodes.get("satProduct").value="geocolour";
 nodes.get("satRegion").value="southwest";
 nodes.get("satFilmLength").value="6";
 nodes.get("satFilmQuality").value="480";
 nodes.get("satFilmSpeed").value="40"; // accelerate simulated clock; site presets are >=420 ms
 const now=Date.now();
 const slots=Array.from({length:8},(_,i)=>new Date(Math.floor((now-90*60000+i*600000)/600000)*600000).toISOString());
 const manifest={generated_at:new Date().toISOString(),capabilities_ok:true,products:{
  geocolour:{map_ok:true,latest_verified_time:slots.at(-1),available_times:slots}
 }};
 const fetch=async (url,opts)=>{
  fetches.push(url);
  if(String(url).includes("GetCapabilities"))throw Error("Simulate blocked capabilities; use checked GitHub manifest");
  if(String(url).includes("satellite_wms_times.json"))return {ok:true,json:async()=>manifest};
  throw Error("Unexpected fetch: "+url);
 };
 const document={getElementById:id=>{assert.ok(nodes.has(id),"Unknown node "+id);return nodes.get(id);},
  hidden:false,addEventListener(){}};
 const window={addEventListener(){}};
 const sandbox={document,window,Image:FakeImage,Option:class{constructor(label,value){this.label=label;this.value=value;}},
  fetch,URLSearchParams,URL,Date,Intl,Math,Number,Array,Set,String,Boolean,
  setTimeout,clearTimeout,AbortController,console};
 vm.runInNewContext(source,sandbox,{timeout:5000});
 return {nodes,requests,fetches,preloaded,state,slots};
}
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function waitUntil(fn,reason,limit=2000){
 const start=Date.now();
 while(!fn()){if(Date.now()-start>limit)throw Error("Timed out: "+reason);await delay(10);}
}
test("Film player reuses small WMS PNGs and never requests each frame again",async()=>{
 const {nodes,requests,fetches,state,slots}=fixture();
 await waitUntil(()=>nodes.get("satTime").options.length===slots.length,"eight verified UTC times");
 assert.equal(nodes.get("satTimeline").max,"7");
 await waitUntil(()=>nodes.get("satImage").naturalWidth>0,"full resolution image");
 const originalRequests=requests.length;
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"film preview started");
 const previewRequests=requests.filter(r=>new URL(r.url).searchParams.get("width")==="480");
 assert.equal(previewRequests.length,6,"six miniature images downloaded exactly once");
 assert.ok(state.maxActive<=2,"at most two parallel WMS preloads");
 assert.ok(state.maxActive>=1);
 assert.equal(nodes.get("satFilmStage").children.length,1);
 assert.equal(nodes.get("satFilmStage").children[0],previewRequests[0].img,"preloaded DOM image reused");
 assert.match(nodes.get("satStatus").textContent,/Satellitenfilm/);
 const count=requests.length;
 await delay(125); // three playback ticks
 assert.equal(requests.length,count,"no additional network calls during playback");
 assert.equal(nodes.get("satFilmProgress").value,6);
 assert.match(nodes.get("satFilmProgressLabel").textContent,/6 von 6/);
 assert.equal(nodes.get("satFilmStage").children[0].naturalWidth,480);
 nodes.get("satPlay").dispatch("click"); // pause
 assert.match(nodes.get("satPlay").textContent,/Fortsetzen/);
 await delay(70);
 assert.equal(requests.length,count);
 nodes.get("satPlay").dispatch("click"); // resume
 await delay(60);
 assert.equal(requests.length,count,"cached playback even after resume");
 nodes.get("satTimeline").value="2";
 nodes.get("satTimeline").dispatch("change"); // seek returns to high resolution still
 assert.equal(nodes.get("satFilmStage").hidden,true);
 await waitUntil(()=>requests.length>count,"single still frame requested on seek");
 const latest=new URL(requests.at(-1).url);
 assert.equal(latest.searchParams.get("width"),"1200","still image is full resolution");
 assert.equal(latest.searchParams.get("bbox"),"-37,24,19,53");
 const before=fetches.length;
 nodes.get("satRegion").value="germany";
 nodes.get("satRegion").dispatch("change");
 assert.equal(fetches.length,before,"switching region must not re-fetch time metadata");
});
test("Lightweight film controls exist and preserve original high-res export",()=>{
 for(const id of ["satTimeline","satFilmLength","satFilmQuality","satFilmSpeed","satFilmStage",
  "satFilmProgressWrap","satFilmProgress","satFilmProgressLabel"]){
  assert.ok(html.includes('id="'+id+'"'),"Missing "+id);
 }
 for(const quality of ["480","720"])assert.ok(html.includes('value="'+quality+'"'));
 assert.match(source,/const w=previewWidth\?Math\.min\(previewWidth,r\.w\):r\.w/);
 assert.match(source,/filmImage\.replaceChildren\(item\.img\)/);
 assert.match(source,/await Promise\.all\(\[worker\(\),worker\(\)\]\)/);
 assert.match(source,/ctx\.drawImage\(img,0,header\)/);
});
