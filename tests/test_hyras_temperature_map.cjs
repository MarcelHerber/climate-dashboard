const test = require('node:test');
const assert = require('node:assert/strict');
const { mapForReference, cellAt, decodePlane, exactRaster } = require('../hyras_temperature_interactive.js');
const vm = require('node:vm');
const html = require('./dashboard_source.cjs')();
function source(name){
  const start=html.indexOf(`function ${name}(`);
  assert.ok(start>=0, name);
  return html.slice(start,html.indexOf('\n}',start)+2);
}
function periodContext(parameter, key){
  const periods=[{key:'year_current',start_date:'2026-01-01',end_date:'2026-11-14',label:'Jahr aktuell 2026'}, {key:'month_10',start_date:'2026-10-01',end_date:'2026-10-31',label:'Oktober 2026'}, {key:'month_11',map_key:'2026_11_live',start_date:'2026-11-01',end_date:'2026-11-14',label:'November aktuell 2026'}];
  const sel={value:key,innerHTML:'temperature options',appendChild(){}};
  const precip={periods:[{key:'2026_11_live',period_type:'month_live',start_date:'2026-11-01',end_date:'2026-11-15',label:'November aktuell 2026'}]};
  const ctx=vm.createContext({hyrasParameter:()=>parameter,hyrasIndex:precip,document:{getElementById:()=>sel,createElement:()=>({appendChild(){}})},...Object.fromEntries(['Tmean','Tmax','Tmin'].map(cap=>[`hyras${cap}RegionsIndex`,{periods}]))});
  const names=['populateHyrasPeriods',...['Tmean','Tmax','Tmin'].flatMap(cap=>[`hyras${cap}PopulateCurvePeriods`,`hyras${cap}CurvePeriod`])];
  if(html.includes('function hyrasTemperatureResolvePeriod('))names.push('hyrasTemperatureResolvePeriod');
  vm.runInContext(names.map(source).join('\n'),ctx);
  return {sel,ctx};
}
for(const parameter of ['tmean','tmax','tmin']){
  const cap=parameter[0].toUpperCase()+parameter.slice(1);
  test(`${parameter}: late precipitation refresh cannot overwrite selected October`,()=>{
    const {sel,ctx}=periodContext(parameter,'month_10');
    ctx.populateHyrasPeriods();
    assert.equal(sel.value,'month_10');
    assert.equal(ctx[`hyras${cap}CurvePeriod`]().key,'month_10');
  });
  test(`${parameter}: stale November precipitation selection resolves to November temperature`,()=>{
    const {sel,ctx}=periodContext(parameter,'2026_11_live');
    assert.equal(ctx[`hyras${cap}CurvePeriod`]().key,'month_11');
    assert.equal(sel.value,'month_11');
  });
}
test('precipitation still populates its active month',()=>{
  const {sel,ctx}=periodContext('precipitation','month_10');
  ctx.populateHyrasPeriods();
  assert.equal(sel.value,'2026_11_live');
});

test('does not substitute the modern reference for the old reference', () => {
  assert.equal(mapForReference({anomaly: 'modern.png'}, '1961-1990'), null);
  assert.equal(mapForReference({anomaly: 'modern.png'}, '1991-2020'), 'modern.png');
  assert.equal(mapForReference({anomaly_by_reference: {'1961-1990': 'old.png'}}, '1961-1990'), 'old.png');
  assert.equal(mapForReference({anomaly:'stale.png',start_date:'2026-11-01',end_date:'2026-11-13'}, '1991-2020','2026-11-01','2026-11-14'),null);
});
test('decodes signed native cells, rejects wrong size and masks nodata', () => {
  const buf = new ArrayBuffer(8), view = new DataView(buf);
  [125,-250,-32768,0].forEach((v,i)=>view.setInt16(i*2,v,true));
  const plane = decodePlane(buf,2,2);
  assert.equal(cellAt(plane,0.25,0.25),1.25);
  assert.equal(cellAt(plane,0.75,0.25),-2.5);
  assert.equal(cellAt(plane,0.25,0.75),null);
  assert.equal(cellAt(plane,1,0.5),null);
  assert.throws(()=>decodePlane(buf,3,2));
});
test('rejects native maps whose date bounds do not match',()=>{
  const entry={raster_dates_by_reference:{'1991-2020':['2026-11-01','2026-11-14']},raster_by_reference:{'1991-2020':'native.gz'},raster_grid:{width:2,height:2}};
  assert.equal(exactRaster(entry,'1991-2020','2026-11-01','2026-11-15'),null);
  assert.equal(exactRaster(entry,'1961-1990','2026-11-01','2026-11-14'),null);
  assert.equal(exactRaster(entry,'1991-2020','2026-11-01','2026-11-14').path,'native.gz');
});
