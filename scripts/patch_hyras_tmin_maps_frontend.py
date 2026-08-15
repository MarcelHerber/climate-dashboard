#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_TMIN_MAP_DOWNLOADS_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"HYRAS-Tmin-Karten-Patch fehlgeschlagen ({label}): Treffer={count}"
        )
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if MARKER in text:
        print("HYRAS Tmin Karten-Downloads V1 sind bereits aktiv.")
        return 0

    if "// HYRAS_TMIN_FRONTEND_V1" not in text:
        raise RuntimeError("HYRAS Tmin Frontend V1 fehlt.")

    old_state = '''let hyrasTminRegionsClimate=null;
let hyrasTminRegionsRecords=null;
let hyrasTminRegionChart=null;'''
    new_state = '''let hyrasTminRegionsClimate=null;
let hyrasTminRegionsRecords=null;
// HYRAS_TMIN_MAP_DOWNLOADS_V1
let hyrasTminMapDownloads=null;
let hyrasTminRegionChart=null;'''
    text = replace_once(text, old_state, new_state, "Map-State")

    old_guard = '''if(hyrasTminRegionsIndex&&hyrasTminRegionsCurrent&&hyrasTminRegionsClimate&&hyrasTminRegionsRecords){
    return hyrasTminRegionsIndex;
  }'''
    new_guard = '''if(hyrasTminRegionsIndex&&hyrasTminRegionsCurrent&&hyrasTminRegionsClimate&&hyrasTminRegionsRecords&&hyrasTminMapDownloads){
    return hyrasTminRegionsIndex;
  }'''
    text = replace_once(text, old_guard, new_guard, "Load-Guard")

    old_fetch = '''const [current,climate,records]=await Promise.all([
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.current_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.climate_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.records_file),
    ]);
    hyrasTminRegionsCurrent=current;
    hyrasTminRegionsClimate=climate;
    hyrasTminRegionsRecords=records;'''
    new_fetch = '''const [current,climate,records,maps]=await Promise.all([
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.current_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.climate_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.records_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.map_downloads_file),
    ]);
    hyrasTminRegionsCurrent=current;
    hyrasTminRegionsClimate=climate;
    hyrasTminRegionsRecords=records;
    hyrasTminMapDownloads=maps;'''
    text = replace_once(text, old_fetch, new_fetch, "Map-Manifest laden")

    function_anchor = 'function hyrasTminRenderCurveChart(region,period,rows){'
    download_js = r'''function hyrasTminMapHref(path){
  return path?`${HYRAS_DATA_BASE}/tmin/${path}`:"#";
}
async function hyrasTminForceMapDownload(event,path,filename){
  if(event)event.preventDefault();
  if(!path)return;

  const url=hyrasTminMapHref(path);
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
    const anchor=document.createElement("a");
    anchor.href=objectUrl;
    anchor.download=filename||path.split("/").pop()||"hyras_tmin.png";
    anchor.style.display="none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(()=>URL.revokeObjectURL(objectUrl),2000);
  }catch(error){
    console.error("HYRAS Tmin Kartendownload:",error);
    window.open(url,"_blank","noopener,noreferrer");
  }finally{
    if(link){
      link.style.pointerEvents="";
      link.style.opacity="";
      link.textContent=oldText;
    }
  }
}

'''
    text = replace_once(
        text,
        function_anchor,
        download_js + function_anchor,
        "Download-Funktionen",
    )

    old_render_head = '''function hyrasTminRenderCurveChart(region,period,rows){
  const frame=document.getElementById("hyrasMapFrame");
  if(!frame)return;'''
    new_render_head = '''function hyrasTminRenderCurveChart(region,period,rows){
  const frame=document.getElementById("hyrasMapFrame");
  if(!frame)return;

  const maps=hyrasTminMapDownloads?.periods?.[period.key]||{};
  const absClass=maps.absolute?"hyras-tmean-download":"hyras-tmean-download disabled";
  const anomClass=maps.anomaly?"hyras-tmean-download":"hyras-tmean-download disabled";'''
    text = replace_once(text, old_render_head, new_render_head, "Map-Auswahl")

    old_downloads = '''    <div class="hyras-tmean-downloads">
      <a class="hyras-tmean-download" href="#" data-tmin-pdf="1">Kurve als PDF herunterladen</a>
    </div>
    <p class="hyras-tmean-region-note">
      Räumliches Gebietsmittel des täglichen 2-m-Temperaturminimums.
      Historische Tagesrekorde beziehen sich auf
      ${hyrasTminRegionsIndex.records_first_year||1951}–${hyrasTminRegionsIndex.records_last_year||2025}.
    </p>'''
    new_downloads = '''    <div class="hyras-tmean-downloads">
      <a class="${absClass}" ${maps.absolute?`href="${hyrasTminMapHref(maps.absolute)}" data-tmin-map="${maps.absolute}" data-tmin-filename="hyras_tmin_${period.key}_temperatur.png"`:""}>Tmin-Karte herunterladen</a>
      <a class="${anomClass}" ${maps.anomaly?`href="${hyrasTminMapHref(maps.anomaly)}" data-tmin-map="${maps.anomaly}" data-tmin-filename="hyras_tmin_${period.key}_abweichung_1991_2020.png"`:""}>Abweichungskarte 1991–2020 herunterladen</a>
      <a class="hyras-tmean-download" href="#" data-tmin-pdf="1">Kurve als PDF herunterladen</a>
    </div>
    <p class="hyras-tmean-region-note">
      ${maps.anomaly
        ?"Absolute Tmin- und Anomaliekarte stehen als fertige PNGs bereit."
        :"Für diesen laufenden Zeitraum ist die absolute Tmin-Karte verfügbar; eine Raster-Anomalie wird erst für vollständige Monate/Jahreszeiten angeboten."}
      Historische Tagesrekorde beziehen sich auf
      ${hyrasTminRegionsIndex.records_first_year||1951}–${hyrasTminRegionsIndex.records_last_year||2025}.
    </p>'''
    text = replace_once(text, old_downloads, new_downloads, "Map-Buttons")

    old_listener = '''  frame.querySelector("a[data-tmin-pdf]")?.addEventListener(
    "click",
    event=>hyrasTminExportCurvePdf(event,region,period)
  );'''
    new_listener = '''  frame.querySelectorAll("a[data-tmin-map]").forEach(link=>{
    link.addEventListener("click",event=>hyrasTminForceMapDownload(
      event,
      link.dataset.tminMap,
      link.dataset.tminFilename
    ));
  });
  frame.querySelector("a[data-tmin-pdf]")?.addEventListener(
    "click",
    event=>hyrasTminExportCurvePdf(event,region,period)
  );'''
    text = replace_once(text, old_listener, new_listener, "Map-Listener")

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS Tmin Karten-Downloads V1 eingebaut:")
    print("- absolute Tmin-Karte für alle aktuellen Perioden")
    print("- Anomaliekarte 1991-2020 für vollständige Monate/Jahreszeiten")
    print("- Blob-Download wie bei Tmean/Tmax")
    print("- Kurven und PDF bleiben unverändert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
