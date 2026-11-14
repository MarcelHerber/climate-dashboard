"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const geometry=fs.readFileSync("satellite_isobar_geometry.js","utf8");
const bbox=[-27,24,49,73];
function shared(){
 const sandbox={window:{},Math,Number};
 vm.runInNewContext(geometry,sandbox,{timeout:3000});
 return sandbox.window.SatelliteIsobarGeometry;
}
function location(nx,ny){
 return [bbox[0]+nx/1000*(bbox[2]-bbox[0]),
         bbox[3]-ny/1000*(bbox[3]-bbox[1])];
}
function loop(x,y,r,steps=14){
 const line=Array.from({length:steps},(_,i)=>
  location(x+r*Math.cos(2*Math.PI*i/steps),
           y+r*Math.sin(2*Math.PI*i/steps)));
 return [...line,line[0]];
}
test("Tiny closed contour artifacts are removed while coherent low-pressure rings survive",()=>{
 const g=shared();
 const microscopic=loop(500,600,3);
 const island=loop(520,610,8);
 const synoptic=loop(330,320,65);
 const result=g.prepare([{hpa:1015,lines:[microscopic,island,synoptic]}],bbox,5);
 assert.equal(result.length,1);
 assert.equal(result[0].runs.length,1,"keep only the meaningful closed contour");
 assert.equal(result[0].heavy,true);
 assert.ok(result[0].runs[0].length>synoptic.length);
 const smoothed=result[0].runs[0];
 assert.deepEqual(Array.from(smoothed[0]),Array.from(smoothed.at(-1)),"closed loop stays closed");
});
test("Very short detached fragments disappear; long open pressure lines retain their end points",()=>{
 const g=shared();
 const tiny=[location(320,400),location(324,400),location(326,401)];
 const long=[location(100,100),location(170,112),location(210,125),location(280,118),location(380,110)];
 const result=g.prepare([{hpa:1010,lines:[tiny,long]}],bbox,5);
 assert.equal(result[0].runs.length,1);
 const kept=result[0].runs[0];
 assert.deepEqual(Array.from(kept[0]),long[0]);
 assert.deepEqual(Array.from(kept.at(-1)),long.at(-1));
});
test("One bounded Chaikin pass makes bends rounder without moving points far from the original contour",()=>{
 const g=shared();
 const original=[location(120,300),location(180,315),location(200,345),location(245,350),location(310,340)];
 const clean=g.clean(original,bbox);
 const result=g.smooth(clean);
 assert.equal(result.length,original.length*2);
 for(const p of result){
  const projected=g.project(p,bbox);
  const maxMove=Math.min(...original.map(o=>{
   const q=g.project(o,bbox);return Math.hypot(projected[0]-q[0],projected[1]-q[1]);
  }));
  assert.ok(maxMove<=2.401,"geometric smoothing must be limited to 2.4 normalized map units");
 }
});
test("Preparation preserves real ECMWF source contours and hides only display fragments",()=>{
 const g=shared();
 const data=[{hpa:1010,lines:[loop(350,390,4),loop(350,390,45)]},
             {hpa:1015,lines:[[location(100,600),location(260,580),location(450,500)]]}];
 const before=JSON.stringify(data);
 const groups=g.prepare(data,bbox,5);
 assert.equal(JSON.stringify(data),before,"never alter underlying model contours");
 assert.equal(groups.length,2);
 assert.equal(groups[0].runs.length,1);
 assert.equal(groups[1].heavy,true);
 assert.ok(g.settings.minLoopDiagonal>0);
});

