"use strict";
const test=require("node:test"),assert=require("node:assert/strict");
const C=require("../stations_rekordlabor_core.js");
test("February 29 is never invented for non-leap years",()=>{
 assert.equal(C.dayIndex(2023,"02-29"),-1);
 assert.equal(C.dayIndex(2024,"02-29"),59);
 assert.equal(C.dayIndex(2024,"03-01"),60);
 assert.equal(C.dayIndex(2023,"03-01"),59);
});
test("seasonal Y axis uses calendar dates at month starts with a leap-day tooltip",()=>{
 const axis=C.seasonDateAxis();
 assert.equal(axis.min,1);
 assert.equal(axis.max,366);
 assert.deepEqual(axis.ticks.map(t=>t.label),
  ["1.1.","1.2.","1.3.","1.4.","1.5.","1.6.",
   "1.7.","1.8.","1.9.","1.10.","1.11.","1.12."]);
 assert.equal(axis.format(1),"1.1.");
 assert.equal(axis.format(60),"29.2.");
 assert.equal(axis.format(61),"1.3.");
 assert.equal(axis.format(366),"31.12.");
 assert.equal(axis.format(367),"");
});
test("hydrological snow Y axis uses real Nov-to-Oct month dates",()=>{
 const days=Array.from({length:366},(_,i)=>
   new Date(Date.UTC(2023,10,1+i)).toISOString().slice(5,10));
 const axis=C.seasonDateAxis(days);
 assert.equal(axis.min,1);
 assert.equal(axis.max,366);
 assert.deepEqual(axis.ticks.map(t=>t.label),
  ["1.11.","1.12.","1.1.","1.2.","1.3.","1.4.",
   "1.5.","1.6.","1.7.","1.8.","1.9.","1.10."]);
 assert.equal(axis.format(1),"1.11.");
 assert.equal(axis.format(days.indexOf("02-29")+1),"29.2.");
 assert.equal(axis.format(366),"31.10.");
});

test("season dates zoom to observed values instead of wasting most of the chart height",()=>{
 const values=[279,281,284,277,286,282,280];
 const axis=C.seasonDateAxis(null,values);
 assert.ok(axis.min<=Math.min(...values));
 assert.ok(axis.max>=Math.max(...values));
 assert.ok(axis.max-axis.min<40,"An autumn event range must not show the full year");
 assert.ok(axis.ticks.length>=3,"Narrow date scale needs several real date labels");
 assert.ok(axis.ticks.every(t=>t.label===axis.format(t.value)));
 assert.ok(axis.ticks.every(t=>t.value>=axis.min&&t.value<=axis.max));
 assert.equal(axis.format(60),"29.2.","Tooltip uses unchanged leap-year coordinates");
});
test("snow date axis zoom respects hydrological years and boundary observations",()=>{
 const days=Array.from({length:366},(_,i)=>
   new Date(Date.UTC(2023,10,1+i)).toISOString().slice(5,10));
 const values=[days.indexOf("01-11")+1,days.indexOf("01-14")+1,
   days.indexOf("01-17")+1];
 const axis=C.seasonDateAxis(days,values);
 assert.ok(axis.min>=1&&axis.max<=366);
 assert.ok(axis.max-axis.min<40);
 assert.equal(axis.format(values[0]),"11.1.");
 assert.equal(axis.format(values[2]),"17.1.");
 const boundary=C.seasonDateAxis(days,[1,2,3]);
 assert.equal(boundary.min,1);
 assert.ok(boundary.max<30,"The first days of November must zoom near November");
});
test("season axis handles absent and degenerate observations without clipping",()=>{
 const empty=C.seasonDateAxis(null,[]);
 assert.equal(empty.min,1);
 assert.equal(empty.max,366);
 const single=C.seasonDateAxis(null,[170,170,null,NaN,0,400]);
 assert.ok(single.min<170&&single.max>170);
 assert.ok(single.max-single.min<=30);
 assert.ok(single.ticks.length>=3);
 const last=C.seasonDateAxis(null,[365,366]);
 assert.equal(last.max,366);
 assert.ok(last.min<365);
});

