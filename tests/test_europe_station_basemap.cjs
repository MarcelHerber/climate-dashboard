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
 const container={style:{}};
 const map={
  panes:new Map(),
  getContainer(){return container},
  createPane(name){const pane={style:{}};this.panes.set(name,pane);return pane;},
  getPane(name){return this.panes.get(name);},
  removeLayer(layer){removed.push(layer)},
  on(event,callback){this.events??={};this.events[event]=callback},
 };
 const L={
  map(){return map;},
  svg(options){return {kind:"svg",options};},
  geoJSON(geo,options){
   const layer={
    geo,options,styles:[],
    addTo(target){assert.equal(target,map);return this;},
    setStyle(style){this.styles.push(style);return this;}
   };
   polygons.push(layer);
   return layer;
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
 return {window,map,container,tiles,polygons,removed,timers,stateEl};
}

test("ship actual Natural Earth Europe geography with Pages",()=>{
 assert.ok(NATURAL_EARTH.source.includes("Natural Earth"));
 assert.ok(NATURAL_EARTH.countries.length>=60);
 assert.ok(Array.isArray(NATURAL_EARTH.countries[0].p));
 assert.ok(NATURAL_EARTH.countries[0].p[0][0][0].length===2);
});

test("self-hosted SVG geography is above raster tiles and below station markers",async()=>{
 const h=harness();
 h.window.attachEuropeStationBasemap(h.map);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.polygons.length,1);
 const layer=h.polygons[0];
 assert.equal(layer.geo.type,"FeatureCollection");
 assert.equal(layer.geo.features.length,NATURAL_EARTH.countries.length);
 assert.equal(layer.geo.features[0].geometry.type,"MultiPolygon");
 assert.equal(layer.options.interactive,false);
 assert.equal(layer.options.pane,"europeStationGeographyPane");
 assert.equal(layer.options.renderer.kind,"svg");
 assert.equal(layer.options.renderer.options.pane,"europeStationGeographyPane");
 assert.equal(h.map.getPane("europeStationGeographyPane").style.zIndex,"350");
 assert.equal(layer.options.style.fillOpacity,.94);
 assert.equal(h.container.style.backgroundColor,"#dcebf2");
 assert.equal(h.map.__europeStationGetBasemapState().geographyLoaded,true);
});

test("never request CARTO key-required imagery; optional OSM layer enhances local outlines",async()=>{
 const h=harness();
 h.window.attachEuropeStationBasemap(h.map);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.tiles.length,1);
 assert.match(h.tiles[0].url,/^https:\/\/tile\.openstreetmap\.org\//);
 assert.doesNotMatch(SOURCE,/cartocdn\.com/);
 h.tiles[0].trigger("tileload");
 assert.equal(h.polygons[0].styles.at(-1).fillOpacity,.12);
 assert.equal(h.map.__europeStationGetBasemapState().sourceIndex,0);
 assert.equal(h.map.__europeStationGetBasemapState().geographyLoaded,true);
 assert.equal(h.stateEl.hidden,true);
});

test("OSM failure removes broken raster images and keeps full local basemap",async()=>{
 const h=harness();
 h.window.attachEuropeStationBasemap(h.map);
 await new Promise(resolve=>setImmediate(resolve));
 const original=h.tiles[0];
 original.trigger("tileerror");
 original.trigger("tileerror");
 assert.equal(h.tiles.length,1);
 assert.equal(h.removed.length,1);
 assert.equal(h.removed[0],original);
 assert.equal(h.map.__europeStationGetBasemapState().sourceIndex,-1);
 assert.equal(h.map.__europeStationGetBasemapState().rasterDisabled,true);
 assert.equal(h.map.__europeStationGetBasemapState().geographyLoaded,true);
 assert.equal(h.polygons[0].styles.at(-1).fillOpacity,.94);
 assert.equal(h.stateEl.hidden,false);
 assert.match(h.stateEl.textContent,/Ländergrenzen/);
});

test("local outlines unavailable report error without stopping OSM",async()=>{
 const h=harness({offline:true});
 h.window.attachEuropeStationBasemap(h.map);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.tiles.length,1);
 assert.equal(h.polygons.length,0);
 assert.match(h.stateEl.textContent,/Ländergrenzen konnten nicht geladen/);
});

test("map integration uses shared basemap and waits for Leaflet on first open",()=>{
 assert.match(HTML,/europe_station_basemap\.js\?v=/);
 assert.match(HTML,/id="europeStationBasemapStatus"/);
 assert.match(HTML,/window\.attachEuropeStationBasemap\(europeStationMap\)/);
 assert.match(HTML,/await window\.ensureEuropeStationLeaflet\(\)/);
});
