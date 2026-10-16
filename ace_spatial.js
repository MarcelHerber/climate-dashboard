(()=>{"use strict";
const $=id=>document.getElementById(id);
let index=null,coast=null,current=null;
const cache=new Map();
const colors=["#163b85","#3675ba","#78acd6","#dae8f2","#ffffff","#f7d6c0","#ed9b79","#cc5a48","#941c28"];
const maps={
 z:{label:"Standardisierte ACE-Abweichung",unit:"σ",points:[-4,-2,-1,-0.45,0,0.45,1,2,4],min:"−4σ",mid:"0",max:"+4σ"},
 abs:{label:"Absolute ACE-Abweichung",unit:"10⁴ kn² / 1°-Zelle",points:[-1,-.5,-.2,-.05,0,.05,.2,.5,1],min:"−1",mid:"0",max:"+1"},
 pct:{label:"ACE in Prozent des Klimamittels",unit:"% des Mittels",points:[0,25,50,75,100,125,150,200,300],min:"0 %",mid:"100 %",max:"300 %"}
};
function selectedMetric(){return $("aceMapMetric")?.value||"z";}
function selectedLayout(){return $("aceMapLayout")?.value||"standard";}
function color(v,metric){
 if(v===null||!Number.isFinite(v))return null;
 const stops=maps[metric].points;
 const value=Math.max(stops[0],Math.min(stops[stops.length-1],v));
 let i=0;while(i<stops.length-2&&value>stops[i+1])i++;
 const t=Math.max(0,Math.min(1,(value-stops[i])/(stops[i+1]-stops[i])));
 const parse=h=>[1,3,5].map(k=>parseInt(h.slice(k,k+2),16));
 const a=parse(colors[i]),b=parse(colors[i+1]);
 return a.map((x,j)=>Math.round(x+(b[j]-x)*t));
}
function buildRaster(record,metric){
 const lons=index.longitudes,lats=index.latitudes;
 const raw=document.createElement("canvas");
 raw.width=lons.length;raw.height=lats.length;
 const context=raw.getContext("2d");
 const image=context.createImageData(raw.width,raw.height);
 for(let row=0;row<lats.length;row++){
  const reversed=lats.length-1-row;  // Northernmost data at top of image.
  for(let col=0;col<lons.length;col++){
   const rgb=color(record[metric]?.[reversed]?.[col],metric);
   if(!rgb)continue;
   const k=(row*lons.length+col)*4;
   image.data[k]=rgb[0];image.data[k+1]=rgb[1];image.data[k+2]=rgb[2];image.data[k+3]=255;
  }
 }
 context.putImageData(image,0,0);
 return raw;
}
function drawRaster(ctx,bounds,w,h,record,metric){
 const lons=index.longitudes,lats=index.latitudes;
 const dx=lons[1]-lons[0],dy=lats[1]-lats[0];
 const west=lons[0]-dx/2,east=lons[lons.length-1]+dx/2;
 const south=lats[0]-dy/2,north=lats[lats.length-1]+dy/2;
 const [x0,y0]=project(west,north,bounds,w,h);
 const [x1,y1]=project(east,south,bounds,w,h);
 ctx.save();
 ctx.imageSmoothingEnabled=true;
 ctx.imageSmoothingQuality="high";
 ctx.drawImage(buildRaster(record,metric),x0,y0,x1-x0,y1-y0);
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
function paint(canvas,region,record,ratio=1.6,layout="standard",metric="z"){
 if(!Array.isArray(record?.[metric]))throw Error("Kartenparameter "+metric+" ist für "+record?.year+" noch nicht berechnet.");
 const broadcast=layout==="broadcast";
 const w=broadcast?1600:(region==="atl"?1050:1250);
 const h=broadcast?900:(region==="atl"?660:650);
 canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
 const ctx=canvas.getContext("2d");
 if(!ctx)throw Error("Canvas nicht verfügbar");
 ctx.scale(canvas.width/w,canvas.height/h);
 const bounds=region==="atl"?[-115,25,-5,65]:[-180,180,-60,60];
 const rect=broadcast?{x:27,y:126,w:1546,h:646}:{x:0,y:0,w,h};
 ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);
 ctx.save();ctx.beginPath();ctx.rect(rect.x,rect.y,rect.w,rect.h);ctx.clip();
 ctx.translate(rect.x,rect.y);
 ctx.fillStyle="#eaf3f7";ctx.fillRect(0,0,rect.w,rect.h);
 drawRaster(ctx,bounds,rect.w,rect.h,record,metric);
 ctx.strokeStyle="rgba(65,87,106,.09)";ctx.lineWidth=.6;
 for(let lon=-180;lon<=180;lon+=20){
  const [x]=project(lon,0,bounds,rect.w,rect.h);
  ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,rect.h);ctx.stroke();
 }
 for(let lat=-60;lat<=80;lat+=20){
  const [,y]=project(0,lat,bounds,rect.w,rect.h);
  ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(rect.w,y);ctx.stroke();
 }
 coastlines(ctx,bounds,rect.w,rect.h);
 ctx.restore();
 const spec=maps[metric];
 const title=(broadcast?"ACE · ":"")+spec.label+" · "+record.year+(record.provisional?" (vorläufig)":"");
 const subtitle=(region==="atl"?"Nordatlantik":"Weltweit")+" · Referenz 1991–2020 · "+(record.provisional?"bis "+record.through:"Kalenderjahr");
 if(broadcast){
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,w,119);
  ctx.fillStyle="#162e46";ctx.font="bold 45px Arial";ctx.fillText(title,42,61);
  ctx.fillStyle="#536576";ctx.font="24px Arial";ctx.fillText(subtitle,43,100);
  ctx.fillStyle="#ffffff";ctx.fillRect(0,783,w,117);
  ctx.fillStyle="#263b50";ctx.font="19px Arial";
  ctx.fillText("NOAA IBTrACS · "+index.resolution_deg+"°-Raster · Glättung "+index.kernel_sigma_deg+"°",42,825);
  ctx.font="17px Arial";ctx.fillStyle="#647486";
  ctx.fillText("ACE-Näherung aus 6-stündlichen Windwerten (USA_WIND), keine statistische Signifikanz",42,859);
 }else{
  const titleW=region==="atl"?690:840;
  ctx.fillStyle="rgba(255,255,255,.94)";ctx.fillRect(11,8,titleW,72);
  ctx.fillStyle="#162e46";ctx.font="bold 23px Arial";ctx.fillText(title,20,35);
  ctx.fillStyle="#536576";ctx.font="16px Arial";ctx.fillText(subtitle,20,63);
  ctx.fillStyle="rgba(255,255,255,.92)";ctx.fillRect(12,h-43,660,32);
  ctx.fillStyle="#314b62";ctx.font="13px Arial";
  ctx.fillText("NOAA IBTrACS · "+index.resolution_deg+"°-Raster · "+spec.unit+" · Glättung "+index.kernel_sigma_deg+"°",20,h-22);
 }
 const lx=broadcast?940:w-375,ly=broadcast?810:18,len=broadcast?575:315;
 if(!broadcast){ctx.fillStyle="rgba(255,255,255,.94)";ctx.fillRect(lx-12,ly-9,len+27,70);}
 const gradient=ctx.createLinearGradient(lx,0,lx+len,0);
 spec.points.forEach((v,i)=>gradient.addColorStop((v-spec.points[0])/(spec.points.at(-1)-spec.points[0]),colors[i]));
 ctx.fillStyle=gradient;ctx.fillRect(lx,ly,len,19);
 ctx.strokeStyle="#788a98";ctx.lineWidth=.6;ctx.strokeRect(lx,ly,len,19);
 ctx.fillStyle="#24394f";ctx.font=(broadcast?"17px":"12px")+" Arial";
 ctx.textAlign="left";ctx.fillText(spec.min,lx,ly+38);
 ctx.textAlign="center";
 const centerValue=metric==="pct"?100:0;
 ctx.fillText(spec.mid,lx+len*(centerValue-spec.points[0])/(spec.points.at(-1)-spec.points[0]),ly+38);
 ctx.textAlign="right";ctx.fillText(spec.max,lx+len,ly+38);ctx.textAlign="left";
 if(broadcast){ctx.font="17px Arial";ctx.fillStyle="#667587";ctx.fillText(spec.unit,lx,ly+67);}
}
async function refresh(){
 const year=$("aceMapYear").value;
 const metric=selectedMetric(),layout=selectedLayout();
 $("aceMapStatus").textContent="Lade ACE-Kartenarchiv für "+year+" …";
 try{
  if(!cache.has(year)){
   const r=await fetch("ace/spatial/"+year+".json",{cache:"no-store"});
   if(!r.ok)throw Error("HTTP "+r.status);
   const d=await r.json();if(!d.ready)throw Error("Jahr noch nicht bereit");
   cache.set(year,d);
  }
  const next=cache.get(year);
  if(!Array.isArray(next[metric])){
   $("aceMapStatus").textContent="Der Parameter „"+maps[metric].label+"“ wird derzeit für alle Archivjahre neu berechnet. Bis dahin ist die σ-Karte verfügbar.";
   return;
  }
  current=next;
  paint($("aceMapCanvas"),$("aceMapRegion").value,current,1.6,layout,metric);
  $("aceMapStatus").textContent=(current.provisional?"Vorläufige Daten bis "+current.through:"Historisches Kalenderjahr "+year)
    +" · "+maps[metric].label+" · "+index.resolution_deg+"°-Raster · Referenz 1991–2020"
    +(metric==="pct"?" · Bereiche mit sehr kleinem Klimamittel maskiert.":"")
    +" · Keine statistische Signifikanzanalyse.";
 }catch(e){$("aceMapStatus").textContent="Karte nicht verfügbar: "+e.message;}
}
function exportMap(ext){
 const year=$("aceMapYear").value,metric=selectedMetric(),layout=selectedLayout();
 const data=cache.get(year);
 if(!data||!Array.isArray(data[metric])){
  $("aceMapStatus").textContent="Dieser Kartenparameter steht im Archiv noch nicht zur Verfügung.";return;
 }
 const region=$("aceMapRegion").value;
 const filename="ACE_"+metric+"_"+region+"_"+year+"_"+(layout==="broadcast"?"16zu9":"Standard");
 const high=document.createElement("canvas");
 // True 3840×2160 for the broadcast template; standard at 2800/3200px.
 const factor=layout==="broadcast"?2.4:region==="atl"?2800/1050:3200/1250;
 try{paint(high,region,data,factor,layout,metric);}catch(e){$("aceMapStatus").textContent=e.message;return;}
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
  pdf.addImage(high.toDataURL("image/png"),"PNG",10,10,high.width*scale,high.height*scale);
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
   const atlas=await fetch("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json");
   if(atlas.ok)coast=await atlas.json();
   else console.warn("ACE country borders HTTP",atlas.status);
  }catch(e){console.warn("ACE coastline unavailable",e);}
  select.addEventListener("change",refresh);
  $("aceMapRegion").addEventListener("change",refresh);
  $("aceMapMetric").addEventListener("change",refresh);
  $("aceMapLayout").addEventListener("change",refresh);
  document.querySelectorAll("[data-ace-map-download]").forEach(b=>b.addEventListener("click",()=>exportMap(b.dataset.aceMapDownload)));
  await refresh();
  if(!coast||!window.topojson) $("aceMapStatus").textContent+=" · Hinweis: Ländergrenzen konnten nicht geladen werden.";
 }catch(e){$("aceMapStatus").textContent="ACE-Kartenarchiv wird noch aufgebaut: "+e.message;}
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();