/* Satellite composite export: genuine EUMETSAT pixels + time-matched ECMWF
 * pressure isobars. JPEG map imagery is embedded as raster in PDF, while
 * pink isolines and pressure labels remain separate editable PDF vectors.
 * No third-party runtime dependency; original model provenance preserved.
 */
(() => {
"use strict";
const BBOX={
 europe:[-27,24,49,73],atlantic:[-70,15,35,75],
 southwest:[-37,24,19,53],central:[-2,43,25,58],germany:[5,47,16,56]
};
const PINK="#ff4fcf",HALO="#061522";
const esc=s=>String(s||"").normalize("NFKD").replace(/[\u0300-\u036f]/g,"").replace(/[^ -~]/g,"?").replace(/[\\()]/g,c=>"\\"+c);
const fmt=s=>Number(s).toFixed(3).replace(/\.000$/,"");
const inBounds=(p,b)=>p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3];
function pathsFor(overlay,region){
 const bbox=BBOX[region];
 if(!bbox||!overlay||!Array.isArray(overlay.contours)||!overlay.contours.length)
  throw Error("Keine realen ECMWF-Konturen für den Kartenexport verfügbar.");
 if(!window.SatelliteIsobarGeometry?.prepare)
  throw Error("Gemeinsamer Isobarenfilter fehlt.");
 const groups=window.SatelliteIsobarGeometry.prepare(overlay.contours,bbox,overlay.spacing||5);
 if(!groups.length)throw Error("Keine ausreichend langen, sauberen Isobaren in diesem Kartenausschnitt.");
 return groups;
}
function project(point,region,x,y,w,h){
 const [minX,minY,maxX,maxY]=BBOX[region];
 return [x+(point[0]-minX)/(maxX-minX)*w,y+(maxY-point[1])/(maxY-minY)*h];
}

/* Exact NOAA WPC EPSG:4326 analysis polylines, independent of ECMWF contours.
 * Reject unverified sources or mixed UTC. No invented front-side triangles.
 */
const NOAA_SOURCE="https://tgftp.nws.noaa.gov/data/raw/as/asus02.kwbc.cod.sus.txt";
const FRONT_COLORS={cold:"#5998c9",warm:"#d77a76",occluded:"#a795c5",stationary:"#a795c5"};
function frontFeatures(fronts,region,satelliteUTC){
 if(!fronts)return [];
 if(!BBOX[region]||fronts.provider!=="NOAA WPC"||fronts.source_url!==NOAA_SOURCE||
   fronts.coordinate_reference_system!=="EPSG:4326"||
   fronts.front_source_format!=="CODSUS-HIRES"||fronts.region!==region||
   fronts.satelliteUTC!==satelliteUTC||!Array.isArray(fronts.features)||
   fronts.features.length>600)throw Error("NOAA-Fronten: Herkunft, Projektion oder Satelliten-UTC nicht verifiziert.");
 const sat=Date.parse(satelliteUTC),valid=Date.parse(fronts.valid_utc);
 if(!Number.isFinite(sat)||!Number.isFinite(valid)||(sat-valid)/3600000 < -1||
   (sat-valid)/3600000 > 12)throw Error("NOAA-Fronten passen zeitlich nicht zur Satellitenaufnahme.");
 const box=BBOX[region],found=[];
 for(const f of fronts.features){
  if(!Object.prototype.hasOwnProperty.call(FRONT_COLORS,f?.type)||!Array.isArray(f?.coords)||
     f.coords.length<2||f.coords.length>3000)throw Error("NOAA-Frontgeometrie ungültig.");
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for(const p of f.coords){
   if(!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite)||
      p[0]<-180||p[0]>180||p[1]<0||p[1]>90)
    throw Error("NOAA-Frontkoordinate außerhalb des gültigen Bereichs.");
   minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
   minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
  }
  if(maxX>=box[0]&&minX<=box[2]&&maxY>=box[1]&&minY<=box[3])found.push(f);
 }
 return found;
}
/* All three output media use the same source vertices and symbol geometry.
 * Symbol SIDES are schematic unless explicitly verified in the NOAA feed.
 * Small Bezier handles preserve every actual WPC coordinate exactly.
 */
