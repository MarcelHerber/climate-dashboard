const test=require('node:test'),assert=require('node:assert/strict');
const {parseCatalogue,episodes,transitions}=require('../grosswetterlagen.js');
const csv='Datum;Nr;GWL\n2000-01-01;1;WA\n2000-01-02;2;WZ\n2000-01-03;2;WZ\n2000-01-04;2;WZ\n2000-01-05;3;HM\n2000-01-07;1;WA';
test('catalogue parses daily dates, rejects duplicates and invalid dates',()=>{assert.equal(parseCatalogue(csv).length,6);assert.throws(()=>parseCatalogue(csv+'\n2000-01-01;3;HM'));assert.throws(()=>parseCatalogue(csv+'\n2000-02-30;1;WA'));});
test('only fully observed episodes are counted',()=>{const runs=episodes(parseCatalogue(csv));assert.equal(runs.length,1);assert.equal(runs[0].code,'WZ');assert.equal(runs[0].n,3);});
test('transitions do not span gaps or unchanged types',()=>{const rows=parseCatalogue(csv);assert.deepEqual([...transitions(rows,()=>true)],[['WA|WZ',1],['WZ|HM',1]]);assert.equal(transitions(rows,r=>r.code!=='HM').size,1);});
