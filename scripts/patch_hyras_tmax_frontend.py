#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_TMAX_FRONTEND_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"HYRAS-Tmax-Frontend-Patch fehlgeschlagen ({label}): Treffer={count}"
        )
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if MARKER in text:
        print("HYRAS Tmax Frontend V1 ist bereits aktiv.")
        return 0

    required = [
        "// HYRAS_TMEAN_REGION_CURVES_V1",
        "// HYRAS_TMEAN_DAILY_RECORDS_V1",
        "// HYRAS_TMEAN_PDF_EXPORT_V1",
    ]
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("Aktuelle Tmean-Basis fehlt: " + ", ".join(missing))

    old_option = '''        <option value="tmean">2-m-Temperaturmittel</option>
      </select>'''
    new_option = '''        <option value="tmean">2-m-Temperaturmittel</option>
        <option value="tmax">2-m-Tagesmaximum</option>
      </select>'''
    text = replace_once(text, old_option, new_option, "Parameteroption")

    anchor = '''async function renderHyrasTmean(){'''
    tmax_js = r'''// HYRAS_TMAX_FRONTEND_V1
let hyrasTmaxRegionsIndex=null;
let hyrasTmaxRegionsCurrent=null;
let hyrasTmaxRegionsClimate=null;
let hyrasTmaxRegionsRecords=null;
let hyrasTmaxRegionChart=null;
let hyrasTmaxRegionsLoading=null;

function hyrasTmaxRegionsBase(){return `${HYRAS_DATA_BASE}/tmax/regions`;}
async function hyrasTmaxRegionsFetch(path){
  const version=hyrasTmaxRegionsIndex?.data_through||"1";
  const response=await fetch(
    `${hyrasTmaxRegionsBase()}/${path}?v=${encodeURIComponent(version)}`,
    {cache:"no-store"}
  );
  if(!response.ok)throw new Error(`Tmax-Gebietsdaten ${path} fehlen (${response.status}).`);
  return response.json();
}
async function hyrasTmaxRegionsEnsureLoaded(){
  if(hyrasTmaxRegionsIndex&&hyrasTmaxRegionsCurrent&&hyrasTmaxRegionsClimate&&hyrasTmaxRegionsRecords){
    return hyrasTmaxRegionsIndex;
  }
  if(hyrasTmaxRegionsLoading)return hyrasTmaxRegionsLoading;

  hyrasTmaxRegionsLoading=(async()=>{
    hyrasTmaxRegionsIndex=await hyrasTmaxRegionsFetch("index.json");
    const [current,climate,records]=await Promise.all([
      hyrasTmaxRegionsFetch(hyrasTmaxRegionsIndex.current_file),
      hyrasTmaxRegionsFetch(hyrasTmaxRegionsIndex.climate_file),
      hyrasTmaxRegionsFetch(hyrasTmaxRegionsIndex.records_file),
    ]);
    hyrasTmaxRegionsCurrent=current;
    hyrasTmaxRegionsClimate=climate;
    hyrasTmaxRegionsRecords=records;
    return hyrasTmaxRegionsIndex;
  })().finally(()=>{hyrasTmaxRegionsLoading=null;});

  return hyrasTmaxRegionsLoading;
}
function hyrasTmaxPopulateRegions(){
  const select=document.getElementById("hyrasTmeanRegionSelect");
  if(!select||!hyrasTmaxRegionsIndex)return;
  const previous=select.value||"Deutschland";
  select.innerHTML=(hyrasTmaxRegionsIndex.regions||[])
    .map(name=>`<option value="${name.replace(/"/g,"&quot;")}">${name}</option>`)
    .join("");
  select.value=(hyrasTmaxRegionsIndex.regions||[]).includes(previous)
    ?previous
    :"Deutschland";
}
function hyrasTmaxPopulateCurvePeriods(){
  const select=document.getElementById("hyrasPeriodSelect");
  if(!select||!hyrasTmaxRegionsIndex)return;
  const previous=select.value;
  const periods=hyrasTmaxRegionsIndex.periods||[];
  select.innerHTML=periods
    .map(period=>`<option value="${period.key}">${period.label}</option>`)
    .join("");
  const preferred=periods.find(period=>period.key==="summer")||periods[0];
  if(previous&&periods.some(period=>period.key===previous)){
    select.value=previous;
  }else if(preferred){
    select.value=preferred.key;
  }
}
function hyrasTmaxCurvePeriod(){
  const key=document.getElementById("hyrasPeriodSelect")?.value;
  return (hyrasTmaxRegionsIndex?.periods||[]).find(period=>period.key===key)
    ||(hyrasTmaxRegionsIndex?.periods||[])[0]
    ||null;
}
function hyrasTmaxRegionName(){
  return document.getElementById("hyrasTmeanRegionSelect")?.value||"Deutschland";
}
function hyrasTmaxNumberOrNull(value){
  if(value===null||value===undefined)return null;
  const number=Number(value);
  return Number.isFinite(number)?number:null;
}
function hyrasTmaxCurveRows(region,period){
  const dates=hyrasTmaxRegionsCurrent?.dates||[];
  const values=hyrasTmaxRegionsCurrent?.regions?.[region]||[];
  const climate=hyrasTmaxRegionsClimate?.regions?.[region]||{};
  const records=hyrasTmaxRegionsRecords?.regions?.[region]||{};
  const rows=[];

  for(let i=0;i<dates.length;i++){
    const date=dates[i];
    if(date<period.start_date||date>period.end_date)continue;
    const mmdd=date.slice(5,10);
    const record=records[mmdd]||{};
    rows.push({
      date,
      current:hyrasTmaxNumberOrNull(values[i]),
      normal:hyrasTmaxNumberOrNull(climate[mmdd]),
      recordMax:hyrasTmaxNumberOrNull(record.max),
      recordMin:hyrasTmaxNumberOrNull(record.min),
      recordMaxYears:Array.isArray(record.max_years)?record.max_years:[],
      recordMinYears:Array.isArray(record.min_years)?record.min_years:[],
    });
  }
  return rows;
}
function hyrasTmaxMean(values){
  const valid=values.filter(Number.isFinite);
  return valid.length?valid.reduce((sum,value)=>sum+value,0)/valid.length:NaN;
}
function hyrasTmaxFmt(value,unit="°C",signed=false){
  if(!Number.isFinite(value))return "–";
  const sign=signed&&value>0?"+":"";
  return `${sign}${value.toLocaleString("de-DE",{
    minimumFractionDigits:2,
    maximumFractionDigits:2
  })} ${unit}`;
}
function hyrasTmaxSetCurveKpis(region,period,rows){
  const current=hyrasTmaxMean(rows.map(row=>row.current));
  const normal=hyrasTmaxMean(rows.map(row=>row.normal));
  const anomaly=current-normal;
  const setHeading=(id,text)=>{
    const element=document.getElementById(id);
    const heading=element?.parentElement?.querySelector("h4");
    if(heading)heading.textContent=text;
  };

  document.getElementById("hyrasPeriodStat").textContent=period.label;
  document.getElementById("hyrasDataThrough").textContent=
    `${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`;

  setHeading("hyrasCurrentMean",`Mittel Tmax ${hyrasTmaxRegionsIndex.year}`);
  document.getElementById("hyrasCurrentMean").textContent=hyrasTmaxFmt(current);
  document.getElementById("hyrasCurrentMeanDetail").textContent=region;

  setHeading("hyrasReferenceMean","Mittel 1991–2020");
  document.getElementById("hyrasReferenceMean").textContent=hyrasTmaxFmt(normal);
  document.getElementById("hyrasReferenceMeanDetail").textContent=
    "exakt dieselben Kalendertage";

  setHeading("hyrasPercentMean","Abweichung");
  document.getElementById("hyrasPercentMean").textContent=
    hyrasTmaxFmt(anomaly,"K",true);

  setHeading("hyrasAnomalyMean","Datentage");
  document.getElementById("hyrasAnomalyMean").textContent=
    String(rows.filter(row=>Number.isFinite(row.current)).length);

  document.getElementById("hyrasReferenceNote").textContent=
    hyrasTmaxRegionsIndex.method_note||
    "HYRAS-Tmax-Gebietsmittel, Referenz 1991–2020.";
}
function hyrasTmaxPdfFilenamePart(value){
  return String(value||"")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g,"")
    .replace(/ß/g,"ss")
    .replace(/[^a-zA-Z0-9]+/g,"_")
    .replace(/^_+|_+$/g,"")
    .toLowerCase()||"tmax";
}
async function hyrasTmaxExportCurvePdf(event,region,period){
  if(event)event.preventDefault();
  const link=event?.currentTarget||null;
  const oldText=link?.textContent||"Kurve als PDF herunterladen";
  if(link){
    link.style.pointerEvents="none";
    link.style.opacity=".65";
    link.textContent="PDF wird erstellt …";
  }

  try{
    const canvas=document.getElementById("hyrasTmaxRegionCanvas");
    const JsPdf=window.jspdf?.jsPDF;
    if(!canvas)throw new Error("Tmax-Kurvencanvas fehlt.");
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
    pdf.text(`Tagesmaximum - ${region}`,margin,15);

    pdf.setFont("helvetica","normal");
    pdf.setFontSize(9.5);
    pdf.setTextColor(85,95,105);
    pdf.text(
      `${period?.label||""} | taegliches HYRAS-Tmax-Gebietsmittel gegen 1991-2020`,
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

    pdf.addImage(
      image,"PNG",imageX,imageTop,imageWidth,imageHeight,undefined,"FAST"
    );

    pdf.setFont("helvetica","normal");
    pdf.setFontSize(7.5);
    pdf.setTextColor(95,95,95);
    const dataThrough=hyrasTmaxRegionsIndex?.data_through||"";
    const recordFirst=hyrasTmaxRegionsIndex?.records_first_year||1951;
    const recordLast=hyrasTmaxRegionsIndex?.records_last_year||2025;
    pdf.text(
      `Quelle: Deutscher Wetterdienst (DWD), HYRAS-DE-TASMAX | Datenstand: ${dataThrough} | Historische Tagesrekorde: ${recordFirst}-${recordLast}`,
      margin,
      pageHeight-6
    );

    const filename=[
      "hyras_tmax",
      hyrasTmaxPdfFilenamePart(region),
      hyrasTmaxPdfFilenamePart(period?.label||period?.key||"kurve")
    ].join("_")+".pdf";
    pdf.save(filename);
  }catch(error){
    console.error("HYRAS Tmax PDF-Export:",error);
    window.alert(`PDF konnte nicht erstellt werden: ${error.message}`);
  }finally{
    if(link){
      link.style.pointerEvents="";
      link.style.opacity="";
      link.textContent=oldText;
    }
  }
}
function hyrasTmaxRenderCurveChart(region,period,rows){
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

  frame.innerHTML=`<div class="hyras-tmean-region-panel">
    <div class="hyras-tmean-region-head">
      <div>
        <h3>Tagesmaximum – ${region}</h3>
        <p>${period.label} · tägliches HYRAS-Tmax-Gebietsmittel gegen 1991–2020</p>
      </div>
    </div>
    <div class="hyras-tmean-chart-wrap">
      <canvas id="hyrasTmaxRegionCanvas"></canvas>
    </div>
    <div class="hyras-tmean-downloads">
      <a class="hyras-tmean-download" href="#" data-tmax-pdf="1">Kurve als PDF herunterladen</a>
    </div>
    <p class="hyras-tmean-region-note">
      Räumliches Gebietsmittel des täglichen 2-m-Temperaturmaximums.
      Historische Tagesrekorde beziehen sich auf 1951–2025.
    </p>
  </div>`;

  frame.querySelector("a[data-tmax-pdf]")?.addEventListener(
    "click",
    event=>hyrasTmaxExportCurvePdf(event,region,period)
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
    hyrasTmaxRegionsIndex.records_first_year||
    hyrasTmaxRegionsRecords?.first_year||
    1951
  );
  const recordLast=Number(
    hyrasTmaxRegionsIndex.records_last_year||
    hyrasTmaxRegionsRecords?.last_year||
    2025
  );

  hyrasTmaxRegionChart=new Chart(
    document.getElementById("hyrasTmaxRegionCanvas"),
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
            label:`${hyrasTmaxRegionsIndex.year}`,
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
          y:{title:{display:true,text:"Tagesmaximum (°C)"}}
        }
      }
    }
  );
}
async function renderHyrasTmax(){
  try{
    await hyrasTmaxRegionsEnsureLoaded();
    const region=hyrasTmaxRegionName();
    const period=hyrasTmaxCurvePeriod();
    if(!period)return;
    const rows=hyrasTmaxCurveRows(region,period);
    hyrasTmaxSetCurveKpis(region,period,rows);
    hyrasTmaxRenderCurveChart(region,period,rows);
  }catch(error){
    console.error("HYRAS Tmax Gebietskurven:",error);
    const frame=document.getElementById("hyrasMapFrame");
    if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;
  }
}

'''
    text = replace_once(text, anchor, tmax_js + anchor, "Tmax-JavaScript")

    old_tmean_render = '''async function renderHyrasTmean(){
  try{'''
    new_tmean_render = '''async function renderHyrasTmean(){
  if(hyrasTmaxRegionChart){
    hyrasTmaxRegionChart.destroy();
    hyrasTmaxRegionChart=null;
  }
  try{'''
    text = replace_once(text, old_tmean_render, new_tmean_render, "Tmax-Chart Cleanup")

    old_switch_head = '''async function hyrasSwitchParameter(){
  const isTmean=hyrasParameter()==="tmean";'''
    new_switch_head = '''async function hyrasSwitchParameter(){
  const temperatureParameter=hyrasParameter();
  const isTmean=temperatureParameter==="tmean";
  const isTmax=temperatureParameter==="tmax";'''
    text = replace_once(text, old_switch_head, new_switch_head, "Switch-Kopf")

    old_switch_branch = '''  if(isTmean){
    if(custom)custom.style.display="none";if(historical)historical.style.display="none";if(metricGroup)metricGroup.style.display="none";if(regionGroup)regionGroup.hidden=false;
    const oldLink=document.getElementById("hyrasOpenImage");if(oldLink)oldLink.style.display="none";
    const status=document.getElementById("hyrasStatus");if(status)status.textContent="HYRAS Tmean Gebietskurven werden geladen …";
    await hyrasTmeanRegionsEnsureLoaded();hyrasTmeanPopulateRegions();hyrasTmeanPopulateCurvePeriods();
    if(status)status.textContent=`Tmean · Deutschland + 16 Bundesländer · Daten bis ${hyrasDate(hyrasTmeanRegionsIndex.data_through)} · Referenz 1991–2020`;
    await renderHyrasTmean();
  }else{'''
    new_switch_branch = '''  if(isTmean||isTmax){
    if(custom)custom.style.display="none";if(historical)historical.style.display="none";if(metricGroup)metricGroup.style.display="none";if(regionGroup)regionGroup.hidden=false;
    const oldLink=document.getElementById("hyrasOpenImage");if(oldLink)oldLink.style.display="none";
    const status=document.getElementById("hyrasStatus");

    if(isTmean){
      if(status)status.textContent="HYRAS Tmean Gebietskurven werden geladen …";
      await hyrasTmeanRegionsEnsureLoaded();
      hyrasTmeanPopulateRegions();
      hyrasTmeanPopulateCurvePeriods();
      if(status)status.textContent=`Tmean · Deutschland + 16 Bundesländer · Daten bis ${hyrasDate(hyrasTmeanRegionsIndex.data_through)} · Referenz 1991–2020`;
      await renderHyrasTmean();
    }else{
      if(status)status.textContent="HYRAS Tmax Gebietskurven werden geladen …";
      await hyrasTmaxRegionsEnsureLoaded();
      hyrasTmaxPopulateRegions();
      hyrasTmaxPopulateCurvePeriods();
      if(status)status.textContent=`Tmax · Deutschland + 16 Bundesländer · Daten bis ${hyrasDate(hyrasTmaxRegionsIndex.data_through)} · Referenz 1991–2020`;
      await renderHyrasTmax();
    }
  }else{'''
    text = replace_once(text, old_switch_branch, new_switch_branch, "Switch-Zweig")

    old_render_route = '''function renderHyras(){
  if(hyrasParameter()==="tmean"){renderHyrasTmean();return;}'''
    new_render_route = '''function renderHyras(){
  if(hyrasParameter()==="tmean"){renderHyrasTmean();return;}
  if(hyrasParameter()==="tmax"){renderHyrasTmax();return;}'''
    text = replace_once(text, old_render_route, new_render_route, "Render-Routing")

    old_region_listener = '''document.getElementById("hyrasTmeanRegionSelect")?.addEventListener("change",()=>renderHyrasTmean());'''
    new_region_listener = '''document.getElementById("hyrasTmeanRegionSelect")?.addEventListener("change",()=>renderHyras());'''
    text = replace_once(text, old_region_listener, new_region_listener, "Gebiet-Listener")

    TARGET.write_text(text, encoding="utf-8")

    print("HYRAS Tmax Frontend V1 eingebaut:")
    print("- neuer HYRAS-Parameter 2-m-Tagesmaximum")
    print("- Deutschland + 16 Bundesländer")
    print("- 2026 gegen tägliches Mittel 1991-2020")
    print("- historische Max/Min-Linien 1951-2025")
    print("- Rekordjahre im Tooltip")
    print("- PDF-Download der Kurve")
    print("- keine Tmax-Karten in diesem Schritt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
