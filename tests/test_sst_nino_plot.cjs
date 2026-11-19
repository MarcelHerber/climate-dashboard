const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("sst_nino_years.js", "utf8");
let config;
const nodes = {
  sstYearsMetric: {value: "absolute"},
  sstYearsHistory: {value: "all"},
  sstYearsYear: {value: "2020"},
  sstYearsCanvas: {getContext() { return {}; }},
  sstYearsPng: {}, sstYearsCsv: {}
};
function Chart(context, options) { config = options; }
const document = {readyState:"loading", addEventListener(){}, getElementById(id){return nodes[id]||null;}};
const window = {Chart};
vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, 'window.drawTest = function(data) { current={data,region:"nino12"}; renderPlot(); };})();'), {document,window,Chart,console,Date,Map});
const years = {};
for(let year=1991;year<=2026;year++) years[year] = Array(366).fill(20);
years[2026].fill(null, 320);
window.drawTest({years,lastDate:"2026-11-15"});
assert.equal(config.data.labels.length, 366);
assert.ok(config.data.datasets.length > 30);
for (const dataset of config.data.datasets) {
  assert.equal(dataset.data.length, 366);
  // With parsing disabled Chart.js expects its internal {x,y} format, not scalar values.
  if (config.options.parsing === false) {
    assert.ok(dataset.data.every((v,i)=>v && typeof v === "object" && v.x === i && "y" in v),
      "Chart.js cannot render scalar datasets with parsing disabled");
  }
}
const current = config.data.datasets.find(d=>d.label==="2026");
assert.equal(current.data[319],20);
assert.equal(current.data[320],null);
console.log("Niño chart data format and incomplete current year verified.");
