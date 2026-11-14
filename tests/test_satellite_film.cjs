"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const source=fs.readFileSync("satelliten.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");

function fixture({failOne480=false,failOne320=false,failLargeStill=false,failAllWms=false,archiveAvailable=false,totalSlots=8,verifiedLagSlots=0}={}){
 let failed480=false,failed320=false;
 const nodes=new Map(),requests=[],fetches=[],preloaded=[],state={active:0,maxActive:0};
 const options=["satSource","satProduct","satRegion","satTime","satImage","satEmpty","satStatus",
   "satPrev","satNext","satPlay","satPng","satTimeline","satTimelineLabel","satFilmStage",
   "satFilmLength","satFilmQuality","satMp4Quality","satFilmSpeed","satFilmProgress","satFilmProgressLabel",
   "satFilmProgressWrap","satRawImage","satMapTitle","satValid","satImageInfo",
   "satOfficial","satAttribution","satReload","satGif","satMp4","satPngIsobars","satPdfIsobars","satGifIsobars"];
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
  constructor(){super();this._src="";this._pending=null;this.naturalWidth=0;this.naturalHeight=0;this.onload=null;this.onerror=null;
   this.decoding="auto";preloaded.push(this);}
  abortPending(){
   const previous=this._pending;
   if(previous&&!previous.aborted){
    previous.aborted=true;
    if(previous.isSmall)state.active--;
   }
   this._pending=null;
  }
  removeAttribute(name){if(name==="src"){this.abortPending();this._src="";}}
  set src(value){
   this.abortPending();
   this._src=value;
   if(!value)return;
   const task={aborted:false,isSmall:false};
   this._pending=task;
   requests.push({url:value,img:this});
   if(String(value).startsWith("./data/satellite_cache/")){
    setTimeout(()=>{if(task.aborted)return;this._pending=null;this.naturalWidth=400;this.naturalHeight=207;this.onload?.();},7);
    return;
   }
   const params=new URL(value).searchParams;
   if(params.get("request")!=="GetMap")return;
   const isSmall=Number(params.get("width"))<=720;
   task.isSmall=isSmall;
   if(isSmall){state.active++;state.maxActive=Math.max(state.maxActive,state.active);}
   setTimeout(()=>{
    if(task.aborted)return;
    if(this._pending===task)this._pending=null;
    this.naturalWidth=Number(params.get("width"));
    this.naturalHeight=Number(params.get("height"));
    if(isSmall)state.active--;
    if(failAllWms){this.onerror?.();return;}
    if(failLargeStill&&this.naturalWidth>=1000){this.onerror?.();return;}
    if(failOne480&&!failed480&&this.naturalWidth===480){failed480=true;this.onerror?.();return;}
    if(failOne320&&!failed320&&this.naturalWidth===320){failed320=true;this.onerror?.();return;}
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
 nodes.get("satMp4Quality").value="preview";
 nodes.get("satFilmSpeed").value="40"; // accelerate simulated clock; site presets are >=420 ms
 const now=Date.now();
 const slots=Array.from({length:totalSlots},(_,i)=>new Date(Math.floor((now-(totalSlots-i)*600000)/600000)*600000).toISOString());
 const manifest={generated_at:new Date().toISOString(),capabilities_ok:true,products:{
  geocolour:{map_ok:true,latest_verified_time:slots.at(-1-verifiedLagSlots),available_times:slots}
 }};
 const fetch=async (url,opts)=>{
  fetches.push(url);
  if(String(url).includes("GetCapabilities"))throw Error("Simulate blocked capabilities; use checked GitHub manifest");
  if(String(url).includes("satellite_wms_times.json"))return {ok:true,json:async()=>manifest};
  if(String(url).includes("satellite_cache/index.json")){
   if(!archiveAvailable)return {ok:false,status:404};
   const observed=slots.at(-1).replace(".000Z","Z");
   const filename="geocolour_southwest_"+observed.replace(/[-:]/g,"")+".png";
   return {ok:true,json:async()=>({schema:1,entries:{geocolour:{southwest:{
    time:observed,url:"./data/satellite_cache/"+filename,source:"EUMETSAT WMS",width:400
   }}}})};
  }
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
 assert.ok(fetches[0].includes("satellite_wms_times.json"),"Local verified WMS metadata must load before remote capabilities");
 assert.ok(!fetches.some(url=>String(url).includes("GetCapabilities")),"Fresh local UTC metadata avoids remote GetCapabilities");
 const originalRequests=requests.length;
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"film preview started");
 const previewRequests=requests.filter(r=>new URL(r.url).searchParams.get("width")==="480");
 assert.equal(previewRequests.length,6,"six miniature images downloaded exactly once");
 assert.ok(state.maxActive<=2,"at most two parallel WMS preloads");
 assert.ok(state.maxActive>=1);
 assert.equal(nodes.get("satGif").disabled,false,"GIF available after preloading");
 assert.equal(nodes.get("satMp4").disabled,true,"MP4 disabled in mock without codec");
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
 assert.equal(latest.searchParams.get("width"),"800","still image uses 800px WMS default preview");
 assert.equal(latest.searchParams.get("bbox"),"-37,24,19,53");
 const before=fetches.length;
 nodes.get("satRegion").value="germany";
 nodes.get("satRegion").dispatch("change");
 assert.equal(fetches.length,before,"switching region must not re-fetch time metadata");
});
test("One failed 480px WMS frame falls back to a lighter 320px preview",async()=>{
 const {nodes,requests}=fixture({failOne480:true});
 await waitUntil(()=>nodes.get("satTime").options.length===8,"UTC timestamps");
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"movie with fallback starts");
 assert.equal(requests.filter(r=>new URL(r.url).searchParams.get("width")==="480").length,6);
 assert.equal(requests.filter(r=>new URL(r.url).searchParams.get("width")==="320").length,1);
 assert.equal(nodes.get("satFilmProgress").value,6);
 assert.ok(nodes.get("satFilmStage").children[0].naturalWidth>0);
 nodes.get("satPlay").dispatch("click");
});
test("36-frame film uses small 320px images and ends at selected UTC frame",async()=>{
 const {nodes,requests,state,slots}=fixture({totalSlots:48});
 await waitUntil(()=>nodes.get("satTime").options.length===48,"48 verified UTC times");
 nodes.get("satTime").value="39";
 nodes.get("satTime").dispatch("change");
 nodes.get("satFilmLength").value="36";
 nodes.get("satFilmLength").dispatch("change");
 assert.equal(nodes.get("satFilmQuality").value,"320","long movies default to 320 px");
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"36-frame movie starts",4000);
 const previewRequests=requests.filter(r=>new URL(r.url).searchParams.get("width")==="320");
 assert.equal(previewRequests.length,36,"all 36 selected frames loaded once");
 assert.ok(state.maxActive<=2,"long film limits simultaneous requests");
 const firstURL=new URL(previewRequests[0].url);
 const lastURL=new URL(previewRequests.at(-1).url);
 assert.equal(firstURL.searchParams.get("time"),slots[4],"movie begins at frame four");
 assert.equal(lastURL.searchParams.get("time"),slots[39],"movie ends at selected UTC time");
 assert.equal(nodes.get("satFilmProgress").value,36);
 assert.match(nodes.get("satFilmProgressLabel").textContent,/36 von 36/);
 const afterPreload=requests.length;
 await delay(110);
 assert.equal(requests.length,afterPreload,"playback makes no further HTTP requests");
 nodes.get("satPlay").dispatch("click");
});
test("36-frame GeoColour film recovers once from a failed 320px image",async()=>{
 const {nodes,requests,state}=fixture({totalSlots:48,failOne320:true});
 await waitUntil(()=>nodes.get("satTime").options.length===48,"48 verified times");
 nodes.get("satFilmLength").value="36";
 nodes.get("satFilmLength").dispatch("change");
 assert.equal(nodes.get("satFilmQuality").value,"320");
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"recovered 36-frame film",5000);
 assert.equal(requests.filter(r=>new URL(r.url).searchParams.get("width")==="320").length,36);
 assert.equal(requests.filter(r=>new URL(r.url).searchParams.get("width")==="240").length,1);
 assert.equal(nodes.get("satFilmProgress").value,36);
 assert.ok(state.maxActive<=2);
 nodes.get("satPlay").dispatch("click");
});
test("48-frame movie covers every available timestamp without duplicate downloads",async()=>{
 const {nodes,requests,state,slots}=fixture({totalSlots:48});
 await waitUntil(()=>nodes.get("satTime").options.length===48,"48 timestamps");
 nodes.get("satFilmLength").value="48";
 nodes.get("satFilmLength").dispatch("change");
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"48-frame movie starts",5000);
 const previews=requests.filter(r=>new URL(r.url).searchParams.get("width")==="320");
 assert.equal(previews.length,48);
 assert.equal(new URL(previews[0].url).searchParams.get("time"),slots[0]);
 assert.equal(new URL(previews.at(-1).url).searchParams.get("time"),slots[47]);
 assert.ok(state.maxActive<=2);
 const before=requests.length;
 await delay(100);
 assert.equal(requests.length,before,"48-frame playback uses cached frames only");
 nodes.get("satPlay").dispatch("click");
});
test("Still picture loads 800px but keeps native image link",async()=>{
 const {nodes,requests,slots}=fixture({failLargeStill:true});
 await waitUntil(()=>nodes.get("satTime").options.length===8,"verified UTC axis");
 await waitUntil(()=>nodes.get("satImage").naturalWidth===800,"sharper still preview loaded",1500);
 const previews=requests.filter(r=>new URL(r.url).searchParams.get("width")==="800");
 assert.ok(previews.length>=1,"800px preview not requested");
 const preview=new URL(previews.at(-1).url);
 const original=new URL(nodes.get("satRawImage").href);
 assert.equal(original.searchParams.get("width"),"1200","native source link retained");
 assert.equal(original.searchParams.get("bbox"),preview.searchParams.get("bbox"));
 assert.equal(original.searchParams.get("time"),preview.searchParams.get("time"));
 assert.equal(preview.searchParams.get("bbox"),"-37,24,19,53");
 assert.equal(preview.searchParams.get("time"),slots.at(-1));
 assert.match(nodes.get("satStatus").textContent,/Vorschau/);
 assert.equal(nodes.get("satPng").disabled,false);
});
test("Same-product cache is used after the 800→400 fallback fails",async()=>{
 const {nodes,requests}=fixture({failAllWms:true,archiveAvailable:true});
 await waitUntil(()=>nodes.get("satTime").options.length===8,"UTC metadata");
 await waitUntil(()=>nodes.get("satValid").textContent.includes("Archivaufnahme"),"early archive",2000);
 const attempted=requests.filter(r=>r.url.startsWith("https://")&&new URL(r.url).searchParams.get("request")==="GetMap");
 assert.equal(attempted.length,2,"one failing 800px and one failing 400px attempt should precede the verified snapshot");
 assert.equal(new URL(attempted[0].url).searchParams.get("width"),"800");
 assert.equal(new URL(attempted[1].url).searchParams.get("width"),"400");
 assert.match(nodes.get("satStatus").textContent,/Nicht aktuell/);
 assert.equal(nodes.get("satProduct").value,"geocolour");
});
test("When all WMS images fail, a real archived GeoColour UTC snapshot is displayed without relabelling it as live",async()=>{
 const {nodes,requests,slots}=fixture({failAllWms:true,archiveAvailable:true});
 await waitUntil(()=>nodes.get("satTime").options.length===8,"eight UTC metadata slots");
 await waitUntil(()=>nodes.get("satImage").src.startsWith("./data/satellite_cache/"),"archive fallback loaded",2000);
 await waitUntil(()=>nodes.get("satValid").textContent.includes("Archivaufnahme"),"archive UTC caption",2000);
 assert.match(nodes.get("satValid").textContent,/nicht live/);
 assert.ok(nodes.get("satValid").textContent.includes("UTC"));
 assert.equal(nodes.get("satProduct").value,"geocolour","do not switch product when matching archive exists");
 assert.equal(nodes.get("satPng").disabled,false);
 assert.ok(requests.some(r=>String(r.url).includes("geocolour_southwest_")));
 assert.match(nodes.get("satStatus").textContent,/gespeicherte GeoColour-Aufnahme/);
});
test("Lightweight film controls exist and preserve original high-res export",()=>{
 for(const id of ["satTimeline","satFilmLength","satFilmQuality","satFilmSpeed","satFilmStage",
  "satFilmProgressWrap","satFilmProgress","satFilmProgressLabel"]){
  assert.ok(html.includes('id="'+id+'"'),"Missing "+id);
 }
 for(const quality of ["320","480","720"])assert.ok(html.includes('value="'+quality+'"'));
 for(const n of [6,8,12,20,36,48])assert.ok(html.includes('<option value="'+n+'"'),"Missing "+n+"-frame choice");
 assert.match(source,/const w=previewWidth\?Math\.min\(previewWidth,r\.w\):r\.w/);
 assert.match(source,/filmImage\.replaceChildren\(item\.img\)/);
 assert.match(source,/await Promise\.all\(\[worker\(\),worker\(\)\]\)/);
 assert.match(source,/ctx\.drawImage\(img,0,header\)/);
});

