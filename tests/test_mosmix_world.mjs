// Regression guard: worldwide MOSMIX fetch/UI is intentionally disabled.
// Historical filename retained because existing workflows invoke this test.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const js=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
new Function(js);
for(const phrase of [
  "mosmixMap", "mosmixStationSearch", "mosmixSunChart",
  "mosmixSunDailyChart", "SunD1", "Rad1h",
  "Sonnenschein letzte 1 h", "Gleitende 24-h-Sonnenscheindauer",
  "Globalstrahlung", 'data-mosmix-mode="sun"', "colorForSun", "station.sun1"
]){
  assert.ok(js.includes(phrase),"MOSMIX Deutschland UI fehlt: "+phrase);
}
for(const removed of [
  "WORLD_INDEX_URL", "WORLD_BASE", "world_stations.json",
  "getWorldShard", "loadWorldIndex", "mosmixWorldSearch",
  "mosmixWorldList", "mosmixWorldOpen", "worldShardCache",
  "openWorldStation", "station.shard", "worldTiles"
]){
  assert.ok(!js.includes(removed),"Globale MOSMIX-Suche muss deaktiviert sein: "+removed);
}
const start=js.indexOf("function rollingSunshine24h(");
const end=js.indexOf("  // A SunD1 sample",start);
assert.ok(start>0&&end>start);
const rolling=new Function(js.slice(start,end)+"return rollingSunshine24h;")();
assert.equal(rolling(Array(24).fill(60))[23],24);
assert.equal(rolling(Array(24).fill(30))[23],12);
assert.equal(rolling(Array(24).fill(60))[22],null);
assert.equal(rolling([...Array(23).fill(60),null])[23],null);
assert.equal(rolling([0,15,30])[2],null);
console.log("PASS: MOSMIX nur Deutschland, globale Daten abgeschaltet, Sonne und Globalstrahlung erhalten.");
