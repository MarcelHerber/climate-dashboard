#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_TMIN_FRONTEND_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"HYRAS-Tmin-Frontend-Patch fehlgeschlagen ({label}): Treffer={count}"
        )
    return text.replace(old, new, 1)


TMIN_JS = r'''// HYRAS_TMIN_FRONTEND_V1
let hyrasTminRegionsIndex=null;
let hyrasTminRegionsCurrent=null;
let hyrasTminRegionsClimate=null;
let hyrasTminRegionsRecords=null;
let hyrasTminRegionChart=null;
let hyrasTminRegionsLoading=null;

function hyrasTminRegionsBase(){return `${HYRAS_DATA_BASE}/tmin/regions`;}
async function hyrasTminRegionsFetch(path){
  const version=hyrasTminRegionsIndex?.data_through||"1";
  const response=await fetch(
    `${hyrasTminRegionsBase()}/${path}?v=${encodeURIComponent(version)}`,
    {cache:"no-store"}
  );
  if(!response.ok)throw new Error(`Tmin-Gebietsdaten ${path} fehlen (${response.status}).`);
  return response.json();
}
async function hyrasTminRegionsEnsureLoaded(){
  if(hyrasTminRegionsIndex&&hyrasTminRegionsCurrent&&hyrasTminRegionsClimate&&hyrasTminRegionsRecords){
    return hyrasTminRegionsIndex;
  }
  if(hyrasTminRegionsLoading)return hyrasTminRegionsLoading;

  hyrasTminRegionsLoading=(async()=>{
    hyrasTminRegionsIndex=await hyrasTminRegionsFetch("index.json");
    const [current,climate,records]=await Promise.all([
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.current_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.climate_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.records_file),
    ]);
    hyrasTminRegionsCurrent=current;
    hyrasTminRegionsClimate=climate;
    hyrasTminRegionsRecords=records;
    return hyrasTminRegionsIndex;
  })().finally(()=>{hyrasTminRegionsLoading=null;});

  return hyrasTminRegionsLoading;
}
function hyrasTminPopulateRegions(){
  const select=document.getElementById("hyrasTmeanRegionSelect");
  if(!select||!hyrasTminRegionsIndex)return;
  const previous=select.value||"Deutschland";
  select.innerHTML=(hyrasTminRegionsIndex.regions||[])
    .map(name=>`<option value="${name.replace(/"/g,"&quot;")}">${name}</option>`)
    .join("");
  select.value=(hyrasTminRegionsIndex.regions||[]).includes(previous)?previous:"Deutschland";
}
function hyrasTminPopulateCurvePeriods(){
  const select=document.getElementById("hyrasPeriodSelect");
  if(!select||!hyrasTminRegionsIndex)return;
  const previous=select.value;
  const periods=hyrasTminRegionsIndex.periods||[];
  select.innerHTML=periods.map(period=>`<option value="${period.key}">${period.label}</option>`).join("");
  const preferred=periods.find(period=>period.key==="summer")||periods[0];
  if(previous&&periods.some(period=>period.key===previous))select.value=previous;
  else if(preferred)select.value=preferred.key;
}
function hyrasTminCurvePeriod(){
  const key=document.getElementById("hyrasPeriodSelect")?.value;
  return (hyrasTminRegionsIndex?.periods||[]).find(period=>period.key===key)
    ||(hyrasTminRegionsIndex?.periods||[])[0]
    ||null;
}
function hyrasTminRegionName(){
  return document.getElementById("hyrasTmeanRegionSelect")?.value||"Deutschland";
}
function hyrasTminNumberOrNull(value){
  if(value===null||value===undefined)return null;
  const number=Number(value);
  return Number.isFinite(number)?number:null;
}
function hyrasTminCurveRows(region,period){
  const dates=hyrasTminRegionsCurrent?.dates||[];
  const values=hyrasTminRegionsCurrent?.regions?.[region]||[];
  const climate=hyrasTminRegionsClimate?.regions?.[region]||{};
  const records=hyrasTminRegionsRecords?.regions?.[region]||{};
  const rows=[];

  for(let i=0;i<dates.length;i++){
    const date=dates[i];
    if(date<period.start_date||date>period.end_date)continue;
    const mmdd=date.slice(5,10);
    const record=records[mmdd]||{};
    rows.push({
      date,
      current:hyrasTminNumberOrNull(values[i]),
      normal:hyrasTminNumberOrNull(climate[mmdd]),
      recordMax:hyrasTminNumberOrNull(record.max),
      recordMin:hyrasTminNumberOrNull(record.min),
      recordMaxYears:Array.isArray(record.max_years)?record.max_years:[],
      recordMinYears:Array.isArray(record.min_years)?record.min_years:[],
    });
  }
  return rows;
}
function hyrasTminMean(values){
  const valid=values.filter(Number.isFinite);
  return valid.length?valid.reduce((sum,value)=>sum+value,0)/valid.length:NaN;
}
function hyrasTminFmt(value,unit="°C",signed=false){
  if(!Number.isFinite(value))return "–";
  const sign=signed&&value>0?"+":"";
  return `${sign}${value.toLocaleString("de-DE",{
    minimumFractionDigits:2,
    maximumFractionDigits:2
  })} ${unit}`;
}
function hyrasTminSetCurveKpis(region,period,rows){
  const current=hyrasTminMean(rows.map(row=>row.current));
  const normal=hyrasTminMean(rows.map(row=>row.normal));
  const anomaly=current-normal;
  const setHeading=(id,text)=>{
    const element=document.getElementById(id);
    const heading=element?.parentElement?.querySelector("h4");
    if(heading)heading.textContent=text;
  };

  document.getElementById("hyrasPeriodStat").textContent=period.label;
  document.getElementById("hyrasDataThrough").textContent=
    `${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`;

  setHeading("hyrasCurrentMean",`Mittel Tmin ${hyrasTminRegionsIndex.year}`);
  document.getElementById("hyrasCurrentMean").textContent=hyrasTminFmt(current);
  document.getElementById("hyrasCurrentMeanDetail").textContent=region;

  setHeading("hyrasReferenceMean","Mittel 1991–2020");
  document.getElementById("hyrasReferenceMean").textContent=hyrasTminFmt(normal);
  document.getElementById("hyrasReferenceMeanDetail").textContent="exakt dieselben Kalendertage";

  setHeading("hyrasPercentMean","Abweichung");
  document.getElementById("hyrasPercentMean").textContent=hyrasTminFmt(anomaly,"K",true);

  setHeading("hyrasAnomalyMean","Datentage");
  document.getElementById("hyrasAnomalyMean").textContent=
    String(rows.filter(row=>Number.isFinite(row.current)).length);

  document.getElementById("hyrasReferenceNote").textContent=
    hyrasTminRegionsIndex.method_note||
    "HYRAS-Tmin-Gebietsmittel, Referenz 1991–2020.";
}
function hyrasTminPdfFilenamePart(value){
  return String(value||"")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g,"")
    .replace(/ß/g,"ss")
    .replace(/[^a-zA-Z0-9]+/g,"_")
    .replace(/^_+|_+$/g,"")
    .toLowerCase()||"tmin";
}
async function hyrasTminExportCurvePdf(event,region,period){
  if(event)event.preventDefault();
  const link=event?.currentTarget||null;
  const oldText=link?.textContent||"Kurve als PDF herunterladen";
  if(link){
    link.style.pointerEvents="none";
    link.style.opacity=".65";
    link.textContent="PDF wird erstellt …";
  }

  try{
    const canvas=document.getElementById("hyrasTminRegionCanvas");
    const JsPdf=window.jspdf?.jsPDF;
    if(!canvas)throw new Error("Tmin-Kurvencanvas fehlt.");
    if(!JsPdf)throw new Error("jsPDF ist nicht verfügbar.");

    const exportCanvas=document.createElement("canvas");
    exportCanvas.width=canvas.width;
    exportCanvas.height=canvas.height;
    const context=exportCanvas.getContext("2d");
    if(!context)throw new Error("PDF-Canvas konnte nicht erzeugt werden.");

    context.fillStyle="#ffffff";
    context.fillRect(0,0,exportCanvas.width,exportCanvas.height);
    context.drawImage(canvas,0,0);

    const image=exportCanvas.toDataURL("image/png",1.0);
    const pdf=new JsPdf({
      orientation:"landscape",
      unit:"mm",
      format:"a4",
      compress:true
    });

    const pageWidth=pdf.internal.pageSize.getWidth();
    const pageHeight=pdf.internal.pageSize.getHeight();
    const margin=12;

    pdf.setTextColor(25,25,25);
    pdf.setFont("helvetica","bold");
    pdf.setFontSize(16);
    pdf.text(`Tagesminimum - ${region}`,margin,15);

    pdf.setFont("helvetica","normal");
    pdf.setFontSize(9.5);
    pdf.setTextColor(85,95,105);
    pdf.text(
      `${period?.label||""} | taegliches HYRAS-Tmin-Gebietsmittel gegen 1991-2020`,
      margin,
      21
    );

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
    const dataThrough=hyrasTminRegionsIndex?.data_through||"";
    const recordFirst=hyrasTminRegionsIndex?.records_first_year||1951;
    const recordLast=hyrasTminRegionsIndex?.records_last_year||2025;
    pdf.text(
      `Quelle: Deutscher Wetterdienst (DWD), HYRAS-DE-TASMIN | Datenstand: ${dataThrough} | Historische Tagesrekorde: ${recordFirst}-${recordLast}`,
      margin,
      pageHeight-6
    );

    const filename=[
      "hyras_tmin",
      hyrasTminPdfFilenamePart(region),
      hyrasTminPdfFilenamePart(period?.label||period?.key||"kurve")
    ].join("_")+".pdf";
    pdf.save(filename);
  }catch(error){
    console.error("HYRAS Tmin PDF-Export:",error);
    window.alert(`PDF konnte nicht erstellt werden: ${error.message}`);
  }finally{
    if(link){
      link.style.pointerEvents="";
      link.style.opacity="";
      link.textContent=oldText;
    }
  }
}
function hyrasTminRenderCurveChart(region,period,rows){
  const frame=document.getElementById("hyrasMapFrame");
  if(!frame)return;

  if(hyrasTmeanRegionChart){
    hyrasTmeanRegionChart.destroy();
    hyrasTmeanRegionChart=null;
  }
  if(hyrasTmaxRegionChart){
    hyrasTmaxRegionChart.destroy();
    hyrasTmaxRegionChart=null;
  }
  if(hyrasTminRegionChart){
    hyrasTminRegionChart.destroy();
    hyrasTminRegionChart=null;
  }

  frame.innerHTML=`<div class="hyras-tmean-region-panel">
    <div class="hyras-tmean-region-head">
      <div>
        <h3>Tagesminimum – ${region}</h3>
        <p>${period.label} · tägliches HYRAS-Tmin-Gebietsmittel gegen 1991–2020</p>
      </div>
    </div>
    <div class="hyras-tmean-chart-wrap">
      <canvas id="hyrasTminRegionCanvas"></canvas>
    </div>
    <div class="hyras-tmean-downloads">
      <a class="hyras-tmean-download" href="#" data-tmin-pdf="1">Kurve als PDF herunterladen</a>
    </div>
    <p class="hyras-tmean-region-note">
      Räumliches Gebietsmittel des täglichen 2-m-Temperaturminimums.
      Historische Tagesrekorde beziehen sich auf
      ${hyrasTminRegionsIndex.records_first_year||1951}–${hyrasTminRegionsIndex.records_last_year||2025}.
    </p>
  </div>`;

  frame.querySelector("a[data-tmin-pdf]")?.addEventListener(
    "click",
    event=>hyrasTminExportCurvePdf(event,region,period)
  );

  const labels=rows.map(row=>{
    const [,month,day]=row.date.split("-");
    return `${day}.${month}.`;
  });
  const climate=rows.map(row=>row.normal);
  const current=rows.map(row=>row.current);
  const recordMax=rows.map(row=>row.recordMax);
  const recordMin=rows.map(row=>row.recordMin);

  const recordFirst=Number(
    hyrasTminRegionsIndex.records_first_year||
    hyrasTminRegionsRecords?.first_year||
    1951
  );
  const recordLast=Number(
    hyrasTminRegionsIndex.records_last_year||
    hyrasTminRegionsRecords?.last_year||
    2025
  );

  hyrasTminRegionChart=new Chart(
    document.getElementById("hyrasTminRegionCanvas"),
    {
      type:"line",
      data:{
        labels,
        datasets:[
          {
            label:"Mittel 1991–2020",
            data:climate,
            borderColor:"#666",
            borderWidth:2,
            pointRadius:0,
            tension:.08,
            spanGaps:false
          },
          {
            label:`${hyrasTminRegionsIndex.year}`,
            data:current,
            borderColor:"#111",
            borderWidth:2.4,
            pointRadius:0,
            tension:.08,
            spanGaps:false,
            fill:{
              target:0,
              above:"rgba(210,55,45,.28)",
              below:"rgba(55,115,190,.28)"
            }
          },
          {
            label:`Historisches Maximum ${recordFirst}–${recordLast}`,
            data:recordMax,
            borderColor:"#b42318",
            backgroundColor:"transparent",
            borderWidth:1.5,
            borderDash:[6,4],
            pointRadius:0,
            tension:.04,
            spanGaps:false
          },
          {
            label:`Historisches Minimum ${recordFirst}–${recordLast}`,
            data:recordMin,
            borderColor:"#1f5f99",
            backgroundColor:"transparent",
            borderWidth:1.5,
            borderDash:[6,4],
            pointRadius:0,
            tension:.04,
            spanGaps:false
          }
        ]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        animation:{duration:250},
        interaction:{mode:"index",intersect:false},
        plugins:{
          legend:{display:true},
          datalabels:{display:false},
          tooltip:{
            filter:item=>item.datasetIndex<2,
            callbacks:{
              afterBody(items){
                if(!items?.length)return "";
                const index=items[0].dataIndex;
                const a=current[index];
                const b=climate[index];
                const row=rows[index]||{};
                const lines=[];

                if(Number.isFinite(a)&&Number.isFinite(b)){
                  lines.push(
                    `Abweichung: ${(a-b)>=0?"+":""}${(a-b).toFixed(2).replace(".",",")} K`
                  );
                }
                if(Number.isFinite(row.recordMax)){
                  lines.push(
                    `Historisches Maximum: ${row.recordMax.toFixed(2).replace(".",",")} °C (${(row.recordMaxYears||[]).join(", ")})`
                  );
                }
                if(Number.isFinite(row.recordMin)){
                  lines.push(
                    `Historisches Minimum: ${row.recordMin.toFixed(2).replace(".",",")} °C (${(row.recordMinYears||[]).join(", ")})`
                  );
                }
                return lines;
              }
            }
          }
        },
        scales:{
          x:{ticks:{maxTicksLimit:14}},
          y:{title:{display:true,text:"Tagesminimum (°C)"}}
        }
      }
    }
  );
}
async function renderHyrasTmin(){
  try{
    await hyrasTminRegionsEnsureLoaded();
    const region=hyrasTminRegionName();
    const period=hyrasTminCurvePeriod();
    if(!period)return;

    const rows=hyrasTminCurveRows(region,period);
    hyrasTminSetCurveKpis(region,period,rows);
    hyrasTminRenderCurveChart(region,period,rows);
  }catch(error){
    console.error("HYRAS Tmin Gebietskurven:",error);
    const frame=document.getElementById("hyrasMapFrame");
    if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;
  }
}

// Bestehende Routen bleiben erhalten; nur Tmin wird ergänzt.
const hyrasRenderBeforeTmin=renderHyras;
renderHyras=function(){
  if(hyrasParameter()==="tmin"){
    renderHyrasTmin();
    return;
  }
  return hyrasRenderBeforeTmin();
};

const hyrasSwitchBeforeTmin=hyrasSwitchParameter;
hyrasSwitchParameter=async function(){
  if(hyrasParameter()!=="tmin"){
    if(hyrasTminRegionChart){
      hyrasTminRegionChart.destroy();
      hyrasTminRegionChart=null;
    }
    return hyrasSwitchBeforeTmin();
  }

  const custom=document.getElementById("hyrasCustomApply")?.parentElement;
  const historical=document.getElementById("hyrasHistoricalApply")?.parentElement;
  const panel=document.getElementById("hyrasPointAnalysis");
  const metricGroup=document.getElementById("hyrasMetricSelect")?.closest(".control-group");
  const regionGroup=document.getElementById("hyrasTmeanRegionGroup");

  if(panel)panel.hidden=true;
  if(custom)custom.style.display="none";
  if(historical)historical.style.display="none";
  if(metricGroup)metricGroup.style.display="none";
  if(regionGroup)regionGroup.hidden=false;

  const oldLink=document.getElementById("hyrasOpenImage");
  if(oldLink)oldLink.style.display="none";

  const status=document.getElementById("hyrasStatus");
  if(status)status.textContent="HYRAS Tmin Gebietskurven werden geladen …";

  await hyrasTminRegionsEnsureLoaded();
  hyrasTminPopulateRegions();
  hyrasTminPopulateCurvePeriods();

  if(status){
    status.textContent=
      `Tmin · Deutschland + 16 Bundesländer · Daten bis ${hyrasDate(hyrasTminRegionsIndex.data_through)} · Referenz 1991–2020`;
  }
  await renderHyrasTmin();
};
'''


