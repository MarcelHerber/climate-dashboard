const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const SOURCE=fs.readFileSync("europe_station_basemap.js","utf8");
const HTML=fs.readFileSync("index.html","utf8");
const NATURAL_EARTH=JSON.parse(fs.readFileSync("wettergefahren_basemap.json","utf8"));

function harness({offline=false}={}){
 const tiles=[],polygons=[],removed=[],timers=[];
 const stateEl={hidden:true,textContent:""};
 const map={
  panes:new Map(),
  createPane(name){const pane={style:{}};this.panes.set(name,pane);return pane;},
  getPane(name){return this.panes.get(name);},
  removeLayer(layer){removed.push(layer)},
  on(event,callback){this.events??={};this.events[event]=callback},
 };
 const L={
  map(){return map;},
  svg(options){return {kind:"svg",options};},
  geoJSON(geo,options){
   polygons.push({geo,options});
   return {addTo(target){assert.equal(target,map);return this}};
  },
  tileLayer(url,options){
   const layer={
    url,options,handlers:{},
    on(name,callback){this.handlers[name]=callback;return this},
    addTo(target){assert.equal(target,map);tiles.push(this);return this},
    trigger(name){this.handlers[name]?.();}
   };
   return layer;
  }
 };
 const document={
  getElementById(id){return id==="europeStationBasemapStatus"?stateEl:null},
  createElement(tag){return {tag,style:{},setAttribute(){}}},
  head:{appendChild(){}}
 };
 const window={L};
 const fetch=()=>offline?Promise.reject(new Error("offline")):
   Promise.resolve({ok:true,json:async()=>NATURAL_EARTH});
 let timerId=0;
 const setTimeout=fn=>{timers.push(fn);return ++timerId};
 const setInterval=()=>++timerId;
 const context={window,document,fetch,setTimeout,setInterval,clearInterval(){},
   clearTimeout(){},Promise,Date,console:{warn(){},info(){}}};
 vm.runInNewContext(SOURCE,context,{timeout:2000});
 return {window,map,tiles,polygons,removed,timers,stateEl};
}

test("ship actual public-domain Natural Earth Europe geography with the site",()=>{
 assert.ok(NATURAL_EARTH.source.includes("Natural Earth"));
 assert.ok(NATURAL_EARTH.countries.length>=60);
 assert.ok(Array.isArray(NATURAL_EARTH.countries[0].p));
 assert.ok(NATURAL_EARTH.countries[0].p[0][0][0].length===2);
});

test("fallback geography is rendered on separate pane underneath tiles and station overlays",async()=>{
 const h=harness();
 h.window.attachEuropeStationBasemap(h.map);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.polygons.length,1);
 const rendered=h.polygons[0];
 assert.equal(rendered.geo.type,"FeatureCollection");
 assert.equal(rendered.geo.features.length,NATURAL_EARTH.countries.length);
 assert.equal(rendered.geo.features[0].geometry.type,"MultiPolygon");
 assert.equal(rendered.options.interactive,false);
 assert.equal(rendered.options.pane,"europeStationGeographyPane");
 assert.equal(rendered.options.renderer.kind,"svg");
 assert.equal(rendered.options.renderer.options.pane,"europeStationGeographyPane");
 assert.equal(h.map.getPane("europeStationGeographyPane").style.zIndex,"195");
 assert.equal(h.tiles.length,1);
 assert.match(h.tiles[0].url,/cartocdn/);
 const geo=h.map.__europeStationGetBasemapState();
 assert.equal(geo.geographyLoaded,true);
});

test("switch from failing CARTO tiles to alternate OpenStreetMap without removing local geography",async()=>{
 const h=harness();
 h.window.attachEuropeStationBasemap(h.map);
 await new Promise(resolve=>setImmediate(resolve));
 const primary=h.tiles[0];
 primary.trigger("tileerror");
 primary.trigger("tileerror");
 assert.equal(h.tiles.length,2);
 assert.match(h.tiles[1].url,/tile.openstreetmap.org/);
 assert.equal(h.removed.length,1);
 assert.equal(h.removed[0],primary);
 assert.equal(h.map.__europeStationGetBasemapState().sourceIndex,1);
 assert.equal(h.map.__europeStationGetBasemapState().geographyLoaded,true);
 h.tiles[1].trigger("tileload");
 assert.equal(h.stateEl.hidden,true);
});

test("both external tile services offline keep self-hosted geography and accessible status",async()=>{
 const h=harness();
 h.window.attachEuropeStationBasemap(h.map);
 await new Promise(resolve=>setImmediate(resolve));
 h.tiles[0].trigger("tileerror");
 h.tiles[0].trigger("tileerror");
 h.tiles[1].trigger("tileerror");
 h.tiles[1].trigger("tileerror");
 assert.equal(h.map.__europeStationGetBasemapState().geographyLoaded,true);
 assert.equal(h.stateEl.hidden,false);
 assert.match(h.stateEl.textContent,/Länderumrisse/);
});

test("local outline unavailable reports problem without breaking tile rendering",async()=>{
 const h=harness({offline:true});
 h.window.attachEuropeStationBasemap(h.map);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.tiles.length,1);
 assert.equal(h.polygons.length,0);
 assert.match(h.stateEl.textContent,/Kartenumrisse fehlen/);
});

test("map integration uses shared basemap and waits for Leaflet on first open",()=>{
 assert.match(HTML,/europe_station_basemap\.js\?v=/);
 assert.match(HTML,/id="europeStationBasemapStatus"/);
 assert.match(HTML,/window\.attachEuropeStationBasemap\(europeStationMap\)/);
 assert.match(HTML,/await window\.ensureEuropeStationLeaflet\(\)/);
});