const frontUnit=width=>Math.max(.74,Math.min(3.6,width/900));
function frontLayout(fronts,region,satelliteUTC,area){
 const features=frontFeatures(fronts,region,satelliteUTC);
 const style=window.SatelliteFrontStyle;
 if(features.length&&!style?.layout)
  throw Error("Gemeinsames NOAA-Synoptikmodul fehlt.");
 return features.map(f=>style.layout(f,p=>project(p,region,area.x,area.y,area.width,area.height),
  frontUnit(area.width))).filter(Boolean);
}
function canvasCommandPath(ctx,steps){
 ctx.beginPath();
 for(const item of steps){
  if(item[0]==="M")ctx.moveTo(item[1],item[2]);
  else if(item[0]==="L")ctx.lineTo(item[1],item[2]);
  else if(item[0]==="C")ctx.bezierCurveTo(...item.slice(1));
  else if(item[0]==="Z")ctx.closePath();
 }
}
function paintFronts(ctx,fronts,region,{x=0,y=0,width,height},satelliteUTC=fronts?.satelliteUTC){
 if(!fronts)return 0;
 if(!width||!height)throw Error("Fronten: Kartenmaße fehlen.");
 const glyphs=frontLayout(fronts,region,satelliteUTC,{x,y,width,height});
 if(!glyphs.length)return 0;
 const unit=frontUnit(width);
 ctx.save();ctx.beginPath();ctx.rect(x,y,width,height);ctx.clip();
 ctx.lineJoin="round";ctx.lineCap="round";
 for(const g of glyphs){
  ctx.setLineDash?.([]);canvasCommandPath(ctx,g.commands);
  ctx.strokeStyle="#122438";ctx.lineWidth=2.55*unit;ctx.stroke();
  if(g.type==="stationary"){
   for(const section of g.sections){
    canvasCommandPath(ctx,section.commands);
    ctx.strokeStyle=section.color;ctx.lineWidth=1.4*unit;ctx.stroke();
   }
  }else{
   canvasCommandPath(ctx,g.commands);
   ctx.strokeStyle=g.color;ctx.lineWidth=1.4*unit;ctx.stroke();
  }
  for(const glyph of g.symbols){
   canvasCommandPath(ctx,glyph.commands);
   ctx.fillStyle=glyph.color;ctx.fill();
   ctx.strokeStyle="#122438";ctx.lineWidth=.55*unit;ctx.stroke();
  }
 }
 ctx.restore();
 return glyphs.length;
}
function pdfCommands(steps,top){
 const arr=[];
 for(const item of steps){
  const t=item[0];
  if(t==="Z"){arr.push("h");continue;}
  const coords=[];
  for(let i=1;i<item.length;i+=2)coords.push(fmt(item[i]),fmt(top-item[i+1]));
  arr.push(coords.join(" ")+(t==="M"?" m":t==="L"?" l":" c"));
 }
 return arr.join("\n");
}
function drawPDFFronts(fronts,region,w,h,bottom,satelliteUTC){
 if(!fronts)return "";
 const glyphs=frontLayout(fronts,region,satelliteUTC,{x:0,y:0,width:w,height:h});
 if(!glyphs.length)return "";
 const out=["% NOAA WPC analyzed frontal vectors (individual editable paths)",
  "% Pips schematic: CODSUS does not encode frontal movement/side",
  "q 0 "+fmt(bottom)+" "+fmt(w)+" "+fmt(h)+" re W n","1 J 1 j"];
 const unit=frontUnit(w),top=bottom+h;
 for(const g of glyphs){
  const path=pdfCommands(g.commands,top);
  out.push("q",pdfRGB("#122438")+" RG",fmt(2.55*unit)+" w",path,"S","Q");
  if(g.type==="stationary"){
   for(const section of g.sections)out.push("q",pdfRGB(section.color)+" RG",
    fmt(1.4*unit)+" w",pdfCommands(section.commands,top),"S","Q");
  }else out.push("q",pdfRGB(g.color)+" RG",fmt(1.4*unit)+" w",path,"S","Q");
  for(const glyph of g.symbols){
   out.push("q",pdfRGB(glyph.color)+" rg",
    pdfRGB("#122438")+" RG",fmt(.55*unit)+" w",
    pdfCommands(glyph.commands,top),"B","Q");
  }
 }
 out.push("Q");
 return out.join("\n");
}

