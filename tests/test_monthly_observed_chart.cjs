const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");

const html=require("./dashboard_source.cjs")();
const builder=fs.readFileSync("scripts/build_pages_site.sh","utf8");

function functionSource(name){
  const start=html.indexOf("function "+name+"(");
  assert.ok(start>=0,"missing function "+name);
  const brace=html.indexOf("{",start);
  let depth=0,end=brace;
  for(;end<html.length;end++){
    if(html[end]==="{")depth++;
    if(html[end]==="}"&&--depth===0){end++;break;}
  }
  return html.slice(start,end);
}

test("provisional month lives inside historical Chart.js instead of a separate appended panel",()=>{
  assert.ok(html.includes('id="monthlyObservedChartNote"'));
  assert.ok(html.includes("const observed=observedMonthlyBar(area,selection,param,values)"));
  assert.ok(html.includes("if(observed)labels.push(observed.year)"));
  assert.ok(html.includes("backgroundColor:observedHatch"));
  assert.ok(html.includes("grouped:false"));
  assert.match(html,/if\s*\(monthlyData\.length\)\s*\{?\s*updateMonthly\(\)/);
  assert.ok(!builder.includes("  monthly_provisional.js\n"),"old unreliable extension still published");
  assert.ok(builder.includes("observed.year} vorläufig"),"Pages build missing integrated-chart check");
  assert.ok(builder.includes("monthly_provisional_history.json"),"Pages build missing archived months");
});

function harness(now,snapshots,docs={},rows=[]){
  const FakeDate=class extends Date {constructor(...args){super(...(args.length?args:[now]));}};
  const helpers=["observedMonthlyBar","monthlyOutlookValue","liveCalendarMonth","liveMonthlyValue","seasonForMonth","combineSeason","liveSeasonValue","periodKeys"];
  return new Function("Date","monthlyObservedHistory","currentMonthOutlookDocs","monthlyData",
    helpers.map(functionSource).join("\n")+"\nfunction areaRows(area){return monthlyData.filter(r=>r.area===area);}\nreturn {observedMonthlyBar,combineSeason,liveSeasonValue,seasonForMonth};")(FakeDate,snapshots,docs,rows);
}
const area="Rheinland-Pfalz",old=[{year:2025,value:5.6}];
function snapshot(month,day,temp,rain){
  return {schema:1,month,data_through:month+"-"+String(day).padStart(2,"0"),days_in_month:new Date(Number(month.slice(0,4)),Number(month.slice(5)),0).getDate(),forecast:false,areas:{[area]:{temp,rain}}};
}
test("November provisional stays while December starts, and final DWD values replace it",()=>{
  const snapshots=[snapshot("2026-11",30,5.69,10.2),snapshot("2026-12",2,3.35,2.1)];
  const {observedMonthlyBar:bar}=harness("2026-12-03T10:00:00Z",snapshots);
  assert.deepEqual(bar(area,"11","temp",old),{year:2026,value:5.69,through:"2026-11-30",source:"HYRAS",mode:"observed",complete:true});
  assert.deepEqual(bar(area,"12","temp",old),{year:2026,value:3.35,through:"2026-12-02",source:"HYRAS",mode:"observed",complete:false});
  assert.equal(bar(area,"10","temp",old),null);
  assert.equal(bar(area,"11","sun",old),null);
  assert.equal(bar(area,"11","temp",[...old,{year:2026,value:5.41}]),null);
  assert.equal(bar(area,"11","rain",old).value,10.2);
  assert.deepEqual(snapshots[0].areas[area],{temp:5.69,rain:10.2});
});
test("GEFS complete month is included in the autumn bar, gaps and stale runs fall back",()=>{
  const dates=Array.from({length:30},(_,i)=>"2026-11-"+String(i+1).padStart(2,"0"));
  const doc={year:2026,month:11,dates,regions:{[area]:{
    observed_through:dates[22],observed_running:dates.map((_,i)=>i<23?4:null),
    models:{gefs:{run:"2026-11-25T00:00:00Z",forecast_from:dates[23],forecast_through:dates[29],stats:{mean:dates.map((_,i)=>i>=23?5:null)}}}
  }}};
  const rows=[{area,date:"2026-09",temp:12},{area,date:"2026-10",temp:8}];
  const check=()=>harness("2026-11-25T11:00:00Z",[],{temp:doc},rows).observedMonthlyBar;
  const full=check()(area,"autumn","temp",old);
  assert.equal(full.complete,true);assert.equal(full.mode,"forecast");assert.equal(full.days,91);
  assert.equal(full.value,(12*30+8*31+5*30)/91);
  assert.equal(check()(area,"11","temp",old).value,5);
  assert.equal(check()(area,"autumn","temp",[...old,{year:2026,value:8}]),null);
  doc.regions[area].models.gefs.stats.mean[28]=null;
  const partial=check()(area,"autumn","temp",old);
  assert.equal(partial.complete,false);assert.equal(partial.days,84);assert.equal(partial.value,(12*30+8*31+4*23)/84);
  doc.regions[area].models.gefs.stats.mean[28]=5;
  doc.regions[area].models.gefs.run="2026-11-20T00:00:00Z";
  assert.equal(check()(area,"autumn","temp",old).mode,"observed");
});
test("winter year rollover, leap day, totals and missing past month",()=>{
  const {combineSeason,seasonForMonth}=harness("2026-12-03T10:00:00Z",[]);
  assert.deepEqual(seasonForMonth("2026-12"),{year:2027,selection:"winter"});
  assert.deepEqual(seasonForMonth("2027-02"),{year:2027,selection:"winter"});
  const months=["2023-12","2024-01","2024-02"];
  const full=combineSeason(months,"2024-02","rain",()=>10,()=>null);
  assert.equal(full.days,91);assert.equal(full.value,30);assert.equal(full.complete,true);
  assert.equal(combineSeason(months,"2024-01","rain",()=>10,()=>null).value,20);
  assert.equal(combineSeason(months,"2024-02","rain",m=>m==="2024-01"?null:10,()=>null),null);
});
test("main inline scripts parse without JavaScript syntax errors",()=>{
  const scripts=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)]
    .map(match=>match[1]).filter(source=>source.trim());
  for(const source of scripts)assert.doesNotThrow(()=>new Function(source));
});
