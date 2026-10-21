// Checks that the single-chart forecast mode uses the actual run's dates.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const html=fs.readFileSync("stratosphaere.html","utf8");
const js=fs.readFileSync("stratosphere_ensemble.js","utf8");

for(const id of ["stratoForecastTab","stratoHistoryTab","stratoViewSwitch",
                  "stratoEnsembleSpan","stratoEnsembleCanvas","stratoMembers","stratoBand90",
                  "stratoEnsembleFrom","stratoEnsembleTo","stratoShowAnalysis"]){
 assert(html.includes('id="'+id+'"'),"Missing simplified forecast control: "+id);
}
assert(html.includes('<body class="strato-forecast-only">'),"Forecast mode must be default");
assert(html.indexOf('id="stratoEnsembleCard"')<html.indexOf('id="stratoHistoryCard"'),
 "Forecast chart must be the first, primary graph");
assert(html.includes('main > :not(.intro):not(#stratoViewSwitch):not(#stratoEnsembleCard)'),
 "Other stratosphere modules must be hidden in forecast-only view");
assert(html.includes('function setStratoView(mode)')&&
 html.includes('document.body.classList.toggle("strato-forecast-only",focus)'),
 "History must remain accessible through working mode switch");
assert(html.includes('stratosphere:view-changed'),"Forecast chart must redraw after mode switch");
assert(/id="stratoMembers"[^>]*checked/.test(html),"All members must start visible");
assert(/id="stratoBand90"[^>]*checked/.test(html),"Forecast spread must start visible");
assert(/id="stratoClimo"[^>]*type="checkbox"(?![^>]*checked)/.test(html),
 "Historical climatology must be off in a forecast-only view");
assert(/id="stratoShowAnalysis"[^>]*type="checkbox"(?![^>]*checked)/.test(html),
 "NASA analysis must be off in a forecast-only view");

const begin=js.indexOf("function day(date){");
const end=js.indexOf("function parseNasa(",begin);
assert(begin>=0&&end>begin,"Forecast horizon helpers missing");
const selection=js.slice(begin,end);
const values={
 stratoEnsembleFrom:{value:""},stratoEnsembleTo:{value:""},
 stratoEnsembleSpan:{value:"all"},
};
const sampleDates=Array.from({length:36},(_,i)=>
 new Date(Date.UTC(2026,9,20+i)).toISOString().slice(0,10));
const sandbox={Date,globalForecast:{valid_dates:sampleDates},drawCounter:{calls:0},
 $:id=>values[id]};
vm.createContext(sandbox);
vm.runInContext('let forecast=globalForecast;function draw(){drawCounter.calls++};'+selection+
 'globalThis.testFns={defaultWindow,applyForecastHorizon}',sandbox,{timeout:1000});
assert.deepEqual(Array.from(Object.values(sandbox.testFns.defaultWindow())),
 ["2026-10-20","2026-11-24"]);
sandbox.testFns.applyForecastHorizon();
assert.equal(values.stratoEnsembleFrom.value,"2026-10-20");
assert.equal(values.stratoEnsembleTo.value,"2026-11-24");
values.stratoEnsembleSpan.value="7";
sandbox.testFns.applyForecastHorizon();
assert.equal(values.stratoEnsembleTo.value,"2026-10-26");
values.stratoEnsembleSpan.value="14";
sandbox.testFns.applyForecastHorizon();
assert.equal(values.stratoEnsembleTo.value,"2026-11-02");
values.stratoEnsembleSpan.value="21";
sandbox.testFns.applyForecastHorizon();
assert.equal(values.stratoEnsembleTo.value,"2026-11-09");
values.stratoEnsembleSpan.value="custom";
values.stratoEnsembleFrom.value="2026-10-25";
values.stratoEnsembleTo.value="2026-11-15";
sandbox.testFns.applyForecastHorizon();
assert.equal(values.stratoEnsembleFrom.value,"2026-10-25");
assert.equal(values.stratoEnsembleTo.value,"2026-11-15");
assert.equal(sandbox.drawCounter.calls,4);
assert(js.includes('if($("stratoShowAnalysis").checked)'),
 "NASA analysis must be opt-in");
assert(js.includes('legend:{display:false}'),"Concise forecast uses its own small legend");
console.log("PASS: current-only default, all 31 members, forecast horizon controls and archive switch");
