"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("satellite_noaa_fronts.js","utf8");
const url="https://tgftp.nws.noaa.gov/data/raw/as/asus02.kwbc.cod.sus.txt";
const utc=new Date(Date.now()-2*3600000).toISOString().slice(0,16)+"Z";
const sat=new Date(Date.now()-1*3600000).toISOString().slice(0,16)+"Z";
function report(changes={}){
 return {schema_version:1,status:"verified",provider:"NOAA WPC",kind:"analysis",
  coordinate_reference_system:"EPSG:4326",georeferencing_verified:true,
  front_source_format:"CODSUS-HIRES",geographic_precision_degrees:0.1,
  source_url:url,valid_utc:utc,features:[
   {type:"Feature",properties:{front_type:"cold"},geometry:{type:"LineString",coordinates:[[-45,56.3],[-40.8,55.8],[-37.6,53]]}},
   {type:"Feature",properties:{front_type:"warm"},geometry:{type:"LineString",coordinates:[[-24,45],[-17,46]]}},
   {type:"Feature",properties:{front_type:"stationary"},geometry:{type:"LineString",coordinates:[[-54,53],[-52,54]]}}
  ],...changes};
}
function fixture(data=report()){
 class El{
  constructor(id){this.id=id;this.attrs={};this.children=[];this.disabled=false;this.checked=id==="satShowWpcFronts";this.value=id==="satSource"?"mtgi1":"atlantic";this.textContent="";this.href="";this.listeners={};}
  setAttribute(k,v){this.attrs[k]=v;}
  removeAttribute(k){delete this.attrs[k];}
  get hidden(){return Object.hasOwn(this.attrs,"hidden");}
  replaceChildren(){this.children=[];}
  appendChild(el){this.children.push(el);}
  addEventListener(k,fn){this.listeners[k]=fn;}
  fire(k){this.listeners[k]?.();}
 }
 const ids=["satWpcFrontSvg","satShowWpcFronts","satWpcFrontStatus","satWpcFrontUTC","satWpcFrontSource","satRegion","satSource"];
 const nodes=new Map(ids.map(id=>[id,new El(id)]));
 nodes.get("satWpcFrontSvg").setAttribute("hidden","");
 const document={getElementById:id=>nodes.get(id)||null,
  createElementNS:(ns,id)=>new El(id)};
 const window={};
 const ctx={document,window,URL,Date,Intl,Number,String,Math,RegExp,Object,
   setTimeout,clearTimeout,fetch:async()=>({ok:true,json:async()=>data})};
 vm.runInNewContext(source,ctx);
 return {nodes,api:window.SatelliteNOAAFronts};
}
const flush=()=>new Promise(r=>setTimeout(r,8));
test("Published layer is directly in satellite stack, distinct from DWD and ECMWF",()=>{
 const html=fs.readFileSync("satelliten.html","utf8");
 assert.ok(html.includes('id="satWpcFrontSvg"'));
 assert.ok(html.includes('id="satShowWpcFronts"'));
 assert.ok(html.includes('id="satDwdFrontSvg"'));
 assert.ok(html.includes('id="satIsobarSvg"'));
 assert.ok(!html.includes('id="satDwdFrontAnalysisSection"'));
});
test("Confirmed NOAA coordinates are projected by identical geographic bbox",async()=>{
 const a=fixture();await flush();
 assert.equal(a.nodes.get("satShowWpcFronts").disabled,false);
 a.api.sync({time:sat,source:"mtgi1",region:"atlantic"});
 const svg=a.nodes.get("satWpcFrontSvg");
 assert.equal(svg.hidden,false);
 assert.equal(svg.children.length,6,"halo plus colored line for each NOAA front");
 const first=svg.children[1];
 const expectedX=(-45+70)*1000/(35+70),expectedY=(75-56.3)*1000/(75-15);
 assert.equal(first.attrs.stroke,"#48a8ff");
 assert.ok(first.attrs.d.startsWith("M"+expectedX.toFixed(2)+" "+expectedY.toFixed(2)));
 assert.match(a.nodes.get("satWpcFrontStatus").textContent,/NOAA-WPC-Frontlinien/);
 assert.equal(a.nodes.get("satWpcFrontSource").href,url);
});
test("Expired, forged, invalid or mixed-provider frames cannot create a false map",async()=>{
 const a=fixture({schema_version:1,status:"unavailable",features:[]});await flush();
 assert.equal(a.nodes.get("satShowWpcFronts").disabled,true);
 assert.equal(a.nodes.get("satWpcFrontSvg").hidden,true);
 for(const bad of [
  {provider:"DWD"},{source_url:"https://evil.example/data.txt"},
  {front_source_format:"CODSUS-LOWRES"},{coordinate_reference_system:"EPSG:3857"},
  {georeferencing_verified:false},{valid_utc:"2026-10-01T12:00Z"},
  {features:[{type:"Feature",properties:{front_type:"warm"},geometry:{type:"LineString",coordinates:[[400,52],[-20,50]]}}]}
 ])assert.equal(a.api.validate(report(bad)),null);
});
test("If chosen satellite UTC diverges by over twelve hours, never draw NOAA fronts",async()=>{
 const a=fixture();await flush();
 a.api.sync({time:new Date(Date.now()+24*3600000).toISOString(),region:"atlantic",source:"mtgi1"});
 assert.equal(a.nodes.get("satWpcFrontSvg").hidden,true);
 assert.match(a.nodes.get("satWpcFrontStatus").textContent,/mehr als 12 Stunden/);
 a.api.sync({time:sat,region:"disk",source:"mtgi1"});
 assert.equal(a.nodes.get("satWpcFrontSvg").hidden,true);
 assert.equal(a.nodes.get("satShowWpcFronts").disabled,true);
});
test("No WPC front falls in Germany while western Atlantic is available; never invent a European analysis",async()=>{
 const a=fixture();await flush();
 a.api.sync({time:sat,source:"mtgi1",region:"germany"});
 assert.equal(a.nodes.get("satWpcFrontSvg").hidden,true);
 assert.equal(a.nodes.get("satShowWpcFronts").disabled,true);
 assert.match(a.nodes.get("satWpcFrontStatus").textContent,/westlichen Nordatlantik/);
});