test("Fast start selects the last successfully verified WMS UTC, never a newer untested frame",async()=>{
 const {nodes,requests,slots,fetches}=fixture({verifiedLagSlots:1});
 await waitUntil(()=>nodes.get("satTime").options.length===slots.length,"manifest contains multiple advertised UTC times");
 await waitUntil(()=>nodes.get("satImage").naturalWidth===800,"last verified 800px still loaded");
 const selected=nodes.get("satTime").value;
 assert.equal(selected,String(slots.length-2),"Verified UTC should be selected over newest advertised");
 const stills=requests.filter(r=>String(r.url).includes("GetMap")&&
   new URL(r.url).searchParams.get("width")==="800");
 assert.ok(stills.length>=1);
 assert.equal(new URL(stills[0].url).searchParams.get("time"),slots.at(-2));
 assert.ok(!fetches.some(u=>String(u).includes("GetCapabilities")));
 assert.match(nodes.get("satStatus").textContent,/Schärfere Vorschau|bestätigte/);
});

test("Restarting a previously loaded film reuses exact-UTC preview frames; region changes miss the cache",async()=>{
 const {nodes,requests,slots}=fixture();
 await waitUntil(()=>nodes.get("satTime").options.length===slots.length,"verified UTC times");
 await waitUntil(()=>nodes.get("satImage").naturalWidth===800,"first still loaded");
 const end=nodes.get("satTime").value;
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"first movie ready");
 const original=requests.filter(x=>new URL(x.url).searchParams.get("width")==="480");
 assert.equal(original.length,6,"six source previews downloaded on first playback");
 nodes.get("satTime").value=end;
 nodes.get("satTime").dispatch("change"); // stops film; same end UTC
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"second movie from preview cache");
 assert.equal(requests.filter(x=>new URL(x.url).searchParams.get("width")==="480").length,6,
  "same exact layer, BBOX, UTC and pixel size must not issue new WMS requests");
 assert.match(nodes.get("satFilmProgressLabel").textContent,/6 aus Vorschaucache/);
 nodes.get("satTime").value=end;
 nodes.get("satTime").dispatch("change");
 nodes.get("satRegion").value="germany";
 nodes.get("satRegion").dispatch("change");
 nodes.get("satPlay").dispatch("click");
 await waitUntil(()=>!nodes.get("satFilmStage").hidden,"new region film");
 assert.equal(requests.filter(x=>new URL(x.url).searchParams.get("width")==="480").length,12,
  "changed geographic BBOX must never reuse unrelated film pixels");
 nodes.get("satPlay").dispatch("click");
});
