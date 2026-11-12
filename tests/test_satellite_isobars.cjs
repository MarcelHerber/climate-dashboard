"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const src=fs.readFileSync("satellite_isobars.js","utf8");
const geom=fs.readFileSync("satellite_isobar_geometry.js","utf8");
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
function fixture({failOnce=false,failFirstOnly=false,tenMinutes=false,tenHours=13,fineMode=false}={}){
 const names=["satIsobarSvg","satShowIsobars","satIsobarSpacing","satIsobarStatus","satRetryIsobars","satRegion","satSource"];
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
 let calls=0;
 const sandbox={document:{getElementById:x=>{assert.ok(map.has(x),"missing node "+x);return map.get(x);},
  createElementNS:()=>new FakeElement(),createDocumentFragment:()=>new FakeElement()},
  window:{},Date,console:{warn(){}},fetch:async(url)=>{
   calls++;
   if((failOnce&&calls<=3)||(failFirstOnly&&calls===1))throw Error("Temporary ECMWF asset error");
   if(tenMinutes&&String(url).endsWith("/ten_minute/index.json")){
    return {ok:true,json:async()=>({
     schema_version:2,model:"ECMWF IFS Open Data",
     time_resolution_minutes:10,source_interval_hours:3,
     run_utc:iso(run),generated_at:iso(now),
     hours:Object.fromEntries(Array.from({length:tenHours},(_,h)=>[
      "h"+String(h).padStart(2,"0"),
      "r"+run.toISOString().slice(0,13).replace(/[-T:]/g,"")+"/h"+String(h).padStart(2,"0")+".json"
     ])),
     ...(fineMode?{
      fine_interval_hpa:2,fine_regions:["europe","southwest","central","germany"],
      fine_hours:Object.fromEntries(Array.from({length:tenHours},(_,h)=>[
       "h"+String(h).padStart(2,"0"),
       "r"+run.toISOString().slice(0,13).replace(/[-T:]/g,"")+"/h"+String(h).padStart(2,"0")+"_2hpa.json"
      ]))
     }:{})
    })};
   }
   if(tenMinutes&&String(url).includes("/ten_minute/r")){
    const fine=String(url).endsWith("_2hpa.json");
    const match=String(url).match(/h(\d{2})(?:_2hpa)?\.json$/);
    const hour=Number(match[1]);
    const frames=Array.from({length:hour===tenHours-1?1:6},(_,i)=>{
     const minute=(hour*6+i)*10;
     return {valid_utc:iso(new Date(run.getTime()+minute*60000)),
      forecast_minute:minute,interpolated:minute%180!==0,
      contours:fine?[
       {hpa:1000,lines:frame(3).contours[0].lines},
       {hpa:1002,lines:frame(3).contours[1].lines},
       {hpa:1004,lines:frame(3).contours[2].lines},
       {hpa:1006,lines:frame(3).contours[0].lines},
       {hpa:1008,lines:frame(3).contours[1].lines},
       {hpa:1010,lines:frame(3).contours[2].lines}
      ]:frame(3).contours};
    });
    return {ok:true,json:async()=>({
     schema_version:2,run_utc:iso(run),hour,frames,
     ...(fine?{interval_hpa:2,regions:["europe","southwest","central","germany"]}:{})
    })};
   }
   return {ok:true,json:async()=>data};
  }};
 vm.runInNewContext(geom,sandbox,{timeout:1000});
 vm.runInNewContext(src,sandbox,{timeout:1000});
 return {map,data,api:sandbox.window.SatelliteIsobars,run,getCalls:()=>calls};
}
async function ready(api){
 for(let i=0;i<20;i++){if(api.frameFor(new Date().toISOString()))return;await new Promise(resolve=>setTimeout(resolve,3));}
 throw Error("MSLP fixture not loaded");
}
test("ECMWF layer has explicit controls and synchronizes on satellite still and film frames",()=>{
 for(const id of ["satIsobarSvg","satShowIsobars","satIsobarSpacing","satIsobarStatus"])assert.ok(html.includes('id="'+id+'"'));
 assert.match(html,/src="satellite_isobars\.js(?:\?v=[^"]+)?"/);
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
 assert.match(map.get("satIsobarStatus").textContent,/3-h-Original-Isobaren/);
 assert.match(map.get("satIsobarStatus").textContent,/Satellit/);
 assert.ok(map.get("satIsobarSvg").children.length>0,"SVG contours were not built");
 assert.equal(map.get("satIsobarSvg").hidden,false);
 const bad=new Date(run.getTime()+20*3600000).toISOString();
 assert.equal(api.frameFor(bad),null,"stale pressure forecast wrongly matched");
 api.sync({time:bad,region:"southwest",source:"mtgi1"});
 assert.equal(map.get("satIsobarSvg").hidden,false,"Independently show currently valid pressure rather than an unrelated image match");
 assert.match(map.get("satIsobarStatus").textContent,/nicht zeitgleich/);
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

test("When EUMETSAT time is unavailable, show independent valid ECMWF pressure contours",async()=>{
 const {api,map}=fixture();
 await ready(api);
 api.sync({time:null,region:"southwest",source:"mtgi1"});
 assert.equal(map.get("satIsobarSvg").hidden,false,"Pressure field should render without an image timestamp");
 assert.ok(map.get("satIsobarSvg").children.length>0,"Vector contour paths should exist");
 assert.match(map.get("satIsobarStatus").textContent,/eigenständige ECMWF-Karte ohne Satellitenbild/);
 assert.match(map.get("satIsobarStatus").textContent,/gültig/);
});
test("A failed ECMWF fetch is recoverable with the independent reload control",async()=>{
 const {api,map,getCalls}=fixture({failOnce:true});
 for(let i=0;i<20&&getCalls()<1;i++)await new Promise(resolve=>setTimeout(resolve,3));
 await new Promise(resolve=>setTimeout(resolve,12));
 assert.match(map.get("satIsobarStatus").textContent,/fehlgeschlagen/);
 assert.ok(html.includes('id="satRetryIsobars"'));
 map.get("satRetryIsobars").emit("click");
 await ready(api);
 api.sync({time:null,region:"southwest",source:"mtgi1"});
 assert.equal(map.get("satIsobarSvg").hidden,false);
 assert.ok(getCalls()>=4,"All three sources failed, then manual reload succeeded");
});

test("When fast local preview fails, the full GitHub pressure contours still appear",async()=>{
 const {api,map,getCalls}=fixture({failFirstOnly:true});
 await ready(api);
 assert.equal(map.get("satIsobarSvg").hidden,false);
 assert.match(map.get("satIsobarStatus").textContent,/ECMWF-Originalkonturen|3-h-Original-Isobaren/, "fallback must be honestly labelled as full ECMWF contours");
 assert.ok(getCalls()>=2,"Fallback must use second source once");
});

test("Every 10-minute satellite image picks its own recomputed MSLP contours",async()=>{
 const {map,api,run}=fixture({tenMinutes:true});
 await ready(api);
 const at=new Date(run.getTime()+200*60000).toISOString();
 api.sync({time:at,region:"southwest",source:"mtgi1"});
 for(let i=0;i<45&&!map.get("satIsobarStatus").textContent.includes("10-Minuten-Interpolation");i++){
  await new Promise(done=>setTimeout(done,4));
 }
 const status=map.get("satIsobarStatus").textContent;
 assert.match(status,/10-Minuten-Interpolation/);
 assert.match(status,/gültig/);
 assert.equal(map.get("satIsobarSvg").hidden,false);
 const paths=map.get("satIsobarSvg").children[0]?.children.filter(n=>n.attrs.d)||[];
 assert.ok(paths.some(p=>p.attrs.stroke==="#ff4fcf"),"single pink isobar colour");
 assert.ok(!paths.some(p=>["#ffb447","#3bdeff"].includes(p.attrs.stroke)),"old cyan/amber colours removed");
 assert.ok(paths.some(p=>p.attrs.stroke==="#061522"),"dark halo");
 const frame=api.tenFrameAt(at);
 assert.equal(frame.forecast_minute,200);
 assert.equal(frame.interpolated,true);
});

test("18-hour model coverage permits 10-minute overlays across an entire refresh window",async()=>{
 const {map,api,run}=fixture({tenMinutes:true,tenHours:19});
 await ready(api);
 const target=new Date(run.getTime()+18*3600000).toISOString();
 api.sync({time:target,region:"europe",source:"mtgi1"});
 for(let i=0;i<50&&!api.tenFrameAt(target);i++)await new Promise(ok=>setTimeout(ok,3));
 const selected=api.tenFrameAt(target);
 assert.ok(selected,"No final forecast frame after +18 h");
 assert.equal(selected.forecast_minute,1080);
 assert.equal(selected.interpolated,false);
 assert.equal(map.get("satIsobarSvg").hidden,false);
 assert.match(map.get("satIsobarStatus").textContent,/Original-IFS-Druckfeld/);
});

test("European fine mode displays genuine 2-hPa contours, syncs and exports without 5-hPa disguise",async()=>{
 const {api,map,run}=fixture({tenMinutes:true,tenHours:19,fineMode:true});
 await ready(api);
 const t=new Date(run.getTime()+200*60000).toISOString();
 api.sync({time:t,region:"europe",source:"mtgi1"});
 map.get("satIsobarSpacing").value="2";
 map.get("satIsobarSpacing").emit("change");
 for(let i=0;i<75&&!api.tenFrameAt(t,2);i++)await new Promise(ok=>setTimeout(ok,3));
 const fine=api.tenFrameAt(t,2);
 assert.ok(fine,"2-hPa fine frame must be fetched independently");
 assert.ok(fine.contours.some(x=>x.hpa===1002));
 assert.ok(fine.contours.every(x=>x.hpa%2===0));
 assert.equal(map.get("satIsobarSvg").hidden,false);
 assert.match(map.get("satIsobarStatus").textContent,/2 hPa/);
 const pieces=map.get("satIsobarSvg").children[0]?.children||[];
 assert.ok(pieces.some(x=>x.attrs.stroke==="#ff4fcf"&&x.attrs["stroke-width"]==="0.75"));
 const exported=await api.exportAt(t,"europe",2,{strictTenMinute:true});
 assert.equal(exported.spacing,2);
 assert.ok(exported.contours.every(x=>x.hpa%2===0));
 await assert.rejects(api.exportAt(t,"atlantic",2),/nur für Europa/);
 api.sync({time:t,region:"atlantic",source:"mtgi1"});
 assert.equal(map.get("satIsobarSpacing").value,"5","Atlantic must reset to default 5 hPa");
 api.sync({time:t,region:"disk",source:"mtgi1"});
 assert.equal(map.get("satIsobarSpacing").disabled,true);
});
test("When 2-hPa source chunks have not been generated, no false fine line is displayed or exported",async()=>{
 const {api,map,run}=fixture({tenMinutes:true,tenHours:19,fineMode:false});
 await ready(api);
 const t=new Date(run.getTime()+200*60000).toISOString();
 api.sync({time:t,region:"southwest",source:"mtgi1"});
 map.get("satIsobarSpacing").value="2";
 map.get("satIsobarSpacing").emit("change");
 for(let i=0;i<35;i++)await new Promise(ok=>setTimeout(ok,2));
 assert.equal(api.tenFrameAt(t,2),null);
 assert.equal(map.get("satIsobarSvg").hidden,true);
 assert.match(map.get("satIsobarStatus").textContent,/noch nicht bereitgestellt/);
 await assert.rejects(api.exportAt(t,"southwest",2),/fehlen die berechneten 2-hPa-Konturen/);
});
