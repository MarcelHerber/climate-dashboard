(()=>{"use strict";
const $=id=>document.getElementById(id);
let index=null,coast=null,current=null;
const cache=new Map();
const colors=["#163b85","#3675ba","#78acd6","#dae8f2","#ffffff","#f7d6c0","#ed9b79","#cc5a48","#941c28"];
function color(v){if(v===null||!Number.isFinite(v))return null;
 return colors[Math.max(0,Math.min(8,Math.floor((Math.max(-2,Math.min(2,v))+2)/4*9)))];}
function project(lon,lat,bounds,w,h){return [(lon-bounds[0])/(bounds[1]-bounds[0])*w,(bounds[3]-lat)/(bounds[3]-bounds[2])*h];}
function coastlines(ctx,bounds,w,h){
 if(!coast||!window.topojson)return;
 const feature=window.topojson.feature(coast,coast.objects.land);
 ctx.fillStyle="#ddd7ca";ctx.strokeStyle="#343f4b";ctx.lineWidth=.6;
 const polys=feature.geometry.type==="MultiPolygon"?feature.geometry.coordinates:feature.geometry.coordinates.map(x=>[x]);
 for(const poly of polys){ctx.beginPath();for(const ring of poly){let first=true;
  for(const [lon,lat] of ring){const [x,y]=project(lon,lat,bounds,w,h);if(first){ctx.moveTo(x,y);first=false}else ctx.lineTo(x,y);}
  ctx.closePath();}ctx.fill("evenodd");ctx.stroke();}
}
function paint(canvas,region,record){
 const ratio=2,w=region==="atl"?1050:1250,h=region==="atl"?660:660;
 canvas.width=w*ratio;canvas.height=h*ratio;
 const ctx=canvas.getContext("2d");ctx.scale(ratio,ratio);
 const bounds=region==="atl"?[-115,25,-5,65]:[-180,180,-60,60];
 ctx.fillStyle="#f0f7fa";ctx.fillRect(0,0,w,h);
 const lons=index.longitudes,lats=index.latitudes;
 const dx=lons[1]-lons[0],dy=lats[1]-lats[0];
 const values=record.z;
 for(let j=0;j<lats.length;j++)for(let i=0;i<lons.length;i++){
  const val=values[j]?.[i],fill=color(val);
  if(!fill)continue;
  const west=lons[i]-dx/2,east=lons[i]+dx/2, north=lats[j]+dy/2,south=lats[j]-dy/2;
  if(east<bounds[0]||west>bounds[1]||north<bounds[2]||south>bounds[3])continue;
  const [x,y]=project(west,north,bounds,w,h);
  ctx.fillStyle=fill;ctx.fillRect(x,y,(east-west)/(bounds[1]-bounds[0])*w+1,dy/(bounds[3]-bounds[2])*h+1);
 }
 coastlines(ctx,bounds,w,h);
 ctx.strokeStyle="rgba(70,94,117,.23)";ctx.lineWidth=.5;
 for(let lon=-180;lon<=180;lon+=20){const [x]=project(lon,0,bounds,w,h);ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
 for(let lat=-60;lat<=80;lat+=20){const [,y]=project(0,lat,bounds,w,h);ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
 ctx.fillStyle="#1c3049";ctx.font="bold 23px Arial";ctx.fillText("Räumliche ACE-Anomalie · "+record.year+(record.provisional?" (vorläufig)":""),20,34);
 ctx.font="17px Arial";ctx.fillText((region==="atl"?"Nordatlantik":"Weltweit")+" · 1991–2020 · "+(record.provisional?"bis "+record.through:"Gesamtjahr"),20,60);
 ctx.font="13px Arial";ctx.fillText("NOAA IBTrACS · geglättete räumliche ACE-Verteilung · σ",20,h-20);
 const lx=w-380,ly=20;for(let i=0;i<colors.length;i++){
  ctx.fillStyle=colors[i];ctx.fillRect(lx+i*37,ly,37,15);
 }
 ctx.fillStyle="#263749";ctx.font="12px Arial";ctx.fillText("−2σ",lx,ly+31);ctx.fillText("0",lx+164,ly+31);ctx.fillText("+2σ",lx+312,ly+31);
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
  $("aceMapStatus").textContent=(current.provisional?"Vorläufige Daten bis "+current.through:"Historischer Jahreszeitraum "+year)+" · Räumliche Standardabweichung gegenüber 1991–2020. Keine Signifikanzanalyse.";
 }catch(e){$("aceMapStatus").textContent="Karte nicht verfügbar: "+e.message;}
}
function exportMap(ext){
 if(!current)return;
 const canvas=$("aceMapCanvas"),name="ACE_Karte_"+$("aceMapRegion").value+"_"+current.year;
 if(ext==="png"){const a=document.createElement("a");a.download=name+".png";a.href=canvas.toDataURL("image/png");a.click();}
 else if(ext==="pdf"){if(!window.jspdf?.jsPDF){$("aceMapStatus").textContent="PDF-Bibliothek nicht geladen.";return;}
  const pdf=new window.jspdf.jsPDF({orientation:"landscape",unit:"mm",format:"a4"});
  const img=canvas.toDataURL("image/png");
  const targetW=277,targetH=canvas.height/canvas.width*277;
  pdf.addImage(img,"PNG",10,10,targetW,Math.min(190,targetH));pdf.save(name+".pdf");
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
   const atlas=await fetch("https://cdn.jsdelivr.net/npm/world-atlas@2/land-110m.json");
   if(atlas.ok)coast=await atlas.json();
  }catch(e){console.warn("ACE coastline unavailable",e);}
  select.addEventListener("change",refresh);
  $("aceMapRegion").addEventListener("change",refresh);
  document.querySelectorAll("[data-ace-map-download]").forEach(b=>b.addEventListener("click",()=>exportMap(b.dataset.aceMapDownload)));
  await refresh();
 }catch(e){$("aceMapStatus").textContent="ACE-Kartenarchiv wird noch aufgebaut: "+e.message;}
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();