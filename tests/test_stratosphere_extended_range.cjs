const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');

function moduleUnderTest(){
  assert.ok(fs.existsSync('stratosphere_extended_range.js'), '46-day ensemble UI missing');
  return require('../stratosphere_extended_range.js');
}
function fixture(){
  const cycle='2026-11-19T00:00:00Z';
  const dates=Array.from({length:47},(_,i)=>new Date(Date.parse(cycle)+i*86400000).toISOString().slice(0,10));
  const members={c00:Array(47).fill(10)};
  for(let i=1;i<=100;i++) members['p'+String(i).padStart(3,'0')]=Array.from({length:47},(_,d)=>i<=20&&d>=2?-10:10);
  return {schema_version:1,provider:'ECMWF IFS Sub-seasonal S2S',cycle_utc:cycle,latitude_deg:60,level_hpa:10,units:'m/s',member_count:101,valid_dates:dates,forecast_step_hours:dates.map((_,i)=>i*24),members};
}
test('all 101 members, daily fractions and actual transitions',()=>{
  const m=moduleUnderTest(), data=fixture();
  assert.equal(m.validate(data),true);
  const result=m.statistics(data);
  assert.equal(result.rows[0].probability,0);
  assert.equal(result.rows[2].probability,20/101*100);
  assert.equal(result.rows[2].mean,610/101);
  assert.equal(result.rows[2].p10,-10);
  assert.equal(result.rows[2].p25,10);
  assert.equal(result.crossing[14],20/101*100);
  delete data.members.p100;
  assert.equal(m.validate(data),false);
});
test('rejects image links outside official chart origin',()=>{
  const m=moduleUnderTest();
  const payload={data:{type:'graphical_product',attributes:{name:'extended-zonal-mean-zonal-wind'},link:{href:'https://charts.ecmwf.int/content/test.png',type:'image/png'}}};
  assert.equal(m.chartLink(payload),'https://charts.ecmwf.int/content/test.png');
  payload.data.link.href='https://example.org/test.png';
  assert.throws(()=>m.chartLink(payload));
});
