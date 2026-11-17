/* Satellite geospatial overlays.
 * Reuse the repository's Natural Earth 1:50m border lines, public domain.
 * WMS maps EPSG:4326: lon increases left-to-right; lat increases bottom-to-top.
 * Full disc/north use the separate, global Natural Earth dataset and the
 * WGS84 geostationary transformation in satellite_projection.js.
 */
(() => {
"use strict";
const id=name=>document.getElementById(name);
const stack=id("satImageStack"),borders=id("satBordersSvg"),cities=id("satCitiesLayer");
const borderToggle=id("satShowBorders"),cityToggle=id("satShowCities"),hint=id("satOverlayHint");
const region=id("satRegion"),source=id("satSource");
const BOXES={
 europe:[-27,24,49,73,1300,850],atlantic:[-70,15,35,75,1400,850],
 southwest:[-37,24,19,53,1200,620],central:[-2,43,25,58,1300,780],
 germany:[5,47,16,56,1140,950]
};
const PLACES=[
 ["Ponta Delgada",-25.67,37.74],["Funchal",-16.92,32.65],["Las Palmas",-15.43,28.12],
 ["Lissabon",-9.14,38.72],["Madrid",-3.70,40.42],["Paris",2.35,48.86],
 ["London",-0.13,51.51],["Dublin",-6.26,53.35],["Reykjavík",-21.94,64.15],
 ["Nuuk",-51.74,64.18],["St. John's",-52.71,47.56],["Berlin",13.41,52.52],
 ["Frankfurt",8.68,50.11],["Oslo",10.75,59.91],["Rom",12.50,41.90],
 ["Casablanca",-7.59,33.57],["Brest",-4.49,48.39],["Tromsø",18.96,69.65]
];
const DISK_PLACES=[
 ["Reykjavík",-21.94,64.15],["Nuuk",-51.74,64.18],["St. John's",-52.71,47.56],
 ["London",-0.13,51.51],["Frankfurt",8.68,50.11],["Madrid",-3.70,40.42],
 ["Oslo",10.75,59.91],["Moskau",37.62,55.75],["Ankara",32.86,39.93],
 ["Casablanca",-7.59,33.57],["Ponta Delgada",-25.67,37.74],["Kairo",31.24,30.04],
 ["Riad",46.68,24.71],["Dakar",-17.45,14.69],["Lagos",3.38,6.52],
 ["Khartum",32.56,15.50],["Nairobi",36.82,-1.29],["Kinshasa",15.27,-4.32],
 ["Johannesburg",28.05,-26.20],["Kapstadt",18.42,-33.93],["Luanda",13.23,-8.84],
 ["Maputo",32.59,-25.97],["Recife",-34.88,-8.05],["Rio de Janeiro",-43.17,-22.91],
 ["Buenos Aires",-58.38,-34.60],["Cayenne",-52.33,4.94]
];
let lines=null,failed=false,busy=false;
let diskLines=null,diskFailed=false,diskBusy=false;
const diskPathCache=new Map();
function show(message){hint.textContent=message;}
function isGeographic(){return source.value==="mtgi1"&&Boolean(BOXES[region.value]);}
function isDisk(place){return Boolean(window.SatelliteProjection?.isDisk(place));}
function diskPaths(place){
 if(!diskLines)return [];
 if(!diskPathCache.has(place)){
  const paths=diskLines.flatMap(line=>window.SatelliteProjection.paths(place,line,1000,1000));
  diskPathCache.set(place,paths);
 }
 return diskPathCache.get(place);
}
function diskCityAnchors(place){
 const {w,h}=window.SatelliteProjection.regions[place],out=[];
 for(const [name,lon,lat] of DISK_PLACES){
  const p=window.SatelliteProjection.project(place,lon,lat,w,h);
  // Keep enough interior space for the complete city label and don't pile
  // labels up around the northern limb, where high-latitude cities converge.
  if(!p||p[0]<40||p[0]>w-40||p[1]<12||p[1]>h-12||out.some(m=>Math.abs(m.p[0]-p[0])<85&&Math.abs(m.p[1]-p[1])<28))continue;
  out.push({name,lon,lat,p});
 }
 return out.map(({name,lon,lat})=>({name,lon,lat}));
}
function appendPath(pieces){
 if(!pieces.length)return;
 const path=document.createElementNS("http://www.w3.org/2000/svg","path");
 path.setAttribute("d",pieces.join(" "));
 path.setAttribute("fill","none");path.setAttribute("stroke","currentColor");
 path.setAttribute("vector-effect","non-scaling-stroke");path.setAttribute("stroke-width","1");
 path.setAttribute("stroke-linejoin","round");borders.appendChild(path);
}
function appendCity(name,x,y){
 const node=document.createElement("span");
 node.className="sat-city-label";node.textContent=name;
 node.style.left=x.toFixed(3)+"%";node.style.top=y.toFixed(3)+"%";
 cities.appendChild(node);
}
function coords(lon,lat,bbox){
 return [(lon-bbox[0])*1000/(bbox[2]-bbox[0]),(bbox[3]-lat)*1000/(bbox[3]-bbox[1])];
}
function update(){
 const r=BOXES[region.value];
 const disc=source.value==="mtgi1"&&isDisk(region.value),diskSpec=disc?window.SatelliteProjection.regions[region.value]:null;
 stack.hidden=source.value!=="mtgi1";
 stack.style.aspectRatio=r?r[4]+"/"+r[5]:diskSpec?diskSpec.w+"/"+diskSpec.h:"1 / 1";
 stack.style.maxWidth=r?r[4]+"px":diskSpec?diskSpec.w+"px":"1400px";
 const supported=isGeographic()||disc;
 borderToggle.disabled=!supported;
 cityToggle.disabled=!supported;
 // SVG elements do not expose the HTMLElement.hidden reflection reliably.
 // Toggle the real DOM attribute so CSS #satBordersSvg[hidden] works.
 borders.toggleAttribute("hidden",!supported||!borderToggle.checked||!(disc?diskLines:lines));
 cities.hidden=!supported||!cityToggle.checked;
 borders.replaceChildren();
 cities.replaceChildren();
 if(!supported){
  show(source.value!=="mtgi1"?"MTG-I2-Erstbilder: keine Kartenüberlagerung.":"Erdscheibe: geostationäre Projektion; geografische Grenzen erst nach gesonderter Projektion.");
  return;
 }
 if(disc){
  if(diskFailed)show("Grenzdaten für die geostationäre Ansicht momentan nicht geladen. Satellitenbilder bleiben nutzbar.");
  else if(!diskLines){show("Lade globale 50m-Natural-Earth-Grenzen …");loadDiskBorders();}
  else show("Natural Earth 1:50m · gesamte Erdscheibe · geostationär projiziert (WGS84)");
  if(diskLines&&borderToggle.checked)appendPath(diskPaths(region.value).map(line=>line.map(([x,y],i)=>(i?"L":"M")+x.toFixed(2)+" "+y.toFixed(2)).join("")));
  if(cityToggle.checked)for(const {name,lon,lat} of diskCityAnchors(region.value)){
   const [x,y]=window.SatelliteProjection.project(region.value,lon,lat,100,100);appendCity(name,x,y);
  }
  return;
 }
 if(failed){show("Grenzdaten momentan nicht geladen. Satellitenbilder bleiben nutzbar.");}
 else if(!lines){show("Lade lokale 50m-Grenzen aus Natural Earth …");}
 else {
  const coverage="Natural Earth 1:50m, -78° bis 65° Länge und 25° bis 85° Nord";
  show(coverage+(r[1]<25?" · südlich 25°N keine Grenzlinien":"")+" · vereinfachte Grenzen");
 }
 if(!r)return;
 if(lines&&borderToggle.checked){
  const pieces=[];
  for(const line of lines){
   if(!Array.isArray(line)||line.length<2)continue;
   let minX=181,maxX=-181,minY=91,maxY=-91;
   for(const p of line){if(!Array.isArray(p)||p.length!==2)continue;minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);}
   if(maxX<r[0]||minX>r[2]||maxY<r[1]||minY>r[3])continue;
   let valid=0,part="";
   for(const p of line){
    if(!Number.isFinite(p[0])||!Number.isFinite(p[1]))continue;
    const [x,y]=coords(p[0],p[1],r);
    part+=(valid++?"L":"M")+x.toFixed(2)+" "+y.toFixed(2);
   }
   if(valid>=2)pieces.push(part);
  }
  appendPath(pieces);
 }
 if(cityToggle.checked){
  for(const [name,lon,lat] of PLACES){
   if(lon<r[0]+.7||lon>r[2]-.7||lat<r[1]+.5||lat>r[3]-.5)continue;
   appendCity(name,(lon-r[0])/(r[2]-r[0])*100,(r[3]-lat)/(r[3]-r[1])*100);
  }
 }
}
async function loadDiskBorders(){
 if(diskLines||diskFailed||diskBusy)return;
 diskBusy=true;
 try{
  const response=await fetch("./data/satellite_borders_50m.json",{cache:"force-cache"});
  if(!response.ok)throw Error("HTTP "+response.status);
  const doc=await response.json();
  if(doc.schema_version!==1||!Array.isArray(doc.lines)||doc.lines.length<1000||!String(doc.source||"").includes("Natural Earth")||
   !Array.isArray(doc.coverage_bbox)||doc.coverage_bbox[0]!==-180||doc.coverage_bbox[1]!==-90||doc.coverage_bbox[2]!==180||doc.coverage_bbox[3]!==90)throw Error("Unerwartetes globales Grenzdatenformat");
  diskLines=doc.lines;
 }catch(error){diskFailed=true;console.warn("Satelliten-Grenzen weltweit:",error);}
 finally{diskBusy=false;update();}
}
async function loadBorders(){
 if(lines||failed||busy)return;
 busy=true;
 try{
  const response=await fetch("./data/blocking/borders_50m.json",{cache:"force-cache"});
  if(!response.ok)throw Error("HTTP "+response.status);
  const doc=await response.json();
  if(doc.schema_version!==1||!Array.isArray(doc.lines)||doc.lines.length<300||
     !Array.isArray(doc.coverage_bbox)||doc.coverage_bbox[0]>-70||
     !String(doc.source||"").includes("Natural Earth"))throw Error("Unerwartetes Grenzdatenformat");
  lines=doc.lines;
 }catch(error){failed=true;console.warn("Satelliten-Grenzen:",error);}
 finally{busy=false;update();}
}
for(const el of [region,source,borderToggle,cityToggle])el.addEventListener("change",update);
update();
loadBorders();
/* Paint the exact same source geometry for lossless HD/4K export.
 * Canvas display is EPSG:4326 and uses the same normalized lon/lat transform
 * as the interactive SVG. Missing border data are reported, not invented. */
function paintBorders(ctx,place,{x=0,y=0,width,height}){
 const bbox=BOXES[place];
 const disc=isDisk(place);
 if(disc?!diskLines:(!bbox||!lines))throw Error("Für den HD-Export fehlen gültige Natural-Earth-Grenzen.");
 const [west,south,east,north]=bbox||[];
 const px=(lon,lat)=>[x+(lon-west)/(east-west)*width,y+(north-lat)/(north-south)*height];
 ctx.save();ctx.beginPath();ctx.rect(x,y,width,height);ctx.clip();
 ctx.lineCap="round";ctx.lineJoin="round";
 ctx.lineWidth=Math.max(1.2,width/1150);
 ctx.strokeStyle="#f3f9ff";ctx.shadowColor="#071622";
 ctx.shadowBlur=Math.max(1.5,width/1300);
 let rendered=0;
 if(disc){
  for(const line of diskPaths(place)){
   ctx.beginPath();
   for(let i=0;i<line.length;i++){
    const [a,b]=line[i],px=x+a/1000*width,py=y+b/1000*height;
    if(i===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);
   }
   ctx.stroke();rendered++;
  }
  ctx.restore();
  if(!rendered)throw Error("Keine Grenzgeometrie für den gewählten Ausschnitt.");
  return rendered;
 }
 for(const line of lines){
  if(!Array.isArray(line)||line.length<2)continue;
  let minX=181,maxX=-181,minY=91,maxY=-91;
  for(const p of line){
   if(!Array.isArray(p)||p.length!==2)continue;
   minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
   minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
  }
  if(maxX<west||minX>east||maxY<south||minY>north)continue;
  ctx.beginPath();let count=0;
  for(const p of line){
   if(!Array.isArray(p)||!Number.isFinite(p[0])||!Number.isFinite(p[1]))continue;
   const [a,b]=px(p[0],p[1]);
   if(count++===0)ctx.moveTo(a,b);else ctx.lineTo(a,b);
  }
  if(count>=2){ctx.stroke();rendered++;}
 }
 ctx.restore();
 if(!rendered)throw Error("Keine Grenzgeometrie für den gewählten Ausschnitt.");
 return rendered;
}
function paintCities(ctx,place,{x=0,y=0,width,height}){
 const bbox=BOXES[place];
 const disc=isDisk(place);
 if(!bbox&&!disc)throw Error("Dieser Ausschnitt besitzt keine geografischen Städtenamen.");
 const size=Math.max(11,Math.round(width/110));
 ctx.save();ctx.beginPath();ctx.rect(x,y,width,height);ctx.clip();
 ctx.lineJoin="round";ctx.textAlign="left";ctx.textBaseline="middle";
 ctx.font="700 "+size+"px Arial,sans-serif";
 let count=0;
 for(const {name,lon,lat} of cityAnchors(place)){
  let px,py;
  if(disc){const p=window.SatelliteProjection.project(place,lon,lat,width,height);if(!p)continue;px=x+p[0];py=y+p[1];}
  else {const [west,south,east,north]=bbox;px=x+(lon-west)/(east-west)*width;py=y+(north-lat)/(north-south)*height;}
  ctx.fillStyle="#ffffff";ctx.strokeStyle="#102038";
  ctx.lineWidth=Math.max(2.5,size*.3);
  const maxW=Math.min(width*.27,Math.max(54,width-x-px-6));
  ctx.beginPath();ctx.arc(px,py,Math.max(2.5,size*.20),0,Math.PI*2);
  ctx.stroke();ctx.fill();
  ctx.strokeText(name,px+size*.5,py-size*.55,maxW);
  ctx.fillText(name,px+size*.5,py-size*.55,maxW);
  count++;
 }
 ctx.restore();
 return count;
}
function cityAnchors(place){
 if(isDisk(place))return diskCityAnchors(place);
 const bbox=BOXES[place];if(!bbox)return [];
 return PLACES.filter(([,lon,lat])=>lon>=bbox[0]+.7&&lon<=bbox[2]-.7&&
  lat>=bbox[1]+.5&&lat<=bbox[3]-.5)
  .map(([name,lon,lat])=>({name,lon,lat}));
}
window.SatelliteOverlay={update,paintBorders,paintCities,cityAnchors};
})();
