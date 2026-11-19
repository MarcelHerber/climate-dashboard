const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const zlib=require('node:zlib');
const path=require('node:path');
const C=require(process.env.RR_FIXTURES?'../stations_regional_calendar.js':'./stations_regional_calendar.js');
const fixtures=process.env.RR_FIXTURES||path.join(__dirname,'fixtures');
const readPart=p=>({manifest:JSON.parse(fs.readFileSync(path.join(fixtures,p,'manifest.json'))),day:JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(fixtures,p,'11-14.json.gz'))))});
const {manifest,day}=readPart('2021-2026');
test('real archive: Bayern highest rainfall 14 November 2021 is 2.1 mm',()=>{
 const rows=C.rank([{manifest,day}],{area:'Bayern',metric:'rs_high',md:'11-14',first:2021,last:2021});
 assert.equal(rows.length,50);
 assert.equal(rows[0].value,2.1);
 assert.equal(rows[0].date,'2021-11-14');
 assert.equal(rows[0].station.state,'Bayern');
 assert.ok(rows.every(r=>r.station.state==='Bayern'));
});
test('ascending temperatures, years, station identity and scaled zero',()=>{
 const m={...manifest,stations:[{id:'00001',key:'kl:1',name:'A'},{id:'00002',key:'kl:2',name:'B'}]};
 const d=[[2000,{txk_low:{Deutschland:[[0,0,0],[-20,1,1]]}}],[2001,{txk_low:{Deutschland:[[-20,0,0]]}}],[2002,{txk_low:{Deutschland:[[-100,0,0]]}}]];
 const rows=C.rank([{manifest:m,day:d}],{area:'Deutschland',metric:'txk_low',md:'11-14',first:2000,last:2001});
 assert.deepEqual(rows.map(r=>[r.value,r.date,r.station.id,r.preliminary]),[[-2,'2000-11-14','00002',true],[-2,'2001-11-14','00001',false],[0,'2000-11-14','00001',false]]);
});
test('only fetch partitions overlapping the user selected year range',()=>{
 assert.deepEqual(C.partitions(1999,2001),['1991-2000','2001-2010']);
});
test('missing station metadata cannot produce a misleading partial result',()=>{
 assert.throws(()=>C.rank([{manifest,day:[[2021,{rs_high:{Deutschland:[[100,999999,0]]}}]]}],{area:'Deutschland',metric:'rs_high',md:'11-14',first:2021,last:2021}),/Station/);
});
test('all 10 real partitions: eight parameters, correct sorting and 50 candidates',()=>{
 const parts=C.partitions(1750,2026).map(readPart);
 const expected={tnk_high:14,txk_low:-16.8,tmk_high:16.6,tmk_low:-18.1,amplitude_high:22,rs_high:83.2,fx_high:212.8,sdk_high:9.5};
 for(const [metric,value] of Object.entries(expected)){
  const rows=C.rank(parts,{area:'Deutschland',metric,md:'11-14',first:1750,last:2026});
  assert.equal(rows.length,50);assert.equal(rows[0].value,value,metric);
  assert.ok(rows.every((r,i)=>i===0||(metric.endsWith('_low')?rows[i-1].value<=r.value:rows[i-1].value>=r.value)));
 }
});
test('historical rain location fallback is not presented as verified',()=>{
 const parts=C.partitions(1750,2026).map(readPart);
 const rows=C.rank(parts,{area:'Rheinland-Pfalz',metric:'rs_high',md:'11-14',first:1750,last:2026});
 const r=rows.find(r=>r.station.name==='Rhaunen'&&r.date==='1964-11-14');
 assert.ok(r);
 assert.equal(C.located(r),false);
});
test('29 February only ranks genuine leap-year dates',()=>{
 const m={...manifest,stations:[{id:'00001',key:'kl:1'}]};
 const day=[1900,2000,2001,2004].map(year=>[year,{txk_low:{Deutschland:[[0,0,0]]}}]);
 assert.deepEqual(C.rank([{manifest:m,day}],{area:'Deutschland',metric:'txk_low',md:'02-29',first:1900,last:2004}).map(r=>r.date),['2000-02-29','2004-02-29']);
});
