import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const js=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
new Function(js);

for(const requirement of [
  'data-mosmix-mode="rain"', 'data-mosmix-mode="gust"', 'data-mosmix-mode="cloud"',
  "rainDay","gustDay","cloudNl","cloudNm","cloudNh","cloudNeff",
  "visibility","lowVis","fog1","fog6","snow1","snow3","snowProb",
  "thunder1","thunder6","conv1","weatherCode",
  "mosmixCompareStationBtn","mosmixClearComparison","addSecondaryMeteogramDatasets",
  'const MANIFEST_URL = "./data/mosmix/manifest.json"',
  "MANIFEST_BACKUP_URL","loadSplitFrame","splitFrameValues","renderSplitMap",
  "mapChunkCache","DATA_COMPRESSED_URL","sunDayFramesFromTimesteps",
  "mosmixDiagramRange","mosmixComparePrevious","comparePreviousRun",
  'previousSeries("TTT")','previousSeries("TX")','previousSeries("TN")',
  'data?._split'
]){
  assert(js.includes(requirement),"MOSMIX map/meteo feature missing: "+requirement);
}
assert(js.includes('const unit=mapUnit();'),"All map mode units must be honored.");
assert(js.includes('data.issue_time'),"Model run identity must be checked.");
const start=js.indexOf("  function thresholdColor(");
const end=js.indexOf("  function renderLegend()",start);
assert(start>0&&end>start);
const thresholdColor=new Function(js.slice(start,end)+"return thresholdColor;")();
const thresholds=[[0,"#eee"],[20,"#aaa"],[50,"#333"],[100,"#000"]];
assert.equal(thresholdColor(0,thresholds),"#eee");
assert.equal(thresholdColor(19.9,thresholds),"#eee");
assert.equal(thresholdColor(20,thresholds),"#aaa");
assert.equal(thresholdColor(100,thresholds),"#000");
assert.equal(thresholdColor(null,thresholds),"#9ca3af");
assert(js.includes('interpolatedValue(ll.lon,ll.lat,bins,binSize,mapMode==="weather")'),
  "Categorical weather codes must not be interpolated as numeric forecasts.");
assert(js.includes("secondaryDetail.parameters?.[fields[hours]]"),
  "Second-station forecast must follow the selected rainfall/gust interval.");
console.log("PASS: MOSMIX-L Tagespakete, Karten, DWD-Wetterparameter und Stations-/Laufvergleich.");
