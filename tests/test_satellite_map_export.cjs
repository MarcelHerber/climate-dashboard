"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const content=fs.readFileSync("satellite_map_export.js","utf8");
const film=fs.readFileSync("satellite_film_export.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");
const site=fs.readFileSync("satelliten.js","utf8");
const sourceOverlay={validUTC:"2026-11-12T03:20:00Z",satelliteUTC:"2026-11-12T03:20:00Z",
 runUTC:"2026-11-12T00:00:00Z",method:"10-Minuten-Interpolation des MSLP-Gitterfeldes",
 spacing:5,region:"southwest",contours:[
  {hpa:1005,lines:[[[-32,41],[-29,42],[-26,43],[-22,44],[-17,45],[-10,45],[-6,46],[-3,46]]]},
  {hpa:1010,lines:[[[-30,42],[-26,42],[-22,43],[-18,44],[-14,44],[-10,45],[-5,45],[-2,46]]]},
  {hpa:1015,lines:[[[-30,40],[-26,41],[-22,42],[-18,43],[-14,43],[-10,44],[-5,44],[-2,45]]]}
 ]};
function loaded(){
 const calls=[];
 const ctx={
  save(){},restore(){},beginPath(){},rect(){},clip(){},moveTo(){},lineTo(){},fillRect(){},
  strokeRect(){},fillText(){},drawImage(){},stroke(){calls.push({width:this.lineWidth,color:this.strokeStyle});},
  measureText(s){return {width:s.length*7};},
  getImageData(x,y,w,h){return {data:new Uint8ClampedArray(w*h*4).fill(127)}}
 };
 const canvas=()=>({
  width:0,height:0,getContext(){return ctx;},
  toDataURL(){return "data:image/jpeg;base64,"+Buffer.from([0xff,0xd8,0xff,0xd9]).toString("base64");},
  toBlob(fn){fn(new Blob(["mock-composite"],{type:"image/png"}));}
 });
 const scope={
  window:{},Blob,TextEncoder,Uint8Array,Uint8ClampedArray,ArrayBuffer,
  atob:s=>Buffer.from(s,"base64").toString("binary"),setTimeout,
  document:{createElement:()=>canvas()},
  console
 };
 vm.runInNewContext(content,scope,{timeout:5000});
 vm.runInNewContext(film,scope,{timeout:5000});
 return {api:scope.window.SatelliteMapExport,film:scope.window.SatelliteFilmExport,calls};
}
const options={image:{naturalWidth:180,naturalHeight:100},
 overlay:sourceOverlay,region:"southwest",regionName:"Südwesteuropa",
 product:"geocolour",productName:"GeoColour",credit:"EUMETSAT"};

test("Only 1015 hPa is bold; all visible isobars remain pink with a dark halo",()=>{
 const {api,calls}=loaded();
 const groups=api.pathsFor(sourceOverlay,"southwest");
 assert.deepEqual(Array.from(groups,g=>[g.hpa,g.heavy]),[[1005,false],[1010,false],[1015,true]]);
 const ctx={save(){},restore(){},beginPath(){},rect(){},clip(){},moveTo(){},lineTo(){},
  stroke(){calls.push({width:this.lineWidth,color:this.strokeStyle});},
  measureText(){return {width:27}},fillRect(){},strokeRect(){},fillText(){}};
 api.paintIsobars(ctx,sourceOverlay,"southwest",{width:900,height:400});
 const pink=calls.filter(x=>x.color==="#ff4fcf"),halo=calls.filter(x=>x.color==="#061522");
 assert.equal(pink.length,3);assert.equal(halo.length,3);
 assert.ok(pink[2].width>pink[1].width);
 assert.equal(pink[0].width,pink[1].width);
 assert.ok(!calls.some(x=>["#ffb447","#3bdeff"].includes(x.color)));
});
test("PNG with time-provenanced isobars produces downloadable PNG bytes",async()=>{
 const {api}=loaded();
 const result=await api.renderPNG(options);
 assert.ok(result.name.endsWith("_isobaren.png"));
 assert.equal(result.blob.type,"image/png");
 assert.ok(result.blob.size>0);
});
test("PDF embeds satellite image and distinct editable vector pressure paths",async()=>{
 const {api}=loaded();
 const result=await api.renderPDF(options);
 const bytes=Buffer.from(await result.blob.arrayBuffer());
 const pdf=bytes.toString("latin1");
 assert.equal(result.blob.type,"application/pdf");
 assert.ok(result.name.endsWith("_isobaren.pdf"));
 assert.ok(pdf.startsWith("%PDF-1.4"));
 assert.match(pdf,/\/Subtype \/Image/);
 assert.match(pdf,/\/Filter \/DCTDecode/);
 assert.match(pdf,/1015/);
 assert.match(pdf,/ l\n/);
 assert.match(pdf,/ RG/);
 assert.match(pdf,/xref\n0 7\n/);
 assert.match(pdf,/%%EOF/);
});
test("Animated GIF composites a pressure overlay for each verified UTC frame",async()=>{
 const {film,api}=loaded();
 const t2="2026-11-12T03:30:00Z";
 const overlays=[sourceOverlay,{...sourceOverlay,validUTC:t2,satelliteUTC:t2}];
 const images=[sourceOverlay.satelliteUTC,t2].map(t=>({time:t,img:{naturalWidth:180,naturalHeight:100}}));
 const result=await film.exportGIF({frames:images,isobarOverlays:overlays,
  product:"geocolour",productName:"GeoColour",credit:"EUMETSAT",
  region:"southwest",width:160,delayMs:400});
 assert.equal(result.blob.type,"image/gif");
 const buf=Buffer.from(await result.blob.arrayBuffer());
 assert.equal(buf.subarray(0,6).toString(),"GIF89a");
 const wrong=[sourceOverlay,{...sourceOverlay,validUTC:t2,satelliteUTC:"2026-11-12T03:40:00Z"}];
 await assert.rejects(film.exportGIF({frames:images,isobarOverlays:wrong,
  product:"geocolour",productName:"GeoColour",credit:"EUMETSAT",
  region:"southwest",width:160,delayMs:400}),/passenden Isobaren/);
});
test("Controls and publication contain all three new composite downloads",()=>{
 for(const id of ["satPngIsobars","satPdfIsobars","satGifIsobars"])
  assert.ok(html.includes('id="'+id+'"'),id+" missing");
 assert.ok(html.includes("satellite_map_export.js"));
 assert.match(site,/downloadComposite\("pdf"\)/);
 assert.match(site,/downloadComposite\("png"\)/);
 assert.match(site,/downloadGIFIsobars/);
 assert.match(html,/1015 hPa/);
});
