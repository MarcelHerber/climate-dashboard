const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");

const html=fs.readFileSync("index.html","utf8");
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
  assert.ok(html.includes("monthlyData.length)updateMonthly()"));
  assert.ok(!builder.includes("  monthly_provisional.js\n"),"old unreliable extension still published");
  assert.ok(builder.includes("observed.year} vorläufig"),"Pages build missing integrated-chart check");
  assert.ok(builder.includes("monthly_provisional_history.json"),"Pages build missing archived months");
});

test("November provisional stays while December starts, and final DWD values replace it",()=>{
  const snapshots=[
    {schema:1,month:"2026-11",data_through:"2026-11-30",forecast:false,
      areas:{"Rheinland-Pfalz":{temp:5.69,rain:10.2}}},
    {schema:1,month:"2026-12",data_through:"2026-12-02",forecast:false,
      areas:{"Rheinland-Pfalz":{temp:3.35,rain:2.1}}}
  ];
  const observedMonthlyBar=new Function("monthlyObservedHistory",
    "return "+functionSource("observedMonthlyBar"))(snapshots);
  const old=[{year:2025,value:5.6}];
  assert.deepEqual(observedMonthlyBar("Rheinland-Pfalz","11","temp",old),
    {year:2026,value:5.69,through:"2026-11-30"});
  assert.deepEqual(observedMonthlyBar("Rheinland-Pfalz","12","temp",old),
    {year:2026,value:3.35,through:"2026-12-02"});
  assert.equal(observedMonthlyBar("Rheinland-Pfalz","10","temp",old),null);
  assert.equal(observedMonthlyBar("Rheinland-Pfalz","11","sun",old),null);

  // DWD may publish November temperature before November precipitation.
  const finalTemp=[...old,{year:2026,value:5.41}];
  assert.equal(observedMonthlyBar("Rheinland-Pfalz","11","temp",finalTemp),null);
  assert.deepEqual(observedMonthlyBar("Rheinland-Pfalz","11","rain",old),
    {year:2026,value:10.2,through:"2026-11-30"});
  assert.deepEqual(snapshots[0].areas["Rheinland-Pfalz"],{temp:5.69,rain:10.2});
});

test("main inline scripts parse without JavaScript syntax errors",()=>{
  const scripts=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)]
    .map(match=>match[1]).filter(source=>source.trim());
  for(const source of scripts)assert.doesNotThrow(()=>new Function(source));
});
