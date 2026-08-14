#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
RECORD_MARKER = "// HYRAS_TMEAN_DAILY_RECORDS_V1"
PDF_MARKER = "// HYRAS_TMEAN_PDF_EXPORT_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"HYRAS-Tmean-PDF-Patch fehlgeschlagen ({label}): Treffer={count}"
        )
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if PDF_MARKER in text:
        print("HYRAS Tmean PDF-Export ist bereits aktiv.")
        return 0

    if RECORD_MARKER not in text:
        raise RuntimeError(
            "HYRAS Tmean Rekordkurven fehlen im aktuellen index.html."
        )

    anchor = 'function hyrasTmeanRenderCurveChart(region,period,rows){'
    pdf_js = r'''// HYRAS_TMEAN_PDF_EXPORT_V1
function hyrasTmeanPdfFilenamePart(value){
  return String(value||"")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g,"")
    .replace(/ß/g,"ss")
    .replace(/[^a-zA-Z0-9]+/g,"_")
    .replace(/^_+|_+$/g,"")
    .toLowerCase()||"tmean";
}
async function hyrasTmeanExportCurvePdf(event,region,period){
  if(event)event.preventDefault();
  const link=event?.currentTarget||null;
  const oldText=link?.textContent||"Kurve als PDF herunterladen";
  if(link){
    link.style.pointerEvents="none";
    link.style.opacity=".65";
    link.textContent="PDF wird erstellt …";
  }
  try{
    const canvas=document.getElementById("hyrasTmeanRegionCanvas");
    const JsPdf=window.jspdf?.jsPDF;
    if(!canvas)throw new Error("Tmean-Kurvencanvas fehlt.");
    if(!JsPdf)throw new Error("jsPDF ist nicht verfügbar.");

    const exportCanvas=document.createElement("canvas");
    exportCanvas.width=canvas.width;
    exportCanvas.height=canvas.height;
    const ctx=exportCanvas.getContext("2d");
    if(!ctx)throw new Error("PDF-Canvas konnte nicht erzeugt werden.");
    ctx.fillStyle="#ffffff";
    ctx.fillRect(0,0,exportCanvas.width,exportCanvas.height);
    ctx.drawImage(canvas,0,0);

    const image=exportCanvas.toDataURL("image/png",1.0);
    const pdf=new JsPdf({orientation:"landscape",unit:"mm",format:"a4",compress:true});
    const pageWidth=pdf.internal.pageSize.getWidth();
    const pageHeight=pdf.internal.pageSize.getHeight();
    const margin=12;

    pdf.setTextColor(25,25,25);
    pdf.setFont("helvetica","bold");
    pdf.setFontSize(16);
    pdf.text(`Temperaturmittel - ${region}`,margin,15);

    pdf.setFont("helvetica","normal");
    pdf.setFontSize(9.5);
    pdf.setTextColor(85,95,105);
    pdf.text(`${period?.label||""} | taegliches HYRAS-Gebietsmittel gegen 1991-2020`,margin,21);

    const imageTop=27;
    const footerHeight=12;
    const maxWidth=pageWidth-margin*2;
    const maxHeight=pageHeight-imageTop-footerHeight;
    const ratio=Math.min(maxWidth/exportCanvas.width,maxHeight/exportCanvas.height);
    const imageWidth=exportCanvas.width*ratio;
    const imageHeight=exportCanvas.height*ratio;
    const imageX=(pageWidth-imageWidth)/2;
    pdf.addImage(image,"PNG",imageX,imageTop,imageWidth,imageHeight,undefined,"FAST");

    pdf.setFont("helvetica","normal");
    pdf.setFontSize(7.5);
    pdf.setTextColor(95,95,95);
    const dataThrough=hyrasTmeanRegionsIndex?.data_through||"";
    const recordFirst=hyrasTmeanRegionsIndex?.records_first_year||1951;
    const recordLast=hyrasTmeanRegionsIndex?.records_last_year||2025;
    pdf.text(
      `Quelle: Deutscher Wetterdienst (DWD), HYRAS-DE-TAS | Datenstand: ${dataThrough} | Historische Tagesrekorde: ${recordFirst}-${recordLast}`,
      margin,
      pageHeight-6
    );

    const filename=[
      "hyras_tmean",
      hyrasTmeanPdfFilenamePart(region),
      hyrasTmeanPdfFilenamePart(period?.label||period?.key||"kurve")
    ].join("_")+".pdf";
    pdf.save(filename);
  }catch(error){
    console.error("HYRAS Tmean PDF-Export:",error);
    window.alert(`PDF konnte nicht erstellt werden: ${error.message}`);
  }finally{
    if(link){
      link.style.pointerEvents="";
      link.style.opacity="";
      link.textContent=oldText;
    }
  }
}

'''
    text = replace_once(text, anchor, pdf_js + anchor, "PDF-Funktion")

    old_buttons = '''      <a class="${anomClass}" ${maps.anomaly?`href="${hyrasTmeanDownloadHref(maps.anomaly)}" data-tmean-map="${maps.anomaly}" data-tmean-filename="hyras_tmean_${period.map_key}_abweichung_1991_2020.png"`:""}>Abweichungskarte 1991–2020 herunterladen</a>
    </div>'''
    new_buttons = '''      <a class="${anomClass}" ${maps.anomaly?`href="${hyrasTmeanDownloadHref(maps.anomaly)}" data-tmean-map="${maps.anomaly}" data-tmean-filename="hyras_tmean_${period.map_key}_abweichung_1991_2020.png"`:""}>Abweichungskarte 1991–2020 herunterladen</a>
      <a class="hyras-tmean-download" href="#" data-tmean-pdf="1">Kurve als PDF herunterladen</a>
    </div>'''
    text = replace_once(text, old_buttons, new_buttons, "PDF-Button")

    old_listener = '''      link.dataset.tmeanFilename
    ));
  });
  const labels=rows.map'''
    new_listener = '''      link.dataset.tmeanFilename
    ));
  });
  frame.querySelector("a[data-tmean-pdf]")?.addEventListener(
    "click",
    event=>hyrasTmeanExportCurvePdf(event,region,period)
  );
  const labels=rows.map'''
    text = replace_once(text, old_listener, new_listener, "PDF-Listener")

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS Tmean PDF-Export V1 eingebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
