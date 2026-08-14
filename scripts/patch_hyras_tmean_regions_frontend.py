#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"

REGION_MARKER = "// HYRAS_TMEAN_REGION_CURVES_V1"
FIX_MARKER = "// HYRAS_TMEAN_MAP_DOWNLOAD_FIX_V2"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"HYRAS-Tmean-Kartendownload-Fix fehlgeschlagen ({label}): Treffer={count}"
        )
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if FIX_MARKER in text:
        print("HYRAS Tmean Kartendownload V2 ist bereits aktiv.")
        return 0

    if REGION_MARKER not in text:
        raise RuntimeError(
            "HYRAS Tmean Gebietskurven V1 fehlen im aktuellen index.html. "
            "Bitte zuerst die Gebietskurven-Version einbauen."
        )

    old_function = '''function hyrasTmeanDownloadHref(path){return path?`${HYRAS_DATA_BASE}/tmean/${path}`:"#";}'''
    new_function = '''// HYRAS_TMEAN_MAP_DOWNLOAD_FIX_V2
function hyrasTmeanDownloadHref(path){return path?`${HYRAS_DATA_BASE}/tmean/${path}`:"#";}
async function hyrasTmeanForceMapDownload(event,path,filename){
  if(event)event.preventDefault();
  if(!path)return;

  const url=hyrasTmeanDownloadHref(path);
  const link=event?.currentTarget||null;
  const oldText=link?.textContent||"";
  if(link){
    link.style.pointerEvents="none";
    link.style.opacity=".65";
    link.textContent="Download wird vorbereitet …";
  }

  try{
    const response=await fetch(url,{cache:"no-store"});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);

    const blob=await response.blob();
    const objectUrl=URL.createObjectURL(blob);
    const a=document.createElement("a");
    a.href=objectUrl;
    a.download=filename||path.split("/").pop()||"hyras_tmean.png";
    a.style.display="none";
    document.body.appendChild(a);
    a.click();
    a.remove();

    window.setTimeout(()=>URL.revokeObjectURL(objectUrl),2000);
  }catch(error){
    console.error("HYRAS Tmean Kartendownload:",error);
    window.open(url,"_blank","noopener,noreferrer");
  }finally{
    if(link){
      link.style.pointerEvents="";
      link.style.opacity="";
      link.textContent=oldText;
    }
  }
}'''
    text = replace_once(text, old_function, new_function, "Download-Funktion")

    old_abs = '''<a class="${absClass}" ${maps.absolute?`href="${hyrasTmeanDownloadHref(maps.absolute)}" download`:""}>Temperaturkarte herunterladen</a>'''
    new_abs = '''<a class="${absClass}" ${maps.absolute?`href="${hyrasTmeanDownloadHref(maps.absolute)}" data-tmean-map="${maps.absolute}" data-tmean-filename="hyras_tmean_${period.map_key}_temperatur.png"`:""}>Temperaturkarte herunterladen</a>'''
    text = replace_once(text, old_abs, new_abs, "Temperaturkarten-Link")

    old_anom = '''<a class="${anomClass}" ${maps.anomaly?`href="${hyrasTmeanDownloadHref(maps.anomaly)}" download`:""}>Abweichungskarte 1991–2020 herunterladen</a>'''
    new_anom = '''<a class="${anomClass}" ${maps.anomaly?`href="${hyrasTmeanDownloadHref(maps.anomaly)}" data-tmean-map="${maps.anomaly}" data-tmean-filename="hyras_tmean_${period.map_key}_abweichung_1991_2020.png"`:""}>Abweichungskarte 1991–2020 herunterladen</a>'''
    text = replace_once(text, old_anom, new_anom, "Anomaliekarten-Link")

    old_after = '''  </div>`;
  const labels=rows.map(r=>{const [,m,d]=r.date.split("-");return `${d}.${m}.`;});'''
    new_after = '''  </div>`;
  frame.querySelectorAll("a[data-tmean-map]").forEach(link=>{
    link.addEventListener("click",event=>hyrasTmeanForceMapDownload(
      event,
      link.dataset.tmeanMap,
      link.dataset.tmeanFilename
    ));
  });
  const labels=rows.map(r=>{const [,m,d]=r.date.split("-");return `${d}.${m}.`;});'''
    text = replace_once(text, old_after, new_after, "Download-Listener")

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS Tmean Kartendownload V2 eingebaut:")
    print("- PNG wird per fetch geladen")
    print("- Download erfolgt über lokalen Blob")
    print("- Cross-Origin-download-Problem umgangen")
    print("- Fallback öffnet die PNG-Datei in neuem Tab")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