function pressureCenters(overlay,region){
 const b=BBOX[region],geo=window.SatelliteIsobarGeometry;
 if(!b||!geo?.detectVisiblePressureSystems||!Array.isArray(overlay?.contours))return [];
 const caps={atlantic:8,europe:6,southwest:5,central:3,germany:2};
 return geo.detectVisiblePressureSystems(overlay.contours,b,{
  minRings:Number(overlay.spacing)===2?6:3,maxSystems:caps[region]||5,minSeparation:94
 });
}
function paintPressureCenters(ctx,overlay,region,{x=0,y=0,width,height}){
 if(!width||!height)return [];
 const markers=pressureCenters(overlay,region);
 const size=Math.max(23,Math.min(52,Math.round(width*.031)));
 ctx.save();ctx.textAlign="center";ctx.textBaseline="middle";
 ctx.font="900 "+size+"px Arial,Helvetica,sans-serif";
 ctx.lineJoin="round";ctx.lineWidth=Math.max(2.2,size*.12);
 for(const m of markers){
  const p=project([m.lon,m.lat],region,x,y,width,height);
  ctx.strokeStyle="#0c1931";ctx.globalAlpha=.96;
  if(typeof ctx.strokeText==="function")ctx.strokeText(m.type,p[0],p[1]);
  ctx.fillStyle=m.type==="T"?"#cf4baf":"#9750c4";
  ctx.fillText(m.type,p[0],p[1]);
 }
 ctx.restore();
 return markers;
}
function paintIsobars(ctx,overlay,region,{x=0,y=0,width,height}){
 const groups=pathsFor(overlay,region);
 if(!width||!height)throw Error("Kartenmaße fehlen.");
 const unit=Math.max(.75,Math.min(1.8,width/900));
 ctx.save();ctx.beginPath();ctx.rect(x,y,width,height);ctx.clip();
 ctx.lineJoin="round";ctx.lineCap="round";
 for(const group of groups){
  const stroke=heavy=>Number(overlay.spacing)===2 ? 0.75*unit : (heavy?1.55:0.9)*unit;
  const draw=()=>{
   ctx.beginPath();
   for(const run of group.runs){
    run.forEach((p,i)=>{
     const at=project(p,region,x,y,width,height);
     if(i===0)ctx.moveTo(at[0],at[1]);else ctx.lineTo(at[0],at[1]);
    });
   }
   ctx.stroke();
  };
  ctx.strokeStyle=HALO;ctx.globalAlpha=.94;ctx.lineWidth=(Number(overlay.spacing)===2?1.85:(group.heavy?2.95:2.3))*unit;draw();
  ctx.strokeStyle=PINK;ctx.globalAlpha=1;ctx.lineWidth=stroke(group.heavy);draw();
 }
 for(const group of groups){
  if(!group.label)continue;
  const p=project(group.label,region,x,y,width,height);
  const label=String(group.hpa),size=Math.max(9,Math.round(13*unit));
  ctx.font="bold "+size+"px Arial,sans-serif";ctx.textAlign="center";ctx.textBaseline="middle";
  const tw=ctx.measureText(label).width+12*unit,th=size+8*unit;
  ctx.globalAlpha=.94;ctx.fillStyle="#07182a";ctx.fillRect(p[0]-tw/2,p[1]-th/2,tw,th);
  ctx.globalAlpha=1;ctx.strokeStyle=PINK;ctx.lineWidth=.65*unit;
  ctx.strokeRect(p[0]-tw/2,p[1]-th/2,tw,th);
  ctx.fillStyle="#ffffff";ctx.fillText(label,p[0],p[1]);
 }
 paintPressureCenters(ctx,overlay,region,{x,y,width,height});
 ctx.restore();
 return groups;
}
function utc(t){return new Date(t).toISOString().slice(0,16).replace("T"," ")+" UTC";}
function titleLine(options){return "MTG "+options.productName+" | "+options.regionName;}
function provenance(options){const o=options.overlay;
 return "Satellit: "+utc(o.satelliteUTC)+" | ECMWF IFS "+utc(o.runUTC)+
  " | Isobaren: "+utc(o.validUTC)+" | Abstand "+o.spacing+" hPa | "+o.method+
  (options.fronts?" | NOAA WPC Analyse "+utc(options.fronts.valid_utc):"");}
