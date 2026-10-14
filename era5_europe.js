let era5AtmosIndex=null;
let era5AtmosPayload=null;
let era5AtmosLoaded=false;
const era5AtmosHistoryCache=new Map();
const era5AtmosExtraHistoryCache=new Map();
let era5AtmosExtraIndex=null;
let era5AtmosClimateIndex=null;
const era5AtmosClimateHistoryCache=new Map();

function era5AtmosFormat(value,unit="",signed=false,digits=1){
  const number=Number(value);
  if(!Number.isFinite(number))return "–";
  const sign=signed&&number>0?"+":"";
  const text=number.toLocaleString("de-DE",{minimumFractionDigits:digits,maximumFractionDigits:digits});
  return `${sign}${text}${unit?" "+unit:""}`;
}

function era5AtmosProductMeta(){
  const select=document.getElementById("era5AtmosParameter");
  const key=select?.value||Object.keys(era5AtmosPayload?.products||{})[0];
  return [key,era5AtmosPayload?.products?.[key]||null];
}

function era5AtmosView(){
  return document.getElementById("era5AtmosView")?.value||"anomaly";
}

async function era5AtmosLoadPeriod(period){
  if(!era5AtmosIndex)throw new Error("ERA5-Index ist noch nicht geladen.");
  if(period===era5AtmosIndex.latest_month_key){
    era5AtmosPayload=era5AtmosIndex;
    return;
  }
  const year=Number(period.slice(0,4));
  const historicalYears=era5AtmosIndex.history_years||[];
  const hasHistorical=historicalYears.includes(year)||
    (era5AtmosExtraIndex?.available_periods||[]).includes(period);
  if(hasHistorical){
    let manifest=era5AtmosHistoryCache.get(year);
    if(!manifest){
      const url=`era5_europe/history/${year}.json?ts=${Date.now()}`;
      const response=await fetch(url,{cache:"no-store"});
      if(!response.ok)throw new Error(`ERA5-Historie ${year}: HTTP ${response.status}`);
      manifest=await response.json();
      if(manifest.year!==year || !manifest.ready)throw new Error(`ERA5-Historienmanifest ungültig: ${year}`);
      era5AtmosHistoryCache.set(year,manifest);
    }
    era5AtmosPayload=manifest.periods?.[period];
    if(!era5AtmosPayload?.ready)throw new Error(`ERA5-Historienmonat fehlt: ${period}`);
    return;
  }
  const response=await fetch(`era5_europe/archive/${period}/index.json?ts=${Date.now()}`,{cache:"no-store"});
  if(!response.ok)throw new Error(`ERA5-Archiv ${period}: HTTP ${response.status}`);
  era5AtmosPayload=await response.json();
}

function era5AtmosAvailablePeriods(){
  const recent=era5AtmosIndex?.available_periods||[];
  const extra=era5AtmosExtraIndex?.available_periods||[];
  const currentExtra=era5AtmosExtraIndex?.current_periods||[];
  const climate=era5AtmosClimateIndex?.available_periods||[];
  const historical=(era5AtmosIndex?.history_years||[])
    .flatMap(year=>Array.from({length:12},(_,month)=>`${year}-${String(month+1).padStart(2,"0")}`));
  return [...new Set([...historical,...extra,...currentExtra,...climate,...recent])].sort();
}

function era5AtmosFillMonths(preferred){
  const periodSelect=document.getElementById("era5AtmosPeriod");
  const yearSelect=document.getElementById("era5AtmosYear");
  if(!periodSelect)return;
  const year=yearSelect?.value||era5AtmosIndex?.latest_month_key?.slice(0,4);
  const available=era5AtmosAvailablePeriods().filter(period=>period.startsWith(year+"-"));
  periodSelect.innerHTML="";
  available.reverse().forEach(period=>{
    const option=document.createElement("option");
    option.value=period;
    const [y,month]=period.split("-");
    const monthNames=["Januar","Februar","März","April","Mai","Juni",
      "Juli","August","September","Oktober","November","Dezember"];
    option.textContent=monthNames[Number(month)-1]||period;
    periodSelect.appendChild(option);
  });
  if(available.includes(preferred))periodSelect.value=preferred;
  else if(available.includes(era5AtmosIndex?.latest_month_key))periodSelect.value=era5AtmosIndex.latest_month_key;
}

