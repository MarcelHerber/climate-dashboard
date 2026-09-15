#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

BUTTON_ID = 'hyrasDailyAnomalyAnimationDownload'

HEAD_OLD = '''        <p id="hyrasDailyAnomalyMeta">Tageskarte wird geladen …</p>
      </div>
    </div>
    <div class="hyras-daily-anomaly-controls">'''
HEAD_NEW = '''        <p id="hyrasDailyAnomalyMeta">Tageskarte wird geladen …</p>
      </div>
      <a class="hyras-tmean-download disabled" id="hyrasDailyAnomalyAnimationDownload" href="#" aria-disabled="true">Animation wird erzeugt …</a>
    </div>
    <div class="hyras-daily-anomaly-controls">'''

MOUNT_MARKER = 'async function hyrasDailyAnomalyMount(parameter,rows){'
HELPER = r'''const HYRAS_DAILY_ANIMATION_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/hyras-animations";
let hyrasDailyAnomalyAnimationManifestPromise=null;
async function hyrasDailyAnomalyAnimationManifest(){
  if(!hyrasDailyAnomalyAnimationManifestPromise){
    hyrasDailyAnomalyAnimationManifestPromise=fetch(
      `${HYRAS_DAILY_ANIMATION_BASE}/manifest.json?t=${Date.now()}`,
      {cache:"no-store"}
    ).then(response=>{
      if(!response.ok)throw new Error(`Animationsmanifest fehlt (HTTP ${response.status}).`);
      return response.json();
    }).catch(error=>{
      hyrasDailyAnomalyAnimationManifestPromise=null;
      throw error;
    });
  }
  return hyrasDailyAnomalyAnimationManifestPromise;
}
async function hyrasDailyAnomalyConfigureAnimationDownload(parameter,manifest,panel){
  const link=panel?.querySelector("#hyrasDailyAnomalyAnimationDownload");
  if(!link)return;
  const reference=hyrasReferencePeriod();
  let animationManifest=null;
  try{animationManifest=await hyrasDailyAnomalyAnimationManifest();}
  catch(error){console.warn("HYRAS Tagesanomalie-Animationsmanifest:",error);}
  if(document.getElementById("hyrasDailyAnomalyPanel")!==panel)return;
  const animationParameter=animationManifest?.parameters?.[parameter];
  const animation=animationParameter?.references?.[reference];
  if(!animation?.url||animationParameter?.data_through!==manifest?.data_through){
    link.classList.add("disabled");
    link.setAttribute("aria-disabled","true");
    link.removeAttribute("href");
    link.textContent=animation?.url?"Animation wird aktualisiert …":"Animation wird erzeugt …";
    link.onclick=event=>event.preventDefault();
    return;
  }
  const url=`${HYRAS_DAILY_ANIMATION_BASE}/${animation.url}?v=${encodeURIComponent(animationParameter.data_through||"1")}`;
  const label=hyrasDailyAnomalyParameterLabel(parameter);
  const filename=`HYRAS_${label}_Tagesabweichungen_${reference}.mp4`;
  link.classList.remove("disabled");
  link.setAttribute("aria-disabled","false");
  link.href=url;
  link.textContent="Animation herunterladen (MP4)";
  link.onclick=async event=>{
    event.preventDefault();
    if(link.classList.contains("disabled"))return;
    const status=panel.querySelector("#hyrasDailyAnomalyStatus");
    const original=link.textContent;
    link.classList.add("disabled");
    link.setAttribute("aria-busy","true");
    link.textContent="MP4 wird geladen …";
    if(status)status.textContent=`Animation ${label} · Referenz ${reference.replace("-","–")} wird heruntergeladen …`;
    try{
      const response=await fetch(url,{cache:"no-store"});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const blob=await response.blob();
      const objectUrl=URL.createObjectURL(blob);
      const download=document.createElement("a");
      download.href=objectUrl;
      download.download=filename;
      document.body.appendChild(download);
      download.click();
      download.remove();
      setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
      if(status)status.textContent=`MP4-Animation · ${animation.frame_count||"?"} Tage · ${animation.fps||"?"} Bilder/s · Referenz ${reference.replace("-","–")}`;
    }catch(error){
      console.error("HYRAS Tagesanomalie-Animation:",error);
      if(status)status.textContent="Die MP4-Animation konnte nicht heruntergeladen werden.";
    }finally{
      link.classList.remove("disabled");
      link.removeAttribute("aria-busy");
      link.textContent=original;
    }
  };
}
'''

STALE_CHECK = '''    if(document.getElementById("hyrasDailyAnomalyPanel")!==mountedPanel)return;

    const dates=hyrasDailyAnomalyRowsDates(rows,manifest);'''
STALE_REPLACEMENT = '''    if(document.getElementById("hyrasDailyAnomalyPanel")!==mountedPanel)return;

    await hyrasDailyAnomalyConfigureAnimationDownload(parameter,manifest,panel);
    const dates=hyrasDailyAnomalyRowsDates(rows,manifest);'''


def patch_html(text: str) -> str:
    if BUTTON_ID in text:
        return text
    if MOUNT_MARKER not in text:
        raise RuntimeError("Mount-Marker für HYRAS-Tagesanomalien fehlt.")
    if HEAD_OLD not in text:
        raise RuntimeError("Panel-Marker für HYRAS-Tagesanomalien fehlt.")
    if STALE_CHECK not in text:
        raise RuntimeError("Initialisierungs-Marker für HYRAS-Tagesanomalien fehlt.")

    text = text.replace(HEAD_OLD, HEAD_NEW, 1)
    text = text.replace(MOUNT_MARKER, HELPER + MOUNT_MARKER, 1)
    text = text.replace(STALE_CHECK, STALE_REPLACEMENT, 1)
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="index.html")
    args = parser.parse_args()
    path = Path(args.file)
    original = path.read_text(encoding="utf-8")
    patched = patch_html(original)
    if patched == original:
        print("HYRAS Tagesanomalie-MP4-Frontend bereits eingebaut.")
        return 0
    path.write_text(patched, encoding="utf-8")
    print("HYRAS Tagesanomalie-MP4-Frontend eingebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
