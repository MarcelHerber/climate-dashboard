const test = require('node:test');
const assert = require('node:assert/strict');
const {buildIndex, valueFor, referenceMean, anomaly, colorFor, rankFor, csvFor, canCompare}=require('../gebietsmittel_archiv.js');
const data=require('../data.json');
const index=buildIndex(data);
const de=index.get('Deutschland');
const near=(a,b)=>assert.ok(Math.abs(a-b)<0.00001,`${a} != ${b}`);

test('real DWD June 2025 uses 1991–2020 and percent of normal',()=>{
  assert.equal(valueFor(de,2025,'06','temp'),18.38);
  near(referenceMean(de,'06','temp',1991),16.354);
  near(anomaly(18.38,16.354,'temp'),2.026);
  near(referenceMean(de,'06','rain',1991),75.53);
  near(anomaly(58.8,75.53,'rain'),77.84986098);
  near(referenceMean(de,'06','sun',1991),216.05);
  near(anomaly(273.3,216.05,'sun'),126.49849572);
});
test('missing sunshine and future months are not zero or complete years',()=>{
  assert.equal(valueFor(de,1881,'01','sun'),null);
  assert.equal(referenceMean(de,'01','sun',1881),null);
  const partial=new Map([['2026-01',{temp:2,rain:30,sun:20}]]);
  assert.equal(valueFor(partial,2026,'12','temp'),null);
  assert.equal(valueFor(partial,2026,'year','rain'),null);
  assert.equal(anomaly(5,0,'rain'),null);
  assert.equal(anomaly(0,10,'rain'),0);
});
test('winter includes previous December and weights leap calendar days',()=>{
  const fixture=new Map([['2019-12',{temp:2,rain:10}],['2020-01',{temp:3,rain:20}],['2020-02',{temp:4,rain:30}]]);
  near(valueFor(fixture,2020,'winter','temp'),(62+93+116)/91);
  assert.equal(valueFor(fixture,2020,'winter','rain'),60);
  assert.equal(valueFor(fixture,2020,'spring','rain'),null);
});
test('approved fixed color bins and clipping',()=>{
  assert.equal(colorFor(-4,'temp'),'#17458f');
  assert.equal(colorFor(0,'temp'),'#f5f5f5');
  assert.equal(colorFor(3,'temp'),'#e00000');
  assert.equal(colorFor(10,'temp'),'#990000');
  assert.equal(colorFor(0,'rain'),'#493021');
  assert.equal(colorFor(100,'rain'),'#f5f5f5');
  assert.equal(colorFor(200,'rain'),'#126030');
  assert.equal(colorFor(50,'sun'),'#303030');
  assert.equal(colorFor(100,'sun'),'#f5f5f5');
  assert.equal(colorFor(150,'sun'),'#b91c1c');
  assert.equal(colorFor(null,'sun'),null);
});
test('rank uses only available data and tied values share rank',()=>{
  const fixture=new Map([['2000-01',{temp:2}],['2001-01',{temp:3}],['2002-01',{temp:3}],['2003-01',{temp:null}]]);
  assert.deepEqual(rankFor(fixture,[2000,2001,2002,2003],2001,'01','temp'),{rank:1,count:3});
  assert.deepEqual(rankFor(fixture,[2000,2001,2002,2003],2000,'01','temp'),{rank:3,count:3});
  assert.equal(rankFor(fixture,[2000,2001,2002,2003],2003,'01','temp'),null);
});
test('map comparison cannot silently substitute an unavailable year',()=>{
  assert.equal(canCompare(de,2025,1881,'06','sun'),false);
  assert.equal(canCompare(de,2025,2024,'06','sun'),true);
  assert.equal(canCompare(new Map([['2026-01',{rain:30}]]),2026,2025,'year','rain'),false);
});
test('CSV preserves metadata, absolute values, normals and missing values',()=>{
  const csv=csvFor(de,[2025,2026],'Deutschland','temp',1991);
  assert.match(csv,/Deutschland;1991–2020;Temperatur;2025;Juni;18,38;16,354;2,026/);
  assert.match(csvFor(de,[1881],'Deutschland','sun',1991),/Deutschland;1991–2020;Sonnenschein;1881;Dezember;;/);
});