function era5AtmosFillParameters(){
  const select=document.getElementById("era5AtmosParameter");
  if(!select)return;
  const previous=select.value;
  select.replaceChildren();
  const appendGroup=(title,products,extra=false)=>{
    if(!products||!Object.keys(products).length)return;
    const group=document.createElement("optgroup");
    group.label=title;
    Object.entries(products).forEach(([key,item])=>{
      const option=document.createElement("option");
      option.value=key;
      option.textContent=`${item.short_label||key} · ${item.label||key}`;
      if(extra)option.dataset.historicalOnly="true";
      group.appendChild(option);
    });
    select.appendChild(group);
  };
  appendGroup("Basisparameter",era5AtmosIndex?.products);
  appendGroup("Neue Druckniveau- und Dynamikparameter",era5AtmosExtraIndex?.products,true);
  appendGroup("Klimatologische Monatskarten · Ausbau",era5AtmosClimateIndex?.products,true);
  if([...select.options].some(o=>o.value===previous))select.value=previous;
  else if(era5AtmosIndex?.products?.t850)select.value="t850";
}

async function era5AtmosChangeParameter(){
  era5AtmosRender();
}

async function era5AtmosAttachExtra(period){
  if(![...(era5AtmosExtraIndex?.available_periods||[]),
    ...(era5AtmosExtraIndex?.current_periods||[])].includes(period))return;
  const year=Number(period.slice(0,4));
  if(year>2025){
    const response=await fetch(`era5_europe/extra/current/${period}.json?ts=${Date.now()}`,{cache:"no-store"});
    if(!response.ok)throw new Error(`ERA5-Zusatzparameter ${period}: HTTP ${response.status}`);
    const item=await response.json();
    if(!item.ready||item.period!==period)throw new Error(`ERA5-Zusatzparameter ${period} sind noch nicht veröffentlicht`);
    era5AtmosPayload={...era5AtmosPayload,products:{
      ...era5AtmosPayload?.products,...item.products
    }};
    return;
  }
  let manifest=era5AtmosExtraHistoryCache.get(year);
  if(!manifest){
    const response=await fetch(`era5_europe/extra/history/${year}.json?ts=${Date.now()}`,{cache:"no-store"});
    if(!response.ok)throw new Error(`ERA5-Erweiterung ${year}: HTTP ${response.status}`);
    manifest=await response.json();
    if(!manifest?.ready || manifest.year!==year)throw new Error("ERA5-Erweiterungsarchiv ungültig");
    era5AtmosExtraHistoryCache.set(year,manifest);
  }
  const entry=manifest.periods?.[period];
  if(!entry?.ready || !entry.products)return;
  era5AtmosPayload={...era5AtmosPayload,products:{
    ...era5AtmosPayload?.products,...entry.products
  }};
}

async function era5AtmosAttachClimatology(period){
  if(!era5AtmosClimateIndex?.available_periods?.includes(period))return;
  const year=Number(period.slice(0,4));
  let entry;
  if(year<=2025){
    let manifest=era5AtmosClimateHistoryCache.get(year);
    if(!manifest){
      const response=await fetch(`era5_europe/climatology/history/${year}.json?ts=${Date.now()}`,{cache:"no-store"});
      if(!response.ok)throw new Error(`ERA5-Klimaarchiv ${year}: HTTP ${response.status}`);
      manifest=await response.json();
      if(!manifest.ready||manifest.year!==year)throw new Error("ERA5-Klimaarchiv ungültig");
      era5AtmosClimateHistoryCache.set(year,manifest);
    }
    entry=manifest.periods?.[period];
  }else{
    const response=await fetch(`era5_europe/climatology/current/${period}.json?ts=${Date.now()}`,{cache:"no-store"});
    if(!response.ok)throw new Error(`ERA5-Klimakarte ${period}: HTTP ${response.status}`);
    entry=await response.json();
  }
  if(!entry?.ready||entry.period!==period)return;
  era5AtmosPayload={...era5AtmosPayload,products:{
    ...era5AtmosPayload?.products,...entry.products
  }};
}

