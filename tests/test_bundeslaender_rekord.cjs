const test=require("node:test"), assert=require("node:assert/strict");
const {bucket,compare,coverage}=require("../bundeslaender_rekord_core.js");
test("calendar buckets, leap day and winter",()=>{
 assert.equal(bucket("2026-01-31","decade"),"1-3");
 assert.equal(bucket("2024-02-29","day"),"02-29");
 assert.equal(bucket("2025-12-31","season"),bucket("2026-02-01","season"));
 assert.notEqual(bucket("2026-03-01","season"),bucket("2026-02-01","season"));
});
test("month comparison includes different days, excludes future and other months",()=>{
 const s=[{date:"2006-11-30",value:-8},{date:"2025-11-02",value:-6},{date:"2026-10-22",value:-20},{date:"2026-11-24",value:-6},{date:"2026-11-25",value:-30}];
 const x=compare(s,"2026-11-24","month","low");
 assert.equal(x.rank,2);assert.equal(x.ties,1);assert.equal(x.last.date,"2025-11-02");assert.equal(x.days,2);
 assert.equal(compare(s,"2026-11-24","day","low").rank,1);
 assert.equal(compare(s,"2026-11-24","month","high").rank,1);
});
test("missing day limits continuous coverage, missing target does not rank",()=>{
 const s=[{date:"2025-11-24",value:5},{date:"2026-11-21",value:2},{date:"2026-11-22",value:null},{date:"2026-11-23",value:1},{date:"2026-11-24",value:0}];
 assert.equal(coverage(s,"2026-11-24","month"),"2026-11-23");
 assert.equal(coverage(s,"2026-11-24","day"),"2025-11-24");
 assert.equal(compare(s,"2026-11-22","month","low"),null);
});

test("annual November extremes may come from different stations and dates",()=>{
 const {annualExtremes}=require("../bundeslaender_rekord_core.js");
 const a=[{date:"2023-11-29",value:-8,stationId:"1"},{date:"2024-11-30",value:-4.6,stationId:"2"},{date:"2024-10-30",value:-10,stationId:"1"},{date:"2025-11-30",value:-6.6,stationId:"3"},{date:"2026-11-24",value:-7,stationId:"1"}];
 const rows=annualExtremes(a,"2026-11-24","month","low",2022);
 assert.deepEqual(rows.map(x=>[x.year,x.entry?.value??null]),[[2025,-6.6],[2024,-4.6],[2023,-8],[2022,null]]);
 assert.equal(rows[0].entry.stationId,"3");
});
