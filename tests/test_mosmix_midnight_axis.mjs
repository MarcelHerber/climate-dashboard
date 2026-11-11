import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

// Exercise the actual axis callbacks used by the six MOSMIX station charts.
// The issue occurs after Chart.js clips the category scale with x.min/x.max:
// context.index is just the visible tick's ordinal, while tick.value is the
// absolute, unchanged index in data.timesteps.
const source=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
const from=source.indexOf("  function berlinDateParts(iso) {");
const until=source.indexOf("  function hasMeteogramValues(detail, param) {",from);
assert.ok(from>0&&until>from);
const code=source.slice(from,until);

function axisFor(timesteps,width=1280) {
  const factory=new Function("data","window",code+
    "\nreturn {berlinDateParts,mosmixAxisTime,baseChartOptions};");
  const helpers=factory({timesteps},{innerWidth:width});
  return {...helpers,axis:helpers.baseChartOptions("°C").scales.x};
}
function hours(start,length) {
  const first=Date.parse(start);
  return Array.from({length},(_,i)=>new Date(first+i*3600000).toISOString());
}
function verifyRange(start,horizonDays) {
  const series=hours(start,195);
  const {axis,berlinDateParts}=axisFor(series);
  const clipStart=6;  // Typical first available MOSMIX forecast hour
  const clipEnd=clipStart+horizonDays*24;
  let midnightLines=0, unexpected=0;
  for(let dataIndex=clipStart;dataIndex<=clipEnd;dataIndex++) {
    const time=berlinDateParts(series[dataIndex]);
    const actualMidnight=time.hour===0;
    // Simulate real Chart.js CategoryScale, including clipped tick ordinal.
    const visibleTickIndex=dataIndex-clipStart;
    const callback=axis.ticks.callback;
    const caption=callback(dataIndex,visibleTickIndex);
    const context={index:visibleTickIndex,tick:{value:dataIndex}};
    const color=axis.grid.color(context);
    const width=axis.grid.lineWidth(context);
    const labeled=Array.isArray(caption)&&caption.includes("00 Uhr");
    if(actualMidnight) {
      midnightLines++;
      assert.ok(labeled,series[dataIndex]+" must have its 00 Uhr label");
      assert.match(color,/116,139/);
      assert.equal(width,1.5);
      assert.ok(caption[0].includes(String(time.day).padStart(2,"0")));
    }else {
      if(labeled || width===1.5)unexpected++;
      assert.ok(!labeled,series[dataIndex]+" is NOT Berlin midnight");
      assert.notEqual(width,1.5);
    }
  }
  assert.ok(midnightLines>=horizonDays-1, "Too few midnight lines for "+horizonDays+" days");
  assert.equal(unexpected,0,"No off-midnight label/grid lines allowed");
  console.log("PASS: "+horizonDays+"-day MOSMIX view, "+midnightLines+
      " genuine Berlin midnight markers; zoom starts at step "+clipStart);
}

verifyRange("2026-11-10T00:00:00Z",3);
verifyRange("2026-11-10T00:00:00Z",5);
verifyRange("2026-06-10T00:00:00Z",3);
verifyRange("2026-06-10T00:00:00Z",5);
verifyRange("2026-03-27T00:00:00Z",5); // MEZ -> MESZ, 23-hour day
verifyRange("2026-10-23T00:00:00Z",5); // MESZ -> MEZ, 25-hour day

const fall=axisFor(hours("2026-10-24T20:00:00Z",32));
const spring=axisFor(hours("2026-03-28T20:00:00Z",32));
assert.equal(fall.berlinDateParts("2026-10-24T22:00:00Z").hour,0);
assert.equal(fall.berlinDateParts("2026-10-25T23:00:00Z").hour,0);
assert.equal(spring.berlinDateParts("2026-03-28T23:00:00Z").hour,0);
assert.equal(spring.berlinDateParts("2026-03-29T22:00:00Z").hour,0);

// Regression check: the second argument is a *visible* tick ordinal, not
// the timestep index. It must never be used to determine local midnight.
const sample=axisFor(hours("2026-11-10T00:00:00Z",150));
assert.deepEqual(sample.axis.ticks.callback(23,0),["Mi 11.11.","00 Uhr"]);
assert.equal(sample.axis.ticks.callback(6,23),"");
assert.equal(sample.axis.grid.lineWidth({index:0,tick:{value:23}}),1.5);
assert.equal(sample.axis.grid.lineWidth({index:23,tick:{value:6}}),0.8);
assert.equal(sample.axis.grid.lineWidth({index:0}),0.8);
console.log("PASS: Chart.js category indices, UTC offsets and DST-safe midnight separators.");
