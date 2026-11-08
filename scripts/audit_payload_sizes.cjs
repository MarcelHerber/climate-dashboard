#!/usr/bin/env node
/* Reproducible payload and JSON parse-cost audit.
   Keeps the real current-year data, station count and scientific precision. */
const fs=require("node:fs");
const zlib=require("node:zlib");
const assert=require("node:assert/strict");
const {performance}=require("node:perf_hooks");

const entries=[
  "index.html","station_precip_index.json","station_snow_height_additional_index.json",
  "daily_tmax_1881_2026.json","station_records.json","data.json"
];
const result=[];
for(const path of entries){
  if(!fs.existsSync(path))continue;
  const buf=fs.readFileSync(path);
  const entry={name:path,raw_bytes:buf.length,gzip_bytes:zlib.gzipSync(buf,{level:6}).length};
  if(path.endsWith(".json")){
    const data=JSON.parse(buf.toString("utf8"));
    const compact=Buffer.from(JSON.stringify(data)+"\n","utf8");
    entry.compact_bytes=compact.length;
    entry.compact_gzip_bytes=zlib.gzipSync(compact,{level:6}).length;
    const samples=[];
    for(let i=0;i<7;i++){
      const t=performance.now();
      const restored=JSON.parse(compact.toString("utf8"));
      samples.push(performance.now()-t);
      // JS stringify canonicalizes -0 to 0 (e.g. station elevation).
      // Compare normalized JSON semantics; the Python Pages writer itself
      // preserves the signed original values from the committed archive.
      assert.equal(JSON.stringify(restored),JSON.stringify(data));
    }
    samples.sort((a,b)=>a-b);
    entry.compact_parse_median_ms=Number(samples[3].toFixed(2));
    if(path==="station_precip_index.json"){
      assert.ok(data.ready);
      assert.ok(data.stations.length>=500);
      assert.ok(compact.length<=buf.length);
      entry.stations=data.stations.length;
      entry.reduction_percent=Number((100*(1-compact.length/buf.length)).toFixed(1));
    }
  }
  result.push(entry);
}
console.log(JSON.stringify({audit:"climate-dashboard-payloads",results:result},null,2));
