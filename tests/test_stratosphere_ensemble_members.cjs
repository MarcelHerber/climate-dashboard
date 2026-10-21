// Ensures that the PRIMARY stratosphere chart plots 31 REAL member traces
// rather than only the GEFS ensemble mean or a synthetic spread.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("stratosphaere.html", "utf8");
const start = html.indexOf("function overlayGEFSEnsemble(");
const end = html.indexOf("function draw(level,year,selected,climo,comparison){", start);
assert(start !== -1 && end > start, "GEFS overlay must be part of primary chart");
const source = html.slice(start, end);

const dates = [
  { key: "10-20", month: 10 }, { key: "10-21", month: 10 },
  { key: "10-22", month: 10 }, { key: "10-23", month: 10 },
];
const valid_dates = dates.map(d => "2026-" + d.key);
const members = Object.fromEntries([
  ["c00", [12, 13, 14, 15]],
  ...Array.from({ length: 30 }, (_, i) => {
    const id = "p" + String(i + 1).padStart(2, "0");
    return [id, [12, 13, 14, 15].map(v => v + (i + 1) * .19)];
  })
]);
const quantiles = Object.fromEntries(["mean", "p05", "p25", "p75", "p95"]
  .map(k => [k, [13, 14, 15, 16]]));
const nodes = {
  windEnsembleToggle: {checked:true},
  windEnsembleBands: {checked:true},
  windEnsembleStatus: {textContent:""},
  mode: {value:"absolute"},
};
const ctx = {
  window: {stratoGefsEnsemble: {
    cycle_utc:"2026-10-20T00:00:00Z",valid_dates,members,quantiles,
  }},
  dates,
  $: id => nodes[id],
  seasonLabel: y => y+"/27",
  modeValues: (rows) => rows,
  line: (label, data, color, width, opts = {}) => ({label, data, color, width, ...opts}),
  band: (low, high, label, color) => [
    {label:"_"+label+" low",data:low,color},
    {label,data:high,color}
  ],
};
vm.createContext(ctx);
vm.runInContext(source,ctx,{timeout:1000});
const datasets = [];
assert.equal(ctx.overlayGEFSEnsemble(datasets,10,2026,{},x=>x), true);
const curves=datasets.filter(d=>d.label==="GEFS · 31 Einzelmitglieder"||
 d.label.startsWith("_GEFS_"));
assert.equal(curves.length,31,"31 individual GEFS traces must be plotted");
assert.equal(curves.filter(d=>d.data.filter(Number.isFinite).length===4).length,31);
assert.equal(new Set(curves.map(d=>d.data[3])).size,31,"members must remain distinct");
assert(datasets.some(d=>d.label==="GEFS · Ensemble-Mittel"));
assert(datasets.some(d=>d.label==="GEFS · Kontrolllauf"));
assert(datasets.some(d=>d.label==="GEFS-Ensemble P5–P95"));
assert(datasets.some(d=>d.label==="GEFS-Ensemble P25–P75"));
assert.match(nodes.windEnsembleStatus.textContent,/31\/31/);
nodes.windEnsembleToggle.checked=false;
assert.equal(ctx.overlayGEFSEnsemble([],10,2026,{},x=>x),false);
nodes.windEnsembleToggle.checked=true;
assert.equal(ctx.overlayGEFSEnsemble([],30,2026,{},x=>x),false);
console.log("PASS: primary 10hPa chart contains 31 distinct member paths, mean, control and both spread bands.");