test("Nested closed contours infer significant T and H, not guessed labels",()=>{
 const g=shared(),b=[-70,15,35,75];
 function ring(lon,lat,r){
  return Array.from({length:65},(_,i)=>{
   const t=2*Math.PI*i/64;return [lon+r*Math.cos(t),lat+r*.6*Math.sin(t)];
  });
 }
 const original=[
  {hpa:995,lines:[ring(-53,55,3)]},
  {hpa:1000,lines:[ring(-53,55,6)]},
  {hpa:1005,lines:[ring(-53,55,10)]},
  {hpa:1030,lines:[ring(-20,43,3)]},
  {hpa:1025,lines:[ring(-20,43,6)]},
  {hpa:1020,lines:[ring(-20,43,10)]}
 ];
 const snapshot=JSON.stringify(original);
 const detected=g.detectPressureSystems(original,b);
 assert.equal(detected.length,2);
 const low=detected.find(x=>x.type==="T");
 const high=detected.find(x=>x.type==="H");
 assert.ok(low&&high);
 assert.equal(low.hpa,995);
 assert.equal(high.hpa,1030);
 assert.ok(Math.abs(low.lon+53)<.4&&Math.abs(low.lat-55)<.4);
 assert.ok(Math.abs(high.lon+20)<.4&&Math.abs(high.lat-43)<.4);
 assert.equal(low.rings,3);assert.equal(high.rings,3);
 assert.equal(JSON.stringify(original),snapshot,"scientific contours must remain unchanged");
});
test("Single pressure rings, noise and clipped boundary contours never create imaginary H/T",()=>{
 const g=shared(),b=[-70,15,35,75];
 const ring=(cx,cy,r)=>Array.from({length:49},(_,i)=>{
  const a=2*Math.PI*i/48;return [cx+r*Math.cos(a),cy+r*Math.sin(a)];
 });
 const one=[{hpa:990,lines:[ring(-30,50,6)]}];
 assert.equal(g.detectPressureSystems(one,b).length,0);
 const nearEdge=[{hpa:995,lines:[ring(31,44,3)]},
  {hpa:1000,lines:[ring(31,44,6)]},
  {hpa:1005,lines:[ring(31,44,10)]}];
 assert.equal(g.detectPressureSystems(nearEdge,b).length,0);
 const tiny=[{hpa:995,lines:[ring(-20,40,.2)]},
  {hpa:1000,lines:[ring(-20,40,.3)]},
  {hpa:1005,lines:[ring(-20,40,.4)]}];
 assert.equal(g.detectPressureSystems(tiny,b).length,0);
});

test("A broad shallow high with one closed oriented 1020-hPa contour receives an H",()=>{
 const g=shared(),b=[-70,15,35,75];
 function ccw(lon,lat,rx,ry){
  return Array.from({length:65},(_,i)=>{
   const a=2*Math.PI*i/64;return [lon+rx*Math.cos(a),lat+ry*Math.sin(a)];
  });
 }
 const ring=ccw(-41,27.5,9,4.4);
 const one=[{hpa:1020,lines:[ring]}];
 const result=g.detectVisiblePressureSystems(one,b);
 assert.equal(result.length,1,"An Atlantic high does not require three 5-hPa contours");
 assert.equal(result[0].type,"H");
 assert.equal(result[0].hpa,1020);
 assert.ok(Math.abs(result[0].lon+41)<.5);
 const reversed=[{hpa:1020,lines:[ring.slice().reverse()]}];
 assert.equal(g.detectVisiblePressureSystems(reversed,b).length,0,
  "A clockwise pressure ring must not be mislabelled as a high");
});
test("The real source-domain ring may cross the viewport edge while the H center stays visible",()=>{
 const g=shared(),europe=[-27,24,49,73];
 const ring=Array.from({length:65},(_,i)=>{
  const a=2*Math.PI*i/64;
  return [-21.5+7*Math.cos(a),57.4+2.9*Math.sin(a)];
 });
 const result=g.detectVisiblePressureSystems([{hpa:1020,lines:[ring]}],europe);
 assert.equal(result.length,1);
 assert.equal(result[0].type,"H");
 assert.ok(result[0].lon>-27&&result[0].lon<49);
 assert.ok(result[0].lat>24&&result[0].lat<73);
});
test("A tiny anticlockwise closed loop is still suppressed as a high",()=>{
 const g=shared(),atlantic=[-70,15,35,75];
 const ring=Array.from({length:65},(_,i)=>{
  const a=2*Math.PI*i/64;return [-25+.5*Math.cos(a),48+.2*Math.sin(a)];
 });
 assert.equal(g.detectVisiblePressureSystems([{hpa:1020,lines:[ring]}],atlantic).length,0);
});

