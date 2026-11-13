/* In-memory, bounded LRU for genuine, successfully decoded EUMETSAT tiles.
 * Exact GetMap URL is the cache key: UTC, WMS layer, EPSG:4326 BBOX, pixel
 * width/height and source are all included. Nothing stored in localStorage.
 * Avoid network and double rendering after a zoom, quality or time revisit.
 */
(() => {
"use strict";
function create({maxBytes=96*1024*1024,ttlMs=45*60*1000,now=()=>Date.now()}={}){
 const entries=new Map();
 let bytes=0,hits=0,misses=0,evictions=0;
 const capacity=Math.max(0,Math.floor(maxBytes));
 const expiresAfter=Math.max(0,Math.floor(ttlMs));
 function discard(key,reason){
  const item=entries.get(key);
  if(!item)return;
  entries.delete(key);bytes-=item.bytes;
  if(reason==="eviction")evictions++;
 }
 function get(key){
  const item=entries.get(key);
  if(!item){misses++;return null;}
  if(now()-item.savedAt>expiresAfter||item.img.naturalWidth!==item.width||
    item.img.naturalHeight!==item.height){
   discard(key,"expiry");misses++;return null;
  }
  // Native Map insertion order is LRU; refreshing on use protects recently
  // visited zoom regions from eviction by later film frames or other areas.
  entries.delete(key);entries.set(key,item);hits++;
  return item.img;
 }
 function put(key,img,{width,height}={}){
  if(typeof key!=="string"||!key.startsWith("https://view.eumetsat.int/geoserver/wms?")||
   !img||!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||
   img.naturalWidth!==width||img.naturalHeight!==height)return false;
  const cost=width*height*4; // approximate decoded RGBA, not PNG transfer bytes
  if(!Number.isSafeInteger(cost)||cost>capacity)return false;
  if(entries.has(key))discard(key);
  while(entries.size&&bytes+cost>capacity){
   discard(entries.keys().next().value,"eviction");
  }
  entries.set(key,{img,width,height,bytes:cost,savedAt:now()});bytes+=cost;
  return true;
 }
 function clear(){
  entries.clear();bytes=0;hits=0;misses=0;evictions=0;
 }
 function stats(){return {entries:entries.size,bytes,maxBytes:capacity,hits,misses,evictions,ttlMs:expiresAfter};}
 return {get,put,clear,stats};
}
window.SatelliteTileCache={create};
})();
