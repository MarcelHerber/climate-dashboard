/* stationen-auswertungen.js – Hitzewellen, Niederschlag, Rekorde, Serien
   Aus index.html ausgelagert (Schritt 2b). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= STATIONS-HITZEWELLEN =================
function ensureStationHeatwavesLoaded(){
  if(stationHeatwavesIndex && stationHeatwavesCurrent){
    updateStationHeatwaves();
    return Promise.resolve(stationHeatwavesIndex);
  }
  if(stationHeatwavesLoading) return stationHeatwavesLoading;
  const loading=document.getElementById("stationHeatwavesLoading");
  loading.textContent="Stations-Hitzewellen werden geladen …";
  stationHeatwavesLoading=dashboardFetch("station_heatwaves_index.json",{cache:"no-store"})
    .then(response=>{if(!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();})
    .then(async data=>{
      if(!data.ready) throw new Error(data.message || "Die Stations-Hitzewellen wurden noch nicht aufgebaut.");
      stationHeatwavesIndex=data;
      const currentResponse=await dashboardFetch(data.current_file||"station_heatwaves_current.json",{cache:"no-store"});
      if(!currentResponse.ok) throw new Error(`Aktuelle Hitzewellen konnten nicht geladen werden (HTTP ${currentResponse.status}).`);
      stationHeatwavesCurrent=await currentResponse.json();
      initializeStationHeatwavesControls();
      loading.hidden=true;
      document.getElementById("stationHeatwavesContent").hidden=false;
      document.getElementById("stationHeatwavesSourceNote").textContent=[data.definition,data.severity_definition,data.method_note].filter(Boolean).join(" ");
      return updateStationHeatwaves().then(()=>data);
    })
    .catch(error=>{
      loading.textContent=`Stations-Hitzewellen konnten nicht geladen werden: ${error.message}`;
      loading.style.color="#7a1010";
      throw error;
    });
  return stationHeatwavesLoading;
}

function initializeStationHeatwavesControls(){
  const stateSelect=document.getElementById("stationHeatwavesStateSelect");
  stateSelect.innerHTML='<option value="Deutschland">Deutschland – alle Stationen</option>';
  (stationHeatwavesIndex.states||[]).forEach(state=>{
    const option=document.createElement("option");
    option.value=state;
    option.textContent=state;
    stateSelect.appendChild(option);
  });
  stateSelect.value="Deutschland";
  stateSelect.addEventListener("change",()=>{populateStationHeatwavesStations();updateStationHeatwaves();});
  document.getElementById("stationHeatwavesSearch").addEventListener("input",()=>{populateStationHeatwavesStations();updateStationHeatwaves();});
  document.getElementById("stationHeatwavesStationSelect").addEventListener("change",updateStationHeatwaves);
  document.getElementById("stationHeatwavesRankSelect").addEventListener("change",updateStationHeatwaves);
  populateStationHeatwavesStations();
}

function filteredStationHeatwavesStations(){
  const state=document.getElementById("stationHeatwavesStateSelect").value;
  const search=document.getElementById("stationHeatwavesSearch").value.trim().toLocaleLowerCase("de-DE");
  return (stationHeatwavesIndex.stations||[]).filter(station=>{
    if(state!=="Deutschland" && station.state!==state) return false;
    if(!search) return true;
    return `${station.name} ${station.id}`.toLocaleLowerCase("de-DE").includes(search);
  });
}

function populateStationHeatwavesStations(){
  const select=document.getElementById("stationHeatwavesStationSelect");
  const previous=select.value;
  const stations=filteredStationHeatwavesStations();
  select.innerHTML="";
  stations.forEach(station=>{
    const option=document.createElement("option");
    option.value=station.id;
    option.textContent=`${station.name} (${station.id})`;
    select.appendChild(option);
  });
  if(stations.some(station=>station.id===previous)) select.value=previous;
  else if(stations.length) select.value=stations[0].id;
}

function stationHeatwaveDateText(iso){
  if(!iso) return "–";
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("de-DE");
}

function stationHeatwaveShortDate(iso){
  if(!iso) return "–";
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("de-DE",{day:"2-digit",month:"short"});
}

function stationHeatwaveRange(event,short=false){
  const formatter=short?stationHeatwaveShortDate:stationHeatwaveDateText;
  return `${formatter(event.start)}–${formatter(event.end)}`;
}

function stationHeatwaveNumber(value,decimals=1){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return "–";
  return Number(value).toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}

function stationHeatwaveMidX(event){
  const start=new Date(`${event.start}T00:00:00Z`);
  const end=new Date(`${event.end}T00:00:00Z`);
  const midpoint=new Date((start.getTime()+end.getTime())/2);
  const year=Number(event.year);
  const yearStart=Date.UTC(year,0,1);
  const nextYear=Date.UTC(year+1,0,1);
  const fraction=(midpoint.getTime()-yearStart)/(nextYear-yearStart);
  return year+(fraction-.5)*.7;
}

function stationHeatwaveRadius(event){
  const severity=Math.max(0,Number(event.severity)||0);
  return Math.max(5,Math.min(31,5+Math.sqrt(severity)*2.15));
}

function stationHeatwaveRankValue(event,criterion){
  if(criterion==="duration") return Number(event.duration)||0;
  if(criterion==="max_tmax") return Number(event.max_tmax)||0;
  return Number(event.severity)||0;
}

function stationHeatwaveTopEvents(events,criterion,limit=10){
  return [...events].sort((a,b)=>
    stationHeatwaveRankValue(b,criterion)-stationHeatwaveRankValue(a,criterion) ||
    Number(b.max_tmax)-Number(a.max_tmax) ||
    Number(b.duration)-Number(a.duration) ||
    String(a.start).localeCompare(String(b.start))
  ).slice(0,limit);
}

function stationHeatwavePoint(event,labelled){
  return {
    x:stationHeatwaveMidX(event),
    y:Number(event.max_tmax),
    r:stationHeatwaveRadius(event),
    event,
    labelled
  };
}

async function updateStationHeatwaves(){
  if(!stationHeatwavesIndex || !stationHeatwavesCurrent) return;
  const stationId=document.getElementById("stationHeatwavesStationSelect").value;
  if(!stationId){
    document.getElementById("stationHeatwavesSummary").textContent="Für diese Auswahl wurde keine Station gefunden.";
    return;
  }
  const station=stationHeatwavesIndex.stations.find(item=>item.id===stationId);
  if(!station) return;
  document.getElementById("stationHeatwavesSummary").textContent=`${station.name}: Hitzewellen werden geladen …`;

  try{
    const response=await dashboardFetch(station.file,{cache:"no-store"});
    if(!response.ok) throw new Error(`Profildatei konnte nicht geladen werden (HTTP ${response.status}).`);
    stationHeatwavesProfile=await response.json();
    const currentData=stationHeatwavesCurrent.stations?.[stationId]||{events:[],missing_warm_days:0};
    const historicalEvents=(stationHeatwavesProfile.events||[]).map(event=>({...event,preliminary:false,ongoing:false}));
    const currentEvents=(currentData.events||[]).map(event=>({...event,preliminary:true}));
    const allEvents=[...historicalEvents,...currentEvents];
    const currentYear=Number(stationHeatwavesIndex.current_year);
    const recentStart=Number(stationHeatwavesIndex.recent_period_start);
    const annual=(stationHeatwavesProfile.annual||[]).map(item=>({year:Number(item[0]),count:Number(item[1]),validDays:Number(item[2])}));
    const oldAnnual=annual.filter(item=>item.year<recentStart);
    const recentAnnual=annual.filter(item=>item.year>=recentStart && item.year<currentYear);
    const oldCount=oldAnnual.reduce((sum,item)=>sum+item.count,0);
    const recentCount=recentAnnual.reduce((sum,item)=>sum+item.count,0);
    const oldRate=oldAnnual.length?oldCount/oldAnnual.length:null;
    const recentRate=recentAnnual.length?recentCount/recentAnnual.length:null;

    const longest=stationHeatwaveTopEvents(allEvents,"duration",1)[0]||null;
    const strongest=stationHeatwaveTopEvents(allEvents,"severity",1)[0]||null;
    const hottest=stationHeatwaveTopEvents(allEvents,"max_tmax",1)[0]||null;
    document.getElementById("stationHeatwavesTotalStat").textContent=`${allEvents.length} Ereignisse`;
    document.getElementById("stationHeatwavesCurrentStat").textContent=`${currentEvents.length} ${currentEvents.length===1?"Ereignis":"Ereignisse"} bis ${stationHeatwaveDateText(stationHeatwavesIndex.data_through)}`;
    document.getElementById("stationHeatwavesLongestStat").textContent=longest?`${longest.duration} Tage (${stationHeatwaveRange(longest,true)})`:"Keine Hitzewelle";
    document.getElementById("stationHeatwavesSeverityStat").textContent=strongest?`${stationHeatwaveNumber(strongest.severity,1)} K·Tage (${strongest.year})`:"–";
    document.getElementById("stationHeatwavesIntensityStat").textContent=hottest?`${stationHeatwaveNumber(hottest.max_tmax,1)} °C (${stationHeatwaveDateText(hottest.peak_date)})`:"–";
    const missing=Number(currentData.missing_warm_days||0);
    document.getElementById("stationHeatwavesMissingStat").textContent=missing?`${missing} ${missing===1?"Tag":"Tage"} seit 1. April`:"Keine seit 1. April";

    const oldText=oldAnnual.length?`${oldCount} in ${oldAnnual[0].year}–${oldAnnual[oldAnnual.length-1].year} (${stationHeatwaveNumber(oldRate,2)}/Jahr)`:"kein ausreichend vollständiger älterer Abschnitt";
    const recentText=recentAnnual.length?`${recentCount} in ${recentStart}–${currentYear-1} (${stationHeatwaveNumber(recentRate,2)}/Jahr)`:"kein ausreichend vollständiger jüngerer Abschnitt";
    document.getElementById("stationHeatwavesSummary").textContent=[
      `${station.name} (${station.id})`,
      station.state||"Bundesland unbekannt",
      station.height===null||station.height===undefined?null:`${station.height} m ü. NHN`,
      `historische Vergleichsjahre ${station.start_year}–${station.end_year}`,
      `insgesamt ${allEvents.length} Hitzewellen`,
      oldText,
      recentText,
      `${currentEvents.length} im Jahr ${currentYear}`
    ].filter(Boolean).join(" · ")+".";

    const strongestKeys=new Set(stationHeatwaveTopEvents(allEvents,"severity",8).map(event=>event.start));
    currentEvents.forEach(event=>strongestKeys.add(event.start));
    const groups={
      older:historicalEvents.filter(event=>Number(event.year)<recentStart),
      recent:historicalEvents.filter(event=>Number(event.year)>=recentStart),
      current:currentEvents
    };
    if(stationHeatwavesBubbleChart) stationHeatwavesBubbleChart.destroy();
    stationHeatwavesBubbleChart=new Chart(document.getElementById("stationHeatwavesBubbleChart"),{
      type:"bubble",
      data:{datasets:[
        {label:`${station.start_year}–${recentStart-1}`,data:groups.older.map(event=>stationHeatwavePoint(event,strongestKeys.has(event.start))),backgroundColor:"rgba(82,82,82,.78)",borderColor:"#fff",borderWidth:1.2},
        {label:`${recentStart}–${currentYear-1}`,data:groups.recent.map(event=>stationHeatwavePoint(event,strongestKeys.has(event.start))),backgroundColor:"rgba(166,0,50,.85)",borderColor:"#fff",borderWidth:1.2},
        {label:String(currentYear),data:groups.current.map(event=>stationHeatwavePoint(event,true)),backgroundColor:"rgba(232,92,0,.88)",borderColor:"#111",borderWidth:2}
      ]},
      options:{
        responsive:true,maintainAspectRatio:false,
        interaction:{mode:"nearest",intersect:true},
        plugins:{
          title:{display:true,text:"DIE ANZAHL DER HITZEWELLEN IM ZEITVERLAUF"},
          subtitle:{display:true,text:`${station.name}: jede Blase entspricht einer Hitzewelle (≥ ${stationHeatwavesIndex.minimum_duration} Tage mit Tmax ≥ ${stationHeatwaveNumber(stationHeatwavesIndex.threshold_c,1)} °C)`},
          datalabels:{
            display:context=>Boolean(context.raw?.labelled) && Number(context.raw?.r)>=8,
            formatter:value=>`${value.event.year}\n${stationHeatwaveRange(value.event,true)}`,
            color:"#fff",textStrokeColor:"#111",textStrokeWidth:2,
            font:{size:10,weight:"bold"},textAlign:"center",clip:false
          },
          tooltip:{callbacks:{
            title:items=>items.length?`${items[0].raw.event.year} · ${stationHeatwaveRange(items[0].raw.event)}`:"",
            label:context=>{
              const event=context.raw.event;
              return [
                `${event.duration} Tage`,
                `Maximum: ${stationHeatwaveNumber(event.max_tmax,1)} °C am ${stationHeatwaveDateText(event.peak_date)}`,
                `Mittlere Tmax: ${stationHeatwaveNumber(event.mean_tmax,1)} °C`,
                `Schweregrad: ${stationHeatwaveNumber(event.severity,1)} K·Tage`,
                event.ongoing?"Ereignis läuft am Datenstand noch":""
              ].filter(Boolean);
            }
          }},
          zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},drag:{enabled:true},mode:"x"}}
        },
        scales:{
          x:{type:"linear",min:Math.max(1800,Number(station.start_year)-1),max:currentYear+1,title:{display:true,text:"Jahr"},ticks:{precision:0,maxTicksLimit:16,callback:value=>Number(value).toFixed(0)}},
          y:{beginAtZero:false,suggestedMin:29.5,suggestedMax:42.5,title:{display:true,text:"Intensität: höchste Tages-Tmax der Hitzewelle (°C)"}}
        }
      }
    });

    const barRows=[...annual.map(item=>({...item,current:false})),{
      year:currentYear,count:currentEvents.length,validDays:Number(currentData.valid_warm_days||0),current:true
    }];
    if(stationHeatwavesBarChart) stationHeatwavesBarChart.destroy();
    stationHeatwavesBarChart=new Chart(document.getElementById("stationHeatwavesBarChart"),{
      type:"bar",
      data:{
        labels:barRows.map(item=>String(item.year)),
        datasets:[{
          label:"Anzahl der Hitzewellen",
          data:barRows.map(item=>item.count),
          backgroundColor:barRows.map(item=>item.current?"rgba(232,92,0,.88)":item.year>=recentStart?"rgba(166,0,50,.76)":"rgba(82,82,82,.64)"),
          borderColor:barRows.map(item=>item.current?"#111":"rgba(255,255,255,.6)"),
          borderWidth:barRows.map(item=>item.current?2:0)
        }]
      },
      options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{
          title:{display:true,text:`Anzahl der Hitzewellen pro Jahr – ${station.name}`},
          datalabels:{display:false},
          tooltip:{callbacks:{afterLabel:context=>{
            const row=barRows[context.dataIndex];
            if(row.current) return `Vorläufig bis ${stationHeatwaveDateText(stationHeatwavesIndex.data_through)} · ${missing} fehlende Tmax-Tage seit 1. April`;
            return `${stationHeatwaveNumber(row.validDays/Number(stationHeatwavesProfile.warm_season_expected_days||214)*100,1)} % Datenabdeckung April–Oktober`;
          }}},
          zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
        },
        scales:{x:{ticks:{maxTicksLimit:22,maxRotation:60}},y:{beginAtZero:true,ticks:{precision:0},title:{display:true,text:"Anzahl der Hitzewellen"}}}
      }
    });

    const criterion=document.getElementById("stationHeatwavesRankSelect").value;
    const criterionLabel=criterion==="duration"?"Dauer":criterion==="max_tmax"?"maximaler Tageshöchsttemperatur":"Schweregrad";
    const top10=stationHeatwaveTopEvents(allEvents,criterion,10);
    document.getElementById("stationHeatwavesTopTitle").textContent=`Top 10 der Hitzewellen nach ${criterionLabel} – ${station.name}`;
    const tbody=document.querySelector("#stationHeatwavesTopTable tbody");
    tbody.innerHTML=top10.length?top10.map((event,index)=>`<tr>
      <td>${index+1}</td>
      <td>${stationHeatwaveRange(event)}${event.ongoing?" (laufend)":""}</td>
      <td><strong>${event.duration} Tage</strong></td>
      <td>${stationHeatwaveNumber(event.max_tmax,1)} °C</td>
      <td>${stationHeatwaveNumber(event.mean_tmax,1)} °C</td>
      <td>${stationHeatwaveNumber(event.severity,1)} K·Tage</td>
      <td><span class="record-badge ${event.preliminary?"preliminary":"checked"}">${event.preliminary?"vorläufig":"geprüft"}</span></td>
    </tr>`).join(""):'<tr><td colspan="7">An dieser Station wurde nach der gewählten Definition noch keine Hitzewelle erkannt.</td></tr>';
  }catch(error){
    document.getElementById("stationHeatwavesSummary").textContent=`Stations-Hitzewellen konnten nicht geladen werden: ${error.message}`;
  }
}

function resetStationHeatwavesZoom(){
  if(stationHeatwavesBubbleChart) stationHeatwavesBubbleChart.resetZoom();
  if(stationHeatwavesBarChart) stationHeatwavesBarChart.resetZoom();
}


// ================= STATIONSNIEDERSCHLAG =================
function stationPrecipCalendarLabels(year){
  const labels=[];
  for(let cursor=new Date(Date.UTC(year,0,1));cursor.getUTCFullYear()===year;cursor.setUTCDate(cursor.getUTCDate()+1)){
    labels.push(cursor.toISOString().slice(5,10));
  }
  return labels;
}

function stationPrecipDecodeYear(encoded,year,labels){
  try{
    const sourceLabels=stationPrecipCalendarLabels(year);
    const bytes=atob(encoded);
    if(bytes.length!==sourceLabels.length*2)return null;
    let total=0;
    const cumulative=new Map();
    for(let i=0;i<sourceLabels.length;i++){
      total+=bytes.charCodeAt(i*2)*256+bytes.charCodeAt(i*2+1);
      cumulative.set(sourceLabels[i],total/10);
    }
    // On non-leap comparison axes, the 29 February amount enters the
    // cumulative value on 1 March. Annual totals never lose precipitation.
    return labels.map(label=>cumulative.get(label)??(label==="02-29"?cumulative.get("02-28"):null));
  }catch(error){return null;}
}

function stationPrecipYearView({year,dataThrough,currentDaily,profile}){
  const labels=stationPrecipCalendarLabels(year);
  const current=[];
  const missingDates=[];
  let total=0;
  for(let i=0;i<labels.length;i++){
    const iso=year+"-"+labels[i],value=currentDaily[i];
    if(iso>dataThrough){current.push(null);continue;}
    if(value==null||!Number.isFinite(Number(value))){current.push(null);missingDates.push(iso);continue;}
    total+=Math.round(Number(value)*10);
    current.push(total/10);
  }
  const curves={};
  for(const [key,encoded] of Object.entries(profile.historical_year_daily_tenths||{})){
    const historyYear=Number(key);
    if(!Number.isInteger(historyYear)||historyYear<1||historyYear>=year)continue;
    const curve=stationPrecipDecodeYear(encoded,historyYear,labels);
    if(curve&&Number.isFinite(curve.at(-1)))curves[key]=curve;
  }
  const entries=Object.entries(curves);
  const reference=entries.filter(([key])=>Number(key)>=1991&&Number(key)<=2020);
  const legacyLabels=stationPrecipCalendarLabels(2001);
  const legacy=(key)=>{
    const values=profile[key]||[];
    return labels.map(label=>values[legacyLabels.indexOf(label==="02-29"?"02-28":label)]??null);
  };
  const climate=reference.length>=5?labels.map((_,i)=>Math.round(reference.reduce((sum,[,data])=>sum+data[i],0)/reference.length*10)/10):legacy("climate_mean_cumulative");
  const minimum=entries.length?labels.map((_,i)=>Math.min(...entries.map(([,data])=>data[i]))):legacy("historical_min_cumulative");
  const maximum=entries.length?labels.map((_,i)=>Math.max(...entries.map(([,data])=>data[i]))):legacy("historical_max_cumulative");
  const annualOrder=entries.slice().sort((a,b)=>a[1].at(-1)-b[1].at(-1)||Number(a[0])-Number(b[0]));
  return {labels,current,climate,minimum,maximum,curves,missingDates,total:total/10,referenceCount:reference.length>=5?reference.length:0,
    dryYear:annualOrder.length?Number(annualOrder[0][0]):null,
    wetYear:annualOrder.length?Number(annualOrder.at(-1)[0]):null};
}

function stationPrecipHistoricalDatasets(view,selected){
  return Object.entries(view.curves).filter(([year])=>selected.has(Number(year))).map(([year,data])=>{
    const wet=Number(year)===view.wetYear,dry=Number(year)===view.dryYear;
    return {label:year,data,borderColor:wet?"#1680cf":dry?"#df861c":selected.size>10?"rgba(130,140,150,.35)":"rgba(125,135,145,.85)",
      borderWidth:wet||dry?2.1:1,pointRadius:0,tension:0,spanGaps:false,fill:false,order:wet||dry?2:3,historyYear:true,historyExtreme:wet||dry};
  });
}

let stationPrecipHistoryStation=null,stationPrecipHistoryView=null,stationPrecipHistorySelection=new Set(),stationPrecipRequestId=0;

function stationPrecipHistoryApply(){
  if(!stationPrecipChart||!stationPrecipHistoryView)return;
  const selected=stationPrecipHistorySelection,view=stationPrecipHistoryView;
  const history=stationPrecipHistoricalDatasets(view,selected);
  stationPrecipChart.data.datasets=stationPrecipChart.data.datasets.filter(dataset=>!dataset.historyYear).concat(history);
  document.getElementById("stationPrecipHistoryCount").textContent=`(${history.length}/${Object.keys(view.curves).length})`;
  document.querySelectorAll("#stationPrecipHistoryYears input").forEach(input=>{input.checked=selected.has(Number(input.value));});
  stationPrecipChart.options.plugins.subtitle.text=history.length
    ?`Vollständige historische Messjahre · ${history.length} eingeblendet · Einzelsummen ab 1. Januar`
    :"Niederschlagssumme ab 1. Januar · aktuelles Jahr nur bis zum Datenstand.";
  stationPrecipChart.update("none");
}

function stationPrecipHistoryControls(stationId,view){
  const control=document.getElementById("stationPrecipHistoryControl");
  stationPrecipHistoryView=view;
  control.hidden=!view;
  if(!view)return;
  if(stationPrecipHistoryStation!==stationId){
    stationPrecipHistoryStation=stationId;
    stationPrecipHistorySelection.clear();
    control.open=false;
  }
  const years=Object.keys(view.curves).map(Number).sort((a,b)=>b-a);
  stationPrecipHistorySelection=new Set([...stationPrecipHistorySelection].filter(year=>years.includes(year)));
  const target=document.getElementById("stationPrecipHistoryYears");
  target.replaceChildren();
  for(const year of years){
    const label=document.createElement("label");
    label.style.cssText="display:flex;align-items:center;gap:5px;white-space:nowrap;cursor:pointer";
    const input=document.createElement("input");
    input.type="checkbox";input.value=String(year);input.checked=stationPrecipHistorySelection.has(year);
    input.addEventListener("change",()=>{
      if(input.checked)stationPrecipHistorySelection.add(year);else stationPrecipHistorySelection.delete(year);
      stationPrecipHistoryApply();
    });
    label.append(input,document.createTextNode(String(year)));
    if(year===view.wetYear||year===view.dryYear)label.title=year===view.wetYear?"Nassestes vollständiges Jahr":"Trockenstes vollständiges Jahr";
    target.append(label);
  }
  document.getElementById("stationPrecipHistoryNote").textContent=years.length
    ?"Graue Linien = historische Messjahre · blau = nassestes, orange = trockenstes vollständiges Jahr. Schaltjahre: Der 29. Februar zählt vollständig zur Jahressumme."
    :"Für diese Station sind noch keine vollständigen Einzeljahreskurven veröffentlicht.";
  document.getElementById("stationPrecipHistoryAll").disabled=!years.length;
  document.getElementById("stationPrecipHistoryNone").disabled=!years.length;
  document.getElementById("stationPrecipHistoryAll").onclick=()=>{
    stationPrecipHistorySelection=new Set(years);stationPrecipHistoryApply();
  };
  document.getElementById("stationPrecipHistoryNone").onclick=()=>{
    stationPrecipHistorySelection.clear();stationPrecipHistoryApply();
  };
  stationPrecipHistoryApply();
}

function stationPrecipFormat(value,decimals=1){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return "–";
  return Number(value).toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}

function stationPrecipDateLabel(monthDay){
  const [month,day]=monthDay.split("-");
  return `${day}.${month}.`;
}

function stationPrecipGermanIsoDate(iso){
  if(!iso) return "–";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
}

function stationPrecipLastDayOfMonth(year,month){
  return new Date(year,month,0).getDate();
}

function stationPrecipClampIso(iso,minIso,maxIso){
  if(!iso) return minIso;
  return iso<minIso?minIso:iso>maxIso?maxIso:iso;
}

function stationPrecipResolveRange(period,customStart,customEnd,index=stationPrecipIndex){
  const year=Number(index.current_year);
  const first=`${year}-01-01`;
  const dataThrough=index.data_through;
  let start=first,end=dataThrough,label="Seit Jahresbeginn";
  if(period==="spring"){start=`${year}-03-01`;end=`${year}-05-31`;label="Frühling";}
  else if(period==="summer"){start=`${year}-06-01`;end=`${year}-08-31`;label="Sommer";}
  else if(period==="autumn"){start=`${year}-09-01`;end=`${year}-11-30`;label="Herbst";}
  else if(period?.startsWith("month-")){
    const month=Number(period.slice(6));
    const monthText=String(month).padStart(2,"0");
    start=`${year}-${monthText}-01`;
    end=`${year}-${monthText}-${String(stationPrecipLastDayOfMonth(year,month)).padStart(2,"0")}`;
    label=new Date(year,month-1,1).toLocaleDateString("de-DE",{month:"long"});
  }else if(period==="custom"){
    start=stationPrecipClampIso(customStart||first,first,dataThrough);
    end=stationPrecipClampIso(customEnd||dataThrough,first,dataThrough);
    label="Freier Zeitraum";
  }
  if(start>dataThrough){
    return {valid:false,start,end:dataThrough,label,message:`${label} ${year} hat zum Datenstand ${stationPrecipGermanIsoDate(dataThrough)} noch nicht begonnen.`};
  }
  end=end>dataThrough?dataThrough:end;
  if(end<start){
    return {valid:false,start,end,label,message:"Das Enddatum liegt vor dem Startdatum."};
  }
  const startKey=start.slice(5),endKey=end.slice(5);
  const labels=index.labels||[];
  const startIndex=labels.indexOf(startKey);
  const endIndex=labels.indexOf(endKey);
  if(startIndex<0||endIndex<0||endIndex<startIndex){
    return {valid:false,start,end,label,message:"Der gewählte Zeitraum konnte nicht auf die Tagesachse abgebildet werden."};
  }
  const displayLabel=period==="ytd"
    ?`Seit Jahresbeginn bis ${stationPrecipGermanIsoDate(end)}`
    :`${label} ${year} · ${stationPrecipGermanIsoDate(start)}–${stationPrecipGermanIsoDate(end)}`;
  return {valid:true,start,end,startIndex,endIndex,label,displayLabel,period,year};
}

function stationPrecipRangeFromPageControls(){
  const period=document.getElementById("stationPrecipPeriodSelect")?.value||"ytd";
  if(period==="ytd"&&stationPrecipIndex){
    const year=Number(stationPrecipIndex.current_year),end=stationPrecipIndex.data_through;
    const labels=stationPrecipCalendarLabels(year),endIndex=labels.indexOf(end.slice(5));
    if(endIndex>=0)return {valid:true,start:`${year}-01-01`,end,startIndex:0,endIndex,label:"Seit Jahresbeginn",displayLabel:`Seit Jahresbeginn bis ${stationPrecipGermanIsoDate(end)}`,period,year};
  }
  return stationPrecipResolveRange(
    period,
    document.getElementById("stationPrecipStartDate")?.value,
    document.getElementById("stationPrecipEndDate")?.value
  );
}

function stationPrecipRangeFromMapControls(){
  return stationPrecipResolveRange(
    document.getElementById("mapPrecipPeriodSelect")?.value||"ytd",
    document.getElementById("mapPrecipStartDate")?.value,
    document.getElementById("mapPrecipEndDate")?.value
  );
}

function stationPrecipConfigureDateInputs(prefix,index=stationPrecipIndex){
  if(!index) return;
  const year=Number(index.current_year);
  const min=`${year}-01-01`,max=index.data_through;
  const start=document.getElementById(`${prefix}StartDate`);
  const end=document.getElementById(`${prefix}EndDate`);
  [start,end].forEach(input=>{if(input){input.min=min;input.max=max;}});
  if(start&&!start.value) start.value=min;
  if(end&&!end.value) end.value=max;
}

function stationPrecipToggleCustomRange(prefix){
  const period=document.getElementById(`${prefix}PeriodSelect`)?.value;
  const group=document.getElementById(`${prefix}CustomRangeGroup`);
  if(group) group.hidden=period!=="custom";
}

function ensureStationPrecipLoaded(){
  if(stationPrecipIndex){
    updateStationPrecipitation();
    return Promise.resolve(stationPrecipIndex);
  }
  if(stationPrecipLoading) return stationPrecipLoading;
  const loading=document.getElementById("stationPrecipLoading");
  loading.textContent="Stationsniederschlag wird geladen …";
  stationPrecipLoading=dashboardFetch("station_precip_index.json",{cache:"no-store"})
    .then(response=>{if(!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();})
    .then(data=>{
      if(!data.ready) throw new Error(data.message || "Die Stations-Niederschlagsdateien wurden noch nicht aufgebaut.");
      stationPrecipIndex=data;
      initializeStationPrecipControls();
      stationPrecipConfigureDateInputs("stationPrecip");
      stationPrecipConfigureDateInputs("mapPrecip");
      loading.hidden=true;
      document.getElementById("stationPrecipContent").hidden=false;
      document.getElementById("stationPrecipSourceNote").textContent=data.source_note || "";
      return updateStationPrecipitation().then(()=>data);
    })
    .catch(error=>{
      loading.textContent=`Stationsniederschlag konnte nicht geladen werden: ${error.message}`;
      loading.style.color="#7a1010";
      throw error;
    });
  return stationPrecipLoading;
}

function initializeStationPrecipControls(){
  const stateSelect=document.getElementById("stationPrecipStateSelect");
  stateSelect.innerHTML='<option value="Deutschland">Deutschland – alle Stationen</option>';
  (stationPrecipIndex.states||[]).forEach(state=>{
    const option=document.createElement("option");
    option.value=state;
    option.textContent=state;
    stateSelect.appendChild(option);
  });
  stateSelect.value="Deutschland";
  stateSelect.addEventListener("change",()=>{
    populateStationPrecipStations();
    updateStationPrecipitation();
  });
  document.getElementById("stationPrecipSearch").addEventListener("input",()=>{
    populateStationPrecipStations();
    updateStationPrecipitation();
  });
  document.getElementById("stationPrecipStationSelect").addEventListener("change",updateStationPrecipitation);
  document.getElementById("stationPrecipPeriodSelect")?.addEventListener("change",()=>{
    stationPrecipToggleCustomRange("stationPrecip");
    updateStationPrecipitation();
  });
  ["stationPrecipStartDate","stationPrecipEndDate"].forEach(id=>document.getElementById(id)?.addEventListener("change",updateStationPrecipitation));
  stationPrecipToggleCustomRange("stationPrecip");
  populateStationPrecipStations();
}

function filteredStationPrecipStations(){
  const state=document.getElementById("stationPrecipStateSelect").value;
  const search=document.getElementById("stationPrecipSearch").value.trim().toLocaleLowerCase("de-DE");
  return (stationPrecipIndex.stations||[]).filter(station=>{
    if(state!=="Deutschland" && station.state!==state) return false;
    if(!search) return true;
    return `${station.name} ${station.id}`.toLocaleLowerCase("de-DE").includes(search);
  });
}

function populateStationPrecipStations(){
  const select=document.getElementById("stationPrecipStationSelect");
  const previous=select.value;
  const stations=filteredStationPrecipStations();
  select.innerHTML="";
  stations.forEach(station=>{
    const option=document.createElement("option");
    option.value=station.id;
    option.textContent=`${station.name} (${station.id})`;
    select.appendChild(option);
  });
  if(stations.some(station=>station.id===previous)) select.value=previous;
  else if(stations.length) select.value=stations[0].id;
}

async function loadStationPrecipCurrentMonths(){
  const files=stationPrecipIndex.current_files||[];
  await Promise.all(files.map(async file=>{
    if(stationPrecipMonthCache.has(file)) return;
    const response=await dashboardFetch(file,{cache:"no-store"});
    if(!response.ok) throw new Error(`${file} konnte nicht geladen werden (HTTP ${response.status}).`);
    stationPrecipMonthCache.set(file,await response.json());
  }));
}

function stationPrecipCurrentDaily(stationId,labels=stationPrecipIndex.labels||[]){
  const byMonth=new Map();
  for(const payload of stationPrecipMonthCache.values()) byMonth.set(Number(payload.month),payload);
  return labels.map(label=>{
    const [monthText,dayText]=label.split("-");
    const month=Number(monthText), day=Number(dayText);
    const payload=byMonth.get(month);
    const values=payload?.stations?.[stationId];
    return values && day<=values.length ? values[day-1] : null;
  });
}

function stationPrecipCumulativeWithGaps(values,labels,dataThrough){
  let total=0;
  const missingDates=[];
  const result=values.map((value,index)=>{
    const iso=`${stationPrecipIndex.current_year}-${labels[index]}`;
    if(iso>dataThrough) return null;
    if(value===null || value===undefined || !Number.isFinite(Number(value))){
      missingDates.push(iso);
      return null;
    }
    total+=Number(value);
    return Math.round(total*10)/10;
  });
  result.missingDates=missingDates;
  result.missingCount=missingDates.length;
  return result;
}

function stationPrecipRangeCumulative(values,labels,range){
  let total=0;
  const missingDates=[];
  const result=[];
  for(let index=range.startIndex;index<=range.endIndex;index++){
    const value=values[index];
    const iso=`${range.year}-${labels[index]}`;
    if(value===null || value===undefined || !Number.isFinite(Number(value))){
      missingDates.push(iso);
      result.push(null);
      continue;
    }
    total+=Number(value);
    result.push(Math.round(total*10)/10);
  }
  result.missingDates=missingDates;
  result.missingCount=missingDates.length;
  result.total=Math.round(total*10)/10;
  return result;
}

function stationPrecipRangeCurveFromCumulative(curve,range){
  if(!Array.isArray(curve)||!curve.length) return [];
  const base=range.startIndex>0?Number(curve[range.startIndex-1]||0):0;
  return curve.slice(range.startIndex,range.endIndex+1).map(value=>
    value===null||value===undefined||!Number.isFinite(Number(value))?null:Math.round((Number(value)-base)*10)/10
  );
}

function stationPrecipRangeTotalFromCumulative(curve,range){
  if(!Array.isArray(curve)||range.endIndex>=curve.length) return null;
  const end=Number(curve[range.endIndex]);
  const base=range.startIndex>0?Number(curve[range.startIndex-1]):0;
  return Number.isFinite(end)&&Number.isFinite(base)?Math.round((end-base)*10)/10:null;
}


function stationPrecipMonthlyFormat(value){
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}) : "–";
}
function stationPrecipCurrentMonthlyRow(stationId){
  if(!stationPrecipIndex) return null;
  const currentYear=Number(stationPrecipIndex.current_year), dataThrough=String(stationPrecipIndex.data_through||"");
  if(!Number.isFinite(currentYear)) return null;
  const byMonth=new Map();
  for(const payload of stationPrecipMonthCache.values()) if(Number(payload?.year)===currentYear) byMonth.set(Number(payload.month),payload);
  const months=Array(12).fill(null);
  for(let month=1;month<=12;month++){
    const values=byMonth.get(month)?.stations?.[stationId];
    if(!Array.isArray(values)) continue;
    const days=new Date(currentYear,month,0).getDate();
    const end=`${currentYear}-${String(month).padStart(2,"0")}-${String(days).padStart(2,"0")}`;
    if(!dataThrough || dataThrough<end || values.length<days) continue;
    const part=values.slice(0,days);
    if(!part.every(v=>v!==null&&v!==undefined&&Number.isFinite(Number(v)))) continue;
    months[month-1]=Math.round(part.reduce((s,v)=>s+Number(v),0)*10)/10;
  }
  if(!months.some(Number.isFinite)) return null;
  const annual=months.every(Number.isFinite)?Math.round(months.reduce((s,v)=>s+Number(v),0)*10)/10:null;
  return {year:currentYear,months,annual,current:true};
}
function stationPrecipMonthlyExtrema(rows){
  const extrema=Array.from({length:12},()=>({min:null,max:null}));
  for(let monthIndex=0;monthIndex<12;monthIndex++){
    const values=rows.map(row=>Number(row.months?.[monthIndex])).filter(value=>Number.isFinite(value));
    if(values.length) extrema[monthIndex]={min:Math.min(...values),max:Math.max(...values)};
  }
  return extrema;
}
function updateStationPrecipMonthlyTable(stationId){
  const body=document.getElementById("stationPrecipMonthlyBody");
  if(!body) return;
  const station=stationPrecipIndex?.stations?.find(item=>item.id===stationId);
  const historical=Array.isArray(stationPrecipProfile?.monthly_history)?stationPrecipProfile.monthly_history.map(row=>({year:Number(row.year),months:Array.isArray(row.months)?row.months.slice(0,12):Array(12).fill(null),annual:row.annual,current:false})):[];
  const current=stationPrecipCurrentMonthlyRow(stationId), currentYear=Number(stationPrecipIndex?.current_year);
  const rows=historical.filter(r=>Number.isFinite(r.year)&&r.year!==currentYear).sort((a,b)=>b.year-a.year);
  if(current) rows.unshift(current);
  const title=document.getElementById("stationPrecipMonthlyTitle"), subtitle=document.getElementById("stationPrecipMonthlySubtitle"), note=document.getElementById("stationPrecipMonthlyNote");
  if(title) title.textContent=`Monatsniederschlag · ${station?.name||stationId}`;
  if(subtitle){
    const years=historical.map(r=>Number(r.year)).filter(Number.isFinite);
    subtitle.textContent=`Monatssummen in mm · ${years.length?Math.min(...years)+"–":""}${currentYear||""} · neuestes Jahr oben`;
  }
  if(!rows.length){
    body.innerHTML='<tr><td colspan="14" class="no-value">Noch keine Monatslisten im Stationsprofil vorhanden.</td></tr>';
    if(note) note.textContent="Die historischen Monatslisten werden beim nächsten vollständigen Neuaufbau der Niederschlagsprofile erzeugt.";
    return;
  }
  const extrema=stationPrecipMonthlyExtrema(rows);
  body.innerHTML=rows.map(row=>{
    const cells=Array.from({length:12},(_,i)=>{
      const raw=row.months?.[i];
      const ok=raw!==null&&raw!==undefined&&Number.isFinite(Number(raw));
      if(!ok) return '<td class="no-value">-</td>';
      const num=Number(raw);
      const classes=[];
      if(extrema[i].max!==null&&num===extrema[i].max) classes.push('station-precip-monthly-max');
      if(extrema[i].min!==null&&num===extrema[i].min) classes.push('station-precip-monthly-min');
      return `<td class="${classes.join(' ')}">${stationPrecipMonthlyFormat(raw)}</td>`;
    }).join("");
    const ok=row.annual!==null&&row.annual!==undefined&&Number.isFinite(Number(row.annual));
    return `<tr class="${row.current?"current-year":""}"><td class="year-cell">${row.year}</td>${cells}<td class="annual-cell ${ok?"":"no-value"}">${ok?stationPrecipMonthlyFormat(row.annual):"-"}</td></tr>`;
  }).join("");
  if(note) note.textContent="Monatsmaxima sind grün, Monatsminima braun markiert. Noch nicht begonnene oder unvollständige Monate werden mit '-' angezeigt. Die Jahressumme erscheint nur bei zwölf vollständigen Monaten.";
}

async function updateStationPrecipitation(){
  if(!stationPrecipIndex) return;
  const requestId=++stationPrecipRequestId;
  const stationId=document.getElementById("stationPrecipStationSelect").value;
  if(!stationId){
    stationPrecipHistoryControls(stationId,null);
    document.getElementById("stationPrecipSummary").textContent="Für diese Auswahl wurde keine Station gefunden.";
    return;
  }
  const range=stationPrecipRangeFromPageControls();
  if(!range.valid){
    stationPrecipHistoryControls(stationId,null);
    document.getElementById("stationPrecipSummary").textContent=range.message;
    return;
  }
  const station=stationPrecipIndex.stations.find(item=>item.id===stationId);
  document.getElementById("stationPrecipSummary").textContent=`${station.name}: Daten für ${range.displayLabel} werden geladen …`;
  try{
    const [profileResponse]=await Promise.all([
      dashboardFetch(station.file,{cache:"no-store"}),
      loadStationPrecipCurrentMonths()
    ]);
    if(!profileResponse.ok) throw new Error(`Klimadatei konnte nicht geladen werden (HTTP ${profileResponse.status}).`);
    const profile=await profileResponse.json();
    if(requestId!==stationPrecipRequestId)return;
    stationPrecipProfile=profile;
    updateStationPrecipMonthlyTable(stationId);

    const fullYear=range.period==="ytd";
    const labels=fullYear?stationPrecipCalendarLabels(range.year):stationPrecipIndex.labels||[];
    const selectedLabels=fullYear?labels:labels.slice(range.startIndex,range.endIndex+1);
    const currentDaily=stationPrecipCurrentDaily(stationId,labels);
    const yearView=fullYear?stationPrecipYearView({year:range.year,dataThrough:range.end,currentDaily,profile}):null;
    const currentCumulative=stationPrecipRangeCumulative(currentDaily,labels,range);
    const climate=yearView?yearView.climate.slice(0,range.endIndex+1):stationPrecipRangeCurveFromCumulative(stationPrecipProfile.climate_mean_cumulative||[],range);
    const chartCurrent=yearView?yearView.current:currentCumulative;
    const chartClimate=yearView?yearView.climate:climate;
    const currentValue=currentCumulative.total;
    const climateValue=climate.length?climate[climate.length-1]:null;
    const deviation=Number.isFinite(currentValue)&&Number.isFinite(climateValue)?currentValue-climateValue:null;
    const percentage=deviation!==null&&climateValue>0?deviation/climateValue*100:null;

    let historicalMin=[],historicalMax=[],minValue=null,maxValue=null,minYear=null,maxYear=null;
    const ytdCompatible=range.startIndex===0;
    const periodHistory=stationPrecipProfile.historical_periods?.[range.period]??null;
    const periodCompatible=Boolean(periodHistory)
      && Number(periodHistory.start_index)===range.startIndex
      && range.endIndex<=Number(periodHistory.end_index);
    const historicalCompatible=ytdCompatible||periodCompatible;
    if(yearView){
      historicalMin=yearView.minimum;
      historicalMax=yearView.maximum;
      minValue=historicalMin[range.endIndex]??null;
      maxValue=historicalMax[range.endIndex]??null;
      const candidates=Object.entries(yearView.curves).map(([year,curve])=>[Number(year),curve[range.endIndex]]).filter(([,value])=>Number.isFinite(value)).sort((a,b)=>a[1]-b[1]||a[0]-b[0]);
      const legacyIndex=stationPrecipCalendarLabels(2001).indexOf(labels[range.endIndex]==="02-29"?"02-28":labels[range.endIndex]);
      minYear=candidates[0]?.[0]??stationPrecipProfile.historical_min_year?.[legacyIndex]??null;
      maxYear=candidates.at(-1)?.[0]??stationPrecipProfile.historical_max_year?.[legacyIndex]??null;
    }else if(ytdCompatible){
      historicalMin=(stationPrecipProfile.historical_min_cumulative||[]).slice(range.startIndex,range.endIndex+1);
      historicalMax=(stationPrecipProfile.historical_max_cumulative||[]).slice(range.startIndex,range.endIndex+1);
      minValue=historicalMin.length?historicalMin[historicalMin.length-1]:null;
      maxValue=historicalMax.length?historicalMax[historicalMax.length-1]:null;
      minYear=(stationPrecipProfile.historical_min_year||[])[range.endIndex]??null;
      maxYear=(stationPrecipProfile.historical_max_year||[])[range.endIndex]??null;
    }else if(periodCompatible){
      const endOffset=range.endIndex-range.startIndex;
      historicalMin=(periodHistory.historical_min_cumulative||[]).slice(0,endOffset+1);
      historicalMax=(periodHistory.historical_max_cumulative||[]).slice(0,endOffset+1);
      minValue=historicalMin.length?historicalMin[historicalMin.length-1]:null;
      maxValue=historicalMax.length?historicalMax[historicalMax.length-1]:null;
      minYear=(periodHistory.historical_min_year||[])[endOffset]??null;
      maxYear=(periodHistory.historical_max_year||[])[endOffset]??null;
    }

    const missingDates=currentCumulative.missingDates||[];
    const missingCount=currentCumulative.missingCount||0;
    document.getElementById("stationPrecipCurrentStat").textContent=Number.isFinite(currentValue)?`${stationPrecipFormat(currentValue)} mm · ${range.displayLabel}`:"–";
    document.getElementById("stationPrecipMeanStat").textContent=Number.isFinite(climateValue)?`${stationPrecipFormat(climateValue)} mm · gleicher Kalenderzeitraum`:"–";
    document.getElementById("stationPrecipDeviationStat").textContent=deviation===null?"–":`${deviation>=0?"+":""}${stationPrecipFormat(deviation)} mm (${percentage>=0?"+":""}${stationPrecipFormat(percentage)} %)`;
    document.getElementById("stationPrecipRangeStat").textContent=historicalCompatible&&minValue!==null
      ?`${stationPrecipFormat(minValue)} mm (${minYear}) bis ${stationPrecipFormat(maxValue)} mm (${maxYear})`
      :"Für diesen Zeitraum nicht vorab berechnet";
    document.getElementById("stationPrecipMissingStat").textContent=missingCount===0
      ? "Keine fehlenden Tageswerte im Zeitraum"
      : `${missingCount} ${missingCount===1?"Tag":"Tage"} ohne Messwert im Zeitraum`;

    const metaParts=[
      `${station.name} (${station.id})`,station.state||"Bundesland unbekannt",
      station.height===null||station.height===undefined?null:`${station.height} m ü. NHN`,
      range.displayLabel,
      `${yearView?.referenceCount||station.reference_years} vollständige Referenzjahre 1991–2020`
    ].filter(Boolean);
    let gapText="";
    if(missingCount>0){
      const shownDates=missingDates.slice(0,5).map(iso=>new Date(`${iso}T00:00:00`).toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit"}));
      const moreDates=missingCount>shownDates.length?` und ${missingCount-shownDates.length} weitere`:"";
      gapText=` Es fehlen ${missingCount} ${missingCount===1?"Tageswert":"Tageswerte"} (${shownDates.join(", ")}${moreDates}). Fehlende Tage werden nicht als 0 mm gewertet.`;
    }else gapText=" Für den gewählten Zeitraum liegen bis zum Datenstand alle Tageswerte vor.";
    if(!historicalCompatible) gapText+=" Der historische Min-Max-Spannbereich ist derzeit für Seit Jahresbeginn sowie Frühling, Sommer und Herbst verfügbar.";
    document.getElementById("stationPrecipSummary").textContent=metaParts.join(" · ")+`.${gapText}`;

    if(stationPrecipChart) stationPrecipChart.destroy();
    const datasets=[];
    if(historicalCompatible){
      datasets.push(
        {label:"Historisches Maximum",data:historicalMax,borderColor:"rgba(110,110,110,.65)",backgroundColor:"rgba(150,150,150,.18)",borderWidth:1,pointRadius:0,fill:{target:1,above:"rgba(150,150,150,.18)"},tension:.12},
        {label:"Historisches Minimum",data:historicalMin,borderColor:"rgba(110,110,110,.65)",borderWidth:1,pointRadius:0,fill:false,tension:.12}
      );
    }
    datasets.push(
      {label:fullYear?"Mittel 1991–2020":`Mittel ${hyrasReferenceDisplay()}`,data:chartClimate,borderColor:"#111",borderWidth:2,borderDash:[8,5],pointRadius:0,fill:false,tension:.12,order:0},
      {label:String(stationPrecipIndex.current_year),data:chartCurrent,borderColor:"#c53030",backgroundColor:"rgba(197,48,48,.08)",borderWidth:3,pointRadius:0,spanGaps:!fullYear,fill:false,tension:.12,order:-1}
    );
    const xTicks=fullYear?{autoSkip:false,maxRotation:0,callback:function(value){
      const label=this.getLabelForValue(value);
      return label?.startsWith("01.")?MONTH_SHORT[Number(label.slice(3,5))-1]:null;
    }}:{maxTicksLimit:14,maxRotation:0};
    stationPrecipChart=new Chart(document.getElementById("stationPrecipChart"),{
      type:"line",data:{labels:selectedLabels.map(stationPrecipDateLabel),datasets},
      options:{responsive:true,maintainAspectRatio:false,interaction:{mode:fullYear?"nearest":"index",intersect:false},plugins:{
        legend:{labels:{filter:(item,data)=>{const dataset=data.datasets[item.datasetIndex];return !dataset?.historyYear||dataset.historyExtreme||stationPrecipHistorySelection.size<=10;}},
          onClick:(event,item,legend)=>{
            const dataset=legend.chart.data.datasets[item.datasetIndex];
            if(dataset?.historyYear){stationPrecipHistorySelection.delete(Number(dataset.label));stationPrecipHistoryApply();return;}
            Chart.defaults.plugins.legend.onClick(event,item,legend);
          }},
        title:{display:true,text:`Kumulierte Niederschlagssumme – ${station.name} – ${range.displayLabel}`},
        subtitle:{display:true,text:"Die Summe startet am ersten Tag des gewählten Zeitraums wieder bei 0 mm.",color:"#666",font:{size:12}},
        datalabels:{display:false},tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${stationPrecipFormat(context.parsed.y)} mm`}},
        zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
      },scales:{x:{ticks:xTicks},y:{beginAtZero:true,title:{display:true,text:"Niederschlagssumme (mm)"}}}}
    });
    stationPrecipHistoryControls(stationId,yearView);

    const deviationSeries=chartCurrent.map((value,index)=>value==null||chartClimate[index]==null?null:Math.round((value-chartClimate[index])*10)/10);
    if(stationPrecipDeviationChart) stationPrecipDeviationChart.destroy();
    stationPrecipDeviationChart=new Chart(document.getElementById("stationPrecipDeviationChart"),{
      type:"line",data:{labels:selectedLabels.map(stationPrecipDateLabel),datasets:[{
        label:`Abweichung ${stationPrecipIndex.current_year} zu 1991–2020`,data:deviationSeries,borderColor:"rgba(80,80,80,.9)",borderWidth:2,pointRadius:0,
        fill:{target:"origin",above:"rgba(50,145,75,.24)",below:"rgba(154,94,43,.24)"},segment:{borderColor:context=>context.p1.parsed.y>=0?"rgba(44,130,66,.95)":"rgba(145,82,35,.95)"},tension:.12
      }]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{
        title:{display:true,text:`Kumulative Niederschlagsabweichung – ${station.name} (${station.id}) – ${range.displayLabel}`},
        subtitle:{display:true,text:"Vergleich mit exakt demselben Kalenderzeitraum des Mittels 1991–2020.",color:"#666",font:{size:12}},
        datalabels:{display:false},tooltip:{callbacks:{label:context=>`${context.parsed.y>=0?"+":""}${stationPrecipFormat(context.parsed.y)} mm`}},
        zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
      },scales:{x:{ticks:xTicks},y:{title:{display:true,text:"Abweichung (mm)"}}}}
    });
  }catch(error){
    if(requestId===stationPrecipRequestId)document.getElementById("stationPrecipSummary").textContent=`Stationskurve konnte nicht geladen werden: ${error.message}`;
  }
}

function resetStationPrecipZoom(){
  if(stationPrecipChart) stationPrecipChart.resetZoom();
  if(stationPrecipDeviationChart) stationPrecipDeviationChart.resetZoom();
}

// ================= STATIONSREKORDE =================
const RECORD_PARAMETER_META={
  txk_high:{label:"Höchste Tagesmaxima",unit:"°C",direction:"desc"},
  tnk_low:{label:"Tiefste Tagesminima",unit:"°C",direction:"asc"},
  tnk_high:{label:"Höchste Tagestiefsttemperaturen",unit:"°C",direction:"desc"},
  rsk_high:{label:"Höchste Tagesniederschläge",unit:"mm",direction:"desc"}
};

function recordDateText(value){
  if(!value) return "–";
  const d=new Date(value+"T12:00:00");
  return d.toLocaleDateString("de-DE");
}

function recordNumber(value,unit){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return "–";
  return `${Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} ${unit}`;
}

function stationMeta(entry){
  return stationRecordsData?.stations?.[entry?.[2]] || {
    id:String(entry?.[2]||"").split(":",1)[0] || "–",
    name:"Unbekannte Station",state:null,height:null
  };
}

function ensureStationRecordsLoaded(){
  if(stationRecordsData){
    updateStationRecordTables();
    return Promise.resolve(stationRecordsData);
  }
  if(stationRecordsLoading) return stationRecordsLoading;
  const loading=document.getElementById("recordLoading");
  loading.textContent="Stationsrekorde werden geladen …";
  stationRecordsLoading=dashboardFetch("station_records.json",{cache:"no-store"})
    .then(response=>{if(!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();})
    .then(data=>{
      if(!data.ready) throw new Error(data.message || "Die Rekorddatei wurde noch nicht aufgebaut.");
      stationRecordsData=data;
      initializeStationRecordControls();
      loading.hidden=true;
      document.getElementById("recordContent").hidden=false;
      updateStationRecordTables();
      return data;
    })
    .catch(error=>{
      loading.textContent=`Stationsrekorde konnten nicht geladen werden: ${error.message}`;
      loading.style.color="#7a1010";
      throw error;
    });
  return stationRecordsLoading;
}

function fillSelect(select,items,valueKey="id",labelKey="label"){
  select.innerHTML="";
  items.forEach(item=>{
    const option=document.createElement("option");
    option.value=typeof item==="string"?item:item[valueKey];
    option.textContent=typeof item==="string"?item:item[labelKey];
    select.appendChild(option);
  });
}

function initializeStationRecordControls(){
  const parameters=stationRecordsData.parameters?.length
    ?stationRecordsData.parameters
    :Object.entries(RECORD_PARAMETER_META).map(([id,item])=>({id,label:item.label}));
  fillSelect(document.getElementById("recordParamSelect"),parameters);
  fillSelect(document.getElementById("newRecordParamSelect"),parameters);
  fillSelect(document.getElementById("recordAreaSelect"),stationRecordsData.areas || ["Deutschland"]);

  const periodSelect=document.getElementById("recordPeriodSelect");
  periodSelect.innerHTML="";
  const groups={all:"Gesamt",year:"Jahr",season:"Jahreszeiten",month:"Monate"};
  (stationRecordsData.periods||[]).forEach(period=>{
    const groupName=groups[period.kind]||"Zeitraum";
    let group=[...periodSelect.querySelectorAll("optgroup")].find(item=>item.label===groupName);
    if(!group){
      group=document.createElement("optgroup");
      group.label=groupName;
      periodSelect.appendChild(group);
    }
    const option=document.createElement("option");
    option.value=period.id;
    option.textContent=period.label;
    group.appendChild(option);
  });
  periodSelect.value="all";

  const years=[...(stationRecordsData.available_years||[])].sort((a,b)=>b-a);
  fillSelect(document.getElementById("recordYearSelect"),years.map(year=>String(year)));
  document.getElementById("newStationRecordsTitle").textContent=`Neue Stationsrekorde ${stationRecordsData.current_year}`;
  document.getElementById("recordSourceNote").textContent=stationRecordsData.source_note || "";

  ["recordParamSelect","recordAreaSelect","recordPeriodSelect","recordYearSelect","recordLimitSelect"]
    .forEach(id=>document.getElementById(id).addEventListener("change",updateStationRecordTables));
  document.getElementById("newRecordParamSelect").addEventListener("change",updateNewStationRecordTable);
}

async function selectedRecordEntries(){
  const parameter=document.getElementById("recordParamSelect").value;
  const area=document.getElementById("recordAreaSelect").value;
  const period=document.getElementById("recordPeriodSelect").value;
  const yearControl=document.getElementById("recordYearControl");
  yearControl.hidden=period!=="year";

  if(period==="year"){
    const year=document.getElementById("recordYearSelect").value;
    let yearData=stationYearCache.get(year);
    if(!yearData){
      const response=await dashboardFetch(`station_records_years/${year}.json`,{cache:"no-store"});
      if(!response.ok) throw new Error(`Jahresdatei ${year} konnte nicht geladen werden (HTTP ${response.status}).`);
      yearData=await response.json();
      stationYearCache.set(year,yearData);
    }
    return {entries:yearData.top_lists?.[parameter]?.[area] || [],parameter,area,period,year};
  }
  return {
    entries:stationRecordsData.top_lists?.[parameter]?.[area]?.[period] || [],
    parameter,area,period,year:null
  };
}

async function updateStationRecordTables(){
  if(!stationRecordsData) return;
  const tbody=document.querySelector("#stationRecordTable tbody");
  tbody.innerHTML='<tr><td colspan="8">Rekordliste wird geladen …</td></tr>';
  try{
    const selection=await selectedRecordEntries();
    const meta=RECORD_PARAMETER_META[selection.parameter];
    const limit=Number(document.getElementById("recordLimitSelect").value||50);
    const entries=selection.entries.slice(0,limit);
    const periodLabel=selection.period==="year"
      ?String(selection.year)
      :(stationRecordsData.periods||[]).find(item=>item.id===selection.period)?.label || selection.period;
    document.getElementById("recordSummary").textContent=
      `${meta.label} · ${selection.area} · ${periodLabel} · ${entries.length} Einträge. `+
      `Es werden einzelne Stationstage ausgewertet; eine Mindestlänge der Messreihe wird nicht verlangt.`;

    if(!entries.length){
      tbody.innerHTML='<tr><td colspan="8">Für diese Auswahl liegen keine Rekorde vor.</td></tr>';
    }else{
      tbody.innerHTML=entries.map((entry,index)=>{
        const station=stationMeta(entry);
        const preliminary=Boolean(entry[3]);
        return `<tr>
          <td>${index+1}</td>
          <td class="record-value">${recordNumber(entry[0],meta.unit)}</td>
          <td>${recordDateText(entry[1])}</td>
          <td class="record-station">${station.name||"–"}</td>
          <td>${station.id||"–"}</td>
          <td>${station.state||"–"}</td>
          <td>${station.height===null||station.height===undefined?"–":`${station.height} m`}</td>
          <td><span class="record-badge ${preliminary?"preliminary":"checked"}">${preliminary?"vorläufig":"historisch geprüft"}</span></td>
        </tr>`;
      }).join("");
    }
  }catch(error){
    tbody.innerHTML=`<tr><td colspan="8">${error.message}</td></tr>`;
    document.getElementById("recordSummary").textContent="Die gewählte Rekordliste konnte nicht geladen werden.";
  }
  updateNewStationRecordTable();
}

function updateNewStationRecordTable(){
  if(!stationRecordsData) return;
  const parameter=document.getElementById("newRecordParamSelect").value;
  const meta=RECORD_PARAMETER_META[parameter];
  const records=stationRecordsData.station_records_current_year?.[parameter] || [];
  const tbody=document.querySelector("#newStationRecordTable tbody");
  document.getElementById("newRecordSummary").textContent=
    records.length
      ?`${records.length} Stationen haben ${stationRecordsData.current_year} ihren bisherigen ${meta.label.toLowerCase()}-Rekord übertroffen.`
      :`Für ${stationRecordsData.current_year} wurde in dieser Kategorie noch kein neuer Stationsrekord erkannt.`;
  if(!records.length){
    tbody.innerHTML='<tr><td colspan="7">Keine neuen Stationsrekorde vorhanden.</td></tr>';
    return;
  }
  tbody.innerHTML=records.slice(0,200).map(item=>{
    const station=stationMeta(item.new);
    return `<tr>
      <td class="record-station">${station.name||"–"} (${station.id||item.station_id})</td>
      <td>${station.state||"–"}</td>
      <td class="record-value">${recordNumber(item.new[0],meta.unit)}</td>
      <td>${recordDateText(item.new[1])}</td>
      <td>${recordNumber(item.old[0],meta.unit)}</td>
      <td>${recordDateText(item.old[1])}</td>
      <td>${recordNumber(item.improvement,meta.unit)}</td>
    </tr>`;
  }).join("");
}


// ================= LÄNGSTE KENNTAGE-SERIEN =================
function ensureStationStreaksLoaded(){
  if(stationStreakIndex){
    updateStationStreakTable();
    return Promise.resolve(stationStreakIndex);
  }
  if(stationStreakLoading) return stationStreakLoading;
  const loading=document.getElementById("stationStreakLoading");
  if(!loading) return Promise.resolve(null);
  loading.hidden=false;
  loading.style.color="";
  loading.textContent="Kenntage-Serien werden geladen …";
  stationStreakLoading=dashboardFetch("station_climate_days_index.json",{cache:"no-store"})
    .then(response=>{if(!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();})
    .then(data=>{
      if(!data.ready) throw new Error(data.message || "Die Stations-Kenntage wurden noch nicht aufgebaut.");
      stationStreakIndex=data;
      initializeStationStreakControls();
      loading.hidden=true;
      document.getElementById("stationStreakContent").hidden=false;
      updateStationStreakTable();
      updateNationalStreakRecords();
      return data;
    })
    .catch(error=>{
      loading.textContent=`Kenntage-Serien konnten nicht geladen werden: ${error.message}`;
      loading.style.color="#7a1010";
      throw error;
    });
  return stationStreakLoading;
}

function initializeStationStreakControls(){
  const metricSelect=document.getElementById("streakMetricSelect");
  metricSelect.innerHTML="";
  (stationStreakIndex.climate_days||[]).forEach(metric=>{
    const option=document.createElement("option");
    option.value=metric.id;
    option.textContent=`${metric.label} · ${metric.definition}`;
    metricSelect.appendChild(option);
  });
  if((stationStreakIndex.climate_days||[]).some(item=>item.id==="hot")) metricSelect.value="hot";

  const areaSelect=document.getElementById("streakAreaSelect");
  areaSelect.innerHTML='<option value="Deutschland">Deutschland</option>';
  (stationStreakIndex.states||[]).forEach(state=>{
    const option=document.createElement("option");
    option.value=state;
    option.textContent=state;
    areaSelect.appendChild(option);
  });
  areaSelect.value="Deutschland";

  ["streakMetricSelect","streakAreaSelect","streakMinYearsSelect","streakLimitSelect"]
    .forEach(id=>document.getElementById(id)?.addEventListener("change",updateStationStreakTable));

  const nationalMetric=document.getElementById("nationalStreakMetricSelect");
  if(nationalMetric){
    nationalMetric.innerHTML="";
    (stationStreakIndex.climate_days||[]).forEach(metric=>{
      const option=document.createElement("option");
      option.value=metric.id;
      option.textContent=`${metric.label} · ${metric.definition}`;
      nationalMetric.appendChild(option);
    });
    if((stationStreakIndex.climate_days||[]).some(item=>item.id==="hot")) nationalMetric.value="hot";
    nationalMetric.addEventListener("change",updateNationalStreakRecords);
  }
  document.getElementById("nationalStreakMapToggle")?.addEventListener("change",updateNationalStreakRecords);
  document.getElementById("nationalStreakMapDownload")?.addEventListener("click",downloadNationalStreakMap);
  updateNationalStreakRecords();
}

function stationStreakDateText(iso){
  if(!iso) return "–";
  const day=new Date(`${iso}T12:00:00Z`);
  if(Number.isNaN(day.getTime())) return iso;
  return day.toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
}

function stationStreakStatus(run){
  if(run?.ongoing) return '<span class="record-badge preliminary">laufend · vorläufig</span>';
  if(run?.preliminary) return '<span class="record-badge preliminary">vorläufig</span>';
  return '<span class="record-badge checked">historisch geprüft</span>';
}

function stationStreakCrossesBoundary(run){
  if(!run?.start || !run?.end) return "";
  const start=String(run.start).slice(0,7);
  const end=String(run.end).slice(0,7);
  if(start===end) return "";
  const startYear=String(run.start).slice(0,4);
  const endYear=String(run.end).slice(0,4);
  return startYear===endYear?" · monatsübergreifend":" · jahresübergreifend";
}

function updateStationStreakTable(){
  if(!stationStreakIndex) return;
  const tbody=document.querySelector("#stationStreakTable tbody");
  if(!tbody) return;
  const metricId=document.getElementById("streakMetricSelect")?.value || "hot";
  const area=document.getElementById("streakAreaSelect")?.value || "Deutschland";
  const minYears=Number(document.getElementById("streakMinYearsSelect")?.value || 0);
  const limit=Number(document.getElementById("streakLimitSelect")?.value || 50);
  const metric=(stationStreakIndex.climate_days||[]).find(item=>item.id===metricId) || {label:metricId,definition:""};

  const candidates=(stationStreakIndex.stations||[])
    .filter(station=>area==="Deutschland" || station.state===area)
    .filter(station=>Number(station.history_years||0)>=minYears)
    .map(station=>({station,run:station.longest_runs?.[metricId]||null}))
    .filter(item=>item.run && Number(item.run.duration)>0)
    .sort((a,b)=>
      Number(b.run.duration)-Number(a.run.duration) ||
      String(a.run.start).localeCompare(String(b.run.start)) ||
      String(a.station.name||"").localeCompare(String(b.station.name||""),"de")
    );

  const rows=candidates.slice(0,limit);
  if(!candidates.length){
    tbody.innerHTML='<tr><td colspan="9">Noch keine Serienrekorde vorhanden. Nach dem ersten Daten-Neuaufbau erscheinen die längsten Folgen hier automatisch.</td></tr>';
    document.getElementById("stationStreakSummary").textContent=
      `${metric.label} · ${area}: Seriendaten sind im aktuellen Kenntage-Index noch nicht vorhanden.`;
  }else{
    const leader=candidates[0];
    document.getElementById("stationStreakSummary").innerHTML=
      `<strong>${metric.label}:</strong> längste Folge ${leader.run.duration} Tage an ${leader.station.name} `+
      `(${stationStreakDateText(leader.run.start)}–${stationStreakDateText(leader.run.end)}). `+
      `${candidates.length} Stationen erfüllen den Filter${minYears?` ≥ ${minYears} Messjahre`:""}.`;

    tbody.innerHTML=rows.map((item,index)=>{
      const station=item.station,run=item.run;
      const measurement=`${station.start_year??"–"}–${station.end_year??"–"} · ${station.history_years??"–"} J.`;
      return `<tr>
        <td>${index+1}</td>
        <td class="record-value"><strong>${Number(run.duration).toLocaleString("de-DE")}</strong> Tage${stationStreakCrossesBoundary(run)}</td>
        <td>${stationStreakDateText(run.start)}</td>
        <td>${stationStreakDateText(run.end)}</td>
        <td class="record-station">${station.name||"–"}</td>
        <td>${station.id||"–"}</td>
        <td>${station.state||"–"}</td>
        <td>${measurement}</td>
        <td>${stationStreakStatus(run)}</td>
      </tr>`;
    }).join("");
  }

  const rule=stationStreakIndex.streak_rule ||
    "Serien laufen über Monats- und Jahresgrenzen weiter. Fehlende relevante Tageswerte unterbrechen die Folge; der 29. Februar zählt als normaler Kalendertag.";
  document.getElementById("stationStreakNote").textContent=
    `${rule} Pro Station wird für die Rangliste nur die längste bekannte Folge des gewählten Kenntags verwendet. `+
    `Das laufende Jahr ist vorläufig.`;
}


function nationalStreakStation(stationId){
  return (stationStreakIndex?.stations||[]).find(station=>station.id===stationId) || null;
}

function updateNationalStreakRecords(){
  if(!stationStreakIndex) return;
  const metricId=document.getElementById("nationalStreakMetricSelect")?.value || "hot";
  const metric=(stationStreakIndex.climate_days||[]).find(item=>item.id===metricId) || {label:metricId,definition:"",color:"#b44"};
  const rows=(stationStreakIndex.national_streak_records?.[metricId]||[]).slice(0,20);
  const tbody=document.querySelector("#nationalStreakTable tbody");
  const summary=document.getElementById("nationalStreakSummary");
  const note=document.getElementById("nationalStreakNote");
  if(!tbody || !summary) return;

  if(!rows.length){
    tbody.innerHTML='<tr><td colspan="9">Die deutschlandweiten Top-20 sind im aktuellen Kenntage-Index noch nicht vorhanden. Nach dem ersten Neuaufbau mit dem aktualisierten Backend erscheinen sie automatisch.</td></tr>';
    summary.textContent=`${metric.label}: nationale Serienrekorde sind noch nicht aufgebaut.`;
  }else{
    const leader=rows[0],station=nationalStreakStation(leader.station_id);
    summary.innerHTML=`<strong>Deutschlandrekord · ${metric.label}:</strong> ${Number(leader.duration).toLocaleString("de-DE")} Tage in Folge an ${station?.name||leader.station_id} `+
      `(${stationStreakDateText(leader.start)}–${stationStreakDateText(leader.end)}). Top ${rows.length} einzelne Serien.`;
    tbody.innerHTML=rows.map((run,index)=>{
      const station=nationalStreakStation(run.station_id)||{};
      const measurement=`${station.start_year??"–"}–${station.end_year??"–"} · ${station.history_years??"–"} J.`;
      return `<tr>
        <td><strong>${index+1}</strong></td>
        <td class="record-value"><strong>${Number(run.duration).toLocaleString("de-DE")}</strong> Tage${stationStreakCrossesBoundary(run)}</td>
        <td>${stationStreakDateText(run.start)}</td>
        <td>${stationStreakDateText(run.end)}</td>
        <td class="record-station">${station.name||"–"}</td>
        <td>${station.id||run.station_id||"–"}</td>
        <td>${station.state||"–"}</td>
        <td>${measurement}</td>
        <td>${stationStreakStatus(run)}</td>
      </tr>`;
    }).join("");
  }

  if(note){
    note.textContent=(stationStreakIndex.national_streak_scope||"Deutschlandweite Top-20 über das erfasste Kenntage-Stationsnetz.")+" "+
      (stationStreakIndex.streak_rule||"");
  }
  const mapTitle=document.getElementById("nationalStreakMapTitle");
  const mapSubtitle=document.getElementById("nationalStreakMapSubtitle");
  if(mapTitle) mapTitle.textContent=`Deutschlandweite Serienrekorde · ${metric.label}`;
  if(mapSubtitle) mapSubtitle.textContent=`Top ${rows.length||20} · ${metric.definition||""} · Datenstand ${stationStreakIndex.data_through||"–"}`;
  updateNationalStreakMap(rows,metric);
}

function updateNationalStreakMap(rows,metric){
  const wrap=document.getElementById("nationalStreakMapWrap");
  const show=document.getElementById("nationalStreakMapToggle")?.value!=="hide";
  if(!wrap) return;
  wrap.hidden=!show;
  if(!show) return;
  const mapElement=document.getElementById("nationalStreakMap");
  if(!mapElement || typeof L==="undefined") return;
  if(!nationalStreakMap){
    nationalStreakMap=L.map(mapElement,{zoomControl:true,scrollWheelZoom:true}).setView([51.15,10.35],6);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{
      maxZoom:18,attribution:'&copy; OpenStreetMap-Mitwirkende',crossOrigin:true
    }).addTo(nationalStreakMap);
    nationalStreakMapLayer=L.layerGroup().addTo(nationalStreakMap);
  }
  nationalStreakMapLayer.clearLayers();

  const grouped=new Map();
  rows.forEach((run,index)=>{
    const station=nationalStreakStation(run.station_id);
    if(!station || !Number.isFinite(Number(station.latitude)) || !Number.isFinite(Number(station.longitude))) return;
    const key=station.id;
    if(!grouped.has(key)) grouped.set(key,{station,runs:[]});
    grouped.get(key).runs.push({run,rank:index+1});
  });
  const bounds=[];
  grouped.forEach(({station,runs})=>{
    const bestRank=Math.min(...runs.map(item=>item.rank));
    const radius=bestRank===1?11:bestRank<=3?9:bestRank<=10?7:6;
    const marker=L.circleMarker([Number(station.latitude),Number(station.longitude)],{
      radius,weight:2,color:"#ffffff",fillColor:metric.color||"#b23a2a",fillOpacity:.9
    });
    const recordLines=runs.map(({run,rank})=>
      `<div><strong>#${rank}</strong> · ${run.duration} Tage · ${stationStreakDateText(run.start)}–${stationStreakDateText(run.end)}</div>`
    ).join("");
    marker.bindPopup(`<strong>${station.name}</strong><br>${station.state||""}<br><span style="font-size:12px">${metric.label}</span><hr style="margin:6px 0">${recordLines}`);
    marker.bindTooltip(`#${bestRank} · ${station.name}: ${runs[0].run.duration} Tage`,{direction:"top"});
    marker.addTo(nationalStreakMapLayer);
    bounds.push([Number(station.latitude),Number(station.longitude)]);
  });
  if(bounds.length){
    nationalStreakMap.fitBounds(bounds,{padding:[24,24],maxZoom:7});
  }else{
    nationalStreakMap.setView([51.15,10.35],6);
  }
  setTimeout(()=>nationalStreakMap?.invalidateSize(),50);
}

async function downloadNationalStreakMap(){
  const mapElement=document.getElementById("nationalStreakMapWrap");
  const button=document.getElementById("nationalStreakMapDownload");
  if(!mapElement || mapElement.hidden) return;
  if(typeof html2canvas!=="function"){
    alert("Die Exportbibliothek konnte nicht geladen werden.");
    return;
  }
  const metricId=document.getElementById("nationalStreakMetricSelect")?.value || "hot";
  const metric=(stationStreakIndex?.climate_days||[]).find(item=>item.id===metricId) || {label:metricId};
  const oldText=button?.textContent;
  if(button){button.disabled=true;button.textContent="Export …";}
  const controls=mapElement.querySelectorAll(".leaflet-control-container");
  const oldDisplays=[...controls].map(node=>node.style.display);
  try{
    controls.forEach(node=>{node.style.display="none";});
    nationalStreakMap?.invalidateSize();
    await new Promise(resolve=>setTimeout(resolve,180));
    const canvas=await window.captureDashboardWithWhiteBackground(mapElement,{scale:3,backgroundColor:"#ffffff",useCORS:true,logging:false});
    if(!window.DashboardExportHQ)throw new Error("Die hochauflösende Exportbibliothek wurde nicht geladen.");
    const labeled=window.DashboardExportHQ.composeCanvas(canvas,{
      title:"Deutschland · "+metric.label+" · Stationsrekorde",
      source:"Quelle: DWD CDC · Stationsauswertung · Kartenbasis: OpenStreetMap"
    });
    const link=document.createElement("a");
    link.download=`kenntage_serienrekorde_${metricId}_deutschland.png`;
    link.href=labeled.toDataURL("image/png");
    link.click();
  }catch(error){
    alert(`Kartenexport fehlgeschlagen: ${error.message}`);
  }finally{
    if(button){button.disabled=false;button.textContent=oldText||"Karte als PNG";}
  }
}



