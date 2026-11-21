/* schnee.js – Schneehöhe (DWD_SNOW_HEIGHT_FRONTEND_V1)
   Aus index.html ausgelagert (Schritt 2b). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= DWD_SNOW_HEIGHT_FRONTEND_V1 =================
function stationSnowFormat(value,decimals=1){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return "–";
  return Number(value).toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}

function stationSnowGermanDate(iso){
  if(!iso) return "–";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
}

function stationSnowMonthDayLabel(monthDay){
  if(!monthDay || !monthDay.includes("-")) return monthDay||"";
  const [month,day]=monthDay.split("-");
  return `${day}.${month}.`;
}

function stationSnowReferenceStatusLabel(status){
  const labels={
    complete:"vollständig",
    good:"sehr gut",
    usable:"brauchbar",
    limited:"eingeschränkt",
    insufficient:"unzureichend"
  };
  return labels[status]||status||"–";
}

async function ensureStationSnowLoaded(){
  if(stationSnowIndex && stationSnowCurrentIndex){
    await updateStationSnow();
    return stationSnowIndex;
  }
  if(stationSnowLoading) return stationSnowLoading;

  const loading=document.getElementById("stationSnowLoading");
  loading.hidden=false;
  loading.style.color="";
  loading.textContent="Schneehöhen werden geladen …";

  stationSnowLoading=Promise.all([
    dashboardFetch("station_snow_height_index.json",{cache:"no-store"}).then(response=>{
      if(!response.ok) throw new Error(`Historischer Schneehöhenindex: HTTP ${response.status}`);
      return response.json();
    }),
    dashboardFetch("station_snow_height_current_index.json",{cache:"no-store"}).then(response=>{
      if(!response.ok) throw new Error(`Aktueller Schneehöhenindex: HTTP ${response.status}`);
      return response.json();
    }),
    dashboardFetch("station_snow_height_additional_index.json",{cache:"no-store"})
      .then(response=>response.ok?response.json():null)
      .catch(error=>{console.warn("Erweiterte Schneestationen noch nicht verfügbar:",error);return null;})
  ]).then(([historyIndex,currentIndex,additionalIndex])=>{
    if(!historyIndex.ready) throw new Error("Die historischen Schneehöhenprofile sind noch nicht bereit.");
    if(!currentIndex.ready) throw new Error("Die aktuelle Schneehöhensaison ist noch nicht bereit.");

    // Original KL stations win on overlapping DWD station IDs.
    // The extended RR/KL catalogue contains only stations with measured snow
    // depths, and is optional while its independent data workflow catches up.
    const baseIds=new Set((historyIndex.stations||[]).map(s=>s.id));
    const extraStations=additionalIndex?.ready===true
      ?(additionalIndex.stations||[]).filter(s=>!baseIds.has(s.id)): [];
    const merged=[...(historyIndex.stations||[]),...extraStations].sort(
      (a,b)=>(a.state||"").localeCompare(b.state||"","de")||
        (a.name||"").localeCompare(b.name||"","de"));
    stationSnowIndex={...historyIndex,stations:merged,station_count:merged.length};
    const currentExtra=extraStations.map(s=>({
      id:s.id,current_available:!!s.current_available,
      file:s.current_file||null,last_observation:s.last_observation||null,
      last_value_cm:s.last_value_cm??null,max_cm:s.current_max_cm??null
    }));
    stationSnowCurrentIndex={...currentIndex,stations:[
      ...(currentIndex.stations||[]),...currentExtra]};
    stationSnowCurrentById=new Map(stationSnowCurrentIndex.stations.map(s=>[String(s.id),s]));
    stationSnowStationById=new Map(merged.map(s=>[String(s.id),s]));
    initializeStationSnowControls();

    loading.hidden=true;
    document.getElementById("stationSnowContent").hidden=false;

    document.getElementById("stationSnowSourceNote").textContent=
      `Quelle: DWD CDC tägliche KL (SHK_TAG) und ergänzend RR (SH_TAG). `+
      `${stationSnowIndex.station_count} Stationen mit nachgewiesenen Tageswerten, davon `+
      `${stationSnowIndex.stations.filter(s=>stationSnowQualifiesForLongSeries(s)).length} mit mindestens 30 vollständigen Jahren. `+
      `Aktuelle Saison ${currentIndex.hydrological_year}: ${currentIndex.data_through?stationSnowGermanDate(currentIndex.data_through):"–"}. `+
      `Unvollständige Messreihen bleiben auswählbar; fehlende Werte sind keine 0 cm.`;

    return updateStationSnow().then(()=>historyIndex);
  }).catch(error=>{
    stationSnowLoading=null;
    loading.textContent=`Schneehöhen konnten nicht geladen werden: ${error.message}`;
    loading.style.color="#7a1010";
    throw error;
  });

  return stationSnowLoading;
}

function initializeStationSnowControls(){
  const stateSelect=document.getElementById("stationSnowStateSelect");
  const states=[...new Set((stationSnowIndex.stations||[]).map(station=>station.state).filter(Boolean))]
    .sort((a,b)=>a.localeCompare(b,"de"));

  stateSelect.innerHTML='<option value="Deutschland">Deutschland – alle Stationen</option>';
  states.forEach(state=>{
    const option=document.createElement("option");
    option.value=state;
    option.textContent=state;
    stateSelect.appendChild(option);
  });
  const savedState=dashboardState.stationSnowStateSelect;
  stateSelect.value=states.includes(savedState)?savedState:"Deutschland";

  function onFilterChange(){
    const before=document.getElementById("stationSnowStationSelect").value;
    populateStationSnowStations();
    if(document.getElementById("stationSnowStationSelect").value!==before)
      document.getElementById("stationSnowStationSelect")
        .dispatchEvent(new Event("change",{bubbles:true}));
  }
  stateSelect.addEventListener("change",onFilterChange);

  // Typing only recomputes an in-memory shortlist; NEVER fetch snow charts
  // until a station is explicitly picked. Search input is debounced.
  document.getElementById("stationSnowSearch").addEventListener("input",()=>{
    if(window.StationSnowExplorer)window.StationSnowExplorer.onSearchInput();
    else populateStationSnowStations();
  });
  for(const controlId of ["stationSnowLongSeriesOnly",
                          "stationSnowAvailabilitySelect",
                          "stationSnowElevationSelect"]){
    document.getElementById(controlId).addEventListener("change",onFilterChange);
  }
  window.StationSnowExplorer?.init({
    onSearchChanged:()=>populateStationSnowStations(),
    onSelect:id=>{
      if(!stationSnowStationById.has(String(id)))return;
      const select=document.getElementById("stationSnowStationSelect");
      if(![...select.options].some(option=>option.value===String(id))){
        const station=stationSnowStationById.get(String(id));
        const option=document.createElement("option");
        option.value=String(id);
        option.textContent=station.name+" ("+id+") · ausgewählt";
        select.appendChild(option);
      }
      if(select.value!==String(id)){
        select.value=String(id);
        window.StationSnowExplorer?.hideSuggestions();
        // Dispatch the same native event as a manual select: existing dashboard
        // persistence must remember map/suggestion selections, too.
        select.dispatchEvent(new Event("change",{bubbles:true}));
      }else window.StationSnowExplorer?.hideSuggestions();
      select.focus({preventScroll:true});
    }
  });

  document.getElementById("stationSnowStationSelect").addEventListener("change",()=>{
    window.StationSnowExplorer?.update(
      filteredStationSnowStations(),
      document.getElementById("stationSnowStationSelect").value,
      stationSnowIndex.stations,stationSnowCurrentById);
    updateStationSnow();
  });
  document.getElementById("stationSnowPeriodSelect").addEventListener("change",updateStationSnow);
  document.getElementById("stationSnowYearsList").addEventListener("change",event=>{
    const control=event.target;
    if(!control.matches('input[type="checkbox"][data-snow-year]'))return;
    const year=Number(control.dataset.snowYear);
    if(control.checked)stationSnowSelectedYears.add(year);
    else stationSnowSelectedYears.delete(year);
    updateStationSnow();
  });
  document.getElementById("stationSnowSelectAllYears").addEventListener("click",()=>{
    stationSnowAvailableYears.forEach(item=>stationSnowSelectedYears.add(item.year));
    updateStationSnow();
  });
  document.getElementById("stationSnowResetYears").addEventListener("click",()=>{
    stationSnowSelectedYears.clear();
    const mostRecent=stationSnowAvailableYears.find(item=>item.isCurrent)||stationSnowAvailableYears[0];
    if(mostRecent)stationSnowSelectedYears.add(mostRecent.year);
    updateStationSnow();
  });

  populateStationSnowStations(true);
}

function stationSnowQualifiesForLongSeries(station){
  // Keep the old scientific criterion: >=30 separate hydrological years,
  // each having >=98% real daily SHK_TAG or SH_TAG observations.
  return Number(station.accepted_history_years||0)>=30;
}
function filteredStationSnowStations(){
  const state=document.getElementById("stationSnowStateSelect").value;
  const query=document.getElementById("stationSnowSearch").value.trim();
  const search=globalThis.StationSnowExplorer?.normalize(query)||
    query.toLocaleLowerCase("de-DE");
  const longOnly=Boolean(document.getElementById("stationSnowLongSeriesOnly")?.checked);
  const availability=document.getElementById("stationSnowAvailabilitySelect")?.value||"all";
  const elevation=document.getElementById("stationSnowElevationSelect")?.value||"all";
  return (stationSnowIndex.stations||[]).filter(station=>{
    if(state!=="Deutschland" && station.state!==state)return false;
    if(longOnly && !stationSnowQualifiesForLongSeries(station))return false;
    if(availability!=="all"){
      const current=stationSnowCurrentMeta(station.id)?.current_available===true;
      if(availability==="current" && !current)return false;
      if(availability==="historical" && current)return false;
    }
    if(elevation!=="all"){
      const altitude=station.height===null||station.height===undefined?
        NaN:Number(station.height);
      if(!Number.isFinite(altitude))return false;
      if(elevation==="0-200" && altitude>=200)return false;
      if(elevation==="200-500" && (altitude<200||altitude>=500))return false;
      if(elevation==="500-1000" && (altitude<500||altitude>=1000))return false;
      if(elevation==="1000+" && altitude<1000)return false;
    }
    if(!search)return true;
    const label=globalThis.StationSnowExplorer?.normalize(station.name+" "+station.id)||
      (station.name+" "+station.id).toLocaleLowerCase("de-DE");
    return label.includes(search);
  });
}

function populateStationSnowStations(firstLoad=false){
  const select=document.getElementById("stationSnowStationSelect");
  const previous=select.value;
  const stations=filteredStationSnowStations();
  const all=stationSnowIndex?.stations||[];
  const qualified=all.filter(stationSnowQualifiesForLongSeries).length;
  const status=document.getElementById("stationSnowFilterStatus");
  if(status)status.textContent=`${stations.length.toLocaleString("de-DE")} Stationen im Filter · ${all.length.toLocaleString("de-DE")} insgesamt · ${qualified.toLocaleString("de-DE")} mit ≥30 vollständigen Messjahren. Nur die gewählte Station lädt Tageswerte.`;

  // A native 5,000-option select is slow and almost unusable on phones.
  // Keep <=45 matched choices and pin any already selected station.
  const savedStation=dashboardState.stationSnowStationSelect;
  const chosen=firstLoad && stations.some(s=>s.id===savedStation)?savedStation:
    firstLoad && stations.some(s=>s.id==="05792")?"05792":previous;
  const top=stations.slice(0,45);
  if(chosen && !top.some(s=>s.id===chosen)){
    const pin=stationSnowStationById.get(String(chosen));
    // During text entry the old selection must stay in place: do not fetch
    // another profile or change the currently displayed chart.
    if(pin && document.getElementById("stationSnowSearch").value.trim())top.unshift(pin);
    else if(pin && stations.some(s=>s.id===chosen))top.unshift(pin);
  }
  select.replaceChildren();
  for(const station of top){
    const option=document.createElement("option");
    option.value=station.id;
    const currentMeta=stationSnowCurrentMeta(station.id);
    const years=Number(station.accepted_history_years||0);
    option.textContent=`${station.name} (${station.id}) · ${years} vollständige Jahre · ${station.source?.includes("RR")?"RR":"KL"}${currentMeta && !currentMeta.current_available?" · keine Saisonwerte":""}`;
    select.appendChild(option);
  }
  if(chosen && top.some(s=>s.id===chosen))select.value=chosen;
  else if(top.length)select.value=top[0].id;
  window.StationSnowExplorer?.update(stations,select.value,
    stationSnowIndex.stations,stationSnowCurrentById);
}

function stationSnowPopulateYearPicker(station,archive,current,currentYear){
  const available=window.StationSnowYears?.yearList(archive,currentYear,Boolean(current?.rows?.length))||[];
  const list=document.getElementById("stationSnowYearsList");
  const status=document.getElementById("stationSnowYearsStatus");
  // Preserve checked years when changing stations. Only discard years without
  // an archive entry at the new station; keep the current-year selection too.
  // This applies to both snow-depth and anomaly/accumulation charts.
  const stationChanged=stationSnowYearStationId!==station.id;
  stationSnowYearStationId=station.id;
  stationSnowAvailableYears=available;
  const yearsAtStation=new Set(available.map(item=>item.year));
  for(const selected of [...stationSnowSelectedYears]){
    if(!yearsAtStation.has(selected))stationSnowSelectedYears.delete(selected);
  }
  // First load, or no overlapping years between stations: show an available
  // season rather than an empty chart. Manually deselecting every year at
  // the same station must remain possible.
  if(!stationSnowSelectedYears.size && stationChanged){
    const recent=available.find(item=>item.isCurrent)||available[0];
    if(recent)stationSnowSelectedYears.add(recent.year);
  }
  list.replaceChildren();
  const fragment=document.createDocumentFragment();
  for(const entry of available){
    const label=document.createElement("label");
    label.className="station-snow-year-choice";
    const checkbox=document.createElement("input");
    checkbox.type="checkbox";
    checkbox.dataset.snowYear=String(entry.year);
    checkbox.checked=stationSnowSelectedYears.has(entry.year);
    const title=document.createElement("span");
    title.textContent=String(entry.year);
    const detail=document.createElement("small");
    detail.textContent=entry.isCurrent?" · aktuell":entry.accepted?" · vollständig":" · Teilreihe";
    label.append(checkbox,title,detail);
    fragment.appendChild(label);
  }
  list.appendChild(fragment);
  status.textContent=!archive?.years?.length
    ?"Historische Tageskurven werden noch aus den DWD-Messwerten aufgebaut; die laufende Saison bleibt verfügbar."
    :available.length+" beobachtete hydrologische Jahre verfügbar. Fehlende Tage bleiben Datenlücken; Teilreihen sind gekennzeichnet.";
}

function stationSnowDailyObjects(profile){
  const columns=profile.daily_columns||[];
  const indexes=Object.fromEntries(columns.map((name,index)=>[name,index]));

  return (profile.daily||[]).map(row=>({
    monthDay:row[indexes.month_day],
    nReference:row[indexes.n_reference],
    median:row[indexes.median_cm],
    p16:row[indexes.p16_cm],
    p84:row[indexes.p84_cm],
    p2_5:row[indexes.p2_5_cm],
    p97_5:row[indexes.p97_5_cm],
    historicalMax:row[indexes.historical_max_cm]
  }));
}

function stationSnowCurrentObjects(current){
  if(!current) return new Map();
  const columns=current.columns||[];
  const indexes=Object.fromEntries(columns.map((name,index)=>[name,index]));
  const result=new Map();

  (current.rows||[]).forEach(row=>{
    const iso=row[indexes.date];
    if(!iso) return;
    result.set(String(iso).slice(5),{
      date:iso,
      snow:row[indexes.snow_cm],
      median:row[indexes.reference_median_cm],
      anomaly:row[indexes.anomaly_cm]
    });
  });

  return result;
}

function stationSnowVisibleDaily(profile){
  const period=document.getElementById("stationSnowPeriodSelect")?.value||"snow";
  const rows=stationSnowDailyObjects(profile);
  if(period==="hydro") return rows;

  const end=rows.findIndex(row=>row.monthDay==="05-31");
  return end>=0?rows.slice(0,end+1):rows;
}

function stationSnowBandDataset(label,data,backgroundColor,borderColor,helper=false){
  return {
    label,
    data,
    borderColor,
    backgroundColor,
    borderWidth:helper?0:0.7,
    pointRadius:0,
    tension:.08,
    fill:helper?false:"-1",
    _snowBandHelper:helper
  };
}

function stationSnowCurrentMeta(stationId){
  return stationSnowCurrentById.get(String(stationId))||null;
}

async function loadStationSnowFiles(stationId){
  if(stationSnowFileCache.has(stationId))return stationSnowFileCache.get(stationId);
  const request=(async()=>{
    const station=stationSnowStationById.get(String(stationId));
    if(!station)throw new Error("Station nicht gefunden.");
    const currentMeta=stationSnowCurrentMeta(stationId);
    const profilePromise=dashboardFetch(station.file||("station_snow_height_profiles/"+stationId+".json"),{cache:"no-store"})
      .then(response=>{
        if(!response.ok)throw new Error("Historisches Profil HTTP "+response.status);
        return response.json();
      });
    const currentPromise=currentMeta?.current_available && currentMeta.file
      ?dashboardFetch(currentMeta.file,{cache:"no-store"}).then(response=>{
        if(!response.ok)throw new Error("Aktuelle Saison HTTP "+response.status);
        return response.json();
      }):Promise.resolve(null);
    const yearPath=station.year_file||("station_snow_height_years/"+stationId+".json");
    const archivePromise=dashboardFetch(yearPath,{cache:"no-store"})
      .then(response=>response.ok?response.json():null)
      .then(payload=>payload?.version===1 && String(payload.station_id)===String(stationId)?payload:null)
      .catch(error=>{console.warn("Historisches Schneehöhen-Jahresarchiv fehlt noch",error);return null;});
    const [profile,current,archive]=await Promise.all([profilePromise,currentPromise,archivePromise]);
    return {station,profile,current,archive,currentMeta};
  })().catch(error=>{stationSnowFileCache.delete(stationId);throw error;});
  stationSnowFileCache.set(stationId,request);
  // Keep only a few loaded stations in RAM, not thousands of archives.
  while(stationSnowFileCache.size>8){
    stationSnowFileCache.delete(stationSnowFileCache.keys().next().value);
  }
  return request;
}

async function updateStationSnow(){
  if(!stationSnowIndex || !stationSnowCurrentIndex) return;

  const stationId=document.getElementById("stationSnowStationSelect")?.value;
  if(!stationId){
    ++stationSnowRequestId;
    document.getElementById("stationSnowSummary").textContent="Keine Station für den gewählten Filter gefunden.";
    if(stationSnowChart){stationSnowChart.destroy();stationSnowChart=null;}
    if(stationSnowDeviationChart){stationSnowDeviationChart.destroy();stationSnowDeviationChart=null;}
    document.getElementById("stationSnowYearsList").replaceChildren();
    document.getElementById("stationSnowYearsStatus").textContent="Keine Messreihe ausgewählt.";
    window.StationSnowAccumulation?.render({
      station:{name:"Keine Station"},archive:null,current:null,
      currentYear:stationSnowCurrentIndex.hydrological_year,selectedYears:new Set()
    });
    return;
  }

  const requestId=++stationSnowRequestId;
  document.getElementById("stationSnowSummary").textContent="Schneehöhenprofil wird geladen …";

  try{
    const {station,profile,current,archive,currentMeta}=await loadStationSnowFiles(stationId);
    if(requestId!==stationSnowRequestId) return;

    stationSnowProfile=profile;
    stationSnowCurrent=current;
    stationSnowYearsArchive=archive;

    const daily=stationSnowVisibleDaily(profile);
    const currentByMonthDay=stationSnowCurrentObjects(current);

    const labels=daily.map(row=>stationSnowMonthDayLabel(row.monthDay));
    const medianValues=daily.map(row=>row.median??null);
    const p16=daily.map(row=>row.p16??null);
    const p84=daily.map(row=>row.p84??null);
    const p2_5=daily.map(row=>row.p2_5??null);
    const p97_5=daily.map(row=>row.p97_5??null);
    const historicalMax=daily.map(row=>row.historicalMax??null);

    const hydroYear=stationSnowCurrentIndex.hydrological_year;
    stationSnowPopulateYearPicker(station,archive,current,hydroYear);
    const yearCurves=window.StationSnowYears?.curves({
      archive,selectedYears:stationSnowSelectedYears,
      monthDays:daily.map(row=>row.monthDay),
      currentYear:hydroYear,currentByMonthDay,median:medianValues
    })||[];
    const height=station.height===null||station.height===undefined?"":` · ${station.height} m`;
    const periodLabel=document.getElementById("stationSnowPeriodSelect").value==="hydro"
      ?"01.11.–31.10."
      :"01.11.–31.05.";

    if(stationSnowChart) stationSnowChart.destroy();
    stationSnowChart=new Chart(document.getElementById("stationSnowChart"),{
      type:"line",
      data:{
        labels,
        datasets:[
          stationSnowBandDataset("",p2_5,"rgba(160,166,171,0)","rgba(160,166,171,0)",true),
          stationSnowBandDataset("2,5–97,5 %",p97_5,"rgba(154,160,166,.22)","rgba(135,142,148,.32)"),
          stationSnowBandDataset("",p16,"rgba(100,108,115,0)","rgba(100,108,115,0)",true),
          stationSnowBandDataset("16–84 %",p84,"rgba(105,112,119,.30)","rgba(95,102,108,.38)"),
          {
            label:"Median 1991–2020",
            data:medianValues,
            borderColor:"#343a40",
            backgroundColor:"#343a40",
            borderWidth:2.2,
            pointRadius:0,
            fill:false,
            tension:.08
          },
          {
            label:"Historisches Maximum",
            data:historicalMax,
            borderColor:"rgba(80,86,91,.70)",
            borderWidth:1.5,
            borderDash:[7,5],
            pointRadius:0,
            fill:false,
            tension:.05
          },
          ...yearCurves.map(curve=>({
            label:curve.label,
            data:curve.values,
            borderColor:curve.color,
            backgroundColor:curve.color,
            borderWidth:curve.current?3:1.5,
            pointRadius:0,
            pointHoverRadius:4,
            fill:false,
            spanGaps:false,
            tension:.06
          }))
        ]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        interaction:{mode:"index",intersect:false},
        plugins:{
          title:{
            display:true,
            text:`Schneehöhe ${station.name} (${station.id})${height} · ${periodLabel}`
          },
          legend:{labels:{filter:item=>Boolean(item.text)}},
          datalabels:{display:false},
          tooltip:{
            callbacks:{
              label:context=>{
                if(context.parsed.y===null || context.parsed.y===undefined) return null;
                return `${context.dataset.label}: ${stationSnowFormat(context.parsed.y)} cm`;
              }
            }
          },
          zoom:{
            pan:{enabled:true,mode:"x"},
            zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}
          }
        },
        scales:{
          x:{ticks:{maxTicksLimit:12,maxRotation:0}},
          y:{beginAtZero:true,title:{display:true,text:"Schneehöhe (cm)"}}
        }
      }
    });

    if(stationSnowDeviationChart) stationSnowDeviationChart.destroy();
    stationSnowDeviationChart=new Chart(document.getElementById("stationSnowDeviationChart"),{
      type:"line",
      data:{
        labels,
        datasets:yearCurves.map(curve=>({
          label:"Abweichung "+curve.label+" zum Median 1991–2020",
          data:curve.deviations,
          borderColor:curve.color,
          backgroundColor:curve.current?"rgba(217,52,43,.12)":curve.color,
          borderWidth:curve.current?2.4:1.5,
          pointRadius:0,
          fill:curve.current?"origin":false,
          spanGaps:false,
          tension:.05
        }))
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        interaction:{mode:"index",intersect:false},
        plugins:{
          title:{
            display:true,
            text:`Abweichung der Schneehöhe vom Median 1991–2020 · ${station.name}`
          },
          datalabels:{display:false},
          tooltip:{
            callbacks:{
              label:context=>{
                if(context.parsed.y===null || context.parsed.y===undefined) return null;
                const value=context.parsed.y;
                return `Abweichung: ${value>=0?"+":""}${stationSnowFormat(value)} cm`;
              }
            }
          },
          zoom:{
            pan:{enabled:true,mode:"x"},
            zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}
          }
        },
        scales:{
          x:{ticks:{maxTicksLimit:12,maxRotation:0}},
          y:{title:{display:true,text:"Abweichung (cm)"}}
        }
      }
    });

    window.StationSnowAccumulation?.render({
      station,profile,archive,current,currentYear:hydroYear,
      selectedYears:stationSnowSelectedYears
    });

    const quality=profile.quality||{};
    const summary=current?.summary||null;
    const refYears=Number(quality.reference_years_available||0);
    const historyYears=Number(quality.accepted_history_years||0);
    const referenceStatus=stationSnowReferenceStatusLabel(quality.reference_status);

    document.getElementById("stationSnowReferenceStat").textContent=`${refYears}/30 Jahre`;
    document.getElementById("stationSnowReferenceDetail").textContent=
      `${referenceStatus} · nur hydrologische Jahre mit ≥ 98 % Tagesabdeckung`;

    document.getElementById("stationSnowHistoryStat").textContent=`${historyYears} Jahre`;
    document.getElementById("stationSnowHistoryDetail").textContent=
      `${Number(quality.observed_history_years||historyYears)} Jahre mit Tageswerten, ${historyYears} davon ≥98 % vollständig`+
      (quality.history_start_year&&quality.history_end_year
        ?` · ${quality.history_start_year}–${quality.history_end_year}`:"");

    if(summary){
      document.getElementById("stationSnowLatestStat").textContent=
        `${stationSnowFormat(summary.last_value_cm)} cm`;
      document.getElementById("stationSnowLatestDetail").textContent=
        `am ${stationSnowGermanDate(summary.last_observation)} · Abweichung zum Median `+
        `${summary.last_anomaly_cm===null||summary.last_anomaly_cm===undefined?"–":`${Number(summary.last_anomaly_cm)>=0?"+":""}${stationSnowFormat(summary.last_anomaly_cm)} cm`}`;

      document.getElementById("stationSnowMaxStat").textContent=
        `${stationSnowFormat(summary.max_cm)} cm`;
      document.getElementById("stationSnowMaxDetail").textContent=
        summary.max_dates?.length
          ?`am ${summary.max_dates.slice(0,2).map(stationSnowGermanDate).join(", ")}${summary.max_dates.length>2?" …":""}`
          :"aktuelles hydrologisches Jahr";

      document.getElementById("stationSnowCoverDaysStat").textContent=
        `${Number(summary.snow_cover_days_observed?.["1"]||0).toLocaleString("de-DE")} Tage`;

      const stale=currentMeta?.last_observation && stationSnowCurrentIndex.data_through &&
        currentMeta.last_observation<stationSnowCurrentIndex.data_through;

      document.getElementById("stationSnowSummary").innerHTML=
        `<strong>${station.name} (${station.id})${height} · hydrologisches Jahr ${hydroYear}:</strong> `+
        `letzte gemeldete Schneehöhe ${stationSnowFormat(summary.last_value_cm)} cm am ${stationSnowGermanDate(summary.last_observation)}. `+
        `Saisonmaximum ${stationSnowFormat(summary.max_cm)} cm. `+
        `${stale?`Die Station meldet SHK_TAG derzeit nicht bis zum Netz-Datenstand ${stationSnowGermanDate(stationSnowCurrentIndex.data_through)}; die rote Kurve endet deshalb am letzten echten Messwert. `:""}`+
        `Referenzbasis: ${refYears}/30 Qualitätsjahre 1991–2020 (${referenceStatus}).`;
    }else{
      document.getElementById("stationSnowLatestStat").textContent="–";
      document.getElementById("stationSnowLatestDetail").textContent="keine SHK_TAG-Werte im hydrologischen Jahr";
      document.getElementById("stationSnowMaxStat").textContent="–";
      document.getElementById("stationSnowMaxDetail").textContent="keine aktuellen Saisonwerte";
      document.getElementById("stationSnowCoverDaysStat").textContent="–";
      document.getElementById("stationSnowSummary").innerHTML=
        `<strong>${station.name} (${station.id})${height}:</strong> `+
        `Für das hydrologische Jahr ${hydroYear} liegen derzeit keine aktuellen Schneehöhenmessungen vor. `+
        (refYears>=10
          ?`Referenzbasis: ${refYears}/30 Qualitätsjahre 1991–2020 (${referenceStatus}).`
          :"Für eine belastbare Referenz 1991–2020 liegen noch keine zehn vollständigen Messjahre vor. Die beobachteten Einzeljahre sind trotzdem verfügbar.");
    }

  }catch(error){
    if(requestId!==stationSnowRequestId) return;
    document.getElementById("stationSnowSummary").textContent=
      `Schneehöhenprofil konnte nicht geladen werden: ${error.message}`;
  }
}

function resetStationSnowZoom(){
  if(stationSnowChart) stationSnowChart.resetZoom();
  if(stationSnowDeviationChart) stationSnowDeviationChart.resetZoom();
}