test("DWD daily zlib16 decoded into original 366-day records",()=>{
 const doc={format:"dwd-tx-tn-tm-zlib16-v1",years:[2023,2024]};
 const bytes=new ArrayBuffer(2*366*3*2);const view=new DataView(bytes);
 for(let i=0;i<366*3*2;i++)view.setInt16(i*2,-32768,true);
 const x=(y,day,field,v)=>view.setInt16(((y===2023?0:366*3)+day*3+field)*2,v,true);
 x(2023,58,0,95);x(2024,59,0,125);
 x(2024,60,0,150);
 const map=C.decodeRawTemperature(doc,bytes);
 assert.equal(map.get(2023).length,365);
 assert.equal(map.get(2024).length,366);
 assert.equal(C.calendarTemperature(map,"02-29",0).length,1);
 assert.equal(C.calendarTemperature(map,"02-29",0)[0].value,12.5);
 assert.equal(C.calendarTemperature(map,"03-01",0).length,1);
 assert.equal(C.calendarTemperature(map,"03-01",0)[0].value,15);
});
test("Snow calendar selects the correct hydrological year and only accepted QC years",()=>{
 const archive={month_days:["11-01","02-29","10-31"],years:[
  {year:2024,accepted:true,values:[1,12,0]},
  {year:2025,accepted:true,values:[4,null,0]},
  {year:2020,accepted:false,values:[55,23,0]}
 ]};
 const feb=C.snowCalendar(archive,"02-29");
 assert.deepEqual(feb.map(x=>x.year),[2024]);
 const nov=C.snowCalendar(archive,"11-01");
 assert.deepEqual(nov.map(x=>x.date),["2023-11-01","2024-11-01"]);
});
test("Seasonal frost and heat events reject years with missing measurement periods",()=>{
 const valid=Array.from({length:365},()=>[20,5,10]);
 const bad=Array.from({length:365},()=>[20,5,10]);
 for(let i=0;i<30;i++)bad[i]=[null,null,null];
 valid[C.dayIndex(2023,"03-12")]=[6,-1,2];
 valid[C.dayIndex(2023,"05-20")]=[15,-1,5];
 valid[C.dayIndex(2023,"07-20")]=[33,12,23];
 const map=new Map([[2023,valid],[2022,bad]]);
 const frost=C.tempSeason(map,"frostSpring");
 assert.equal(frost.records.length,1);assert.equal(frost.records[0].md,"05-20");
 assert.deepEqual(frost.excluded,[2022]);
 const heat=C.tempSeason(map,"hotFirst");
 assert.equal(heat.records.length,1);assert.equal(heat.records[0].md,"07-20");
});
test("Snow first/last and longest continuous period do not cross null gaps",()=>{
 const days=Array.from({length:366},(_,i)=>
   new Date(Date.UTC(2003,10,1+i)).toISOString().slice(5,10));
 const values=days.map(()=>0);
 values[days.indexOf("11-02")]=2;values[days.indexOf("11-03")]=3;
 values[days.indexOf("11-04")]=null;values[days.indexOf("02-02")]=5;
 const archive={month_days:days,
  years:[{year:2025,accepted:true,coverage:1,values}]};
 assert.equal(C.snowSeason(archive,"snowFirst").records[0].md,"11-02");
 assert.equal(C.snowSeason(archive,"snowLast").records[0].md,"02-02");
 const max=C.snowLongest(archive);
 assert.equal(max[0].days,2);
});
test("Max angular wind change 180° and direction threshold ≥3 m/s",()=>{
 assert.equal(C.stationWindDifference({speed:4,direction:355},{speed:3,direction:5}),10);
 assert.equal(C.stationWindDifference({speed:4,direction:0},{speed:4,direction:180}),180);
 assert.equal(C.stationWindDifference({speed:2.9,direction:355},{speed:3,direction:5}),null);
});

test("seasonal rank sorts calendar date rather than raw 365/366 day index",()=>{
 const y2023=Array.from({length:365},()=>[20,3,10]);
 const y2024=Array.from({length:366},()=>[20,3,10]);
 y2023[C.dayIndex(2023,"03-01")]=[10,-2,4];
 y2024[C.dayIndex(2024,"03-01")]=[10,-2,4];
 const ranked=C.tempSeason(new Map([[2024,y2024],[2023,y2023]]),"frostSpring");
 assert.equal(ranked.records.length,2);
 assert.equal(ranked.records[0].md,"03-01");
 assert.equal(ranked.records[1].md,"03-01");
 assert.equal(ranked.records[0].dayOfYear,ranked.records[1].dayOfYear);
});

test("Historical DWD KL RSK/SDK retains leap-day records and missing days",()=>{
 const doc={years:[2023,2024],metrics:{rain:{encoded:"dwd-kl-daily-zlib16-v1"}}};
 const buf=new ArrayBuffer(2*366*2),view=new DataView(buf);
 for(let i=0;i<366*2;i++)view.setInt16(i*2,-32768,true);
 view.setInt16((366+59)*2,224,true);  // 22.4 mm on February 29, 2024
 view.setInt16((366+60)*2,53,true);   // 5.3 mm on March 1
 view.setInt16(58*2,122,true);        // 12.2 mm February 28, 2023
 const map=C.decodeRawDailyMetric(doc,"rain",buf);
 assert.equal(C.calendarKL(map,"02-29").length,1);
 assert.equal(C.calendarKL(map,"02-29")[0].value,22.4);
 assert.equal(C.calendarKL(map,"03-01").length,1);
 assert.equal(C.calendarKL(map,"03-01")[0].value,5.3);
 assert.equal(C.calendarKL(map,"12-31").length,0);
});
