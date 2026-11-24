// HYRAS_TMIN_FRONTEND_V1
let hyrasTminRegionsIndex=null;
let hyrasTminRegionsCurrent=null;
let hyrasTminRegionsClimate=null;
let hyrasTminRegionsClimateReference=null;
let hyrasTminRegionsRecords=null;
// HYRAS_TMIN_MAP_DOWNLOADS_V1
let hyrasTminMapDownloads=null;
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
  if(hyrasTminRegionsIndex&&hyrasTminRegionsCurrent&&hyrasTminRegionsClimate&&hyrasTminRegionsRecords&&hyrasTminMapDownloads){
    return hyrasTminRegionsIndex;
  }
  if(hyrasTminRegionsLoading)return hyrasTminRegionsLoading;

  hyrasTminRegionsLoading=(async()=>{
    hyrasTminRegionsIndex=await hyrasTminRegionsFetch("index.json");
    const [current,climate,records,maps]=await Promise.all([
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.current_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.climate_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.records_file),
      hyrasTminRegionsFetch(hyrasTminRegionsIndex.map_downloads_file),
    ]);
    hyrasTminRegionsCurrent=current;
    hyrasTminRegionsClimate=climate;
    hyrasTminRegionsClimateReference=String(climate?.reference||hyrasTminRegionsIndex?.default_reference||"1991-2020");
    hyrasTminRegionsRecords=records;
    hyrasTminMapDownloads=maps;
    return hyrasTminRegionsIndex;
  })().finally(()=>{hyrasTminRegionsLoading=null;});

  return hyrasTminRegionsLoading;
}
async function hyrasTminEnsureClimateReference(){
  const reference=hyrasReferencePeriod();
  if(hyrasTminRegionsClimate&&hyrasTminRegionsClimateReference===reference)return hyrasTminRegionsClimate;
  const path=hyrasTminRegionsIndex?.climate_files_by_reference?.[reference]
    ||(reference==="1991-2020"?hyrasTminRegionsIndex?.climate_file:null);
  if(!path)throw new Error(`Tmin-Gebietskurve für Referenz ${hyrasReferenceDisplay()} ist noch nicht veröffentlicht.`);
  const climate=await hyrasTminRegionsFetch(path);
  if(hyrasReferencePeriod()===reference&&hyrasParameter()==="tmin"){
    hyrasTminRegionsClimate=climate;
    hyrasTminRegionsClimateReference=reference;
  }
  return climate;
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
  const preferred=periods.filter(period=>period.key.startsWith("month_")).sort((a,b)=>String(b.end_date).localeCompare(String(a.end_date)))[0]||periods.find(period=>period.key==="summer")||periods[0];
  if(previous&&periods.some(period=>period.key===previous))select.value=previous;
  else if(preferred)select.value=preferred.key;
}
function hyrasTminCurvePeriod(){
  return hyrasTemperatureResolvePeriod(hyrasTminRegionsIndex,hyrasTminPopulateCurvePeriods);
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

  setHeading("hyrasReferenceMean",`Mittel ${hyrasReferenceDisplay()}`);
  document.getElementById("hyrasReferenceMean").textContent=hyrasTminFmt(normal);
  document.getElementById("hyrasReferenceMeanDetail").textContent="exakt dieselben Kalendertage";

  setHeading("hyrasPercentMean","Abweichung");
  document.getElementById("hyrasPercentMean").textContent=hyrasTminFmt(anomaly,"K",true);

  setHeading("hyrasAnomalyMean","Datentage");
  document.getElementById("hyrasAnomalyMean").textContent=
    String(rows.filter(row=>Number.isFinite(row.current)).length);

  document.getElementById("hyrasReferenceNote").textContent=
    hyrasTminRegionsIndex.method_note||
    `HYRAS-Tmin-Gebietsmittel, Referenz ${hyrasReferenceDisplay()}.`;
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
    const exportChart=window.Chart?.getChart(canvas);
    context.drawImage(exportChart?chartCanvasWithWhiteBackground(exportChart):canvas,0,0);

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
      `${period?.label||""} | taegliches HYRAS-Tmin-Gebietsmittel gegen ${hyrasReferencePeriod()}`,
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
function hyrasTminMapHref(path){
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

function hyrasTminRenderCurveChart(region,period,rows){
  const frame=document.getElementById("hyrasMapFrame");
  if(!frame)return;

  const mapsBase=hyrasTminMapDownloads?.periods?.[period.key]||{},maps={...mapsBase,anomaly:(window.HyrasTemperatureInteractive?HyrasTemperatureInteractive.mapForReference(mapsBase, hyrasReferencePeriod(),period.start_date,period.end_date):(hyrasReferencePeriod()==='1991-2020'?mapsBase.anomaly:null))};
  const absClass=maps.absolute?"hyras-tmean-download":"hyras-tmean-download disabled";
  const anomClass=maps.anomaly?"hyras-tmean-download":"hyras-tmean-download disabled";

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
    ${maps.anomaly?`<div class="hyras-tmean-anomaly-preview">
      <div class="hyras-tmean-anomaly-preview-head">
        <div>
          <h4>2-m-Tmin-Abweichung</h4>
          <p>${period.label} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)} · Abweichung gegenüber ${hyrasReferenceDisplay()}</p>
        </div>
      </div>
      <a class="hyras-tmean-anomaly-preview-link" href="${hyrasTemperaturePreviewHref(hyrasTminMapHref(maps.anomaly),hyrasTminRegionsIndex?.data_through)}" target="_blank" rel="noopener">
        <img src="${hyrasTemperaturePreviewHref(hyrasTminMapHref(maps.anomaly),hyrasTminRegionsIndex?.data_through)}" alt="HYRAS 2-m-Tmin-Abweichung ${period.label} gegenüber ${hyrasReferenceDisplay()}" loading="eager">
      </a>
      <div class="hyras-temperature-raster-status" role="status">Rasterabfrage wird geladen …</div>
    </div>`:`<div class="hyras-tmean-anomaly-preview"><div class="hyras-tmean-anomaly-preview-empty">Für diesen Zeitraum ist keine fertige Tmin-Abweichungskarte verfügbar.</div><div class="hyras-temperature-raster-status" role="status">Rasterabfrage wird geladen …</div></div>`}
    <div class="hyras-tmean-downloads" role="group" aria-label="HYRAS-Karten als PNG herunterladen">
      <a class="${absClass}" ${maps.absolute?`href="${hyrasTminMapHref(maps.absolute)}" data-tmin-map="${maps.absolute}" data-tmin-filename="hyras_tmin_${period.key}_temperatur.png"`:""}>Tmin-Karte herunterladen</a>
      <a class="${anomClass}" ${maps.anomaly?`href="${hyrasTminMapHref(maps.anomaly)}" data-tmin-map="${maps.anomaly}" data-tmin-filename="hyras_tmin_${period.key}_abweichung_${hyrasReferencePeriod().replace("-","_")}.png"`:""}>Abweichungskarte ${hyrasReferenceDisplay()} herunterladen</a>
    </div>
    <div class="hyras-tmean-region-head">
      <div>
        <h3>Tagesminimum – ${region}</h3>
        <p>${period.label} · tägliches HYRAS-Tmin-Gebietsmittel gegen ${hyrasReferenceDisplay()}</p>
      </div>
    </div>
    <div class="hyras-tmean-chart-wrap">
      <canvas id="hyrasTminRegionCanvas"></canvas>
    </div>
    <div class="hyras-tmean-downloads hyras-curve-downloads">
      <a class="hyras-tmean-download" href="#" data-tmin-pdf="1">Kurve als PDF herunterladen</a>
    </div>
    ${hyrasDailyAnomalyPanelHtml("tmin")}

    <p class="hyras-tmean-region-note">
      ${maps.anomaly
        ?"Absolute Tmin- und Anomaliekarte stehen als fertige PNGs bereit."
        :"Für diesen laufenden Zeitraum ist die absolute Tmin-Karte verfügbar; eine Raster-Anomalie wird erst für vollständige Monate/Jahreszeiten angeboten."}
      Historische Tagesrekorde beziehen sich auf
      ${hyrasTminRegionsIndex.records_first_year||1951}–${hyrasTminRegionsIndex.records_last_year||2025}.
    </p>
  </div>`;

  window.HyrasTemperatureInteractive?.mount(frame.querySelector(".hyras-tmean-anomaly-preview"),{entry:mapsBase,parameter:"tmin",reference:hyrasReferencePeriod(),key:period.key,start:period.start_date,end:period.end_date,version:hyrasTminRegionsIndex?.data_through||"1",base:HYRAS_DATA_BASE,boundary:hyrasIndex?.interactive?.boundary_overlay_1km});
  frame.querySelectorAll("a[data-tmin-map]").forEach(link=>{
    link.addEventListener("click",event=>hyrasTminForceMapDownload(
      event,
      link.dataset.tminMap,
      link.dataset.tminFilename
    ));
  });
  frame.querySelector("a[data-tmin-pdf]")?.addEventListener(
    "click",
    event=>hyrasTminExportCurvePdf(event,region,period)
  );
  hyrasDailyAnomalyMount("tmin",rows);

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
            label:`Mittel ${hyrasReferenceDisplay()}`,
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
  const current=hyrasTemperatureRenderStart("tmin");
  try{
    await hyrasTminRegionsEnsureLoaded();
    if(!current())return;
    await hyrasTminEnsureClimateReference();
    if(!current())return;
    const region=hyrasTminRegionName();
    const period=hyrasTminCurvePeriod();
    if(!period)return;

    const rows=hyrasTminCurveRows(region,period);
    hyrasTminSetCurveKpis(region,period,rows);
    hyrasTminRenderCurveChart(region,period,rows);
  }catch(error){
    if(!current())return;
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
  ++hyrasTemperatureRenderGeneration;
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
  if(historical)historical.style.display="";
  if(metricGroup)metricGroup.style.display="none";
  if(regionGroup)regionGroup.hidden=false;

  const oldLink=document.getElementById("hyrasOpenImage");
  if(oldLink)oldLink.style.display="none";

  const status=document.getElementById("hyrasStatus");
  if(status)status.textContent="HYRAS Tmin Gebietskurven werden geladen …";
  const frame=document.getElementById("hyrasMapFrame");
  if(frame)frame.innerHTML='<div class="hyras-loading">Temperaturdaten werden geladen …</div>';

  await hyrasTminRegionsEnsureLoaded();
  if(hyrasParameter()!=="tmin")return;
  hyrasTminPopulateRegions();
  hyrasTminPopulateCurvePeriods();

  if(status){
    status.textContent=
      `Tmin · Deutschland + 16 Bundesländer · Daten bis ${hyrasDate(hyrasTminRegionsIndex.data_through)} · Referenz ${hyrasReferenceDisplay()}`;
  }
  await renderHyrasTmin();
};