function footerLine(o){return "Bild: EUMETSAT | Druckprognose: ECMWF CC BY 4.0 | Interpolierte Modellwerte, keine Messung";}
function rasterCanvas(image){
 const w=image.naturalWidth||image.width,h=image.naturalHeight||image.height;
 if(!w||!h)throw Error("Satellitenbild nicht vollständig geladen.");
 const c=document.createElement("canvas");c.width=w;c.height=h;
 const ctx=c.getContext("2d");if(!ctx)throw Error("Canvas nicht verfügbar.");
 ctx.drawImage(image,0,0,w,h);
 return c;
}
async function renderPNG(options){
 const image=options.image;
 if(!options.overlay?.validUTC)throw Error("Keine gültigen Isobaren zum ausgewählten Satellitenbild.");
 const w=image.naturalWidth||image.width,h=image.naturalHeight||image.height;
 if(!w||!h)throw Error("Satellitenbild fehlt.");
 const header=Math.max(82,Math.round(w*.085)),footer=Math.max(65,Math.round(w*.063));
 const c=document.createElement("canvas");c.width=w;c.height=header+h+footer;
 const ctx=c.getContext("2d");ctx.fillStyle="#ffffff";ctx.fillRect(0,0,c.width,c.height);
 ctx.fillStyle="#10263f";ctx.font="bold "+Math.max(17,Math.round(w*.022))+"px Arial";
 ctx.fillText(titleLine(options),18,Math.round(header*.39),w-32);
 ctx.font=Math.max(12,Math.round(w*.013))+"px Arial";
 ctx.fillText(provenance(options),18,Math.round(header*.78),w-32);
 ctx.drawImage(image,0,header,w,h);
 paintIsobars(ctx,options.overlay,options.region,{x:0,y:header,width:w,height:h});
 paintFronts(ctx,options.fronts,options.region,{x:0,y:header,width:w,height:h},options.overlay.satelliteUTC);
 ctx.fillStyle="#10263f";ctx.font=Math.max(11,Math.round(w*.014))+"px Arial";
 ctx.fillText(footerLine(options),18,header+h+Math.round(footer*.5),w-32);
 const blob=await new Promise((resolve,reject)=>{
  try{c.toBlob(b=>b?resolve(b):reject(Error("Canvas-Export gesperrt (CORS).")),"image/png");}
  catch(e){reject(e);}
 });
 return {blob,name:filename(options,"png")};
}
function filename(o,type){
 return "mtg_"+o.product+"_"+o.region+"_"+o.overlay.satelliteUTC.replace(/[-:]/g,"").replace("T","_").replace(".000Z","Z")+"_isobaren"+(o.fronts?"_noaa_fronten":"")+"."+type;
}
const ascii=new TextEncoder();
function concat(items){
 const total=items.reduce((n,a)=>n+a.length,0),out=new Uint8Array(total);
 let off=0;for(const part of items){out.set(part,off);off+=part.length;}return out;
}
function pdfRGB(hex){
 return [1,3,5].map(i=>fmt(parseInt(hex.slice(i,i+2),16)/255)).join(" ");
}
function drawPDFVectors(overlay,region,w,h,bottom){
 const groups=pathsFor(overlay,region),out=[];
 const pt=p=>{
  const at=project(p,region,0,0,w,h);
  return [at[0],bottom+h-at[1]];
 };
 const unit=Math.max(.75,Math.min(1.8,w/900));
 out.push("q",fmt(0)+" "+fmt(bottom)+" "+fmt(w)+" "+fmt(h)+" re W n","1 J 1 j");
 for(const group of groups){
  const path=[];
  for(const run of group.runs){
   run.forEach((p,i)=>{
    const xy=pt(p);
    path.push(fmt(xy[0])+" "+fmt(xy[1])+(i?" l":" m"));
   });
  }
  const d=path.join("\n");
  const fine=Number(overlay.spacing)===2;
  const line=(fine?0.75:(group.heavy?1.55:0.9))*unit;
  out.push(pdfRGB(HALO)+" RG",fmt((fine?1.85:(group.heavy?2.95:2.3))*unit)+" w",d,"S");
  out.push(pdfRGB(PINK)+" RG",fmt(line)+" w",d,"S");
 }
 for(const group of groups){
  if(!group.label)continue;
  const xy=pt(group.label),fs=12*unit;
  out.push("0.027 0.094 0.165 rg",fmt(xy[0]-24*unit)+" "+fmt(xy[1]-10*unit)+
   " "+fmt(48*unit)+" "+fmt(20*unit)+" re f",
   pdfRGB(PINK)+" RG",fmt(.65*unit)+" w",fmt(xy[0]-24*unit)+" "+fmt(xy[1]-10*unit)+
   " "+fmt(48*unit)+" "+fmt(20*unit)+" re S",
   "1 1 1 rg","BT /F1 "+fmt(fs)+" Tf "+fmt(xy[0]-14*unit)+" "+fmt(xy[1]-4*unit)+
    " Td ("+esc(String(group.hpa))+") Tj ET");
 }
 // Keep H/T as editable text within the vector layer, not raster pixels.
 for(const m of pressureCenters(overlay,region)){
  const [cx,cy]=pt([m.lon,m.lat]);
  const fs=Math.max(24,Math.min(48,w*.031));
  out.push("q",
   pdfRGB("#0c1931")+" RG",
   pdfRGB(m.type==="T"?"#cf4baf":"#9750c4")+" rg",
   fmt(Math.max(2.2,fs*.12))+" w",
   "BT /F1 "+fmt(fs)+" Tf 2 Tr "+
    fmt(cx-fs*.35)+" "+fmt(cy-fs*.34)+" Td ("+m.type+") Tj ET",
   "Q");
 }
 out.push("Q");
 return out.join("\n");
}
async function renderPDF(options){
 const o=options.overlay;
 if(!o?.validUTC)throw Error("Keine UTC-validierten Modell-Isobaren verfügbar.");
 const base=rasterCanvas(options.image);
 const jpeg=base.toDataURL("image/jpeg",.93);
 if(!jpeg.startsWith("data:image/jpeg;base64,"))throw Error("PDF-Hintergrundbild konnte nicht codiert werden.");
 const b64=jpeg.slice(jpeg.indexOf(",")+1),raw=atob(b64);
 const jpg=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)jpg[i]=raw.charCodeAt(i);
 const w=base.width,h=base.height,top=Math.max(84,Math.round(w*.081)),bottom=Math.max(65,Math.round(w*.058)),pageH=h+top+bottom;
 const escapedTitle=esc(titleLine(options)),escapedTime=esc(provenance(options)),escapedFooter=esc(footerLine(options));
 const code=[
 "q 1 1 1 rg 0 0 "+fmt(w)+" "+fmt(pageH)+" re f Q",
 "0.063 0.149 0.247 rg",
 "BT /F1 "+fmt(Math.max(17,w*.02))+" Tf 18 "+fmt(pageH-35)+" Td ("+escapedTitle+") Tj ET",
 "BT /F1 "+fmt(Math.max(11,w*.011))+" Tf 18 "+fmt(pageH-60)+" Td ("+escapedTime+") Tj ET",
 "q "+fmt(w)+" 0 0 "+fmt(h)+" 0 "+fmt(bottom)+" cm /Im0 Do Q",
 drawPDFVectors(o,options.region,w,h,bottom),
 drawPDFFronts(options.fronts,options.region,w,h,bottom,o.satelliteUTC),
 "0.063 0.149 0.247 rg",
 "BT /F1 "+fmt(Math.max(11,w*.012))+" Tf 18 "+fmt(bottom/2)+" Td ("+escapedFooter+") Tj ET"
 ].join("\n")+"\n";
 const codeBytes=ascii.encode(code);
 const parts=[],offsets=[0];let length=0;
 function push(part){parts.push(part);length+=part.length;}
 function pushText(s){push(ascii.encode(s));}
 pushText("%PDF-1.4\n%Satellite MSLP composite\n");
 function object(id,dict,stream){
  offsets[id]=length;pushText(id+" 0 obj\n"+dict);
  if(stream){pushText("\nstream\n");push(stream);pushText("\nendstream");}
  pushText("\nendobj\n");
 }
 object(1,"<< /Type /Catalog /Pages 2 0 R >>");
 object(2,"<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
 object(3,"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "+fmt(w)+" "+fmt(pageH)+
  "] /Resources << /XObject << /Im0 5 0 R >> /Font << /F1 6 0 R >> >> /Contents 4 0 R >>");
 object(4,"<< /Length "+codeBytes.length+" >>",codeBytes);
 object(5,"<< /Type /XObject /Subtype /Image /Width "+w+" /Height "+h+
   " /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "+jpg.length+" >>",jpg);
 object(6,"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
 const xref=length;
 pushText("xref\n0 7\n0000000000 65535 f \n");
 for(let i=1;i<=6;i++)pushText(String(offsets[i]).padStart(10,"0")+" 00000 n \n");
 pushText("trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n"+xref+"\n%%EOF\n");
 return {blob:new Blob(parts,{type:"application/pdf"}),name:filename(options,"pdf")};
}
function download(result){
 if(!result?.blob?.size)throw Error("Exportdatei ist leer.");
 const u=URL.createObjectURL(result.blob),link=document.createElement("a");
 link.href=u;link.download=result.name;document.body.append(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(u),60000);
 return result.blob.size;
}
window.SatelliteMapExport={paintIsobars,paintFronts,frontLayout,frontFeatures,paintPressureCenters,pressureCenters,pathsFor,renderPNG,renderPDF,download};
})();