"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("satellite_front_style.js","utf8");
const sandbox={window:{},Math,Object,Array,Number,String};vm.runInNewContext(source,sandbox);
const F=sandbox.window.SatelliteFrontStyle;
const front=type=>({type,coords:[[10,20],[45,24],[80,22],[115,25],[155,29],[200,30]],
 symbol_orientation_verified:false});
const numeric=(v)=>JSON.parse(JSON.stringify(v));
test("Shared front style keeps original NOAA vertices with tiny bezier handles",()=>{
 const input=front("cold"),g=F.layout(input,p=>p,1);
 assert.equal(g.commands[0][0],"M");assert.deepEqual(numeric(g.commands[0].slice(1)),[10,20]);
 assert.ok(g.commands.every((c,i)=>i===0||c[0]==="C"));
 g.commands.slice(1).forEach((c,i)=>assert.deepEqual(numeric(c.slice(-2)),input.coords[i+1]));
 assert.ok(!g.orientationVerified,"CODSUS does not encode front-side motion");
 assert.ok(g.symbols.length>1,"Long fronts carry a limited number of small type marks");
});
test("Kalt/Warm/Okklusion: classic low-contrast pips, stationary alternating blue/red and opposite sides",()=>{
 const cold=F.layout(front("cold"),p=>p,1),warm=F.layout(front("warm"),p=>p,1),
  occl=F.layout(front("occluded"),p=>p,1),stationary=F.layout(front("stationary"),p=>p,1);
 assert.ok(cold.symbols.every(x=>x.shape==="triangle"&&x.color==="#5998c9"));
 assert.ok(warm.symbols.every(x=>x.shape==="arc"&&x.color==="#d77a76"));
 assert.ok(occl.symbols.some(x=>x.shape==="arc")&&occl.symbols.some(x=>x.shape==="triangle"));
 assert.ok(stationary.sections.some(x=>x.color==="#5998c9"));
 assert.ok(stationary.sections.some(x=>x.color==="#d77a76"));
 assert.ok(stationary.symbols.some(x=>x.color==="#5998c9"));
 assert.ok(stationary.symbols.some(x=>x.color==="#d77a76"));
 assert.ok(stationary.symbols.every(x=>x.commands.at(-1)[0]==="Z"));
});
test("No false motion claim: only explicit verified source side is accepted",()=>{
 const a=F.layout({...front("cold"),symbol_orientation_verified:false,symbol_side:"left"},p=>p,1);
 const b=F.layout({...front("cold"),symbol_orientation_verified:true,symbol_side:"right"},p=>p,1);
 assert.equal(a.orientationVerified,false);
 assert.equal(b.orientationVerified,true);
 assert.notDeepEqual(numeric(a.symbols[0].commands),numeric(b.symbols[0].commands));
});
test("SVG, Canvas and PDF all consume same generated Bezier and symbol geometry",()=>{
 const js=fs.readFileSync("satellite_noaa_fronts.js","utf8"),
  exp=fs.readFileSync("satellite_map_export.js","utf8"),
  html=fs.readFileSync("satelliten.html","utf8"),
  build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
 assert.ok(html.includes('src="satellite_front_style.js?v='));
 assert.ok(html.indexOf('src="satellite_front_style.js')<html.indexOf('src="satellite_map_export.js'));
 assert.match(js,/style\.layout\(feature/);
 assert.match(exp,/style\.layout\(f,/);
 assert.match(exp,/ctx\.bezierCurveTo/);
 assert.match(exp,/" c"/);
 assert.match(exp,/pdfCommands\(glyph\.commands/);
 assert.ok(build.includes("satellite_front_style.js"));
 assert.match(html,/Symbolseite ist schematisch/);
});
