(function(){
"use strict";

const SST_ARCHIVE_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/sst-archive";
let sstManifestPromise=null;
let sstManifest=null;
let sstMounted=false;
let sstState={region:"europe",view:"absolute",date:null};

function sstEl(id){return document.getElementById(id);}
function sstIsoDate(value){
  const date=value instanceof Date?value:new Date(`${value}T00:00:00Z`);
  if(Number.isNaN(date.getTime()))return null;
  return date.toISOString().slice(0,10);
}
function sstShiftDate(iso,days){
  const date=new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate()+days);
  return sstIsoDate(date);
}
function sstRegionLabel(region){return sstManifest?.regions?.[region]?.label||region;}
function sstViewLabel(view){return view==="anomaly"?"SST-Anomalie zu 1991–2020":"SST absolut";}
function sstSetStatus(message,{show=true}={}){
  const status=sstEl("sstStatus");if(!status)return;
  status.textContent=message||"";status.hidden=!show;
}
function sstEnsureStatsBlock(){
  let block=sstEl("sstStats");
  if(block)return block;
  const shell=sstEl("sstMapImage")?.closest?.(".sst-europe-map-shell");
  if(!shell)return null;
  block=document.createElement("div");
  block.id="sstStats";
  block.className="sst-europe-stats";
  block.hidden=true;
  block.setAttribute("aria-live","polite");
  shell.insertAdjacentElement("afterend",block);
  return block;
}
function sstFormatStat(value,{signed=false}={}){
  const number=Number(value);
  if(!Number.isFinite(number))return "–";
  const formatted=Math.abs(number).toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2});
  if(number<0)return `−${formatted} °C`;
  if(signed&&number>0)return `+${formatted} °C`;
  return `${formatted} °C`;
}
function sstStatsLine(stats,view){
  if(!stats)return "";
  const signed=view==="anomaly";
  const title=signed?"Abweichung im Kartenausschnitt":"Temperatur im Kartenausschnitt";
  return `${title}: Mittel ${sstFormatStat(stats.mean,{signed})} · Minimum ${sstFormatStat(stats.min,{signed})} · Maximum ${sstFormatStat(stats.max,{signed})}`;
}
function sstRenderStats(stats,view){
  const block=sstEnsureStatsBlock();if(!block)return;
  if(!stats||![stats.mean,stats.min,stats.max].every(value=>Number.isFinite(Number(value)))){
    block.textContent="";block.hidden=true;return;
  }
  const signed=view==="anomaly";
  const title=signed?"Abweichung im Kartenausschnitt":"Temperatur im Kartenausschnitt";
  block.innerHTML=`<span class="sst-europe-stats-title">${title}</span><span><strong>Mittel</strong> ${sstFormatStat(stats.mean,{signed})}</span><span><strong>Minimum</strong> ${sstFormatStat(stats.min,{signed})}</span><span><strong>Maximum</strong> ${sstFormatStat(stats.max,{signed})}</span>`;
  block.hidden=false;
}

async function loadSstManifest(){
  if(!sstManifestPromise){
    sstManifestPromise=fetch(`${SST_ARCHIVE_BASE}/manifest.json?t=${Date.now()}`,{cache:"no-store"})
      .then(r=>{if(!r.ok)throw new Error(`SST manifest HTTP ${r.status}`);return r.json();})
      .then(payload=>{
        if(Number(payload?.schema_version)!==1)throw new Error("Unbekannte SST-Manifest-Version");
        return payload;
      })
      .catch(error=>{sstManifestPromise=null;throw error;});
  }
  return sstManifestPromise;
}
window.loadSstManifest=loadSstManifest;

function sstPopulateRegions(){
  const select=sstEl("sstRegion");if(!select||!sstManifest)return;
  const previous=select.value||sstState.region;
  select.innerHTML=Object.entries(sstManifest.regions||{}).map(([id,meta])=>`<option value="${id}">${meta.label||id}</option>`).join("");
  select.value=sstManifest.regions?.[previous]?previous:Object.keys(sstManifest.regions||{})[0]||"europe";
  sstState.region=select.value;
}

function sstUpdateDateBounds(){
  const input=sstEl("sstDate");if(!input||!sstManifest)return;
  input.min=sstManifest.archive_start||"2020-01-01";
  input.max=sstManifest.data_through||"";
  input.value=sstState.date||sstManifest.data_through||"";
}

