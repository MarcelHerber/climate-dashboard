"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
function fixture(script){
 const ids=["satWpcFrontSvg","satShowWpcFronts","satWpcFrontStatus","satWpcFrontUTC",
  "satWpcFrontSource","satDwdFrontSvg","satShowDwdFronts","satDwdFrontStatus",
  "satDwdFrontUTC","satDwdFrontSource","satDwdFrontRefresh","satRegion","satSource"];
 class El{
  constructor(id){this.attrs={};this.children=[];this.checked=true;this.disabled=false;
   this.value=id==="satSource"?"mtgi1":"atlantic";this.textContent="";this.listeners={};}
  setAttribute(key,value){this.attrs[key]=value;}
  removeAttribute(key){delete this.attrs[key];}
  replaceChildren(){this.children=[];}
  addEventListener(event,fn){this.listeners[event]=fn;}
 }
 const nodes=new Map(ids.map(id=>[id,new El(id)]));
 const wpc=nodes.get("satWpcFrontSvg"),dwd=nodes.get("satDwdFrontSvg");
 wpc.children=[{attrs:{d:"M10 10"}}];dwd.children=[{attrs:{d:"M10 10"}}];
 let calls=0;const window={SatelliteFrontsPaused:true};
 const ctx={window,document:{getElementById:id=>nodes.get(id)||null},
  URL,Date,Intl,Number,String,Math,RegExp,Object,
  fetch:async()=>{calls++;throw Error("Front-data fetch attempted while paused");},
  setTimeout,clearTimeout};
 vm.runInNewContext(fs.readFileSync(script,"utf8"),ctx,{timeout:5000});
 return {nodes,window,calls:()=>calls};
}
test("No NOAA layer, source fetch or export when paused, even after a synthetic toggle",()=>{
 const f=fixture("satellite_noaa_fronts.js");
 const toggle=f.nodes.get("satShowWpcFronts"),svg=f.nodes.get("satWpcFrontSvg");
 assert.equal(toggle.checked,false);
 assert.equal(toggle.disabled,true);
 assert.ok(Object.hasOwn(svg.attrs,"hidden"));
 assert.equal(svg.children.length,0);
 toggle.checked=true;f.window.SatelliteNOAAFronts.sync({time:new Date().toISOString(),region:"atlantic",source:"mtgi1"});
 assert.equal(toggle.checked,false);
 assert.equal(f.window.SatelliteNOAAFronts.exportAt(new Date().toISOString(),"atlantic"),null);
 assert.equal(svg.children.length,0);
 assert.equal(f.calls(),0);
});
test("No DWD front lines or external fetches while paused",()=>{
 const f=fixture("satellite_dwd_fronts.js");
 const toggle=f.nodes.get("satShowDwdFronts"),svg=f.nodes.get("satDwdFrontSvg");
 assert.equal(toggle.checked,false);
 assert.equal(toggle.disabled,true);
 assert.equal(svg.children.length,0);
 assert.ok(Object.hasOwn(svg.attrs,"hidden"));
 toggle.checked=true;f.window.SatelliteFrontAnalysis.sync({time:new Date().toISOString(),region:"atlantic",source:"mtgi1"});
 assert.equal(toggle.checked,false);
 assert.equal(svg.children.length,0);
 assert.equal(f.calls(),0);
});
test("Public satellite page hides both front selectors while retaining ECMWF isobars",()=>{
 const html=fs.readFileSync("satelliten.html","utf8");
 const css=fs.readFileSync("satelliten.css","utf8");
 const js=fs.readFileSync("satelliten.js","utf8");
 const hd=fs.readFileSync("satellite_hd.js","utf8");
 assert.match(html,/window\.SatelliteFrontsPaused\s*=\s*true/);
 assert.match(html,/<label hidden><input id="satShowWpcFronts"/);
 assert.match(html,/<label hidden><input id="satShowDwdFronts"/);
 assert.match(html,/id="satSynopticOverlaySection" hidden/);
 assert.match(html,/id="satShowIsobars" type="checkbox" checked/);
 assert.match(html,/PNG mit Isobaren ↓/);
 assert.match(html,/Vektor-PDF mit Isobaren ↓/);
 assert.match(html,/GIF mit Isobaren ↓/);
 assert.match(css,/#satSynopticOverlaySection\[hidden\]/);
 assert.match(js,/frontOverlays:withFronts\?frontOverlays:null/);
 assert.match(hd,/SatelliteFrontsPaused===true\?null/);
});
