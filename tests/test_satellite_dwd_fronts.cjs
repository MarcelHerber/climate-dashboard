"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("satellite_dwd_fronts.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");
const now=new Date();
const aligned=new Date(now);
aligned.setUTCMinutes(0,0,0);aligned.setUTCHours(Math.max(0,aligned.getUTCHours()-3));
const stamp=date=>date.toISOString().slice(0,16).replace("T","").replace(/[-:]/g,"");
const issued=new Date(aligned.getTime()+60*60000);
const format=date=>date.toISOString().slice(0,16)+"Z";
const prefix="https://opendata.dwd.de/weather/charts/analysis/";
function item(region="atlantic",args={}){
 const regionCode=region==="central"?"dwdc":"dwdna";
 const uri=prefix+"Z__C_EDZW_"+stamp(issued)+"00_tka01%2Cana_bwkman_"+
   regionCode+"_O_000000_000000_"+stamp(aligned)+"_WV12SW.png";
 return {
  kind:"analysis",valid_utc:format(aligned),published_utc:format(issued),source_url:uri,
  image_verified:true,fresh:true,region,...args
 };
}
function fixture({maps={atlantic:item("atlantic"),central:item("central")},state="healthy",fail=false}={}){
 class Element{
  constructor(id){
   this.id=id;this.hidden=false;this.disabled=false;this.href="";
   this.src="";this.textContent="";this.value=id==="satFrontRegion"?"atlantic":"";
   this.complete=false;this.naturalWidth=0;this.listeners={};
  }
  addEventListener(name,fn){this.listeners[name]=fn;}
  fire(name){return this.listeners[name]?.();}
  removeAttribute(name){this[name]=name==="src"?"":undefined;}
 }
 const ids=["satFrontRegion","satFrontStatus","satFrontImage","satFrontOpen",
  "satFrontSource","satFrontValid","satFrontMeta","satFrontRefresh"];
 const elements=Object.fromEntries(ids.map(id=>[id,new Element(id)]));
 const img=elements.satFrontImage;
 let requested=[];
 Object.defineProperty(img,"src",{get(){return this._src||""},set(v){
  this._src=v;
  if(v){this.naturalWidth=1000;this.complete=true;Promise.resolve().then(()=>this.onload?.());}
 }});
 const manifest={
  schema_version:1,kind:"analysis",source_page:prefix,status:state,
  generated_at:new Date().toISOString(),maps
 };
 const context={document:{getElementById:id=>elements[id]||null},window:{},
  URL,Date,Intl,Promise,Number,String,RegExp,setTimeout,clearTimeout,
  fetch:async url=>{
   requested.push(url);
   if(fail)return {ok:false,status:503};
   return {ok:true,json:async()=>manifest};
  }};
 vm.runInNewContext(source,context);
 return {els:elements,requested,context,manifest};
}
const flush=()=>new Promise(resolve=>setTimeout(resolve,0));
test("Show separately verified original manual DWD analysis with accurate UTC and attribution",async()=>{
 const v=fixture();await flush();
 assert.equal(v.requested.length,1);
 assert.equal(v.els.satFrontOpen.href,v.manifest.maps.atlantic.source_url);
 assert.equal(v.els.satFrontImage.src,v.manifest.maps.atlantic.source_url);
 assert.equal(v.els.satFrontImage.hidden,false);
 assert.match(v.els.satFrontValid.textContent,/Gültig: .*UTC/);
 assert.match(v.els.satFrontMeta.textContent,/Analyse, keine Prognose/);
 assert.match(v.els.satFrontStatus.textContent,/Originalkarte geladen/);
 assert.equal(v.els.satFrontSource.href,prefix);
 assert.ok(html.includes('id="satDwdFrontAnalysisSection"'));
 assert.ok(html.includes('Originalkarte · Analyse'));
 assert.ok(html.includes('href="#satDwdFrontAnalysisSection"'));
 assert.ok(!source.includes("satIsobarSvg") && !source.includes("satHDTiles"),
  "original chart is independent of satellite EPSG:4326 and model isobars");
});
test("Central Europe chart uses different original source and original UTC",async()=>{
 const v=fixture();await flush();
 const prev=v.els.satFrontImage.src;
 v.els.satFrontRegion.value="central";
 v.els.satFrontRegion.fire("change");
 await flush();
 assert.notEqual(v.els.satFrontImage.src,prev);
 assert.ok(v.els.satFrontImage.src.includes("dwdc"));
 assert.match(v.els.satFrontStatus.textContent,/Originalkarte geladen/);
 assert.equal(v.requested.length,1,"reselecting region never reloads entire manifest");
});
test("Invalid origin, forecast filename and mismatched UTC are refused",async()=>{
 const bads=[
  {source_url:"https://www.attacker.example/"+item().source_url.split("/").at(-1)},
  {source_url:prefix+"ico_tkboden_na_036.png"},
  {valid_utc:"2026-01-01T12:00Z"},
  {image_verified:false},
  {kind:"forecast"}
 ];
 for(const change of bads){
  const v=fixture({maps:{atlantic:item("atlantic",change)}});
  await flush();
  assert.equal(v.els.satFrontImage.hidden,true);
  assert.equal(v.els.satFrontOpen.hidden,true);
  assert.match(v.els.satFrontStatus.textContent,/Keine verifizierte/);
 }
});
test("Unavailable manifest and expired report fail visibly without claiming current fronts",async()=>{
 const p=fixture({fail:true});await flush();
 assert.match(p.els.satFrontStatus.textContent,/nicht erreichbar/);
 assert.equal(p.els.satFrontImage.hidden,true);
 const v=fixture({maps:{atlantic:item("atlantic",{valid_utc:"2024-11-13T06:00Z"})}});
 await flush();
 assert.equal(v.els.satFrontImage.hidden,true);
 assert.match(v.els.satFrontStatus.textContent,/Keine verifizierte|älter als/);
});
test("Historical verified image is labeled stale rather than currently analyzed",async()=>{
 const t=fixture({maps:{atlantic:item("atlantic",{previously_verified:true,fresh:false})}});
 await flush();
 assert.equal(t.els.satFrontImage.hidden,false);
 assert.match(t.els.satFrontStatus.textContent,/Ältere Analyse/);
});
test("DWD report reload safely handles external image failure",async()=>{
 const v=fixture();await flush();
 v.els.satFrontImage.onerror();
 assert.equal(v.els.satFrontImage.hidden,true);
 assert.match(v.els.satFrontStatus.textContent,/nicht erreichbar/);
 assert.equal(v.els.satFrontOpen.hidden,false,"official source stays available");
 v.els.satFrontRefresh.fire("click");
 await flush();
 assert.equal(v.requested.length,2);
});
