/* Automated scientific data association tests: no browser required. */
"use strict";
const assert=require("node:assert/strict");
const path=require("node:path");
const cps=require(path.join(__dirname,"..","tiefdruck_cps_compare.js"));
const HOURS=3600000;
function make(model,id,shift=0,dLat=0,dLon=0,n=5) {
 const base=Date.UTC(2026,9,13,18);
 const points=[];
 for(let j=0;j<n;j++){
  const i=j+shift;
  points.push({
   time:new Date(base+i*6*HOURS).toISOString().replace(".000Z","Z"),
   h:j*6,lat:45+i*.35+dLat,lon:-48+i*.55+dLon,
   mslp_hpa:980-j,
   cps:{b:12+i*1.8,vt_lower:-50+i*22,vt_upper:-65+i*18}
  });
 }
 return {id,model,run:new Date(base+shift*6*HOURS).toISOString().replace(".000Z","Z"),points};
}
const gfs=make("gfs","GFS-1");
const ifs=make("ifs-atl","IFS-1",-1,.13,.12);
const aifs=make("aifs-atl","AIFS-1",-1,.20,.21);
function run() {
 assert.equal(cps.hasCps(gfs.points[0]),true);
 assert.equal(cps.hasCps({...gfs.points[0],cps:null}),false);
 assert.ok(cps.trackScore(gfs,ifs));
 assert.ok(cps.trackScore(gfs,aifs));
 assert.equal(cps.trackScore(gfs,make("ifs-atl","NO-UTC",9)),null,
  "Cannot join storms without shared valid UTC times");
 assert.equal(cps.trackScore(gfs,make("ifs-atl","FAR",-1,15,20)),null,
  "Cannot join storms hundreds of km apart");
 const matching=cps.matchModels(gfs,[gfs,ifs,aifs]);
 assert.equal(matching.models.gfs,gfs);
 assert.equal(matching.models["ifs-atl"],ifs);
 assert.equal(matching.models["aifs-atl"],aifs);
 assert.ok(matching.details["aifs-atl"].commonTimes>=2);
 const inverse=cps.matchModels(ifs,[gfs,ifs,aifs]);
 assert.equal(inverse.models.gfs,gfs);
 assert.equal(inverse.models["aifs-atl"],aifs);
 const ambiguous=make("ifs-atl","IFS-2",-1,.145,.145);
 const m2=cps.matchModels(gfs,[gfs,ifs,ambiguous,aifs]);
 assert.equal(m2.models["ifs-atl"],null,"Near-ties cannot be confidently attributed");
 assert.match(m2.details["ifs-atl"],/Mehrdeutige/);
 const noCps=make("aifs-atl","AIFS-NoCPS",-1,.20,.21);
 noCps.points.forEach(p=>p.cps=null);
 const m3=cps.matchModels(gfs,[gfs,ifs,noCps]);
 assert.equal(m3.models["aifs-atl"],noCps,"Track matching must use positions, not CPS availability");
 assert.equal(cps.seriesPoints(noCps,"upper").length,0,"Missing CPS is never fabricated");
 const scales=cps.axisRanges(matching.models,"asymmetry");
 const scales2=cps.axisRanges(matching.models,"upper");
 assert.ok(scales.x.min<=-50&&scales.x.max>=38);
 assert.ok(scales.y.min<=12&&scales.y.max>=20);
 assert.ok(scales2.y.min<=-65);
 const paths=cps.seriesPoints(gfs,"asymmetry");
 assert.equal(paths.length,5);
 assert.equal(paths[0].y,gfs.points[0].cps.b);
 assert.equal(cps.seriesPoints(gfs,"upper")[0].y,gfs.points[0].cps.vt_upper);
 const gap=make("gfs","GAP");
 gap.points.splice(1,2);
 const fragmented=cps.seriesPoints(gap,"asymmetry");
 assert.ok(fragmented.some(p=>p.break),"Do not draw continuous 30-h gap as measured path");
 // This fixture intentionally doesn't use current production storm IDs.
 // Matching relies exclusively on model, shared UTC and spatial consistency.
 console.log("Scientific CPS comparison association tests: OK (12 scenarios)");
}
run();
