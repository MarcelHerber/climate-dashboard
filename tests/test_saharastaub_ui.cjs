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
  assert.ok(builder.includes("  saharastaub_extended.js\\n".replace("\\n","\n")));
  for(const id of ["dustMap","dustParameter","dustRegion","dustTime","dustLegend","dustPng","dustView","dustSeries"])assert.ok(page.includes('id="'+id+'"'));
});
test("Saharastaub belongs to Sonstiges across desktop and mobile navigation",()=>{
  const homepage=fs.readFileSync("index.html","utf8");
  const misc=homepage.split('<div class="nav-dropdown" data-nav-group="misc">')[1]?.split('</div>\n      </div>')[0]||"";
  const europe=homepage.split('<div class="nav-dropdown" data-nav-group="europe">')[1]?.split('<div class="nav-dropdown" data-nav-group="misc">')[0]||"";
  assert.ok(misc.includes("window.location.href='saharastaub.html'"),"desktop Sonstiges entry missing");
  assert.ok(!europe.includes("saharastaub.html"),"Saharastaub should not appear under Europa");
  assert.ok(homepage.includes('["saharastaub.html","Sonstiges · Saharastaub-Monitor (ICON-ART-EU)"]'));
  const mobileSonstiges=nav.split('{id:"tools",name:"Sonstiges",items:[')[1]?.split(']}')[0]||"";
  assert.ok(mobileSonstiges.includes('["saharastaub.html","Saharastaub · ICON-ART"]'));
  const mobileEuropa=nav.split('{id:"europe",name:"Europa & Prognosen",items:[')[1]?.split(']}')[0]||"";
  assert.ok(!mobileEuropa.includes("saharastaub.html"),"mobile menu should have only one destination");
  assert.ok(!builder.includes('marker=\'id="saharastaub-quicklink"\''),"standalone header banner still injected");
});
test("Palette thresholds constant across times and map regions",()=>{
  assert.ok(source.includes('breaks:[0.05,0.1,0.2,0.35,0.5,0.75,1,1.5,2.5]'));
  assert.ok(source.includes('breaks:[25,50,100,200,400,800,1600,2500,4000]'));
  assert.ok(source.includes('JSON.stringify(server.breaks)!==JSON.stringify(param.breaks)'));
  assert.ok(source.includes('boundsLabel(i,param.breaks)'));
  assert.ok(source.includes('canvas.toBlob'));
  assert.ok(source.includes('"#f2f4f7"'));
  assert.ok(source.includes('"#5a2875"'));
  assert.ok(page.includes('id="dustHideBackground"'));
  assert.ok(source.includes("const hiddenBackground=controls.hide.checked"));
  assert.ok(source.includes('value<=1') && source.includes("img.data[src+3]=0"));
  assert.ok(source.includes('controls.region.addEventListener("change",render)'));
});
