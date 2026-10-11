let era5AtmosIndex=null;
let era5AtmosPayload=null;
let era5AtmosLoaded=false;

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
  const response=await fetch(`era5_europe/archive/${period}/index.json?ts=${Date.now()}`,{cache:"no-store"});
  if(!response.ok)throw new Error(`ERA5-Archiv ${period}: HTTP ${response.status}`);
  era5AtmosPayload=await response.json();
}

function era5AtmosFillControls(){
  const periodSelect=document.getElementById("era5AtmosPeriod");
  const parameterSelect=document.getElementById("era5AtmosParameter");
  if(periodSelect){
    const previous=periodSelect.value;
    periodSelect.innerHTML="";
    [...(era5AtmosIndex?.available_periods||[])].reverse().forEach(period=>{
      const option=document.createElement("option");
      option.value=period;
      const [year,month]=period.split("-");
      option.textContent=`${month}.${year}`;
      periodSelect.appendChild(option);
    });
    periodSelect.value=[...periodSelect.options].some(o=>o.value===previous)?previous:era5AtmosIndex.latest_month_key;
  }
  if(parameterSelect){
    const previous=parameterSelect.value;
    parameterSelect.innerHTML="";
    Object.entries(era5AtmosIndex?.products||{}).forEach(([key,item])=>{
      const option=document.createElement("option");
      option.value=key;
      option.textContent=item.short_label||item.label||key;
      parameterSelect.appendChild(option);
    });
    if([...parameterSelect.options].some(o=>o.value===previous))parameterSelect.value=previous;
  }
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
  if(!item)return;
  const viewItem=item[view];
  const period=era5AtmosPayload.latest_month_key||era5AtmosPayload.period||"";
  const label=era5AtmosPayload.label||period;

  const viewLabels={absolute:"Absolutwert",anomaly:"Abweichung 1991–2020",rank:"historischer Rang"};
  if(title)title.textContent=`${item.label} · ${viewLabels[view]||view}`;
  if(subtitle)subtitle.textContent=`${label} · ERA5 ${item.level_hpa?item.level_hpa+" hPa":"Single Level"}`;

  if(viewItem?.file){
    if(image){
      image.hidden=false;
      image.src=`${viewItem.file}?ts=${encodeURIComponent(era5AtmosIndex?.generated_at||Date.now())}`;
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
  set("era5AtmosAnomaly",era5AtmosFormat(stats.anomaly_area_mean,key==="t850"?"K":unit,true,key==="z500"?0:1),"Abweichung des Europa-Flächenmittels");
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
    era5AtmosPayload=era5AtmosIndex;
    era5AtmosFillControls();
    document.getElementById("era5AtmosPeriod")?.addEventListener("change",era5AtmosChangePeriod);
    document.getElementById("era5AtmosParameter")?.addEventListener("change",era5AtmosRender);
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
