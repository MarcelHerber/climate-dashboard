/* era5-land.js – ERA5-Land Europa (Karten, Rankings, Gitterpunktanalyse, laufende Ränge)
   Aus index.html ausgelagert (Schritt 5). Klassisches Skript, gemeinsamer globaler Scope. */
// ================= ERA5-LAND EUROPA · V8.1 =================
function era5EuropeFormat(value,decimals=1,suffix=""){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return "–";
  return `${Number(value).toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals})}${suffix}`;
}
function era5EuropeSetStatus(text,state=""){
  const el=document.getElementById("era5EuropeStatus");if(!el)return;
  el.textContent=text;el.className=`era5-europe-status ${state}`.trim();
}
function era5EuropeSoilLayerLabel(layer){
  const fallback={layer1:"0–7 cm",layer2:"7–28 cm",layer3:"28–100 cm",layer4:"100–289 cm"};
  return era5EuropeIndex?.soil_layers?.[layer]?.label||fallback[layer]||layer;
}
function era5EuropeUpdateSoilLayerVisibility(){
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const group=document.getElementById("era5EuropeSoilLayerGroup");
  if(group)group.style.display=parameter==="soil_moisture"?"":"none";
}
// ERA5_TEMPERATURE_RANK_FRONTEND_V1
function era5EuropeUpdateViewOptions(){
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const select=document.getElementById("era5EuropeView");if(!select)return;
  const previous=select.value;let entries;
  const mapYear=document.getElementById("era5EuropeMapYear"),periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";
  const rankReady=parameter==="temperature"&&mapYear?.value==="current"&&Boolean(era5EuropeIndex?.periods?.[periodId]?.temperature?.rank);
  if(parameter==="temperature"){entries=[["absolute","Absolutwert (°C)"],["anomaly","Abweichung 1991–2020 (K)"]];if(rankReady)entries.push(["rank","Historischer Rang seit 1950"]);}
  else if(parameter==="precipitation") entries=[["absolute","Niederschlagssumme (mm)"],["percent","Prozent vom Mittel 1991–2020"]];
  else if(parameter==="soil_moisture") entries=[["absolute","Bodenfeuchte (m³/m³)"],["anomaly","Abweichung 1991–2020 (m³/m³)"],["percentile","Perzentil / Dürreklasse 1991–2020"]];
  else if(parameter==="snow_depth") entries=[["absolute","Schneehöhe (cm)"],["anomaly","Abweichung 1991–2020 (cm)"],["percentile","Perzentil 1991–2020"]];
  else if(parameter==="snow_water_equivalent") entries=[["absolute","Schneewasseräquivalent (mm)"],["anomaly","Abweichung 1991–2020 (mm)"],["percentile","Perzentil 1991–2020"]];
  else if(parameter==="snow_cover") entries=[["absolute","Schneebedeckung (%)"],["anomaly","Abweichung 1991–2020 (Prozentpunkte)"],["percentile","Perzentil 1991–2020"]];
  else entries=[["absolute","Absolutwert (mm)"],["anomaly","Abweichung 1991–2020 (mm)"],["percentile","Perzentil 1991–2020"]];
  select.innerHTML=entries.map(([value,label])=>`<option value="${value}">${label}</option>`).join("");
  if(entries.some(([value])=>value===previous))select.value=previous;
  else select.value=parameter==="precipitation"?"percent":parameter==="soil_moisture"?"percentile":"anomaly";
}

// ERA5_TP_ALL_MONTHS_FRONTEND_V1
// ERA5_RUNNING_FRONTEND_V2
function era5EuropeUpdatePeriodOptions(){
  const select=document.getElementById("era5EuropePeriod");if(!select)return;
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const previous=select.value||"latest_month";
  const latest=era5EuropeIndex?.periods?.latest_month;
  const summer=era5EuropeIndex?.periods?.summer;
  const runningMonth=era5EuropeIndex?.periods?.running_month;
  const runningSeasonIds=["running_spring","running_summer","running_autumn","running_winter"];
  const runningSeasonId=runningSeasonIds.find(id=>era5EuropeIndex?.periods?.[id]);
  const runningSeason=runningSeasonId?era5EuropeIndex.periods[runningSeasonId]:null;
  const tp=parameter==="temperature"||parameter==="precipitation";
  let html='<optgroup label="Aktuell / Saison">';
  if(tp&&runningMonth)html+=`<option value="running_month">${runningMonth.label||"Laufender Monat"}</option>`;
  if(tp&&runningSeason)html+=`<option value="${runningSeasonId}">${runningSeason.label||"Laufende Saison"}</option>`;
  html+=`<option value="latest_month">${latest?.label||"Jüngster vollständiger Monat"}</option>`+
        `<option value="summer">${summer?.label||"Sommer (JJA)"}</option>`+
        '</optgroup>';
  const monthNumbers=(era5EuropeIndex?.history_map?.temperature_precipitation_months||[]).map(Number).filter(m=>m>=1&&m<=12);
  if(tp&&monthNumbers.length){
    const options=monthNumbers.map(month=>{const id=`month_${String(month).padStart(2,"0")}`,p=era5EuropeIndex?.periods?.[id];return `<option value="${id}">${p?.label||id}</option>`;}).join("");
    html+=`<optgroup label="Monate · aktuell + Historie 1950–${era5EuropeIndex?.history_map?.year_end||""}">${options}</optgroup>`;
  }
  select.innerHTML=html;
  if([...select.options].some(o=>o.value===previous))select.value=previous;
  else if(tp&&runningMonth)select.value="running_month";
  else select.value="latest_month";
}
function era5EuropePeriodIsHistoricalOnly(periodId){return Boolean(era5EuropeIndex?.periods?.[periodId]?.historical_only);}
function era5EuropeHighresSampleEntries(field,maxSamples=40000){
  const values=field?.values||[];if(!values.length)return [];
  const step=Math.max(1,Math.floor(values.length/maxSamples)),rows=[];
  for(let i=0;i<values.length;i+=step){const value=Number(values[i]);if(Number.isFinite(value))rows.push({value});}
  return rows;
}
function era5EuropeHighresWeightedMean(field){
  if(!field?.values||!field.nlat||!field.nlon)return null;
  let sum=0,weights=0;const nlat=Number(field.nlat),nlon=Number(field.nlon),latStart=Number(field.latStart),latStep=Number(field.latStep);
  for(let y=0;y<nlat;y++){
    const lat=latStart+y*latStep,w=Math.max(.01,Math.cos(lat*Math.PI/180)),row=y*nlon;
    for(let x=0;x<nlon;x++){const value=Number(field.values[row+x]);if(Number.isFinite(value)){sum+=value*w;weights+=w;}}
  }
  return weights?sum/weights:null;
}
// ERA5_PERIOD_YEAR_LABEL_FIX_V1
function era5EuropePeriodDisplayLabel(period,year){
  const raw=String(period?.label||"Zeitraum").trim();
  const y=Number(year);
  if(!Number.isFinite(y))return raw;
  const periodYear=Number(period?.year);
  if(Number.isFinite(periodYear)){
    const re=new RegExp(`\\b${periodYear}\\b`,'g');
    if(re.test(raw))return raw.replace(re,String(y));
  }
  const months=(period?.months||[]).map(Number).filter(Number.isFinite);
  if(months.length===1)return `${raw.replace(/\\s+(?:19|20)\\d{2}\\s*$/,'').trim()} ${y}`;
  return raw;
}
function era5EuropeSyncPeriodOptionLabels(){
  const select=document.getElementById("era5EuropePeriod");if(!select||!era5EuropeIndex)return;
  const selectedYear=era5EuropeMapYear();
  for(const option of select.options){
    if(!String(option.value||"").startsWith("month_"))continue;
    const period=era5EuropeIndex?.periods?.[option.value];if(!period)continue;
    const year=Number.isFinite(selectedYear)?selectedYear:Number(period?.year);
    option.textContent=era5EuropePeriodDisplayLabel(period,year);
  }
}
function era5EuropeShowMonthlyRankingPending(meta,period,year){
  const panel=document.getElementById("era5EuropeRanking");if(!panel)return;
  document.getElementById("era5EuropeRankingTitle").textContent=`${meta.label} · ${era5EuropePeriodDisplayLabel(period,year)}`;
  document.getElementById("era5EuropeRankingSubtitle").textContent="0,1°-Monatskarte verfügbar · 1,0°-Rankings und Gitterpunkt-Zeitreihen werden in einer späteren Stufe ergänzt.";
  for(const id of ["era5EuropeRankingMax","era5EuropeRankingMin","era5EuropeRankingHighRecords","era5EuropeRankingLowRecords","era5EuropeRankingMaxDetail","era5EuropeRankingMinDetail"]){const el=document.getElementById(id);if(el)el.textContent="–";}
  const top=document.getElementById("era5EuropeRankingTop"),bottom=document.getElementById("era5EuropeRankingBottom");
  if(top)top.innerHTML='<div class="era5-europe-loading">Für das neue Monatsarchiv ist in dieser Stufe zunächst nur die hochaufgelöste Karte aktiv.</div>';
  if(bottom)bottom.innerHTML='';
  const foot=document.getElementById("era5EuropeRankingFoot");if(foot)foot.textContent="Temperatur und Niederschlag sind bereits vollständig als Monatskarten vorhanden; Rankings werden separat nachgezogen.";
  era5EuropeRankingPoints=[];era5EuropeRenderRankingMarkers();clearEra5EuropePoint();
}

