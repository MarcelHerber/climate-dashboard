import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const js=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
new Function(js);
for(const phrase of [
 "world_stations.json","getWorldShard","openWorldStation",
 "mosmixWorldSearch","mosmixWorldList","mosmixBackGermany",
 "mosmixSunChart","SunD1","Rad1h",
 "Sonnenschein letzte 1 h","Gleitende 24-h-Sonnenscheindauer",
 "Globalstrahlung","worldMapPin","Weltstation anzeigen",
 "data-mosmix-mode=\\"sun\\"","colorForSun","station.sun1"
]){
 assert(js.includes(phrase),"MOSMIX UI missing: "+phrase);
}
const start=js.indexOf("function rollingSunshine24h(");
const end=js.indexOf("function destroyMeteogramCharts()",start);
assert(start>0&&end>start);
const rolling=new Function(js.slice(start,end)+"return rollingSunshine24h;")();
assert.equal(rolling(Array(24).fill(60))[23],24);
assert.equal(rolling(Array(24).fill(30))[23],12);
assert.equal(rolling(Array(24).fill(60))[22],null);
assert.equal(rolling([...Array(23).fill(60),null])[23],null);
assert.equal(rolling([0,15,30])[2],null);
assert.equal(js.includes('minZoom:2'),true);
assert.equal(js.includes('station.shard'),true);
console.log("PASS: MOSMIX Weltstationssuche, echte SunD1/Rad1h und gleitende 24-h-Sonne.");
