/* HYRAS regional workshop — native raster, projected boundaries and DWD observations.
 * Boundaries: deutschlandGeoJSON (GIS-DATA, public-domain archive); not a current BKG product.
 * Numerical data are never resampled to invent meteorological resolution. */
(function(root){
"use strict";
const states=["Deutschland","Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"];
const geoUrl="https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/1_sehr_hoch.geo.json";
const stationBase="europe_stations/dwd_daily_map/";
const $=id=>document.getElementById(id);
const cache=new Map();
let source=null,revision=0,display=null,stationRequest=null,projectedCache=null;
function get(url,kind="json"){
 const key=kind+":"+url;
 if(!cache.has(key)){
  const p=fetch(url).then(async r=>{
   if(!r.ok)throw Error("HTTP "+r.status+" ("+url.split("/").pop()+")");
   if(kind==="json")return r.json();
   const b=new Uint8Array(await r.arrayBuffer());
   if(b[0]===31&&b[1]===139){
    if(!root.DecompressionStream)throw Error("Browser unterstützt keine gzip-Daten");
    return new Response(new Blob([b]).stream().pipeThrough(new DecompressionStream("gzip"))).json();
   }
   return JSON.parse(new TextDecoder().decode(b));
  }).catch(e=>{cache.delete(key);throw e});
  cache.set(key,p);
 }
 return cache.get(key);
}
function bracket(a,v){
 if(v<=a[0])return [0,1,(v-a[0])/(a[1]-a[0])];
 const n=a.length-1;
 if(v>=a[n])return [n-1,n,(v-a[n-1])/(a[n]-a[n-1])];
 let l=0,h=n;while(h-l>1){const m=(l+h)>>1;if(a[m]<=v)l=m;else h=m}
 return [l,h,(v-a[l])/(a[h]-a[l])];
}
function coordinate(g,x,y){
 const [a,b,u]=bracket(g.x_indices,x),[c,d,v]=bracket(g.y_indices,y);
 const f=t=>(1-u)*(1-v)*t[c][a]+u*(1-v)*t[c][b]+(1-u)*v*t[d][a]+u*v*t[d][b];
 return [f(g.lon),f(g.lat)];
}
// Invert the published HYRAS grid lookup, rather than treating lon/lat as a rectangular image.
function project(g,lon,lat){
 let x=(g.width-1)/2,y=(g.height-1)/2;
 for(let n=0;n<9;n++){
  const a=coordinate(g,x,y),b=coordinate(g,x+1,y),c=coordinate(g,x,y+1);
  const dx=lon-a[0],dy=lat-a[1],p=b[0]-a[0],q=c[0]-a[0],r=b[1]-a[1],s=c[1]-a[1],det=p*s-q*r;
  if(!Number.isFinite(det)||Math.abs(det)<1e-12)return null;
  x+=(s*dx-q*dy)/det;y+=(p*dy-r*dx)/det;
  if(Math.abs(dx)+Math.abs(dy)<1e-8)break;
 }
 const v=coordinate(g,x,y);
 return Number.isFinite(x)&&Number.isFinite(y)&&Math.abs(v[0]-lon)+Math.abs(v[1]-lat)<.001?[x+.5,y+.5]:null;
}
function normalized(s){return String(s||"").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/ß/g,"ss").replace(/[^a-z]/g,"")}
function featureName(f){return f.properties?.name||f.properties?.NAME||f.properties?.GEN||""}
function polygons(f){return f.geometry?.type==="Polygon"?[f.geometry.coordinates]:f.geometry?.type==="MultiPolygon"?f.geometry.coordinates:[]}
function extent(polys,w,h){
 let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
 for(const poly of polys)for(const ring of poly)for(const p of ring){x0=Math.min(x0,p[0]);x1=Math.max(x1,p[0]);y0=Math.min(y0,p[1]);y1=Math.max(y1,p[1])}
 if(!Number.isFinite(x0))throw Error("Keine Regionsgeometrie verfügbar");
 const pad=Math.max(5,.045*Math.max(x1-x0,y1-y0));
 x0=Math.max(0,Math.floor(x0-pad));y0=Math.max(0,Math.floor(y0-pad));x1=Math.min(w,Math.ceil(x1+pad));y1=Math.min(h,Math.ceil(y1+pad));
 if(x1<=x0||y1<=y0)throw Error("Region außerhalb des Rasters");
 return {x:x0,y:y0,w:x1-x0,h:y1-y0};
}
function makePath(ctx,polys){ctx.beginPath();for(const poly of polys)for(const ring of poly){if(ring.length<3)continue;ctx.moveTo(ring[0][0],ring[0][1]);for(let i=1;i<ring.length;i++)ctx.lineTo(ring[i][0],ring[i][1]);ctx.closePath()}}
function isoDates(start,end){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(start||"")||!/^\d{4}-\d{2}-\d{2}$/.test(end||"")||start>end)return [];
 let t=Date.parse(start+"T00:00:00Z"),last=Date.parse(end+"T00:00:00Z");
 if(!Number.isFinite(t)||!Number.isFinite(last)||(last-t)/86400000>366)return [];
 const dates=[];for(;t<=last;t+=86400000)dates.push(new Date(t).toISOString().slice(0,10));return dates;
}
function accumulate(days,field){
 const sums=new Map();
 for(const payload of days){
  const seen=new Set();
  for(const row of payload.rows||[]){
   const i=Number(row[0]),v=row[field];
   if(!Number.isInteger(i)||seen.has(i)||v===null||v===undefined||!Number.isFinite(Number(v)))continue;
   seen.add(i);const a=sums.get(i)||[0,0];a[0]+=Number(v)/10;a[1]++;sums.set(i,a);
  }
 }
 return new Map([...sums].filter(([,a])=>a[1]===days.length).map(([i,a])=>[i,a[0]/a[1]]));
}
function install(){
 if($("hyrasRegionalWorkshop"))return;
 const frame=$("hyrasMapFrame"),card=frame?.closest(".hyras-map-card");if(!card)return;
 const el=document.createElement("details");el.id="hyrasRegionalWorkshop";el.className="hyras-map-card";
 el.innerHTML='<summary style="cursor:pointer;font-weight:800;font-size:18px">Regionale HYRAS-Karten · HD / Stationswerte · Vektor-PDF</summary>'+
 '<p class="note">Eigenständige Kartenausschnitte aus der aktuell ausgewählten HYRAS-Rasterdarstellung. Keine künstliche Erhöhung der meteorologischen Auflösung.</p>'+
 '<div class="hyras-reg-controls">'+
 '<label>Region <select id="hyrasRegRegion">'+states.map(s=>'<option>'+s+'</option>').join("")+'</select></label>'+
 '<label>Darstellung <select id="hyrasRegRendering"><option value="strong" selected>Stark geglättet (Flächenkonturen)</option><option value="smooth">Leicht geglättet</option><option value="native">Originalraster (pixelgenau)</option></select></label>'+
 '<label>PNG-Kantenlänge <select id="hyrasRegSize"><option value="2000">2.000 px</option><option value="4000" selected>4.000 px</option><option value="8000">8.000 px</option></select></label>'+
 '<label><input id="hyrasRegStations" type="checkbox" checked> DWD-Stationen</label>'+
 '<label><input id="hyrasRegNames" type="checkbox"> Stationsnamen</label>'+
 '<label><input id="hyrasRegValues" type="checkbox" checked> Messwerte</label>'+
 '<label><input id="hyrasRegOnlyValid" type="checkbox"> Nur Stationen mit gültigem Wert</label>'+
 '<label><input id="hyrasRegNeighbors" type="checkbox"> Umgebung anzeigen</label><label><input id="hyrasRegPdfTransparent" type="checkbox" checked> PDF ohne weißen Hintergrund</label></div>'+
 '<p id="hyrasRegStatus" class="note" role="status">Zuerst eine numerische HYRAS-Karte laden.</p>'+
 '<div class="hyras-map-actions" style="margin:10px 0;display:flex;flex-wrap:wrap;gap:8px"><button type="button" class="action" id="hyrasRegPdfTop" disabled>Diese regionale Karte als PDF (Vektor) herunterladen</button><span id="hyrasRegPdfRegion" class="note"></span></div><div id="hyrasRegPreview" class="hyras-reg-preview"></div>'+
 '<p id="hyrasRegInspection" class="note" aria-live="polite"></p>'+
 '<div class="hyras-map-actions"><button type="button" class="action" id="hyrasRegPng" disabled>PNG herunterladen</button><button type="button" class="action" id="hyrasRegPdf" disabled>PDF (Vektor) herunterladen</button></div>'+
 '<p class="note">Quellen: DWD HYRAS-DE / DWD CDC Tageswerte KL; Grenzen: deutschlandGeoJSON (GIS-DATA, Archivstand 2022 oder älter). Stationswerte nur bei vollständigen Tagesdaten im gewählten Zeitraum und passender Referenz.</p>';
 const style=document.createElement("style");
 style.textContent=".hyras-reg-controls{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin:12px 0}.hyras-reg-controls label{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-size:13px}.hyras-reg-controls select{max-width:100%;padding:6px}.hyras-reg-preview{background:#fff;overflow:hidden;border-radius:7px}.hyras-reg-preview canvas{display:block;width:100%;height:auto;touch-action:pan-y}.hyras-reg-controls input{width:auto}@media(max-width:650px){.hyras-reg-controls label{max-width:100%}}";
 document.head.append(style);card.before(el);
 el.addEventListener("toggle",()=>{if(el.open)refresh()});
 for(const id of ["hyrasRegRegion","hyrasRegRendering","hyrasRegStations","hyrasRegNames","hyrasRegValues","hyrasRegOnlyValid","hyrasRegNeighbors"]){$(id).addEventListener("change",refresh)}
 $("hyrasRegPng").onclick=()=>download("png");$("hyrasRegPdf").onclick=()=>download("pdf");$("hyrasRegPdfTop").onclick=()=>download("pdf");
 const watch=new MutationObserver(()=>{if(source&&!source.owner?.isConnected){source=null;revision++;display=null;clear("Diese Ansicht besitzt derzeit kein unterstütztes numerisches Raster. Bitte eine andere HYRAS-Karte wählen.")}});
 watch.observe(frame,{childList:true,subtree:true});
}
function clear(message){
 if($("hyrasRegStatus"))$("hyrasRegStatus").textContent=message;
 if($("hyrasRegPreview"))$("hyrasRegPreview").replaceChildren();
 if($("hyrasRegInspection"))$("hyrasRegInspection").textContent="";
 for(const id of ["hyrasRegPng","hyrasRegPdf","hyrasRegPdfTop"])if($(id))$(id).disabled=true;
 if($("hyrasRegPdfRegion"))$("hyrasRegPdfRegion").textContent="";
}
function legendFrom(node){
 return Array.from(node?.querySelectorAll("span")||[]).map(e=>({label:e.textContent.trim(),color:e.querySelector("i")?.style.backgroundColor||e.querySelector("i")?.style.background})).filter(x=>x.color&&x.label);
}
async function loadGeometry(s){
 const [g,j]=await Promise.all([get(s.lookupUrl),get(geoUrl)]);
 if(g.width!==s.canvas.width||g.height!==s.canvas.height)throw Error("Georeferenz und Originalraster stimmen nicht überein.");
 if(projectedCache?.g===g&&projectedCache?.j===j)return projectedCache;
 if(!Array.isArray(j.features)||j.features.length<16)throw Error("Bundeslandgrenzen fehlen");
 const items=j.features.map(f=>({name:featureName(f),polys:polygons(f).map(poly=>poly.map(ring=>ring.map(p=>project(g,p[0],p[1])).filter(Boolean))).filter(poly=>poly[0]?.length>=3)}));
 if(states.slice(1).some(n=>!items.some(f=>normalized(f.name)===normalized(n))))throw Error("Bundesland-Namen stimmen nicht mit dem Grenzdatensatz überein.");
 projectedCache={g,j,items};return projectedCache;
}
async function stationIndex(){
 if(!stationRequest)stationRequest=get(stationBase+"index.json","json").catch(e=>{stationRequest=null;throw e});
 return stationRequest;
}
async function stationData(s,geo,region,wantValues){
 const idx=await stationIndex();
 if(!idx.ready||!Array.isArray(idx.stations)||!Array.isArray(idx.dates))throw Error("DWD-Tagesstationsarchiv nicht verfügbar.");
 let values=new Map(),note="DWD-KL-Stationsstandorte (aktuelles Stationsverzeichnis).";
 const dates=isoDates(s.start,s.end);
 const field={tmean:12,tmax:3,tmin:4}[s.parameter];
 if(wantValues&&field!==undefined&&s.metric==="anomaly"&&s.reference==="1991-2020"&&dates.length&&dates.every(d=>idx.dates.includes(d))){
  const payloads=[];
  for(let i=0;i<dates.length;i+=8){
   const next=await Promise.all(dates.slice(i,i+8).map(d=>get(stationBase+"calendar/"+d.slice(5)+".json.gz?v="+encodeURIComponent(idx.generated_at||""),"gzip")));
   next.forEach((p,k)=>{if(p.date!==dates[i+k]||!Array.isArray(p.rows)||!String(p.reference_period).includes("1991"))throw Error("Falscher DWD-Tagesdatensatz");payloads.push(p)});
  }
  values=accumulate(payloads,field);
  note="DWD: Anomalie aus "+dates.length+" vollständigen Tageswerten je Station, Referenz 1991–2020.";
 }else if(wantValues){
  note=field===undefined?"Nur KL-Stationsstandorte: Niederschlagsmesswerte sind noch nicht angebunden.":s.reference!=="1991-2020"?"Nur Standorte: Stationsreferenz 1961–1990 fehlt.":"Nur Standorte: Für diesen Zeitraum fehlen vollständige passende DWD-Tagesdateien.";
 }
 const stations=idx.stations.flatMap((row,i)=>{
  if(region!=="Deutschland"&&normalized(row[6])!==normalized(region)&&!$("hyrasRegNeighbors").checked)return [];
  const p=project(geo.g,Number(row[4]),Number(row[3]));
  return p?[{name:row[2],id:row[1],elev:row[5],p,value:values.get(i),state:row[6]}]:[];
 });
 return {stations,note};
}
function filterStations(stations,onlyValid){
 return onlyValid?stations.filter(st=>Number.isFinite(st.value)):stations;
}
// Display-only normalized Gaussian convolution: no-data cells contribute
// neither zero nor a colour. The source observations are never overwritten.
function gaussianDisplay(values,valid,w,h,sigma){
 const radius=Math.max(1,Math.ceil(3*sigma)),kernel=Array.from({length:2*radius+1},(_,i)=>Math.exp(-.5*((i-radius)/sigma)**2));
 const sums=new Float32Array(w*h),weights=new Float32Array(w*h),out=new Float32Array(w*h);
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
  let sum=0,weight=0;
  for(let k=-radius;k<=radius;k++){const xx=x+k;if(xx<0||xx>=w)continue;const i=y*w+xx;if(!valid[i]||!Number.isFinite(values[i]))continue;const a=kernel[k+radius];sum+=a*values[i];weight+=a}
  const i=y*w+x;sums[i]=sum;weights[i]=weight;
 }
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
  let sum=0,weight=0;
  for(let k=-radius;k<=radius;k++){const yy=y+k;if(yy<0||yy>=h)continue;const i=yy*w+x,a=kernel[k+radius];sum+=a*sums[i];weight+=a*weights[i]}
  out[y*w+x]=weight>0?sum/weight:NaN;
 }
 return out;
}
function interpolateDisplay(values,w,h,x,y){
 x=Math.max(0,Math.min(w-1,x));y=Math.max(0,Math.min(h-1,y));
 const x0=Math.floor(x),y0=Math.floor(y),x1=Math.min(w-1,x0+1),y1=Math.min(h-1,y0+1),u=x-x0,v=y-y0;
 let sum=0,weight=0;
 const a=values[y0*w+x0],b=values[y0*w+x1],c=values[y1*w+x0],d=values[y1*w+x1];
 if(Number.isFinite(a)){const q=(1-u)*(1-v);sum+=a*q;weight+=q}
 if(Number.isFinite(b)){const q=u*(1-v);sum+=b*q;weight+=q}
 if(Number.isFinite(c)){const q=(1-u)*v;sum+=c*q;weight+=q}
 if(Number.isFinite(d)){const q=u*v;sum+=d*q;weight+=q}
 return weight?sum/weight:NaN;
}
function renderingLabel(mode){return mode==="native"?"Originalraster":mode==="strong"?"stark geglättet (Flächenkonturen)":"leicht geglättet"}
const smoothCache=new WeakMap();
function drawRaster(ctx,s,b,rendering){
 const canvas=s.canvas,w=canvas.width,h=canvas.height,field=s.numeric;
 ctx.imageSmoothingEnabled=rendering!=="native";
 if(ctx.imageSmoothingEnabled)ctx.imageSmoothingQuality="high";
 if(rendering==="native"||!field||field.values.length!==w*h||field.valid.length!==w*h){ctx.drawImage(canvas,0,0);return}
 // Filter at a fixed physical scale so preview, zoom and exports agree.
 const sigma=(rendering==="strong"?3:1)/Math.max(.25,s.resolution||1);
 let cached=smoothCache.get(canvas);
 if(!cached){cached=new Map();smoothCache.set(canvas,cached)}
 if(!cached.has(sigma))cached.set(sigma,gaussianDisplay(field.values,field.valid,w,h,sigma));
 const filtered=cached.get(sigma);
 // Interpolate the numerical display field, then apply the original
 // discrete colour classes. This produces smooth contours, not blurry RGB.
 // Render only the selected crop; bound temporary memory for large regions.
 const sub=Math.max(1,Math.min(8,Math.floor(Math.sqrt(12000000/(b.w*b.h)))));
 const tile=document.createElement("canvas");tile.width=b.w*sub;tile.height=b.h*sub;
 const tc=tile.getContext("2d"),img=tc.createImageData(tile.width,tile.height),dst=img.data;
 const breaks=field.breaks,colors=field.rgb;
 for(let py=0;py<tile.height;py++){
  const sy=b.y+(py+.5)/sub,iy=Math.min(h-1,Math.floor(sy));
  for(let px=0;px<tile.width;px++){
   const sx=b.x+(px+.5)/sub,ix=Math.min(w-1,Math.floor(sx));
   if(!field.valid[iy*w+ix])continue;
   const value=interpolateDisplay(filtered,w,h,sx-.5,sy-.5);
   if(!Number.isFinite(value))continue;
   let k=0;while(k<breaks.length&&value>=breaks[k])k++;
   const color=colors[Math.min(k,colors.length-1)],i=4*(py*tile.width+px);
   dst[i]=color[0];dst[i+1]=color[1];dst[i+2]=color[2];dst[i+3]=255;
  }
 }
 tc.putImageData(img,0,0);
 ctx.drawImage(tile,b.x,b.y,b.w,b.h);
}
function colorRectangles(data,w,h,emit){
 // Exact run-length encoding of the selected display raster. A run is
 // extended vertically only when colour and both horizontal edges agree.
 let active=new Map();
 for(let y=0;y<h;y++){
  const next=new Map();
  for(let x=0;x<w;){
   const start=x,i=4*(y*w+x),key=(data[i]<<24|data[i+1]<<16|data[i+2]<<8|data[i+3])>>>0;
   x++;while(x<w){const j=4*(y*w+x);if(((data[j]<<24|data[j+1]<<16|data[j+2]<<8|data[j+3])>>>0)!==key)break;x++;}
   if(!(key&255))continue;
   const id=key+":"+start+":"+x,old=active.get(id);
   if(old){old.h++;next.set(id,old);active.delete(id);}
   else next.set(id,{key,x:start,y,w:x-start,h:1});
  }
  for(const rect of active.values())emit(rect);
  active=next;
 }
 for(const rect of active.values())emit(rect);
}
function regionalPdfContext(pdf,measure,transparent=false){
 let transform=[1,1,0,0],stack=[],path=[],circle=null;
 const c={fillStyle:"#000000",strokeStyle:"#000000",lineWidth:1,font:"12px sans-serif",lineJoin:"miter",lineCap:"butt",
  save(){stack.push({transform:transform.slice(),fillStyle:c.fillStyle,strokeStyle:c.strokeStyle,lineWidth:c.lineWidth,font:c.font,lineJoin:c.lineJoin,lineCap:c.lineCap});pdf.saveGraphicsState()},
  restore(){const state=stack.pop();if(!state)throw Error("PDF-Grafikzustand fehlt");transform=state.transform;for(const k of ["fillStyle","strokeStyle","lineWidth","font","lineJoin","lineCap"])c[k]=state[k];pdf.restoreGraphicsState()},
  translate(x,y){transform[2]+=x*transform[0];transform[3]+=y*transform[1]},
  scale(x,y){transform[0]*=x;transform[1]*=y},
  beginPath(){path=[];circle=null},
  moveTo(x,y){path.push({op:"m",c:point(x,y)})},
  lineTo(x,y){path.push({op:"l",c:point(x,y)})},
  closePath(){path.push({op:"h",c:[]})},
  rect(x,y,w,h){c.moveTo(x,y);c.lineTo(x+w,y);c.lineTo(x+w,y+h);c.lineTo(x,y+h);c.closePath()},
  arc(x,y,r){circle={xy:point(x,y),r:r*Math.abs(transform[0])}},
  clip(rule){if(path.length){pdf.path(path);if(rule==="evenodd")pdf.clipEvenOdd();else pdf.clip();pdf.discardPath()}},
  stroke(){strokeStyle();if(circle)pdf.circle(...circle.xy,circle.r,"S");else if(path.length)pdf.path(path).stroke()},
  fill(){pdf.setFillColor(...rgb(c.fillStyle));if(circle)pdf.circle(...circle.xy,circle.r,"F");else if(path.length)pdf.path(path).fill()},
  fillRect(x,y,w,h){if(transparent&&x===0&&y===0&&c.fillStyle==="#ffffff"&&transform[0]===1&&transform[1]===1&&w===measure.canvas.width&&h===measure.canvas.height)return;pdf.setFillColor(...rgb(c.fillStyle));pdf.rect(...point(x,y),w*transform[0],h*transform[1],"F")},
  strokeRect(x,y,w,h){strokeStyle();pdf.rect(...point(x,y),w*transform[0],h*transform[1],"S")},
  measureText(t){measure.font=c.font;return measure.measureText(String(t))},
  fillText(t,x,y,max){drawText(t,x,y,max,false)},
  strokeText(t,x,y,max){drawText(t,x,y,max,true)},
  drawImage(image,x,y,w=image.width,h=image.height){
   const iw=image.width,ih=image.height;
   if(!iw||!ih)return;
   const pixels=image.getContext("2d").getImageData(0,0,iw,ih).data,groups=new Map();
   const sx=w/iw,sy=h/ih;
   function flush(key,ops){
    if(!ops.length)return;
    const alpha=(key&255)/255;
    pdf.saveGraphicsState();if(alpha!==1)pdf.setGState(new pdf.GState({opacity:alpha}));
    pdf.setFillColor(key>>>24,(key>>>16)&255,(key>>>8)&255);
    pdf.path(ops).fill();pdf.restoreGraphicsState();ops.length=0;
   }
   colorRectangles(pixels,iw,ih,r=>{
    let ops=groups.get(r.key);if(!ops){ops=[];groups.set(r.key,ops)}
    const a=point(x+r.x*sx,y+r.y*sy),b=point(x+(r.x+r.w)*sx,y+(r.y+r.h)*sy);
    ops.push({op:"m",c:a},{op:"l",c:[b[0],a[1]]},{op:"l",c:b},{op:"l",c:[a[0],b[1]]},{op:"h",c:[]});
    if(ops.length>=5000)flush(r.key,ops);
   });
   for(const [key,ops] of groups)flush(key,ops);
  }
 };
 function point(x,y){return [x*transform[0]+transform[2],y*transform[1]+transform[3]]}
 function rgb(value){const hex=/^#([0-9a-f]{6})$/i.exec(value);if(hex)return [0,2,4].map(i=>parseInt(hex[1].slice(i,i+2),16));const short=/^#([0-9a-f]{3})$/i.exec(value);if(short)return [...short[1]].map(a=>parseInt(a+a,16));const vals=/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(value);if(vals)return vals.slice(1).map(Number);return value==="white"?[255,255,255]:[0,0,0]}
 function strokeStyle(){pdf.setDrawColor(...rgb(c.strokeStyle));pdf.setLineWidth(c.lineWidth*Math.abs(transform[0]));pdf.setLineJoin(c.lineJoin);pdf.setLineCap(c.lineCap)}
 function drawText(t,x,y,max,outline){
  const str=String(t),size=Number(/([\d.]+)px/.exec(c.font)?.[1])||12,actual=c.measureText(str).width;
  pdf.setFont("helvetica",/bold|700/.test(c.font)?"bold":"normal");
  pdf.setFontSize(size*Math.abs(transform[1])*(max&&actual>max?max/actual:1));
  if(outline)strokeStyle();else pdf.setTextColor(...rgb(c.fillStyle));
  pdf.text(str,...point(x,y),{renderingMode:outline?"stroke":"fill",baseline:"alphabetic"});
 }
 return c;
}
function renderCanvas(d,maxEdge,pdfFactory=null){
 const {s,b,features,selected,region,stations,legend,neighbors,names,values,rendering}=d;
 const u=Math.max(1,maxEdge/1000),pad=Math.round(18*u),top=Math.round(76*u);
 const estimatedWidth=Math.min(maxEdge-2*pad,(maxEdge-top-130*u)*b.w/b.h);
 const font=Math.round(12*u),legendCols=Math.max(1,Math.min(5,Math.floor(estimatedWidth/(150*u)))),legendRows=Math.ceil(legend.length/legendCols);
 const footer=Math.round((66+legendRows*22)*u);
 const scale=Math.min((maxEdge-2*pad)/b.w,(maxEdge-top-footer)/b.h);
 const w=Math.max(1,Math.floor(b.w*scale)),h=Math.max(1,Math.floor(b.h*scale));
 const cv=document.createElement("canvas");cv.width=w+2*pad;cv.height=h+top+footer;const measure=cv.getContext("2d"),ctx=pdfFactory?pdfFactory(cv,measure):measure;
 if(!ctx)throw Error("Canvas konnte nicht erzeugt werden");
 ctx.fillStyle="#ffffff";ctx.fillRect(0,0,cv.width,cv.height);ctx.fillStyle="#192630";ctx.font="bold "+Math.round(22*u)+"px sans-serif";
 ctx.fillText("HYRAS · "+region,pad,28*u,cv.width-pad*2);
 ctx.font=Math.round(14*u)+"px sans-serif";ctx.fillText(s.title||"",pad,48*u,cv.width-pad*2);
 ctx.font=Math.round(12*u)+"px sans-serif";ctx.fillText((s.subtitle||"")+" · Raster "+s.resolution+" km",pad,65*u,cv.width-pad*2);
 ctx.save();ctx.translate(pad,top);ctx.scale(w/b.w,h/b.h);ctx.translate(-b.x,-b.y);
 ctx.beginPath();ctx.rect(b.x,b.y,b.w,b.h);ctx.clip();
 if(region!=="Deutschland"&&!neighbors){makePath(ctx,selected);ctx.clip("evenodd")}
 // Display-only filtered contours; vector boundaries and stations stay sharp.
 drawRaster(ctx,s,b,rendering);
 ctx.lineJoin="round";ctx.lineCap="round";
 for(const f of features){makePath(ctx,f.polys);ctx.strokeStyle="#343a40";ctx.lineWidth=(region===f.name?1.5:.65)*u/scale;ctx.stroke()}
 ctx.restore();
 ctx.strokeStyle="#c9cfd4";ctx.lineWidth=u;ctx.strokeRect(pad,top,w,h);
 // Stations use a fixed graphic scale, with deterministic collision avoidance for labels.
 const hits=[],boxes=[];const fmt=v=>(v>0?"+":"")+v.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1});
 ctx.font="bold "+Math.round(12*u)+"px sans-serif";
 const sorted=stations.slice().sort((a,b)=>(Number.isFinite(b.value)?1:0)-(Number.isFinite(a.value)?1:0)||String(a.id).localeCompare(String(b.id)));
 ctx.save();ctx.beginPath();ctx.rect(pad,top,w,h);ctx.clip();
 for(const st of sorted){
  const x=pad+(st.p[0]-b.x)*w/b.w,y=top+(st.p[1]-b.y)*h/b.h;if(x<pad||x>pad+w||y<top||y>top+h)continue;
  const has=Number.isFinite(st.value);ctx.beginPath();ctx.arc(x,y,3.3*u,0,2*Math.PI);ctx.fillStyle=has?"#ffffff":"#d3d9df";ctx.fill();ctx.strokeStyle="#1d242b";ctx.lineWidth=1.2*u;ctx.stroke();
  hits.push({...st,x,y});
  const label=[values&&has?fmt(st.value):"",names?st.name:""].filter(Boolean).join(" · ");
  if(!label)continue;
  const tw=ctx.measureText(label).width,th=15*u;
  for(const [dx,dy] of [[7,-5],[-7,-5],[7,15],[-7,15]]){
   const tx=x+dx*u-(dx<0?tw:0),ty=y+dy*u;
   const box=[tx-2*u,ty-th,tx+tw+2*u,ty+3*u];
   if(box[0]<pad||box[1]<top||box[2]>pad+w||box[3]>top+h||boxes.some(a=>!(a[2]<box[0]||a[0]>box[2]||a[3]<box[1]||a[1]>box[3])))continue;
   boxes.push(box);ctx.strokeStyle="white";ctx.lineWidth=3*u;ctx.strokeText(label,tx,ty);ctx.fillStyle="#182027";ctx.fillText(label,tx,ty);break;
  }
 }
 ctx.restore();ctx.font=font+"px sans-serif";
 legend.forEach((l,i)=>{const col=i%legendCols,row=Math.floor(i/legendCols),x=pad+col*w/legendCols,y=top+h+14*u+row*22*u;ctx.fillStyle=l.color;ctx.fillRect(x,y,15*u,12*u);ctx.strokeStyle="#aaa";ctx.lineWidth=.6*u;ctx.strokeRect(x,y,15*u,12*u);ctx.fillStyle="#26323b";ctx.fillText(l.label,x+20*u,y+11*u,Math.max(10,w/legendCols-24*u))});
 ctx.fillStyle="#45525c";ctx.font=Math.round(11*u)+"px sans-serif";
 ctx.fillText("DWD HYRAS-DE · DWD CDC KL · Grenzen: deutschlandGeoJSON/GIS-DATA",pad,cv.height-24*u,cv.width-2*pad);
 ctx.fillText("Darstellung: "+renderingLabel(rendering)+(rendering==="native"?"":" (keine höhere Datenauflösung)"),pad,top+h+Math.round((14+legendRows*22)*u),cv.width-2*pad);
 ctx.fillText(d.note||"",pad,cv.height-9*u,cv.width-2*pad);
 return {cv,hits};
}
async function refresh(){
 if(!$("hyrasRegionalWorkshop")?.open)return;
 const rev=++revision,s=source;display=null;
 clear("Regionalkarte wird vorbereitet …");
 if(!s?.owner?.isConnected){clear("Für diese Ansicht ist noch kein numerisches Raster verfügbar.");return}
 try{
  const region=$("hyrasRegRegion").value,neighbors=$("hyrasRegNeighbors").checked,names=$("hyrasRegNames").checked,values=$("hyrasRegValues").checked,onlyValid=$("hyrasRegOnlyValid").checked;
  const geo=await loadGeometry(s);if(rev!==revision)return;
  const features=geo.items;
  const selected=(region==="Deutschland"?features:features.filter(f=>normalized(f.name)===normalized(region))).flatMap(f=>f.polys);
  const b=region==="Deutschland"?{x:0,y:0,w:s.canvas.width,h:s.canvas.height}:extent(selected,s.canvas.width,s.canvas.height);
  let st={stations:[],note:"Stationslayer ausgeschaltet."};
  if($("hyrasRegStations").checked){$("hyrasRegStatus").textContent="DWD-Stationswerte für den Kartenzeitraum werden geprüft …";try{st=await stationData(s,geo,region,values||onlyValid)}catch(e){st.note="Stationsdaten nicht verfügbar: "+e.message}}
  if(rev!==revision||!s.owner.isConnected)return;
  const rendering=$("hyrasRegRendering").value;
  const d={s,b,features,selected,region,stations:filterStations(st.stations,onlyValid),legend:s.legend||[],neighbors,names,values,rendering,note:st.note};
  const out=renderCanvas(d,1100);$("hyrasRegPreview").replaceChildren(out.cv);
  display=d;
  out.cv.addEventListener("pointerup",e=>{
   const r=out.cv.getBoundingClientRect(),x=(e.clientX-r.left)*out.cv.width/r.width,y=(e.clientY-r.top)*out.cv.height/r.height;
   let best=null,dist=22;for(const h of out.hits){const q=Math.hypot(x-h.x,y-h.y);if(q<dist){best=h;dist=q}}
   $("hyrasRegInspection").textContent=best?best.name+" (DWD "+best.id+", "+best.elev+" m) · "+(Number.isFinite(best.value)?best.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})+" K":"Kein passender Messwert"):"Stationspunkt antippen, um Details zu sehen.";
  });
  $("hyrasRegStatus").textContent="HYRAS-Raster: "+s.resolution+" km · "+renderingLabel(rendering)+" · "+out.hits.length+" Stationspunkte im Ausschnitt. "+st.note;
  $("hyrasRegPng").disabled=false;$("hyrasRegPdf").disabled=false;$("hyrasRegPdfTop").disabled=false;
  $("hyrasRegPdfRegion").textContent=region+" · "+s.title+" · "+(s.start||"")+" – "+(s.end||"");
 }catch(e){if(rev===revision){clear("Regionalkarte nicht verfügbar: "+e.message);console.warn("HYRAS regional",e)}}
}
async function download(format){
 const d=display;if(!d||!d.s.owner.isConnected)return;
 const buttons=(format==="png"?["hyrasRegPng"]:["hyrasRegPdf","hyrasRegPdfTop"]).map($).filter(Boolean);buttons.forEach(b=>b.disabled=true);
 try{
  const name="hyras_"+d.s.parameter+"_"+normalized(d.region)+"_"+(d.s.start||"")+'_'+(d.s.end||"");
  if(format==="pdf"){
   $("hyrasRegInspection").textContent="Vektor-PDF wird aufgebaut …";
   if(!root.jspdf?.jsPDF&&root.dashboardExportLibraries?.pdf)await root.dashboardExportLibraries.pdf();
   const Pdf=root.jspdf?.jsPDF;if(!Pdf)throw Error("jsPDF nicht verfügbar");
   let pdf;const transparent=$("hyrasRegPdfTransparent").checked;
   renderCanvas(d,1100,(cv,measure)=>{pdf=new Pdf({orientation:cv.width>=cv.height?"landscape":"portrait",unit:"pt",format:[cv.width,cv.height],compress:true});return regionalPdfContext(pdf,measure,transparent)});
   pdf.save(name+"_vektor.pdf");$("hyrasRegInspection").textContent="Vektor-PDF erstellt: Farbflächen, Grenzen, Stationen und Texte sind eigenständige Vektorobjekte.";
  }else{
   const {cv}=renderCanvas(d,Number($("hyrasRegSize").value)||4000);
   const blob=await new Promise((ok,no)=>cv.toBlob(b=>b?ok(b):no(Error("PNG zu groß für den Browser")),"image/png"));
   const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name+".png";document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2500);
  }
 }catch(e){$("hyrasRegInspection").textContent="Export fehlgeschlagen: "+e.message}
 finally{buttons.forEach(b=>b.disabled=!display)}
}
async function exportNationalPdf(s,transparent=true){
 if(!s?.canvas||!s.owner?.isConnected)throw Error("Die gewählte Karte ist nicht mehr aktuell.");
 const geo=await loadGeometry(s);
 if(!root.jspdf?.jsPDF&&root.dashboardExportLibraries?.pdf)await root.dashboardExportLibraries.pdf();
 const Pdf=root.jspdf?.jsPDF;if(!Pdf)throw Error("jsPDF nicht verfügbar.");
 if(!s.owner.isConnected)throw Error("Die Kartenauswahl wurde während des Exports geändert.");
 const features=geo.items;
 const d={s,b:{x:0,y:0,w:s.canvas.width,h:s.canvas.height},features,selected:features.flatMap(f=>f.polys),region:"Deutschland",stations:[],legend:legendFrom(s.legendNode),neighbors:false,names:false,values:false,rendering:"native",note:"Referenz: "+s.reference+" · Originalraster "+s.resolution+" km"};
 let pdf;
 renderCanvas(d,1100,(cv,measure)=>{pdf=new Pdf({orientation:cv.width>=cv.height?"landscape":"portrait",unit:"pt",format:[cv.width,cv.height],compress:true});return regionalPdfContext(pdf,measure,transparent)});
 const filename=["hyras",s.parameter,"deutschland",s.metric,s.start,s.end,s.reference,"vektor"].filter(Boolean).join("_")+".pdf";
 pdf.save(filename);
}
function setSource(s){
 install();
 if(!s?.canvas||!s.lookupUrl||!s.owner?.isConnected)return;
 source={...s,legend:legendFrom(s.legendNode)};display=null;revision++;
 if($("hyrasRegionalWorkshop")?.open)refresh();else clear("Raster verfügbar. Regionale Kartenwerkstatt öffnen.");
}
const api={project,coordinate,extent,isoDates,accumulate,filterStations,gaussianDisplay,interpolateDisplay,drawRaster,colorRectangles,regionalPdfContext,renderCanvas,exportNationalPdf,install,setSource};
if(typeof module==="object"&&module.exports)module.exports=api;else {root.HyrasRegional=api;install()}
})(typeof globalThis==="object"?globalThis:this);
