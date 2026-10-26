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
  source.indexOf("  const mosmixAxisCache"));
assert.ok(dailyHelpers.startsWith("  function sunDayFramesFromTimesteps"));
assert.ok(dateHelpers.startsWith("  function berlinDateParts"));
const {sunDayFramesFromTimesteps,sunDayValue}=new Function(
  dailyHelpers+"\n"+dateHelpers+"\nreturn {sunDayFramesFromTimesteps,sunDayValue};"
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

console.log("PASS: MOSMIX Tages-Sonnenschein, vollständige Kalenderdaten, DST, fehlende Werte, Tagesbalken.");
