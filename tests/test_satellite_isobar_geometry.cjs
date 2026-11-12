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
