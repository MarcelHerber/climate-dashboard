const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('climate index reads its data only when the control is in the active tab', () => {
  const source = fs.readFileSync(path.join(__dirname, '../js/gebietsmittel.js'), 'utf8');
  const start = source.indexOf('function updateClimateIndex(){');
  const end = source.indexOf('\nfunction ', start + 1);
  assert.ok(start >= 0 && end > start);
  for (const active of [true, false]) {
    let read = false;
    const context = {
      document: {getElementById(id) {
        if (id === 'indexPeriodSelect') return {closest: () => ({classList: {contains: () => active}})};
        return {classList: {contains: () => false}};
      }},
      get monthlyData() {read = true; return [];},
    };
    vm.runInNewContext(source.slice(start, end) + '\nupdateClimateIndex();', context);
    assert.equal(read, active);
  }
});
