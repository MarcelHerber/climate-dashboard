const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const script=fs.readFileSync("station_snow_years.js","utf8");
const html=fs.readFileSync("index.html","utf8");
const context={window:{}};
vm.runInNewContext(script,context);
const api=context.window.StationSnowYears;
const days=["11-01","11-02","02-28","02-29","03-01"];
const archive={
 version:1,station_id:"05792",month_days:days,
 years:[
  {year:2025,coverage:1,valid_days:365,accepted:true,values:[4,7,11,null,14]},
  {year:2024,coverage:.48,valid_days:175,accepted:false,values:[1,null,3,6,8]},
  {year:1955,coverage:.02,valid_days:8,accepted:false,values:[null,0,null,null,0]}
 ]
};
test("historic years including incomplete data are independently selectable",()=>{
 const list=api.yearList(archive,2027,true);
 assert.deepEqual(Array.from(list,x=>x.year),[2027,2025,2024,1955]);
 assert.equal(list[0].isCurrent,true);
 assert.equal(list[2].accepted,false);
 assert.equal(list[3].validDays,8);
});
test("day-by-day values align with hydrological axis; missing is null not zero",()=>{
 const values=api.values(archive,2025,days,2027,new Map());
 assert.deepEqual(Array.from(values),[4,7,11,null,14]);
 assert.equal(api.values(archive,1955,days,2027,new Map())[1],0);
 assert.equal(api.values(archive,1955,days,2027,new Map())[0],null);
});
test("current season and historical seasons use identical month-day alignment",()=>{
 const current=new Map([["11-01",{snow:2}],["11-02",{snow:0}],["03-01",{snow:15}]]);
 const result=api.curves({archive,selectedYears:new Set([2025,2024,2027]),
   monthDays:days,currentYear:2027,currentByMonthDay:current,median:[0,1,5,2,7]});
 assert.deepEqual(Array.from(result,x=>x.year),[2025,2024,2027]);
 assert.deepEqual(Array.from(result[2].values),[2,0,null,null,15]);
 assert.deepEqual(Array.from(result[1].deviations),[1,null,-2,4,1]);
 assert.equal(result[2].current,true);
 assert.equal(result[0].current,false);
});
test("no selection shows no selected-year curves, not artificial data",()=>{
 assert.equal(api.curves({archive,selectedYears:new Set(),monthDays:days,
   currentYear:2027,currentByMonthDay:new Map(),median:[0,0,0,0,0]}).length,0);
});
test("snow station navigation does not restore a stale mobile tab",()=>{
 assert.match(html,/if\(control\.id==="mobileTabSelect"\)return;[\s\S]{0,80}const saved=dashboardState\[control\.id\]/);
 assert.match(html,/if\(control\.id==="mobileTabSelect"\)return; \/\/ persisted by switchTab only/);
 assert.match(html,/id="stationSnowYearsList"/);
 assert.match(html,/stationSnowPopulateYearPicker\(station,archive,current,hydroYear\)/);
 assert.match(html,/datasets:yearCurves\.map\(curve=>/);
 assert.match(html,/station_snow_years\.js\?v=/);
});
