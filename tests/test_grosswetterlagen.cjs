const test=require('node:test'),assert=require('node:assert/strict');
const {parseCatalogue,episodes,transitions}=require('../grosswetterlagen.js');
const csv='Datum;Nr;GWL\n2000-01-01;1;WA\n2000-01-02;2;WZ\n2000-01-03;2;WZ\n2000-01-04;2;WZ\n2000-01-05;3;HM\n2000-01-07;1;WA';
test('catalogue parses daily dates, rejects duplicates and invalid dates',()=>{assert.equal(parseCatalogue(csv).length,6);assert.throws(()=>parseCatalogue(csv+'\n2000-01-01;3;HM'));assert.throws(()=>parseCatalogue(csv+'\n2000-02-30;1;WA'));});
test('only fully observed episodes are counted',()=>{const runs=episodes(parseCatalogue(csv));assert.equal(runs.length,1);assert.equal(runs[0].code,'WZ');assert.equal(runs[0].n,3);});
test('transitions do not span gaps or unchanged types',()=>{const rows=parseCatalogue(csv);assert.deepEqual([...transitions(rows,()=>true)],[['WA|WZ',1],['WZ|HM',1]]);assert.equal(transitions(rows,r=>r.code!=='HM').size,1);});

test('frequency distribution uses all classified days and sorts by count',()=>{const {frequencyDistribution}=require('../grosswetterlagen.js');const r=frequencyDistribution(new Map([['WA',2],['WZ',3],['HM',1],['U',0]]));assert.deepEqual(r.map(x=>x.code),['WZ','WA','HM','U']);assert.equal(r[0].percent,50);assert.equal(r.reduce((s,x)=>s+x.days,0),6);assert.equal(frequencyDistribution(new Map([['WA',0]]))[0].percent,0);});
