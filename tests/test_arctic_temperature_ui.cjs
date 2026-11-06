const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const script=fs.readFileSync("arktis_temperatur.js","utf8");
const page=fs.readFileSync("arktis_temperatur.html","utf8");
const nav=fs.readFileSync("mobile_navigation.js","utf8");
const site=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const home=fs.readFileSync("index.html","utf8");
const seaice=fs.readFileSync("meereis.html","utf8");

test("Arctic DMI module included in all site navigation surfaces",()=>{
  for(const name of ["arktis_temperatur.html","arktis_temperatur.js","arktis_temperatur.css"]){
    assert.ok(site.includes("  "+name+"\n"),"Missing Pages file "+name);
  }
  assert.ok(home.includes("window.location.href='arktis_temperatur.html'"));
  assert.ok(nav.includes('["arktis_temperatur.html","Arktische Temperaturen'));
  assert.ok(seaice.includes('href="arktis_temperatur.html"'));
  assert.ok(site.includes("data/arctic80_temperature.json"));
});
test("Arctic chart controls, source links and export controls exist",()=>{
  for(const id of ["arcticStatus","arcticLastDay","arcticYear","arcticCompare",
    "arcticHistoryMode","arcticReference","arcticAnnualChart","arcticAnomalyChart",
    "arcticShow7","arcticShow30","arcticPngAnnual","arcticPngAnomaly",
    "arcticPdf","arcticCsv"]){
    assert.ok(page.includes('id="'+id+'"'),"Missing control "+id);
  }
  assert.ok(page.includes("meanT")===false,"Never embed stale hard-coded daily readings in markup");
  assert.ok(page.includes("1958–2002"));
  assert.ok(page.includes("kein flächengewichtetes Temperaturmittel"));
  assert.ok(page.includes("jsdelivr.net/npm/chart.js"));
  assert.ok(page.includes("jspdf"));
});
test("DMI chart JS parses and trailing anomalies don't fill gaps or use future days",()=>{
  assert.doesNotThrow(()=>new Function(script));
  const window={},document={readyState:"loading",addEventListener(){}};
  vm.runInNewContext(script,{window,document,console,Date,Number,Math,Object,Array,String,Intl},{timeout:2500});
  const math=window.Arctic80Math;
  assert.ok(math);
  assert.deepEqual(Array.from(math.diff([4,null,6],[2,2,7])),[2,null,-1]);
  assert.deepEqual(Array.from(math.smooth([1,2,3,4],3)),[null,null,2,3]);
  assert.deepEqual(Array.from(math.smooth([1,null,3,4,5],3)),[null,null,null,null,4]);
  assert.equal(math.lastIndex([1,0,null,null]),1);
});
test("CSV has reproducible date-aligned temperatures and anomalies",()=>{
  const win={},doc={readyState:"loading",addEventListener(){}};
  vm.runInNewContext(script,{window:win,document:doc,console,Date,Number,Math,Object,Array,String,Intl},{timeout:2500});
  const dataset={days:["01-01","01-02","01-03"],years:{"2026":[1,2,null],"2012":[3,4,5]},reference:{temperatures:[0,1,2]}};
  const result=win.Arctic80Math.csv(dataset,"2026","2012");
  assert.ok(result.includes("Abweichung (K)"));
  assert.ok(result.includes("01-01;1;0;1"));
  assert.ok(result.includes("01-03;;2;"));
});

test("New Arctic ranking panels and their JavaScript ship in Pages artifact",()=>{
  const stats=fs.readFileSync("arktis_statistik.js","utf8");
  assert.ok(site.includes("  arktis_statistik.js\\n"),"Missing Arctic statistics JS in build list");
  assert.ok(site.includes("node --check _site/arktis_statistik.js"));
  assert.ok(page.includes('id="arcticRecords"'));
  assert.ok(page.includes('id="arcticSeasons"'));
  assert.match(page,/src="arktis_statistik\\.js\\?v=\\d+"/);
  assert.doesNotThrow(()=>new Function(stats));
  assert.ok(script.includes("arctic80:data-ready"),"Charts must notify statistics when shared data is ready");
  const window={},document={readyState:"loading",addEventListener(){}};
  vm.runInNewContext(stats,{window,document,console},{timeout:2500});
  const math=window.Arctic80StatsMath;
  assert.equal(math.periods.length,16);
  const fake={days:["01-01","01-02"],years:{"2024":[2,4],"2025":[1,3]}};
  const rows=math.daily(fake,0,2024);
  assert.equal(rows.rank,1);
  assert.equal(rows.min.value,1);
  assert.equal(rows.max.value,2);
  assert.equal(math.period(fake,2024,[[0,1]]),3);
  assert.equal(math.period({...fake,years:{"2024":[2,null]}},2024,[[0,1]]),null);
});
