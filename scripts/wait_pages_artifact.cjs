'use strict';

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitForArtifact({id, name, list, attempts = 12, interval = 5000, pause: sleep = pause, log = console.log}) {
  if (!Number.isSafeInteger(id) || id <= 0 || !name || attempts < 2) throw new Error('Invalid Pages artifact identity or polling limit');
  let confirmed = 0;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    let artifacts;
    try {
      artifacts = await list();
      if (!Array.isArray(artifacts)) throw new Error('Invalid artifact list');
    } catch (error) {
      if (error.status >= 400 && error.status < 500 && ![404, 429].includes(error.status)) throw error;
      log(`Artifact lookup ${attempt}/${attempts}: ${error.message}`);
      artifacts = [];
    }
    const named = artifacts.filter(artifact => artifact.name === name);
    if (named.length > 1) throw new Error(`Pages artifact ${name} is ambiguous`);
    const artifact = named.find(item => item.id === id && item.expired === false && item.size_in_bytes > 0);
    confirmed = artifact ? confirmed + 1 : 0;
    if (confirmed === 2) {
      log(`Confirmed Pages artifact ${name} (${id}, ${artifact.size_in_bytes} bytes) twice.`);
      return artifact;
    }
    log(`Pages artifact ${name}: observation ${attempt}/${attempts}, confirmations ${confirmed}/2.`);
    if (attempt < attempts) await sleep(interval);
  }
  throw new Error(`Pages artifact ${name} (${id}) not visible consistently after ${attempts} attempts`);
}

async function main(env = process.env) {
  const id = Number(env.PAGES_ARTIFACT_ID);
  const name = env.PAGES_ARTIFACT_NAME;
  if (!env.GH_TOKEN || !env.GITHUB_API_URL || !env.GITHUB_REPOSITORY || !env.GITHUB_RUN_ID) throw new Error('Missing GitHub Actions API configuration');
  const url = new URL(`${env.GITHUB_API_URL}/repos/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}/artifacts`);
  url.searchParams.set('name', name);
  const list = async () => {
    const response = await fetch(url, {headers: {Authorization: `Bearer ${env.GH_TOKEN}`, Accept: 'application/vnd.github+json'}, signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw Object.assign(new Error(`GitHub artifact API HTTP ${response.status}`), {status: response.status});
    return (await response.json()).artifacts;
  };
  await waitForArtifact({id, name, list});
}

if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = {waitForArtifact};
