/* Climate Dashboard – print-quality exports independent of mobile viewport.
   Keeps source chart data and all scientific values unchanged. */
(function(root){
  "use strict";
  const WIDTH=2200, HEIGHT=1470, MARGIN=72, HEADER=168, FOOTER=118;
  function copy(value,seen){
    if(value===null || typeof value!=="object")return value;
    seen=seen||new WeakMap();
    if(seen.has(value))return seen.get(value);
    // Chart.js time scales and scientific series can contain Date objects.
    // A plain-object copy turns those into {}, breaking export timestamps.
    if(value instanceof Date){
      const result=new Date(value.getTime());seen.set(value,result);return result;
    }
    if(ArrayBuffer.isView(value) && !(value instanceof DataView)){
      const result=new value.constructor(value);seen.set(value,result);return result;
    }
    if(Array.isArray(value)){
      const result=[];seen.set(value,result);
      value.forEach((entry,i)=>{result[i]=copy(entry,seen);});
      return result;
    }
    const result={};seen.set(value,result);
    for(const key of Object.keys(value))result[key]=copy(value[key],seen);
    return result;
  }
  function line(ctx,text,x,y,maxWidth,size,bold){
    ctx.font=(bold?"700 ":"400 ")+size+"px Arial, Helvetica, sans-serif";
    ctx.fillText(String(text||""),x,y,maxWidth);
  }
  function composeCanvas(source,metadata){
    if(!source || !source.width || !source.height)throw Error("Grafik ist leer.");
    const out=document.createElement("canvas");
    out.width=WIDTH;out.height=HEIGHT;
    const ctx=out.getContext("2d",{alpha:false});
    if(!ctx)throw Error("Export-Canvas konnte nicht erstellt werden.");
    ctx.fillStyle="#ffffff";ctx.fillRect(0,0,WIDTH,HEIGHT);
    ctx.textBaseline="top";
    ctx.fillStyle="#19324a";
    line(ctx,metadata.title||"Climate Dashboard Deutschland",MARGIN,46,WIDTH-MARGIN*2,39,true);
    ctx.fillStyle="#58697c";
    line(ctx,metadata.subtitle||"Climate Dashboard Deutschland · hochauflösender Export",
      MARGIN,105,WIDTH-MARGIN*2,20,false);
    ctx.strokeStyle="#cfd9e4";ctx.lineWidth=2;
    ctx.beginPath();ctx.moveTo(MARGIN,145);ctx.lineTo(WIDTH-MARGIN,145);ctx.stroke();
    const availableW=WIDTH-MARGIN*2,availableH=HEIGHT-HEADER-FOOTER;
    const scale=Math.min(availableW/source.width,availableH/source.height);
    const drawW=source.width*scale,drawH=source.height*scale;
    ctx.drawImage(source,(WIDTH-drawW)/2,HEADER+(availableH-drawH)/2,drawW,drawH);
    ctx.strokeStyle="#cfd9e4";
    ctx.beginPath();ctx.moveTo(MARGIN,HEIGHT-FOOTER+12);
    ctx.lineTo(WIDTH-MARGIN,HEIGHT-FOOTER+12);ctx.stroke();
    ctx.fillStyle="#405369";
    const provenance=String(metadata.source||"Quelle und Bezugszeitraum: siehe Diagramm/Kartenlegende.");
    // Keep provenance readable, even for very long station or model names:
    // split into at most two short lines instead of horizontally squashing text.
    const lines=[];
    const ctxWidth=WIDTH-MARGIN*2;
    const words=provenance.split(/\s+/).filter(Boolean);
    let current="";
    ctx.font="400 19px Arial, Helvetica, sans-serif";
    for(const word of words){
      const next=current?current+" "+word:word;
      if(current&&ctx.measureText?.(next).width>ctxWidth){
        lines.push(current);current=word;
      }else current=next;
    }
    if(current)lines.push(current);
    for(let i=0;i<Math.min(2,lines.length);i++)
      line(ctx,lines[i],MARGIN,HEIGHT-FOOTER+27+i*25,ctxWidth,19,false);
    ctx.fillStyle="#52677b";
    line(ctx,"Erstellt: "+new Date().toLocaleString("de-DE")+" · Climate Dashboard Deutschland"
      +" · Werte und Einheiten unverändert",
      MARGIN,HEIGHT-FOOTER+83,ctxWidth,16,false);
    return out;
  }
  function renderChart(chart,metadata){
    if(!chart || !chart.data || !root.Chart)throw Error("Diagramm nicht verfügbar.");
    const canvas=document.createElement("canvas");
    canvas.width=WIDTH-MARGIN*2;canvas.height=HEIGHT-HEADER-FOOTER;
    const originalOptions=chart.config?._config?.options || chart.config?.options || {};
    const options=copy(originalOptions);
    options.responsive=false;
    options.maintainAspectRatio=false;
    options.animation=false;
    options.devicePixelRatio=1;
    options.plugins=options.plugins||{};
    // The site-wide mobile Chart.js plugin must not reduce export tick labels.
    options.plugins.climateMobileLegibilityV1=false;
    options.plugins.zoom=false;
    options.plugins.datalabels={display:false};
    const legend=options.plugins.legend||{};
    if(legend.display!==false){
      legend.display=true;
      legend.labels=legend.labels||{};
      legend.labels.font={...(legend.labels.font||{}),size:18};
      legend.labels.boxWidth=24;
      legend.labels.color="#22374d";
    }
    options.plugins.legend=legend;
    for(const [axis,config] of Object.entries(options.scales||{})){
      if(!config || typeof config!=="object")continue;
      config.ticks=config.ticks||{};
      if(config.ticks.display!==false && config.ticks.autoSkip!==false){
        config.ticks.maxTicksLimit=Math.max(Number(config.ticks.maxTicksLimit)||0,axis==="x"?17:10);
        config.ticks.maxRotation=axis==="x"?35:0;
      }
      config.ticks.font={...(config.ticks.font||{}),size:19};
      config.ticks.color="#24384d";
      if(config.grid?.display!==false)config.grid={...(config.grid||{}),color:"#d9e1e8"};
      if(config.title?.display){
        config.title.font={...(config.title.font||{}),size:22};
        config.title.color="#24384d";
      }
    }
    if(options.plugins.title?.display){
      options.plugins.title.font={...(options.plugins.title.font||{}),size:25};
      options.plugins.title.padding=16;
      options.plugins.title.color="#19324a";
    }
    // Preserve user-controlled visibility without modifying the source chart.
    const datasets=chart.data.datasets.map((dataset,index)=>{
      const cloned=copy(dataset);
      cloned.hidden=typeof chart.isDatasetVisible==="function"
        ?!chart.isDatasetVisible(index):Boolean(dataset.hidden);
      return cloned;
    });
    const config={
      type:chart.config.type,
      data:{labels:copy(chart.data.labels),datasets},
      options
    };
    const scopedPlugins=chart.config?._config?.plugins;
    if(Array.isArray(scopedPlugins))config.plugins=scopedPlugins;
    let cloneChart;
    try{
      cloneChart=new root.Chart(canvas,config);
      cloneChart.update("none");
      return composeCanvas(canvas,metadata);
    }finally{
      if(cloneChart)cloneChart.destroy();
    }
  }
  root.DashboardExportHQ=Object.freeze({copy,composeCanvas,renderChart,WIDTH,HEIGHT});
})(window);


