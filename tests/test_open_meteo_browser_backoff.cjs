const {test}=require("node:test");
const assert=require("node:assert/strict");
const vm=require("node:vm");
const fs=require("node:fs");
const text=fs.readFileSync("t850_ensembles.js","utf8").split("// OPEN_METEO_BACKOFF_BEGIN")[1].split("// OPEN_METEO_BACKOFF_END")[0];
function harness(mock){
  let time=100000, calls=[], waits=[];
  const box={AbortController,DOMException,Promise,Map,Date:class extends Date{static now(){return time;}},
    setTimeout(fn,ms){const timer=setImmediate(()=>{time+=ms;waits.push(ms);fn();});return timer;},
    clearTimeout:clearImmediate,fetch:async(url,opts)=>{calls.push(String(url));return mock(calls.length,opts);}};
  vm.createContext(box);
  vm.runInContext(text+"\nglobalThis.api={fetchOpenMeteo,retryAfterMs};",box);
  return {api:box.api,calls,waits};
}
function response(status,body={},after=null){
  return {ok:status>=200&&status<300,status,headers:{get:()=>after},json:async()=>body};
}
test("successful call consumes JSON and does not retry",async()=>{
  const h=harness(()=>response(200,{value:42}));
  assert.equal((await h.api.fetchOpenMeteo("test")).value,42);
  assert.equal(h.calls.length,1);
});
test("429 minute limit honors Retry-After and at least 65 seconds",async()=>{
  const h=harness(n=>n===1?response(429,{reason:"Minutely API request limit exceeded"},"80"):response(200,{ok:true}));
  assert.equal((await h.api.fetchOpenMeteo("test")).ok,true);
  assert.equal(h.calls.length,2);
  assert.ok(h.waits.includes(80000));
});
test("daily limit does not retry and stops other requests",async()=>{
  const h=harness(()=>response(429,{reason:"Daily API request limit exceeded"}));
  await assert.rejects(h.api.fetchOpenMeteo("a"),e=>e.status===429);
  await assert.rejects(h.api.fetchOpenMeteo("b"),e=>e.status===429);
  assert.equal(h.calls.length,1);
});
test("400 is permanent, 503 and network failure are retried at most three times",async()=>{
  const a=harness(()=>response(400));
  await assert.rejects(a.api.fetchOpenMeteo("bad"),e=>e.status===400);
  assert.equal(a.calls.length,1);
  const b=harness(n=>n===1?response(503):n===2?Promise.reject(new TypeError("network")):response(200,{ok:true}));
  assert.equal((await b.api.fetchOpenMeteo("retry")).ok,true);
  assert.equal(b.calls.length,3);
  const c=harness(()=>response(503));
  await assert.rejects(c.api.fetchOpenMeteo("down"),e=>e.status===503);
  assert.equal(c.calls.length,3);
});
test("abort during 429 wait prevents another fetch",async()=>{
  const controller=new AbortController();
  const h=harness(()=>{setImmediate(()=>controller.abort());return response(429);});
  await assert.rejects(h.api.fetchOpenMeteo("a",{signal:controller.signal}),e=>e.name==="AbortError");
  assert.equal(h.calls.length,1);
});
test("Retry-After HTTP-date is interpreted correctly",()=>{
  const h=harness(()=>response(200));
  assert.equal(h.api.retryAfterMs("Thu, 01 Jan 1970 00:02:00 GMT",100000),20000);
});
test("at most two network requests in flight",async()=>{
  let active=0,peak=0;
  const h=harness(async()=>{active++;peak=Math.max(peak,active);await new Promise(r=>setImmediate(r));active--;return response(200);});
  await Promise.all(["a","b","c","d"].map(u=>h.api.fetchOpenMeteo(u)));
  assert.ok(peak<=2);
  assert.equal(h.calls.length,4);
});
