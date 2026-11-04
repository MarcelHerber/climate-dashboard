const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const source=fs.readFileSync("station_snow_accumulation.js","utf8");
const html=fs.readFileSync("index.html","utf8");
const build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
const context={window:{}};
vm.runInNewContext(source,context,{timeout:3000});
const api=context.window.StationSnowAccumulation;
const axis=["11-01","11-02","02-28","02-29","03-01"];
function flat(year,value=2){
  return {year,values:axis.map(()=>value)};
}

test("inclusive arbitrary interval in hydrological-year order",()=>{
  assert.deepEqual(Array.from(api.selectedDays(axis,"11-02","02-29")),
    ["11-02","02-28","02-29"]);
  assert.equal(api.selectedDays(axis,"03-01","11-01"),null);
  assert.equal(api.selectedDays(axis,"01-15","03-01"),null);
});

test("snow depth is accumulated as cm-days, never as fresh snowfall",()=>{
  const r=api.accumulate(["11-01","11-02"],["11-01","11-02"],[10,10],2025);
  assert.equal(r.total,20);
  assert.deepEqual(Array.from(r.series),[10,20]);
  assert.equal(r.complete,true);
  assert.equal(r.coverage,1);
});

test("zero cm is a real observation, missing stays null, partial totals flagged",()=>{
  const r=api.accumulate(axis,axis,[0,10,null,null,5],2025);
  assert.equal(r.total,15);
  assert.equal(r.observed,3);
  assert.equal(r.expected,4); // Feb 29 is not a date in 2025
  assert.equal(r.complete,false);
  assert.deepEqual(Array.from(r.series),[0,10,null,10,15]);
});

test("29 February only adds cm-days in leap years",()=>{
  const days=axis;
  const values=[10,10,10,15,20];
  const leap=api.accumulate(axis,days,values,2024);
  const ordinary=api.accumulate(axis,days,values,2025);
  assert.equal(leap.expected,5);
  assert.equal(leap.total,65);
  assert.equal(ordinary.expected,4);
  assert.equal(ordinary.total,50);
  assert.equal(ordinary.series[3],30);
  assert.equal(leap.complete,true);
  assert.equal(ordinary.complete,true);
});

test("reference is median of complete season cumulative totals, excludes missing years",()=>{
  const years=[1991,1992,1993,1994,1995,1996].map(y=>flat(y));
  years.find(x=>x.year===1994).values[1]=null; // exclude incomplete season
  const ref=api.reference({month_days:axis,years},axis);
  assert.equal(ref.count,5);
  assert.equal(ref.total,8); // nonleap=4 days x 2, leap=5 days x 2
  assert.equal(ref.series[0],2);
  assert.equal(ref.series.at(-1),8);
});

test("too few clean climate years produces no misleading median",()=>{
  const ref=api.reference({month_days:axis,years:[flat(1991),flat(1992)]},axis);
  assert.equal(ref.count,2);
  assert.equal(ref.total,null);
  assert.equal(ref.series,null);
});

test("current incomplete season is labeled interim; historic zero must remain zero",()=>{
  const current={columns:["date","snow_cm"],rows:[
    ["2026-11-01",0],["2026-11-02",6]
  ]};
  const archive={month_days:axis,years:[{year:2025,values:[0,0,0,null,0]}]};
  const result=api.report(archive,current,2027,new Set([2027,2025]),"11-01","11-02");
  assert.equal(result.rows.length,2);
  const now=result.rows.find(r=>r.year===2027);
  assert.equal(now.total,6);
  assert.equal(now.complete,true);
  assert.equal(result.rows.find(r=>r.year===2025).total,0);
  const longer=api.report(archive,current,2027,new Set([2027]),"11-01","03-01");
  assert.equal(longer.rows[0].complete,false);
  assert.equal(longer.rows[0].coverage,0.5); // nonleap current winter
});

test("embedded controls, chart export and publication wiring",()=>{
  assert.match(html,/id="stationSnowAccumulation"/);
  assert.match(html,/id="stationSnowCumStart"/);
  assert.match(html,/id="stationSnowCumEnd"/);
  assert.match(html,/id="stationSnowCumChart"/);
  assert.match(html,/StationSnowAccumulation\?\.render\(\{/);
  assert.match(html,/station_snow_accumulation\.js\?v=/);
  assert.match(build,/station_snow_accumulation\.js/);
  assert.match(build,/test_station_snow_accumulation\.cjs/);
});
