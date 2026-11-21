const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../js/loader.js'), 'utf8');

function harness() {
  const scripts = [], restored = [], tabs = new Map();
  function node() {
    return { children: [], style: {}, append(child) { this.children.push(child); },
      setAttribute() {}, addEventListener(name, fn) { this[name] = fn; }, remove() { this.removed = true; } };
  }
  function makeTab(id) {
    const tab = { id, active: false, notices: [], classList: { contains: () => tab.active },
      querySelectorAll() { return tab.notices.filter(n => !n.removed); }, prepend(n) { tab.notices.push(n); } };
    tabs.set(id, tab); return tab;
  }
  const ctx = { document: { createElement: () => node(), createTextNode: String,
    getElementById: id => tabs.get(id), head: { appendChild(n) { scripts.push(n); } } },
    navigator: {}, restoreDashboardControls: tab => restored.push(tab.id), console };
  ctx.window = ctx; vm.runInNewContext(source, ctx);
  return { modules: ctx.DashboardModules, scripts, restored, makeTab };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('slow repeated visits restore and activate once, only for the latest visit', async () => {
  const { modules, scripts, restored, makeTab } = harness();
  const tab = makeTab('current'); tab.active = true;
  let calls = 0;
  modules.whenTabReady('current', () => calls++);
  tab.active = false; tab.active = true;
  modules.whenTabReady('current', () => calls++);
  assert.equal(scripts.length, 1);
  scripts[0].onload(); await tick();
  assert.equal(calls, 1); assert.deepEqual(restored, ['current']);
});

test('background load does not restore hidden controls, but first later visit does', async () => {
  const { modules, scripts, restored, makeTab } = harness();
  const tab = makeTab('europeStations'); tab.active = true;
  let calls = 0;
  modules.whenTabReady('europeStations', () => calls++);
  tab.active = false;
  scripts[0].onload(); await tick();
  assert.equal(calls, 0); assert.deepEqual(restored, []);
  tab.active = true;
  modules.whenTabReady('europeStations', () => calls++); await tick();
  assert.equal(calls, 1); assert.deepEqual(restored, ['europeStations']);
});

test('failed script is removed and retry loads it exactly once', async () => {
  const { modules, scripts, makeTab } = harness();
  const tab = makeTab('stationSnow'); tab.active = true;
  let calls = 0;
  modules.whenTabReady('stationSnow', () => calls++);
  scripts[0].onerror(); await tick();
  assert.equal(modules.tabReady('stationSnow'), false);
  const notice = tab.notices.find(n => !n.removed);
  assert.equal(notice.children[1].textContent, 'Erneut versuchen');
  notice.children[1].click();
  assert.equal(scripts.length, 2); assert.ok(scripts[0].removed);
  scripts[1].onload(); await tick();
  assert.equal(calls, 1); assert.equal(modules.tabReady('stationSnow'), true);
});
