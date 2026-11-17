const test = require('node:test');
const assert = require('node:assert/strict');
const axis = require('../stations_temperaturgegensatz.js');
const fs = require('node:fs');
const vm = require('node:vm');

test('automatic axis fits yearly contrasts and ignores archive gaps', () => {
  assert.deepEqual(axis.bounds([33, null, 44.7, 35], 'auto'), {min:32,max:46,step:2});
  assert.deepEqual(axis.bounds([35], 'auto'), {min:34,max:36,step:0.5});
});
test('zero mode retains zero and a rounded upper bound', () => {
  assert.deepEqual(axis.bounds([33,44.7], 'zero'), {min:0,max:50,step:10});
});
test('manual axis accepts decimal steps and rejects invalid or excessive ticks', () => {
  assert.deepEqual(axis.bounds([33,44.7],'manual',{min:30,max:45,step:2.5}), {min:30,max:45,step:2.5});
  for(const input of [{min:40,max:30,step:2},{min:0,max:45,step:0},{min:0,max:45,step:0.1},{min:'',max:45,step:5},{min:0,max:10,step:2}])
    assert.throws(()=>axis.bounds([33,44.7],'manual',input));
});
test('export uses actual chart ticks, including decimal values and clipping', () => {
  const window={}; vm.runInNewContext(fs.readFileSync('t850_vector_export.js','utf8'),{window});
  const chart={data:{labels:[1951,1952,1953],datasets:[{label:'Jahresmaximum',data:[29,36,46],pointRadius:2}]},scales:{x:{min:0,max:2},y:{min:30,max:45,ticks:[30,32.5,35,37.5,40,42.5,45].map(value=>({value}))}}};
  const scene=window.T850VectorExport.buildScene(chart,axis.exportTicks(chart));
  assert.deepEqual(Array.from(scene.ticks,t=>t.label),['30','32,5','35','37,5','40','42,5','45']);
  for(const segment of scene.series[0].points)for(const [,y] of segment)assert.ok(y>=259-1e-8&&y<=802+1e-8);
  assert.equal(scene.series[0].markers.length,1);
});
