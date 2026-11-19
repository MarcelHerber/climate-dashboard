const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require(require('node:fs').existsSync(__dirname+'/stations_regional_year.js')?'./stations_regional_year.js':'../stations_regional_year.js');
test('calendar includes leap day and all December dates',()=>{
 assert.equal(C.days.length,366);assert.equal(C.days[59],'02-29');assert.equal(C.days.at(-1),'12-31');
});
test('missing observations stay null; 0 and negative are preserved',()=>{
 const doc={rows:[[[-13,1999,'1','A',0],[0,2026,'2','B',1]],[null,null]]};
 assert.deepEqual(C.series(doc,0),[-1.3,null]);assert.deepEqual(C.series(doc,1),[0,null]);
});
test('CSV contains dates, both winners, names and provisional flag',()=>{
 const doc={area:'Hessen',metric:'txk_low',unit:'°C',current_year:2026,rows:[[[-13,1999,'00001','A; B',0],[0,2026,'00002','C',1]],[null,null]]};
 const csv=C.csvText(doc);
 assert.match(csv,/1999/);assert.match(csv,/00001/);assert.match(csv,/"A; B"/);assert.match(csv,/vorläufig/);assert.match(csv,/"02-01"|01-02/);
});
