const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const source = globalThis.TEST_SOURCE || fs.readFileSync(path.join(__dirname, "../index.html"), "utf8");
const start = source.indexOf("function stationPrecipCalendarLabels(");
const stop = source.indexOf("function stationPrecipFormat(",start);
const api = start < 0 ? {} : new Function(source.slice(start,stop)+"\nreturn {stationPrecipCalendarLabels, stationPrecipDecodeYear, stationPrecipYearView, stationPrecipHistoricalDatasets};")();
function encode(year, entries) {
  const length = (year%4===0&&year%100!==0)||year%400===0?366:365;
  const buffer = Buffer.alloc(length*2);
  for(const [index,value] of entries) buffer.writeUInt16BE(value,index*2);
  return buffer.toString("base64");
}
test("full calendar retains future nulls and uses original complete annual curves",()=>{
  assert.equal(typeof api.stationPrecipYearView,"function");
  const labels=api.stationPrecipCalendarLabels(2026);
  const result=api.stationPrecipYearView({year:2026,dataThrough:"2026-01-02",currentDaily:[1,2],profile:{historical_year_daily_tenths:{"1999":encode(1999,[[0,10],[364,90]]),"2000":encode(2000,[[0,20],[59,30],[365,150]]),"2001":encode(2001,[[364,150]]),"2002":encode(2002,[[364,150]]),"2003":encode(2003,[[364,150]])}}});
  assert.equal(result.labels[0],"01-01");
  assert.equal(result.labels.at(-1),"12-31");
  assert.equal(result.labels.length,365);
  assert.deepEqual(result.current.slice(0,4),[1,3,null,null]);
  assert.equal(result.climate.at(-1),15);
  assert.equal(result.curves["2000"][59],5);
  assert.equal(result.curves["2000"].at(-1),20);
  assert.equal(result.curves["1999"].at(-1),10);
  assert.equal(result.dryYear,1999);
  assert.equal(result.wetYear,2000);
});
test("chosen years only are represented in exportable datasets",()=>{
  assert.equal(typeof api.stationPrecipHistoricalDatasets,"function");
  let view={curves:{"1999":[1,2],"2000":[2,4],"2001":[1,3]},dryYear:1999,wetYear:2000};
  assert.deepEqual(api.stationPrecipHistoricalDatasets(view,new Set()).map(d=>d.label),[]);
  assert.deepEqual(api.stationPrecipHistoricalDatasets(view,new Set([2000])).map(d=>[d.label,d.data.at(-1)]),[["2000",4]]);
  const all=api.stationPrecipHistoricalDatasets(view,new Set([1999,2000,2001]));
  assert.equal(all.length,3);
  assert.notEqual(all[0].borderColor,all[2].borderColor);
  assert.notEqual(all[1].borderColor,all[2].borderColor);
});
test("old profile without individual history still has a full reference and axis",()=>{
  assert.equal(typeof api.stationPrecipYearView,"function");
  const profile={climate_mean_cumulative:Array(365).fill(8),historical_min_cumulative:Array(365).fill(3),historical_max_cumulative:Array(365).fill(12)};
  const view=api.stationPrecipYearView({year:2026,dataThrough:"2026-01-01",currentDaily:[0],profile});
  assert.equal(view.climate.at(-1),8);
  assert.equal(view.minimum.at(-1),3);
  assert.equal(view.maximum.at(-1),12);
  assert.equal(view.current.at(-1),null);
  assert.deepEqual(Object.keys(view.curves),[]);
});

test("fewer than five exact reference years preserve the published climate normal",()=>{
  const profile={climate_mean_cumulative:Array(365).fill(8),historical_year_daily_tenths:{"2000":encode(2000,[[0,20]])}};
  const view=api.stationPrecipYearView({year:2026,dataThrough:"2026-01-01",currentDaily:[0],profile});
  assert.equal(view.climate.at(-1),8);
  assert.equal(view.referenceCount,0);
  assert.equal(view.curves["2000"].at(-1),2);
});