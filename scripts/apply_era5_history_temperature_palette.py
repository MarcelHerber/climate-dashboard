#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "// ERA5_TEMP_ANOMALY_DISCRETE_V1"
ANCHOR = "function era5EuropeHistoryScaleFor(entries,parameter,view){"

PALETTE_JS = r'''  // ERA5_TEMP_ANOMALY_DISCRETE_V1
  if(parameter==="temperature"&&view==="anomaly"){
    const min=-8,max=8,center=0;
    const levels=[-8,-7,-6,-5,-4,-3,-2,-1,-.5,0,.5,1,2,3,4,5,6,7,8];
    const boundaries=[-8.5,-7.5,-6.5,-5.5,-4.5,-3.5,-2.5,-1.5,-.75,-.25,.25,.75,1.5,2.5,3.5,4.5,5.5,6.5,7.5,8.5];
    const stops=["#3A006F","#51009E","#6B03C6","#5E4FFC","#187DFD","#70B1FB","#C6E4FB","#DDEBF9","#EDF4FA","#FDFCFC","#FDF0BC","#FDE47C","#FDBD3E","#FC691C","#F93A19","#E51B75","#FC579B","#FC83B4","#FDAFCB"];
    const color=value=>{
      if(!Number.isFinite(value))return "rgba(0,0,0,0)";
      for(let i=0;i<stops.length;i++)if(value<boundaries[i+1])return stops[i];
      return stops[stops.length-1];
    };
    const gradientStops=stops.flatMap((stop,index)=>{
      const from=(100*index/stops.length).toFixed(4),to=(100*(index+1)/stops.length).toFixed(4);
      return [`${stop} ${from}%`,`${stop} ${to}%`];
    }).join(",");
    const gradient=`linear-gradient(90deg,transparent 49.7%,#000 49.7%,#000 50.3%,transparent 50.3%),linear-gradient(90deg,${gradientStops})`;
    return {min,max,center,stops,color,gradient,levels,boundaries,discrete:true};
  }'''


def apply_palette(text: str) -> tuple[str, bool]:
    if MARKER in text:
        return text, False
    hits = text.count(ANCHOR)
    if hits != 1:
        raise RuntimeError(f"Historische ERA5-Skalenfunktion nicht eindeutig gefunden: Treffer={hits}")
    return text.replace(ANCHOR, ANCHOR + "\n" + PALETTE_JS, 1), True


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "index.html"
    text = target.read_text(encoding="utf-8")
    text, changed = apply_palette(text)
    if changed:
        target.write_text(text, encoding="utf-8")
        print("ERA5 historische Temperatur-Anomalieskala auf diskret -8 bis +8 K umgestellt.")
    else:
        print("ERA5 historische Temperatur-Anomalieskala ist bereits aktuell.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
