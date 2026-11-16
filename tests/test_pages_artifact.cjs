const test = require('node:test');
const assert = require('node:assert/strict');
const {waitForArtifact} = require('../scripts/wait_pages_artifact.cjs');

const expected = {id: 123, name: 'github-pages-2', size_in_bytes: 732290032, expired: false};
const options = {id: 123, name: expected.name, attempts: 5, pause: async () => {}, log: () => {}};

test('waits for two consecutive observations of the exact artifact', async () => {
  const results = [[], [expected], [], [expected], [expected]];
  let calls = 0;
  const found = await waitForArtifact({...options, list: async () => results[calls++]});
  assert.deepEqual(found, expected);
  assert.equal(calls, 5);
});

test('does not accept a different ID, name, an expired or an empty artifact', async () => {
  const artifacts = [{...expected, id: 124}, {...expected, name: 'github-pages-1'}, {...expected, expired: true}, {...expected, size_in_bytes: 0}];
  let calls = 0;
  await assert.rejects(waitForArtifact({...options, list: async () => [artifacts[calls++ % artifacts.length]]}), /not visible/);
  assert.equal(calls, 5);
});

test('retries transient API failures but requires two successful observations', async () => {
  let calls = 0;
  const result = await waitForArtifact({...options, list: async () => {
    if (++calls === 1) throw Object.assign(new Error('unavailable'), {status: 503});
    return [expected];
  }});
  assert.equal(result.id, 123);
  assert.equal(calls, 3);
});

test('does not hide permanent authorization failures', async () => {
  let calls = 0;
  await assert.rejects(waitForArtifact({...options, list: async () => {
    calls++; throw Object.assign(new Error('forbidden'), {status: 403});
  }}), /forbidden/);
  assert.equal(calls, 1);
});

test('rejects duplicate artifacts with the same name instead of deploying ambiguously', async () => {
  await assert.rejects(waitForArtifact({...options, list: async () => [expected, {...expected, id: 124}]}), /ambiguous/);
});
