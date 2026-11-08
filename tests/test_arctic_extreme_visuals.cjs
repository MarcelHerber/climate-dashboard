const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const js=fs.readFileSync("arktis_temperatur.js","utf8");
const html=fs.readFileSync("arktis_temperatur.html","utf8");
const css=fs.readFileSync("arktis_temperatur.css","utf8");
const doc=JSON.parse(fs.readFileSync("data/arctic80_temperature.json","utf8"));
const w={};
vm.runInNewContext(js,{window:w,document:{readyState:"loading",addEventListener(){}},
  console,Date,Number,Math,Intl,Array,Object,String},{timeout:6000});
const visual=w.Arctic80VisualMath,stats=w.Arctic80StreaksMath;
assert.ok(visual,"Visual math should load from main JS");
const results=stats.analyze(doc);
test("Color categories require strict P10/P90 exceedance and preserve nulls",()=>{
  assert.equal(visual.kindAt(7,2,6),"warm");
  assert.equal(visual.kindAt(1,2,6),"cold");
  assert.equal(visual.kindAt(2,2,6),"neutral");
  assert.equal(visual.kindAt(6,2,6),"neutral");
  assert.equal(visual.kindAt(null,2,6),null);
  assert.equal(visual.kindAt(7,null,6),null);
});
test("Calendar-year overlap handles December to January crossings",()=>{
  const e={start:"2003-12-29",end:"2004-01-02",days:5};
  assert.equal(visual.overlap(e,"2002"),null);
  assert.equal(visual.overlap(e,"2003").end,"2003-12-31");
  assert.equal(visual.overlap(e,"2004").start,"2004-01-01");
  const synthetic={events:{warm:[e],cold:[]}};
  assert.equal(visual.eventSegments(doc,synthetic,2003,"warm",5)[0].from,doc.days.indexOf("12-29"));
  assert.equal(visual.eventSegments(doc,synthetic,2004,"warm",5)[0].to,doc.days.indexOf("01-02"));
  assert.equal(visual.eventSegments(doc,synthetic,2004,"warm",6).length,0);
});
test("All-year streak overlay includes known long spells at stable calendar indices",()=>{
  const warm=visual.eventSegments(doc,results,2018,"warm",7);
  assert.ok(warm.some(s=>s.event.start==="2018-09-25"&&s.event.end==="2018-11-12"));
  const cold=visual.eventSegments(doc,results,2026,"cold",7);
  assert.ok(cold.some(s=>s.event.start==="2026-06-08"&&s.event.end==="2026-08-10"));
  assert.equal(cold.find(s=>s.event.start==="2026-06-08").from,doc.days.indexOf("06-08"));
  assert.equal(visual.eventSegments(doc,results,2018,"cold",30).every(s=>s.event.days>=30),true);
});
test("Heatmap grid hit test is bounded and keeps February 29 as a separate column",()=>{
  const years=Object.keys(doc.years).map(Number).sort((a,b)=>a-b);
  assert.equal(years.length,69);
  assert.deepEqual(JSON.parse(JSON.stringify(visual.hitCell(48+59*3+1,33+4*13+1,years,366))),
    {year:years[4],index:59});
  assert.equal(doc.days[59],"02-29");
  assert.equal(visual.hitCell(0,0,years,366),null);
  assert.equal(visual.hitCell(48+366*3,33,years,366),null);
});
test("Extremes heatmap UI, toggles, accessible instructions and responsive scroll",()=>{
  for(const id of ["arcticVisualPanel","arcticVisualWarm","arcticVisualCold",
    "arcticVisualMinimum","arcticVisualInfo","arcticHeatmapPanel","arcticHeatmapCanvas",
    "arcticHeatmapScroll","arcticHeatmapCount","arcticHeatmapHover"]){
    assert.ok(html.includes('id="'+id+'"'),"Missing "+id);
  }
  assert.match(js,/id:"arcticExtremeOverlay"/);
  assert.match(js,/Chart\.register\(overlay\)/);
  assert.match(css,/arctic-heatmap-scroll\{overflow-x:auto/);
  assert.match(html,/arktis_temperatur\.js\?v=\d+/);
  assert.match(html,/arktis_temperatur\.css\?v=\d+/);
});
