/* Satellite geospatial overlays.
 * Reuse the repository's Natural Earth 1:50m border lines, public domain.
 * WMS maps EPSG:4326: lon increases left-to-right; lat increases bottom-to-top.
 * Full disk uses AUTO:97004 and MUST NOT display these lat/lon paths.
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
let lines=null,failed=false,busy=false;
function show(message){hint.textContent=message;}
function isGeographic(){return source.value==="mtgi1"&&Boolean(BOXES[region.value]);}
function coords(lon,lat,bbox){
 return [(lon-bbox[0])*1000/(bbox[2]-bbox[0]),(bbox[3]-lat)*1000/(bbox[3]-bbox[1])];
}
function update(){
 const r=BOXES[region.value];
 stack.hidden=source.value!=="mtgi1";
 stack.style.aspectRatio=r?r[4]+"/"+r[5]:"1 / 1";
 stack.style.maxWidth=r?r[4]+"px":"1400px";
 const supported=isGeographic();
 borderToggle.disabled=!supported;
 cityToggle.disabled=!supported;
 // SVG elements do not expose the HTMLElement.hidden reflection reliably.
 // Toggle the real DOM attribute so CSS #satBordersSvg[hidden] works.
 borders.toggleAttribute("hidden",!supported||!borderToggle.checked||!lines);
 cities.hidden=!supported||!cityToggle.checked;
 borders.replaceChildren();
 cities.replaceChildren();
 if(!supported){
  show(source.value!=="mtgi1"?"MTG-I2-Erstbilder: keine Kartenüberlagerung.":"Erdscheibe: geostationäre Projektion; geografische Grenzen erst nach gesonderter Projektion.");
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
  if(pieces.length){
   const path=document.createElementNS("http://www.w3.org/2000/svg","path");
   path.setAttribute("d",pieces.join(" "));
   path.setAttribute("fill","none");
   path.setAttribute("stroke","currentColor");
   path.setAttribute("vector-effect","non-scaling-stroke");
   path.setAttribute("stroke-width","1");
   path.setAttribute("stroke-linejoin","round");
   borders.appendChild(path);
  }
 }
 if(cityToggle.checked){
  for(const [name,lon,lat] of PLACES){
   if(lon<r[0]+.7||lon>r[2]-.7||lat<r[1]+.5||lat>r[3]-.5)continue;
   const node=document.createElement("span");
   node.className="sat-city-label";
   node.textContent=name;
   node.style.left=((lon-r[0])/(r[2]-r[0])*100).toFixed(3)+"%";
   node.style.top=((r[3]-lat)/(r[3]-r[1])*100).toFixed(3)+"%";
   cities.appendChild(node);
  }
 }
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
window.SatelliteOverlay={update};
})();