"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const html=fs.readFileSync("satelliten.html","utf8");
const build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const sources=Object.fromEntries(["satellite_view_options.js","satellite_lightning.js","satellite_radar.js"].map(name=>[name,fs.readFileSync(name,"utf8")]));
test("Phase 1/2 assets are in deploy and parse",()=>{
 for(const [name,body] of Object.entries(sources)){
  assert.ok(html.includes('src="'+name+'?'),name+" must load from page");
  assert.ok(build.includes("  "+name+"\n"),name+" must be deployed");
  assert.doesNotThrow(()=>new vm.Script(body),name+" syntax");
 }
});
test("Opt-in layers and viewport controls have accessible labels",()=>{
 for(const id of ["satShowLightning","satLightningWindow","satLightningStatus","satLightningOverlay",
 "satShowRadar","satRadarOpacity","satRadarStatus","satRadarOverlay","satZoomIn","satZoomOut",
 "satZoomReset","satZoomValue","satIRPreset"]){
  assert.ok(html.includes('id="'+id+'"'),"Missing "+id);
 }
 assert.match(html,/id="satShowLightning" type="checkbox"/);
 assert.match(html,/id="satShowRadar" type="checkbox"/);
 assert.match(html,/kalibrierten Temperaturwerte/);
 assert.match(html,/RainViewer/);
});
test("Lightning cannot claim a time without verified LI GetMap metadata",()=>{
 const source=sources["satellite_lightning.js"];
 assert.match(source,/entry\.map_ok/);
 assert.match(source,/entry\.latest_verified_time/);
 assert.match(source,/Date\.parse\(t\)\+5\*60000<=target/);
 assert.match(source,/10\*60000/);
 assert.match(source,/LI-Bildabruf nicht vollständig/);
});
test("Radar uses matched past timestamps and genuine Mercator reprojection",()=>{
 const source=sources["satellite_radar.js"];
 assert.match(source,/radar\.past/);
 assert.match(source,/20\*60000/);
 assert.match(source,/Math\.asinh\(Math\.tan\(/);
 assert.match(source,/ctx\.drawImage\(merc/);
 assert.match(source,/satFilmStage/);
 assert.match(source,/rainviewer\.com/);
});
