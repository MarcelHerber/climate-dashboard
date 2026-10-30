import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {gzipSync} from "node:zlib";
const source=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
new Function(source);
const from=source.indexOf("  async function fetchMosmixSource(");
const until=source.indexOf("  async function loadStates()",from);
assert.ok(from>0 && until>from);
const funcs=source.slice(from,until);

const sample={product:"DWD MOSMIX-L",timesteps:["2026-10-27T00:00:00Z"],
  stations:[{name:"FRANKFURT/M",values:[12],sun1:[30]}]};
const compressed=gzipSync(Buffer.from(JSON.stringify(sample)));
const dataMock=(fetchImpl)=>{
  const status={textContent:""};
  const maker=new Function("fetch","document","DecompressionStream","Response",`
    const MANIFEST_URL="./data/mosmix/manifest.json";
    const MANIFEST_BACKUP_URL="https://raw.example/manifest.json";
    const MAP_BASE="./data/mosmix/";
    const MAP_BACKUP_BASE="https://raw.example/";
    const DATA_COMPRESSED_URL="./data/mosmix/mosmix_ttt.json.gz";
    const DATA_LOCAL_URL="./data/mosmix/mosmix_ttt.json";
    const DATA_URL="https://raw.example/mosmix_ttt.json";
    const DATA_BACKUP_URL="https://cdn.example/mosmix_ttt.json";
    const DATA_TIMEOUT_MS=15000;
    ${funcs}
    return loadData;
  `);
  return {load:maker(fetchImpl,{getElementById:()=>status},DecompressionStream,Response),
    status};
};
{
  const calls=[];
  const manifest={schema:2,issue_time:"2026-10-28T09:00:00Z",
    timesteps:["2026-10-28T12:00:00Z"],
    stations:Array.from({length:150},(_,i)=>({id:String(i),name:"S"+i})),
    modes:{hourly:[{path:"maps/hourly/2026-10-28.json",slot:0,valid:"2026-10-28T12:00:00Z"}]}};
  const {load}=dataMock(async(url)=>{
    calls.push(url);
    if(url=== "./data/mosmix/manifest.json")return {ok:true,json:async()=>manifest};
    throw new Error("Large JSON should never be requested with a valid manifest");
  });
  const result=await load(false);
  assert.equal(result._split,true);
  assert.equal(result.stations.length,150);
  assert.equal(result._mapsBase,"./data/mosmix/");
  assert.equal(calls.length,1);
}
{
  const calls=[];
  const {load}=dataMock(async(url)=>{
    calls.push(url);
    if(url.endsWith(".gz")){
      return {ok:true,body:new ReadableStream({
        start(controller){controller.enqueue(new Uint8Array(compressed));controller.close();}
      })};
    }
    throw new Error("Unexpected fetch after compressed Pages snapshot");
  });
  const result=await load(false);
  assert.equal(result._mosmixSource,"Website (komprimiert)");
  assert.equal(result.stations[0].name,"FRANKFURT/M");
  assert.equal(calls.filter(url=>!url.endsWith("manifest.json")).length,1);
}
{
  const calls=[];
  const {load}=dataMock(async(url)=>{
    calls.push(url);
    if(url.endsWith(".gz"))return {ok:false,status:404};
    if(url.startsWith("./data/"))return {ok:true,json:async()=>structuredClone(sample)};
    throw new Error("Unexpected remote download");
  });
  const result=await load(false);
  assert.equal(result._mosmixSource,"Website");
  assert.equal(calls.filter(url=>!url.endsWith("manifest.json")).length,2);
}
{
  const calls=[];
  const {load}=dataMock(async(url)=>{
    calls.push(url);
    if(!url.startsWith("https://cdn."))return {ok:false,status:404};
    return {ok:true,json:async()=>structuredClone(sample)};
  });
  const result=await load(false);
  assert.equal(result._mosmixSource,"Ersatzquelle");
  assert.equal(result._mosmixFallback,true);
  assert.equal(calls.filter(url=>!url.endsWith("manifest.json")).length,4);
}
{
  const {load,status}=dataMock(async()=>{throw new Error("Offline")});
  await assert.rejects(load(false),/Keine MOSMIX-Quelle erreichbar/);
  assert.match(status.textContent,/Lade Deutschland-MOSMIX-Daten/);
}
assert.ok(source.includes("if (!window.L) await ensureLeaflet();"),
  "Leaflet fallback missing");
assert.ok(!source.includes("if (!window.L) return;"),
  "Silent Leaflet abort would leave the page permanently loading");
console.log("PASS: MOSMIX gzip+Pages-first, uncompressed/remote fallbacks and no silent Leaflet stall.");
