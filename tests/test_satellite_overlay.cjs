"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const html=fs.readFileSync("satelliten.html","utf8");
const js=fs.readFileSync("satellite_overlay.js","utf8");
const css=fs.readFileSync("satelliten.css","utf8");
const build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const geo=JSON.parse(fs.readFileSync("data/blocking/borders_50m.json","utf8"));
function node(){
 return {hidden:false,disabled:false,checked:true,value:"",textContent:"",style:{},children:[],
  attrs:{},listeners:{},
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn)},
  fire(type){for(const fn of this.listeners[type]||[])fn()},
  replaceChildren(...items){this.children=items},
  appendChild(el){this.children.push(el)},
  setAttribute(k,v){this.attrs[k]=v},
  toggleAttribute(k,force){if(force){this.attrs[k]="";if(k==="hidden")this.hidden=true;}else{delete this.attrs[k];if(k==="hidden")this.hidden=false;}return Boolean(force)}
 };
}
async function fixture(projected=false){
 const names=["satImageStack","satBordersSvg","satCitiesLayer","satShowBorders","satShowCities",
  "satOverlayHint","satRegion","satSource"];
 const els=Object.fromEntries(names.map(k=>[k,node()]));
 els.satRegion.value="southwest";els.satSource.value="mtgi1";
 const sandbox={
  document:{getElementById:id=>els[id],createElement:()=>node(),
   createElementNS:()=>node()},
  window:{},console:{warn(){}},
  fetch:async url=>{if(projected&&url==="./data/satellite_borders_50m.json")return{ok:true,json:async()=>JSON.parse(fs.readFileSync("data/satellite_borders_50m.json","utf8"))};assert.equal(url,"./data/blocking/borders_50m.json");return{ok:true,json:async()=>geo}}
 };
 if(projected)vm.runInNewContext(fs.readFileSync("satellite_projection.js","utf8"),sandbox);
 vm.runInNewContext(js,sandbox,{timeout:1000});
 for(let i=0;i<12&&!els.satBordersSvg.children.length;i++){
  await new Promise(resolve=>setTimeout(resolve,5));
 }
 els.overlay=sandbox.window.SatelliteOverlay;
 return els;
}
test("Natural Earth geography covers the Azores, Madeira, Canaries, Newfoundland and Iceland",()=>{
 assert.equal(geo.schema_version,1);
 assert.match(geo.source,/Natural Earth/);
 assert.ok(geo.lines.length>=400);
 const boxes={azores:[-32,-23,35,42],canaries:[-19,-12,27,30],
  madeira:[-19,-15,31,34],newfoundland:[-59,-49,45,51],iceland:[-26,-12,62,68]};
 for(const [name,b] of Object.entries(boxes)){
  const found=geo.lines.some(line=>line.some(([x,y])=>x>=b[0]&&x<=b[1]&&y>=b[2]&&y<=b[3]));
  assert.ok(found,"Missing real 50m coastline near "+name);
 }
});
test("Borders and cities line up with the southwest EPSG:4326 WMS viewport",async()=>{
 const e=await fixture();
 assert.equal(e.satBordersSvg.hidden,false);
 assert.ok(e.satBordersSvg.children.length>0,"No vector path drawn");
 assert.equal(e.satBordersSvg.children[0].attrs["vector-effect"],"non-scaling-stroke");
 assert.equal(e.satImageStack.style.aspectRatio,"1200/620");
 assert.ok(e.satBordersSvg.children[0].attrs.d.length>1000);
 const names=e.satCitiesLayer.children.map(x=>x.textContent);
 for(const name of ["Ponta Delgada","Funchal","Las Palmas","Lissabon","Madrid"]){
  assert.ok(names.includes(name),"No label for "+name);
 }
 const a=e.satCitiesLayer.children.find(x=>x.textContent==="Ponta Delgada");
 const expectedX=(-25.67+37)/(19+37)*100;
 const expectedY=(53-37.74)/(53-24)*100;
 assert.ok(Math.abs(parseFloat(a.style.left)-expectedX)<0.002);
 assert.ok(Math.abs(parseFloat(a.style.top)-expectedY)<0.002);
});
test("Overlays are togglable and safely suppressed without disk projection helper and on MTG-I2",async()=>{
 const e=await fixture();
 e.satShowBorders.checked=false;e.satShowBorders.fire("change");
 assert.equal(e.satBordersSvg.hidden,true);
 assert.equal(e.satCitiesLayer.hidden,false);
 e.satShowBorders.checked=true;e.satShowBorders.fire("change");
 assert.equal(e.satBordersSvg.hidden,false);
 e.satRegion.value="disk";e.satRegion.fire("change");
 assert.equal(e.satBordersSvg.hidden,true);
 assert.equal(e.satCitiesLayer.hidden,true);
 assert.equal(e.satShowBorders.disabled,true);
 assert.match(e.satOverlayHint.textContent,/geostationär/);
 assert.equal(e.satImageStack.style.aspectRatio,"1 / 1");
 e.satSource.value="mtgi2";e.satSource.fire("change");
 assert.equal(e.satImageStack.hidden,true);
 e.satSource.value="mtgi1";e.satRegion.value="atlantic";e.satRegion.fire("change");
 assert.equal(e.satImageStack.hidden,false);
 assert.equal(e.satBordersSvg.hidden,false);
 assert.ok(e.satCitiesLayer.children.some(x=>x.textContent==="Nuuk"));
 assert.match(e.satOverlayHint.textContent,/südlich 25°N/);
});
test("Whole-disc border data and geostationary city overlays work on screen and export",async()=>{
 const world=JSON.parse(fs.readFileSync("data/satellite_borders_50m.json","utf8"));
 assert.equal(world.schema_version,1);
 assert.match(world.source,/Natural Earth 1:50m/);
 const points=world.lines.flat();
 // Distinct coasts in the old footprint's newly covered sectors.
 for(const [west,south,east,north] of [[-18,3,-15,15],[-37,-7,-30,-3],[16,-35,20,-28],[49,17,60,28]]){
  assert.ok(points.some(([lon,lat])=>lon>=west&&lon<=east&&lat>=south&&lat<=north));
 }
 const e=await fixture(true);
 // HD export has its own borders choice, independent of the screen toggle.
 e.satShowBorders.checked=false;
 e.satRegion.value="disk";e.satRegion.fire("change");
 for(let i=0;i<30&&!e.satOverlayHint.textContent.includes("WGS84");i++)await new Promise(r=>setTimeout(r,10));
 assert.match(e.satOverlayHint.textContent,/WGS84/);
 assert.equal(e.satBordersSvg.hidden,true);
 e.satShowBorders.checked=true;e.satShowBorders.fire("change");
 assert.equal(e.satShowBorders.disabled,false);
 assert.equal(e.satBordersSvg.hidden,false);
 assert.ok(e.satBordersSvg.children[0].attrs.d.length>10000);
 assert.ok(e.satCitiesLayer.children.some(x=>x.textContent==="Johannesburg"));
 const anchors=e.overlay.cityAnchors("disk");
 assert.ok(anchors.some(x=>x.name==="Johannesburg"));
 const calls=[],labels=[];
 const ctx={save(){},restore(){},beginPath(){},rect(){},clip(){},moveTo(x,y){calls.push([x,y])},lineTo(x,y){calls.push([x,y])},stroke(){},arc(){},fill(){},strokeText(){},fillText(name,x,y){labels.push([name,x,y])}};
 assert.ok(e.overlay.paintBorders(ctx,"disk",{width:1400,height:1400})>100);
 assert.ok(calls.some(([,y])=>y>700));
 assert.ok(e.overlay.paintCities(ctx,"disk",{width:1400,height:1400})>10);
 assert.ok(labels.some(([name,x,y])=>name==="Johannesburg"&&x>700&&y>700));
 e.satRegion.value="north";e.satRegion.fire("change");
 assert.equal(e.satShowBorders.disabled,false);
 assert.equal(e.satBordersSvg.hidden,false);
 assert.equal(e.satImageStack.style.aspectRatio,"1400/700");
 assert.ok(!e.satCitiesLayer.children.some(x=>x.textContent==="Johannesburg"));
 calls.length=0;
 assert.ok(e.overlay.paintBorders(ctx,"north",{width:1400,height:700})>100);
 assert.ok(calls.every(([x,y])=>x>=0&&x<=1400&&y>=0&&y<=700));
 labels.length=0;
 assert.ok(e.overlay.paintCities(ctx,"north",{width:1400,height:700})>5);
 assert.ok(labels.every(([name,x,y])=>name!=="Johannesburg"&&x>=0&&x<=1400&&y>=0&&y<=700));
});
test("Satellite overlay assets are built and mobile controls remain accessible",()=>{
 assert.match(html,/<script defer src="satellite_overlay\.js(?:\?[^"]+)?"><\/script>/);
 for(const k of ["satImageStack","satBordersSvg","satCitiesLayer","satShowBorders","satShowCities"]){
  assert.ok(html.includes('id="'+k+'"'));
 }
 assert.ok(build.includes("  satellite_overlay.js\n"));
 assert.ok(build.includes("cp data/blocking/borders_50m.json _site/data/blocking/borders_50m.json"));
 assert.ok(build.includes("node --test tests/test_satellite_overlay.cjs"));
 assert.ok(css.includes(".sat-image-stack"));
 assert.ok(css.includes("@media(max-width:650px)"));
 assert.doesNotThrow(()=>new vm.Script(js));
});
