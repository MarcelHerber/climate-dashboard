(()=>{"use strict";
const $=id=>document.getElementById(id);
let index=null,coast=null,current=null;
const cache=new Map();
const colors=["#163b85","#3675ba","#78acd6","#dae8f2","#ffffff","#f7d6c0","#ed9b79","#cc5a48","#941c28"];
// Continuous diverging palette: smooth colours without implying extra observations.
const knots=[-4,-2,-1,-0.45,0,0.45,1,2,4];
function color(v){
 if(v===null||!Number.isFinite(v))return null;
 const value=Math.max(-4,Math.min(4,v));
 let i=0;while(i<knots.length-2&&value>knots[i+1])i++;
 const t=(value-knots[i])/(knots[i+1]-knots[i]);
 const parse=h=>[1,3,5].map(k=>parseInt(h.slice(k,k+2),16));
 const a=parse(colors[i]),b=parse(colors[i+1]);
 return a.map((x,j)=>Math.round(x+(b[j]-x)*t));
}
function buildRaster(record){
 const lons=index.longitudes,lats=index.latitudes;
 const raw=document.createElement("canvas");
 raw.width=lons.length;raw.height=lats.length;
 const context=raw.getContext("2d");
 const image=context.createImageData(raw.width,raw.height);
 for(let row=0;row<lats.length;row++){
  const reversed=lats.length-1-row;  // Northernmost data at top of image.
  for(let col=0;col<lons.length;col++){
   const rgb=color(record.z[reversed]?.[col]);
   if(!rgb)continue;
   const k=(row*lons.length+col)*4;
   image.data[k]=rgb[0];image.data[k+1]=rgb[1];image.data[k+2]=rgb[2];image.data[k+3]=255;
  }
 }
 context.putImageData(image,0,0);
 return raw;
}
function drawRaster(ctx,bounds,w,h,record){
 const lons=index.longitudes,lats=index.latitudes;
 const dx=lons[1]-lons[0],dy=lats[1]-lats[0];
 const west=lons[0]-dx/2,east=lons[lons.length-1]+dx/2;
 const south=lats[0]-dy/2,north=lats[lats.length-1]+dy/2;
 const [x0,y0]=project(west,north,bounds,w,h);
 const [x1,y1]=project(east,south,bounds,w,h);
 ctx.save();
 ctx.imageSmoothingEnabled=true;
 ctx.imageSmoothingQuality="high";
 ctx.drawImage(buildRaster(record),x0,y0,x1-x0,y1-y0);
 ctx.restore();
}
function project(lon,lat,bounds,w,h){return [(lon-bounds[0])/(bounds[1]-bounds[0])*w,(bounds[3]-lat)/(bounds[3]-bounds[2])*h];}
function coastlines(ctx,bounds,w,h){
 if(!coast||!window.topojson)return;
 const topo=window.topojson;
 const countries=coast.objects.countries;
 if(!countries)return;
 const land=topo.feature(coast,countries);
 function drawGeometry(geom,fill){
  if(!geom)return;
  if(geom.type==="FeatureCollection"){geom.features.forEach(f=>drawGeometry(f.geometry,fill));return;}
  if(geom.type==="Feature"){drawGeometry(geom.geometry,fill);return;}
  const polygons=geom.type==="Polygon"?[geom.coordinates]:
    geom.type==="MultiPolygon"?geom.coordinates:null;
  if(polygons){
   for(const poly of polygons){ctx.beginPath();
    for(const ring of poly){
     ring.forEach(([lon,lat],i)=>{const [x,y]=project(lon,lat,bounds,w,h);
      if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});
     ctx.closePath();
    }
    if(fill)ctx.fill("evenodd");ctx.stroke();
   }
   return;
  }
  const lines=geom.type==="LineString"?[geom.coordinates]:
    geom.type==="MultiLineString"?geom.coordinates:[];
  for(const line of lines){ctx.beginPath();let previous=null;
   line.forEach(([lon,lat],i)=>{
    const [x,y]=project(lon,lat,bounds,w,h);
    // Avoid artificial lines across the 180° meridian.
    if(i===0||(previous!==null&&Math.abs(x-previous)>w/2))ctx.moveTo(x,y);
    else ctx.lineTo(x,y);
    previous=x;
   });ctx.stroke();
  }
 }
 ctx.save();
 // Country polygons are filled in beige so anomalies remain exclusively over water.
 ctx.fillStyle="#dad5ca";ctx.strokeStyle="#253543";ctx.lineWidth=.8;
 drawGeometry(land,true);
 // Draw all international borders above the land fill.
 ctx.strokeStyle="#37434d";ctx.lineWidth=.6;
 drawGeometry(topo.mesh(coast,countries,(a,b)=>a!==b),false);
 ctx.restore();
}
function paint(canvas,region,record,ratio=1.65){
 const w=region==="atl"?1050:1250,h=region==="atl"?660:650;
 canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
 const ctx=canvas.getContext("2d");
 ctx.scale(canvas.width/w,canvas.height/h);
 const bounds=region==="atl"?[-115,25,-5,65]:[-180,180,-60,60];
 ctx.fillStyle="#eaf3f7";ctx.fillRect(0,0,w,h);
 drawRaster(ctx,bounds,w,h,record);
 // Subtle graticule, below the coastline and international borders.
 ctx.save();
 ctx.strokeStyle="rgba(65,87,106,.10)";
 ctx.lineWidth=.55;
 for(let lon=-180;lon<=180;lon+=20){
  const [x]=project(lon,0,bounds,w,h);
  ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();
 }
 for(let lat=-60;lat<=80;lat+=20){
  const [,y]=project(0,lat,bounds,w,h);
  ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();
 }
 ctx.restore();
 coastlines(ctx,bounds,w,h);
 // Floating white annotation background for TV and social exports.
 ctx.fillStyle="rgba(255,255,255,.91)";
 ctx.fillRect(10,8,region==="atl"?635:760,65);
 ctx.fillStyle="#17283c";ctx.font="bold 23px Arial";
 ctx.fillText("Räumliche ACE-Anomalie · "+record.year+(record.provisional?" (vorläufig)":""),20,34);
 ctx.font="16px Arial";
 ctx.fillText((region==="atl"?"Nordatlantik":"Weltweit")+" · Referenz 1991–2020 · "+(record.provisional?"bis "+record.through:"Gesamtjahr"),20,59);
 const lx=w-382,ly=18,legendW=326;
 ctx.fillStyle="rgba(255,255,255,.94)";ctx.fillRect(lx-12,ly-9,legendW+27,61);
 const gradient=ctx.createLinearGradient(lx,0,lx+legendW,0);
 colors.forEach((hex,i)=>gradient.addColorStop(i/(colors.length-1),hex));
 ctx.fillStyle=gradient;ctx.fillRect(lx,ly,legendW,17);
 ctx.strokeStyle="#75889b";ctx.lineWidth=.5;ctx.strokeRect(lx,ly,legendW,17);
 ctx.fillStyle="#263749";ctx.font="12px Arial";
 ctx.fillText("−4σ",lx,ly+33);ctx.fillText("0",lx+legendW/2-4,ly+33);
 ctx.fillText("+4σ",lx+legendW-25,ly+33);
 ctx.fillStyle="rgba(255,255,255,.90)";ctx.fillRect(12,h-39,620,28);
 ctx.fillStyle="#2d4055";ctx.font="13px Arial";
 ctx.fillText("NOAA IBTrACS · geglättete ACE-Verteilung · σ · "+index.resolution_deg+"°-Raster",20,h-20);
}
async function refresh(){
 const year=$("aceMapYear").value;
 $("aceMapStatus").textContent="Lade ACE-Kartenarchiv für "+year+" …";
 try{
  if(!cache.has(year)){
   const r=await fetch("ace/spatial/"+year+".json",{cache:"no-store"});
   if(!r.ok)throw Error("HTTP "+r.status);
   const d=await r.json();if(!d.ready)throw Error("Jahr noch nicht bereit");
   cache.set(year,d);
  }
  current=cache.get(year);
  paint($("aceMapCanvas"),$("aceMapRegion").value,current);
  $("aceMapStatus").textContent=(current.provisional?"Vorläufige Daten bis "+current.through:"Historischer Jahreszeitraum "+year)
    +" · "+index.resolution_deg+"° Raster, Gauß-Glättung "+index.kernel_sigma_deg+"°"
    +(index.resolution_deg>1?" · 1°-Archiv wird noch neu berechnet.":"")
    +" · Standardisiert gegenüber 1991–2020; keine Signifikanzanalyse.";
 }catch(e){$("aceMapStatus").textContent="Karte nicht verfügbar: "+e.message;}
}
function exportMap(ext){
 if(!current)return;
 const region=$("aceMapRegion").value;
 const filename="ACE_Anomalie_"+region+"_"+current.year+"_"+index.resolution_deg+"deg";
 // Render a separate print-resolution map, not the scaled browser preview.
 const high=document.createElement("canvas");
 paint(high,region,current,(region==="atl"?2800/1050:3200/1250));
 if(ext==="png"){
  high.toBlob(blob=>{
   if(!blob){$("aceMapStatus").textContent="PNG-Erstellung fehlgeschlagen.";return;}
   const url=URL.createObjectURL(blob),a=document.createElement("a");
   a.download=filename+".png";a.href=url;document.body.appendChild(a);a.click();a.remove();
   setTimeout(()=>URL.revokeObjectURL(url),4000);
  },"image/png");
 }else if(ext==="pdf"){
  if(!window.jspdf?.jsPDF){$("aceMapStatus").textContent="PDF-Bibliothek nicht geladen.";return;}
  const pdf=new window.jspdf.jsPDF({orientation:"landscape",unit:"mm",format:"a4"});
  const maxW=277,maxH=190,scale=Math.min(maxW/high.width,maxH/high.height);
  pdf.addImage(high.toDataURL("image/png"),"PNG",10,10,
               high.width*scale,high.height*scale);
  pdf.save(filename+".pdf");
 }
}
async function init(){
 try{
  const r=await fetch("ace/spatial/index.json",{cache:"no-store"});
  if(!r.ok)throw Error("Archivindex HTTP "+r.status);
  index=await r.json();if(!index.ready||!index.years?.length)throw Error("Kein berechnetes Kartenjahr");
  const select=$("aceMapYear");for(const year of [...index.years].reverse()){
   const o=document.createElement("option");o.value=year;o.textContent=year;select.append(o);}
  try{
   const atlas=await fetch("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json");
   if(atlas.ok)coast=await atlas.json();
   else console.warn("ACE country borders HTTP",atlas.status);
  }catch(e){console.warn("ACE coastline unavailable",e);}
  select.addEventListener("change",refresh);
  $("aceMapRegion").addEventListener("change",refresh);
  document.querySelectorAll("[data-ace-map-download]").forEach(b=>b.addEventListener("click",()=>exportMap(b.dataset.aceMapDownload)));
  await refresh();
  if(!coast||!window.topojson) $("aceMapStatus").textContent+=" · Hinweis: Ländergrenzen konnten nicht geladen werden.";
 }catch(e){$("aceMapStatus").textContent="ACE-Kartenarchiv wird noch aufgebaut: "+e.message;}
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();