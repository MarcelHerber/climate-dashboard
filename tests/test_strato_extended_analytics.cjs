const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{},document:{getElementById:()=>null},console};
for(const file of ['stratosphere_nasa_common.js','stratosphere_joint_comparison.js',
  'stratosphere_analysis_forecast.js','stratosphere_comparison_metrics.js',
  'stratosphere_vertical_profile.js']) {
  vm.runInNewContext(fs.readFileSync(file,'utf8'),context,{filename:file});
}
const nasa=context.window.stratoNASAData;
const joint=context.window.stratoJointMath;
const history=context.window.stratoHistoryMath;
const metric=context.window.stratoMetricsMath;
const vertical=context.window.stratoVerticalMath;
const start='2026-11-07',days=[start,'2026-11-08','2026-11-09',
  '2026-11-10','2026-11-11','2026-11-12','2026-11-13',
  '2026-11-14','2026-11-15','2026-11-16','2026-11-17',
  '2026-11-18','2026-11-19','2026-11-20','2026-11-21','2026-11-22'];
function model(id){
  const members={c00:days.map((_,i)=>i<3?2:-2)};
  for(let i=1;i<=(id==='gefs'?30:50);i++) {
    const name='p'+String(i).padStart(2,'0');
    members[name]=days.map((_,step)=>i===1?(-2):(step===5&&i%5===0?-1:5));
  }
  return {schema_version:1,provider:id==='gefs'?'NOAA GEFS':'ECMWF IFS ENS',
    level_hpa:10,latitude_deg:60,units:'m/s',cycle_utc:start+'T00:00:00Z',
    valid_dates:days,members};
}
test('NASA parser accepts only original daily analysis and ignores missing/forecast',()=>{
  const raw='Name: NASA\nDate Data Minimum 10% 30% Mean 70% 90% Maximum Fcst\n'+
  '2026-11-01 22 10 15 17 20 24 28 34 0\n'+
  '2026-11-02 -9999 10 15 17 20 24 28 34 0\n'+
  '2026-11-03 30 10 15 17 20 24 28 34 24\n'+
  '2026-11-04 18 10 15 17 20 24 28 34 -1';
  const result=nasa.parse(raw);
  assert.deepEqual(Array.from(result,([date,value])=>[date,value]),[['2026-11-01',22]]);
  assert.equal(nasa.season('2027-01-11'),2026);
  assert.equal(nasa.season('2026-07-01'),2026);
  assert.equal(nasa.dateISO('2027-01-01',-1),'2026-12-31');
});
test('combined NASA/GEFS/EPS rows retain actual observations, climatology and missing values',()=>{
  const g=model('gefs'),e=model('eps');
  const ref={mean:25,p10:12,p90:37};
  const obs=new Map([['2026-11-06',28],['2026-11-07',30]]);
  const historyData=new Map([[10,{observations:obs,reference:Object.fromEntries(
    ['11-06','11-07','11-08','11-09','11-10','11-11','11-12','11-13','11-14',
     '11-15','11-16','11-17','11-18','11-19','11-20','11-21','11-22'].map(day=>[day,ref]))}]]);
  const raw={gefs:g,eps:e,hour:0};
  const absolute=history.compose(historyData,raw,'absolute');
  const one=absolute.rows.find(r=>r.date==='2026-11-06');
  assert.equal(one.analysis,28);
  assert.equal(one.average,25);
  assert.equal(one.p10,12);
  assert.equal(one.p90,37);
  assert.equal(one.gefs,null);
  const first=absolute.rows.find(r=>r.date==='2026-11-07');
  assert.equal(first.analysis,30);
  assert.ok(Number.isFinite(first.gefs));
  assert.ok(Number.isFinite(first.eps));
  assert.equal(absolute.transition,'2026-11-07');
  const anomalies=history.compose(historyData,raw,'anomaly');
  const av=anomalies.rows.find(r=>r.date==='2026-11-06');
  assert.equal(av.analysis,3);assert.equal(av.p10,-13);assert.equal(av.average,0);
  // Missing climatology must not manufacture an anomaly from an absolute wind.
  const missing=anomalies.rows.find(r=>r.date==='2026-11-05');
  assert.equal(missing.p10,null);assert.equal(missing.average,null);
});
test('new wind reversal within +7/+15 d is cumulative unique-member frequency',()=>{
  const g=joint.summarize(model('gefs'),0,'gefs');
  const e=joint.summarize(model('eps'),0,'eps');
  const g7=metric.probability(g,7),g15=metric.probability(g,15);
  const e7=metric.probability(e,7),e15=metric.probability(e,15);
  assert.equal(g7.total,31);assert.equal(e7.total,51);
  assert.ok(g15.first>=g7.first);assert.ok(e15.first>=e7.first);
  assert.equal(g7.first,g.crossed);
  assert.equal(e15.first,e.crossed);
  assert.equal(metric.probability({...g,rows:g.rows.slice(0,5)},7),null);
  assert.equal(metric.probability(g,16),null);
});
test('mean-model differences retain sign and only the common original dates',()=>{
  const g=joint.summarize(model('gefs'),0,'gefs');
  const e=joint.summarize(model('eps'),0,'eps');
  const aligned=joint.align(g,e);
  const rows=metric.difference(aligned);
  assert.equal(rows.length,16);
  assert.equal(rows[0].date,'2026-11-07');
  assert.ok(Math.abs(rows[0].value-(g.rows[0].mean-e.rows[0].mean))<1e-10);
  assert.equal(rows[0].gefs,g.rows[0].mean);
});
test('vertical pressure-level analysis remains separate from 10-hPa model forecast',()=>{
  assert.deepEqual([...nasa.LEVELS],[10,30,50,70,100]);
  assert.equal(vertical.anomaly(30,25,'anomaly'),5);
  assert.equal(vertical.anomaly(30,25,'absolute'),30);
  assert.equal(vertical.anomaly(30,null,'anomaly'),null);
  assert.equal(vertical.scaleFor('absolute'),60);
  assert.equal(vertical.scaleFor('anomaly'),30);
  assert.equal(vertical.color(null,'absolute'),'#e3e8ed');
  assert.ok(vertical.color(5,'anomaly').startsWith('rgb('));
});
