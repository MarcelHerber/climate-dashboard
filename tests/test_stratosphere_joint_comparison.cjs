const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const context={window:{},document:{getElementById:()=>null}};
vm.runInNewContext(fs.readFileSync('stratosphere_joint_comparison.js','utf8'),context);
const {summarize,align,percentile}=context.window.stratoJointMath;
const days=['2026-11-08','2026-11-09','2026-11-10','2026-11-11'];
function model(which,hour=0){
  const eps=which==='eps',members={c00:[4,1,-2,-1]};
  const total=eps?50:30;
  for(let i=1;i<=total;i++){
    const id='p'+String(i).padStart(2,'0');
    members[id]=i===1?[-1,-2,-3,-1]:i===2?[3,-1,2,-1]:[5,4,4,5];
  }
  return {
    provider:eps?'ECMWF IFS ENS':'NOAA GEFS',
    level_hpa:10,latitude_deg:60,units:'m/s',
    cycle_utc:'2026-11-08T'+String(hour).padStart(2,'0')+':00:00Z',
    valid_dates:[...days],members
  };
}
test('per-day percentages and first signed crossings use original samples, not inferred times',()=>{
  const g=summarize(model('gefs'),0,'gefs');
  const e=summarize(model('eps'),0,'eps');
  assert.equal(g.count,31);
  assert.equal(e.count,51);
  assert.equal(g.crossed,2);
  assert.equal(e.crossed,2);
  assert.deepEqual(Array.from(g.rows,r=>r.first),[0,1,1,0]);
  assert.deepEqual(Array.from(e.rows,r=>r.first),[0,1,1,0]);
  assert.deepEqual(Array.from(g.rows,r=>r.negative),[1,2,2,3]);
  assert.equal(g.rows[1].mean,(1-2-1+(31-3)*4)/31);
  for(const row of e.rows){
    assert.ok(row.p05<=row.p25 && row.p25<=row.p75 && row.p75<=row.p95);
  }
  // Members starting in easterlies aren't new reversals until they cross from >=0.
  assert.equal(g.rows[0].first,0);
});
test('shared-UTC forecast comparison only includes dates common to both model products',()=>{
  const gefs=summarize(model('gefs',12),12,'gefs');
  const limited=model('eps',12);
  limited.valid_dates=limited.valid_dates.slice(1);
  Object.keys(limited.members).forEach(key=>limited.members[key]=limited.members[key].slice(1));
  const eps=summarize(limited,12,'eps');
  const rows=align(gefs,eps);
  assert.deepEqual(Array.from(rows,r=>r.date),days.slice(1));
  assert.equal(rows[0].g.date,rows[0].e.date);
  assert.equal(rows.length,3);
});
test('different UTC hours, invalid member totals and fabricated incomplete values are rejected',()=>{
  assert.equal(summarize(model('gefs',0),12,'gefs'),null);
  const corrupted=model('eps',0);
  delete corrupted.members.p50;
  assert.equal(summarize(corrupted,0,'eps'),null);
  const broken=model('gefs',0);
  broken.members.p30[1]=null;
  assert.equal(summarize(broken,0,'gefs'),null);
  assert.deepEqual(Array.from(align(summarize(model('gefs',0),0,'gefs'),null)),[]);
});
test('all chart intervals retain exact finite quantiles and no time interpolation',()=>{
  assert.equal(percentile([0,10,20,30],.50),15);
  assert.equal(percentile([0,10,20,30],.05),1.5);
  const g=summarize(model('gefs',12),12,'gefs');
  assert.ok(g.rows.every(r=>Number.isFinite(r.mean)&&Number.isFinite(r.p05)));
  assert.ok(g.rows.every(r=>r.date.includes('2026-11-')));
});
