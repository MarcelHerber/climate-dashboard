const assert=require("node:assert/strict");
const test=require("node:test");
const fs=require("node:fs");
const html=fs.readFileSync("index.html","utf8");

test("HYRAS temperature rank archive is an accessible collapsed disclosure",()=>{
  const start=html.indexOf('<details id="hyrasTemperatureRanks"');
  const end=html.indexOf('</details>',start);
  assert.ok(start>=0&&end>start,"Missing native details");
  const section=html.slice(start,end+10);
  assert.match(section,/<summary id="hyrasRankHeading" class="hyras-rank-summary">/);
  assert.ok(!html.slice(start,start+240).includes(" open"),"Must start collapsed");
  for(const id of ["hyrasRankParameterSelect","hyrasRankDayImage","hyrasRankMonthImage","hyrasRankSummerImage","hyrasRankSlider","hyrasRankDownload"]){
    assert.ok(section.includes('id="'+id+'"'),id);
  }
  assert.ok(section.includes("Sommerarchiv 2026"));
  assert.ok(section.includes("31.08.2026"));
  assert.equal(section.split("<summary").length-1,1);
});

test("HYRAS live monthly selection takes priority over last completed period",()=>{
  assert.ok(html.includes('return periods.find(p=>p.period_type==="month_live")||periods.find(p=>p.period_type==="season_live")'));
  assert.ok(html.includes('periods.find(p=>p.period_type==="month_live")?.key||hyrasIndex.default_period'));
  const useLatest=(html.match(/const preferred=periods\.filter\(period=>period\.key\.startsWith\("month_"\)\)/g)||[]).length;
  assert.equal(useLatest,2,"Tmax and Tmin should select most recent observed month");
  assert.ok(html.includes('["month_live","season_live","summer_live","ytd_live"].includes(period.period_type)'));
});

test("all inline scripts still parse",()=>{
  const scripts=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)]
    .map(x=>x[1]).filter(x=>x.trim());
  for(const code of scripts)assert.doesNotThrow(()=>new Function(code));
});
