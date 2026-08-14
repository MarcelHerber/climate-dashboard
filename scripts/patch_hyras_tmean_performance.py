#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_TMEAN_PERFORMANCE_V1"
FRONTEND_MARKER = "// HYRAS_TMEAN_FRONTEND_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"HYRAS-Tmean-Speedpatch fehlgeschlagen ({label}): Treffer={count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"HYRAS-Tmean-Speedpatch fehlgeschlagen ({label}): Treffer={count}")
    return new


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if FRONTEND_MARKER not in text:
        raise RuntimeError("HYRAS Tmean ist noch nicht im Frontend eingebaut.")

    if MARKER in text:
        print("HYRAS Tmean Performance V1 ist bereits aktiv.")
        return 0

    state_old = 'const hyrasTmeanFileCache=new Map();\nconst hyrasTmeanMonthCache=new Map();'
    state_new = '''const hyrasTmeanFileCache=new Map();
const hyrasTmeanMonthCache=new Map();
// HYRAS_TMEAN_PERFORMANCE_V1
const HYRAS_TMEAN_CURRENT_DISPLAY_FACTOR=2;
let hyrasTmeanBoundaryBitmapPromise=null;
let hyrasTmeanExportObjectUrl=null;'''
    text = replace_once(text, state_old, state_new, "Performance-State")

    decode_new = r'''function hyrasTmeanDecodePlane(raw,width,height,scale=100,missing=-32768,offset=0,factor=1){
  const step=Math.max(1,Math.floor(Number(factor)||1));
  const outWidth=Math.ceil(width/step),outHeight=Math.ceil(height/step),n=outWidth*outHeight;
  const values=new Float32Array(n),valid=new Uint8Array(n);
  let out=0;
  for(let oy=0;oy<outHeight;oy++){
    const sy=Math.min(height-1,oy*step);
    const row=offset+sy*width;
    for(let ox=0;ox<outWidth;ox++,out++){
      const sx=Math.min(width-1,ox*step),q=raw[row+sx];
      if(q===undefined||q===missing){values[out]=NaN;continue;}
      values[out]=Number(q)/scale;valid[out]=1;
    }
  }
  return {values,valid,width:outWidth,height:outHeight,resolutionKm:step};
}'''
    text = regex_once(
        text,
        r'function hyrasTmeanDecodePlane\(raw,width,height,scale=100,missing=-32768,offset=0\)\{.*?\n\}(?=\nasync function hyrasTmeanEnsureLoaded)',
        decode_new,
        "2-km-Dekodierung",
    )

    draw_new = r'''async function hyrasTmeanBoundaryBitmap(){
  const boundary=hyrasIndex?.interactive?.boundary_overlay_1km;
  if(!boundary)return null;
  if(!hyrasTmeanBoundaryBitmapPromise){
    hyrasTmeanBoundaryBitmapPromise=fetch(`${HYRAS_DATA_BASE}/${boundary}`,{cache:"force-cache"})
      .then(response=>{if(!response.ok)throw new Error(`HYRAS-Grenzmaske fehlt (${response.status}).`);return response.blob();})
      .then(blob=>createImageBitmap(blob))
      .catch(error=>{hyrasTmeanBoundaryBitmapPromise=null;throw error;});
  }
  return hyrasTmeanBoundaryBitmapPromise;
}
function hyrasTmeanResetExportLink(){
  const link=document.getElementById("hyrasOpenImage");
  if(link)link.onclick=null;
  if(hyrasTmeanExportObjectUrl){
    URL.revokeObjectURL(hyrasTmeanExportObjectUrl);
    hyrasTmeanExportObjectUrl=null;
  }
}
function hyrasTmeanInstallLazyExport(link,canvas,mode,boundaryPromise){
  if(!link)return;
  hyrasTmeanResetExportLink();
  link.textContent="PNG herunterladen";
  link.target="";
  link.removeAttribute("download");
  link.href="#";
  link.style.display="inline-block";
  link.onclick=async event=>{
    event.preventDefault();
    try{await boundaryPromise;}catch(_){}
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/png"));
    if(!blob)return;
    if(hyrasTmeanExportObjectUrl)URL.revokeObjectURL(hyrasTmeanExportObjectUrl);
    hyrasTmeanExportObjectUrl=URL.createObjectURL(blob);
    const a=document.createElement("a");
    a.href=hyrasTmeanExportObjectUrl;
    a.download=`hyras_tmean_${mode}.png`;
    document.body.appendChild(a);a.click();a.remove();
    window.setTimeout(()=>{
      if(hyrasTmeanExportObjectUrl){
        URL.revokeObjectURL(hyrasTmeanExportObjectUrl);
        hyrasTmeanExportObjectUrl=null;
      }
    },1500);
  };
}
async function hyrasTmeanDrawMap(raster,{title,subtitle,mode,resolutionKm}){
  const raw=document.createElement("canvas");
  raw.width=raster.width;raw.height=raster.height;
  const rctx=raw.getContext("2d",{alpha:true}),img=rctx.createImageData(raw.width,raw.height);
  for(let i=0,j=0;i<raster.values.length;i++,j+=4){
    if(!raster.valid[i]){img.data[j+3]=0;continue;}
    const [r,g,b,a]=hyrasTmeanColor(raster.values[i],mode);
    img.data[j]=r;img.data[j+1]=g;img.data[j+2]=b;img.data[j+3]=a;
  }
  rctx.putImageData(img,0,0);

  const effectiveKm=Number(raster.resolutionKm||resolutionKm||1);
  const canvas=document.createElement("canvas");
  if(effectiveKm===2&&hyrasTmeanIndex?.grid_1km){
    canvas.width=Number(hyrasTmeanIndex.grid_1km.width)||raw.width*2;
    canvas.height=Number(hyrasTmeanIndex.grid_1km.height)||raw.height*2;
  }else{
    const displayScale=effectiveKm<=1?1:4;
    canvas.width=raw.width*displayScale;
    canvas.height=raw.height*displayScale;
  }
  const ctx=canvas.getContext("2d",{alpha:true});
  ctx.imageSmoothingEnabled=false;
  ctx.drawImage(raw,0,0,canvas.width,canvas.height);

  const frame=document.getElementById("hyrasMapFrame");
  frame.innerHTML="";
  const wrap=document.createElement("div");
  wrap.className="hyras-dynamic-wrap";
  wrap.innerHTML=`<div class="hyras-dynamic-title">${title}</div><div class="hyras-dynamic-subtitle">${subtitle}</div>`;
  wrap.appendChild(canvas);
  const legend=document.createElement("div");
  legend.className="hyras-dynamic-legend";
  legend.innerHTML=hyrasTmeanLegend(mode);
  wrap.appendChild(legend);
  frame.appendChild(wrap);

  const boundaryPromise=hyrasTmeanBoundaryBitmap().then(bmp=>{
    if(!bmp)return null;
    ctx.imageSmoothingEnabled=true;
    ctx.drawImage(bmp,0,0,canvas.width,canvas.height);
    return bmp;
  }).catch(error=>{console.warn("Tmean-Grenzen:",error);return null;});

  hyrasTmeanInstallLazyExport(document.getElementById("hyrasOpenImage"),canvas,mode,boundaryPromise);
}'''
    text = regex_once(
        text,
        r'async function hyrasTmeanDrawMap\(raster,\{title,subtitle,mode,resolutionKm\}\)\{.*?\n\}(?=\nfunction hyrasTmeanSetKpis)',
        draw_new,
        "Grenzcache / Lazy-PNG",
    )

    current_old = 'const raw=await hyrasTmeanLoadI16(path),w=Number(hyrasTmeanIndex.grid_1km.width),h=Number(hyrasTmeanIndex.grid_1km.height),raster=hyrasTmeanDecodePlane(raw,w,h,100,-32768);'
    current_new = 'const raw=await hyrasTmeanLoadI16(path),w=Number(hyrasTmeanIndex.grid_1km.width),h=Number(hyrasTmeanIndex.grid_1km.height),raster=hyrasTmeanDecodePlane(raw,w,h,100,-32768,0,HYRAS_TMEAN_CURRENT_DISPLAY_FACTOR);'
    text = replace_once(text, current_old, current_new, "aktuelles 2-km-Raster")

    text = replace_once(
        text,
        'hyrasTmeanSetKpis({label:period.label,dateLabel:`${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`,currentMean:cur,referenceMean:ref,anomalyMean:anom,live:Boolean(period.live),resolutionKm:1});',
        'hyrasTmeanSetKpis({label:period.label,dateLabel:`${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`,currentMean:cur,referenceMean:ref,anomalyMean:anom,live:Boolean(period.live),resolutionKm:2});',
        "KPI-Auflösung",
    )
    text = replace_once(
        text,
        'await hyrasTmeanDrawMap(raster,{title:`HYRAS Tmean · ${period.label}`,subtitle:`${selectedMode==="anomaly"?"Abweichung 1991–2020":"2-m-Temperaturmittel"} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`,mode:selectedMode,resolutionKm:1});',
        'await hyrasTmeanDrawMap(raster,{title:`HYRAS Tmean · ${period.label}`,subtitle:`${selectedMode==="anomaly"?"Abweichung 1991–2020":"2-m-Temperaturmittel"} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`,mode:selectedMode,resolutionKm:2});',
        "Kartendarstellung 2 km",
    )

    switch_old = '  }else{\n    if(custom)custom.style.display="";hyrasRestorePrecipMetricOptions();'
    switch_new = '  }else{\n    hyrasTmeanResetExportLink();\n    if(custom)custom.style.display="";hyrasRestorePrecipMetricOptions();'
    text = replace_once(text, switch_old, switch_new, "Export beim Parameterwechsel")

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS Tmean Performance V1 aktiviert:")
    print("- aktuelle Karte: 2-km-Browserdarstellung aus nativen 1-km-Daten")
    print("- nur etwa 25 % der bisherigen Rasterzellen werden dekodiert/eingefärbt")
    print("- Grenzmaske wird einmalig gecacht")
    print("- PNG wird erst beim Klick erzeugt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
