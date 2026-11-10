"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const html=fs.readFileSync("satelliten.html","utf8");
const js=fs.readFileSync("satelliten.js","utf8");
const css=fs.readFileSync("satelliten.css","utf8");
const mobile=fs.readFileSync("mobile_navigation.js","utf8");
const build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
test("Meteosat viewer assets included in Pages deployment",()=>{
 for(const path of ["satelliten.html","satelliten.css","satelliten.js"])assert.ok(build.includes("  "+path+"\n"),path+" missing from build");
 assert.ok(mobile.includes('["satelliten.html","Satelliten · MTG"]'));
 assert.ok(mobile.includes('satelliteLink.href="./satelliten.html"'));
 assert.ok(html.includes("mobile_navigation.js"));
 assert.ok(html.includes("dashboard_theme.js"));
});
test("Meteosat viewer shows only documented official products and honest source status",()=>{
 for(const layer of ["mtg_fd:rgb_geocolour","mtg_fd:rgb_dust","mtg_fd:rgb_cloudtype"])assert.ok(js.includes(layer),layer);
 assert.ok(js.includes('request:"GetCapabilities"'));
 assert.ok(js.includes('layerTimes(xml,description().layer)'));
 assert.ok(js.includes("Der Aufnahmezeitpunkt ist noch nicht verifiziert"));
 assert.ok(js.includes('source.value==="mtgi2"'));
 assert.ok(html.includes("kein Livestream"));
 assert.ok(html.includes("ESA-Erstbilder"));
 assert.ok(js.includes('if(t)params.set("time",t)'));
 assert.ok(js.includes('transparent:"false"'));
 assert.ok(js.includes('version:"1.1.1"'));
});
test("Accessible mobile layout and labelled export",()=>{
 for(const id of ["satSource","satProduct","satRegion","satTime","satPrev","satPlay","satNext","satPng","satStatus","satImage"])assert.ok(html.includes('id="'+id+'"'),id+" control missing");
 assert.ok(html.includes('aria-live="polite"'));
 assert.ok(css.includes("@media(max-width:650px)"));
 assert.ok(js.includes('crossOrigin="anonymous"'));
 assert.ok(js.includes('ctx.fillText("© EUMETSAT"'));
 assert.ok(js.includes('time.addEventListener("change"'));
 assert.ok(js.includes('visibilitychange'));
});
test("Satelliten viewer JavaScript parses",()=>{assert.doesNotThrow(()=>new vm.Script(js));});
