const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const source=fs.readFileSync("arktis_era5_maps.js","utf8");
const html=fs.readFileSync("arktis_temperatur.html","utf8");
const build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const sandbox={window:{},document:{readyState:"loading",addEventListener(){}},console};
vm.runInNewContext(source,sandbox,{timeout:5000});
const math=sandbox.window.ArcticEra5Archive;
const image=(kind,region,date)=>"maps/"+kind+"_"+region+"n_"+date.replaceAll("-","")+".png";
function r(region,date){
 return {boundary_version:3,temperature_png:image("t2m",region,date),
 anomaly_png:image("anomaly",region,date),mean_c:-11,mean_anomaly_k:4};
}
test("ERA5 archive accepts only real, correctly named 60/70/80N image references",()=>{
 const date="2026-11-01",all={"80":r(80,date),"70":r(70,date),"60":r(60,date)};
 const d=math.normalize({schema:2,ready:true,target_days:30,
 days:[{date,regions:all}]});
 assert.ok(d);
 assert.equal(d.days.length,1);
 assert.equal(Object.keys(d.days[0].regions).length,3);
 assert.ok(math.validFile(image("t2m",60,date)));
 assert.ok(!math.validFile("maps/t2m_50n_20261101.png"));
 assert.ok(!math.validFile("../maps/t2m_80n_20261101.png"));
});
test("Old 80N files remain available without inventing 60 or 70N images",()=>{
 const d=math.normalize({schema:1,ready:true,days:[{date:"2026-11-01",
 temperature_png:"maps/t2m_20261101.png",
 anomaly_png:"maps/anomaly_20261101.png",mean_c:-7,mean_anomaly_k:8}]});
 assert.ok(d);
 assert.equal(Object.keys(d.days[0].regions).join(","),"80");
 assert.ok(!d.days[0].regions["60"]);
});
test("Missing days/regions are omitted rather than filled with synthetic maps",()=>{
 const day="2026-10-31",good=r(80,day);
 const x=math.normalize({schema:2,ready:true,days:[
 {date:day,regions:{"80":good,"60":{...r(60,day),mean_c:NaN}}},
 {date:day,regions:{"80":good}},
 {date:"malformed",regions:{"80":good}}
 ]});
 assert.equal(x.days.length,1);
 assert.ok(x.days[0].regions["80"]);
 assert.ok(!x.days[0].regions["60"]);
});
test("Viewer has accessible region/date controls, fixed color legends and the build ships JS",()=>{
 for(const id of ["arcticEra5MapRegion","arcticEra5MapDate","arcticEra5Calendar",
 "arcticEra5ArchiveProgress","arcticEra5Pdf","arcticEra5TempMap","arcticEra5AnomalyMap"]){
  assert.ok(html.includes('id="'+id+'"'),id);
 }
 for(const region of ["80","70","60"]) assert.ok(html.includes('value="'+region+'"'));
 assert.ok(html.includes("−45 bis +15 °C"));
 assert.ok(html.includes("−15 bis +15 K"));
 assert.match(html,/arktis_era5_maps\.js\?v=\d+/);
 assert.ok(build.includes("  arktis_era5_maps.js\n"));
 assert.ok(build.includes("node --check _site/arktis_era5_maps.js"));
});
