"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const content=fs.readFileSync("satellite_map_export.js","utf8");
const geometry=fs.readFileSync("satellite_isobar_geometry.js","utf8");
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
 const calls=[],textCalls=[];
 const ctx={
  save(){},restore(){},beginPath(){},rect(){},clip(){},moveTo(){},lineTo(){},fillRect(){},
  strokeRect(){},fillText(s){textCalls.push(String(s));},strokeText(s){textCalls.push("outline:"+String(s));},drawImage(){},stroke(){calls.push({width:this.lineWidth,color:this.strokeStyle});},
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
 vm.runInNewContext(geometry,scope,{timeout:5000});
 vm.runInNewContext(content,scope,{timeout:5000});
 vm.runInNewContext(film,scope,{timeout:5000});
 return {api:scope.window.SatelliteMapExport,film:scope.window.SatelliteFilmExport,calls,textCalls};
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
 assert.deepEqual(pink.map(s=>s.width),[0.9,0.9,1.55],
  "Pink: normal 0.9px, 1015 hPa 1.55px at reference scale");
 assert.deepEqual(halo.map(s=>s.width),[2.3,2.3,2.95],
  "Dark halo: normal 2.3px, 1015 hPa 2.95px at reference scale");
 assert.ok(pink[2].width>pink[1].width);
 assert.equal(pink[0].width,pink[1].width);
 assert.ok(!calls.some(x=>["#ffb447","#3bdeff"].includes(x.color)));
});
test("The same shared filter removes tiny isobar loops in PNG/GIF/PDF vector geometry",()=>{
 const {api}=loaded();
 const ring=(lon,lat,dx,dy)=>[
  [lon-dx,lat], [lon,lat+dy], [lon+dx,lat], [lon,lat-dy], [lon-dx,lat]
 ];
 const extra={...sourceOverlay,contours:[{hpa:1015,lines:[
  ...sourceOverlay.contours[2].lines,
  ring(-8,37,.17,.1)
 ]}]};
 const clean=api.pathsFor(extra,"southwest");
 assert.equal(clean.length,1);
 assert.equal(clean[0].runs.length,1,"Micro-loop must not enter the PDF, PNG or GIF compositor");
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

test("Atlantic PNG, vector PDF and GIF contain only verified H/T letters",async()=>{
 const {api,film,textCalls}=loaded();
 const ring=(lon,lat,r)=>Array.from({length:65},(_,i)=>{
  const rad=Math.PI*2*i/64;return [lon+r*Math.cos(rad),lat+r*.6*Math.sin(rad)];
 });
 const layer={...sourceOverlay,region:"atlantic",contours:[
  {hpa:1005,lines:[ring(-55,55,10)]},
  {hpa:1000,lines:[ring(-55,55,6)]},
  {hpa:995,lines:[ring(-55,55,3)]},
  // The H must be recognized from only one broad closed 1020-hPa ring.
  {hpa:1020,lines:[ring(-20,43,10)]}
 ]};
 const found=api.pressureCenters(layer,"atlantic");
 assert.deepEqual(Array.from(found,x=>x.type).sort(),["H","T"]);
 const item={...options,region:"atlantic",regionName:"Nordatlantik & Europa",overlay:layer};
 const png=await api.renderPNG(item);
 assert.equal(png.blob.type,"image/png");
 assert.ok(png.name.includes("_atlantic_")&&png.name.endsWith("_isobaren.png"));
 assert.ok(textCalls.includes("H")&&textCalls.includes("T"),
  "PNG must render both meteorologically verified system letters");
 const pdf=await api.renderPDF(item);
 const body=Buffer.from(await pdf.blob.arrayBuffer()).toString("latin1");
 assert.match(body,/\(H\) Tj ET/);
 assert.match(body,/\(T\) Tj ET/);
 assert.ok(pdf.name.includes("_atlantic_"));
 assert.match(body,/\/Subtype \/Image/);
 const second=new Date(Date.parse(layer.satelliteUTC)+600000).toISOString().replace(".000Z","Z");
 const gif=await film.exportGIF({
  frames:[{time:layer.satelliteUTC,img:{naturalWidth:180,naturalHeight:100}},
          {time:second,img:{naturalWidth:180,naturalHeight:100}}],
  isobarOverlays:[layer,{...layer,satelliteUTC:second,validUTC:second}],
  region:"atlantic",product:"geocolour",productName:"GeoColour",
  width:160,delayMs:360,credit:"EUMETSAT"
 });
 const bytes=Buffer.from(await gif.blob.arrayBuffer());
 assert.equal(bytes.subarray(0,6).toString(),"GIF89a");
 assert.ok(textCalls.filter(x=>x==="H").length>=3&&textCalls.filter(x=>x==="T").length>=3,
  "GIF must include the same H/T letters frame by frame");
});

test("2-hPa European PNG and vector PDF retain even-pressure contours and 1015 is not emphasized",async()=>{
 const {api,calls}=loaded();
 const source=sourceOverlay.contours;
 const fine={...sourceOverlay,spacing:2,contours:[
  {hpa:1000,lines:source[0].lines},
  {hpa:1002,lines:source[1].lines},
  {hpa:1004,lines:source[2].lines},
  {hpa:1010,lines:source[1].lines}
 ]};
 const groups=api.pathsFor(fine,"southwest");
 assert.deepEqual(Array.from(groups,x=>x.hpa),[1000,1002,1004,1010]);
 assert.ok(groups.every(x=>!x.heavy));
 const ctx={save(){},restore(){},beginPath(){},rect(){},clip(){},moveTo(){},lineTo(){},
  stroke(){calls.push({width:this.lineWidth,color:this.strokeStyle});},
  measureText(){return {width:27}},fillRect(){},strokeRect(){},fillText(){}};
 api.paintIsobars(ctx,fine,"southwest",{width:900,height:400});
 const pink=calls.filter(x=>x.color==="#ff4fcf");
 const halo=calls.filter(x=>x.color==="#061522");
 assert.ok(pink.length===4&&halo.length===4);
 assert.ok(pink.every(x=>x.width===.75));
 assert.ok(halo.every(x=>x.width===1.85));
 const opts={...options,overlay:fine};
 const png=await api.renderPNG(opts);
 assert.equal(png.blob.type,"image/png");
 const pdf=await api.renderPDF(opts);
 assert.equal(pdf.blob.type,"application/pdf");
 const txt=Buffer.from(await pdf.blob.arrayBuffer()).toString("latin1");
 assert.ok(txt.startsWith("%PDF-1.4"));
 assert.ok(txt.includes("/Subtype /Image"));
 assert.ok(txt.includes("(1010) Tj ET"));
});
