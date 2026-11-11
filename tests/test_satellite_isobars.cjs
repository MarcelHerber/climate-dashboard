"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const src=fs.readFileSync("satellite_isobars.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");
const satellite=fs.readFileSync("satelliten.js","utf8");

class FakeElement{
 constructor(){this.value="";this.checked=true;this.disabled=false;this.hidden=true;this.textContent="";this.attrs={};this.children=[];this.listeners={};}
 addEventListener(key,fn){(this.listeners[key]??=[]).push(fn);}
 emit(key){for(const fn of this.listeners[key]||[])fn();}
 toggleAttribute(key,force){if(force){this.attrs[key]="";this.hidden=true;}else{delete this.attrs[key];this.hidden=false;}return force;}
 setAttribute(key,v){this.attrs[key]=v;}
 appendChild(item){this.children.push(item);}
 replaceChildren(...items){this.children=items;}
}
function fixture(){
 const names=["satIsobarSvg","satShowIsobars","satIsobarSpacing","satIsobarStatus","satRegion","satSource"];
 const map=new Map(names.map(x=>[x,new FakeElement()]));
 map.get("satRegion").value="southwest";
 map.get("satSource").value="mtgi1";
 map.get("satIsobarSpacing").value="5";
 const now=new Date(),run=new Date(now.getTime()-6*3600000);
 run.setUTCMinutes(0,0,0);
 const iso=x=>x.toISOString().replace(".000Z","Z");
 const points=[[-48,35],[-40,39],[-30,43],[-25,45],[-18,48],[-8,51]];
 const frame=h=>({valid_utc:iso(new Date(run.getTime()+h*3600000)),forecast_hour:h,contours:[
  {hpa:1000,lines:[points]},{hpa:1005,lines:[points.map(([x,y])=>[x+3,y-1])]},
  {hpa:1010,lines:[points.map(([x,y])=>[x+6,y-2])]}
 ]});
 const data={schema_version:1,generated_at:iso(now),run_utc:iso(run),
  model:"ECMWF IFS Open Data",units:"hPa",field:"mean sea-level pressure",
  resolution_degrees:.25,interval_hpa:5,bbox:[-75,12,55,80],
  frames:[0,3,6,9,12].map(frame)};
 const sandbox={document:{getElementById:x=>{assert.ok(map.has(x),"missing node "+x);return map.get(x);},
  createElementNS:()=>new FakeElement(),createDocumentFragment:()=>new FakeElement()},
  window:{},Date,console:{warn(){}},fetch:async()=>({ok:true,json:async()=>data})};
 vm.runInNewContext(src,sandbox,{timeout:1000});
 return {map,data,api:sandbox.window.SatelliteIsobars,run};
}
async function ready(api){
 for(let i=0;i<20;i++){if(api.frameFor(new Date().toISOString()))return;await new Promise(resolve=>setTimeout(resolve,3));}
 throw Error("MSLP fixture not loaded");
}
test("ECMWF layer has explicit controls and synchronizes on satellite still and film frames",()=>{
 for(const id of ["satIsobarSvg","satShowIsobars","satIsobarSpacing","satIsobarStatus"])assert.ok(html.includes('id="'+id+'"'));
 assert.ok(html.includes('src="satellite_isobars.js"'));
 assert.match(satellite,/SatelliteIsobars\?\.sync\(\{time:t,region/);
 assert.match(satellite,/SatelliteIsobars\?\.sync\(\{time:item\.time,region/);
 assert.doesNotThrow(()=>new vm.Script(src));
});
test("Real metadata interval selects nearest previous valid IFS forecast, never future",async()=>{
 const {api,map,data,run}=fixture();
 await ready(api);
 const t=new Date(run.getTime()+3*3600000+10*60000).toISOString();
 api.sync({time:t,region:"southwest",source:"mtgi1"});
 assert.equal(api.frameFor(t).forecast_hour,3);
 assert.match(map.get("satIsobarStatus").textContent,/\+3 h Vorhersage/);
 assert.match(map.get("satIsobarStatus").textContent,/10 min später/);
 assert.ok(map.get("satIsobarSvg").children.length>0,"SVG contours were not built");
 assert.equal(map.get("satIsobarSvg").hidden,false);
 const bad=new Date(run.getTime()+20*3600000).toISOString();
 assert.equal(api.frameFor(bad),null,"stale pressure forecast wrongly matched");
 api.sync({time:bad,region:"southwest",source:"mtgi1"});
 assert.equal(map.get("satIsobarSvg").hidden,true);
 assert.match(map.get("satIsobarStatus").textContent,/kein passendes/);
});
test("5/10 hPa spacing and disk projection exclusions are safe",async()=>{
 const {api,map,run}=fixture();
 await ready(api);
 const t=new Date(run.getTime()+3*3600000).toISOString();
 api.sync({time:t,region:"southwest",source:"mtgi1"});
 const findPaths=()=>map.get("satIsobarSvg").children[0]?.children.filter(n=>n.attrs.d)||[];
 const all=findPaths().length;
 map.get("satIsobarSpacing").value="10";
 map.get("satIsobarSpacing").emit("change");
 assert.ok(findPaths().length<all);
 assert.ok(findPaths().length>=1);
 map.get("satShowIsobars").checked=false;map.get("satShowIsobars").emit("change");
 assert.equal(map.get("satIsobarSvg").hidden,true);
 map.get("satShowIsobars").checked=true;map.get("satShowIsobars").emit("change");
 assert.equal(map.get("satIsobarSvg").hidden,false);
 api.sync({time:t,region:"disk",source:"mtgi1"});
 assert.equal(map.get("satShowIsobars").disabled,true);
 assert.equal(map.get("satIsobarSvg").hidden,true);
 api.sync({time:t,region:"europe",source:"mtgi2"});
 assert.equal(map.get("satIsobarSvg").hidden,true);
});
