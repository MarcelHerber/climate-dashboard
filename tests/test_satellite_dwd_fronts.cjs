"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const js=fs.readFileSync("satellite_dwd_fronts.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");
const DWD="https://opendata.dwd.de/weather/charts/analysis/";
const GML="https://opendata.dwd.de/weather/fronts/manual_20261113.gml";
const UTC=new Date(Date.now()-2*3600000).toISOString().replace(/\.\d{3}Z$/,"Z");
const MOMENT=new Date(Date.now()-3600000).toISOString().replace(/\.\d{3}Z$/,"Z");
function validData(overrides={}){
 return {schema_version:1,status:"verified",provider:"DWD",kind:"analysis",
  coordinate_reference_system:"EPSG:4326",georeferencing_verified:true,
  front_source_format:"NinJo-GML",source_url:GML,valid_utc:UTC,
  features:[
   {type:"Feature",properties:{front_type:"cold"},geometry:{type:"LineString",coordinates:[[8,50],[11,52]]}},
   {type:"Feature",properties:{front_type:"warm"},geometry:{type:"LineString",coordinates:[[-9,38],[2,48]]}}
  ],...overrides};
}
function harness(geodata={schema_version:1,status:"unavailable",features:[]}){
 const nodes=new Map(),calls=[];
 class Element{
  constructor(id){this.id=id;this.attrs={};this.disabled=false;this.checked=false;
   this.value=id==="satSource"?"mtgi1":id==="satRegion"?"europe":"";
   this.href="";this.textContent="";this.listeners={};this.children=[];}
  addEventListener(kind,fn){this.listeners[kind]=fn;}
  fire(kind){return this.listeners[kind]?.();}
  setAttribute(key,value){this.attrs[key]=String(value);}
  removeAttribute(key){delete this.attrs[key];}
  appendChild(item){this.children.push(item);}
  replaceChildren(){this.children=[];}
  get hidden(){return "hidden" in this.attrs;}
 }
 for(const id of ["satShowDwdFronts","satDwdFrontSvg","satDwdFrontStatus",
  "satDwdFrontUTC","satDwdFrontSource","satDwdFrontRefresh","satSource","satRegion"])
  nodes.set(id,new Element(id));
 nodes.get("satDwdFrontSvg").setAttribute("hidden","");
 const makeGml=()=>geodata;
 const official={schema_version:1,kind:"analysis",maps:{atlantic:{
  source_url:DWD+"Z__C_EDZW_20261113153053_tka01%2Cana_bwkman_dwdna_O_000000_000000_202611131200_WV12SW.png",
  valid_utc:UTC
 }}};
 const document={getElementById:id=>nodes.get(id),createElementNS(ns,tag){
  return new Element(tag);
 }};
 const win={};
 const context={window:win,document,URL,Date,Intl,Number,String,RegExp,
  setTimeout,clearTimeout,fetch:async url=>{
   calls.push(url);
   return {ok:true,json:async()=>url.includes("fronts_geo.json")?makeGml():official};
  }};
 vm.runInNewContext(js,context,{timeout:3000});
 return {nodes,calls,api:win.SatelliteFrontAnalysis};
}
const settle=()=>new Promise(r=>setTimeout(r,5));
test("No separately displayed original chart, isobars already on satellite, DWD source link remains",()=>{
 assert.ok(!html.includes('id="satDwdFrontAnalysisSection"'));
 assert.ok(!html.includes('id="satFrontImage"'));
 assert.ok(!html.includes('id="satFrontRegion"'));
 assert.ok(html.includes('id="satDwdFrontSvg"'));
 assert.ok(html.includes('id="satShowDwdFronts"'));
 assert.ok(html.includes('id="satShowIsobars" type="checkbox" checked'));
 assert.ok(html.includes('id="satDwdFrontStatus"'));
});
test("Unverified DWD PNG must NEVER be painted as a georeferenced front",async()=>{
 const a=harness();await settle();
 assert.equal(a.nodes.get("satShowDwdFronts").disabled,true);
 assert.equal(a.nodes.get("satDwdFrontSvg").children.length,0);
 assert.equal(a.nodes.get("satDwdFrontSvg").hidden,true);
 assert.match(a.nodes.get("satDwdFrontStatus").textContent,/Noch keine öffentlich zugänglichen/);
 assert.match(a.nodes.get("satDwdFrontSource").href,/opendata\.dwd\.de/);
 assert.equal(a.calls.length,2,"separate official PNG provenance and candidate vector feed");
});
test("Verified official DWD NinJo GML lines use same EPSG:4326 geographic transform as satellite",async()=>{
 const a=harness(validData());await settle();
 const toggle=a.nodes.get("satShowDwdFronts");
 assert.equal(toggle.disabled,false);
 toggle.checked=true;
 a.api.sync({time:MOMENT,region:"europe",source:"mtgi1"});
 const svg=a.nodes.get("satDwdFrontSvg");
 assert.equal(svg.hidden,false);
 assert.equal(svg.children.length,2);
 const first=svg.children[0];
 assert.equal(first.attrs.stroke,"#47a5fa");
 const expectedX=(8-(-27))*1000/(49-(-27));
 const expectedY=(73-50)*1000/(73-24);
 assert.ok(first.attrs.d.startsWith("M"+expectedX.toFixed(2)+" "+expectedY.toFixed(2)));
 assert.match(a.nodes.get("satDwdFrontStatus").textContent,/direkt im Satellitenbild/);
 assert.match(a.nodes.get("satDwdFrontUTC").textContent,/gegenüber dem Satellitenbild/);
 assert.equal(a.api.project([8,50],[-27,24,49,73])[0],expectedX);
});
test("Non-geographic full disk, time missing and time offset >18h strictly hide manual fronts",async()=>{
 const a=harness(validData());await settle();
 a.nodes.get("satShowDwdFronts").checked=true;
 a.api.sync({time:MOMENT,region:"disk",source:"mtgi1"});
 assert.equal(a.nodes.get("satDwdFrontSvg").hidden,true);
 a.api.sync({time:null,region:"europe",source:"mtgi1"});
 assert.equal(a.nodes.get("satDwdFrontSvg").hidden,true);
 a.api.sync({time:new Date(Date.now()+24*3600000).toISOString(),region:"europe",source:"mtgi1"});
 assert.equal(a.nodes.get("satDwdFrontSvg").hidden,true);
 assert.match(a.nodes.get("satDwdFrontStatus").textContent,/auseinander/);
});
test("Refuse forged official maps, unverified sources, wrong CRS, broken coordinates and stale fronts",()=>{
 const a=harness();
 const rejected=[
  {source_url:"https://untrusted.example/dwd.gml"},
  {source_url:DWD+"20261113_fronts.png"},
  {coordinate_reference_system:"EPSG:3857"},
  {georeferencing_verified:false},
  {kind:"forecast"},
  {valid_utc:"2023-01-01T00:00:00Z"},
  {features:[{type:"Feature",properties:{front_type:"warm"},geometry:{type:"LineString",coordinates:[[8,110],[9,48]]}}]},
  {features:[]}
 ];
 for(const change of rejected)assert.equal(a.api.validate(validData(change)),null);
});
test("Date and SVG layer stay separate from ECMWF isobars; old source chart remains official link",async()=>{
 const a=harness(validData());await settle();
 a.nodes.get("satShowDwdFronts").checked=true;
 a.api.sync({time:MOMENT,source:"mtgi1",region:"germany"});
 assert.equal(a.nodes.get("satDwdFrontSvg").hidden,false);
 assert.ok(a.nodes.get("satDwdFrontSvg").children.length>0);
 assert.equal(a.nodes.get("satShowDwdFronts").disabled,false);
 assert.ok(!js.includes("satIsobarSvg"),"manual DWD front layer must not overwrite ECMWF pressure contours");
});
