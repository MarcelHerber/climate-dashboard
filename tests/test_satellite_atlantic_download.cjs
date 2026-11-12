"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const source=fs.readFileSync("satelliten.js","utf8");
const start=source.indexOf("function loadCORSImage(");
const end=source.indexOf("async function downloadComposite(format){",start);
assert.ok(start>=0&&end>start);
const pixelCode=source.slice(start,end);
const UTC="2026-11-12T11:20:00Z";
const BOX="-70,15,35,75";
function fixture({failWidths=[],cacheTime=null,cacheWorks=false}={}){
 const requests=[],fetches=[],photo={naturalWidth:400,crossOrigin:"",src:"https://view.eumetsat.int/old-image.png"};
 const region={value:"atlantic"},product={value:"geocolour"};
 class Image {
  constructor(){this.crossOrigin="";this.naturalWidth=0;this.naturalHeight=0;this.onload=null;this.onerror=null;this._src="";}
  set src(url){
   this._src=url;
   if(!url)return;
   requests.push({url,crossOrigin:this.crossOrigin});
   queueMicrotask(()=>{
    if(!this._src)return;
    const params=new URL(url,"https://example.test/").searchParams;
    const width=Number(params.get("width"))||400;
    if(failWidths.includes(width)||(!url.startsWith("./")&&failWidths.includes("all"))||
       (url.startsWith("./")&&!cacheWorks)){this.onerror?.();return;}
    this.naturalWidth=width;this.naturalHeight=Math.round(width*850/1400);
    this.onload?.();
   });
  }
  get src(){return this._src;}
 }
 const cachePath=(time)=>"./data/satellite_cache/geocolour_atlantic_"+
  time.replace(/[-:]/g,"")+".png";
 const fetch=async url=>{
  fetches.push(url);
  if(!cacheTime)return {ok:false,status:404};
  return {ok:true,json:async()=>({
   schema:1,entries:{geocolour:{atlantic:{
    time:cacheTime,url:cachePath(cacheTime),width:400,source:"EUMETSAT WMS"
   }}}
  })};
 };
 const window={};
 const sandbox={window,Image,region,product,filmImage:{hidden:true},
  filmItems:[],filmPosition:0,image:photo,cachedImage:null,fetch,
  setTimeout,clearTimeout,URL,Date,
  REGIONS:{atlantic:{w:1400,h:850,bbox:[-70,15,35,75]}},
  imageUrl:(time,width)=>"https://view.eumetsat.int/geoserver/wms?"+
   new URLSearchParams({request:"GetMap",layers:"mtg_fd:rgb_geocolour",
    time,bbox:BOX,width:String(width),height:String(Math.round(width*850/1400))}),
 };
 vm.runInNewContext(pixelCode+"\nwindow.testExportPixels=exportPixels;",sandbox,{timeout:5000});
 return {run:window.testExportPixels,requests,fetches,cachePath,photo};
}
test("Atlantic exporter requests time-identical CORS-enabled smaller WMS instead of fragile 1400px",async()=>{
 const f=fixture();const image=await f.run(UTC);
 assert.equal(image.naturalWidth,720);
 assert.equal(f.requests.length,1);
 const u=new URL(f.requests[0].url);
 assert.equal(u.searchParams.get("time"),UTC);
 assert.equal(u.searchParams.get("bbox"),BOX);
 assert.equal(u.searchParams.get("width"),"720");
 assert.equal(f.requests[0].crossOrigin,"anonymous");
});
test("Failed Atlantic 720px falls back to 480px with unchanged geographic extent and UTC",async()=>{
 const f=fixture({failWidths:[720]});const img=await f.run(UTC);
 assert.equal(img.naturalWidth,480);
 assert.deepEqual(f.requests.map(x=>new URL(x.url).searchParams.get("width")),["720","480"]);
 assert.ok(f.requests.every(x=>new URL(x.url).searchParams.get("bbox")===BOX));
});
test("All WMS resolutions fail: exact-UTC same-region official PNG archive is used",async()=>{
 const f=fixture({failWidths:["all"],cacheTime:UTC,cacheWorks:true});
 const image=await f.run(UTC);
 assert.equal(image.naturalWidth,400);
 assert.equal(f.requests.length,4);
 assert.equal(f.requests.at(-1).url,f.cachePath(UTC));
 assert.ok(f.requests.every(x=>x.crossOrigin==="anonymous"));
});
test("Stale Atlantic archive is never relabelled as current and no tainted preview is returned",async()=>{
 const f=fixture({failWidths:["all"],cacheTime:"2026-11-12T11:00:00Z",cacheWorks:true});
 await assert.rejects(f.run(UTC),/nicht automatisch für Canvas freigegeben/);
 assert.equal(f.requests.length,3);
 assert.ok(!f.requests.some(x=>x.url.includes("20261112T110000")));
 assert.equal(f.photo.naturalWidth,400,"Existing visible preview is not falsely passed as CORS-safe");
});
test("Atlantic export regression: PNG, PDF, GIF buttons remain and call their own actions",()=>{
 const html=fs.readFileSync("satelliten.html","utf8");
 for(const id of ["satPng","satPngIsobars","satPdfIsobars","satGif","satGifIsobars"]){
  assert.ok(html.includes('id="'+id+'"'),"missing "+id);
 }
 assert.match(source,/const img=await exportPixels\(selected\)/);
 assert.match(source,/composite\.renderPDF\(arg\)/);
 assert.match(source,/composite\.renderPNG\(arg\)/);
 assert.match(source,/exporters\.exportGIF\(/);
 assert.match(source,/\[720,480,400\]/);
});
