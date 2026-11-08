const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const script = fs.readFileSync("arktis_temperatur.js","utf8");
const html = fs.readFileSync("arktis_temperatur.html","utf8");
const build = fs.readFileSync("scripts/build_pages_site.sh","utf8");
const ctxt = {window:{},document:{readyState:"loading",addEventListener(){}},console,Date,Number,Math,Array,Object,String,Intl};
vm.runInNewContext(script,ctxt,{timeout:5000});
const lib=ctxt.window.Arctic80StreaksMath;
assert.ok(lib,"Expected bundled DMI warm/cold streak math");

function mock(){
  const days=Array.from({length:366},(_,i)=>
    new Date(Date.UTC(2024,0,1+i)).toISOString().slice(5,10));
  const years={};
  for(let year=1958;year<=2004;year++){
    years[String(year)]=days.map(day=>
      day==="02-29"&&!lib.leap(year)?null:0);
  }
  const idx=day=>days.indexOf(day);
  for(const day of ["12-29","12-30","12-31"])years["2003"][idx(day)]=5;
  for(const day of ["01-01","01-02"])years["2004"][idx(day)]=5;
  years["2004"][idx("07-01")]=-3;
  years["2004"][idx("07-02")]=-3;
  return {days,years,last_date:"2004-12-31",latest_year:2004};
}

test("Historical per-calendar-day P10/P90 of 1958–2002 with 29 February separate",()=>{
  const d=mock(),ref=lib.thresholds(d);
  assert.equal(ref.p90.length,366);
  assert.equal(ref.p10.length,366);
  assert.equal(ref.counts[d.days.indexOf("02-29")],11);
  assert.equal(ref.counts[d.days.indexOf("03-01")],45);
  assert.ok(ref.p90.every(x=>x===0));
  assert.ok(ref.p10.every(x=>x===0));
});
test("Only strict >P90 or <P10; ties at threshold excluded",()=>{
  const d=mock(),analysis=lib.analyze(d);
  const y=analysis.annual.find(row=>row.year===2004);
  assert.equal(y.warmDays,2);
  assert.equal(y.coldDays,2);
  assert.equal(y.coverage,366);
  assert.equal(y.maxWarm,2);
  assert.equal(y.maxCold,2);
});
test("Extremes run across 31 Dec / 1 Jan, without a fictitious Feb 29",()=>{
  const d=mock(),a=lib.analyze(d);
  const event=a.events.warm.find(e=>e.start==="2003-12-29");
  assert.equal(event.end,"2004-01-02");
  assert.equal(event.days,5);
  const yr2003=a.annual.find(y=>y.year===2003);
  const yr2004=a.annual.find(y=>y.year===2004);
  assert.equal(yr2003.maxWarm,3);
  assert.equal(yr2004.maxWarm,2);
  assert.equal(yr2003.expected,365);
  assert.equal(yr2004.expected,366);
});
test("Missing days split streaks rather than being bridged",()=>{
  const d=mock();
  d.years["2003"][d.days.indexOf("12-30")]=null;
  const a=lib.analyze(d);
  assert.equal(a.events.warm.find(e=>e.start==="2003-12-29").days,1);
  assert.equal(a.events.warm.find(e=>e.start==="2003-12-31").days,3);
  assert.equal(a.annual.find(y=>y.year===2003).coverage,364);
});
test("Partial current year omitted from annual complete-year rankings",()=>{
  const d=mock(),i=d.days.indexOf("07-01");
  d.last_date="2004-07-01";
  for(let day=i+1;day<366;day++)d.years["2004"][day]=null;
  const a=lib.analyze(d),last=a.annual.at(-1);
  assert.ok(last.coverage<last.expected);
  assert.equal(a.annual.filter(y=>y.coverage===y.expected).length,46);
});
test("Live-data mathematical integrity, long event and baseline",()=>{
  const d=JSON.parse(fs.readFileSync("data/arctic80_temperature.json","utf8"));
  const r=lib.analyze(d),warm=r.events.warm[0],cold=r.events.cold[0];
  assert.ok(r.annual.length>=60);
  assert.equal(r.reference.p90.length,366);
  assert.ok(warm.days>=10 && warm.meanExcess>0);
  assert.ok(cold.days>=10 && cold.meanExcess>0);
  assert.equal(r.annual.at(-1).year,Number(d.latest_year));
});
test("Streak UI and Pages JS included, new controls versioned",()=>{
  for(const id of ["arcticStreaks","arcticStreakType","arcticStreakMinDays",
    "arcticStreakStatus","arcticStreakEvents","arcticStreakYears",
    "arcticStreakMonths","arcticStreakDays","arcticStreakRanking"]){
    assert.ok(html.includes('id="'+id+'"'),id);
  }
  assert.ok(html.includes("Perzentile"));
  assert.ok(script.includes("Arctic80StreaksMath"));
  assert.ok(build.includes("node --test tests/test_arctic_streaks.cjs"));
  assert.match(html,/arktis_temperatur\.js\?v=\d+/);
});
