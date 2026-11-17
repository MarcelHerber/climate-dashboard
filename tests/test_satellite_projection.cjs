"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const vm=require("node:vm");
const fs=require("node:fs");
const box={window:{}};
if(fs.existsSync('satellite_projection.js'))vm.runInNewContext(fs.readFileSync('satellite_projection.js','utf8'),box);
const projection=box.window.SatelliteProjection;

test('EUMETView AUTO:97004 WGS84 projection agrees with independent PROJ coordinates',()=>{
 // GDAL/PROJ geos, WGS84, +h=35785831 +lon_0=0 +sweep=y.
 for(const [lon,lat,x,y] of [
  [0,0,0,0],[8.68,50.11,580716.558353321,4548065.02167898],
  [-52.71,47.56,-3096126.67287781,4202752.14809671],
  [78,0,5425019.2595249,0],[0,78,0,5406887.12942393],
  [28.05,-26.2,2592240.21353994,-2686944.42332947],
  [-30,-30,-2641693.69137324,-3020003.89471944]]){
  const p=projection?.project('disk',lon,lat,13000000,13000000);
  assert.ok(p,'visible ground point');
  assert.ok(Math.abs(p[0]-(6500000+x))<1,'x');
  assert.ok(Math.abs(p[1]-(6500000-y))<1,'y');
 }
});

test('back side and poles are hidden, and north is precisely the unchanged upper half of full disc',()=>{
 for (const [lon,lat] of [[83,0],[0,83],[-110,30],[180,0],[0,-90],[NaN,10]]) {
  assert.equal(projection?.project('disk',lon,lat,1400,1400),null);
 }
 const d=projection.project('disk',8.68,50.11,1400,1400), n=projection.project('north',8.68,50.11,1400,700);
 assert.deepEqual(Array.from(n),Array.from(d));
 assert.equal(projection.project('north',28.05,-26.2,1400,700),null);
 assert.equal(projection.containsPixel('disk',700,700,1400,1400),true);
 assert.equal(projection.containsPixel('disk',50,50,1400,1400),false);
 assert.equal(projection.containsPixel('disk',1400,700,1400,1400),false);
 assert.equal(projection.containsPixel('disk',d[0],d[1],1400,1400),true);
 assert.equal(projection.containsPixel('north',700,701,1400,700),false);
});

test('paths clip the equator and limb, never joining via points hidden behind Earth',()=>{
 const cross=projection?.paths('north',[[-30,-20],[-30,20]],1400,700);
 assert.ok(cross?.length===1);
 assert.ok(Math.abs(cross[0][0][1]-700)<1e-5);
 const limb=projection.paths('disk',[[80,0],[105,0]],1400,1400);
 assert.equal(limb.length,1);
 assert.ok(limb[0].at(-1)[0]>1280);
 assert.ok(limb[0].at(-1)[0]<1290);
 const split=projection.paths('disk',[[0,0],[100,0],[0,20]],1400,1400);
 assert.equal(split.length,2);
 const anti=projection.paths('disk',[[170,0],[-170,0]],1400,1400);
 assert.equal(anti.length,0);
 const bothHidden=projection.paths('disk',[[-82,0],[82,0]],1400,1400);
 assert.equal(bothHidden.length,1);
 assert.ok(bothHidden[0][0][0]<120&&bothHidden[0].at(-1)[0]>1280);
 for(const path of [...cross,...limb,...split])for(const [x,y] of path)assert.ok(projection.containsPixel('disk',x,y,1400,1400));
});
