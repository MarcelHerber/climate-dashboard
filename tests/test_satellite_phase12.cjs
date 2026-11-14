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

test("Additional FCI products are disclosed only after real MTG GetMap checks",()=>{
 const main=fs.readFileSync("satelliten.js","utf8");
 const audit=fs.readFileSync("scripts/audit_satellite_layers.py","utf8");
 assert.match(main,/report\.capabilities_ok/);
 assert.match(main,/x\.map_ok&&x\.tested&&x\.recent/);
 assert.match(main,/\^mtg_fd:/);
 for(const name of ["extra_airmass","extra_night_microphysics","extra_convection",
  "extra_cloud_phase","extra_true_colour","extra_visible_06"])
  assert.ok(main.includes(name),"Missing RGB guide: "+name);
 assert.ok(audit.includes('"true_colour"')&&audit.includes('"visible_06"'));
 assert.ok(html.includes('id="satProductGuide"'));
 assert.ok(html.includes("nur tatsächlich nachgewiesene Produkte"));
 assert.ok(main.includes('group.append(new Option(label+" · geprüft",code))'));
 assert.ok(!main.includes("opt.disabled=true"),"Unavailable RGBs should be described, not shown as grey menu options");
 for(const layer of ['"fog"','"snow"'])assert.ok(audit.includes(layer),"Official WMS category missing "+layer);
 for(const guide of ["extra_fog","extra_snow"])assert.ok(main.includes(guide));
});
test("Decoded frame cache is bounded and keyed by the exact verified WMS request",()=>{
 const main=fs.readFileSync("satelliten.js","utf8");
 assert.match(main,/const PREVIEW_CACHE_LIMIT=/);
 assert.match(main,/const PREVIEW_CACHE_TTL=15\*60\*1000/);
 assert.match(main,/previewCache\.get\(url\)/);
 assert.match(main,/savePreview\(url,im\)/);
 assert.match(main,/aus Vorschaucache/);
});

test("Long satellite explanations live below the picture in three closed, accessible panels",()=>{
 const main=fs.readFileSync("satelliten.js","utf8");
 const css=fs.readFileSync("satelliten.css","utf8");
 const picture=html.indexOf('id="satPictureFrame"');
 const details=html.indexOf('id="satImageDetails"');
 assert.ok(picture>0&&details>picture,"Detailed descriptions must follow the real satellite picture");
 for(const section of ["satProductDetails","satDataDetails","satTechDetails"]){
  assert.match(html,new RegExp('<details class="sat-image-accordion" id="'+section+'">'));
 }
 for(const id of ["satProductGuide","satIsobarStatus","satAdditionalStatus"]){
  const match=html.match(new RegExp('id="'+id+'"','g'))||[];
  assert.equal(match.length,1,id+" preserved exactly once for live update");
  assert.ok(html.indexOf('id="'+id+'"')>details,id+" must be below the image");
 }
 for(const phrase of ["Der Film lädt die gewählten Aufnahmen","Zum Verschieben das vergrößerte Bild","Standardmäßig werden 5-hPa-Isobaren"]){
  assert.ok(html.includes(phrase));
  assert.ok(!html.slice(0,picture).includes(phrase),"Long note displayed before the picture: "+phrase);
 }
 assert.match(html,/id="satIsobarBrief" role="status" aria-live="polite"/);
 assert.match(main,/function initIsobarBrief\(\)/);
 assert.match(main,/new MutationObserver\(update\)/);
 assert.match(css,/\.sat-image-accordion summary:focus-visible/);
 assert.match(css,/@media\(max-width:650px\)/);
});
