const test = require('node:test');
const assert = require('node:assert/strict');
const { mapForReference, cellAt, decodePlane, exactRaster } = require('../hyras_temperature_interactive.js');

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