function era5AtmosFillControls(){
  const yearSelect=document.getElementById("era5AtmosYear");
  const periods=era5AtmosAvailablePeriods();
  if(yearSelect){
    const previous=yearSelect.value;
    const years=[...new Set(periods.map(period=>period.slice(0,4)))].reverse();
    yearSelect.innerHTML="";
    years.forEach(year=>{
      const option=document.createElement("option");
      option.value=year;
      option.textContent=year;
      yearSelect.appendChild(option);
    });
    yearSelect.value=years.includes(previous)?previous:era5AtmosIndex.latest_month_key.slice(0,4);
  }
  era5AtmosFillMonths(era5AtmosIndex.latest_month_key);
  era5AtmosFillParameters();
}

async function era5AtmosChangeYear(){
  era5AtmosFillMonths();
  await era5AtmosChangePeriod();
}

function era5AtmosRender(){
  const status=document.getElementById("era5AtmosStatus");
  const image=document.getElementById("era5AtmosImage");
  const placeholder=document.getElementById("era5AtmosPlaceholder");
  const title=document.getElementById("era5AtmosTitle");
  const subtitle=document.getElementById("era5AtmosSubtitle");
  if(!era5AtmosPayload)return;

  const [key,item]=era5AtmosProductMeta();
  const view=era5AtmosView();
  if(!item){
    const text="Für diesen Parameter und Monat sind noch keine ERA5-Karten veröffentlicht.";
    if(image)image.hidden=true;
    if(placeholder){placeholder.hidden=false;placeholder.textContent=text;}
    if(title)title.textContent="Historischer ERA5-Zusatzparameter";
    if(subtitle)subtitle.textContent="ERA5-Monatsarchiv";
    for(const id of ["era5AtmosCurrent","era5AtmosReference","era5AtmosAnomaly","era5AtmosRank1","era5AtmosTop3"]){
      const node=document.getElementById(id);
      if(node)node.textContent="–";
    }
    if(status)status.textContent=text;
    return;
  }
  const viewItem=item[view];
  const period=era5AtmosPayload.latest_month_key||era5AtmosPayload.period||"";
  const label=era5AtmosPayload.label||period;

  const viewLabels={absolute:"Absolutwert",anomaly:"Abweichung 1991–2020",rank:"historischer Rang"};
  if(title)title.textContent=`${item.label} · ${viewLabels[view]||view}`;
  if(subtitle)subtitle.textContent=`${label} · ERA5 ${item.level_hpa?item.level_hpa+" hPa":"Single Level"}`;

  if(viewItem?.file){
    if(image){
      const tiled=Number.isInteger(viewItem.tile_index);
      image.closest(".era5-atmos-image-wrap")?.classList.toggle("tiled",tiled);
      image.style.transform=tiled?`translateX(-${(viewItem.tile_index*100/3).toFixed(6)}%)`:"";
      image.hidden=false;
      const url=viewItem.file;
      image.src=`${url}${url.includes("?")?"&":"?"}ts=${encodeURIComponent(era5AtmosIndex?.generated_at||Date.now())}`;
      image.alt=`${item.label} ${viewLabels[view]||view} ${label}`;
    }
    if(placeholder)placeholder.hidden=true;
  }else{
    if(image)image.hidden=true;
    if(placeholder){placeholder.hidden=false;placeholder.textContent="Für diese Auswahl ist noch keine Karte verfügbar.";}
  }

  const unit=item.unit||"";
  const stats=item.stats||{};
  const rank=item.rank||{};
  const set=(id,value,detail="")=>{
    const el=document.getElementById(id);
    if(el)el.textContent=value;
    const d=document.getElementById(id+"Detail");
    if(d)d.textContent=detail;
  };
  set("era5AtmosCurrent",era5AtmosFormat(stats.current_area_mean,unit,false,key==="z500"?0:1),"Europa-Flächenmittel");
  set("era5AtmosReference",era5AtmosFormat(stats.reference_area_mean,unit,false,key==="z500"?0:1),"Mittel 1991–2020");
  set("era5AtmosAnomaly",era5AtmosFormat(stats.anomaly_area_mean,item.anomaly?.unit||(key==="t850"?"K":unit),true,key==="z500"?0:1),"Abweichung des Europa-Flächenmittels");
  set("era5AtmosRank1",Number.isFinite(rank.rank1_area_percent)?era5AtmosFormat(rank.rank1_area_percent,"%",false,1):"–",rank.direction||"");
  set("era5AtmosTop3",Number.isFinite(rank.top3_area_percent)?era5AtmosFormat(rank.top3_area_percent,"%",false,1):"–",`Top-3-Flächenanteil · Rang 1–${rank.total_rank_positions||"–"}`);

  if(status){
    status.classList.remove("error");
    status.textContent=`${label} · ERA5 0,25° · Historie ab ${era5AtmosIndex.history_start||1940} · Referenz ${era5AtmosIndex.reference_period||"1991–2020"}`;
  }
}

