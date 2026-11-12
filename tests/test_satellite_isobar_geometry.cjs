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
