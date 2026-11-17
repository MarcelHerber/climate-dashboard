import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const source=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
new Function(source); // Check complete module syntax.
for(const needle of [
  'data-mosmix-mode="sun"', 'Sonne (Tag)', 'mosmixSunDailyChart',
  'Sonnenscheindauer pro Kalendertag', 'sunDayFramesFromTimesteps',
  'sunDayValue', 'buildSunFrames',
  'mapMode==="sun" ? buildSunFrames()',
  'meteogramCharts.length !== 6'
]){
  assert.ok(source.includes(needle), "Missing daily sunshine feature: "+needle);
}

// Execute original production helpers rather than copying their algorithm.
const dailyHelpers=source.slice(source.indexOf("  function sunDayFramesFromTimesteps"),
  source.indexOf("  function destroyMeteogramCharts"));
const dateHelpers=source.slice(source.indexOf("  function berlinDateParts"),
  source.indexOf("  const mosmixBerlinMidnightPlugin"));
assert.ok(dailyHelpers.startsWith("  function sunDayFramesFromTimesteps"));
assert.ok(dateHelpers.startsWith("  function berlinDateParts"));
const {sunDayFramesFromTimesteps,sunDayValue,sunshineDayLabels,gustDayLabels}=new Function(
  dailyHelpers+"\n"+dateHelpers+"\nreturn {sunDayFramesFromTimesteps,sunDayValue,sunshineDayLabels,gustDayLabels};"
)();

function hours(start,count){
  return Array.from({length:count},(_,i)=>
    new Date(Date.parse(start)+i*3600000).toISOString());
}
for(const [name,start,count,key] of [
  ["Winterzeit","2026-10-27T00:00:00Z",24,"2026-10-27"],
  ["Sommerzeitbeginn","2026-03-29T00:00:00Z",23,"2026-03-29"],
  ["Winterzeitbeginn","2026-10-24T23:00:00Z",25,"2026-10-25"]
]){
  const times=hours(start,count);
  const frames=sunDayFramesFromTimesteps(times);
  assert.equal(frames.length,1,name);
  assert.equal(frames[0].key,key,name+": Datum");
  assert.equal(frames[0].indices.length,count,name+": Stunden");
  assert.equal(sunDayValue(times.map(()=>30),frames[0]),count/2,name+": Stunden-Summe");
  const values=times.map(()=>0);
  values[Math.floor(values.length/2)]=null;
  assert.equal(sunDayValue(values,frames[0]),null,name+": fehlender Wert");
}

// Do not publish partial days or count a gap as a full day.
assert.equal(sunDayFramesFromTimesteps(hours("2026-10-27T10:00:00Z",14)).length,0);
const missing=hours("2026-10-27T00:00:00Z",24);
missing.splice(8,1);
assert.equal(sunDayFramesFromTimesteps(missing).length,0);
const frame=sunDayFramesFromTimesteps(hours("2026-10-27T00:00:00Z",24))[0];
assert.equal(sunDayValue(Array(24).fill(0),frame),0);
assert.equal(sunDayValue(Array(24).fill(60),frame),24);
assert.equal(sunDayValue(Array(24).fill(null),frame),null);
assert.equal(sunDayValue(Array(24).fill(61),frame),null);

const station={lat:47.87,lon:7.66};
const days=sunDayFramesFromTimesteps(hours('2026-11-21T00:00:00Z',48));
const values=Array(48).fill(0); values[10]=60; values[11]=42;
const labels=sunshineDayLabels(values,days,station);
assert.equal(labels.length,2);
assert.match(labels[0].text,/^1,7 \/ 9,[0123] h \(19 %\)$/);
assert.match(labels[1].text,/^0,0 \/ 9,[0123] h \(0 %\)$/);
assert.equal(labels[0].index,11.5); assert.equal(labels[0].dayIndex,0);
values[25]=null;
assert.equal(sunshineDayLabels(values,days,station).length,1);
const summer=sunDayFramesFromTimesteps(hours('2026-06-20T23:00:00Z',24));
const summerLabel=sunshineDayLabels(Array(24).fill(0),summer,station)[0];
assert.ok(summerLabel.possibleHours>15.7&&summerLabel.possibleHours<16.2);
assert.equal(sunshineDayLabels(Array(24).fill(0),summer,{lat:null,lon:null})[0].text,'0,0 h');

// 3/6/12h maxima can exceed the one-hour values; an interval overlapping
// yesterday cannot be assigned to today. End at local 24:00 belongs to today.
const gustFrames=sunDayFramesFromTimesteps(hours('2026-11-21T00:00:00Z',48));
const ff={FX1:Array(48).fill(62),FX3:Array(48).fill(null),FX6:Array(48).fill(null),FXh:Array(48).fill(null)};
ff.FX3[5]=68; ff.FX6[10]=70; ff.FXh[23]=74; ff.FXh[3]=110; ff.FX3[24]=99;
let gust=gustDayLabels(ff,gustFrames);
assert.deepEqual(gust.map(r=>r.text),['74 km/h','62 km/h']);
assert.equal(gust[0].source,'FXh');
ff.FXh[23]=null; assert.equal(gustDayLabels(ff,gustFrames)[0].text,'70 km/h');
ff.FX6[10]=null; assert.equal(gustDayLabels(ff,gustFrames)[0].text,'68 km/h');
ff.FX1[1]=null; assert.equal(gustDayLabels(ff,gustFrames).length,1,'missing coverage must omit day');
ff.FX3[2]=65; assert.equal(gustDayLabels(ff,gustFrames)[0].text,'68 km/h','3h interval covers missing hour');
const dstFrames=sunDayFramesFromTimesteps(hours('2026-10-24T23:00:00Z',25));
assert.equal(gustDayLabels({FX1:Array(25).fill(0)},dstFrames)[0].text,'0 km/h');
assert.equal(gustDayLabels({FX1:Array(24).fill(20)},dstFrames).length,0);

console.log("PASS: MOSMIX Tages-Sonnenschein, vollständige Kalenderdaten, DST, fehlende Werte, Tagesbalken.");