/* Broadcast maps: native raster layers, editable annotation objects, no UI screenshot. */
(function(){
"use strict";
if(typeof document==="undefined")return;
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");
function filename(kind,ext){
 const ids=kind==="hyras"?["hyrasParameterSelect","hyrasPeriodSelect","hyrasMetricSelect","hyrasReferenceSelect"]:["era5EuropeParameter","era5EuropePeriod","era5EuropeMapYear","era5EuropeView"];
 return [kind==="hyras"?"HYRAS":"ERA5-Land-Europa",...ids.map(id=>$(id)?.value).filter(Boolean)].join("_").replace(/[^a-zA-Z0-9_-]/g,"_")+"."+ext;
}
function canvas(w,h){const c=document.createElement("canvas");c.width=w;c.height=h;return c;}
async function bitmap(img){
 if(!img?.src)throw Error("Keine fertige Karte ausgewählt.");
 const r=await fetch(img.currentSrc||img.src,{cache:"no-store"});if(!r.ok)throw Error("Kartenbild HTTP "+r.status);
 const b=await r.blob();const im=await createImageBitmap(b);const out=canvas(im.width,im.height);out.getContext("2d").drawImage(im,0,0);im.close?.();return out;
}
function colors(node){return [...(node?.querySelectorAll("span")||[])].map(e=>({label:e.textContent.trim(),color:e.querySelector("i")?.style.backgroundColor||e.querySelector("i")?.style.background})).filter(x=>x.color&&x.label);}
async function source(kind){
 if(kind==="hyras"){
  const root=$("hyrasMapFrame");
  const native=root?.querySelector(".hyras-temperature-native-canvas");
  if(native?.broadcastMap){const m=native.broadcastMap;return {...m,layers:[{name:"HYRAS-Raster",image:m.data},...(m.borders?[{name:"Grenzen-Raster",image:m.borders}]:[])],note:m.borders?"Raster und Grenzmaske getrennt.":"Grenzmaske nicht verfügbar."};}
  const map=root?.querySelector(".hyras-dynamic-wrap canvas");
  if(map?.width&&map?.height)return {layers:[{name:"Kartenraster",image:map}],title:root.querySelector(".hyras-dynamic-title")?.textContent||"HYRAS Deutschland",subtitle:root.querySelector(".hyras-dynamic-subtitle")?.textContent||$("hyrasDataThrough")?.textContent,source:"DWD HYRAS-DE",legend:colors(root.querySelector(".hyras-dynamic-legend")),note:"Diese Ansicht enthält bereits eingebrannte Grenzen."};
  const img=root?.querySelector(".hyras-tmean-anomaly-preview-link:not([hidden]) img, .hyras-dynamic-wrap img");
  if(img)return {layers:[{name:"Originalkarte-Raster",image:await bitmap(img)}],title:img.alt||"HYRAS Deutschland",subtitle:$("hyrasDataThrough")?.textContent,source:"DWD HYRAS-DE",legend:[],note:"Originalkarte enthält bereits Beschriftung und Grenzen."};
  throw Error("HYRAS-Karte noch nicht bereit.");
 }
 const img=$("era5EuropeImage");
 const base=await bitmap(img);
 const overlay=$("era5EuropeHistoryCanvas");
 if(overlay){if(!overlay.width||overlay.width!==base.width||overlay.height!==base.height)throw Error("Historisches ERA5-Raster noch nicht fertig.");}
 const historical=!!overlay;
 const legend=historical?[...($("era5EuropeImageStage")?.querySelectorAll(".era5-europe-history-legend span")||[])].map(x=>x.textContent.trim()).join(" bis "):"";
 return {layers:[{name:historical?"Geografische-Basiskarte":"ERA5-Originalkarte",image:base},...(historical?[{name:"ERA5-Datenraster",image:overlay,opacity:.9}]:[])],title:$("era5EuropeMapTitle")?.textContent||"ERA5-Land Europa",subtitle:[$("era5EuropeMapSubtitle")?.textContent?.split(" · Karte anklicken")[0],$("era5EuropeDataKpi")?.textContent,legend?("Skala: "+legend):""].filter(Boolean).join(" · "),source:"Copernicus C3S / ECMWF · ERA5-Land",legend:[],note:historical?"Basiskarte und Datenraster getrennt; Legendenendwerte als Text.":"Original-PNG ist eine Rasterebene; darin vorhandene Grenzen und Texte sind nicht einzeln editierbar."};
}
function scene(m,transparent,clean){
 const W=1920,H=1080,background=transparent?null:"#ffffff",fg=transparent?"#19324a":"#19324a",items=[];
 if(background)items.push({group:"Hintergrund",kind:"rect",x:0,y:0,w:W,h:H,color:background});
 const hasLegend=!clean&&m.legend?.length,top=clean?32:130,bottom=clean?1048:hasLegend?918:995;
 const first=m.layers[0].image,ratio=Math.min(1800/first.width,(bottom-top)/first.height),w=first.width*ratio,h=first.height*ratio,x=(W-w)/2,y=top+(bottom-top-h)/2;
 for(const layer of m.layers)items.push({group:layer.name,kind:"image",x,y,w,h,opacity:layer.opacity??1,src:layer.image.toDataURL("image/png")});
 const text=(group,value,x,y,size,weight=400,align="left")=>items.push({group,kind:"text",value,x,y,size,weight,align,color:fg});
 if(!clean){
 text("Titel",m.title,64,62,46,700);text("Zeitraum",m.subtitle||"",64,106,26);
 if(hasLegend){const n=m.legend.length,step=1770/n;for(let i=0;i<n;i++){const e=m.legend[i],x=75+i*step;items.push({group:"Legende",kind:"rect",x,y:938,w:step,h:32,color:e.color});text("Legende",e.label,x+step/2,997,22,400,"center");}}
 text("Quelle",m.source,64,1048,23);
 }
 return items;
}
function svg(items){
 const groups=new Map();for(const i of items){if(!groups.has(i.group))groups.set(i.group,[]);groups.get(i.group).push(i);}
 const item=i=>i.kind==="image"?'<image x="'+i.x+'" y="'+i.y+'" width="'+i.w+'" height="'+i.h+'" opacity="'+i.opacity+'" href="'+i.src+'" xlink:href="'+i.src+'"/>':i.kind==="rect"?'<rect x="'+i.x+'" y="'+i.y+'" width="'+i.w+'" height="'+i.h+'" fill="'+esc(i.color)+'"/>':'<text x="'+i.x+'" y="'+i.y+'" fill="'+i.color+'" font-family="Arial,sans-serif" font-size="'+i.size+'" font-weight="'+i.weight+'" text-anchor="'+(i.align==="center"?"middle":"start")+'">'+esc(i.value)+'</text>';
 return '<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="1920" height="1080" viewBox="0 0 1920 1080"><desc>Native Kartenraster; separate Texte und vorhandene Kartenebenen. Keine künstliche Datenauflösung.</desc>'+[...groups].map(([name,arr],i)=>'<g id="layer-'+i+'" inkscape:groupmode="layer" inkscape:label="'+esc(name)+'"><title>'+esc(name)+'</title>'+arr.map(item).join("")+'</g>').join("")+'</svg>';
}
async function pdf(items){
 if(!window.jspdf?.jsPDF){if(window.dashboardExportLibraries?.pdf)await window.dashboardExportLibraries.pdf();else throw Error("PDF-Bibliothek nicht geladen.");}
 const p=new window.jspdf.jsPDF({orientation:"landscape",unit:"pt",format:[1920,1080],compress:true});
 for(const i of items){
  if(i.kind==="image"){if(i.opacity!==1&&p.GState){p.saveGraphicsState();p.setGState(new p.GState({opacity:i.opacity}));}p.addImage(i.src,"PNG",i.x,i.y,i.w,i.h,undefined,"FAST");if(i.opacity!==1&&p.GState)p.restoreGraphicsState();}
  if(i.kind==="rect"){p.setFillColor(i.color);p.rect(i.x,i.y,i.w,i.h,"F");}
  if(i.kind==="text"){p.setFont("helvetica",i.weight>=600?"bold":"normal");p.setTextColor(i.color);p.setFontSize(i.size);p.text(String(i.value),i.x,i.y,{align:i.align});}
 }
 return p.output("blob");
}
async function png(items,width){
 const out=canvas(width,width*9/16),ctx=out.getContext("2d");ctx.scale(width/1920,width/1920);
 for(const i of items){
  if(i.kind==="image"){const img=new Image();img.src=i.src;await img.decode();ctx.save();ctx.globalAlpha=i.opacity;ctx.imageSmoothingEnabled=false;ctx.drawImage(img,i.x,i.y,i.w,i.h);ctx.restore();}
  if(i.kind==="rect"){ctx.fillStyle=i.color;ctx.fillRect(i.x,i.y,i.w,i.h);}
  if(i.kind==="text"){ctx.fillStyle=i.color;ctx.font=i.weight+" "+i.size+"px Arial,sans-serif";ctx.textAlign=i.align;ctx.fillText(String(i.value),i.x,i.y);}
 }
 return new Promise((resolve,reject)=>out.toBlob(b=>b?resolve(b):reject(Error("PNG konnte nicht erstellt werden.")),"image/png"));
}
async function originalVector(format){
 const img=$("era5EuropeImage");if(!img||$("era5EuropeHistoryCanvas"))throw Error("Original-Vektorkarte nur für neu gerenderte aktuelle ERA5-Temperaturkarten verfügbar.");
 const url=new URL(img.currentSrc||img.src,location.href);if(!url.pathname.endsWith(".png"))throw Error("Kartenformat nicht unterstützt.");
 const root=url.href.replace(/\.png(?=\?|$)/,"");
 const path=ext=>{const u=new URL(url);u.pathname=u.pathname.replace(/\.png$/,"."+ext);return u.href;};
 const m=await fetch(path("broadcast.json"),{cache:"no-store"});if(!m.ok)throw Error("Original-Vektorkarte noch nicht erzeugt. Bitte 16:9-PNG oder Hybrid-SVG verwenden.");
 const manifest=await m.json(),raw=await fetch(url.href,{cache:"no-store"});if(!raw.ok)throw Error("Original-PNG nicht erreichbar.");
 const hash=[...new Uint8Array(await crypto.subtle.digest("SHA-256",await raw.arrayBuffer()))].map(x=>x.toString(16).padStart(2,"0")).join("");
 if(hash!==manifest.png_sha256)throw Error("Vektorkarte gehört zu einem anderen Datenstand; Export abgebrochen.");
 const result=await fetch(path(format),{cache:"no-store"});if(!result.ok)throw Error("Original-Vektorkarte nicht verfügbar.");
 const bytes=await result.arrayBuffer(),expected=manifest[format+"_sha256"],actual=[...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(x=>x.toString(16).padStart(2,"0")).join("");
 if(actual!==expected)throw Error("Vektordatei stimmt nicht mit dem publizierten Datenstand überein.");
 return new Blob([bytes],{type:format==="svg"?"image/svg+xml":"application/pdf"});
}
function save(blob,name){const u=URL.createObjectURL(blob),a=document.createElement("a");a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),30000);}
function mount(kind,host){
 if(!host||host.querySelector("[data-broadcast-map-export]"))return;
 const box=document.createElement("div");box.dataset.broadcastMapExport=kind;box.style.cssText="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0;font-size:13px;";
 const format=document.createElement("select"),background=document.createElement("select"),layout=document.createElement("select"),btn=document.createElement("button"),status=document.createElement("span");
 for(const [v,t] of [["png4k","PNG 4K (16:9)"],["pnghd","PNG Full-HD (16:9)"],["svg","SVG (Raster + Ebenen)"],["pdf","PDF (Raster + Vektor)"],...(kind==="era5"?[["original-svg","Original-SVG (Vektorgrenzen)"],["original-pdf","Original-PDF (Vektorgrenzen)"]]:[["data","Datenraster PNG transparent"],["borders","Grenzmaske PNG transparent"]])])format.add(new Option(t,v));
 background.add(new Option("Weiß","white"));background.add(new Option("Transparent","transparent"));layout.add(new Option("Mit Titel und Legende","full"));layout.add(new Option("Nur Karte","clean"));
 format.setAttribute("aria-label","Dateiformat");background.setAttribute("aria-label","Hintergrund");layout.setAttribute("aria-label","Kartenlayout");btn.type="button";btn.className="action";btn.textContent="Sendegrafik exportieren";status.setAttribute("role","status");status.style.flexBasis="100%";status.textContent=kind==="era5"?"Original-Vektorgrenzen nur für neu erzeugte Temperaturkarten. Vorhandene PNGs bleiben Raster.":"Rasterflächen bleiben original; verfügbare Grenzmaske und Beschriftungen werden separat exportiert.";
 btn.onclick=async()=>{btn.disabled=true;const f=format.value;try{status.textContent="Export wird erstellt …";let blob,ext;
 if(f.startsWith("original-")){ext=f.slice(9);blob=await originalVector(ext);status.textContent="Originalkarte: Rasterdaten und Vektorgrenzen.";}
 else {const m=await source(kind);if(f==="data"||f==="borders"){const layer=f==="data"?m.layers.find(x=>x.name==="HYRAS-Raster"):m.layers.find(x=>x.name==="Grenzen-Raster");if(!layer)throw Error("Diese getrennte Ebene ist für die gewählte Karte nicht verfügbar.");blob=await new Promise((res,rej)=>layer.image.toBlob(b=>b?res(b):rej(Error("PNG fehlgeschlagen")),"image/png"));ext="png";}else{const items=scene(m,background.value==="transparent",layout.value==="clean");ext=f.startsWith("png")?"png":f;blob=ext==="svg"?new Blob([svg(items)],{type:"image/svg+xml"}):ext==="pdf"?await pdf(items):await png(items,f==="png4k"?3840:1920);}status.textContent=m.note+(background.value==="transparent"&&kind==="era5"?" Vorhandene weiße Bildflächen bleiben erhalten.":"");}
 save(blob,filename(kind,ext).replace("."+ext,"_"+f+"."+ext));
 }catch(e){status.textContent=e.message;}finally{btn.disabled=false;}};
 box.append(format,background,layout,btn,status);host.append(box);
}
function init(){mount("hyras",document.querySelector(".hyras-map-actions"));mount("era5",document.querySelector(".era5-europe-map-actions"));}
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