def main() -> int:
    text=TARGET.read_text(encoding="utf-8")

    # Reparaturmodus: Die sichtbare Tmin-Option muss unabhängig davon
    # vorhanden sein, ob die Tmin-JavaScript-Logik bereits eingebaut ist.
    # Das behebt ältere Läufe, bei denen der Marker vorhanden war,
    # die Dropdown-Option aber fehlte.
    menu_changed=False
    if 'value="tmin"' not in text:
        old_option='''        <option value="tmax">2-m-Tagesmaximum</option>'''
        new_option='''        <option value="tmax">2-m-Tagesmaximum</option>
        <option value="tmin">2-m-Tagesminimum</option>'''
        text=replace_once(text,old_option,new_option,"Tmin-Parameteroption reparieren")
        menu_changed=True

    if MARKER in text:
        if menu_changed:
            TARGET.write_text(text,encoding="utf-8")
            print("HYRAS Tmin Frontend V1 war bereits aktiv; fehlende Tmin-Menüoption wurde ergänzt.")
        else:
            print("HYRAS Tmin Frontend V1 inklusive Menüoption ist bereits vollständig aktiv.")
        return 0

    required=[
        "// HYRAS_TMEAN_REGION_CURVES_V1",
        "// HYRAS_TMEAN_DAILY_RECORDS_V1",
        "// HYRAS_TMEAN_PDF_EXPORT_V1",
        "// HYRAS_TMAX_FRONTEND_V1",
    ]
    missing=[marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("Benötigte HYRAS-Frontend-Basis fehlt: "+", ".join(missing))

    pos=text.rfind("</script>")
    if pos<0:
        raise RuntimeError("Kein abschließender Script-Block gefunden.")

    text=text[:pos]+"\n"+TMIN_JS+"\n"+text[pos:]
    TARGET.write_text(text,encoding="utf-8")

    print("HYRAS Tmin Frontend V1 eingebaut:")
    print("- 2-m-Tagesminimum im Parameterfeld")
    print("- Deutschland + 16 Bundesländer")
    print("- 2026 gegen Tagesmittel 1991-2020")
    print("- historische Max/Min-Linien 1951 bis Vorjahr")
    print("- Rekordjahre im Tooltip")
    print("- PDF-Download der Kurve")
    print("- noch keine Tmin-Karten in Stufe 2")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