function sstRenderTimeline(){
  const wrap=sstEl("sstTimeline");if(!wrap||!sstManifest||!sstState.date)return;
  wrap.innerHTML="";
  for(let offset=29;offset>=0;offset--){
    const iso=sstShiftDate(sstState.date,-offset);
    const available=Boolean(sstManifest.dates?.[iso]);
    const button=document.createElement("button");
    button.type="button";
    button.disabled=!available;
    button.dataset.date=iso;
    button.title=available?iso:`${iso} · keine Karte`;
    const d=new Date(`${iso}T00:00:00Z`);
    button.textContent=`${String(d.getUTCDate()).padStart(2,"0")}.${String(d.getUTCMonth()+1).padStart(2,"0")}`;
    if(iso===sstState.date)button.classList.add("active");
    button.addEventListener("click",()=>sstSelectDate(iso));
    wrap.appendChild(button);
  }
}

function sstArchiveUrl(rel){return `${SST_ARCHIVE_BASE}/${String(rel).replace(/^\/+/,"")}`;}

function sstRenderMap(){
  if(!sstManifest||!sstState.date)return;
  const region=sstState.region,view=sstState.view,date=sstState.date;
  const manifest=sstManifest;
  const rel=manifest.dates?.[date]?.regions?.[region]?.[view];
  const stats=manifest.dates?.[date]?.statistics?.[region]?.[view];
  const image=sstEl("sstMapImage");
  const dataThrough=sstEl("sstDataThrough");
  if(dataThrough)dataThrough.textContent=`Datenstand: ${sstManifest.data_through||"–"}`;
  sstRenderStats(stats,view);
  if(!image)return;
  if(!rel){
    image.removeAttribute("src");image.alt="Keine SST-Karte verfügbar";
    sstSetStatus("Für dieses Datum liegt keine SST-Karte vor.");
    sstEnableExports(false);
    sstRenderTimeline();
    return;
  }
  sstSetStatus("SST-Karte wird geladen …");
  sstEnableExports(false);
  image.crossOrigin="anonymous";
  image.alt=`${sstRegionLabel(region)} · ${sstViewLabel(view)} · ${date}`;
  image.onload=()=>{sstSetStatus("",{show:false});sstEnableExports(true);};
  image.onerror=()=>{sstSetStatus("Die SST-Karte konnte nicht geladen werden.");sstEnableExports(false);};
  image.src=`${sstArchiveUrl(rel)}?v=${encodeURIComponent(sstManifest.generated_at||sstManifest.data_through||"1")}`;
  sstRenderTimeline();
}

function sstSelectDate(iso){
  const normalized=sstIsoDate(iso);if(!normalized)return;
  sstState.date=normalized;
  const input=sstEl("sstDate");if(input)input.value=normalized;
  sstRenderMap();
}

function sstEnableExports(enabled){
  [sstEl("sstPngDownload"),sstEl("sstPdfDownload")].forEach(button=>{if(button)button.disabled=!enabled;});
}

function sstBindControls(){
  const region=sstEl("sstRegion"),view=sstEl("sstView"),date=sstEl("sstDate");
  if(region&&!region.dataset.sstBound){region.addEventListener("change",()=>{sstState.region=region.value;sstRenderMap();});region.dataset.sstBound="1";}
  if(view&&!view.dataset.sstBound){view.addEventListener("change",()=>{sstState.view=view.value;sstRenderMap();});view.dataset.sstBound="1";}
  if(date&&!date.dataset.sstBound){date.addEventListener("change",()=>sstSelectDate(date.value));date.dataset.sstBound="1";}
  const prev=sstEl("sstPrevDay");if(prev&&!prev.dataset.sstBound){prev.addEventListener("click",()=>sstSelectDate(sstShiftDate(sstState.date,-1)));prev.dataset.sstBound="1";}
  const next=sstEl("sstNextDay");if(next&&!next.dataset.sstBound){next.addEventListener("click",()=>sstSelectDate(sstShiftDate(sstState.date,1)));next.dataset.sstBound="1";}
  const latest=sstEl("sstLatestDay");if(latest&&!latest.dataset.sstBound){latest.addEventListener("click",()=>sstSelectDate(sstManifest?.data_through));latest.dataset.sstBound="1";}
  const png=sstEl("sstPngDownload");if(png&&!png.dataset.sstBound){png.addEventListener("click",downloadSstPng);png.dataset.sstBound="1";}
  const pdf=sstEl("sstPdfDownload");if(pdf&&!pdf.dataset.sstBound){pdf.addEventListener("click",downloadSstPdf);pdf.dataset.sstBound="1";}
}

