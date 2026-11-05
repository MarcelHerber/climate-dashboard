const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const source=fs.readFileSync("saharastaub.js","utf8");
const page=fs.readFileSync("saharastaub.html","utf8");
const builder=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const nav=fs.readFileSync("mobile_navigation.js","utf8");
test("Saharastaub pages included in Pages build and mobile menu",()=>{
  for(const path of ["saharastaub.html","saharastaub.css","saharastaub.js"])assert.ok(builder.includes("  "+path+"\n"));
  assert.ok(nav.includes('["saharastaub.html","Saharastaub · ICON-ART"]'));
  for(const id of ["dustMap","dustParameter","dustRegion","dustTime","dustLegend","dustPng"])assert.ok(page.includes('id="'+id+'"'));
});
test("Palette thresholds constant across times and map regions",()=>{
  assert.ok(source.includes('breaks:[0.02,0.05,0.1,0.2,0.4,0.7,1,1.5,2.5]'));
  assert.ok(source.includes('breaks:[1,10,25,50,100,200,400,800,1600]'));
  assert.ok(source.includes('JSON.stringify(server.breaks)!==JSON.stringify(param.breaks)'));
  assert.ok(source.includes('boundsLabel(i,param.breaks)'));
  assert.ok(source.includes('canvas.toBlob'));
  assert.ok(source.includes('controls.region.addEventListener("change",render)'));
});
