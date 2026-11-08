const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const main=fs.readFileSync("arktis_temperatur.js","utf8");
const moduleCode=fs.readFileSync("arktis_klimastatistik.js","utf8");
const html=fs.readFileSync("arktis_temperatur.html","utf8");
const build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const data=JSON.parse(fs.readFileSync("data/arctic80_temperature.json","utf8"));
const fake={window:{},document:{readyState:"loading",addEventListener(){}},
 console,Date,Number,Math,Intl,Array,Object,String,Map,Set};
vm.runInNewContext(main,fake,{timeout:10000});
vm.runInNewContext(moduleCode,fake,{timeout:10000});
const stat=fake.window.Arctic80LongTermMath;
assert.ok(stat,"Long-term Arctic module should export its pure helpers");
const days=data.days;
function fixture(){
 const years={};
 for(const y of [2019,2020,2021]){
  years[String(y)]=days.map(day=>day==="02-29"&&y!==2020?null:0);
 }
 function fill(y,month,num){
  for(let i=0;i<days.length;i++)if(Number(days[i].slice(0,2))===month&&years[String(y)][i]!=null)
   years[String(y)][i]=num;
 }
 fill(2019,12,2);
 fill(2020,1,-2);fill(2020,2,-2);
 fill(2020,12,2);fill(2021,1,2);
 return {days,years,last_date:"2021-12-31",latest_year:2021};
}
function ref(){return {p10:days.map(()=>-1),p90:days.map(()=>1)};}
test("DJF is assigned to Jan/Feb calendar year and runs across year boundary",()=>{
 const fixtureDoc=fixture(),one=stat.seasonFor(fixtureDoc,ref(),2020,"djf"),
 two=stat.seasonFor(fixtureDoc,ref(),2021,"djf");
 assert.equal(one.first,"2019-12-01");assert.equal(one.last,"2020-02-29");
 assert.equal(one.days,91);assert.equal(one.warm,31);assert.equal(one.cold,60);
 assert.equal(one.longestWarm,31);assert.equal(one.longestCold,60);
 assert.equal(two.first,"2020-12-01");assert.equal(two.last,"2021-02-28");
 assert.equal(two.days,90);assert.equal(two.warm,62);assert.equal(two.longestWarm,62);
 assert.equal(stat.seasonFor(fixtureDoc,ref(),2019,"djf"),null);
});
test("Seasons with missing days are excluded; leap day only in leap years",()=>{
 const d=fixture();d.years["2020"][days.indexOf("02-29")]=null;
 assert.equal(stat.seasonFor(d,ref(),2020,"djf"),null);
 const result=stat.seasonFor(d,ref(),2021,"djf");
 assert.ok(result&&result.days===90);
 d.years["2021"][days.indexOf("01-10")]=null;
 assert.equal(stat.seasonFor(d,ref(),2021,"djf"),null);
});
test("Seasonal rankings keep ties and separate warm from cold records",()=>{
 const season=[{year:2000,warm:3,cold:7},{year:2001,warm:9,cold:3},{year:2002,warm:9,cold:3}];
 const r=stat.seasonalRank(season,"warm",2002);
 assert.equal(r.rank,1);assert.equal(r.sorted[0].warm,9);
 assert.equal(stat.seasonalRank(season,"cold",2001).rank,2);
});
test("Trend regression uses observed complete years only and yields per-decade units",()=>{
 const rows=[{year:2000,coverage:365,expected:365,warmDays:0},
 {year:2001,coverage:365,expected:365,warmDays:2},
 {year:2002,coverage:364,expected:365,warmDays:200},
 {year:2003,coverage:365,expected:365,warmDays:6}];
 const filtered=stat.annualFiltered(rows,2000,2003);
 assert.equal(filtered.length,3);
 const fit=stat.regression(filtered,"warmDays");
 assert.ok(Math.abs(fit.perDecade-20)<1e-9);
 assert.ok(Math.abs(fit.r2-1)<1e-9);
 assert.equal(stat.regression(filtered.slice(0,2),"warmDays"),null);
});
test("Decades use only complete years and disclose sample sizes",()=>{
 const rows=[{year:1998,expected:365,coverage:365,warmDays:15,coldDays:4,maxWarm:6,maxCold:2},
 {year:1999,expected:365,coverage:365,warmDays:25,coldDays:8,maxWarm:8,maxCold:4},
 {year:2000,expected:366,coverage:1,warmDays:999,coldDays:999,maxWarm:999,maxCold:999}];
 const dec=stat.decadal(rows);
 assert.equal(dec.length,1);assert.equal(dec[0].decade,1990);assert.equal(dec[0].years,2);
 assert.equal(dec[0].warmDays,20);assert.equal(dec[0].coldDays,6);
});
test("Real archive: 4 seasonal groups and data gaps excluded",()=>{
 const actual=stat.analyze(data);
 assert.equal(actual.annual.length,69);
 assert.equal(actual.seasons.djf.length>=50,true);
 assert.equal(actual.seasons.mam.length>=50,true);
 assert.equal(actual.seasons.jja.length>=50,true);
 assert.equal(actual.seasons.son.length>=50,true);
 assert.ok(actual.seasons.djf.every(s=>s.first.endsWith("-12-01")&&s.last.endsWith("-02-28")||s.last.endsWith("-02-29")));
 assert.ok(!actual.seasons.son.some(s=>s.year===2026));
 assert.ok(actual.seasons.djf.some(s=>s.year===2026));
 assert.ok(actual.decades.every(d=>d.years>=1&&d.years<=10));
});
test("All four CSV exports and PNG/PDF controls are present and wired",()=>{
 const buttons=["arcticHeatmapPng","arcticHeatmapPdf","arcticHeatmapCsv",
 "arcticTrendPng","arcticTrendPdf","arcticAnnualStatsCsv","arcticEventsCsv",
 "arcticSeasonPng","arcticSeasonPdf","arcticSeasonCsv"];
 for(const id of buttons){assert.ok(html.includes('id="'+id+'"'),id);
  assert.ok(moduleCode.includes('["'+id+'"'),"Event handler "+id);}
 assert.match(html,/src="arktis_klimastatistik\.js\?v=\d+"/);
 assert.ok(build.includes("  arktis_klimastatistik.js\n"));
 assert.ok(build.includes("node --check _site/arktis_klimastatistik.js"));
 for(const id of ["arcticTrendDaysCanvas","arcticTrendDurationCanvas","arcticSeasonCanvas","arcticDecadeBody",
 "arcticSeasonWarmBody","arcticSeasonColdBody","arcticLongTermLoad"]){
  assert.ok(html.includes('id="'+id+'"'),id);
 }
 assert.ok(moduleCode.includes("Quelle: DMI / ECMWF"));
 assert.ok(moduleCode.includes("canvas.width=width*2"));
});
