const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('sst_nino_years.js', 'utf8');
const window = {};
vm.runInNewContext(src.replace(/\}\)\(\);\s*$/, 'window.api = { REGIONS, parseDailyCsv };})();'), {
  window, document: {readyState:'loading',addEventListener(){}}, Date, Map
});
const {REGIONS, parseDailyCsv} = window.api;
for (const key of ['world','natl','npac','spna','europe','mediterranean','north_atlantic','nordic_seas','pacific','indian_ocean']) {
  assert.ok(REGIONS[key], `missing region ${key}`);
}
const rows = ['date,sst'];
for (let d = new Date(Date.UTC(1982,0,1)); d < new Date(Date.now()-3*86400000); d.setUTCDate(d.getUTCDate()+1)) {
  const iso = d.toISOString().slice(0,10);
  if (iso === '1995-01-01') rows.push(`${iso},`);
  else rows.push(`${iso},${iso === '1995-01-02' ? -0.5 : 8.25}`);
}
const data = parseDailyCsv(rows.join('\n'));
assert.equal(data.years['1995'][0], null, 'blank SST must not be zero');
assert.equal(data.years['1995'][1], -0.5, 'cold regional SST is valid');
assert.equal(data.years['1995'][2], 8.25);
assert.equal(data.years['1995'][59], null, 'non-leap year has no Feb 29');
assert.throws(() => parseDailyCsv(rows.join('\n'), true), /Archiv seit 1982/);
assert.ok(parseDailyCsv(rows.join('\n').replace('1995-01-01,\n','1995-01-01,8.25\n'), true).count >= 15000);
console.log('Regional choices, cold SST, missing values, leap day checked.');
