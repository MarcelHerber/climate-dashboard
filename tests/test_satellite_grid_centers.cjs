"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const geometrySource=fs.readFileSync("satellite_isobar_geometry.js","utf8");
const rendererSource=fs.readFileSync("satellite_map_export.js","utf8");
const BBOX=[-27,24,49,73];
const raw=[
 {type:"T",lon:-18,lat:49.75,pressure_hpa:994.7,prominence_hpa:6.1,score:53},
 {type:"H",lon:14,lat:51.25,pressure_hpa:1030.2,prominence_hpa:5.5,score:48}
];
function context(){
 const scope={window:{},Math,Number,TextEncoder,Blob,Uint8Array,Uint8ClampedArray,ArrayBuffer,
  atob:s=>Buffer.from(s,"base64").toString("binary"),setTimeout,
  document:{createElement:()=>({width:0,height:0,
   getContext(){return {save(){},restore(){},beginPath(){},rect(){},clip(){},moveTo(){},
    lineTo(){},stroke(){},fill(){},arc(){},fillRect(){},strokeRect(){},
    drawImage(){},fillText(){},strokeText(){},measureText(s){return {width:s.length*7}}}},
   toDataURL(){return "data:image/jpeg;base64,"+Buffer.from([255,216,255,217]).toString("base64");},
   toBlob(cb){cb(new Blob(["png"],{type:"image/png"}));}})}
 };
 vm.runInNewContext(geometrySource,scope);
 vm.runInNewContext(rendererSource,scope);
 return {geo:scope.window.SatelliteIsobarGeometry,exporter:scope.window.SatelliteMapExport};
}
function make(spacing){
 return {validUTC:"2026-11-14T12:00:00Z",satelliteUTC:"2026-11-14T12:00:00Z",
  runUTC:"2026-11-14T12:00:00Z",region:"europe",spacing,
  contours:[{hpa:spacing===2?1002:1000,
    lines:[ [[-26,30],[-20,35],[-16,41],[-8,47],[-2,48],[10,46],[28,45]] ]}],
  pressure_centers_method:"ifs_mslp_grid_extrema_v1",pressure_centers:raw};
}
const normalized=a=>JSON.parse(JSON.stringify(a));
test("Same IFS grid extrema and kerndruck for 2 and 5 hPa despite totally different isolines",()=>{
 const {geo,exporter}=context(),a=make(2),b=make(5);
 assert.deepEqual(normalized(geo.modelGridCenters(a,BBOX)),
   normalized(geo.modelGridCenters(b,BBOX)));
 assert.deepEqual(normalized(exporter.pressureCenters(a,"europe")),
   normalized(exporter.pressureCenters(b,"europe")));
 assert.equal(exporter.pressureCenters(a,"europe")[0].hpa,994.7);
 assert.equal(exporter.pressureCenters(a,"europe")[0].source,"ifs_grid");
});
test("Single grid center remains visible even when neither 2- nor 5-hPa loops close",()=>{
 const {exporter}=context();
 assert.equal(exporter.pressureCenters(make(5),"europe").length,2);
 assert.equal(exporter.pressureCenters(make(2),"europe").length,2);
});
test("Grid MSLP centers reject unverified source geometry and cannot invent fallback markers",()=>{
 const {geo}=context();
 const fake=make(5);fake.pressure_centers=[{...raw[0],lat:500}];
 assert.throws(()=>geo.modelGridCenters(fake,BBOX),/Gitter|IFS/);
 assert.deepEqual(normalized(geo.modelGridCenters({...make(5),pressure_centers:[]},BBOX)),[]);
});
test("City and contour-number collisions move only label, with true grid anchor unchanged",()=>{
 const {geo}=context(),centers=geo.modelGridCenters(make(5),BBOX);
 const low=centers[0],lab=geo.project([low.lon,low.lat],BBOX);
 const lonlat=[low.lon,low.lat];
 const placed=geo.pressureLabels(centers,BBOX,{
  width:1000,height:1000,fontSize:40.5,
  isobarLabels:[lonlat],cityAnchors:[{name:"Simulated city",lon:low.lon,lat:low.lat}]
 });
 const label=placed.find(x=>x.type==="T");
 assert.ok(label,"Label can be displaced to free visible space");
 assert.equal(label.lon,low.lon);
 assert.equal(label.lat,low.lat);
 assert.equal(label.anchorX,lab[0]);assert.equal(label.anchorY,lab[1]);
 assert.equal(label.leader,true);
 assert.ok(Math.hypot(label.labelX-label.anchorX,label.labelY-label.anchorY)>15);
 const again=geo.pressureLabels(centers,BBOX,{width:1000,height:1000,fontSize:40.5,
  isobarLabels:[lonlat],cityAnchors:[{name:"Simulated city",lon:low.lon,lat:low.lat}]});
 assert.deepEqual(normalized(again),normalized(placed),"Deterministic label locations for SVG and exports");
});
test("PNG/GIF/PDF exporters use shared model centers, vector letters and leaders",async()=>{
 const {exporter}=context();
 const image={naturalWidth:900,naturalHeight:500};
 const a=make(5);
 const png=await exporter.renderPNG({image,overlay:a,region:"europe",
  regionName:"Europa",product:"geocolour",productName:"GeoColour"});
 assert.equal(png.blob.type,"image/png");
 const pdf=await exporter.renderPDF({image,overlay:a,region:"europe",
  regionName:"Europa",product:"geocolour",productName:"GeoColour"});
 const bytes=Buffer.from(await pdf.blob.arrayBuffer()).toString("latin1");
 assert.ok(bytes.includes("(T) Tj ET")&&bytes.includes("(H) Tj ET"));
 assert.ok(bytes.includes("/Subtype /Image"));
 assert.ok(bytes.includes(" RG"));
});
