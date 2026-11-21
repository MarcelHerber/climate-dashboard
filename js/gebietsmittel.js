/* gebietsmittel.js – Gebietsmittel, Kartenvergleich, Klima-Index, Seit Jahresbeginn
   Aus index.html ausgelagert (Schritt 2a). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= MONATSDATEN LADEN =================

// ================= GEBIETSMITTEL =================
function updateMonthly(){
  if(!document.getElementById("monthly")?.classList.contains("active")) return;
  if(!monthlyData.length) return;
  const area=document.getElementById("monthlyAreaSelect").value;
  const param=document.getElementById("paramSelect").value;
  const selection=document.getElementById("monthSelect").value;
  const values=seriesFor(area,selection,param);
  const reference=updateMonthlyReferenceUi();
  const climateMean=monthlyReferenceMean(values,reference);
  const labels=values.map(item=>item.year);
  const dataValues=values.map(item=>item.value);
  // Append the current partial month to THIS chart, not a separate widget.
  const observed=observedMonthlyBar(area,selection,param,values);
  if(observed)labels.push(observed.year);

  // Frei wählbares gleitendes Mittel. Der Wert eines Jahres umfasst dieses Jahr
  // und die unmittelbar vorhergehenden Jahre innerhalb der gewählten Fensterbreite.
  const rollingWindow=updateMonthlyRollingUi();
  const rollingMean=monthlyRollingSeries(values,rollingWindow);

  // Bei Temperatur beginnt die y-Achse knapp unter dem niedrigsten Wert,
  // statt unnötig bei 0 °C zu starten.
  let temperatureScaleMin;
  if(param==="temp"){
    const finiteValues=dataValues.filter(Number.isFinite);
    if(finiteValues.length){
      const lowest=Math.min(...finiteValues);
      const highest=Math.max(...finiteValues);
      const padding=Math.max(0.4,(highest-lowest)*0.06);
      temperatureScaleMin=Math.floor((lowest-padding)*2)/2;
    }
  }

  const sortedHigh=[...values].sort((a,b)=>b.value-a.value).slice(0,3);
  const sortedLow=[...values].sort((a,b)=>a.value-b.value).slice(0,3);
  document.getElementById("top3High").innerHTML=sortedHigh.map(item=>`<li>${item.year}: ${formatValue(item.value,param)}</li>`).join("");
  document.getElementById("top3Low").innerHTML=sortedLow.map(item=>`<li>${item.year}: ${formatValue(item.value,param)}</li>`).join("");
  document.getElementById("climateMean").textContent=formatValue(climateMean,param);

  if(monthlyChart) monthlyChart.destroy();
  const observedHatch=observed?observedMonthlyHatch(document.getElementById("monthlyChart").getContext("2d")):null;
  const provisionalInfo=document.getElementById("monthlyObservedChartNote");
  if(provisionalInfo){
    provisionalInfo.hidden=!observed;
    if(observed)provisionalInfo.textContent=`${observed.year} schraffiert: HYRAS-Beobachtungen bis ${observed.through.slice(8,10)}.${observed.through.slice(5,7)}.${observed.through.slice(0,4)} · vorläufig, keine Prognose und kein vollständiger Monatswert.`;
  }
  monthlyChart=new Chart(document.getElementById("monthlyChart"),{
    type:"bar",
    data:{
      labels,
      datasets:[
        {
          type:"bar",
          label:PARAM_META[param].label,
          data:dataValues,
          backgroundColor:dataValues.map(value=>primaryBarColor(param,value,climateMean)),
          borderWidth:0,
          order:2
        },
        ...(observed?[{
          type:"bar",
          label:`${observed.year} vorläufig · HYRAS bis ${observed.through.slice(8,10)}.${observed.through.slice(5,7)}.`,
          data:labels.map((_,i)=>i===labels.length-1?observed.value:null),
          grouped:false,
          backgroundColor:observedHatch,
          borderColor:"#27658f",
          borderWidth:1.5,
          order:2
        }]:[]),
        {
          type:"line",
          label:`Mittel ${reference.label}`,
          data:dataValues.map(()=>climateMean),
          borderColor:"#111",
          borderDash:[7,5],
          borderWidth:2,
          pointRadius:0,
          order:1
        },
        ...(rollingWindow?[{
          type:"line",
          label:`${rollingWindow}-jähriges gleitendes Mittel`,
          data:rollingMean,
          borderColor:monthlyRollingColor(param),
          borderDash:[2,5],
          borderWidth:2.5,
          pointRadius:0,
          pointHoverRadius:3,
          tension:0.12,
          spanGaps:false,
          order:0
        }]:[])
      ]
    },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        title:{display:true,text:`${area}: ${periodLabel(selection)} – ${PARAM_META[param].label}`},
        datalabels:{display:false},
        zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},drag:{enabled:true},mode:"x"}}
      },
      scales:{
        x:{ticks:{maxTicksLimit:18}},
        y:{
          beginAtZero:param!=="temp",
          ...(param==="temp" && Number.isFinite(temperatureScaleMin)?{min:temperatureScaleMin}:{}),
          title:{display:true,text:PARAM_META[param].unit}
        }
      }
    }
  });

  const deviations=dataValues.map(value=>climateMean===null?null:value-climateMean);
  if(monthlyDeviationChart) monthlyDeviationChart.destroy();
  monthlyDeviationChart=new Chart(document.getElementById("monthlyDeviationChart"),{
    type:"bar",
    data:{labels,datasets:[{
      label:`Abweichung vom Mittel ${reference.label} (${PARAM_META[param].unit})`,
      data:deviations,
      backgroundColor:deviations.map(value=>deviationColor(param,value))
    }]},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      plugins:{
        title:{display:true,text:`${area}: Abweichungen zu ${reference.label} – ${periodLabel(selection)}`},
        datalabels:{display:false}
      },
      scales:{
        x:{ticks:{maxTicksLimit:18}},
        y:{title:{display:true,text:PARAM_META[param].unit}}
      }
    }
  });
}


// ================= 16.3 GEBIETSMITTEL-KARTENVERGLEICH + RANKING + DETAIL =================
const REGIONAL_MAP_STATE_AREA={
  "Baden-Württemberg":"Baden-Württemberg",
  "Bayern":"Bayern",
  "Berlin":"Brandenburg/Berlin",
  "Brandenburg":"Brandenburg",
  "Bremen":"Niedersachsen/Hamburg/Bremen",
  "Hamburg":"Niedersachsen/Hamburg/Bremen",
  "Hessen":"Hessen",
  "Mecklenburg-Vorpommern":"Mecklenburg-Vorpommern",
  "Niedersachsen":"Niedersachsen",
  "Nordrhein-Westfalen":"Nordrhein-Westfalen",
  "Rheinland-Pfalz":"Rheinland-Pfalz",
  "Saarland":"Saarland",
  "Sachsen":"Sachsen",
  "Sachsen-Anhalt":"Sachsen-Anhalt",
  "Schleswig-Holstein":"Schleswig-Holstein",
  "Thüringen":"Thüringen"
};
const REGIONAL_MAP_STATE_SHORT={
  "Baden-Württemberg":"BW","Bayern":"BY","Berlin":"BE","Brandenburg":"BB","Bremen":"HB","Hamburg":"HH","Hessen":"HE",
  "Mecklenburg-Vorpommern":"MV","Niedersachsen":"NI","Nordrhein-Westfalen":"NW","Rheinland-Pfalz":"RP","Saarland":"SL","Sachsen":"SN",
  "Sachsen-Anhalt":"ST","Schleswig-Holstein":"SH","Thüringen":"TH"
};
const REGIONAL_MAP_COLORS={
  negative:["#54278f","#756bb1","#9e9ac8","#cbc9e2","#e7e7ef"],
  positive:["#fee0d2","#fc9272","#ef3b2c","#cb181d","#8b0000"],
  dry:["#8c510a","#bf812d","#dfc27d","#f6e8c3"],
  wet:["#d1e5f0","#92c5de","#4393c3","#2166ac"],
  low:["#313695","#74add1","#e0f3f8","#ffffbf","#fdae61","#d73027"]
};

function regionalMapParam(){return document.getElementById("paramSelect")?.value||"rain";}
function regionalMapSelection(){return document.getElementById("monthSelect")?.value||"07";}
function regionalMapMode(){
  const select=document.getElementById("regionalMapModeSelect");
  let mode=select?.value||"anomaly";
  if(regionalMapParam()==="temp" && mode==="percent"){
    mode="anomaly";
    if(select)select.value="anomaly";
  }
  return mode;
}
function regionalMapRowsByDate(area){
  return new Map(areaRows(area).map(item=>[item.date,item]));
}
function regionalMapAvailableSlots(year,selection,param,area="Deutschland"){
  const byDate=regionalMapRowsByDate(area);
  return periodKeys(year,selection).map((key,index)=>{
    const row=byDate.get(`${key.year}-${String(key.month).padStart(2,"0")}`);
    return row && row[param]!==null && row[param]!==undefined && Number.isFinite(Number(row[param])) ? index : null;
  }).filter(Number.isInteger);
}
function regionalMapAvailableYears(){
  if(!monthlyData.length)return [];
  const param=regionalMapParam(),selection=regionalMapSelection();
  const rawYears=[...new Set(areaRows("Deutschland").map(item=>Number(item.date.slice(0,4))))].filter(Number.isFinite);
  if(!rawYears.length)return [];
  let minYear=Math.min(...rawYears),maxYear=Math.max(...rawYears);
  if(selection==="winter") maxYear+=1;
  const years=[];
  for(let year=minYear;year<=maxYear;year++){
    if(regionalMapAvailableSlots(year,selection,param).length)years.push(year);
  }
  return years;
}
function regionalMapYearIsPartial(year){
  const selection=regionalMapSelection(),param=regionalMapParam();
  return regionalMapAvailableSlots(year,selection,param).length<periodKeys(year,selection).length;
}
function populateRegionalMapYears({preserve=true}={}){
  const selectA=document.getElementById("regionalMapYearSelect");
  const selectB=document.getElementById("regionalMapYearBSelect");
  if(!selectA||!selectB)return;
  const previousA=Number(selectA.value),previousB=Number(selectB.value);
  const years=regionalMapAvailableYears();
  [selectA,selectB].forEach(select=>{
    select.innerHTML="";
    years.forEach(year=>{
      const option=document.createElement("option");
      option.value=year;
      option.textContent=`${year}${regionalMapYearIsPartial(year)?" (teilweise)":""}`;
      select.appendChild(option);
    });
  });
  if(!years.length)return;
  const latest=years[years.length-1],previous=years.length>1?years[years.length-2]:latest;
  selectA.value=String(preserve&&years.includes(previousA)?previousA:previous);
  selectB.value=String(preserve&&years.includes(previousB)?previousB:latest);
}
function regionalMapComparableSlots(yearA,yearB,selection,param){
  const slotsA=new Set(regionalMapAvailableSlots(yearA,selection,param));
  const slotsB=new Set(regionalMapAvailableSlots(yearB,selection,param));
  return periodKeys(yearA,selection).map((_,index)=>index).filter(index=>slotsA.has(index)&&slotsB.has(index));
}
function regionalMapPeriodComparisonLabel(selection,slots,year){
  const keys=periodKeys(year,selection);
  if(slots.length===keys.length)return periodLabel(selection);
  if(!slots.length)return `${periodLabel(selection)} · keine gemeinsamen Daten`;
  const months=slots.map(index=>keys[index]?.month).filter(Number.isFinite);
  if(months.length===1)return `${periodLabel(selection)} (${MONTH_NAMES[months[0]-1]})`;
  return `${periodLabel(selection)} (${MONTH_NAMES[months[0]-1]}–${MONTH_NAMES[months[months.length-1]-1]})`;
}
function regionalMapAreaForState(name){
  const preferred=REGIONAL_MAP_STATE_AREA[name]||name;
  const areas=new Set(availableAreas());
  if(areas.has(name))return name;
  if(areas.has(preferred))return preferred;
  return null;
}
function regionalMapAggregateSlots(area,year,selection,param,slots){
  if(!area||!slots.length)return null;
  const byDate=regionalMapRowsByDate(area);
  const keys=periodKeys(year,selection);
  const selected=slots.map(index=>({key:keys[index],entry:byDate.get(`${keys[index].year}-${String(keys[index].month).padStart(2,"0")}`)}));
  if(selected.some(item=>!item.entry||item.entry[param]===null||item.entry[param]===undefined||!Number.isFinite(Number(item.entry[param]))))return null;
  if(param==="temp"){
    let weighted=0,totalDays=0;
    selected.forEach(({key,entry})=>{
      const days=daysInMonth(key.year,key.month);
      weighted+=Number(entry.temp)*days;
      totalDays+=days;
    });
    return totalDays?weighted/totalDays:null;
  }
  return selected.reduce((sum,{entry})=>sum+Number(entry[param]),0);
}
function regionalMapReferenceValue(area,param,selection,reference,slots){
  if(!area||!slots.length)return null;
  const values=[];
  for(let year=reference.start;year<=reference.end;year++){
    const value=regionalMapAggregateSlots(area,year,selection,param,slots);
    if(Number.isFinite(value))values.push(value);
  }
  return values.length>=29?mean(values):null;
}
function regionalMapRecord(area,year,param,selection,reference,slots){
  if(!area)return {value:null,reference:null,anomaly:null,percent:null};
  const value=regionalMapAggregateSlots(area,year,selection,param,slots);
  const ref=regionalMapReferenceValue(area,param,selection,reference,slots);
  return {
    value:Number.isFinite(value)?value:null,
    reference:Number.isFinite(ref)?ref:null,
    anomaly:Number.isFinite(value)&&Number.isFinite(ref)?value-ref:null,
    percent:Number.isFinite(value)&&Number.isFinite(ref)&&ref!==0?value/ref*100:null
  };
}
function regionalMapMetric(record,mode){
  if(mode==="absolute")return record.value;
  if(mode==="percent")return record.percent;
  return record.anomaly;
}
function regionalMapMetricLabel(param,mode){
  if(mode==="absolute")return `${PARAM_META[param].label} (${param==="rain"?"l/m²":PARAM_META[param].unit})`;
  if(mode==="percent")return "Vom Mittel (%)";
  return `Abweichung (${param==="rain"?"l/m²":PARAM_META[param].unit})`;
}
function regionalMapMetricText(value,param,mode,{difference=false}={}){
  if(!Number.isFinite(value))return "–";
  const sign=(mode==="anomaly"||difference)&&value>0?"+":"";
  if(mode==="percent")return `${sign}${value.toFixed(difference?1:0).replace(".",",")} ${difference?"Prozentpunkte":"%"}`;
  if(param==="temp")return `${sign}${value.toFixed(2).replace(".",",")} °C`;
  const unit=param==="rain"?"l/m²":"h";
  return `${sign}${value.toFixed(1).replace(".",",")} ${unit}`;
}

function regionalHistoryDescriptor(param){
  if(param==="temp")return {high:"wärmsten",low:"kältesten",noun:"Temperatur"};
  if(param==="rain")return {high:"niederschlagsreichsten",low:"trockensten",noun:"Niederschlag"};
  return {high:"sonnigsten",low:"sonnenärmsten",noun:"Sonnenscheindauer"};
}
function regionalHistoricalEntries(area,param,selection,slots){
  if(!area||!slots.length)return [];
  const rawYears=[...new Set(areaRows(area).map(item=>Number(item.date.slice(0,4))))].filter(Number.isFinite);
  if(!rawYears.length)return [];
  let minYear=Math.min(...rawYears),maxYear=Math.max(...rawYears);
  if(selection==="winter")maxYear+=1;
  const entries=[];
  for(let year=minYear;year<=maxYear;year++){
    const value=regionalMapAggregateSlots(area,year,selection,param,slots);
    if(Number.isFinite(value))entries.push({year,value});
  }
  return entries;
}
function regionalHistoricalRank(entries,year){
  const target=entries.find(item=>item.year===year);
  if(!target||!entries.length)return null;
  const sorted=[...entries].sort((a,b)=>b.value-a.value||a.year-b.year);
  const rankHigh=sorted.findIndex(item=>item.year===year)+1;
  const sortedLow=[...entries].sort((a,b)=>a.value-b.value||a.year-b.year);
  const rankLow=sortedLow.findIndex(item=>item.year===year)+1;
  const below=entries.filter(item=>item.value<target.value).length;
  const equal=entries.filter(item=>item.value===target.value).length;
  const percentile=entries.length>1?100*(below+0.5*equal)/entries.length:100;
  return {year,value:target.value,rankHigh,rankLow,total:entries.length,percentile};
}
function regionalHistoryPercentileText(rank,param){
  if(!rank)return "–";
  const d=regionalHistoryDescriptor(param);
  return `Rang ${rank.rankHigh} von ${rank.total} der ${d.high} · Gegenrang ${rank.rankLow} der ${d.low} · Perzentil ${rank.percentile.toFixed(1).replace(".",",")}`;
}
function renderRegionalHistoricalContext(area,displayName,param,selection,slots,yearA,yearB,periodText){
  const entries=regionalHistoricalEntries(area,param,selection,slots);
  const rankA=regionalHistoricalRank(entries,yearA),rankB=regionalHistoricalRank(entries,yearB);
  const descriptor=regionalHistoryDescriptor(param);
  const set=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
  set("regionalHistoryTitle",`Historischer Kontext · ${displayName}`);
  set("regionalHistoryAreaBadge",displayName);
  set("regionalHistorySubtitle",`${periodText} · historischer Vergleich mit exakt denselben Teilmonaten`);
  set("regionalHistoryALabel",`${yearA} · historischer Rang`);
  set("regionalHistoryBLabel",`${yearB} · historischer Rang`);
  set("regionalHistoryAValue",rankA?`${rankA.rankHigh} / ${rankA.total}`:"–");
  set("regionalHistoryBValue",rankB?`${rankB.rankHigh} / ${rankB.total}`:"–");
  set("regionalHistoryADetail",rankA?`${regionalMapMetricText(rankA.value,param,"absolute")} · ${regionalHistoryPercentileText(rankA,param)}`:"Für dieses Jahr liegt im historischen Vergleich kein vollständiger Wert vor.");
  set("regionalHistoryBDetail",rankB?`${regionalMapMetricText(rankB.value,param,"absolute")} · ${regionalHistoryPercentileText(rankB,param)}`:"Für dieses Jahr liegt im historischen Vergleich kein vollständiger Wert vor.");
  if(!entries.length){
    set("regionalHistoryHighValue","–");set("regionalHistoryHighDetail","keine historischen Vergleichswerte");
    set("regionalHistoryLowValue","–");set("regionalHistoryLowDetail","keine historischen Vergleichswerte");
    set("regionalHistoryText","Für diese Auswahl liegen keine ausreichend langen historischen Vergleichsdaten vor.");
    return;
  }
  const high=[...entries].sort((a,b)=>b.value-a.value||a.year-b.year)[0];
  const low=[...entries].sort((a,b)=>a.value-b.value||a.year-b.year)[0];
  set("regionalHistoryHighValue",regionalMapMetricText(high.value,param,"absolute"));
  set("regionalHistoryHighDetail",`${high.year} · Rang 1 der ${descriptor.high}`);
  set("regionalHistoryLowValue",regionalMapMetricText(low.value,param,"absolute"));
  set("regionalHistoryLowDetail",`${low.year} · Rang 1 der ${descriptor.low}`);
  const first=Math.min(...entries.map(item=>item.year)),last=Math.max(...entries.map(item=>item.year));
  let sentence=`Für ${displayName} umfasst der historische Vergleich ${entries.length} auswertbare Jahre (${first}–${last}). `;
  if(rankA&&rankB){
    const moreExtreme=rankA.rankHigh<rankB.rankHigh?yearA:rankB.rankHigh<rankA.rankHigh?yearB:null;
    sentence+=`${yearA} liegt auf Rang ${rankA.rankHigh} der ${descriptor.high}, ${yearB} auf Rang ${rankB.rankHigh}. `;
    if(moreExtreme)sentence+=`${moreExtreme} liegt damit näher am historischen oberen Extrem. `;
    else sentence+="Beide Jahre besitzen denselben Rang am oberen Ende der historischen Verteilung. ";
    sentence+=`Die Perzentile betragen ${rankA.percentile.toFixed(1).replace(".",",")} (${yearA}) und ${rankB.percentile.toFixed(1).replace(".",",")} (${yearB}).`;
  }else sentence+="Mindestens eines der beiden gewählten Jahre ist für diesen historischen Vergleich nicht vollständig verfügbar.";
  set("regionalHistoryText",sentence);
}

async function downloadRegionalMapPanel(mapName){
  const ids={A:{map:"regionalMap",button:"regionalMapDownloadA",title:"regionalMapTitleA"},B:{map:"regionalMapB",button:"regionalMapDownloadB",title:"regionalMapTitleB"},D:{map:"regionalMapDiff",button:"regionalMapDownloadDiff",title:"regionalMapTitleDiff"}};
  const cfg=ids[mapName];if(!cfg)return;
  const mapEl=document.getElementById(cfg.map),button=document.getElementById(cfg.button);
  const panel=mapEl?.closest(".regional-map-panel");
  if(!mapEl||!panel)return;
  if(typeof html2canvas!=="function"){alert("Die Exportbibliothek konnte nicht geladen werden.");return;}
  const yearA=document.getElementById("regionalMapYearSelect")?.value||"A",yearB=document.getElementById("regionalMapYearBSelect")?.value||"B";
  const param=regionalMapParam(),period=periodLabel(regionalMapSelection());
  const kind=mapName==="A"?yearA:mapName==="B"?yearB:`${yearA}_minus_${yearB}`;
  const filename=safeExportFilename(`Gebietsmittelkarte_${PARAM_META[param].label}_${period}_${kind}`,"png");
  if(button){button.disabled=true;button.textContent="…";}
  panel.classList.add("regional-map-exporting");
  try{
    const mapObj=mapName==="A"?regionalMap:mapName==="B"?regionalMapB:regionalMapDiff;
    mapObj?.invalidateSize(false);
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    const canvas=await window.captureDashboardWithWhiteBackground(panel,{scale:3,backgroundColor:"#fbfcfd",useCORS:true,logging:false});
    const link=document.createElement("a");link.download=filename;link.href=canvas.toDataURL("image/png",1);document.body.appendChild(link);link.click();link.remove();
  }catch(error){console.error("Kartenexport:",error);alert(`Karte konnte nicht exportiert werden: ${error.message}`);}
  finally{panel.classList.remove("regional-map-exporting");if(button){button.disabled=false;button.textContent="PNG ↓";}}
}

function regionalRankingSortRows(rows){
  const sort=document.getElementById("regionalRankingSort")?.value||"desc";
  const copy=[...rows];
  if(sort==="asc")return copy.sort((a,b)=>a.diff-b.diff||a.name.localeCompare(b.name,"de"));
  if(sort==="abs")return copy.sort((a,b)=>Math.abs(b.diff)-Math.abs(a.diff)||b.diff-a.diff||a.name.localeCompare(b.name,"de"));
  if(sort==="alpha")return copy.sort((a,b)=>a.name.localeCompare(b.name,"de"));
  return copy.sort((a,b)=>b.diff-a.diff||a.name.localeCompare(b.name,"de"));
}
function regionalRankingBarClass(value){
  if(!Number.isFinite(value)||Math.abs(value)<1e-12)return "neutral";
  return value>0?"positive":"negative";
}
function renderRegionalRanking(byState,param,mode,yearA,yearB,periodText){
  const body=document.getElementById("regionalRankingBody");
  if(!body)return;
  const rows=[...byState.entries()].map(([name,item])=>({name,...item})).filter(item=>Number.isFinite(item.diff));
  document.getElementById("regionalRankingYearAHead").textContent=String(yearA);
  document.getElementById("regionalRankingYearBHead").textContent=String(yearB);
  const subtitle=document.getElementById("regionalRankingSubtitle");
  if(subtitle)subtitle.textContent=`${periodText} · ${regionalMapMetricLabel(param,mode)} · ${yearA} minus ${yearB}`;
  if(!rows.length){
    body.innerHTML='<tr><td colspan="5" class="regional-ranking-no-data">Für diese Auswahl liegen keine vergleichbaren Bundeslandwerte vor.</td></tr>';
    ["regionalRankingMax","regionalRankingMin","regionalRankingClosest"].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent="–";});
    ["regionalRankingMaxDetail","regionalRankingMinDetail","regionalRankingClosestDetail"].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent="–";});
    return;
  }
  const maxRow=[...rows].sort((a,b)=>b.diff-a.diff)[0];
  const minRow=[...rows].sort((a,b)=>a.diff-b.diff)[0];
  const closest=[...rows].sort((a,b)=>Math.abs(a.diff)-Math.abs(b.diff))[0];
  const setExtreme=(valueId,detailId,row)=>{
    document.getElementById(valueId).textContent=regionalMapMetricText(row?.diff,param,mode,{difference:true});
    document.getElementById(detailId).textContent=row?.name||"–";
  };
  setExtreme("regionalRankingMax","regionalRankingMaxDetail",maxRow);
  setExtreme("regionalRankingMin","regionalRankingMinDetail",minRow);
  setExtreme("regionalRankingClosest","regionalRankingClosestDetail",closest);
  const maxAbs=Math.max(...rows.map(row=>Math.abs(row.diff)),1e-12);
  const sorted=regionalRankingSortRows(rows);
  body.innerHTML=sorted.map((row,index)=>{
    const width=Math.max(2,Math.min(100,Math.abs(row.diff)/maxAbs*100));
    const areaText=row.area&&row.area!==row.name?` title="DWD-Gebiet: ${row.area}"`:"";
    return `<tr data-area="${row.area||""}" data-name="${row.name}"${areaText}><td>${index+1}</td><td>${row.name}</td><td>${regionalMapMetricText(row.metricA,param,mode)}</td><td>${regionalMapMetricText(row.metricB,param,mode)}</td><td class="regional-ranking-diff-cell"><div class="regional-ranking-diff-layout"><span class="regional-ranking-diff-value">${regionalMapMetricText(row.diff,param,mode,{difference:true})}</span><span class="regional-ranking-bar-track"><span class="regional-ranking-bar ${regionalRankingBarClass(row.diff)}" style="display:block;width:${width.toFixed(1)}%"></span></span></div></td></tr>`;
  }).join("");
  body.querySelectorAll("tr[data-area]").forEach(row=>row.addEventListener("click",()=>regionalMapSelectArea(row.dataset.area,row.dataset.name)));
}

function regionalReportDirectionWord(param,value){
  if(!Number.isFinite(value)||Math.abs(value)<1e-12)return "nahezu gleich";
  if(param==="temp")return value>0?"wärmer":"kälter";
  if(param==="rain")return value>0?"niederschlagsreicher":"niederschlagsärmer";
  return value>0?"sonniger":"sonnenärmer";
}
function regionalReportMetricPhrase(param,mode){
  if(mode==="percent")return "beim Anteil am Klimamittel";
  if(mode==="anomaly")return "bei der Abweichung vom Klimamittel";
  if(param==="temp")return "bei der Temperatur";
  if(param==="rain")return "beim Niederschlag";
  return "bei der Sonnenscheindauer";
}
function regionalReportListHtml(rows,param,mode){
  if(!rows.length)return '<li class="regional-report-empty">Keine vergleichbaren Werte.</li>';
  return rows.map((row,index)=>{
    const cls=row.diff>0?"regional-report-positive":row.diff<0?"regional-report-negative":"regional-report-neutral";
    return `<li data-area="${row.area||""}" data-name="${row.name}"><span class="regional-report-rank">${index+1}</span><span class="regional-report-name">${row.name}</span><span class="regional-report-value ${cls}">${regionalMapMetricText(row.diff,param,mode,{difference:true})}</span></li>`;
  }).join("");
}
function regionalReportPlainText(){
  const text=document.getElementById("regionalReportText")?.textContent?.trim()||"";
  const subtitle=document.getElementById("regionalReportSubtitle")?.textContent?.trim()||"";
  const pos=[...document.querySelectorAll("#regionalReportTopPositive li[data-name]")].map((li,i)=>`${i+1}. ${li.dataset.name}: ${li.querySelector('.regional-report-value')?.textContent||''}`);
  const neg=[...document.querySelectorAll("#regionalReportTopNegative li[data-name]")].map((li,i)=>`${i+1}. ${li.dataset.name}: ${li.querySelector('.regional-report-value')?.textContent||''}`);
  return ["Deutschland-Vergleichsbericht",subtitle,"",text,"", "Top 5 stärkste Zunahmen A − B",...pos,"", "Top 5 stärkste Abnahmen A − B",...neg].join("\n");
}
async function copyRegionalReport(){
  const status=document.getElementById("regionalReportCopyStatus");
  try{
    const text=regionalReportPlainText();
    if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);
    else{const ta=document.createElement("textarea");ta.value=text;ta.style.position="fixed";ta.style.opacity="0";document.body.appendChild(ta);ta.select();document.execCommand("copy");ta.remove();}
    if(status)status.textContent="Bericht kopiert.";
  }catch(_error){if(status)status.textContent="Kopieren war nicht möglich.";}
  window.setTimeout(()=>{if(status)status.textContent="";},2200);
}
function renderRegionalComparisonReport(byState,param,mode,yearA,yearB,periodText,germanyA,germanyB,germanyMetricA,germanyMetricB,reference){
  const rows=[...byState.entries()].map(([name,item])=>({name,...item})).filter(row=>Number.isFinite(row.diff));
  const subtitle=document.getElementById("regionalReportSubtitle");
  if(subtitle)subtitle.textContent=`${periodText} · ${PARAM_META[param].label} · ${yearA} gegen ${yearB} · Referenz ${reference.label}`;
  const set=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
  if(!rows.length){
    set("regionalReportText","Für diese Auswahl liegen keine ausreichend vergleichbaren Bundeslandwerte vor.");
    ["regionalReportGermanyDiff","regionalReportPositiveCount","regionalReportNegativeCount","regionalReportRange"].forEach(id=>set(id,"–"));
    const p=document.getElementById("regionalReportTopPositive"),n=document.getElementById("regionalReportTopNegative");
    if(p)p.innerHTML='<li class="regional-report-empty">Keine Daten.</li>';if(n)n.innerHTML='<li class="regional-report-empty">Keine Daten.</li>';
    return;
  }
  const eps=1e-9;
  const positive=rows.filter(r=>r.diff>eps).sort((a,b)=>b.diff-a.diff);
  const negative=rows.filter(r=>r.diff<-eps).sort((a,b)=>a.diff-b.diff);
  const neutral=rows.length-positive.length-negative.length;
  const maxRow=[...rows].sort((a,b)=>b.diff-a.diff)[0],minRow=[...rows].sort((a,b)=>a.diff-b.diff)[0];
  const strongestPositive=positive[0]||null,strongestNegative=negative[0]||null;
  const range=maxRow.diff-minRow.diff;
  const germanyDiff=Number.isFinite(germanyMetricA)&&Number.isFinite(germanyMetricB)?germanyMetricA-germanyMetricB:null;
  set("regionalReportGermanyDiff",regionalMapMetricText(germanyDiff,param,mode,{difference:true}));
  set("regionalReportGermanyDetail",`${yearA} − ${yearB}`);
  set("regionalReportPositiveCount",String(positive.length));
  set("regionalReportNegativeCount",String(negative.length));
  set("regionalReportRange",regionalMapMetricText(range,param,mode,{difference:true}));
  const topP=document.getElementById("regionalReportTopPositive"),topN=document.getElementById("regionalReportTopNegative");
  if(topP)topP.innerHTML=regionalReportListHtml(positive.slice(0,5),param,mode);
  if(topN)topN.innerHTML=regionalReportListHtml(negative.slice(0,5),param,mode);
  [topP,topN].filter(Boolean).forEach(list=>list.querySelectorAll("li[data-area]").forEach(li=>li.addEventListener("click",()=>regionalMapSelectArea(li.dataset.area,li.dataset.name))));

  const absDiff=Number.isFinite(germanyA?.value)&&Number.isFinite(germanyB?.value)?germanyA.value-germanyB.value:null;
  const direction=regionalReportDirectionWord(param,absDiff);
  const absText=regionalMapMetricText(Math.abs(absDiff),param,"absolute");
  const metricPhrase=regionalReportMetricPhrase(param,mode);
  let first;
  if(Number.isFinite(absDiff)&&Math.abs(absDiff)>=eps){
    first=`Deutschland war im ${periodText} ${yearA} insgesamt ${absText} ${direction} als ${yearB}.`;
  }else if(Number.isFinite(absDiff)){
    first=`Deutschland lag im ${periodText} ${yearA} und ${yearB} beim absoluten Wert nahezu gleichauf.`;
  }else first=`Für Deutschland ist für ${periodText} kein vollständiger Direktvergleich verfügbar.`;
  const majority=positive.length===negative.length?`Genauso viele Bundesländer lagen ${metricPhrase} über wie unter Jahr B.`:positive.length>negative.length?`${positive.length} von ${rows.length} Bundesländern lagen ${metricPhrase} in Jahr A über Jahr B.`:`${negative.length} von ${rows.length} Bundesländern lagen ${metricPhrase} in Jahr A unter Jahr B.`;
  const positiveText=strongestPositive?`Die größte positive Differenz zeigt ${strongestPositive.name} mit ${regionalMapMetricText(strongestPositive.diff,param,mode,{difference:true})}.`:`Kein Bundesland weist eine positive Differenz A − B auf.`;
  const negativeText=strongestNegative?`Die stärkste negative Differenz zeigt ${strongestNegative.name} mit ${regionalMapMetricText(strongestNegative.diff,param,mode,{difference:true})}.`:`Kein Bundesland weist eine negative Differenz A − B auf.`;
  const extremes=`${positiveText} ${negativeText}`;
  const neutralText=neutral?` ${neutral} Bundesland${neutral===1?" liegt":" liegen"} praktisch gleichauf.`:"";
  set("regionalReportText",`${first} ${majority}${neutralText} ${extremes}`);
  set("regionalReportFoot",`Automatisch aus ${rows.length} Bundesländern berechnet. Die Top-5-Listen beziehen sich auf ${regionalMapMetricLabel(param,mode)}. Berlin sowie Hamburg/Bremen können auf kombinierten DWD-Gebietsmitteln beruhen; dadurch sind dort identische Werte mit Nachbar-/Kombinationsgebieten möglich.`);
}

function regionalMapScale(values,param,mode){
  const finite=values.filter(Number.isFinite);if(!finite.length)return {color:()=>"#e5e7eb",legend:[]};
  if(mode==="anomaly"){
    const abs=Math.max(...finite.map(v=>Math.abs(v)),param==="temp"?.5:1);
    const stops=[-abs,-abs*.66,-abs*.33,0,abs*.33,abs*.66,abs];
    const colors=param==="temp"?["#313695","#74add1","#d7eef5","#f7f7f7","#fdae61","#ef6548","#a50026"]:["#8c510a","#bf812d","#dfc27d","#f5f5f5","#80cdc1","#35978f","#01665e"];
    const color=v=>{if(!Number.isFinite(v))return "#e5e7eb";let i=0;while(i<stops.length-1&&v>=stops[i+1])i++;return colors[Math.min(i,colors.length-1)];};
    return {color,legend:stops.map((v,i)=>({value:v,color:colors[i]}))};
  }
  if(mode==="percent"){
    const stops=[0,50,75,90,100,110,125,150];const colors=["#8c510a","#bf812d","#dfc27d","#f6e8c3","#d1e5f0","#92c5de","#4393c3","#2166ac"];
    const color=v=>{if(!Number.isFinite(v))return "#e5e7eb";let i=0;while(i<stops.length-1&&v>=stops[i+1])i++;return colors[Math.min(i,colors.length-1)];};
    return {color,legend:stops.map((v,i)=>({value:v,color:colors[i]}))};
  }
  const min=Math.min(...finite),max=Math.max(...finite),range=max-min||1;const colors=REGIONAL_MAP_COLORS.low;
  const color=v=>{if(!Number.isFinite(v))return "#e5e7eb";const t=Math.max(0,Math.min(.999,(v-min)/range));return colors[Math.min(colors.length-1,Math.floor(t*colors.length))];};
  return {color,legend:colors.map((c,i)=>({value:min+range*i/(colors.length-1),color:c}))};
}
function regionalMapDifferenceScale(values,param){
  const finite=values.filter(Number.isFinite);
  if(!finite.length)return {color:()=>"#e5e7eb",legend:[]};
  const abs=Math.max(...finite.map(v=>Math.abs(v)),param==="temp"?.3:1);
  const stops=[-abs,-abs*.66,-abs*.33,0,abs*.33,abs*.66,abs];
  const colors=param==="temp"
    ?["#313695","#74add1","#d7eef5","#f7f7f7","#fdae61","#ef6548","#a50026"]
    :["#8c510a","#bf812d","#dfc27d","#f5f5f5","#80cdc1","#35978f","#01665e"];
  const color=v=>{if(!Number.isFinite(v))return "#e5e7eb";let i=0;while(i<stops.length-1&&v>=stops[i+1])i++;return colors[Math.min(i,colors.length-1)];};
  return {color,legend:stops.map((v,i)=>({value:v,color:colors[i]}))};
}
function renderRegionalMapLegend(scale,param,mode,elementId="regionalMapLegend",difference=false){
  const el=document.getElementById(elementId);if(!el)return;
  const items=scale.legend.map(item=>`<span class="regional-map-legend-item"><span class="regional-map-legend-swatch" style="background:${item.color}"></span>${regionalMapMetricText(item.value,param,mode,{difference})}</span>`);
  items.push('<span class="regional-map-legend-item"><span class="regional-map-legend-swatch" style="background:#e5e7eb"></span>keine Daten</span>');
  el.innerHTML=items.join("");
}
function regionalMapLoadGeoJson(){
  if(regionalMapGeoJson)return Promise.resolve(regionalMapGeoJson);
  if(regionalMapGeoPromise)return regionalMapGeoPromise;
  regionalMapGeoPromise=fetch(CURRENT_MAP_BOUNDARY_URL,{cache:"force-cache"}).then(r=>{if(!r.ok)throw new Error(`Bundesländergrenzen HTTP ${r.status}`);return r.json();}).then(data=>regionalMapGeoJson=data).finally(()=>regionalMapGeoPromise=null);
  return regionalMapGeoPromise;
}
function initRegionalMapById(containerId,mapName){
  const container=document.getElementById(containerId);if(!container||typeof L==="undefined")return null;
  let map=mapName==="A"?regionalMap:mapName==="B"?regionalMapB:regionalMapDiff;
  if(map)return map;
  container.innerHTML="";
  map=L.map(container,{zoomControl:mapName==="A",attributionControl:false,minZoom:5,maxZoom:9,scrollWheelZoom:false,boxZoom:false,doubleClickZoom:true}).setView([51.15,10.3],6);
  if(mapName==="A")regionalMap=map;
  else if(mapName==="B")regionalMapB=map;
  else regionalMapDiff=map;
  return map;
}
function regionalMapComparisonTooltip(name,area,recordA,recordB,param,mode,reference,yearA,yearB,periodText){
  const combined=area&&area!==name?`<div class="muted">DWD-Gebiet: ${area}</div>`:"";
  const metricA=regionalMapMetric(recordA,mode),metricB=regionalMapMetric(recordB,mode);
  const difference=Number.isFinite(metricA)&&Number.isFinite(metricB)?metricA-metricB:null;
  return `<div class="regional-map-tooltip"><strong>${name}</strong>${combined}<div>${periodText}</div><hr style="border:0;border-top:1px solid #e4e7e9;margin:6px 0"><div>${yearA}: <b>${regionalMapMetricText(metricA,param,mode)}</b></div><div>${yearB}: <b>${regionalMapMetricText(metricB,param,mode)}</b></div><div>A − B: <b>${regionalMapMetricText(difference,param,mode,{difference:true})}</b></div><div class="muted" style="margin-top:5px">Absolut: ${yearA} ${regionalMapMetricText(recordA.value,param,"absolute")} · ${yearB} ${regionalMapMetricText(recordB.value,param,"absolute")}</div><div class="muted">Referenz ${reference.label}: ${regionalMapMetricText(recordA.reference,param,"absolute")}</div></div>`;
}
function regionalDetailMonthValue(area,key,param){
  if(!area||!key)return null;
  const row=regionalMapRowsByDate(area).get(`${key.year}-${String(key.month).padStart(2,"0")}`);
  const value=row?.[param];
  return value===null||value===undefined||!Number.isFinite(Number(value))?null:Number(value);
}
function regionalDetailMonthReference(area,month,param,reference){
  if(!area||!Number.isFinite(month))return null;
  const byDate=regionalMapRowsByDate(area),values=[];
  for(let year=reference.start;year<=reference.end;year++){
    const row=byDate.get(`${year}-${String(month).padStart(2,"0")}`);
    const value=row?.[param];
    if(value!==null&&value!==undefined&&Number.isFinite(Number(value)))values.push(Number(value));
  }
  return values.length>=29?mean(values):null;
}
function regionalDetailSlotLabel(key,selection){
  if(!key)return "–";
  const month=MONTH_NAMES[key.month-1]||String(key.month);
  return selection==="winter"?`${month} ${key.year}`:month;
}
function regionalDetailPeriodDetail(record,param,reference){
  if(!record||!Number.isFinite(record.value))return "keine Daten";
  if(param==="temp")return `Abweichung zu ${reference.label}: ${regionalMapMetricText(record.anomaly,param,"anomaly")}`;
  const pct=Number.isFinite(record.percent)?`${record.percent.toFixed(0).replace(".",",")} % vom Mittel`:"ohne Referenz";
  return `${pct} · Abw. ${regionalMapMetricText(record.anomaly,param,"anomaly")}`;
}
function regionalDetailClearCharts(){
  if(regionalDetailChart){try{regionalDetailChart.destroy();}catch(_error){}regionalDetailChart=null;}
  if(regionalDetailDiffChart){try{regionalDetailDiffChart.destroy();}catch(_error){}regionalDetailDiffChart=null;}
}
function updateRegionalDetail(){
  const area=regionalDetailArea||"Deutschland";
  const displayName=regionalDetailDisplayName||area;
  const selectA=document.getElementById("regionalMapYearSelect"),selectB=document.getElementById("regionalMapYearBSelect");
  if(!monthlyData.length||!selectA||!selectB)return;
  const yearA=Number(selectA.value),yearB=Number(selectB.value);
  if(!Number.isFinite(yearA)||!Number.isFinite(yearB))return;
  const param=regionalMapParam(),selection=regionalMapSelection(),reference=monthlyReferencePeriod();
  const slots=regionalMapComparableSlots(yearA,yearB,selection,param);
  const periodText=regionalMapPeriodComparisonLabel(selection,slots,yearA);
  const recordA=regionalMapRecord(area,yearA,param,selection,reference,slots);
  const recordB=regionalMapRecord(area,yearB,param,selection,reference,slots);
  const diff=Number.isFinite(recordA.value)&&Number.isFinite(recordB.value)?recordA.value-recordB.value:null;
  const heading=document.getElementById("regionalDetailTitle");
  const subtitle=document.getElementById("regionalDetailSubtitle");
  const badge=document.getElementById("regionalDetailAreaBadge");
  if(heading)heading.textContent=`Detailvergleich · ${displayName}`;
  if(subtitle)subtitle.textContent=`${periodText} · ${PARAM_META[param].label} · ${yearA} gegen ${yearB}`;
  if(badge)badge.textContent=displayName;
  const setText=(id,text)=>{const el=document.getElementById(id);if(el)el.textContent=text;};
  setText("regionalDetailATitle",String(yearA));
  setText("regionalDetailBTitle",String(yearB));
  setText("regionalDetailReferenceTitle",`Referenz ${reference.label}`);
  setText("regionalDetailAValue",regionalMapMetricText(recordA.value,param,"absolute"));
  setText("regionalDetailBValue",regionalMapMetricText(recordB.value,param,"absolute"));
  setText("regionalDetailReferenceValue",regionalMapMetricText(recordA.reference,param,"absolute"));
  setText("regionalDetailADetail",regionalDetailPeriodDetail(recordA,param,reference));
  setText("regionalDetailBDetail",regionalDetailPeriodDetail(recordB,param,reference));
  setText("regionalDetailReferenceDetail",`${periodText} · 30-jähriges Mittel`);
  setText("regionalDetailDiffValue",regionalMapMetricText(diff,param,"absolute",{difference:true}));
  setText("regionalDetailDiffDetail",`${yearA} − ${yearB}`);

  const keysA=periodKeys(yearA,selection),keysB=periodKeys(yearB,selection);
  const monthRows=slots.map(index=>{
    const keyA=keysA[index],keyB=keysB[index];
    const valueA=regionalDetailMonthValue(area,keyA,param),valueB=regionalDetailMonthValue(area,keyB,param);
    const ref=regionalDetailMonthReference(area,keyA?.month,param,reference);
    return {index,keyA,keyB,label:regionalDetailSlotLabel(keyA,selection),valueA,valueB,reference:ref,diff:Number.isFinite(valueA)&&Number.isFinite(valueB)?valueA-valueB:null};
  });
  const finiteDiffs=monthRows.filter(row=>Number.isFinite(row.diff));
  const peak=finiteDiffs.length?[...finiteDiffs].sort((a,b)=>Math.abs(b.diff)-Math.abs(a.diff))[0]:null;
  setText("regionalDetailPeakValue",peak?regionalMapMetricText(peak.diff,param,"absolute",{difference:true}):"–");
  setText("regionalDetailPeakDetail",peak?peak.label:"keine gemeinsamen Monatswerte");
  setText("regionalDetailSeriesTitle",`${PARAM_META[param].label}: ${yearA}, ${yearB} und Referenz ${reference.label}`);
  setText("regionalDetailDiffTitle",`Monatliche Differenz ${yearA} − ${yearB}`);
  const sourceHint=area!==displayName?` Für ${displayName} wird das DWD-Gebietsmittel „${area}“ verwendet.`:"";
  setText("regionalDetailNote",`Die Referenzlinie zeigt für jeden dargestellten Monat das Mittel ${reference.label}. ${slots.length<periodKeys(yearA,selection).length?"Bei diesem laufenden Zeitraum werden nur die in beiden Jahren vorhandenen Monate dargestellt. ":""}${param==="rain"?"In den Kennzahlen wird zusätzlich der Anteil am Klimamittel ausgewiesen.":""}${sourceHint}`.trim());
  renderRegionalHistoricalContext(area,displayName,param,selection,slots,yearA,yearB,periodText);

  regionalDetailClearCharts();
  const canvas=document.getElementById("regionalDetailChart"),diffCanvas=document.getElementById("regionalDetailDiffChart");
  if(!canvas||!diffCanvas||!monthRows.length)return;
  const labels=monthRows.map(row=>row.label);
  const valuesA=monthRows.map(row=>row.valueA),valuesB=monthRows.map(row=>row.valueB),refs=monthRows.map(row=>row.reference),diffs=monthRows.map(row=>row.diff);
  const unit=param==="rain"?"l/m²":PARAM_META[param].unit;
  const tooltipValue=value=>Number.isFinite(value)?regionalMapMetricText(value,param,"absolute"):"–";
  regionalDetailChart=new Chart(canvas,{
    type:"line",
    data:{labels,datasets:[
      {label:String(yearA),data:valuesA,borderColor:"#c83b32",backgroundColor:"rgba(200,59,50,.10)",borderWidth:3,pointRadius:4,pointHoverRadius:6,tension:.18,spanGaps:false},
      {label:String(yearB),data:valuesB,borderColor:"#346b9b",backgroundColor:"rgba(52,107,155,.10)",borderWidth:3,pointRadius:4,pointHoverRadius:6,tension:.18,spanGaps:false},
      {label:`Mittel ${reference.label}`,data:refs,borderColor:"#30363a",backgroundColor:"transparent",borderWidth:2,borderDash:[7,5],pointRadius:2,pointHoverRadius:4,tension:.12,spanGaps:false}
    ]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{display:true},datalabels:{display:false},tooltip:{callbacks:{label:ctx=>`${ctx.dataset.label}: ${tooltipValue(ctx.parsed.y)}`}}},scales:{x:{grid:{display:false}},y:{beginAtZero:param!=="temp",title:{display:true,text:unit}}}}
  });
  regionalDetailDiffChart=new Chart(diffCanvas,{
    type:"bar",
    data:{labels,datasets:[{label:`${yearA} − ${yearB}`,data:diffs,backgroundColor:diffs.map(v=>!Number.isFinite(v)?"#d9dfe3":v>=0?"#c94b3c":"#3f75a2"),borderWidth:0,borderRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{display:false},datalabels:{display:ctx=>Number.isFinite(ctx.dataset.data[ctx.dataIndex]),anchor:"end",align:ctx=>(ctx.dataset.data[ctx.dataIndex]??0)>=0?"end":"start",formatter:v=>regionalMapMetricText(v,param,"absolute",{difference:true}),font:{size:10,weight:"bold"},clamp:true},tooltip:{callbacks:{label:ctx=>`A − B: ${regionalMapMetricText(ctx.parsed.y,param,"absolute",{difference:true})}`}}},scales:{x:{grid:{display:false}},y:{title:{display:true,text:`Differenz (${unit})`},grid:{color:ctx=>ctx.tick.value===0?"#7d878e":"rgba(0,0,0,.07)"}}}}
  });
}
function regionalMapSelectArea(area,displayName=area){
  if(!area)return;
  regionalDetailArea=area;
  regionalDetailDisplayName=displayName||area;
  updateRegionalDetail();
  const select=document.getElementById("monthlyAreaSelect");
  if(!select||![...select.options].some(o=>o.value===area))return;
  select.value=area;
  synchronizeArea("monthlyAreaSelect");
  updateMonthly();updateMonthlyAnomalyTable();updateClimateIndex();updateAccumulation();
}
function renderRegionalComparisonLayer({map,mapName,geo,byState,metricGetter,scale,labels,tooltipGetter}){
  if(!map)return null;
  let currentLayer=mapName==="A"?regionalMapLayer:mapName==="B"?regionalMapLayerB:regionalMapLayerDiff;
  if(currentLayer)map.removeLayer(currentLayer);
  let hoverTooltip=mapName==="A"?regionalMapHoverTooltip:mapName==="B"?regionalMapHoverTooltipB:regionalMapHoverTooltipDiff;
  if(hoverTooltip){map.removeLayer(hoverTooltip);hoverTooltip=null;}
  const group=L.geoJSON(geo,{
    style:feature=>{
      const name=feature?.properties?.name;
      const item=byState.get(name);
      const value=item?metricGetter(item):null;
      return {color:"#ffffff",weight:1.45,fillColor:scale.color(value),fillOpacity:Number.isFinite(value)?.9:.5};
    },
    onEachFeature:(feature,layer)=>{
      const name=feature?.properties?.name||"Bundesland";
      const item=byState.get(name);
      const value=item?metricGetter(item):null;
      if(labels&&Number.isFinite(value)){
        layer.bindTooltip(`${REGIONAL_MAP_STATE_SHORT[name]||""}<br>${regionalMapMetricText(value,item.param,item.mode,{difference:mapName==="D"})}`,{permanent:true,direction:"center",className:"regional-map-value-label",interactive:false});
      }
      layer.on({
        mouseover:e=>{
          e.target.setStyle({weight:2.5,color:"#263238",fillOpacity:1});
          let tip=mapName==="A"?regionalMapHoverTooltip:mapName==="B"?regionalMapHoverTooltipB:regionalMapHoverTooltipDiff;
          if(tip)map.removeLayer(tip);
          tip=L.tooltip({direction:"top",offset:[0,-7],opacity:.98,className:"regional-map-hover-tooltip"}).setLatLng(e.latlng).setContent(tooltipGetter(name,item)).addTo(map);
          if(mapName==="A")regionalMapHoverTooltip=tip;
          else if(mapName==="B")regionalMapHoverTooltipB=tip;
          else regionalMapHoverTooltipDiff=tip;
        },
        mousemove:e=>{
          const tip=mapName==="A"?regionalMapHoverTooltip:mapName==="B"?regionalMapHoverTooltipB:regionalMapHoverTooltipDiff;
          if(tip)tip.setLatLng(e.latlng);
        },
        mouseout:e=>{
          const itemNow=byState.get(name);
          const valueNow=itemNow?metricGetter(itemNow):null;
          e.target.setStyle({color:"#ffffff",weight:1.45,fillColor:scale.color(valueNow),fillOpacity:Number.isFinite(valueNow)?.9:.5});
          const tip=mapName==="A"?regionalMapHoverTooltip:mapName==="B"?regionalMapHoverTooltipB:regionalMapHoverTooltipDiff;
          if(tip)map.removeLayer(tip);
          if(mapName==="A")regionalMapHoverTooltip=null;
          else if(mapName==="B")regionalMapHoverTooltipB=null;
          else regionalMapHoverTooltipDiff=null;
        },
        click:()=>regionalMapSelectArea(item?.area,name)
      });
    }
  }).addTo(map);
  if(mapName==="A")regionalMapLayer=group;
  else if(mapName==="B")regionalMapLayerB=group;
  else regionalMapLayerDiff=group;
  map.fitBounds(group.getBounds(),{padding:[8,8],animate:false});
  window.setTimeout(()=>map.invalidateSize(),50);
  return group;
}
function swapRegionalMapYears(){
  const a=document.getElementById("regionalMapYearSelect"),b=document.getElementById("regionalMapYearBSelect");
  if(!a||!b)return;
  const value=a.value;a.value=b.value;b.value=value;
  updateRegionalMap();
}
function updateRegionalMap(){
  if(!document.getElementById("monthly")?.classList.contains("active")) return;
  if(!monthlyData.length)return;
  const selectA=document.getElementById("regionalMapYearSelect");
  const selectB=document.getElementById("regionalMapYearBSelect");
  if(!selectA||!selectB)return;
  if(!selectA.options.length||!selectB.options.length)populateRegionalMapYears({preserve:false});
  const yearA=Number(selectA.value),yearB=Number(selectB.value);
  if(!Number.isFinite(yearA)||!Number.isFinite(yearB))return;
  const param=regionalMapParam(),selection=regionalMapSelection(),reference=monthlyReferencePeriod(),mode=regionalMapMode();
  const modeSelect=document.getElementById("regionalMapModeSelect");
  if(modeSelect){[...modeSelect.options].forEach(o=>{o.disabled=param==="temp"&&o.value==="percent";});}
  const slots=regionalMapComparableSlots(yearA,yearB,selection,param);
  const periodText=regionalMapPeriodComparisonLabel(selection,slots,yearA);
  const states=["Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"];
  const byState=new Map();
  states.forEach(name=>{
    const area=regionalMapAreaForState(name);
    const recordA=regionalMapRecord(area,yearA,param,selection,reference,slots);
    const recordB=regionalMapRecord(area,yearB,param,selection,reference,slots);
    const metricA=regionalMapMetric(recordA,mode),metricB=regionalMapMetric(recordB,mode);
    byState.set(name,{area,recordA,recordB,metricA,metricB,diff:Number.isFinite(metricA)&&Number.isFinite(metricB)?metricA-metricB:null,param,mode});
  });
  const valuesAB=[...byState.values()].flatMap(item=>[item.metricA,item.metricB]).filter(Number.isFinite);
  const diffs=[...byState.values()].map(item=>item.diff).filter(Number.isFinite);
  const scaleAB=regionalMapScale(valuesAB,param,mode);
  const scaleDiff=regionalMapDifferenceScale(diffs,param);
  renderRegionalMapLegend(scaleAB,param,mode,"regionalMapLegend",false);
  renderRegionalMapLegend(scaleDiff,param,mode,"regionalMapDiffLegend",true);

  const germanyA=regionalMapRecord("Deutschland",yearA,param,selection,reference,slots);
  const germanyB=regionalMapRecord("Deutschland",yearB,param,selection,reference,slots);
  const germanyMetricA=regionalMapMetric(germanyA,mode),germanyMetricB=regionalMapMetric(germanyB,mode);
  const germanyDiff=Number.isFinite(germanyMetricA)&&Number.isFinite(germanyMetricB)?germanyMetricA-germanyMetricB:null;
  document.getElementById("regionalMapGermanyATitle").textContent=`Deutschland · ${yearA}`;
  document.getElementById("regionalMapGermanyBTitle").textContent=`Deutschland · ${yearB}`;
  document.getElementById("regionalMapGermany").textContent=regionalMapMetricText(germanyMetricA,param,mode);
  document.getElementById("regionalMapGermanyB").textContent=regionalMapMetricText(germanyMetricB,param,mode);
  document.getElementById("regionalMapGermanyDiff").textContent=regionalMapMetricText(germanyDiff,param,mode,{difference:true});
  document.getElementById("regionalMapGermanyDetail").textContent=periodText;
  document.getElementById("regionalMapGermanyBDetail").textContent=periodText;
  document.getElementById("regionalMapGermanyDiffDetail").textContent=`${yearA} − ${yearB}`;

  const ranked=[...byState.entries()].filter(([,item])=>Number.isFinite(item.diff)).map(([name,item])=>({name,value:item.diff})).sort((a,b)=>Math.abs(b.value)-Math.abs(a.value));
  const strongest=ranked[0];
  document.getElementById("regionalMapHigh").textContent=strongest?regionalMapMetricText(strongest.value,param,mode,{difference:true}):"–";
  document.getElementById("regionalMapHighDetail").textContent=strongest?.name||"–";
  renderRegionalRanking(byState,param,mode,yearA,yearB,periodText);
  renderRegionalComparisonReport(byState,param,mode,yearA,yearB,periodText,germanyA,germanyB,germanyMetricA,germanyMetricB,reference);
  updateRegionalDetail();

  document.getElementById("regionalMapTitleA").textContent=String(yearA);
  document.getElementById("regionalMapTitleB").textContent=String(yearB);
  document.getElementById("regionalMapTitleDiff").textContent=`${yearA} − ${yearB}`;
  document.getElementById("regionalMapSubtitleA").textContent=`${periodText} · ${regionalMapMetricLabel(param,mode)}`;
  document.getElementById("regionalMapSubtitleB").textContent=`${periodText} · ${regionalMapMetricLabel(param,mode)}`;
  document.getElementById("regionalMapSubtitleDiff").textContent=`Differenz · ${regionalMapMetricLabel(param,mode)}`;

  if(!slots.length){
    const clearLayer=(map,layer)=>{if(map&&layer)map.removeLayer(layer);};
    clearLayer(regionalMap,regionalMapLayer);regionalMapLayer=null;
    clearLayer(regionalMapB,regionalMapLayerB);regionalMapLayerB=null;
    clearLayer(regionalMapDiff,regionalMapLayerDiff);regionalMapLayerDiff=null;
    const note=document.getElementById("regionalMapNote");
    if(note)note.textContent=`Für ${yearA} und ${yearB} gibt es im gewählten Zeitraum keine gemeinsamen Monatsdaten. Bitte zwei andere Jahre oder einen anderen Zeitraum wählen.`;
    return;
  }

  regionalMapLoadGeoJson().then(geo=>{
    const mapA=initRegionalMapById("regionalMap","A");
    const mapB=initRegionalMapById("regionalMapB","B");
    const mapD=initRegionalMapById("regionalMapDiff","D");
    const labels=document.getElementById("regionalMapLabelsToggle")?.checked!==false;
    const tooltipGetter=(name,item)=>regionalMapComparisonTooltip(name,item?.area,item?.recordA||{},item?.recordB||{},param,mode,reference,yearA,yearB,periodText);
    renderRegionalComparisonLayer({map:mapA,mapName:"A",geo,byState,metricGetter:item=>item.metricA,scale:scaleAB,labels,tooltipGetter});
    renderRegionalComparisonLayer({map:mapB,mapName:"B",geo,byState,metricGetter:item=>item.metricB,scale:scaleAB,labels,tooltipGetter});
    renderRegionalComparisonLayer({map:mapD,mapName:"D",geo,byState,metricGetter:item=>item.diff,scale:scaleDiff,labels,tooltipGetter});
  }).catch(error=>{
    ["regionalMap","regionalMapB","regionalMapDiff"].forEach(id=>{
      const mapEl=document.getElementById(id);if(mapEl)mapEl.innerHTML=`<div class="regional-map-no-data">Deutschlandkarte konnte nicht geladen werden: ${error.message}</div>`;
    });
  });
  const partial=slots.length<periodKeys(yearA,selection).length;
  const note=document.getElementById("regionalMapNote");
  if(note)note.textContent=`${regionalMapMetricLabel(param,mode)} · ${periodText} · Referenz ${reference.label} · Vergleich ${yearA} gegen ${yearB}.${partial?" Laufender Zeitraum: Für beide Jahre werden nur die gemeinsam vorhandenen Teilmonate verwendet.":""} Jahr A und Jahr B besitzen dieselbe Farbskala; die Differenzkarte ist separat symmetrisch um 0 skaliert. Berlin nutzt Brandenburg/Berlin; Hamburg und Bremen Niedersachsen/Hamburg/Bremen. Klick auf ein Bundesland übernimmt das zugehörige DWD-Gebiet in die Diagramme.`;
}

function resetMonthlyZoom(){if(monthlyChart) monthlyChart.resetZoom();}

// ================= KLIMA-INDEX =================
function indexColor(value,alpha=.72){
  const clipped=Math.max(-3,Math.min(3,value));
  const strength=Math.abs(clipped)/3;
  const neutral=[238,235,226];
  const target=clipped>=0?[186,64,35]:[42,94,145];
  const rgb=neutral.map((component,index)=>Math.round(component+(target[index]-component)*strength));
  return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`;
}

const indexGuidesPlugin={
  id:"indexGuides",
  beforeDatasetsDraw(chart){
    if(chart.canvas.id!=="climateIndexChart" || !chart.$indexStats) return;
    const {ctx,chartArea:{left,right,top,bottom},scales:{x,y}}=chart;
    const x0=x.getPixelForValue(0);
    const y0=y.getPixelForValue(0);
    ctx.save();
    ctx.strokeStyle="rgba(70,70,70,.45)";
    ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(x0,top);ctx.lineTo(x0,bottom);ctx.stroke();
    ctx.beginPath();ctx.moveTo(left,y0);ctx.lineTo(right,y0);ctx.stroke();

    const rx=Math.abs(x.getPixelForValue(chart.$indexStats.tempSd)-x0);
    const ry=Math.abs(y.getPixelForValue(chart.$indexStats.rainSd)-y0);
    if(Number.isFinite(rx) && Number.isFinite(ry)){
      ctx.setLineDash([6,6]);
      ctx.strokeStyle="rgba(80,80,80,.48)";
      ctx.beginPath();
      ctx.ellipse(x0,y0,rx,ry,0,0,Math.PI*2);
      ctx.stroke();
    }
    ctx.restore();
  },
  afterDatasetsDraw(chart){
    if(chart.canvas.id!=="climateIndexChart") return;
    const {ctx,chartArea:{left,right,top,bottom}}=chart;
    const labels=[
      {text:"KALT & TROCKEN",x:left+12,y:top+12,align:"left",color:"#806f35"},
      {text:"WARM & TROCKEN",x:right-12,y:top+12,align:"right",color:"#b14c24"},
      {text:"KALT & NASS",x:left+12,y:bottom-12,align:"left",color:"#2f6a9b"},
      {text:"WARM & NASS",x:right-12,y:bottom-12,align:"right",color:"#43833b"}
    ];
    ctx.save();
    ctx.font="bold 15px Arial";
    ctx.textBaseline="middle";
    labels.forEach(label=>{
      const width=ctx.measureText(label.text).width;
      const boxLeft=label.align==="left"?label.x-5:label.x-width-5;
      ctx.fillStyle="rgba(255,255,255,.88)";
      ctx.strokeStyle=label.color;
      ctx.lineWidth=1;
      ctx.fillRect(boxLeft,label.y-12,width+10,24);
      ctx.strokeRect(boxLeft,label.y-12,width+10,24);
      ctx.fillStyle=label.color;
      ctx.textAlign=label.align;
      ctx.fillText(label.text,label.x,label.y);
    });
    ctx.restore();
  }
};
Chart.register(indexGuidesPlugin);

function updateClimateIndex(){
  if(!document.getElementById("indexPeriodSelect")?.closest(".tab-content")?.classList.contains("active")) return;
  if(!monthlyData.length) return;
  const area=document.getElementById("indexAreaSelect").value;
  const selection=document.getElementById("indexPeriodSelect").value;
  const tempSeries=seriesFor(area,selection,"temp");
  const rainSeries=seriesFor(area,selection,"rain");
  const tempByYear=new Map(tempSeries.map(item=>[item.year,item.value]));
  const rainByYear=new Map(rainSeries.map(item=>[item.year,item.value]));
  const years=[...tempByYear.keys()].filter(year=>rainByYear.has(year)).sort((a,b)=>a-b);

  const refYears=years.filter(year=>year>=1991 && year<=2020);
  const tempRef=refYears.map(year=>tempByYear.get(year));
  const rainRef=refYears.map(year=>rainByYear.get(year));
  const tempMean=mean(tempRef);
  const rainMean=mean(rainRef);
  const tempSd=stdDev(tempRef);
  const rainSd=stdDev(rainRef);
  if([tempMean,rainMean,tempSd,rainSd].some(value=>value===null || value===0)){
    document.getElementById("indexSummary").textContent="Für diesen Zeitraum liegen nicht genügend Referenzwerte 1991–2020 vor.";
    return;
  }

  const points=years.map(year=>{
    const temp=tempByYear.get(year);
    const rain=rainByYear.get(year);
    const tempAnom=temp-tempMean;
    const rainAnom=rain-rainMean;
    const tempZ=tempAnom/tempSd;
    const rainZ=rainAnom/rainSd;
    const combined=Math.sqrt(tempZ**2+rainZ**2);
    const warmDryIndex=tempZ-rainZ;
    return {
      x:tempAnom,
      y:rainAnom,
      r:Math.max(5,Math.min(18,5+combined*3.6)),
      year,temp,rain,tempAnom,rainAnom,tempZ,rainZ,combined,warmDryIndex
    };
  });
  const latestYear=Math.max(...points.map(point=>point.year));
  const current=points.filter(point=>point.year===latestYear);
  const history=points.filter(point=>point.year!==latestYear);
  const latest=current[0];

  const direction=`${latest.tempAnom>=0?"wärmer":"kälter"} und ${latest.rainAnom<0?"trockener":"nasser"}`;
  document.getElementById("indexSummary").innerHTML=
    `<strong>${area}, ${periodLabel(selection)} ${latest.year}:</strong> `+
    `${latest.tempAnom>=0?"+":""}${latest.tempAnom.toFixed(2).replace(".",",")} °C und `+
    `${latest.rainAnom>=0?"+":""}${latest.rainAnom.toFixed(1).replace(".",",")} mm gegenüber 1991–2020 – damit ${direction}.`;

  if(climateIndexChart) climateIndexChart.destroy();
  climateIndexChart=new Chart(document.getElementById("climateIndexChart"),{
    type:"bubble",
    data:{datasets:[
      {
        label:"Jahre",
        data:history,
        backgroundColor:history.map(point=>indexColor(point.warmDryIndex,.62)),
        borderColor:history.map(point=>indexColor(point.warmDryIndex,.9)),
        borderWidth:1
      },
      {
        label:`Aktuell (${latestYear})`,
        data:current,
        backgroundColor:current.map(point=>indexColor(point.warmDryIndex,.95)),
        borderColor:"#111",
        borderWidth:3
      }
    ]},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      layout:{padding:{top:10,right:10,bottom:5,left:5}},
      plugins:{
        title:{
          display:true,
          text:`${area}: ${periodLabel(selection)}-Index seit ${Math.min(...years)}`,
          font:{size:24}
        },
        subtitle:{
          display:true,
          text:"Temperatur- und Niederschlagsabweichungen gegenüber 1991–2020",
          font:{size:14}
        },
        legend:{display:false},
        datalabels:{
          display:context=>document.getElementById("indexLabelsToggle").checked || context.datasetIndex===1,
          formatter:value=>value.year,
          color:context=>context.datasetIndex===1?"#fff":"rgba(55,55,55,.70)",
          font:context=>({size:context.datasetIndex===1?14:9,weight:context.datasetIndex===1?"bold":"normal"}),
          anchor:"center",
          align:"center",
          clamp:true
        },
        tooltip:{callbacks:{
          title:items=>String(items[0].raw.year),
          label:context=>{
            const point=context.raw;
            return [
              `Temperatur: ${formatValue(point.temp,"temp")}`,
              `Abweichung: ${point.tempAnom>=0?"+":""}${point.tempAnom.toFixed(2)} °C`,
              `Niederschlag: ${formatValue(point.rain,"rain")}`,
              `Abweichung: ${point.rainAnom>=0?"+":""}${point.rainAnom.toFixed(1)} mm`,
              `Warm-Trocken-Index: ${point.warmDryIndex.toFixed(2)}`
            ];
          }
        }}
      },
      scales:{
        x:{
          title:{display:true,text:"Temperaturabweichung (°C)  ← kälter | wärmer →"},
          grid:{color:"rgba(120,120,120,.14)"}
        },
        y:{
          reverse:true,
          title:{display:true,text:"Niederschlagsabweichung (mm)  ↑ trockener | nasser ↓"},
          grid:{color:"rgba(120,120,120,.14)"}
        }
      }
    }
  });
  climateIndexChart.$indexStats={tempSd,rainSd};
  climateIndexChart.update();
}

// ================= SEIT JAHRESBEGINN =================
function populateAccumulationYears(){
  const select=document.getElementById("accYearSelect");
  const years=[...new Set(monthlyData.map(item=>Number(item.date.slice(0,4))))].sort((a,b)=>a-b);
  select.innerHTML="";
  years.forEach(year=>{
    const option=document.createElement("option");
    option.value=year;
    option.textContent=year;
    select.appendChild(option);
  });
  select.value=Math.max(...years);
}

function runningYear(area,year,param){
  const rows=areaRows(area);
  const byDate=new Map(rows.map(item=>[item.date,item]));
  const result=[];
  let cumulative=0;
  let weighted=0;
  let totalDays=0;
  let interrupted=false;

  for(let month=1;month<=12;month++){
    const entry=byDate.get(`${year}-${String(month).padStart(2,"0")}`);
    if(interrupted || !entry || entry[param]===null || entry[param]===undefined){
      result.push(null);
      interrupted=true;
      continue;
    }
    if(param==="temp"){
      const days=daysInMonth(year,month);
      weighted+=entry.temp*days;
      totalDays+=days;
      result.push(weighted/totalDays);
    }else{
      cumulative+=entry[param];
      result.push(cumulative);
    }
  }
  return result;
}

function updateAccumulation(){
  if(!document.getElementById("monthly")?.classList.contains("active")) return;
  if(!monthlyData.length) return;
  const area=document.getElementById("accAreaSelect").value;
  const param=document.getElementById("accParamSelect").value;
  const year=Number(document.getElementById("accYearSelect").value);
  const selected=runningYear(area,year,param);
  const allYears=[...new Set(areaRows(area).map(item=>Number(item.date.slice(0,4))))].sort((a,b)=>a-b);
  const baselineYears=allYears.filter(value=>value>=1991 && value<=2020);
  const baselineSeries=baselineYears.map(value=>runningYear(area,value,param));
  const historySeries=allYears.filter(value=>value!==year).map(value=>runningYear(area,value,param));

  const climate=Array.from({length:12},(_,month)=>{
    const values=baselineSeries.map(series=>series[month]).filter(Number.isFinite);
    return mean(values);
  });
  const minimum=Array.from({length:12},(_,month)=>{
    const values=historySeries.map(series=>series[month]).filter(Number.isFinite);
    return values.length?Math.min(...values):null;
  });
  const maximum=Array.from({length:12},(_,month)=>{
    const values=historySeries.map(series=>series[month]).filter(Number.isFinite);
    return values.length?Math.max(...values):null;
  });

  let lastIndex=-1;
  selected.forEach((value,index)=>{if(Number.isFinite(value)) lastIndex=index;});
  if(lastIndex>=0){
    const actual=selected[lastIndex];
    const normal=climate[lastIndex];
    const difference=actual-normal;
    let comparison="";
    if(param==="temp"){
      comparison=`${difference>=0?"+":""}${difference.toFixed(2).replace(".",",")} °C`;
    }else{
      const percent=normal!==0?actual/normal*100:null;
      comparison=`${difference>=0?"+":""}${difference.toFixed(1).replace(".",",")} ${PARAM_META[param].unit}`+
        (percent!==null?` (${percent.toFixed(0)} % des Mittels)`:"");
    }

    const peerValues=historySeries.map(series=>series[lastIndex]).filter(Number.isFinite);
    const rank=[...peerValues,actual].sort((a,b)=>b-a).indexOf(actual)+1;
    const rankText=param==="temp"?`${rank}. wärmster Wert`:`${rank}. höchster Wert`;
    document.getElementById("accSummary").innerHTML=
      `<strong>${area}, Januar–${MONTH_NAMES[lastIndex]} ${year}:</strong> `+
      `${formatValue(actual,param)}; Abweichung zu 1991–2020: ${comparison}. `+
      `${rankText} von ${peerValues.length+1} Jahren bis zu diesem Monatsende.`;
  }else{
    document.getElementById("accSummary").textContent="Für das ausgewählte Jahr liegen noch keine Werte vor.";
  }

  if(accumulationChart) accumulationChart.destroy();
  accumulationChart=new Chart(document.getElementById("accumulationChart"),{
    type:"line",
    data:{labels:MONTH_SHORT,datasets:[
      {
        label:"Historisches Minimum",
        data:minimum,
        borderColor:"rgba(90,110,135,.55)",
        borderWidth:1,
        pointRadius:0,
        tension:.15
      },
      {
        label:"Historischer Bereich",
        data:maximum,
        borderColor:"rgba(90,110,135,.55)",
        backgroundColor:"rgba(120,140,165,.14)",
        borderWidth:1,
        pointRadius:0,
        fill:"-1",
        tension:.15
      },
      {
        label:"Mittel 1991–2020",
        data:climate,
        borderColor:"#111",
        borderDash:[7,5],
        borderWidth:2.5,
        pointRadius:0,
        tension:.15
      },
      {
        label:String(year),
        data:selected,
        borderColor:"#d12d25",
        backgroundColor:"#d12d25",
        borderWidth:3,
        pointRadius:3,
        spanGaps:false,
        tension:.15
      }
    ]},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        title:{
          display:true,
          text:param==="temp"
            ?`${area}: laufendes Temperaturmittel ${year}`
            :`${area}: ${PARAM_META[param].label} seit Jahresbeginn ${year}`
        },
        datalabels:{display:false},
        tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${formatValue(context.parsed.y,param)}`}}
      },
      scales:{y:{title:{display:true,text:PARAM_META[param].unit}}}
    }
  });
}

// ================= STEUERUNG GEBIETSMITTEL =================
document.getElementById("monthlyAreaSelect").addEventListener("change",()=>{
  synchronizeArea("monthlyAreaSelect"); updateMonthly(); updateMonthlyAnomalyTable(); updateClimateIndex(); updateAccumulation();
});
document.getElementById("indexAreaSelect").addEventListener("change",()=>{
  synchronizeArea("indexAreaSelect"); updateMonthly(); updateMonthlyAnomalyTable(); updateClimateIndex(); updateAccumulation();
});
document.getElementById("accAreaSelect").addEventListener("change",()=>{
  synchronizeArea("accAreaSelect"); updateMonthly(); updateMonthlyAnomalyTable(); updateClimateIndex(); updateAccumulation();
});
document.getElementById("paramSelect").addEventListener("change",()=>{updateMonthly();updateMonthlyAnomalyTable();populateRegionalMapYears();updateRegionalMap();});
document.getElementById("monthSelect").addEventListener("change",()=>{updateMonthly();populateRegionalMapYears();updateRegionalMap();});
document.getElementById("monthlyReferenceSelect").addEventListener("change",()=>{updateMonthlyReferenceUi();updateMonthly();updateMonthlyAnomalyTable();updateRegionalMap();});
document.getElementById("monthlyReferenceStart").addEventListener("change",()=>{updateMonthlyReferenceUi();updateMonthly();updateMonthlyAnomalyTable();updateRegionalMap();});
document.getElementById("monthlyRollingSelect").addEventListener("change",()=>{updateMonthlyRollingUi();updateMonthly();});
document.getElementById("monthlyRollingYears").addEventListener("change",()=>{updateMonthlyRollingUi();updateMonthly();});
document.getElementById("regionalMapYearSelect").addEventListener("change",updateRegionalMap);
document.getElementById("regionalMapYearBSelect").addEventListener("change",updateRegionalMap);
document.getElementById("regionalMapSwapYears").addEventListener("click",swapRegionalMapYears);
document.getElementById("regionalMapModeSelect").addEventListener("change",updateRegionalMap);
document.getElementById("regionalMapLabelsToggle").addEventListener("change",updateRegionalMap);
document.getElementById("regionalRankingSort").addEventListener("change",updateRegionalMap);
document.getElementById("regionalReportCopy").addEventListener("click",copyRegionalReport);
document.getElementById("regionalMapDownloadA").addEventListener("click",()=>downloadRegionalMapPanel("A"));
document.getElementById("regionalMapDownloadB").addEventListener("click",()=>downloadRegionalMapPanel("B"));
document.getElementById("regionalMapDownloadDiff").addEventListener("click",()=>downloadRegionalMapPanel("D"));
document.getElementById("indexPeriodSelect").addEventListener("change",updateClimateIndex);
document.getElementById("indexLabelsToggle").addEventListener("change",updateClimateIndex);
document.getElementById("accParamSelect").addEventListener("change",updateAccumulation);
document.getElementById("accYearSelect").addEventListener("change",updateAccumulation);