test("Real 2026-11-14 10:40 UTC IFS contours identify missing T west of Ireland",()=>{
 const g=shared();
 const fixture=JSON.parse(fs.readFileSync(
  "tests/fixtures/satellite_mslp_20261114_1040_missing_low.json","utf8"));
 assert.equal(fixture.source,"ECMWF IFS Open Data");
 assert.equal(fixture.valid_utc,"2026-11-14T10:40:00Z");
 const original=JSON.stringify(fixture.contours);
 const found=g.detectVisiblePressureSystems(fixture.contours,fixture.bbox,{
  minRings:3,maxSystems:6,minSeparation:94
 });
 assert.equal(found.length,1,
  "1000-hPa enclosed depression must be marked, but the 1015-hPa shallow loop must not");
 const low=found[0];
 assert.equal(low.type,"T");assert.equal(low.hpa,1000);
 assert.ok(Math.abs(low.lon+18.8)<.65&&Math.abs(low.lat-49.8)<.65,
  "Marker belongs inside the genuine 1000 hPa ring west of Ireland");
 assert.equal(low.rings,1);
 assert.equal(JSON.stringify(fixture.contours),original,
  "Never mutate model contour coordinates to force an H/T center");
});
test("Single low must be clockwise, pronounced, round enough and not clipped",()=>{
 const g=shared(),bbox=[-27,24,49,73];
 function loop(lon,lat,rx,ry,reverse=false){
  const pts=Array.from({length:65},(_,i)=>{
   const a=2*Math.PI*i/64;
   return [lon+rx*Math.cos(a),lat+ry*Math.sin(a)];
  });
  return reverse?pts.reverse():pts;
 }
 const strict={minRings:3,maxSystems:7};
 // Anticlockwise in lon/lat: a source contour for a high; not a low.
 assert.equal(g.detectPressureSystems([{hpa:1000,lines:[loop(-18,50,4,2)]}],bbox,strict).length,0);
 // Clockwise around a low with a substantial, complete single ring.
 const good=g.detectPressureSystems([{hpa:1000,lines:[loop(-18,50,4,2,true)]}],bbox,strict);
 assert.equal(good.length,1);assert.equal(good[0].type,"T");
 // A single, weak 1015-hPa closed contour remains too uncertain to label.
 assert.equal(g.detectPressureSystems([{hpa:1015,lines:[loop(-18,50,4,2,true)]}],bbox,strict).length,0);
 assert.equal(g.detectPressureSystems([{hpa:1000,lines:[loop(-18,50,.7,.4,true)]}],bbox,strict).length,0,
  "No tiny H/T symbols around numerical micro-loops");
 assert.equal(g.detectPressureSystems([{hpa:1000,lines:[loop(-18,50,5,.2,true)]}],bbox,strict).length,0,
  "A narrow pressure contour island must not be a compact low");
 assert.equal(g.detectPressureSystems([{hpa:1000,lines:[loop(-26.2,51,4,2,true)]}],bbox,strict).length,0,
  "Closed system crossing the map edge is not a supported center");
});
test("Nested deep lows take precedence over a low-scored single-ring candidate",()=>{
 const g=shared(),bbox=[-27,24,49,73];
 function clockwise(lon,lat,r){
  const pts=Array.from({length:65},(_,i)=>{
   const a=-2*Math.PI*i/64;
   return [lon+r*Math.cos(a),lat+.65*r*Math.sin(a)];
  });return pts;
 }
 const contours=[
  {hpa:990,lines:[clockwise(-18,50,2.2)]},
  {hpa:995,lines:[clockwise(-18,50,3.2)]},
  {hpa:1000,lines:[clockwise(-18,50,5.4)]}
 ];
 const found=g.detectVisiblePressureSystems(contours,bbox,{maxSystems:7});
 assert.equal(found.length,1,"Do not duplicate T for the same nested cyclone");
 assert.equal(found[0].type,"T");assert.equal(found[0].hpa,990);
 assert.ok(found[0].rings>=3);
});
