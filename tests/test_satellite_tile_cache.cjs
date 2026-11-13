"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const source=fs.readFileSync("satellite_tile_cache.js","utf8");
const url=(time,layer="mtg_fd:rgb_geocolour",bbox="-27,24,49,73",w=64)=>
 "https://view.eumetsat.int/geoserver/wms?service=WMS&request=GetMap&"+
 new URLSearchParams({time,layers:layer,bbox,width:String(w),height:"64",srs:"EPSG:4326"});
const T="2026-11-13T09:10:00Z";
function make({maxBytes=65536,ttlMs=5000}={}){
 const window={};
 vm.runInNewContext(source,{window,Map,Date,Math,Number,String,Error});
 let now=1000;
 const cache=window.SatelliteTileCache.create({maxBytes,ttlMs,now:()=>now});
 return {cache,tick:ms=>now+=ms};
}
const img=(w=64,h=64)=>({naturalWidth:w,naturalHeight:h});
test("Only validated, correctly dimensioned EUMETSAT WMS PNG results are cacheable",()=>{
 const {cache}=make();
 assert.equal(cache.put(url(T),img(),{width:64,height:64}),true);
 assert.equal(cache.get(url(T)).naturalWidth,64);
 assert.equal(cache.put(url(T),img(63),{width:64,height:64}),false);
 assert.equal(cache.put("https://other-service.example/geoserver/wms?"+url(T).split("?")[1],
   img(),{width:64,height:64}),false);
 assert.equal(cache.put(url(T),img(),{width:63,height:64}),false);
 assert.equal(cache.put(url(T),{naturalWidth:0,naturalHeight:0},{width:64,height:64}),false);
 assert.equal(cache.stats().entries,1,"failed cache put never changes the valid prior entry");
});
test("Cache keys keep UTC, layer, bbox and requested WMS pixel resolution isolated",()=>{
 const {cache}=make();
 const at=url(T),later=url("2026-11-13T09:20:00Z"),ir=url(T,"mtg_fd:ir105_hrfi"),
  other=url(T,undefined,"-70,15,35,75"),larger=url(T,undefined,undefined,128);
 assert.ok(cache.put(at,img(),{width:64,height:64}));
 for(const key of [later,ir,other,larger])
  assert.equal(cache.get(key),null,"must not serve another time/product/area/resolution");
 assert.equal(cache.get(at).naturalWidth,64);
});
test("LRU evicts least recently used decoded image under a strict byte budget",()=>{
 const {cache}=make({maxBytes:2*64*64*4,ttlMs:5000});
 const a=url(T),b=url("2026-11-13T09:20:00Z"),c=url("2026-11-13T09:30:00Z");
 for(const key of [a,b])assert.equal(cache.put(key,img(),{width:64,height:64}),true);
 assert.strictEqual(cache.get(a).naturalWidth,64,"A is most recently accessed");
 cache.put(c,img(),{width:64,height:64});
 assert.equal(cache.get(b),null,"B was evicted, not the recently reused A");
 assert.equal(cache.get(a).naturalWidth,64);
 assert.equal(cache.get(c).naturalWidth,64);
 assert.equal(cache.stats().entries,2);
 assert.equal(cache.stats().bytes,2*64*64*4);
 assert.equal(cache.stats().evictions,1);
});
test("Oversized tiles and expired records are not kept or presented as current",()=>{
 const c=make({maxBytes:500,ttlMs:200});
 assert.equal(c.cache.put(url(T),img(),{width:64,height:64}),false);
 assert.equal(c.cache.stats().bytes,0);
 const d=make({maxBytes:20000,ttlMs:200});
 d.cache.put(url(T),img(),{width:64,height:64});
 d.tick(201);
 assert.equal(d.cache.get(url(T)),null);
 assert.equal(d.cache.stats().entries,0);
 assert.equal(d.cache.stats().bytes,0);
});
test("User clear releases entries and resets counters without affecting source images",()=>{
 const {cache}=make();
 const image=img();
 cache.put(url(T),image,{width:64,height:64});
 assert.strictEqual(cache.get(url(T)),image);
 cache.clear();
 assert.equal(cache.stats().entries,0);
 assert.equal(cache.stats().bytes,0);
 assert.equal(cache.stats().hits,0);
 assert.equal(image.naturalWidth,64,"active DOM image is not cleared or overwritten");
});
test("Production page loads cache before HD, deploys both and shows clear button",()=>{
 const html=fs.readFileSync("satelliten.html","utf8");
 const build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
 assert.ok(html.indexOf('src="satellite_tile_cache.js?')<html.indexOf('src="satellite_hd.js?'));
 assert.ok(html.includes('id="satClearTileCache"'));
 assert.ok(build.includes("  satellite_tile_cache.js\n"));
 assert.ok(build.includes("node --check _site/satellite_tile_cache.js"));
});
