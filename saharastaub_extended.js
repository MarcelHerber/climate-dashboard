/* Class-faithful local ICON-ART forecast curves, no invented real-valued concentrations. */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const city=$("dustCity"),lat=$("dustLat"),lon=$("dustLon"),chart=$("dustSeries"),note=$("dustSeriesStatus");
if(!city||!chart)return;
function selected(){
 const latitude=Number(lat.value),longitude=Number(lon.value);
 if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||latitude<25||latitude>=74||longitude< -28||longitude>=60)return null;
 return {latitude,longitude};
}
function interval(code,breaks){
 if(code===255)return "keine Daten";
 if(code===0)return "< "+breaks[0];
 if(code>=breaks.length)return "≥ "+breaks.at(-1);
 return breaks[code-1]+" – < "+breaks[code];
}
function redraw(){
 const api=window.SaharaDustAPI,forecast=api?.getForecast();
 const ctx=chart.getContext("2d"),w=chart.width,h=chart.height;
 ctx.fillStyle="#fff";ctx.fillRect(0,0,w,h);
 if(!forecast){note.textContent="Noch keine geprüften ICON-ART-Prognosefelder vorhanden.";return;}
 const coord=selected();
 if(!coord){note.textContent="Koordinaten außerhalb des verfügbaren Modellrasters (25–74° N, 28° W–60° E).";return;}
 const grid=forecast.grid,key=$("dustParameter").value,meta=api.params[key];
 if(!meta){note.textContent="Unbekannter Parameter.";return;}
 const col=Math.floor((coord.longitude-grid.lon_min)/grid.step),row=Math.floor((coord.latitude-grid.lat_min)/grid.step);
 if(col<0||row<0||col>=grid.cols||row>=grid.rows){note.textContent="Ort außerhalb des Modellrasters.";return;}
 const pixel=row*grid.cols+col;
 const points=forecast.frames.map(frame=>{
   if(typeof frame[key]!=="string")return {hour:frame.hour,code:255};
   try {return {hour:frame.hour,code:api.unpack(frame[key],grid.rows*grid.cols)[pixel]};}
   catch(_){return {hour:frame.hour,code:255};}
 });
 const valid=points.filter(p=>p.code!==255);
 if(!valid.length){note.textContent="An diesem Ort sind für den Parameter keine verifizierten Vorhersagedaten vorhanden.";return;}
 const margin={left:76,right:28,top:30,bottom:62},cw=w-margin.left-margin.right,ch=h-margin.top-margin.bottom;
 const maxHour=Math.max(72,points.at(-1).hour);
 const x=t=>margin.left+cw*t/maxHour, y=cl=>margin.top+ch*(1-cl/9);
 ctx.strokeStyle="#d7e0e8";ctx.lineWidth=1;ctx.fillStyle="#3c546b";ctx.font="15px system-ui";
 for(let tick=0;tick<=9;tick++){const yy=y(tick);ctx.beginPath();ctx.moveTo(margin.left,yy);ctx.lineTo(margin.left+cw,yy);ctx.stroke();ctx.fillText(String(tick),margin.left-29,yy+5);}
 for(let hour=0;hour<=maxHour;hour+=12){const xx=x(hour);ctx.fillText("+"+hour+" h",xx-17,h-margin.bottom+24);}
 ctx.fillStyle="#284158";ctx.font="bold 17px system-ui";ctx.fillText(meta.name+" · Klassenverlauf · "+meta.unit,margin.left,20);
 ctx.fillStyle="#476179";ctx.font="14px system-ui";ctx.fillText("Feste Farbklasse (0–9) · kein exakter Konzentrationswert",margin.left,h-8);
 ctx.strokeStyle="#bd572b";ctx.lineWidth=3;ctx.beginPath();let connected=false;
 for(const point of points){if(point.code===255){connected=false;continue;}
   if(!connected){ctx.moveTo(x(point.hour),y(point.code));connected=true;}else ctx.lineTo(x(point.hour),y(point.code));
   const next=points[points.indexOf(point)+1];if(!next||next.code===255){ctx.stroke();ctx.beginPath();connected=false;}}
 ctx.fillStyle="#bd572b";
 for(const point of valid){ctx.beginPath();ctx.arc(x(point.hour),y(point.code),3.5,0,Math.PI*2);ctx.fill();}
 const peak=Math.max(...valid.map(p=>p.code));
 note.textContent="Ort: "+coord.latitude.toFixed(2)+"° N, "+coord.longitude.toFixed(2)+"° E · "+valid.length+" gültige Termine · höchste erreichte Klasse "+peak+" ("+interval(peak,meta.breaks)+" "+meta.unit+"). Die Klassen beziehen sich auf 0,2°-Zellmittel und sind keine genauen Messwerte.";
}
city.addEventListener("change",()=>{
 if(city.value!=="custom"){const [a,b]=city.value.split(",").map(Number);lat.value=String(a);lon.value=String(b);}
 redraw();
});
for(const node of [lat,lon])node.addEventListener("change",()=>{city.value="custom";redraw();});
document.addEventListener("sahara-data-ready",redraw);
document.addEventListener("sahara-view-change",redraw);
const satellite=$("dustEumetWms"),satelliteStatus=$("dustEumetStatus");
if(satellite){
 // WMS 1.1.1 uses lon/lat for EPSG:4326. Omit TIME rather than asserting a false timestamp.
 const params=new URLSearchParams({
  service:"WMS",version:"1.1.1",request:"GetMap",
  layers:"mtg_fd:rgb_dust",styles:"",format:"image/png",transparent:"false",
  srs:"EPSG:4326",bbox:"-28,25,60,74",width:"1000",height:"550"
 });
 satellite.addEventListener("load",()=>{satelliteStatus.textContent="EUMETSAT Dust-RGB-WMS geladen. Der serverseitige Bildzeitpunkt ist nicht verifiziert; kein synchroner ICON-ART-Vergleich.";});
 satellite.addEventListener("error",()=>{satellite.hidden=true;satelliteStatus.textContent="Die WMS-Vorschau konnte nicht geladen werden. Der offizielle EUMETView-Link darunter bleibt verfügbar.";});
 satellite.src="https://view.eumetsat.int/geoserver/wms?"+params.toString();
}
redraw();
})();