async function era5AtmosChangePeriod(){
  const status=document.getElementById("era5AtmosStatus");
  try{
    if(status)status.textContent="ERA5-Archiv wird geladen …";
    const period=document.getElementById("era5AtmosPeriod")?.value||era5AtmosIndex?.latest_month_key;
    await era5AtmosLoadPeriod(period);
    await era5AtmosAttachExtra(period);
    await era5AtmosAttachClimatology(period);
    era5AtmosFillParameters();
    era5AtmosRender();
  }catch(error){
    console.error("ERA5 Atmosphäre:",error);
    if(status){status.classList.add("error");status.textContent=`ERA5-Daten konnten nicht geladen werden: ${error.message}`;}
  }
}

async function ensureEra5AtmosphereLoaded(){
  if(era5AtmosLoaded){
    era5AtmosRender();
    return;
  }
  const status=document.getElementById("era5AtmosStatus");
  try{
    if(status)status.textContent="ERA5-Atmosphärendaten werden geladen …";
    const response=await fetch(`era5_europe/index.json?ts=${Date.now()}`,{cache:"no-store"});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    era5AtmosIndex=await response.json();
    if(!era5AtmosIndex?.ready)throw new Error("ERA5-Index ist noch nicht bereit.");
    try{
      const extra=await fetch(`era5_europe/extra/index.json?ts=${Date.now()}`,{cache:"no-store"});
      if(extra.ok){
        const data=await extra.json();
        if(data.ready)era5AtmosExtraIndex=data;
      }
    }catch(error){console.info("ERA5-Erweiterung noch nicht verfügbar",error);}
    try{
      const climate=await fetch(`era5_europe/climatology/index.json?ts=${Date.now()}`,{cache:"no-store"});
      if(climate.ok){
        const data=await climate.json();
        if(data.ready)era5AtmosClimateIndex=data;
      }
    }catch(error){console.info("ERA5-Klimamodule noch nicht verfügbar",error);}
    era5AtmosPayload=era5AtmosIndex;
    era5AtmosFillControls();
    const parameterControl=document.getElementById("era5AtmosParameter")?.closest(".control-group");
    if(parameterControl&&era5AtmosExtraIndex?.completed===era5AtmosExtraIndex?.expected){
      const info=document.createElement("small");
      info.className="era5-atmos-archive-hint";
      info.textContent="10 Basis- und Zusatzparameter · Klimamonatskarten im Ausbau";
      parameterControl.appendChild(info);
    }
    document.getElementById("era5AtmosYear")?.addEventListener("change",era5AtmosChangeYear);
    document.getElementById("era5AtmosPeriod")?.addEventListener("change",era5AtmosChangePeriod);
    document.getElementById("era5AtmosImage")?.addEventListener("error",()=>{
      const img=document.getElementById("era5AtmosImage");
      const placeholder=document.getElementById("era5AtmosPlaceholder");
      if(img)img.hidden=true;
      if(placeholder){
        placeholder.hidden=false;
        placeholder.textContent="Diese historische Karte konnte nicht geladen werden. Bitte prüfe die Release-Datei.";
      }
    });
    document.getElementById("era5AtmosParameter")?.addEventListener("change",era5AtmosChangeParameter);
    document.getElementById("era5AtmosView")?.addEventListener("change",era5AtmosRender);
    era5AtmosLoaded=true;
    era5AtmosRender();
  }catch(error){
    console.error("ERA5 Atmosphäre:",error);
    if(status){
      status.classList.add("error");
      status.textContent=`ERA5-Atmosphärenmodul ist noch nicht verfügbar: ${error.message}`;
    }
  }
}


/* ERA5_STRATOSPHERE_MODULE_V1 */
/* Optional and isolated: loading the stratosphere module never blocks ERA5 maps. */
(function(){
  if(document.querySelector('script[data-era5-stratosphere]'))return;
  const el=document.createElement('script');
  el.src='era5_stratosphere.js?v=1';
  el.async=true;
  el.setAttribute('data-era5-stratosphere','1');
  document.head.appendChild(el);
})();