function era5EuropeUpdateMapYearOptions(){
  const select=document.getElementById("era5EuropeMapYear");if(!select)return;
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";
  const period=era5EuropeIndex?.periods?.[periodId]||{};
  const historicalOnly=Boolean(period.historical_only);
  const runningOnly=Boolean(period.running_only);
  const previous=select.value||"current";
  const currentYear=Number(period.year||era5EuropeIndex?.history_map?.year_end||new Date().getFullYear());
  const start=parameter==="soil_moisture"?Number(era5EuropeIndex?.history_map?.soil_year_start||1991):Number(era5EuropeIndex?.history_map?.year_start||1950);
  const end=parameter==="soil_moisture"?Number(era5EuropeIndex?.history_map?.soil_year_end||2020):Number(era5EuropeIndex?.history_map?.year_end||currentYear-1);
  const years=[];for(let y=end;y>=start;y--)years.push(y);
  if(runningOnly){select.innerHTML='<option value="current">Laufender Datenstand</option>';select.value="current";return;}
  select.innerHTML=(historicalOnly?'':'<option value="current">Aktueller Datenstand · 0,1°</option>')+
    years.filter(y=>historicalOnly||y!==currentYear).map(y=>`<option value="${y}">${y} · historische Karte 0,1°</option>`).join("");
  if([...select.options].some(o=>o.value===previous))select.value=previous;
  else select.value=historicalOnly?String(end):"current";
}
function era5EuropeMapYear(){
  const raw=document.getElementById("era5EuropeMapYear")?.value||"current";
  return raw==="current"?null:Number(raw);
}
function era5EuropeReferenceForPoint(point,parameter,layer,periodId){
  const series=era5EuropePointSeries(point,parameter,layer,periodId);if(!series)return null;
  const entries=era5EuropeFiniteEntries(series.years,series.history).filter(e=>e.year>=1991&&e.year<=2020);
  if(!entries.length)return null;return entries.reduce((s,e)=>s+e.value,0)/entries.length;
}
function era5EuropePercentileForPoint(point,parameter,layer,periodId,year){
  const series=era5EuropePointSeries(point,parameter,layer,periodId);if(!series)return null;
  const entries=era5EuropeFiniteEntries(series.years,series.history);const target=entries.find(e=>e.year===Number(year));if(!target)return null;
  const ref=entries.filter(e=>e.year>=1991&&e.year<=2020);if(!ref.length)return null;
  const below=ref.filter(e=>e.value<target.value).length,equal=ref.filter(e=>e.value===target.value).length;
  return 100*(below+0.5*equal)/ref.length;
}
function era5EuropeHistoricalField(parameter,layer,periodId,year,view){
  const rows=[];
  for(const point of era5EuropeAnalysis?.points||[]){
    const series=era5EuropePointSeries(point,parameter,layer,periodId);if(!series)continue;
    const idx=(series.years||[]).map(Number).indexOf(Number(year));if(idx<0)continue;
    const raw=Number(series.history?.[idx]);if(!Number.isFinite(raw))continue;
    const reference=era5EuropeReferenceForPoint(point,parameter,layer,periodId);
    let value=raw;
    if(view==="anomaly")value=Number.isFinite(reference)?raw-reference:null;
    else if(view==="percent")value=Number.isFinite(reference)&&reference!==0?raw/reference*100:null;
    else if(view==="percentile")value=era5EuropePercentileForPoint(point,parameter,layer,periodId,year);
    if(Number.isFinite(value))rows.push({point,raw,reference,value});
  }
  return rows;
}
function era5EuropeQuantile(values,q){
  const a=values.filter(Number.isFinite).sort((x,y)=>x-y);if(!a.length)return 0;const pos=(a.length-1)*q,lo=Math.floor(pos),hi=Math.ceil(pos);return lo===hi?a[lo]:a[lo]+(a[hi]-a[lo])*(pos-lo);
}
function era5EuropeMix(a,b,t){
  const parse=h=>[parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];const A=parse(a),B=parse(b);const c=A.map((v,i)=>Math.round(v+(B[i]-v)*Math.max(0,Math.min(1,t))));return `rgb(${c[0]},${c[1]},${c[2]})`;
}
function era5EuropeMultiColor(stops,t){
  t=Math.max(0,Math.min(1,t));const p=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(p));return era5EuropeMix(stops[i],stops[i+1],p-i);
}
function era5EuropeHistoryScaleFor(entries,parameter,view){
  const vals=entries.map(e=>e.value).filter(Number.isFinite);let min=era5EuropeQuantile(vals,.02),max=era5EuropeQuantile(vals,.98),center=null,stops;
  if(view==="percentile"){min=0;max=100;stops=parameter.startsWith("snow_")?["#f7fbff","#9ecae1","#3182bd","#08306b"]:["#8c510a","#dfc27d","#f5f5f5","#80cdc1","#01665e"];}
  else if(view==="percent"){min=0;max=Math.max(200,era5EuropeQuantile(vals,.98));center=100;stops=["#8c510a","#dfc27d","#f5f5f5","#80cdc1","#01665e"];}
  else if(view==="anomaly" || parameter==="water_balance"){
    const vmax=Math.max(Math.abs(era5EuropeQuantile(vals,.02)),Math.abs(era5EuropeQuantile(vals,.98)),parameter==="temperature"?1:0.001);min=-vmax;max=vmax;center=0;
    stops=parameter.startsWith("snow_")?["#b35806","#f1a340","#f7f7f7","#92c5de","#0571b0"]:parameter==="temperature"?["#2166ac","#67a9cf","#f7f7f7","#ef8a62","#b2182b"]:["#8c510a","#dfc27d","#f5f5f5","#80cdc1","#01665e"];
  }else{
    if(parameter!=="temperature"&&parameter!=="soil_moisture"&&parameter!=="water_balance")min=Math.max(0,min);
    if(max<=min)max=min+1;
    if(parameter==="temperature")stops=["#313695","#74add1","#ffffbf","#f46d43","#a50026"];
    else if(parameter.startsWith("snow_"))stops=["#f7fbff","#c6dbef","#6baed6","#2171b5","#08306b"];
    else if(parameter==="soil_moisture")stops=["#a6611a","#dfc27d","#80cdc1","#018571"];
    else stops=["#ffffd9","#c7e9b4","#41b6c4","#225ea8","#0c2c84"];
  }
  const color=value=>{if(!Number.isFinite(value))return "rgba(0,0,0,0)";let t;if(center!==null&&center>min&&center<max){t=value<=center?.5*(value-min)/(center-min):.5+.5*(value-center)/(max-center);}else t=(value-min)/(max-min);return era5EuropeMultiColor(stops,t);};
  return {min,max,center,stops,color,gradient:`linear-gradient(90deg,${stops.join(",")})`};
}
function era5EuropeWeightedMeanRows(rows,key){
  let s=0,w=0;for(const row of rows){const v=Number(row[key]);if(!Number.isFinite(v))continue;const ww=Math.max(.05,Math.cos(Number(row.point.lat)*Math.PI/180));s+=v*ww;w+=ww;}return w?s/w:null;
}
function era5EuropeWeightedFractionRows(rows,predicate){
  let hit=0,total=0;for(const row of rows){const ww=Math.max(.05,Math.cos(Number(row.point.lat)*Math.PI/180));total+=ww;if(predicate(row))hit+=ww;}return total?100*hit/total:null;
}
async function ensureEra5EuropeHighresArchiveLoaded(){
  if(era5EuropeHighresArchive?.ready)return era5EuropeHighresArchive;
  if(era5EuropeHighresArchiveLoading)return era5EuropeHighresArchiveLoading;
  const file=era5EuropeIndex?.history_map?.archive_file;
  if(!file)throw new Error("0,1°-Historienarchiv fehlt. Bitte den ERA5-Land-Workflow einmal ausführen.");
  era5EuropeHighresArchiveLoading=fetch(`${ERA5_EUROPE_RAW_BASE}${file}?v=${encodeURIComponent(era5EuropeIndex.generated_at||Date.now())}`,{cache:"no-store"})
    .then(async response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();if(!data?.ready)throw new Error("0,1°-Historienarchiv ist noch nicht bereit.");era5EuropeHighresArchive=data;return data;})
    .finally(()=>{era5EuropeHighresArchiveLoading=null;});
  return era5EuropeHighresArchiveLoading;
}
function era5EuropeHighresVariableKey(parameter,layer){return parameter==="soil_moisture"?`soil_moisture_${layer}`:parameter;}
function era5EuropeHighresPackMeta(parameter,layer,month){
  const key=era5EuropeHighresVariableKey(parameter,layer),mk=String(month).padStart(2,"0");
  return era5EuropeHighresArchive?.variables?.[key]?.[mk]||null;
}
function era5EuropeHighresCacheRemember(key,value){
  if(era5EuropeHighresPackCache.has(key))era5EuropeHighresPackCache.delete(key);
  era5EuropeHighresPackCache.set(key,value);
  while(era5EuropeHighresPackCache.size>6){const oldest=era5EuropeHighresPackCache.keys().next().value;era5EuropeHighresPackCache.delete(oldest);}
}
async function era5EuropeHighresLoadPack(meta){
  if(!meta?.file)throw new Error("Historisches 0,1°-Datenpaket fehlt.");
  const key=meta.file;
  if(era5EuropeHighresPackCache.has(key)){const cached=era5EuropeHighresPackCache.get(key);era5EuropeHighresCacheRemember(key,cached);return cached;}
  const promise=fetch(`${ERA5_EUROPE_RAW_BASE}${meta.file}?v=${encodeURIComponent(era5EuropeIndex.generated_at||Date.now())}`,{cache:"force-cache"}).then(async response=>{
    if(!response.ok)throw new Error(`HTTP ${response.status} für ${meta.file}`);
    const packed=new Uint8Array(await response.arrayBuffer());let bytes=packed;
    if(packed.length>=2&&packed[0]===0x1f&&packed[1]===0x8b){
      if(typeof DecompressionStream==="undefined")throw new Error("Dieser Browser unterstützt die Dekompression des 0,1°-Archivs nicht.");
      const stream=new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip"));bytes=new Uint8Array(await new Response(stream).arrayBuffer());
    }
    const expected=Number(meta.n_years)*Number(meta.nlat)*Number(meta.nlon);
    if(bytes.length!==expected)throw new Error(`0,1°-Archiv hat ${bytes.length} statt ${expected} Rasterbytes.`);
    return {meta,bytes};
  }).catch(error=>{era5EuropeHighresPackCache.delete(key);throw error;});
  era5EuropeHighresCacheRemember(key,promise);return promise;
}
function era5EuropeHighresDecodeYear(pack,year){
  const meta=pack.meta,iy=Number(year)-Number(meta.year_start);if(iy<0||iy>=Number(meta.n_years))return null;
  const nlat=Number(meta.nlat),nlon=Number(meta.nlon),n=nlat*nlon,start=iy*n,missing=Number(meta.missing??255),offset=Number(meta.offset),step=Number(meta.step),out=new Float32Array(n),delta=meta.predictor==="delta-x-u8-v1";
  if(delta){for(let y=0;y<nlat;y++){let code=0,row=start+y*nlon;for(let x=0;x<nlon;x++){const enc=pack.bytes[row+x];code=x===0?enc:(code+enc)&255;out[y*nlon+x]=code===missing?NaN:offset+code*step;}}}
  else{for(let i=0;i<n;i++){const code=pack.bytes[start+i];out[i]=code===missing?NaN:offset+code*step;}}
  return out;
}
function era5EuropeHighresIsAccumulated(parameter){return ["precipitation","evaporation","runoff","surface_runoff","sub_surface_runoff","water_balance"].includes(parameter);}
function era5EuropeDaysInMonth(year,month){return new Date(Date.UTC(Number(year),Number(month),0)).getUTCDate();}
async function era5EuropeHighresCombinedRaw(parameter,layer,periodId,year){
  const months=(era5EuropeIndex?.periods?.[periodId]?.months||[]).map(Number);if(!months.length)return null;
  const metas=months.map(month=>era5EuropeHighresPackMeta(parameter,layer,month));if(metas.some(meta=>!meta))throw new Error("Für diese historische 0,1°-Karte fehlt noch mindestens ein Monatsarchiv.");
  const packs=await Promise.all(metas.map(era5EuropeHighresLoadPack));const nlat=Number(metas[0].nlat),nlon=Number(metas[0].nlon),n=nlat*nlon;
  if(metas.some(meta=>Number(meta.nlat)!==nlat||Number(meta.nlon)!==nlon))throw new Error("0,1°-Monatsarchive haben unterschiedliche Rastergrößen.");
  const sum=new Float64Array(n),den=new Float64Array(n),accum=era5EuropeHighresIsAccumulated(parameter);
  for(let k=0;k<packs.length;k++){
    const values=era5EuropeHighresDecodeYear(packs[k],year);if(!values)return null;const w=accum?1:era5EuropeDaysInMonth(year,months[k]);
    for(let i=0;i<n;i++){const v=values[i];if(Number.isFinite(v)){sum[i]+=v*w;den[i]+=accum?1:w;}}
  }
  const out=new Float32Array(n);for(let i=0;i<n;i++)out[i]=den[i]>0?(accum?sum[i]:sum[i]/den[i]):NaN;
  return {values:out,nlat,nlon,latStart:Number(metas[0].lat_start),latStep:Number(metas[0].lat_step),lonStart:Number(metas[0].lon_start),lonStep:Number(metas[0].lon_step)};
}
async function era5EuropeHighresReference(parameter,layer,periodId){
  const key=`${era5EuropeHighresArchive?.generated_at||"archive"}|${parameter}|${layer}|${periodId}`;if(era5EuropeHighresReferenceCache.has(key))return era5EuropeHighresReferenceCache.get(key);
  let sum=null,count=null,template=null;
  for(let year=1991;year<=2020;year++){
    const field=await era5EuropeHighresCombinedRaw(parameter,layer,periodId,year);if(!field)continue;if(!template){template=field;sum=new Float64Array(field.values.length);count=new Uint8Array(field.values.length);}
    for(let i=0;i<field.values.length;i++){const v=field.values[i];if(Number.isFinite(v)){sum[i]+=v;count[i]++;}}
  }
  if(!template)throw new Error("1991–2020-Referenz für das 0,1°-Archiv fehlt.");
  const values=new Float32Array(sum.length);for(let i=0;i<values.length;i++)values[i]=count[i]?sum[i]/count[i]:NaN;
  const result={...template,values};era5EuropeHighresReferenceCache.set(key,result);return result;
}
async function era5EuropeHighresPercentile(parameter,layer,periodId,year,target){
  const below=new Uint8Array(target.values.length),equal=new Uint8Array(target.values.length),count=new Uint8Array(target.values.length);
  for(let refYear=1991;refYear<=2020;refYear++){
    const field=await era5EuropeHighresCombinedRaw(parameter,layer,periodId,refYear);if(!field)continue;
    for(let i=0;i<field.values.length;i++){const r=field.values[i],t=target.values[i];if(!Number.isFinite(r)||!Number.isFinite(t))continue;count[i]++;if(r<t)below[i]++;else if(r===t)equal[i]++;}
  }
  const values=new Float32Array(target.values.length);for(let i=0;i<values.length;i++)values[i]=count[i]?100*(below[i]+.5*equal[i])/count[i]:NaN;return {...target,values};
}
async function era5EuropeHighresViewField(parameter,layer,periodId,year,view){
  await ensureEra5EuropeHighresArchiveLoaded();const raw=await era5EuropeHighresCombinedRaw(parameter,layer,periodId,year);if(!raw)throw new Error(`Für ${year} liegt in diesem 0,1°-Archiv kein Raster vor.`);
  if(view==="absolute")return raw;if(view==="percentile")return era5EuropeHighresPercentile(parameter,layer,periodId,year,raw);
  const reference=await era5EuropeHighresReference(parameter,layer,periodId),values=new Float32Array(raw.values.length);
  for(let i=0;i<values.length;i++){const a=raw.values[i],b=reference.values[i];if(!Number.isFinite(a)||!Number.isFinite(b)){values[i]=NaN;continue;}values[i]=view==="percent"?(b!==0?a/b*100:NaN):a-b;}
  return {...raw,values};
}
function era5EuropeHistoryScaleRgb(scale,value){
  if(!Number.isFinite(value))return null;if(!scale._rgbStops)scale._rgbStops=scale.stops.map(hex=>[parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)]);
  let t;if(scale.center!==null&&scale.center>scale.min&&scale.center<scale.max)t=value<=scale.center?.5*(value-scale.min)/(scale.center-scale.min):.5+.5*(value-scale.center)/(scale.max-scale.center);else t=(value-scale.min)/(scale.max-scale.min);
  t=Math.max(0,Math.min(1,t));const stops=scale._rgbStops,p=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(p)),f=p-i,A=stops[i],B=stops[i+1];return [Math.round(A[0]+(B[0]-A[0])*f),Math.round(A[1]+(B[1]-A[1])*f),Math.round(A[2]+(B[2]-A[2])*f)];
}
function era5EuropeDrawHistoricalCanvas(){
  const canvas=document.getElementById("era5EuropeHistoryCanvas"),img=document.getElementById("era5EuropeImage"),raster=era5EuropeHistoricalRaster;if(!canvas||!img||!img.naturalWidth||!raster)return;
  canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;const ctx=canvas.getContext("2d");ctx.clearRect(0,0,canvas.width,canvas.height);
  const off=document.createElement("canvas");off.width=raster.nlon;off.height=raster.nlat;const octx=off.getContext("2d"),image=octx.createImageData(raster.nlon,raster.nlat),data=image.data;
  for(let y=0;y<raster.nlat;y++){const sy=raster.latStep<=0?y:raster.nlat-1-y;for(let x=0;x<raster.nlon;x++){const sx=raster.lonStep>=0?x:raster.nlon-1-x,src=sy*raster.nlon+sx,dst=(y*raster.nlon+x)*4,rgb=era5EuropeHistoryScaleRgb(era5EuropeHistoricalScale,raster.values[src]);if(!rgb){data[dst+3]=0;continue;}data[dst]=rgb[0];data[dst+1]=rgb[1];data[dst+2]=rgb[2];data[dst+3]=255;}}
  octx.putImageData(image,0,0);const g=era5EuropeIndex?.click_geometry||{left:.07,top:.16,right:.96,bottom:.82};const dx=g.left*canvas.width,dy=g.top*canvas.height,dw=(g.right-g.left)*canvas.width,dh=(g.bottom-g.top)*canvas.height;ctx.imageSmoothingEnabled=false;ctx.drawImage(off,dx,dy,dw,dh);
}
function era5EuropeHistoryLegendLabel(v,meta,view){
  if(view==="percentile")return `P${Math.round(v)}`;if(view==="percent")return `${Math.round(v)} %`;return era5EuropeFormat(v,meta.decimals,` ${view==="anomaly"?(meta.diffUnit||meta.unit):meta.unit}`);
}
async function renderEra5EuropeHistorical(){
  const wrap=document.getElementById("era5EuropeImageWrap");if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Historische Karte wird aus dem echten 0,1°-ERA5-Land-Archiv aufgebaut …</div>';
  try{await ensureEra5EuropeHighresArchiveLoaded();}catch(error){if(wrap)wrap.innerHTML=`<div class="era5-europe-loading">Historisches 0,1°-Kartenarchiv konnte nicht geladen werden: ${error.message}</div>`;return;}
  let analysisReady=false;try{await ensureEra5EuropeAnalysisLoaded();analysisReady=true;}catch(error){console.warn("ERA5 1°-Analyse für diese Monatskarte nicht erforderlich:",error);}
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature",layer=document.getElementById("era5EuropeSoilLayer")?.value||"layer1",periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month",view=document.getElementById("era5EuropeView")?.value||"absolute",year=era5EuropeMapYear();if(!Number.isFinite(year))return;
  const period=era5EuropeIndex?.periods?.[periodId],meta=era5EuropeMetricMeta(parameter,layer);
  if(period?.historical_only&&!["temperature","precipitation"].includes(parameter)){if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Das neue Monatsarchiv ist in dieser Stufe nur für Temperatur und Niederschlag verfügbar.</div>';return;}
  let rows=analysisReady?era5EuropeHistoricalField(parameter,layer,periodId,year,view):[];era5EuropeHistoricalEntries=rows;
  try{era5EuropeHistoricalRaster=await era5EuropeHighresViewField(parameter,layer,periodId,year,view);}catch(error){console.error(error);if(wrap)wrap.innerHTML=`<div class="era5-europe-loading">Die historische 0,1°-Karte ist noch nicht aufgebaut: ${error.message}<br>Bitte den Workflow „ERA5-Land Europa aktualisieren“ einmal mit force = false ausführen.</div>`;return;}
  era5EuropeHistoricalScale=era5EuropeHistoryScaleFor(rows.length?rows:era5EuropeHighresSampleEntries(era5EuropeHistoricalRaster),parameter,view);
  const rawRaster=await era5EuropeHighresCombinedRaw(parameter,layer,periodId,year);
  const referenceRaster=await era5EuropeHighresReference(parameter,layer,periodId);
  const rawMean=era5EuropeHighresWeightedMean(rawRaster),refMean=era5EuropeHighresWeightedMean(referenceRaster);
  const base=`${ERA5_EUROPE_RAW_BASE}${era5EuropeIndex?.history_map?.base_file||"era5_land_europe/maps/historical_base.png"}?v=${encodeURIComponent(era5EuropeIndex.generated_at||Date.now())}`;
  const minLabel=era5EuropeHistoryLegendLabel(era5EuropeHistoricalScale.min,meta,view),maxLabel=era5EuropeHistoryLegendLabel(era5EuropeHistoricalScale.max,meta,view),clickable=rows.length>0;
  if(wrap)wrap.innerHTML=`<div id="era5EuropeImageStage" class="era5-europe-image-stage"><img id="era5EuropeImage" class="era5-europe-image" crossorigin="anonymous" alt="Historische ERA5-Land-Karte ${year}" src="${base}"><canvas id="era5EuropeHistoryCanvas" class="era5-europe-history-canvas"></canvas><div id="era5EuropePointMarker" class="era5-europe-point-marker"></div><div class="era5-europe-history-badge">Historisches Kartenarchiv<br>${year} · 0,1° ERA5-Land</div><div class="era5-europe-click-hint">${clickable?'Karte anklicken<br>→ Gitterpunktanalyse':'Monatsarchiv<br>0,1° ERA5-Land'}</div><div class="era5-europe-history-legend"><span>${minLabel}</span><div class="era5-europe-history-gradient" style="background:${era5EuropeHistoricalScale.gradient}"></div><span>${maxLabel}</span></div></div>`;
  const stage=document.getElementById("era5EuropeImageStage"),img=document.getElementById("era5EuropeImage");if(clickable)stage?.addEventListener("click",era5EuropeHandleMapClick);img?.addEventListener("load",()=>{era5EuropeDrawHistoricalCanvas();if(clickable)era5EuropePlaceMarker();});img?.addEventListener("error",()=>{if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Die historische Basiskarte konnte nicht geladen werden.</div>';});
  const periodDisplayLabel=era5EuropePeriodDisplayLabel(period,year);
  document.getElementById("era5EuropeMapTitle").textContent=`${meta.label} · ${periodDisplayLabel}`;document.getElementById("era5EuropeMapSubtitle").textContent=`Historische 0,1°-ERA5-Land-Karte · ${document.getElementById("era5EuropeView")?.selectedOptions?.[0]?.textContent||view}${clickable?' · Rankings/KPIs separat auf 1,0°':' · Monatsarchiv'}`;
  document.getElementById("era5EuropePeriodKpi").textContent=periodDisplayLabel;document.getElementById("era5EuropeDataKpi").textContent="Historisches Archiv · sichtbares Raster 0,1°";
  const diffLabel=document.getElementById("era5EuropeDifferenceLabel");document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(rawMean,meta.decimals,` ${meta.unit}`);document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(refMean,meta.decimals,` ${meta.unit}`);
  if(parameter==="precipitation"){if(diffLabel)diffLabel.textContent="Vom Mittel";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(Number.isFinite(rawMean)&&Number.isFinite(refMean)&&refMean!==0?rawMean/refMean*100:null,0," %");document.getElementById("era5EuropeDifferenceDetail").textContent=`Niederschlag ${year} gegenüber 1991–2020`;}
  else{if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(Number.isFinite(rawMean)&&Number.isFinite(refMean)?rawMean-refMean:null,meta.decimals,` ${parameter==="temperature"?"K":meta.diffUnit||meta.unit}`);document.getElementById("era5EuropeDifferenceDetail").textContent=`${year} gegenüber 1991–2020`;}
  const source=document.getElementById("era5EuropeSource");if(source)source.textContent=`Quelle: ${era5EuropeIndex.source}. ${era5EuropeIndex.history_map?.note||"Historische sichtbare Karte auf 0,1°."} ${era5EuropeIndex.history_map?.tp_all_months_note||""}`.trim();
  if(clickable){if(era5EuropeSelectedPoint)renderEra5EuropePointAnalysis();renderEra5EuropeRankings();}else era5EuropeShowMonthlyRankingPending(meta,period,year);
}
function era5RunningRankPercent(value){
  return Number.isFinite(Number(value))?Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})+" %":"–";
}
function era5RunningRankSetStatus(message,state=""){
  const el=document.getElementById("era5RunningRankStatus");if(!el)return;
  el.textContent=message;
  el.style.color=state==="error"?"#a33d32":state==="ok"?"#3f7652":"";
}
function era5RunningRankDisplayDate(value){
  if(!value)return "aktueller Stand";
  const date=new Date(`${value}T00:00:00`);
  if(Number.isNaN(date.getTime()))return value;
  return date.toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
}
function era5RunningRankStopPlay(){
  if(era5RunningRankPlayTimer!==null){
    window.clearInterval(era5RunningRankPlayTimer);
    era5RunningRankPlayTimer=null;
  }
  era5RunningRankPlayBusy=false;
  const button=document.getElementById("era5RunningRankPlay");
  if(button)button.textContent="▶ Abspielen";
}
function era5RunningRankUpdateTimeline(){
  const slider=document.getElementById("era5RunningRankSlider");
  const prev=document.getElementById("era5RunningRankPrev");
  const next=document.getElementById("era5RunningRankNext");
  const label=document.getElementById("era5RunningRankTimelineDate");
  const length=era5RunningRankDates.length;
  const index=length?Math.max(0,Math.min(era5RunningRankDateIndex,length-1)):0;
  if(slider){
    slider.min="0";
    slider.max=String(Math.max(0,length-1));
    slider.value=String(index);
    slider.disabled=length<2;
  }
  if(prev)prev.disabled=length<2||index<=0;
  if(next)next.disabled=length<2||index>=length-1;
  if(label){
    label.textContent=length
      ?`${era5RunningRankDisplayDate(era5RunningRankDates[index])} · ${index+1}/${length}`
      :"Noch kein Archivstand";
  }
}
function era5RunningRankArchiveIndexUrl(date){
  const pattern=era5RunningTemperatureRanks?.archive_index_pattern
    ||"era5_land_europe/running/temperature_ranks/archive/{date}/index.json";
  return `${ERA5_EUROPE_RAW_BASE}${pattern.replace("{date}",date)}?v=${encodeURIComponent(date)}`;
}
async function era5RunningRankSelectIndex(index,{manual=false}={}){
  const length=era5RunningRankDates.length;
  if(!length)return;
  const next=Math.max(0,Math.min(Number(index)||0,length-1));
  if(manual)era5RunningRankStopPlay();
  era5RunningRankDateIndex=next;
  era5RunningRankUpdateTimeline();
  const date=era5RunningRankDates[next];
  if(date===era5RunningTemperatureRanks?.data_through){
    era5RunningTemperatureRanksDisplay=era5RunningTemperatureRanks;
    renderEra5RunningTemperatureRanks();
    return;
  }
  if(era5RunningRankArchiveCache.has(date)){
    era5RunningTemperatureRanksDisplay=era5RunningRankArchiveCache.get(date);
    renderEra5RunningTemperatureRanks();
    return;
  }
  era5RunningRankSetStatus(`Archivstand ${era5RunningRankDisplayDate(date)} wird geladen …`);
  try{
    const response=await fetch(era5RunningRankArchiveIndexUrl(date),{cache:"force-cache"});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const payload=await response.json();
    if(!payload?.ready)throw new Error("Archivstand ist nicht bereit");
    era5RunningRankArchiveCache.set(date,payload);
    if(era5RunningRankDates[era5RunningRankDateIndex]!==date)return;
    era5RunningTemperatureRanksDisplay=payload;
    renderEra5RunningTemperatureRanks();
  }catch(error){
    console.error("ERA5-Rangarchiv:",error);
    era5RunningRankSetStatus(`Archivstand konnte nicht geladen werden: ${error.message}`,"error");
  }
}
function era5RunningRankStep(delta){
  if(!era5RunningRankDates.length)return;
  era5RunningRankSelectIndex(era5RunningRankDateIndex+Number(delta||0),{manual:true});
}
function era5RunningRankSliderInput(value){
  era5RunningRankSelectIndex(Number(value),{manual:true});
}
function era5RunningRankTogglePlay(){
  if(era5RunningRankPlayTimer!==null){
    era5RunningRankStopPlay();
    return;
  }
  if(era5RunningRankDates.length<2)return;
  const button=document.getElementById("era5RunningRankPlay");
  if(button)button.textContent="⏸ Pause";
  era5RunningRankPlayTimer=window.setInterval(async()=>{
    if(era5RunningRankPlayBusy)return;
    era5RunningRankPlayBusy=true;
    try{
      const next=era5RunningRankDateIndex>=era5RunningRankDates.length-1?0:era5RunningRankDateIndex+1;
      await era5RunningRankSelectIndex(next);
    }finally{
      era5RunningRankPlayBusy=false;
    }
  },850);
}

function era5RunningRankProducts(data){
  const products={...(data?.products||{})};
  if(!products.season_to_date&&products.summer_to_date){
    products.season_to_date={...products.summer_to_date,season_key:"summer",season_name:"Sommer"};
  }
  return products;
}
function era5RunningRankCurrentProduct(){
  const data=era5RunningTemperatureRanksDisplay||era5RunningTemperatureRanks;
  if(!data?.ready||!data.products)return null;
  const products=era5RunningRankProducts(data);
  const key=products[era5RunningTemperatureRankProduct]?era5RunningTemperatureRankProduct:(products.year_to_date?"year_to_date":"day");
  const product=products[key];
  if(!product?.file)return null;
  return {data,key,product};
}
function era5RunningRankDownloadBaseName(key,data){
  const names={day:"tag",month_to_date:"monat_bis_heute",season_to_date:"jahreszeit_bis_heute",year_to_date:"jahr_bis_heute"};
  const date=String(data?.data_through||"aktuell").replace(/[^0-9-]/g,"");
  return `era5_temperatur_rang_${names[key]||key}_${date||"aktuell"}`;
}
async function era5RunningRankFetchBlob(){
  const current=era5RunningRankCurrentProduct();
  if(!current)throw new Error("Keine ERA5-Rangkarte ausgewählt.");
  const url=`${ERA5_EUROPE_RAW_BASE}${current.product.file}?v=${encodeURIComponent(current.data.data_through||Date.now())}`;
  const response=await fetch(url,{cache:"no-store"});
  if(!response.ok)throw new Error(`Rangkarte nicht erreichbar (HTTP ${response.status})`);
  const blob=await response.blob();
  if(!blob.size)throw new Error("Die Rangkarte ist leer.");
  return {...current,blob};
}
async function downloadEra5RunningRankPng(){
  const button=document.getElementById("era5RunningRankDownloadPng");
  if(button)button.disabled=true;
  try{
    const {data,key,blob}=await era5RunningRankFetchBlob();
    const dataUrl=await era5RunningRankBlobToPngDataUrl(blob);
    const link=document.createElement("a");
    link.href=dataUrl;
    link.download=`${era5RunningRankDownloadBaseName(key,data)}.png`;
    document.body.appendChild(link);link.click();link.remove();
  }catch(error){
    console.error("ERA5-Rangkarte PNG:",error);
    era5RunningRankSetStatus(`PNG-Download fehlgeschlagen: ${error.message}`,"error");
  }finally{
    if(button)button.disabled=false;
  }
}
async function era5RunningRankBlobToPngDataUrl(blob){
  const source=URL.createObjectURL(blob);
  try{
    const image=await new Promise((resolve,reject)=>{
      const img=new Image();
      img.onload=()=>resolve(img);
      img.onerror=()=>reject(new Error("Rangkarte konnte nicht dekodiert werden."));
      img.src=source;
    });
    const canvas=document.createElement("canvas");
    canvas.width=image.naturalWidth||image.width;
    canvas.height=image.naturalHeight||image.height;
    const ctx=canvas.getContext("2d");
    if(!ctx)throw new Error("PNG-Canvas konnte nicht erstellt werden.");
    ctx.fillStyle="#ffffff";ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.drawImage(image,0,0);
    return canvas.toDataURL("image/png");
  }finally{
    URL.revokeObjectURL(source);
  }
}
function era5RunningRankBlobToDataUrl(blob){
  return era5RunningRankBlobToPngDataUrl(blob);
}
function era5RunningRankImageSize(dataUrl){
  return new Promise((resolve,reject)=>{
    const img=new Image();
    img.onload=()=>resolve({width:img.naturalWidth||img.width,height:img.naturalHeight||img.height});
    img.onerror=()=>reject(new Error("Bildgröße konnte nicht bestimmt werden."));
    img.src=dataUrl;
  });
}
async function downloadEra5RunningRankPdf(){
  const button=document.getElementById("era5RunningRankDownloadPdf");
  if(button)button.disabled=true;
  try{
    const {data,key,blob}=await era5RunningRankFetchBlob();
    const dataUrl=await era5RunningRankBlobToDataUrl(blob);
    const size=await era5RunningRankImageSize(dataUrl);
    const jsPDFCtor=window.jspdf?.jsPDF;
    if(!jsPDFCtor)throw new Error("PDF-Bibliothek ist nicht verfügbar.");
    const pdf=new jsPDFCtor({orientation:"landscape",unit:"mm",format:"a4",compress:true});
    const pageWidth=pdf.internal.pageSize.getWidth(),pageHeight=pdf.internal.pageSize.getHeight();
    const margin=8,maxWidth=pageWidth-2*margin,maxHeight=pageHeight-2*margin;
    const scale=Math.min(maxWidth/size.width,maxHeight/size.height);
    const width=size.width*scale,height=size.height*scale;
    pdf.addImage(dataUrl,"PNG",(pageWidth-width)/2,(pageHeight-height)/2,width,height,undefined,"FAST");
    pdf.save(`${era5RunningRankDownloadBaseName(key,data)}.pdf`);
  }catch(error){
    console.error("ERA5-Rangkarte PDF:",error);
    era5RunningRankSetStatus(`PDF-Download fehlgeschlagen: ${error.message}`,"error");
  }finally{
    if(button)button.disabled=false;
  }
}
function renderEra5RunningTemperatureRanks(){
  const data=era5RunningTemperatureRanksDisplay||era5RunningTemperatureRanks;
  if(!data?.ready||!data.products)return;
  const products=era5RunningRankProducts(data);
  const key=products[era5RunningTemperatureRankProduct]?era5RunningTemperatureRankProduct:"day";
  era5RunningTemperatureRankProduct=key;
  const product=products[key],stats=product.stats||{};
  const seasonButton=document.getElementById("era5RunningRankSeasonButton");
  if(seasonButton){
    const seasonName=products.season_to_date?.season_name||"Jahreszeit";
    seasonButton.textContent=`${seasonName} bis heute`;
  }
  document.querySelectorAll("[data-era5-running-rank-product]").forEach(button=>{
    const productKey=button.dataset.era5RunningRankProduct;
    const available=Boolean(products[productKey]);
    const active=available&&productKey===key;
    button.hidden=!available;
    button.classList.toggle("active",active);
    button.setAttribute("aria-pressed",active?"true":"false");
  });
  const year=Number(data.current_year)||String(data.data_through||"").slice(0,4)||"2026";
  const title=document.getElementById("era5RunningRankTitle");if(title)title.textContent=`Temperatur-Rang ${year}`;
  const subtitle=document.getElementById("era5RunningRankSubtitle");if(subtitle)subtitle.textContent=product.note||"Laufende Einordnung der 2-m-Temperatur gegenüber 1950–2025.";
  const period=document.getElementById("era5RunningRankPeriod");if(period)period.textContent=product.label||data.data_through||"–";
  const periodDetail=document.getElementById("era5RunningRankPeriodDetail");if(periodDetail)periodDetail.textContent=`Datenstand ${data.data_through||"–"}`;
  const rank1=document.getElementById("era5RunningRankRank1");if(rank1)rank1.textContent=era5RunningRankPercent(stats.rank1_area_percent);
  const top3=document.getElementById("era5RunningRankTop3");if(top3)top3.textContent=era5RunningRankPercent(stats.top3_area_percent);
  const top3Detail=document.getElementById("era5RunningRankTop3Detail");if(top3Detail)top3Detail.textContent=`${Number(product.comparison_years)||Number(data.historical_years)||76} historische Jahre · insgesamt ${Number(product.total_rank_positions)||Number(data.total_rank_positions)||77} Rangpositionen`;
  const foot=document.getElementById("era5RunningRankFoot");if(foot)foot.textContent=`${product.rank_direction||data.rank_direction||"1 = wärmster"} · Vergleich ${product.history_start||data.history_start||1950}–${product.history_end||data.history_end||2025} plus ${year} · ${data.grid||"0,1° ERA5-Land"}.`;
  const wrap=document.getElementById("era5RunningRankImageWrap");
  if(wrap&&product.file){
    const img=document.createElement("img");
    img.className="era5-running-rank-image";
    img.alt=`ERA5-Land Temperatur-Rangkarte ${product.label||""}`.trim();
    img.loading="lazy";
    img.addEventListener("error",()=>{wrap.innerHTML='<div class="era5-europe-loading">Rangkarte konnte nicht geladen werden.</div>';});
    img.src=`${ERA5_EUROPE_RAW_BASE}${product.file}?v=${encodeURIComponent(data.data_through||Date.now())}`;
    wrap.replaceChildren(img);
  }
  era5RunningRankSetStatus(`Datenstand ${data.data_through||"–"} · ${data.grid||"ERA5-Land"} · Rang 1 = wärmster`,"ok");
}
async function ensureEra5RunningTemperatureRanksLoaded(force=false){
  if(era5RunningTemperatureRanks&&!force){renderEra5RunningTemperatureRanks();return era5RunningTemperatureRanks;}
  if(era5RunningTemperatureRanksLoading&&!force)return era5RunningTemperatureRanksLoading;
  era5RunningRankSetStatus("Temperatur-Rangkarten werden geladen …");
  const url=`${ERA5_EUROPE_RAW_BASE}${ERA5_RUNNING_TEMPERATURE_RANKS_INDEX}?ts=${Date.now()}`;
  era5RunningTemperatureRanksLoading=fetch(url,{cache:"no-store"}).then(async response=>{
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    era5RunningTemperatureRanks=await response.json();
    if(!era5RunningTemperatureRanks?.ready)throw new Error("Rangdaten sind noch nicht bereit");
    const dates=Array.isArray(era5RunningTemperatureRanks.available_dates)
      ?era5RunningTemperatureRanks.available_dates.filter(value=>/^\d{4}-\d{2}-\d{2}$/.test(String(value))).sort()
      :[];
    const latest=String(era5RunningTemperatureRanks.data_through||"");
    if(latest&&!dates.includes(latest))dates.push(latest);
    era5RunningRankDates=[...new Set(dates)].sort();
    era5RunningRankDateIndex=era5RunningRankDates.length?era5RunningRankDates.length-1:-1;
    era5RunningTemperatureRanksDisplay=era5RunningTemperatureRanks;
    era5RunningRankUpdateTimeline();
    renderEra5RunningTemperatureRanks();
    return era5RunningTemperatureRanks;
  }).catch(error=>{
    console.error("ERA5-Land Temperatur-Rangkarten konnten nicht geladen werden:",error);
    era5RunningRankSetStatus(`Temperatur-Rangkarten konnten nicht geladen werden: ${error.message}`,"error");
    const wrap=document.getElementById("era5RunningRankImageWrap");if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Keine Rangkarte verfügbar.</div>';
    throw error;
  }).finally(()=>{era5RunningTemperatureRanksLoading=null;});
  return era5RunningTemperatureRanksLoading;
}

async function ensureEra5EuropeLoaded(force=false){
  if(era5EuropeIndex && !force){renderEra5Europe();return era5EuropeIndex;}
  if(era5EuropeLoading && !force)return era5EuropeLoading;
  era5EuropeSetStatus("ERA5-Land Europa wird geladen …");
  const url=`${ERA5_EUROPE_RAW_BASE}era5_land_europe/index.json?ts=${Date.now()}`;
  era5EuropeLoading=fetch(url,{cache:"no-store"}).then(async response=>{
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    era5EuropeIndex=await response.json();
    if(!era5EuropeIndex?.ready){
      era5EuropeSetStatus(era5EuropeIndex?.message||"ERA5-Land Europa wurde noch nicht aufgebaut.","warn");
      const wrap=document.getElementById("era5EuropeImageWrap");
      if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Noch keine ERA5-Land-Karten vorhanden. Nach der einmaligen CDS-Einrichtung den Workflow „ERA5-Land Europa aktualisieren“ starten.</div>';
      return era5EuropeIndex;
    }
    const v=Number(era5EuropeIndex.payload_version||0),hires=Number(era5EuropeIndex?.history_map?.archive_version||0)>=2&&String(era5EuropeIndex?.history_map?.grid||"").startsWith("0,1");
    era5EuropeSetStatus(`Datenstand ${era5EuropeIndex.data_through} · Referenz ${era5EuropeIndex.reference_period} · ${era5EuropeIndex.spatial_resolution}${v>=8&&hires?" · Rankings + 0,1°-Historienarchiv + Schnee + Wasserhaushalt bereit":v>=8?" · Rankings bereit · 0,1°-Historienarchiv nach nächstem Workflow":v>=7?" · Historisches Kartenarchiv + Schnee + Wasserhaushalt bereit":v>=6?" · Schnee + Wasserhaushalt + Klickanalyse bereit":v>=5?" · Wasserhaushalt + Klickanalyse bereit":v>=4?" · Klickanalyse bereit":""}`,v>=4?"ok":"warn");
    era5EuropeUpdatePeriodOptions();
    era5EuropeUpdateMapYearOptions();
    renderEra5Europe();
    return era5EuropeIndex;
  }).catch(error=>{
    console.error("ERA5-Land Europa konnte nicht geladen werden:",error);
    era5EuropeSetStatus(`ERA5-Land Europa konnte nicht geladen werden: ${error.message}`,"error");
    throw error;
  }).finally(()=>{era5EuropeLoading=null;});
  return era5EuropeLoading;
}
async function ensureEra5EuropeAnalysisLoaded(){
  if(era5EuropeAnalysis?.ready)return era5EuropeAnalysis;
  if(era5EuropeAnalysisLoading)return era5EuropeAnalysisLoading;
  const file=era5EuropeIndex?.analysis?.file;
  if(!file)throw new Error("Analyse-Datensatz fehlt. Bitte den ERA5-Land-Workflow einmal ausführen.");
  era5EuropeAnalysisLoading=fetch(`${ERA5_EUROPE_RAW_BASE}${file}?ts=${Date.now()}`,{cache:"no-store"})
    .then(async response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);era5EuropeAnalysis=await response.json();return era5EuropeAnalysis;})
    .finally(()=>{era5EuropeAnalysisLoading=null;});
  return era5EuropeAnalysisLoading;
}
function era5EuropeCoordinateLabel(point){
  if(!point)return "–";
  const lat=`${Math.abs(Number(point.lat)).toLocaleString("de-DE",{maximumFractionDigits:1})}° ${Number(point.lat)>=0?"N":"S"}`;
  const lon=`${Math.abs(Number(point.lon)).toLocaleString("de-DE",{maximumFractionDigits:1})}° ${Number(point.lon)>=0?"E":"W"}`;
  return `${lat}, ${lon}`;
}
function era5EuropeRankingValueText(row,meta,view,parameter){
  if(!row||!Number.isFinite(Number(row.value)))return "–";
  if(view==="percentile")return `P${Math.round(Number(row.value))}`;
  if(view==="percent")return era5EuropeFormat(row.value,0," %");
  const unit=view==="anomaly"?(parameter==="temperature"?"K":meta.diffUnit||meta.unit):meta.unit;
  return era5EuropeFormat(row.value,meta.decimals,` ${unit}`);
}
function era5EuropeRankingDetail(row,meta,view,parameter){
  if(!row)return "–";
  const raw=era5EuropeFormat(row.raw,meta.decimals,` ${meta.unit}`);
  const ref=era5EuropeFormat(row.reference,meta.decimals,` ${meta.unit}`);
  if(view==="absolute")return `Wert ${raw} · Mittel 1991–2020 ${ref}`;
  if(view==="percent")return `${raw} · Mittel ${ref}`;
  if(view==="percentile")return `${raw} · Referenzmittel ${ref}`;
  return `${raw} · Mittel 1991–2020 ${ref}`;
}
function era5EuropeRankingTitles(parameter,view){
  if(parameter==="temperature"&&view==="absolute")return ["Top 10 · Wärmste Gitterpunkte","Bottom 10 · Kälteste Gitterpunkte"];
  if(parameter==="temperature"&&view==="anomaly")return ["Top 10 · Stärkste positive Abweichungen","Bottom 10 · Stärkste negative Abweichungen"];
  if(parameter==="precipitation"&&view==="percent")return ["Top 10 · Nasseste relativ zum Mittel","Bottom 10 · Trockenste relativ zum Mittel"];
  if(parameter==="precipitation")return ["Top 10 · Höchste Niederschlagssummen","Bottom 10 · Niedrigste Niederschlagssummen"];
  if(parameter==="soil_moisture"&&view==="percentile")return ["Top 10 · Feuchteste Perzentile","Bottom 10 · Trockenste Perzentile"];
  if(parameter==="soil_moisture")return ["Top 10 · Höchste Bodenfeuchte","Bottom 10 · Niedrigste Bodenfeuchte"];
  if(parameter==="water_balance")return ["Top 10 · Größter Wasserüberschuss","Bottom 10 · Größtes Wasserdefizit"];
  if(parameter.startsWith("snow_"))return ["Top 10 · Schneereichste Gitterpunkte","Bottom 10 · Schneeärmste Gitterpunkte"];
  if(view==="anomaly")return ["Top 10 · Größte positive Abweichungen","Bottom 10 · Größte negative Abweichungen"];
  if(view==="percentile")return ["Top 10 · Höchste Perzentile","Bottom 10 · Niedrigste Perzentile"];
  return ["Top 10 · Höchste Kartenwerte","Bottom 10 · Niedrigste Kartenwerte"];
}
function era5EuropeRankingRank(point,parameter,layer,periodId,year){
  const series=era5EuropePointSeries(point,parameter,layer,periodId);if(!series)return null;
  const entries=era5EuropeFiniteEntries(series.years,series.history);
  return era5EuropeRankInfo(entries,year,parameter);
}
function era5EuropeRenderRankingMarkers(){
  const stage=document.getElementById("era5EuropeImageStage");if(!stage||!era5EuropeIndex)return;
  stage.querySelectorAll(".era5-ranking-pin").forEach(node=>node.remove());
  const g=era5EuropeIndex.click_geometry||{left:.07,top:.16,right:.96,bottom:.82},c=era5EuropeIndex.coverage||{west:-25,east:45,north:72,south:34};
  for(const item of era5EuropeRankingPoints.filter(item=>item.rank<=3)){
    const point=item.point;if(!point)continue;
    const x=g.left+(point.lon-c.west)/(c.east-c.west)*(g.right-g.left),y=g.top+(c.north-point.lat)/(c.north-c.south)*(g.bottom-g.top);
    const pin=document.createElement("div");pin.className=`era5-ranking-pin ${item.kind}`;pin.textContent=String(item.rank);pin.style.left=`${x*100}%`;pin.style.top=`${y*100}%`;pin.title=`${item.kind==="top"?"Top":"Bottom"} ${item.rank}: ${era5EuropeCoordinateLabel(point)}`;stage.appendChild(pin);
  }
}
function era5EuropeSelectRankingPoint(index){
  const item=era5EuropeRankingPoints.find(row=>row.index===Number(index));if(!item?.point)return;
  era5EuropeSelectedPoint=item.point;
  const panel=document.getElementById("era5EuropePointAnalysis");if(panel)panel.hidden=false;
  era5EuropePlaceMarker();renderEra5EuropePointAnalysis();
  if(panel)panel.scrollIntoView({behavior:"smooth",block:"start"});
}
function era5EuropeRankingItemHtml(row,pos,kind,index,meta,view,parameter){
  const rank=row.historyRank;
  const rankText=rank?`Hist. #${rank.rankHigh}/${rank.total} ↑ · #${rank.rankLow}/${rank.total} ↓`:"Historischer Rang –";
  return `<button class="era5-ranking-item" type="button" data-era5-rank-index="${index}"><span class="era5-ranking-pos">${pos}</span><span class="era5-ranking-main"><span class="era5-ranking-coord">${era5EuropeCoordinateLabel(row.point)}</span><span class="era5-ranking-detail">${era5EuropeRankingDetail(row,meta,view,parameter)}</span></span><span class="era5-ranking-value">${era5EuropeRankingValueText(row,meta,view,parameter)}<small>${rankText}</small></span></button>`;
}
async function renderEra5EuropeRankings(){
  const panel=document.getElementById("era5EuropeRanking");if(!panel||!era5EuropeIndex?.ready)return;
  const request=++era5EuropeRankingRequest;
  const top=document.getElementById("era5EuropeRankingTop"),bottom=document.getElementById("era5EuropeRankingBottom");
  if(top)top.innerHTML='<div class="era5-europe-loading">Ranking wird berechnet …</div>';if(bottom)bottom.innerHTML='<div class="era5-europe-loading">Ranking wird berechnet …</div>';
  try{await ensureEra5EuropeAnalysisLoaded();}catch(error){if(request!==era5EuropeRankingRequest)return;if(top)top.innerHTML=`<div class="era5-europe-loading">Ranking nicht verfügbar: ${error.message}</div>`;if(bottom)bottom.innerHTML="";return;}
  if(request!==era5EuropeRankingRequest)return;
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature",layer=document.getElementById("era5EuropeSoilLayer")?.value||"layer1",periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month",view=document.getElementById("era5EuropeView")?.value||"absolute";
  const period=era5EuropeIndex.periods?.[periodId],selectedYear=era5EuropeMapYear(),year=Number.isFinite(selectedYear)?selectedYear:Number(period?.year||era5EuropeAnalysis.analysis_year),meta=era5EuropeMetricMeta(parameter,layer);
  let rows=era5EuropeHistoricalField(parameter,layer,periodId,year,view);
  rows=rows.map(row=>({...row,historyRank:era5EuropeRankingRank(row.point,parameter,layer,periodId,year)})).filter(row=>Number.isFinite(Number(row.value)));
  if(!rows.length){if(top)top.innerHTML='<div class="era5-europe-loading">Für diese Auswahl sind keine Rankingwerte verfügbar.</div>';if(bottom)bottom.innerHTML="";for(const id of ["era5EuropeRankingMax","era5EuropeRankingMin","era5EuropeRankingHighRecords","era5EuropeRankingLowRecords"]){const el=document.getElementById(id);if(el)el.textContent="–";}for(const id of ["era5EuropeRankingMaxDetail","era5EuropeRankingMinDetail"]){const el=document.getElementById(id);if(el)el.textContent="–";}era5EuropeRankingPoints=[];era5EuropeRenderRankingMarkers();return;}
  const sorted=[...rows].sort((a,b)=>b.value-a.value),topRows=sorted.slice(0,10),bottomRows=[...rows].sort((a,b)=>a.value-b.value).slice(0,10),max=topRows[0],min=bottomRows[0];
  const highRecords=rows.filter(row=>row.historyRank?.rankHigh===1).length,lowRecords=rows.filter(row=>row.historyRank?.rankLow===1).length;
  document.getElementById("era5EuropeRankingTitle").textContent=`${meta.label} · Europa-Ranking ${year}`;
  document.getElementById("era5EuropeRankingSubtitle").textContent=`${periodId==="summer"?"Sommer":"Jüngster vollständiger Monat"} · ${document.getElementById("era5EuropeView")?.selectedOptions?.[0]?.textContent||view} · ${rows.length.toLocaleString("de-DE")} Landgitterpunkte auf 1,0°`;
  document.getElementById("era5EuropeRankingMax").textContent=era5EuropeRankingValueText(max,meta,view,parameter);document.getElementById("era5EuropeRankingMaxDetail").textContent=era5EuropeCoordinateLabel(max.point);
  document.getElementById("era5EuropeRankingMin").textContent=era5EuropeRankingValueText(min,meta,view,parameter);document.getElementById("era5EuropeRankingMinDetail").textContent=era5EuropeCoordinateLabel(min.point);
  document.getElementById("era5EuropeRankingHighRecords").textContent=highRecords.toLocaleString("de-DE");document.getElementById("era5EuropeRankingHighRecordsDetail").textContent=`${era5EuropeFormat(100*highRecords/rows.length,1," %")} der gültigen Gitterpunkte · lokaler historischer Höchstwert`;
  document.getElementById("era5EuropeRankingLowRecords").textContent=lowRecords.toLocaleString("de-DE");document.getElementById("era5EuropeRankingLowRecordsDetail").textContent=`${era5EuropeFormat(100*lowRecords/rows.length,1," %")} der gültigen Gitterpunkte · lokaler historischer Tiefstwert`;
  const [topTitle,bottomTitle]=era5EuropeRankingTitles(parameter,view);document.getElementById("era5EuropeRankingTopTitle").textContent=topTitle;document.getElementById("era5EuropeRankingBottomTitle").textContent=bottomTitle;
  era5EuropeRankingPoints=[];let idx=0;
  const topHtml=topRows.map((row,i)=>{const index=idx++;era5EuropeRankingPoints.push({index,point:row.point,kind:"top",rank:i+1});return era5EuropeRankingItemHtml(row,i+1,"top",index,meta,view,parameter);}).join("");
  const bottomHtml=bottomRows.map((row,i)=>{const index=idx++;era5EuropeRankingPoints.push({index,point:row.point,kind:"bottom",rank:i+1});return era5EuropeRankingItemHtml(row,i+1,"bottom",index,meta,view,parameter);}).join("");
  if(top)top.innerHTML=topHtml;if(bottom)bottom.innerHTML=bottomHtml;
  panel.querySelectorAll("[data-era5-rank-index]").forEach(button=>button.addEventListener("click",()=>era5EuropeSelectRankingPoint(button.dataset.era5RankIndex)));
  era5EuropeRenderRankingMarkers();
  const foot=document.getElementById("era5EuropeRankingFoot");if(foot)foot.textContent=`Historischer Rang am jeweiligen Gitterpunkt: ${parameter==="soil_moisture"?"1991–2020 plus aktuelles Jahr":"1950 bis zum aktuellen Jahr"}. Die sichtbare Karte nutzt 0,1°; Top/Bottom und historische Ränge werden bewusst auf dem vergleichbaren 1,0°-Analyseraster berechnet.`;
}
function era5EuropeMetricMeta(parameter,layer){
  if(parameter==="temperature")return {label:"2-m-Temperatur",unit:"°C",decimals:2};
  if(parameter==="precipitation")return {label:"Niederschlag",unit:"mm",decimals:1};
  if(parameter==="soil_moisture")return {label:`Bodenfeuchte ${era5EuropeSoilLayerLabel(layer)}`,unit:"m³/m³",decimals:4};
  if(parameter==="snow_depth")return {label:"Schneehöhe",unit:"cm",decimals:1};
  if(parameter==="snow_water_equivalent")return {label:"Schneewasseräquivalent",unit:"mm",decimals:1};
  if(parameter==="snow_cover")return {label:"Schneebedeckung",unit:"%",diffUnit:"Prozentpunkte",decimals:1};
  const labels={evaporation:"Gesamtverdunstung",runoff:"Gesamtabfluss",surface_runoff:"Oberflächenabfluss",sub_surface_runoff:"Unterirdischer Abfluss",water_balance:"Wasserbilanz P − E"};
  return {label:labels[parameter]||parameter,unit:"mm",decimals:1};
}
function era5EuropePointSeries(point,parameter,layer,periodId){
  if(!point)return null;
  const monthly=parameter==="soil_moisture"?point.monthly?.soil_moisture?.layers?.[layer]:point.monthly?.[parameter];
  const history=parameter==="soil_moisture"?point.history?.[periodId]?.soil_moisture?.layers?.[layer]:point.history?.[periodId]?.[parameter];
  const years=parameter==="soil_moisture"?era5EuropeAnalysis?.soil_history_years?.[periodId]:era5EuropeAnalysis?.history_years?.[periodId];
  return {monthly,history,years};
}
function era5EuropeFiniteEntries(years,values){
  return (years||[]).map((year,i)=>({year:Number(year),value:Number(values?.[i])})).filter(item=>Number.isFinite(item.value));
}
function era5EuropeRankInfo(entries,currentYear,parameter){
  const target=[...entries].reverse().find(item=>item.year===Number(currentYear));if(!target)return null;
  const above=entries.filter(item=>item.value>target.value).length,below=entries.filter(item=>item.value<target.value).length,equal=entries.filter(item=>item.value===target.value).length;
  let highWord="höchste",lowWord="niedrigste";
  if(parameter==="temperature"){highWord="wärmste";lowWord="kälteste";}
  else if(parameter==="precipitation"){highWord="nasseste";lowWord="trockenste";}
  else if(parameter==="soil_moisture"){highWord="feuchteste";lowWord="trockenste";}
  else if(parameter==="snow_depth"){highWord="schneereichste";lowWord="schneeärmste";}
  else if(parameter==="snow_water_equivalent"){highWord="schneewasserreichste";lowWord="schneewasserärmste";}
  else if(parameter==="snow_cover"){highWord="schneebedeckteste";lowWord="schneeärmste";}
  else if(parameter==="evaporation"){highWord="verdunstungsreichste";lowWord="verdunstungsärmste";}
  else if(parameter==="water_balance"){highWord="wasserreichste";lowWord="trockenste";}
  else {highWord="abflussreichste";lowWord="abflussärmste";}
  return {value:target.value,rankHigh:above+1,rankLow:below+1,total:entries.length,percentile:100*(below+0.5*equal)/entries.length,highWord,lowWord};
}
function era5EuropePointReference(entries,parameter){
  const ref=entries.filter(item=>item.year>=1991&&item.year<=2020).map(item=>item.value).filter(Number.isFinite);
  if(!ref.length)return null;
  return ref.reduce((a,b)=>a+b,0)/ref.length;
}
function era5EuropeNearestPoint(lat,lon){
  const points=era5EuropeAnalysis?.points||[];let best=null,bestD=Infinity;
  const cos=Math.cos(lat*Math.PI/180);
  for(const point of points){const dy=point.lat-lat,dx=(point.lon-lon)*cos,d=dx*dx+dy*dy;if(d<bestD){bestD=d;best=point;}}
  return best;
}
function era5EuropePlaceMarker(){
  const marker=document.getElementById("era5EuropePointMarker");
  if(!marker||!era5EuropeSelectedPoint||!era5EuropeIndex)return;
  const g=era5EuropeIndex.click_geometry||{left:.07,top:.16,right:.96,bottom:.82};
  const c=era5EuropeIndex.coverage||{west:-25,east:45,north:72,south:34};
  const x=g.left+(era5EuropeSelectedPoint.lon-c.west)/(c.east-c.west)*(g.right-g.left);
  const y=g.top+(c.north-era5EuropeSelectedPoint.lat)/(c.north-c.south)*(g.bottom-g.top);
  marker.style.left=`${x*100}%`;marker.style.top=`${y*100}%`;marker.style.display="block";
}
// ERA5_TP_CURRENT_MONTHS_FRONTEND_V1
async function era5EuropeHandleMapClick(event){
  const selectedPeriodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";
  if(era5EuropeIndex?.periods?.[selectedPeriodId]?.analysis_ready===false)return;
  const stage=document.getElementById("era5EuropeImageStage");if(!stage||!era5EuropeIndex)return;
  const rect=stage.getBoundingClientRect();const nx=(event.clientX-rect.left)/rect.width,ny=(event.clientY-rect.top)/rect.height;
  const g=era5EuropeIndex.click_geometry||{left:.07,top:.16,right:.96,bottom:.82};
  if(nx<g.left||nx>g.right||ny<g.top||ny>g.bottom)return;
  const c=era5EuropeIndex.coverage||{west:-25,east:45,north:72,south:34};
  const lon=c.west+(nx-g.left)/(g.right-g.left)*(c.east-c.west);
  const lat=c.north-(ny-g.top)/(g.bottom-g.top)*(c.north-c.south);
  const panel=document.getElementById("era5EuropePointAnalysis");if(panel)panel.hidden=false;
  const title=document.getElementById("era5EuropePointTitle");if(title)title.textContent="Gitterpunktanalyse wird geladen …";
  try{
    await ensureEra5EuropeAnalysisLoaded();
    era5EuropeSelectedPoint=era5EuropeNearestPoint(lat,lon);
    if(!era5EuropeSelectedPoint)throw new Error("Kein ERA5-Land-Punkt in der Nähe gefunden.");
    era5EuropePlaceMarker();renderEra5EuropePointAnalysis();
  }catch(error){console.error(error);if(title)title.textContent="Gitterpunktanalyse nicht verfügbar";const sub=document.getElementById("era5EuropePointSubtitle");if(sub)sub.textContent=error.message;}
}
function era5EuropeUpdateCompareOptions(years,currentYear){
  const select=document.getElementById("era5EuropeCompareYear");if(!select)return;
  const previous=Number(select.value);
  const choices=(years||[]).map(Number).filter(y=>y!==Number(currentYear));
  select.innerHTML=choices.slice().reverse().map(y=>`<option value="${y}">${y}</option>`).join("");
  if(choices.includes(previous))select.value=String(previous);
  else if(choices.includes(2003))select.value="2003";
  else if(choices.length)select.value=String(choices[choices.length-1]);
}
function renderEra5EuropePointAnalysis(){
  if(!era5EuropeSelectedPoint||!era5EuropeAnalysis?.ready)return;
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const layer=document.getElementById("era5EuropeSoilLayer")?.value||"layer1";
  const periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";
  const period=era5EuropeIndex?.periods?.[periodId];
  const meta=era5EuropeMetricMeta(parameter,layer);
  const series=era5EuropePointSeries(era5EuropeSelectedPoint,parameter,layer,periodId);if(!series)return;
  const entries=era5EuropeFiniteEntries(series.years,series.history);
  const currentYear=Number(period?.year||era5EuropeAnalysis.analysis_year);
  const selectedMapYear=era5EuropeMapYear();
  const displayYear=Number.isFinite(selectedMapYear)?selectedMapYear:currentYear;
  const rank=era5EuropeRankInfo(entries,displayYear,parameter);
  const reference=era5EuropePointReference(entries,parameter);
  era5EuropeUpdateCompareOptions(series.years,displayYear);
  const compareYear=Number(document.getElementById("era5EuropeCompareYear")?.value);
  const compare=entries.find(item=>item.year===compareYear)||null;
  const point=era5EuropeSelectedPoint;
  const latText=`${Math.abs(point.lat).toLocaleString("de-DE",{maximumFractionDigits:1})}° ${point.lat>=0?"N":"S"}`;
  const lonText=`${Math.abs(point.lon).toLocaleString("de-DE",{maximumFractionDigits:1})}° ${point.lon>=0?"E":"W"}`;
  document.getElementById("era5EuropePointTitle").textContent=`${meta.label} · ${latText}, ${lonText}`;
  document.getElementById("era5EuropePointSubtitle").textContent=`${Number.isFinite(selectedMapYear)?`${displayYear} · historische Karte`:period?.label||"Zeitraum"} · nächster ERA5-Land-Analysepunkt · ${era5EuropeAnalysis.analysis_grid}`;
  const currentLabel=document.getElementById("era5EuropePointCurrentLabel");if(currentLabel)currentLabel.textContent=Number.isFinite(selectedMapYear)?`Kartenjahr ${displayYear}`:"Aktueller Zeitraum";
  const current=rank?.value;
  document.getElementById("era5EuropePointCurrent").textContent=era5EuropeFormat(current,meta.decimals,` ${meta.unit}`);
  let currentDetail="";
  if(Number.isFinite(current)&&Number.isFinite(reference)){
    if(parameter==="precipitation") currentDetail=`${era5EuropeFormat(current/reference*100,0," %")} vom Mittel`;
    else currentDetail=`${era5EuropeFormat(current-reference,meta.decimals,` ${parameter==="temperature"?"K":meta.diffUnit||meta.unit}`)} zum Mittel`;
  }
  if(parameter==="soil_moisture" || ["evaporation","runoff","surface_runoff","sub_surface_runoff","water_balance","snow_depth","snow_water_equivalent","snow_cover"].includes(parameter)){
    const pct=rank?.percentile;if(Number.isFinite(pct))currentDetail+=`${currentDetail?" · ":""}P${Math.round(pct)}`;
  }
  document.getElementById("era5EuropePointCurrentDetail").textContent=currentDetail||"–";
  document.getElementById("era5EuropePointReference").textContent=era5EuropeFormat(reference,meta.decimals,` ${meta.unit}`);
  document.getElementById("era5EuropePointRank").textContent=rank?`#${rank.rankHigh} / ${rank.total}`:"–";
  document.getElementById("era5EuropePointRankDetail").textContent=rank?`${rank.rankHigh}. ${rank.highWord} · ${rank.rankLow}. ${rank.lowWord} · P${rank.percentile.toFixed(0)}`:"–";
  document.getElementById("era5EuropePointCompareLabel").textContent=Number.isFinite(compareYear)?`Vergleich ${compareYear}`:"Vergleichsjahr";
  document.getElementById("era5EuropePointCompare").textContent=compare?era5EuropeFormat(compare.value,meta.decimals,` ${meta.unit}`):"–";
  document.getElementById("era5EuropePointCompareDetail").textContent=compare&&Number.isFinite(current)?`${displayYear} ${era5EuropeFormat(current-compare.value,meta.decimals,` ${parameter==="temperature"?"K":meta.diffUnit||meta.unit}`)} dazu`:"–";
  const monthly=series.monthly||{};const labels=era5EuropeAnalysis.month_labels||[];
  const currentMonthly=monthly.current||[],refMonthly=monthly.reference||[];
  if(era5EuropePointMonthlyChart)era5EuropePointMonthlyChart.destroy();
  const monthlyCanvas=document.getElementById("era5EuropePointMonthlyChart");
  era5EuropePointMonthlyChart=new Chart(monthlyCanvas,{type:"line",data:{labels,datasets:[
    {label:String(era5EuropeAnalysis.analysis_year),data:currentMonthly,borderWidth:2.4,pointRadius:2.2,tension:.15,spanGaps:true},
    {label:"1991–2020",data:refMonthly,borderWidth:1.8,borderDash:[6,4],pointRadius:0,tension:.15,spanGaps:true}
  ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{position:"top"}},scales:{y:{title:{display:true,text:meta.unit}}}}});
  const monthlySub=document.getElementById("era5EuropePointMonthlySubtitle");
  if(monthlySub)monthlySub.textContent=`Monatswerte ${era5EuropeAnalysis.analysis_year} bis ${labels[labels.length-1]||"–"} gegen 1991–2020`;
  if(era5EuropePointHistoryChart)era5EuropePointHistoryChart.destroy();
  const histCanvas=document.getElementById("era5EuropePointHistoryChart");
  const histLabels=entries.map(item=>item.year),histValues=entries.map(item=>item.value);
  const currentData=entries.map(item=>item.year===displayYear?item.value:null);
  const compareData=entries.map(item=>item.year===compareYear?item.value:null);
  era5EuropePointHistoryChart=new Chart(histCanvas,{type:"line",data:{labels:histLabels,datasets:[
    {label:period?.label||"Historie",data:histValues,borderWidth:1.3,pointRadius:0,tension:0,spanGaps:true},
    {label:String(displayYear),data:currentData,showLine:false,pointRadius:6,pointHoverRadius:7},
    {label:Number.isFinite(compareYear)?String(compareYear):"Vergleich",data:compareData,showLine:false,pointRadius:5,pointHoverRadius:6}
  ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"nearest",intersect:false},plugins:{legend:{position:"top"}},scales:{x:{ticks:{maxTicksLimit:12}},y:{title:{display:true,text:meta.unit}}}}});
  const histSub=document.getElementById("era5EuropePointHistorySubtitle");
  if(histSub)histSub.textContent=parameter==="soil_moisture"?"1991–2020 plus aktuelles Jahr":"ERA5-Land seit 1950 bis zum aktuellen Jahr";
  const foot=document.getElementById("era5EuropePointFoot");
  if(foot)foot.textContent=`${era5EuropeAnalysis.history_note||""} Die Klickanalyse und Rankings nutzen ${era5EuropeAnalysis.analysis_grid}; sichtbare aktuelle und historische Karten bleiben 0,1°.`.trim();
}
function era5EuropePeriodDataThrough(period){return period?.running_data_through||era5EuropeIndex?.data_through||"–";}
function renderEra5Europe(){
  if(!era5EuropeIndex?.ready)return;
  era5EuropeSyncPeriodOptionLabels();
  if(Number.isFinite(era5EuropeMapYear())){renderEra5EuropeHistorical();return;}
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const soilLayer=document.getElementById("era5EuropeSoilLayer")?.value||"layer1";
  const periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";
  const defaultView=parameter==="precipitation"?"percent":parameter==="soil_moisture"?"percentile":"anomaly";
  const view=document.getElementById("era5EuropeView")?.value||defaultView;
  const period=era5EuropeIndex.periods?.[periodId];let parameterData=period?.[parameter];
  if(parameter==="soil_moisture")parameterData=parameterData?.layers?.[soilLayer]||(soilLayer==="layer1"?parameterData:null);
  const mapInfo=parameterData?.[view];if(!period)return;
  const meta=era5EuropeMetricMeta(parameter,soilLayer),title=meta.label;
  if(!parameterData||!mapInfo){
    const wrap=document.getElementById("era5EuropeImageWrap");if(wrap)wrap.innerHTML='<div class="era5-europe-loading">Dieser ERA5-Land-Parameter wird mit dem nächsten erfolgreichen Europa-Workflow aufgebaut.</div>';
    document.getElementById("era5EuropeMapTitle").textContent=`${title} · ${period.label}`;document.getElementById("era5EuropeMapSubtitle").textContent="Daten noch nicht erzeugt";
    document.getElementById("era5EuropePeriodKpi").textContent=period.label;document.getElementById("era5EuropeDataKpi").textContent=`Datenstand ${era5EuropePeriodDataThrough(period)}`;
    document.getElementById("era5EuropeCurrentKpi").textContent="–";document.getElementById("era5EuropeReferenceKpi").textContent="–";document.getElementById("era5EuropeDifferenceKpi").textContent="–";
    const diffLabel=document.getElementById("era5EuropeDifferenceLabel");if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeDifferenceDetail").textContent="V8-Daten noch nicht erzeugt";return;
  }
  document.getElementById("era5EuropeMapTitle").textContent=`${title} · ${period.label}`;
  document.getElementById("era5EuropeMapSubtitle").textContent=`${mapInfo.label||view} · ERA5-Land · Landflächen · Karte anklicken für Gitterpunktanalyse`;
  document.getElementById("era5EuropePeriodKpi").textContent=period.label;document.getElementById("era5EuropeDataKpi").textContent=`Datenstand ${era5EuropePeriodDataThrough(period)}`;
  const stats=parameterData.stats||{},diffLabel=document.getElementById("era5EuropeDifferenceLabel");
  if(parameter==="temperature"){
    if(view==="rank"){
      const rankStats=parameterData?.rank?.stats||{};
      if(diffLabel)diffLabel.textContent="Rang-1-Fläche";document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,2," °C");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,2," °C");document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(rankStats.rank_area_percent,1," %");document.getElementById("era5EuropeDifferenceDetail").textContent=`Rang 1 = wärmster Wert seit ${parameterData?.rank?.history_start||1950} · Top 3: ${era5EuropeFormat(rankStats.top3_area_percent,1," %")}`;
    }else{
      if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,2," °C");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,2," °C");document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.difference,2," K");document.getElementById("era5EuropeDifferenceDetail").textContent="Temperaturabweichung zum Mittel";
    }
  }else if(parameter==="precipitation"){
    if(diffLabel)diffLabel.textContent="Vom Mittel";document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,1," mm");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,1," mm");document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.percent,0," %");document.getElementById("era5EuropeDifferenceDetail").textContent="Prozent des Niederschlagsmittels";
  }else if(parameter==="soil_moisture"){
    document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,3," m³/m³");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,3," m³/m³");
    if(view==="percentile"){if(diffLabel)diffLabel.textContent="Trockenflächen";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.dry_area_percent,0," %");document.getElementById("era5EuropeDifferenceDetail").textContent=`≤ P20 · davon ≤ P10: ${era5EuropeFormat(stats.very_dry_area_percent,0," %")} · ≥ P80: ${era5EuropeFormat(stats.wet_area_percent,0," %")}`;}
    else{if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.difference,3," m³/m³");document.getElementById("era5EuropeDifferenceDetail").textContent="Bodenfeuchteabweichung zum Mittel";}
  }else if(["snow_depth","snow_water_equivalent","snow_cover"].includes(parameter)){
    const unit=meta.unit;document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,1,` ${unit}`);document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,1,` ${unit}`);
    if(view==="percentile"){if(diffLabel)diffLabel.textContent="Schneearm";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.low_area_percent,0," %");document.getElementById("era5EuropeDifferenceDetail").textContent=`≤ P20 · davon ≤ P10: ${era5EuropeFormat(stats.very_low_area_percent,0," %")} · ≥ P80: ${era5EuropeFormat(stats.high_area_percent,0," %")}`;}
    else{if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.difference,1,` ${meta.diffUnit||unit}`);document.getElementById("era5EuropeDifferenceDetail").textContent=`${title} gegenüber 1991–2020`;}
  }else{
    document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,1," mm");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,1," mm");
    if(view==="percentile"){if(diffLabel)diffLabel.textContent="Ungewöhnlich niedrig";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.low_area_percent,0," %");document.getElementById("era5EuropeDifferenceDetail").textContent=`≤ P20 · davon ≤ P10: ${era5EuropeFormat(stats.very_low_area_percent,0," %")} · ≥ P80: ${era5EuropeFormat(stats.high_area_percent,0," %")}`;}
    else{if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.difference,1," mm");document.getElementById("era5EuropeDifferenceDetail").textContent=`${title} gegenüber 1991–2020`;}
  }
  const imageUrl=`${ERA5_EUROPE_RAW_BASE}${mapInfo.file}?v=${encodeURIComponent(era5EuropeIndex.generated_at||Date.now())}`,wrap=document.getElementById("era5EuropeImageWrap");
  if(wrap){wrap.innerHTML=`<div id="era5EuropeImageStage" class="era5-europe-image-stage"><img id="era5EuropeImage" class="era5-europe-image" alt="${title} ${period.label}" src="${imageUrl}"><div id="era5EuropePointMarker" class="era5-europe-point-marker"></div><div class="era5-europe-click-hint">Karte anklicken<br>→ Gitterpunktanalyse</div></div>`;const stage=document.getElementById("era5EuropeImageStage"),img=document.getElementById("era5EuropeImage");stage?.addEventListener("click",era5EuropeHandleMapClick);img?.addEventListener("load",era5EuropePlaceMarker);img?.addEventListener("error",()=>{wrap.innerHTML='<div class="era5-europe-loading">Die Karten-PNG konnte nicht geladen werden.</div>';});}
  const source=document.getElementById("era5EuropeSource");if(source){let extra=era5EuropeIndex.availability_note||"";if(view==="percentile")extra=era5EuropeIndex.percentile_note||extra;if(parameter==="temperature"&&view==="rank")extra=parameterData?.rank?.note||`Historischer Temperaturrang seit ${parameterData?.rank?.history_start||1950}; Rang 1 ist der wärmste Wert am jeweiligen 0,1°-Gitterpunkt.`;if(["evaporation","runoff","surface_runoff","sub_surface_runoff","water_balance"].includes(parameter))extra=`${era5EuropeIndex.water_budget_note||""} ${extra}`.trim();if(["snow_depth","snow_water_equivalent","snow_cover"].includes(parameter))extra=`${era5EuropeIndex.snow_note||""} ${extra}`.trim();source.textContent=`Quelle: ${era5EuropeIndex.source}. ${extra}`.trim();}
  const rankPanel=document.getElementById("era5EuropeRanking"),rankView=parameter==="temperature"&&view==="rank";
  if(rankPanel)rankPanel.hidden=rankView;
  if(rankView){if(era5EuropeSelectedPoint&&era5EuropeAnalysis?.ready)renderEra5EuropePointAnalysis();return;}
  if(period?.analysis_ready===false){
    era5EuropeShowMonthlyRankingPending(meta,period,Number(period?.year));
  }else{
    if(era5EuropeSelectedPoint&&era5EuropeAnalysis?.ready)renderEra5EuropePointAnalysis();
    renderEra5EuropeRankings();
  }
}
async function downloadEra5EuropeMap(){
  if(!era5EuropeIndex?.ready)return;
  const historicalYear=era5EuropeMapYear();
  if(Number.isFinite(historicalYear)){
    const stage=document.getElementById("era5EuropeImageStage"),button=document.getElementById("era5EuropeDownload"),original=button?.textContent;if(!stage)return;if(button){button.disabled=true;button.textContent="…";}
    try{const canvas=await window.captureDashboardWithWhiteBackground(stage,{backgroundColor:"#ffffff",scale:2,useCORS:true});const link=document.createElement("a");const parameter=document.getElementById("era5EuropeParameter")?.value||"parameter",periodId=document.getElementById("era5EuropePeriod")?.value||"period",view=document.getElementById("era5EuropeView")?.value||"view";link.href=canvas.toDataURL("image/png");link.download=`era5_land_europa_${parameter}_${historicalYear}_${periodId}_${view}_0p1deg.png`;link.click();}catch(error){console.error(error);alert(`PNG-Download nicht möglich: ${error.message}`);}finally{if(button){button.disabled=false;button.textContent=original;}}return;
  }
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";const soilLayer=document.getElementById("era5EuropeSoilLayer")?.value||"layer1";const periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";const view=document.getElementById("era5EuropeView")?.value||"absolute";
  let parameterData=era5EuropeIndex.periods?.[periodId]?.[parameter];if(parameter==="soil_moisture")parameterData=parameterData?.layers?.[soilLayer]||(soilLayer==="layer1"?parameterData:null);const mapInfo=parameterData?.[view];if(!mapInfo)return;
  const button=document.getElementById("era5EuropeDownload"),original=button?.textContent;if(button){button.disabled=true;button.textContent="…";}
  try{const response=await fetch(`${ERA5_EUROPE_RAW_BASE}${mapInfo.file}?download=${Date.now()}`,{cache:"no-store"});if(!response.ok)throw new Error(`HTTP ${response.status}`);const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement("a");const layerPart=parameter==="soil_moisture"?`_${soilLayer}`:"";link.href=url;link.download=`era5_land_europa_${parameter}${layerPart}_${periodId}_${view}.png`;document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);}catch(error){console.error(error);alert(`PNG-Download nicht möglich: ${error.message}`);}finally{if(button){button.disabled=false;button.textContent=original;}}
}
function clearEra5EuropePoint(){
  era5EuropeSelectedPoint=null;const panel=document.getElementById("era5EuropePointAnalysis");if(panel)panel.hidden=true;const marker=document.getElementById("era5EuropePointMarker");if(marker)marker.style.display="none";if(era5EuropePointMonthlyChart){era5EuropePointMonthlyChart.destroy();era5EuropePointMonthlyChart=null;}if(era5EuropePointHistoryChart){era5EuropePointHistoryChart.destroy();era5EuropePointHistoryChart=null;}
}
function initEra5EuropeControls(){
  const parameter=document.getElementById("era5EuropeParameter"),soilLayer=document.getElementById("era5EuropeSoilLayer"),period=document.getElementById("era5EuropePeriod"),mapYear=document.getElementById("era5EuropeMapYear"),view=document.getElementById("era5EuropeView"),download=document.getElementById("era5EuropeDownload"),compare=document.getElementById("era5EuropeCompareYear"),clear=document.getElementById("era5EuropeClearPoint");if(!parameter||!period||!view)return;
  era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdateMapYearOptions();era5EuropeUpdateViewOptions();
  parameter.addEventListener("change",()=>{era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdatePeriodOptions();era5EuropeUpdateMapYearOptions();era5EuropeUpdateViewOptions();renderEra5Europe();});soilLayer?.addEventListener("change",()=>{renderEra5Europe();});period.addEventListener("change",()=>{era5EuropeUpdateMapYearOptions();era5EuropeUpdateViewOptions();renderEra5Europe();});mapYear?.addEventListener("change",()=>{era5EuropeUpdateViewOptions();renderEra5Europe();});view.addEventListener("change",renderEra5Europe);download?.addEventListener("click",downloadEra5EuropeMap);compare?.addEventListener("change",renderEra5EuropePointAnalysis);clear?.addEventListener("click",clearEra5EuropePoint);
}
initEra5EuropeControls();
function initEra5RunningTemperatureRankControls(){
  document.querySelectorAll("[data-era5-running-rank-product]").forEach(button=>{
    button.addEventListener("click",()=>{
      const product=button.dataset.era5RunningRankProduct;
      if(!product||product===era5RunningTemperatureRankProduct)return;
      era5RunningTemperatureRankProduct=product;
      renderEra5RunningTemperatureRanks();
    });
  });
  document.getElementById("era5RunningRankDownloadPng")?.addEventListener("click",downloadEra5RunningRankPng);
  document.getElementById("era5RunningRankDownloadPdf")?.addEventListener("click",downloadEra5RunningRankPdf);
  document.getElementById("era5RunningRankPrev")?.addEventListener("click",()=>era5RunningRankStep(-1));
  document.getElementById("era5RunningRankNext")?.addEventListener("click",()=>era5RunningRankStep(1));
  document.getElementById("era5RunningRankPlay")?.addEventListener("click",era5RunningRankTogglePlay);
  document.getElementById("era5RunningRankSlider")?.addEventListener("input",event=>era5RunningRankSliderInput(event.target.value));
}
initEra5RunningTemperatureRankControls();