async function composeSstExportCanvas(){
  const image=sstEl("sstMapImage");
  if(!image?.src||!image.complete||!image.naturalWidth)throw new Error("Die SST-Karte ist noch nicht geladen.");
  const stats=sstManifest?.dates?.[sstState.date]?.statistics?.[sstState.region]?.[sstState.view];
  const statsLine=sstStatsLine(stats,sstState.view);
  const footerHeight=statsLine?120:90;
  const canvas=document.createElement("canvas");
  canvas.width=image.naturalWidth;canvas.height=image.naturalHeight+footerHeight;
  const ctx=canvas.getContext("2d");
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.drawImage(image,0,0,image.naturalWidth,image.naturalHeight);
  ctx.fillStyle="#202428";ctx.font="600 20px Arial,sans-serif";
  ctx.fillText(`${sstState.date} · ${sstRegionLabel(sstState.region)} · ${sstViewLabel(sstState.view)}`,28,image.naturalHeight+32);
  if(statsLine){
    ctx.fillStyle="#202428";ctx.font="600 16px Arial,sans-serif";
    ctx.fillText(statsLine,28,image.naturalHeight+63);
  }
  ctx.fillStyle="#5f676d";ctx.font="15px Arial,sans-serif";
  const source=sstState.view==="anomaly"?"NASA/JPL MUR SST v4.1 · Referenz NOAA OISST 1991–2020":"NASA/JPL MUR SST v4.1";
  ctx.fillText(source,28,image.naturalHeight+(statsLine?96:65));
  return canvas;
}
window.composeSstExportCanvas=composeSstExportCanvas;

function sstFilename(extension){return `SST_${sstState.region}_${sstState.view}_${sstState.date}.${extension}`;}
function sstDownloadBlob(blob,filename){
  const url=URL.createObjectURL(blob);const link=document.createElement("a");
  link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();
  window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}

async function downloadSstPng(){
  try{
    const canvas=await composeSstExportCanvas();
    const fallback=()=>{const link=document.createElement("a");link.download=sstFilename("png");link.href=canvas.toDataURL("image/png");document.body.appendChild(link);link.click();link.remove();};
    if(canvas.toBlob)canvas.toBlob(blob=>blob?sstDownloadBlob(blob,sstFilename("png")):fallback(),"image/png");
    else fallback();
  }catch(error){console.error("SST PNG Export:",error);window.alert(`PNG konnte nicht erstellt werden: ${error.message}`);}
}
window.downloadSstPng=downloadSstPng;

async function downloadSstPdf(){
  try{
    const canvas=await composeSstExportCanvas();
    const JsPdf=window.jspdf?.jsPDF;if(!JsPdf)throw new Error("jsPDF ist nicht geladen.");
    const orientation=canvas.width>=canvas.height?"landscape":"portrait";
    const pdf=new JsPdf({orientation,unit:"mm",format:"a4"});
    const pageWidth=pdf.internal.pageSize.getWidth(),pageHeight=pdf.internal.pageSize.getHeight();
    const margin=8,maxWidth=pageWidth-2*margin,maxHeight=pageHeight-2*margin;
    const scale=Math.min(maxWidth/canvas.width,maxHeight/canvas.height);
    const width=canvas.width*scale,height=canvas.height*scale;
    pdf.addImage(canvas.toDataURL("image/png"),"PNG",(pageWidth-width)/2,(pageHeight-height)/2,width,height,undefined,"FAST");
    pdf.save(sstFilename("pdf"));
  }catch(error){console.error("SST PDF Export:",error);window.alert(`PDF konnte nicht erstellt werden: ${error.message}`);}
}
window.downloadSstPdf=downloadSstPdf;

async function mountSstEurope(){
  if(sstMounted&&sstManifest){sstRenderMap();return;}
  sstSetStatus("SST-Archiv wird geladen …");
  try{
    sstManifest=await loadSstManifest();
    sstPopulateRegions();
    sstState.view=sstEl("sstView")?.value||"absolute";
    sstState.date=sstManifest.data_through||sstManifest.available_dates?.at(-1)||null;
    sstUpdateDateBounds();
    sstBindControls();
    sstMounted=true;
    sstRenderMap();
  }catch(error){console.error("SST Europa:",error);sstSetStatus(`SST-Daten konnten nicht geladen werden: ${error.message}`);}
}
window.mountSstEurope=mountSstEurope;

document.addEventListener("click",event=>{
  const button=event.target.closest?.(".tab-button");
  if(button?.getAttribute("onclick")?.includes("switchTab('sst-europe')"))window.setTimeout(mountSstEurope,0);
});
document.addEventListener("DOMContentLoaded",()=>{
  if(sstEl("sst-europe")?.classList.contains("active"))mountSstEurope();
});
})();
