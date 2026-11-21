
// ================= VERSION 9: ZUSTAND, MOBILE NAVIGATION, CSV =================
// ================= VERSION 15.1: HYRAS-FLÄCHENKARTEN =================
function hyrasNum(value,unit="",digits=1){
  const n=Number(value);
  if(!Number.isFinite(n)) return "–";
  return `${n.toLocaleString("de-DE",{minimumFractionDigits:digits,maximumFractionDigits:digits})}${unit?` ${unit}`:""}`;
}
function hyrasDate(value){
  if(!value) return "–";
  const d=new Date(`${value}T12:00:00Z`);
  return Number.isNaN(d.getTime())?value:d.toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
}
async function hyrasFetchJson(path){
  const sep=path.includes("?")?"&":"?";
  const response=await fetch(`${HYRAS_DATA_BASE}/${path}${sep}t=${Date.now()}`,{cache:"no-store"});
  if(!response.ok) throw new Error(`HYRAS-Datei ${path} nicht erreichbar (HTTP ${response.status})`);
  return response.json();
}
// HYRAS_REFERENCE_PERIOD_SELECTOR_V1
function hyrasReferencePeriod(){return document.getElementById("hyrasReferenceSelect")?.value||"1991-2020";}
function hyrasReferenceDisplay(){return hyrasReferencePeriod().replace("-","–");}
function hyrasReferenceYears(){const parts=hyrasReferencePeriod().split("-").map(Number);return {start:parts[0]||1991,end:parts[1]||2020};}
function hyrasReferenceSlug(){return hyrasReferencePeriod().replace("-","_");}
function hyrasReferenceFiles(manifest){
  const ref=hyrasReferencePeriod();
  return manifest?.reference_files_by_period?.[ref]||manifest?.reference_files||{};
}
function hyrasMetricConfig(metric){
  if(metric==="sum") return {key:"sum",label:"Niederschlagssumme"};
  if(metric==="anomaly") return {key:"anomaly",label:"Abweichung in l/m²"};
  return {key:"percent",label:`Prozent des Mittels ${hyrasReferenceDisplay()}`};
}
function hyrasSelectedPeriod(){
  const periods=hyrasIndex?.periods||[];
  const selected=document.getElementById("hyrasPeriodSelect")?.value;
  return periods.find(period=>period.key===selected)||periods.find(period=>period.key===hyrasIndex?.default_period)||periods[0]||null;
}
function populateHyrasPeriods(){
  // A delayed precipitation refresh must not replace the temperature options.
  if(hyrasParameter()!=="precipitation")return;
  const select=document.getElementById("hyrasPeriodSelect");
  if(!select || !hyrasIndex) return;
  const periods=hyrasIndex.periods||[];
  const previous=select.value;
  select.innerHTML="";
  const customGroup=document.createElement("optgroup");customGroup.label="Eigener Zeitraum";
  const customOption=document.createElement("option");customOption.value="__custom__";customOption.textContent="Freier Zeitraum …";customGroup.appendChild(customOption);
  const historicalOption=document.createElement("option");historicalOption.value="__historical__";historicalOption.textContent="Historische Auswahl …";customGroup.appendChild(historicalOption);select.appendChild(customGroup);
  const groups={month:[],season:[],summary:[],current:[]};
  periods.forEach(period=>{
    if(period.period_type==="month") groups.month.push(period);
    else if(period.period_type==="season") groups.season.push(period);
    else if(["month_live","season_live","summer_live","ytd_live"].includes(period.period_type)) groups.current.push(period);
    else groups.summary.push(period);
  });
  const addGroup=(label,rows)=>{
    if(!rows.length) return;
    const group=document.createElement("optgroup");group.label=label;
    rows.forEach(period=>{const option=document.createElement("option");option.value=period.key;option.textContent=`${period.label} · ${period.date_label||""}`;group.appendChild(option);});
    select.appendChild(group);
  };
  addGroup("Aktuell bis zum jüngsten HYRAS-Tag",groups.current);
  addGroup("Weitere Zeiträume",groups.summary);
  addGroup("Abgeschlossene Jahreszeiten",groups.season);
  addGroup("Abgeschlossene Monate",groups.month);
  const target=["__custom__","__historical__"].includes(previous)?previous:((previous&&periods.some(p=>p.key===previous))?previous:(periods.find(p=>p.period_type==="month_live")?.key||hyrasIndex.default_period||periods[0]?.key||""));
  select.value=target;
}
async function hyrasLoadWebManifest(){
  if(hyrasWebManifest) return hyrasWebManifest;
  const path=hyrasIndex?.web_manifest||"hyras_web_manifest.json";
  hyrasWebManifest=await hyrasFetchJson(path);
  const start=document.getElementById("hyrasCustomStart");
  const end=document.getElementById("hyrasCustomEnd");
  if(start){start.min=hyrasWebManifest.first_date;start.max=hyrasWebManifest.last_date;if(!start.value)start.value=`${hyrasWebManifest.year}-06-01`>=hyrasWebManifest.first_date?`${hyrasWebManifest.year}-06-01`:hyrasWebManifest.first_date;}
  if(end){end.min=hyrasWebManifest.first_date;end.max=hyrasWebManifest.last_date;if(!end.value)end.value=hyrasWebManifest.last_date;}
  return hyrasWebManifest;
}
async function hyrasLoadHistoricalManifest(){
  if(hyrasHistoricalManifest) return hyrasHistoricalManifest;
  const path=hyrasIndex?.historical_manifest||"hyras_historical_manifest.json";
  hyrasHistoricalManifest=await hyrasFetchJson(path);
  const yearSelect=document.getElementById("hyrasHistoricalYear");
  if(yearSelect){
    const previous=yearSelect.value;
    const years=[...(hyrasHistoricalManifest.years||[])].sort((a,b)=>b-a);
    yearSelect.innerHTML=years.map(year=>`<option value="${year}">${year}</option>`).join("");
    if(previous&&years.includes(Number(previous))) yearSelect.value=previous;
    else if(years.length) yearSelect.value=String(years[0]);
  }
  const monthSelect=document.getElementById("hyrasHistoricalMonth");
  if(monthSelect&&!monthSelect.dataset.initialized){
    monthSelect.value=String(hyrasIndex?.latest_complete_month||7);
    monthSelect.dataset.initialized="1";
  }
  return hyrasHistoricalManifest;
}
function hyrasHistoricalSelection(year,type,month){
  if(type==="month") return [{year,month}];
  if(type==="spring") return [3,4,5].map(m=>({year,month:m}));
  if(type==="summer") return [6,7,8].map(m=>({year,month:m}));
  if(type==="autumn") return [9,10,11].map(m=>({year,month:m}));
  if(type==="winter") return [{year:year-1,month:12},{year,month:1},{year,month:2}];
  return Array.from({length:12},(_,i)=>({year,month:i+1}));
}
function hyrasHistoricalLabel(year,type,month){
  const names=["","Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
  if(type==="month") return `${names[month]} ${year}`;
  if(type==="spring") return `Frühling ${year}`;
  if(type==="summer") return `Sommer ${year}`;
  if(type==="autumn") return `Herbst ${year}`;
  if(type==="winter") return `Winter ${year}`;
  return `Jahr ${year}`;
}
function hyrasHistoricalDateLabel(year,type,month){
  const pad=n=>String(n).padStart(2,"0");
  const last=(y,m)=>new Date(Date.UTC(y,m,0)).getUTCDate();
  if(type==="month") return `01.${pad(month)}.–${pad(last(year,month))}.${pad(month)}.${year}`;
  if(type==="spring") return `01.03.–31.05.${year}`;
  if(type==="summer") return `01.06.–31.08.${year}`;
  if(type==="autumn") return `01.09.–30.11.${year}`;
  if(type==="winter") return `01.12.${year-1}–${String(last(year,2)).padStart(2,"0")}.02.${year}`;
  return `01.01.–31.12.${year}`;
}
function hyrasHistoricalMonthPath(manifest,year,month){
  return (manifest.month_file_pattern||"historical/{year}/month_{month}.png").replace("{year}",String(year)).replace("{month}",String(month).padStart(2,"0"));
}
async function hyrasLoadHistoricalMonth(year,month){
  const manifest=await hyrasLoadHistoricalManifest();
  const path=hyrasHistoricalMonthPath(manifest,year,month);
  const encoded=await hyrasLoadEncodedRaster(path);
  return hyrasDecodeEncodedRaster(encoded,manifest.value_scale||10);
}
async function hyrasLoadHistoricalReference(month){
  const manifest=await hyrasLoadHistoricalManifest();
  const path=hyrasReferenceFiles(manifest)?.[String(month)];
  if(!path) throw new Error(`Referenzraster ${hyrasReferenceDisplay()} für Monat ${month} fehlt.`);
  const encoded=await hyrasLoadEncodedRaster(path);
  return hyrasDecodeEncodedRaster(encoded,manifest.value_scale||10);
}
function hyrasSumRasters(rasters){
  if(!rasters.length) throw new Error("Keine Raster zum Addieren.");
  const width=rasters[0].width,height=rasters[0].height,n=width*height;
  const values=new Float32Array(n),valid=new Uint8Array(n).fill(1);
  for(const raster of rasters){
    if(raster.width!==width||raster.height!==height) throw new Error("Historische Rastergrößen stimmen nicht überein.");
    for(let i=0;i<n;i++){
      if(!valid[i]) continue;
      if(!raster.valid[i]||!Number.isFinite(raster.values[i])){valid[i]=0;values[i]=NaN;continue;}
      values[i]+=raster.values[i];
    }
  }
  return {width,height,values,valid};
}
function hyrasHistoricalTypeControls(){
  const type=document.getElementById("hyrasHistoricalType")?.value||"month";
  const month=document.getElementById("hyrasHistoricalMonth");
  if(month) month.disabled=type!=="month";
}
async function hyrasLoadGeoLookup(path){
  if(!path) return null;
  if(hyrasGeoLookupCache.has(path)) return hyrasGeoLookupCache.get(path);
  const promise=hyrasFetchJson(path).catch(error=>{hyrasGeoLookupCache.delete(path);throw error;});
  hyrasGeoLookupCache.set(path,promise);return promise;
}
function hyrasLookupBracket(indices,value){
  if(!indices?.length)return [0,0,0];
  if(value<=indices[0])return [0,0,0];
  const last=indices.length-1;if(value>=indices[last])return [last,last,0];
  let lo=0,hi=last;
  while(hi-lo>1){const mid=(lo+hi)>>1;if(indices[mid]<=value)lo=mid;else hi=mid;}
  const a=indices[lo],b=indices[hi],t=b===a?0:(value-a)/(b-a);return [lo,hi,Math.max(0,Math.min(1,t))];
}
function hyrasLookupCoord(lookup,col,row){
  if(!lookup)return null;
  const [x0,x1,tx]=hyrasLookupBracket(lookup.x_indices,col),[y0,y1,ty]=hyrasLookupBracket(lookup.y_indices,row);
  const bilinear=(grid)=>{const a=Number(grid?.[y0]?.[x0]),b=Number(grid?.[y0]?.[x1]),c=Number(grid?.[y1]?.[x0]),d=Number(grid?.[y1]?.[x1]);if(![a,b,c,d].every(Number.isFinite))return NaN;return a*(1-tx)*(1-ty)+b*tx*(1-ty)+c*(1-tx)*ty+d*tx*ty;};
  const lon=bilinear(lookup.lon),lat=bilinear(lookup.lat);return Number.isFinite(lon)&&Number.isFinite(lat)?{lon,lat}:null;
}
function hyrasMetricRaster(state,metric){
  const n=state.current.values.length,values=new Float32Array(n),valid=new Uint8Array(n);
  for(let i=0;i<n;i++){
    const c=state.current.values[i],r=state.reference?.values?.[i];
    if(metric==="sum"){
      if(state.current.valid[i]&&Number.isFinite(c)){values[i]=c;valid[i]=1;}
    }else if(state.current.valid[i]&&state.reference?.valid?.[i]&&Number.isFinite(c)&&Number.isFinite(r)&&r>0.1){
      values[i]=metric==="percent"?c/r*100:c-r;valid[i]=1;
    }
  }
  return {values,valid};
}
function hyrasTipNumber(value,digits=1){return Number.isFinite(Number(value))?Number(value).toLocaleString("de-DE",{minimumFractionDigits:digits,maximumFractionDigits:digits}):"–";}
function hyrasAttachMouseover(canvas,wrap,state,geoLookupPath){
  const tip=document.createElement("div");tip.className="hyras-hover-tooltip";wrap.appendChild(tip);
  let lookupPromise=geoLookupPath?hyrasLoadGeoLookup(geoLookupPath).catch(()=>null):Promise.resolve(null);
  const update=async event=>{
    const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;
    const px=Math.max(0,Math.min(rect.width-0.001,event.clientX-rect.left)),py=Math.max(0,Math.min(rect.height-0.001,event.clientY-rect.top));
    const col=Math.max(0,Math.min(state.width-1,Math.floor(px/rect.width*state.width))),row=Math.max(0,Math.min(state.height-1,Math.floor(py/rect.height*state.height))),idx=row*state.width+col;
    const c=state.current?.valid?.[idx]?Number(state.current.values[idx]):NaN;
    if(!Number.isFinite(c)){tip.style.display="none";return;}
    const r=state.reference?.valid?.[idx]?Number(state.reference.values[idx]):NaN;
    const pct=Number.isFinite(r)&&r>0.1?c/r*100:NaN,anom=Number.isFinite(r)?c-r:NaN;
    const lookup=await lookupPromise,coord=hyrasLookupCoord(lookup,col,row);
    const coordText=coord?`${hyrasTipNumber(coord.lat,3)}° N · ${hyrasTipNumber(coord.lon,3)}° E`:`Raster ${col+1} / ${row+1}`;
    tip.innerHTML=`<strong>HYRAS-Rasterzelle</strong><div class="hyras-tip-grid"><span>Niederschlag</span><span class="hyras-tip-value">${hyrasTipNumber(c,1)} l/m²</span><span>Mittel 1991–2020</span><span class="hyras-tip-value">${hyrasTipNumber(r,1)}${Number.isFinite(r)?" l/m²":""}</span><span>Vom Mittel</span><span class="hyras-tip-value">${hyrasTipNumber(pct,0)}${Number.isFinite(pct)?" %":""}</span><span>Abweichung</span><span class="hyras-tip-value">${Number.isFinite(anom)&&anom>=0?"+":""}${hyrasTipNumber(anom,1)}${Number.isFinite(anom)?" l/m²":""}</span></div><div style="margin-top:5px;color:#d6dde3">${coordText}</div>`;
    tip.style.display="block";
    const wrect=wrap.getBoundingClientRect(),tw=tip.offsetWidth||240,th=tip.offsetHeight||120;let left=event.clientX-wrect.left+14,top=event.clientY-wrect.top+14;if(left+tw>wrect.width-6)left=event.clientX-wrect.left-tw-14;if(top+th>wrect.height-6)top=event.clientY-wrect.top-th-14;tip.style.left=`${Math.max(6,left)}px`;tip.style.top=`${Math.max(6,top)}px`;
  };
  canvas.addEventListener("pointermove",event=>{update(event).catch(()=>{});});
  canvas.addEventListener("pointerleave",()=>{tip.style.display="none";});
  canvas.addEventListener("click",event=>{update(event).catch(()=>{});});
}
async function hyrasDrawInteractiveMap({state,title,subtitle,boundaryOverlay,geoLookup,downloadName}){
  const metric=document.getElementById("hyrasMetricSelect")?.value||"percent",cfg=hyrasColorConfig(metric),raster=hyrasMetricRaster(state,metric),n=raster.values.length;
  const raw=document.createElement("canvas");raw.width=state.width;raw.height=state.height;const rctx=raw.getContext("2d"),img=rctx.createImageData(state.width,state.height);
  for(let i=0,j=0;i<n;i++,j+=4){if(!raster.valid[i]||!Number.isFinite(raster.values[i])){img.data[j+3]=0;continue;}const [rr,gg,bb]=hyrasHexRgb(hyrasColorForValue(raster.values[i],cfg));img.data[j]=rr;img.data[j+1]=gg;img.data[j+2]=bb;img.data[j+3]=255;}
  rctx.putImageData(img,0,0);
  const scale=(Number(state.resolutionKm||1)<=1)?2:4,canvas=document.createElement("canvas");canvas.width=state.width*scale;canvas.height=state.height*scale;const ctx=canvas.getContext("2d");
  // Bake the white background into the PNG; CSS backgrounds are not exported.
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.imageSmoothingEnabled=false;ctx.drawImage(raw,0,0,canvas.width,canvas.height);
  if(boundaryOverlay){try{const response=await fetch(`${HYRAS_DATA_BASE}/${boundaryOverlay}?t=${Date.now()}`);if(response.ok){const bmp=await createImageBitmap(await response.blob());ctx.imageSmoothingEnabled=true;ctx.drawImage(bmp,0,0,canvas.width,canvas.height);bmp.close?.();}}catch(error){console.warn("HYRAS-Grenzen:",error);}}
  // Do not let a previous precipitation raster render overwrite a newly
  // selected temperature view after its boundary overlay finished loading.
  if(hyrasParameter()!=="precipitation")return;
  const frame=document.getElementById("hyrasMapFrame");frame.innerHTML="";const wrap=document.createElement("div");wrap.className="hyras-dynamic-wrap";wrap.innerHTML=`<div class="hyras-dynamic-title">${title}</div><div class="hyras-dynamic-subtitle">${subtitle} · ${hyrasMetricConfig(metric).label}</div>`;const stage=document.createElement("div");stage.className="hyras-canvas-stage";stage.appendChild(canvas);wrap.appendChild(stage);const legend=document.createElement("div");legend.className="hyras-dynamic-legend";legend.innerHTML=hyrasDynamicLegend(metric);wrap.appendChild(legend);frame.appendChild(wrap);hyrasAttachMouseover(canvas,wrap,state,geoLookup);hyrasInstallClickAnalysis(canvas,stage,wrap,state,geoLookup,raster,metric);
  const link=document.getElementById("hyrasOpenImage");if(link){link.textContent="PNG herunterladen";link.target="";link.download=downloadName||`hyras_${metric}.png`;link.href=canvas.toDataURL("image/png");link.style.display="inline-block";}
}
async function hyrasLoadPresetState(period){
  const info=period?.interactive;if(!info?.current)throw new Error("Interaktives 1-km-Raster fehlt für diesen Zeitraum.");
  const current=hyrasDecodeEncodedRaster(await hyrasLoadEncodedRaster(info.current),info.value_scale||10);let reference=null;
  const referencePath=info.references?.[hyrasReferencePeriod()]||info.reference;
  if(referencePath)reference=hyrasDecodeEncodedRaster(await hyrasLoadEncodedRaster(referencePath),info.value_scale||10);
  return {current,reference,width:current.width,height:current.height,resolutionKm:1,key:period.key,referenceKey:hyrasReferencePeriod()};
}
async function hyrasRenderPresetMap(period){
  if(!hyrasPresetState||hyrasPresetState.key!==period.key||hyrasPresetState.referenceKey!==hyrasReferencePeriod())hyrasPresetState=await hyrasLoadPresetState(period);
  const interactive=hyrasIndex?.interactive||{};
  await hyrasDrawInteractiveMap({state:hyrasPresetState,title:`HYRAS-Niederschlag · ${period.label||""}`,subtitle:`${period.date_label||""} · ${period.reference_exact?`Referenz ${hyrasReferenceDisplay()}`:"aktueller HYRAS-Zeitraum"}`,boundaryOverlay:interactive.boundary_overlay_1km,geoLookup:interactive.geo_lookup_1km,downloadName:`hyras_${period.key}_${document.getElementById("hyrasMetricSelect")?.value||"sum"}_${hyrasReferenceSlug()}.png`});
}
async function hyrasRenderHistoricalMap(){
  if(!hyrasHistoricalState)return;
  const manifest=await hyrasLoadHistoricalManifest(),state=hyrasHistoricalState;
  await hyrasDrawInteractiveMap({state,title:`HYRAS-Niederschlag · ${state.label}`,subtitle:`${state.dateLabel} · Referenz ${hyrasReferenceDisplay()} · historisches HYRAS-1-km-Raster`,boundaryOverlay:manifest.boundary_overlay,geoLookup:manifest.geo_lookup,downloadName:`hyras_historisch_${state.year}_${state.type}_${document.getElementById("hyrasMetricSelect")?.value||"percent"}.png`});
}
async function hyrasApplyHistorical(){
  const msg=document.getElementById("hyrasHistoricalMessage");
  try{
    const manifest=await hyrasLoadHistoricalManifest();
    const year=Number(document.getElementById("hyrasHistoricalYear")?.value),type=document.getElementById("hyrasHistoricalType")?.value||"month",month=Number(document.getElementById("hyrasHistoricalMonth")?.value||1);
    if(!Number.isFinite(year)) throw new Error("Bitte ein historisches Jahr auswählen.");
    const available=new Set((manifest.years||[]).map(Number));
    const selection=hyrasHistoricalSelection(year,type,month);
    for(const item of selection){if(!available.has(item.year)) throw new Error(`${hyrasHistoricalLabel(year,type,month)} ist nicht vollständig verfügbar (benötigt ${item.year}).`);}
    if(msg){msg.className="hyras-custom-message";msg.textContent="Historische HYRAS-Raster werden geladen und zusammengesetzt …";}
    const currentParts=await Promise.all(selection.map(item=>hyrasLoadHistoricalMonth(item.year,item.month)));
    const uniqueMonths=[...new Set(selection.map(item=>item.month))];
    const refByMonth=new Map();
    await Promise.all(uniqueMonths.map(async m=>refByMonth.set(m,await hyrasLoadHistoricalReference(m))));
    const referenceParts=selection.map(item=>refByMonth.get(item.month));
    const current=hyrasSumRasters(currentParts),reference=hyrasSumRasters(referenceParts),stats=hyrasCustomStats(current,reference);
    const label=hyrasHistoricalLabel(year,type,month),dateLabel=hyrasHistoricalDateLabel(year,type,month);
    hyrasHistoricalState={year,type,month,label,dateLabel,current,reference,stats,width:current.width,height:current.height,resolutionKm:Number(manifest.web_sampling_km||1)};
    hyrasCustomState=null;
    const select=document.getElementById("hyrasPeriodSelect");if(select)select.value="__historical__";
    document.getElementById("hyrasPeriodStat").textContent=label;
    document.getElementById("hyrasDataThrough").textContent=dateLabel;
    document.getElementById("hyrasCurrentMean").textContent=hyrasNum(stats.current_mean_mm,"l/m²",1);
    document.getElementById("hyrasCurrentMeanDetail").textContent=`historisches HYRAS-1-km-Raster ${manifest.web_sampling_km} km`;
    document.getElementById("hyrasReferenceMean").textContent=hyrasNum(stats.reference_mean_mm,"l/m²",1);
    document.getElementById("hyrasReferenceMeanDetail").textContent="Mittel 1991–2020 · gleicher Kalendermonat/Zeitraum";
    document.getElementById("hyrasPercentMean").textContent=hyrasNum(stats.percent_of_reference,"%",1);
    const a=Number(stats.anomaly_mean_mm);document.getElementById("hyrasAnomalyMean").textContent=Number.isFinite(a)?`${a>=0?"+":""}${hyrasNum(a,"l/m²",1)} zum Mittel`:"–";
    document.getElementById("hyrasReferenceNote").textContent=`Historische HYRAS-Auswertung ${manifest.first_year}–${manifest.last_year}: Monatssummen direkt im nativen ${manifest.web_sampling_km}-km-HYRAS-DE-PR-Raster. Referenz ${hyrasReferenceDisplay()}.`;
    [...document.getElementById("hyrasMetricSelect").options].forEach(o=>o.disabled=false);
    await hyrasRenderHistoricalMap();
    if(msg)msg.textContent=`Berechnet: ${label} · ${dateLabel} · Vergleich mit 1991–2020.`;
  }catch(error){console.error("HYRAS Historie:",error);if(msg){msg.className="hyras-custom-message error";msg.textContent=error.message;}}
}

function hyrasPreviousIso(iso){
  const d=new Date(`${iso}T12:00:00Z`);d.setUTCDate(d.getUTCDate()-1);return d.toISOString().slice(0,10);
}
async function hyrasLoadEncodedRaster(path){
  if(!path) return null;
  if(hyrasWebImageCache.has(path)) return hyrasWebImageCache.get(path);
  const promise=(async()=>{
    const response=await fetch(`${HYRAS_DATA_BASE}/${path}?t=${Date.now()}`,{cache:"force-cache"});
    if(!response.ok) throw new Error(`Webraster ${path} nicht erreichbar (HTTP ${response.status})`);
    const blob=await response.blob();
    const bitmap=await createImageBitmap(blob);
    const canvas=document.createElement("canvas");canvas.width=bitmap.width;canvas.height=bitmap.height;
    const ctx=canvas.getContext("2d",{willReadFrequently:true});ctx.drawImage(bitmap,0,0);bitmap.close?.();
    const data=ctx.getImageData(0,0,canvas.width,canvas.height).data;
    return {width:canvas.width,height:canvas.height,data};
  })();
  hyrasWebImageCache.set(path,promise);
  return promise;
}
function hyrasDecodeEncodedRaster(image,scale){
  const n=image.width*image.height, values=new Float32Array(n), valid=new Uint8Array(n), d=image.data;
  for(let i=0,j=0;i<n;i++,j+=4){
    if(d[j+3]===0){values[i]=NaN;continue;}
    const q=d[j]*65536+d[j+1]*256+d[j+2];values[i]=q/scale;valid[i]=1;
  }
  return {width:image.width,height:image.height,values,valid};
}
function hyrasZeroRaster(width,height){return {width,height,values:new Float32Array(width*height),valid:new Uint8Array(width*height).fill(1)};}
async function hyrasCumulativeRaster(kind,iso,allowZero=false){
  const manifest=await hyrasLoadWebManifest();
  if(allowZero && iso<manifest.first_date) return hyrasZeroRaster(manifest.width,manifest.height);
  const files=kind==="reference"?hyrasReferenceFiles(manifest):manifest.current_files;
  const path=files?.[iso];if(!path) throw new Error(`Für ${hyrasDate(iso)} liegt kein ${kind==="reference"?`Referenzraster ${hyrasReferenceDisplay()} `:"aktuelles "}Webraster vor.`);
  const encoded=await hyrasLoadEncodedRaster(path);return hyrasDecodeEncodedRaster(encoded,manifest.value_scale||10);
}
function hyrasRangeDifference(endRaster,startRaster){
  const n=endRaster.values.length,out=new Float32Array(n),valid=new Uint8Array(n);
  for(let i=0;i<n;i++){
    if(!endRaster.valid[i]||!startRaster.valid[i]){out[i]=NaN;continue;}
    out[i]=Math.max(0,endRaster.values[i]-startRaster.values[i]);valid[i]=1;
  }
  return {width:endRaster.width,height:endRaster.height,values:out,valid};
}
function hyrasCustomStats(current,reference){
  let sumC=0,sumR=0,count=0;
  for(let i=0;i<current.values.length;i++){
    const c=current.values[i],r=reference.values[i];
    if(!current.valid[i]||!reference.valid[i]||!Number.isFinite(c)||!Number.isFinite(r)||r<=0.1) continue;
    sumC+=c;sumR+=r;count++;
  }
  if(!count)return {current_mean_mm:null,reference_mean_mm:null,percent_of_reference:null,anomaly_mean_mm:null};
  const c=sumC/count,r=sumR/count;return {current_mean_mm:c,reference_mean_mm:r,percent_of_reference:r?c/r*100:null,anomaly_mean_mm:c-r};
}
function hyrasColorConfig(metric){
  if(metric==="sum")return {breaks:[0,10,25,50,75,100,150,200,300,500,750,1000],colors:["#f7fbff","#deebf7","#c6dbef","#9ecae1","#6baed6","#4292c6","#2171b5","#08519c","#08306b","#041f4a","#02142f"],unit:"l/m²"};
  if(metric==="anomaly")return {breaks:[-400,-250,-150,-100,-75,-50,-25,-10,10,25,50,75,100,150,250,400],colors:["#3b1f00","#543005","#8c510a","#bf812d","#d69f4b","#dfc27d","#ead8ad","#f6e8c3","#f5f5f5","#c7eae5","#80cdc1","#35978f","#1b7f75","#01665e","#003c30"],unit:"l/m²"};
  return {breaks:[0,25,50,75,90,110,125,150,200,300],colors:["#6b3d1f","#9a6334","#c99762","#e4c49f","#f1ede5","#dcebd5","#a8d39b","#68ad6f","#287d46"],unit:"%"};
}
function hyrasHexRgb(hex){const h=hex.replace("#","");return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)];}
function hyrasColorForValue(value,cfg){
  let idx=0;while(idx<cfg.breaks.length&&value>=cfg.breaks[idx])idx++;return cfg.colors[Math.min(idx,cfg.colors.length-1)];
}
function hyrasDynamicLegend(metric){
  const cfg=hyrasColorConfig(metric),parts=[];
  for(let i=0;i<cfg.colors.length;i++){
    let label;if(i===0)label=`< ${cfg.breaks[0]} ${cfg.unit}`;else if(i===cfg.colors.length-1)label=`≥ ${cfg.breaks.at(-1)} ${cfg.unit}`;else label=`${cfg.breaks[i-1]}–${cfg.breaks[i]} ${cfg.unit}`;
    parts.push(`<span><i style="background:${cfg.colors[i]}"></i>${label}</span>`);
  }return parts.join("");
}
async function hyrasRenderCustomMap(){
  if(!hyrasCustomState)return;
  const manifest=await hyrasLoadWebManifest(),state=hyrasCustomState;
  state.resolutionKm=Number(manifest.web_sampling_km||2);
  await hyrasDrawInteractiveMap({state,title:"HYRAS-Niederschlag · Freier Zeitraum",subtitle:`${hyrasDate(state.start)}–${hyrasDate(state.end)} · tagesgenaue Referenz 1991–2020`,boundaryOverlay:manifest.boundary_overlay,geoLookup:manifest.geo_lookup,downloadName:`hyras_${state.start}_${state.end}_${document.getElementById("hyrasMetricSelect")?.value||"percent"}.png`});
}
async function hyrasApplyCustomRange(){
  const msg=document.getElementById("hyrasCustomMessage"),start=document.getElementById("hyrasCustomStart")?.value,end=document.getElementById("hyrasCustomEnd")?.value;
  try{
    const manifest=await hyrasLoadWebManifest();
    if(!start||!end)throw new Error("Bitte Start- und Enddatum auswählen.");
    if(start>end)throw new Error("Das Startdatum liegt nach dem Enddatum.");
    if(start<manifest.first_date||end>manifest.last_date)throw new Error(`Verfügbar ist ${hyrasDate(manifest.first_date)} bis ${hyrasDate(manifest.last_date)}.`);
    if(msg){msg.className="hyras-custom-message";msg.textContent="Freier Zeitraum wird aus den tagesgenauen HYRAS-Webrastern berechnet …";}
    const prev=hyrasPreviousIso(start);
    const [curEnd,curPrev,refEnd,refPrev]=await Promise.all([hyrasCumulativeRaster("current",end),hyrasCumulativeRaster("current",prev,true),hyrasCumulativeRaster("reference",end),hyrasCumulativeRaster("reference",prev,true)]);
    const current=hyrasRangeDifference(curEnd,curPrev),reference=hyrasRangeDifference(refEnd,refPrev),stats=hyrasCustomStats(current,reference);
    hyrasCustomState={start,end,current,reference,stats,width:current.width,height:current.height};
    const select=document.getElementById("hyrasPeriodSelect");if(select)select.value="__custom__";
    document.getElementById("hyrasPeriodStat").textContent="Freier Zeitraum";
    document.getElementById("hyrasDataThrough").textContent=`${hyrasDate(start)}–${hyrasDate(end)}`;
    document.getElementById("hyrasCurrentMean").textContent=hyrasNum(stats.current_mean_mm,"l/m²",1);
    document.getElementById("hyrasCurrentMeanDetail").textContent=`Webraster ${manifest.web_sampling_km} km · tagesgenaue Summe`;
    document.getElementById("hyrasReferenceMean").textContent=hyrasNum(stats.reference_mean_mm,"l/m²",1);
    document.getElementById("hyrasReferenceMeanDetail").textContent="tagesgenaues Mittel 1991–2020";
    document.getElementById("hyrasPercentMean").textContent=hyrasNum(stats.percent_of_reference,"%",1);
    const a=Number(stats.anomaly_mean_mm);document.getElementById("hyrasAnomalyMean").textContent=Number.isFinite(a)?`${a>=0?"+":""}${hyrasNum(a,"l/m²",1)} zum Mittel`:"–";
    document.getElementById("hyrasReferenceNote").textContent=`Freier Zeitraum: tagesgenauer Vergleich 1991–2020. Für die sofortige Browserberechnung wird ein ${manifest.web_sampling_km}-km-Webraster aus dem nativen HYRAS-1-km-Gitter verwendet; die vordefinierten Karten bleiben 1 km.`;
    [...document.getElementById("hyrasMetricSelect").options].forEach(o=>o.disabled=false);
    await hyrasRenderCustomMap();
    if(msg)msg.textContent=`Berechnet: ${hyrasDate(start)}–${hyrasDate(end)} · tagesgenaue Referenz 1991–2020 · Webraster ${manifest.web_sampling_km} km.`;
  }catch(error){console.error("HYRAS freier Zeitraum:",error);if(msg){msg.className="hyras-custom-message error";msg.textContent=error.message;}}
}
function updateHyrasMetricAvailability(period){
  const select=document.getElementById("hyrasMetricSelect");
  if(!select || !period) return;
  const hasPercent=Boolean(period.outputs?.percent);
  const hasAnomaly=Boolean(period.outputs?.anomaly);
  [...select.options].forEach(option=>{
    if(option.value==="percent") option.disabled=!hasPercent;
    if(option.value==="anomaly") option.disabled=!hasAnomaly;
  });
  if((select.value==="percent"&&!hasPercent)||(select.value==="anomaly"&&!hasAnomaly)) select.value="sum";
}
function hyrasRenderPresetFallback(period,cfg,file){
  if(hyrasParameter()!=="precipitation")return;
  const frame=document.getElementById("hyrasMapFrame"),link=document.getElementById("hyrasOpenImage");
  if(!file){frame.innerHTML='<div class="hyras-loading">Für diese Darstellung wurde keine Karte erzeugt.</div>';if(link)link.style.display="none";return;}
  const url=`${HYRAS_DATA_BASE}/${file}?t=${Date.now()}`;if(link){link.textContent="Karte groß öffnen";link.target="_blank";link.removeAttribute("download");}
  const img=document.createElement("img");img.alt=`HYRAS ${cfg.label} · ${period.label||""}`;img.loading="eager";img.src=url;img.onerror=()=>{frame.innerHTML='<div class="hyras-loading">Die HYRAS-Karte konnte nicht geladen werden.</div>';};frame.innerHTML="";frame.appendChild(img);if(link){link.href=url;link.style.display="inline-block";}
}
// HYRAS_LIVE_DAILY_PRESETS_V1
async function hyrasRenderLiveDailyPreset(period){
  const manifest=await hyrasLoadWebManifest();
  const start=period?.start_date,end=period?.end_date;
  if(!start||!end)throw new Error("Laufender HYRAS-Zeitraum besitzt kein Start-/Enddatum.");
  if(start<manifest.first_date||end>manifest.last_date)throw new Error(`Tagesdaten verfügbar: ${hyrasDate(manifest.first_date)} bis ${hyrasDate(manifest.last_date)}.`);
  const stateKey=`${period.key}|${start}|${end}|${manifest.data_through||manifest.last_date}|${hyrasReferencePeriod()}`;
  if(!hyrasLivePresetState||hyrasLivePresetState.stateKey!==stateKey){
    const prev=hyrasPreviousIso(start);
    const [curEnd,curPrev,refEnd,refPrev]=await Promise.all([
      hyrasCumulativeRaster("current",end),
      hyrasCumulativeRaster("current",prev,true),
      hyrasCumulativeRaster("reference",end),
      hyrasCumulativeRaster("reference",prev,true),
    ]);
    const current=hyrasRangeDifference(curEnd,curPrev),reference=hyrasRangeDifference(refEnd,refPrev),stats=hyrasCustomStats(current,reference);
    hyrasLivePresetState={stateKey,start,end,current,reference,stats,width:current.width,height:current.height,resolutionKm:Number(manifest.web_sampling_km||2)};
  }
  const state=hyrasLivePresetState,stats=state.stats||{};
  const metricSelect=document.getElementById("hyrasMetricSelect");
  if(metricSelect)[...metricSelect.options].forEach(option=>option.disabled=false);
  document.getElementById("hyrasPeriodStat").textContent=period.label||"Aktueller Zeitraum";
  document.getElementById("hyrasDataThrough").textContent=period.date_label||`${hyrasDate(start)}–${hyrasDate(end)}`;
  document.getElementById("hyrasCurrentMean").textContent=hyrasNum(stats.current_mean_mm,"l/m²",1);
  document.getElementById("hyrasCurrentMeanDetail").textContent=`HYRAS-Tagesdaten · Webraster ${state.resolutionKm} km`;
  document.getElementById("hyrasReferenceMean").textContent=hyrasNum(stats.reference_mean_mm,"l/m²",1);
  document.getElementById("hyrasReferenceMeanDetail").textContent=`exakter gleicher Kalenderabschnitt ${hyrasReferenceDisplay()}`;
  document.getElementById("hyrasPercentMean").textContent=hyrasNum(stats.percent_of_reference,"%",1);
  const anom=Number(stats.anomaly_mean_mm);
  document.getElementById("hyrasAnomalyMean").textContent=Number.isFinite(anom)?`${anom>=0?"+":""}${hyrasNum(anom,"l/m²",1)} zum Mittel`:"Abweichung nicht verfügbar";
  const note=document.getElementById("hyrasReferenceNote");
  if(note)note.textContent=`Tagesgenauer HYRAS-Vergleich mit exakt demselben Kalenderabschnitt ${hyrasReferenceDisplay()}.`;
  await hyrasDrawInteractiveMap({
    state,
    title:`HYRAS-Niederschlag · ${period.label||"Aktueller Zeitraum"}`,
    subtitle:`${period.date_label||`${hyrasDate(start)}–${hyrasDate(end)}`} · tagesgenaue Referenz ${hyrasReferenceDisplay()}`,
    boundaryOverlay:manifest.boundary_overlay,
    geoLookup:manifest.geo_lookup,
    downloadName:`hyras_${period.key}_${metricSelect?.value||"percent"}.png`,
  });
}
// HYRAS_CLICK_TIMESERIES_V1
// HYRAS_TIMESERIES_ROUNDING_V1
function hyrasClickSeriesBase(){return `${HYRAS_DATA_BASE}/click_series_5km`;}
async function hyrasLoadClickSeriesManifest(){
  if(hyrasClickSeriesManifest)return hyrasClickSeriesManifest;
  const response=await fetch(`${hyrasClickSeriesBase()}/manifest.json?t=${encodeURIComponent(hyrasIndex?.data_through||Date.now())}`,{cache:"no-store"});
  if(!response.ok)throw new Error(`Klick-Zeitreihenmanifest nicht verfügbar (${response.status}).`);
  hyrasClickSeriesManifest=await response.json();
  return hyrasClickSeriesManifest;
}
async function hyrasGunzipBuffer(buffer){
  if(typeof DecompressionStream==="undefined")throw new Error("Dieser Browser unterstützt die komprimierten HYRAS-Zeitreihen nicht.");
  const stream=new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}
async function hyrasLoadClickMonth(month){
  const key=Number(month);
  if(hyrasClickSeriesPackCache.has(key))return hyrasClickSeriesPackCache.get(key);
  const promise=(async()=>{
    const manifest=await hyrasLoadClickSeriesManifest(),mm=String(key).padStart(2,"0");
    const response=await fetch(`${hyrasClickSeriesBase()}/month_${mm}.u16.gz?t=${encodeURIComponent(manifest.last_year||"")}`);
    if(!response.ok)throw new Error(`HYRAS-Zeitreihenpack Monat ${mm} fehlt (${response.status}).`);
    const raw=await hyrasGunzipBuffer(await response.arrayBuffer()),values=new Uint16Array(raw);
    const expected=Number(manifest.years?.length||0)*Number(manifest.width||0)*Number(manifest.height||0);
    if(values.length!==expected)throw new Error(`HYRAS-Zeitreihenpack Monat ${mm} hat ${values.length} statt ${expected} Werte.`);
    return values;
  })().catch(error=>{hyrasClickSeriesPackCache.delete(key);throw error;});
  hyrasClickSeriesPackCache.set(key,promise);return promise;
}
function hyrasPartsFromDates(startIso,endIso){
  if(!startIso||!endIso)return [];
  const start=new Date(`${startIso}T00:00:00Z`),end=new Date(`${endIso}T00:00:00Z`),targetYear=end.getUTCFullYear(),parts=[];
  let y=start.getUTCFullYear(),m=start.getUTCMonth()+1;
  const ey=end.getUTCFullYear(),em=end.getUTCMonth()+1;
  for(let guard=0;guard<24;guard++){
    parts.push({month:m,offset:y-targetYear});
    if(y===ey&&m===em)break;
    m++;if(m===13){m=1;y++;}
  }
  return parts;
}
function hyrasCurrentSeriesSpec(){
  const special=document.getElementById("hyrasPeriodSelect")?.value;
  if(special==="__custom__")return null;
  if(special==="__historical__"){
    const state=hyrasHistoricalState;if(!state)return null;
    const selection=hyrasHistoricalSelection(Number(state.year),state.type,Number(state.month||1));
    return {label:state.label||"Historischer Zeitraum",parts:selection.map(item=>({month:Number(item.month),offset:Number(item.year)-Number(state.year)})),selectedYear:Number(state.year),appendCurrent:false,partial:false,historical:true};
  }
  const period=hyrasSelectedPeriod();if(!period)return null;
  return {label:period.label||"Aktueller Zeitraum",parts:hyrasPartsFromDates(period.start_date,period.end_date),selectedYear:Number(hyrasIndex?.year),appendCurrent:true,partial:Boolean(period.daily_live),historical:false,endDate:period.end_date};
}
function hyrasStateValueAtNorm(raster,state,xNorm,yNorm){
  if(!raster||!state?.width||!state?.height)return NaN;
  const col=Math.max(0,Math.min(state.width-1,Math.round(xNorm*(state.width-1)))),row=Math.max(0,Math.min(state.height-1,Math.round(yNorm*(state.height-1)))),idx=row*state.width+col;
  return raster.valid?.[idx]&&Number.isFinite(raster.values?.[idx])?Number(raster.values[idx]):NaN;
}
function hyrasPointLocationText(coord){
  if(!coord)return "Rasterpunkt";
  return `${Number(coord.lat).toLocaleString("de-DE",{minimumFractionDigits:3,maximumFractionDigits:3})}° N · ${Number(coord.lon).toLocaleString("de-DE",{minimumFractionDigits:3,maximumFractionDigits:3})}° E`;
}
function hyrasPeriodSeriesName(label){
  return String(label||"Niederschlag").replace(/\s+aktuell\s+\d{4}(?:\/\d{2})?$/i,"").replace(/\s+\d{4}$/i,"");
}
function hyrasSeriesRank(entries,year){
  const sorted=[...entries].filter(item=>Number.isFinite(item.value)).sort((a,b)=>b.value-a.value||a.year-b.year),found=sorted.findIndex(item=>item.year===year);
  return found>=0?{rank:found+1,count:sorted.length}:null;
}
function hyrasRenderPointSeries({spec,years,values,currentValue,coord,analysisKm}){
  const panel=document.getElementById("hyrasPointAnalysis");if(!panel)return;
  panel.hidden=false;
  let plotYears=[...years],plotValues=[...values],selectedYear=Number(spec.selectedYear),selectedValue=NaN;
  if(spec.appendCurrent&&Number.isFinite(currentValue)){
    const existing=plotYears.indexOf(selectedYear);if(existing>=0)plotValues[existing]=currentValue;else{plotYears.push(selectedYear);plotValues.push(currentValue);}
  }
  const selectedIndex=plotYears.indexOf(selectedYear);if(selectedIndex>=0)selectedValue=Number(plotValues[selectedIndex]);
  const historicalEntries=years.map((year,i)=>({year,value:Number(values[i])})).filter(item=>Number.isFinite(item.value));
  const comparisonEntries=plotYears.map((year,i)=>({year,value:Number(plotValues[i])})).filter(item=>Number.isFinite(item.value));
  const refVals=historicalEntries.filter(item=>item.year>=1991&&item.year<=2020).map(item=>item.value),reference=refVals.length?refVals.reduce((a,b)=>a+b,0)/refVals.length:NaN;
  const recordPool=spec.partial?historicalEntries:comparisonEntries,record=recordPool.length?[...recordPool].sort((a,b)=>b.value-a.value)[0]:null;
  const rank=spec.partial?null:hyrasSeriesRank(comparisonEntries,selectedYear);
  const seriesName=hyrasPeriodSeriesName(spec.label);
  document.getElementById("hyrasPointTitle").textContent=`${seriesName} · Zeitreihe seit ${plotYears[0]||"1931"}`;
  document.getElementById("hyrasPointSubtitle").textContent=`${hyrasPointLocationText(coord)} · HYRAS-Analyseraster ${analysisKm} km`;
  document.getElementById("hyrasPointSelectedValue").textContent=Number.isFinite(selectedValue)?`${selectedValue.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m² · ${selectedYear}`:"–";
  document.getElementById("hyrasPointRank").textContent=spec.partial?"laufend · kein Rang":rank?`${rank.rank}. von ${rank.count}`:"–";
  document.getElementById("hyrasPointRecord").textContent=record?`${record.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m² · ${record.year}`:"–";
  document.getElementById("hyrasPointReference").textContent=Number.isFinite(reference)?`${reference.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m²`:"–";
  const note=document.getElementById("hyrasPointNote");
  note.textContent=spec.partial?`Hinweis: ${selectedYear} reicht nur bis ${hyrasDate(spec.endDate)}. Frühere Jahre zeigen für den bereits begonnenen Monatsumfang vollständige Monatswerte; deshalb wird für das laufende Jahr bewusst kein historischer Rang angegeben.`:`Zeitreihe aus den monatlichen HYRAS-Rastern. Rang und Rekord beziehen sich auf die an diesem ${analysisKm}-km-Analysepunkt verfügbaren Jahre.`;

  if(hyrasPointChart){hyrasPointChart.destroy();hyrasPointChart=null;}
  const ctx=document.getElementById("hyrasPointChart")?.getContext("2d");if(!ctx)return;
  const selectedData=plotYears.map((year,i)=>year===selectedYear?plotValues[i]:null),referenceData=plotYears.map(()=>Number.isFinite(reference)?reference:null);
  hyrasPointChart=new Chart(ctx,{type:"line",data:{labels:plotYears,datasets:[
    {label:"Niederschlag",data:plotValues,borderColor:"#52718a",backgroundColor:"rgba(82,113,138,.12)",borderWidth:1.6,pointRadius:1.8,pointHoverRadius:4,tension:.12,spanGaps:true},
    {label:"Mittel 1991–2020",data:referenceData,borderColor:"#222",borderWidth:1.4,borderDash:[6,5],pointRadius:0,spanGaps:true},
    {label:`Auswahl ${selectedYear}`,data:selectedData,borderColor:"#b42318",backgroundColor:"#b42318",pointRadius:6,pointHoverRadius:7,showLine:false}
  ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{display:true},datalabels:{formatter:value=>Number.isFinite(Number(value))?Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):""},tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${Number(context.raw).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m²`}}},scales:{x:{title:{display:true,text:"Jahr"},ticks:{maxTicksLimit:16}},y:{beginAtZero:true,title:{display:true,text:"Niederschlag (l/m²)"}}}}});
}
async function hyrasUpdatePointAnalysis(state,geoLookupPath,point){
  const request=++hyrasPointRequest,panel=document.getElementById("hyrasPointAnalysis");if(panel)panel.hidden=false;
  const spec=hyrasCurrentSeriesSpec();
  if(!spec){
    if(panel){document.getElementById("hyrasPointTitle").textContent="HYRAS-Punktzeitreihe";document.getElementById("hyrasPointSubtitle").textContent="Für freie Start-/Endzeiträume ist die lange Punktzeitreihe nicht verfügbar. Bitte Monat, Jahreszeit, Jahr oder eine historische Karte wählen.";}
    return;
  }
  try{
    const manifest=await hyrasLoadClickSeriesManifest();if(request!==hyrasPointRequest)return;
    const col=Math.max(0,Math.min(manifest.width-1,Math.round(point.xNorm*(manifest.width-1)))),row=Math.max(0,Math.min(manifest.height-1,Math.round(point.yNorm*(manifest.height-1))));
    const xNorm=manifest.width>1?col/(manifest.width-1):0,yNorm=manifest.height>1?row/(manifest.height-1):0;
    hyrasSelectedGridPoint={xNorm,yNorm};
    const uniqueMonths=[...new Set(spec.parts.map(part=>part.month))],packs=new Map();
    await Promise.all(uniqueMonths.map(async month=>packs.set(month,await hyrasLoadClickMonth(month))));if(request!==hyrasPointRequest)return;
    const yearToIndex=new Map((manifest.years||[]).map((year,i)=>[Number(year),i])),years=[],values=[],plane=manifest.width*manifest.height,missing=Number(manifest.missing_value??65535),scale=Number(manifest.value_scale||10);
    for(const targetYear of (manifest.years||[]).map(Number)){
      let total=0,ok=true;
      for(const part of spec.parts){
        const yi=yearToIndex.get(targetYear+Number(part.offset||0));if(yi===undefined){ok=false;break;}
        const q=packs.get(part.month)?.[yi*plane+row*manifest.width+col];if(q===undefined||q===missing){ok=false;break;}
        total+=Number(q)/scale;
      }
      if(ok){years.push(targetYear);values.push(total);}
    }
    const currentValue=spec.appendCurrent?hyrasStateValueAtNorm(state.current,state,xNorm,yNorm):NaN;
    let coord=null;
    if(geoLookupPath){try{const lookup=await hyrasLoadGeoLookup(geoLookupPath),scol=Math.round(xNorm*(state.width-1)),srow=Math.round(yNorm*(state.height-1));coord=hyrasLookupCoord(lookup,scol,srow);}catch(error){console.warn("HYRAS Klick-Koordinate:",error);}}
    if(request!==hyrasPointRequest)return;
    hyrasRenderPointSeries({spec,years,values,currentValue,coord,analysisKm:Number(manifest.resolution_km||5)});
  }catch(error){
    console.error("HYRAS Klick-Zeitreihe:",error);
    if(panel){document.getElementById("hyrasPointTitle").textContent="HYRAS-Punktzeitreihe";document.getElementById("hyrasPointSubtitle").textContent=error.message;}
  }
}
function hyrasFindSeparatedMaxima(raster,state,count=3){
  const resolution=Math.max(.5,Number(state?.resolutionKm||1)),block=Math.max(4,Math.round(25/resolution)),minDist=Math.max(8,Math.round(45/resolution)),candidates=[];
  for(let y0=0;y0<state.height;y0+=block){for(let x0=0;x0<state.width;x0+=block){let best=-Infinity,bx=-1,by=-1;const y1=Math.min(state.height,y0+block),x1=Math.min(state.width,x0+block);for(let y=y0;y<y1;y++){let idx=y*state.width+x0;for(let x=x0;x<x1;x++,idx++){if(raster.valid?.[idx]&&Number.isFinite(raster.values?.[idx])&&Number(raster.values[idx])>best){best=Number(raster.values[idx]);bx=x;by=y;}}}if(bx>=0)candidates.push({col:bx,row:by,value:best});}}
  candidates.sort((a,b)=>b.value-a.value);const chosen=[];
  for(const candidate of candidates){if(chosen.every(item=>(item.col-candidate.col)**2+(item.row-candidate.row)**2>=minDist**2)){chosen.push(candidate);if(chosen.length>=count)break;}}
  return chosen;
}
function hyrasMetricMaxText(value,metric){
  if(metric==="percent")return `${Number(value).toLocaleString("de-DE",{maximumFractionDigits:0})} %`;
  const sign=metric==="anomaly"&&Number(value)>0?"+":"";return `${sign}${Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m²`;
}
function hyrasMapMaxima(raster,state){
  return hyrasFindSeparatedMaxima(raster,state,3);
}
function hyrasPlaceSelectedPin(stage,point){
  stage.querySelectorAll(".hyras-selected-pin").forEach(node=>node.remove());if(!point)return;
  const pin=document.createElement("div");pin.className="hyras-selected-pin";pin.style.left=`${point.xNorm*100}%`;pin.style.top=`${point.yNorm*100}%`;stage.appendChild(pin);
}
function hyrasInstallClickAnalysis(canvas,stage,wrap,state,geoLookupPath,raster,metric){
  const maxima=hyrasMapMaxima(raster,state),strip=document.createElement("div");strip.className="hyras-maxima-strip";strip.innerHTML=maxima.map((item,i)=>`<span><b class="hyras-maxima-badge">${i+1}</b>${hyrasMetricMaxText(item.value,metric)}</span>`).join("");wrap.appendChild(strip);
  const selectPoint=async rawPoint=>{
    try{const manifest=await hyrasLoadClickSeriesManifest(),col=Math.max(0,Math.min(manifest.width-1,Math.round(rawPoint.xNorm*(manifest.width-1)))),row=Math.max(0,Math.min(manifest.height-1,Math.round(rawPoint.yNorm*(manifest.height-1)))),point={xNorm:manifest.width>1?col/(manifest.width-1):0,yNorm:manifest.height>1?row/(manifest.height-1):0};hyrasSelectedGridPoint=point;hyrasPlaceSelectedPin(stage,point);await hyrasUpdatePointAnalysis(state,geoLookupPath,point);}catch(error){console.error("HYRAS Punktwahl:",error);}
  };
  canvas.addEventListener("click",event=>{const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;selectPoint({xNorm:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),yNorm:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))});});
  if(hyrasSelectedGridPoint){hyrasPlaceSelectedPin(stage,hyrasSelectedGridPoint);hyrasUpdatePointAnalysis(state,geoLookupPath,hyrasSelectedGridPoint).catch(error=>console.error("HYRAS Punktzeitreihe aktualisieren:",error));}
}
// HYRAS_TMEAN_FRONTEND_V1
function hyrasParameter(){return document.getElementById("hyrasParameterSelect")?.value||"precipitation";}
function hyrasTmeanBase(){return `${HYRAS_DATA_BASE}/tmean`;}
async function hyrasTmeanFetchJson(path){
  const response=await fetch(`${hyrasTmeanBase()}/${path}?t=${encodeURIComponent(hyrasTmeanIndex?.data_through||Date.now())}`,{cache:"no-store"});
  if(!response.ok)throw new Error(`HYRAS Tmean ${path} nicht verfügbar (${response.status}).`);
  return response.json();
}
async function hyrasTmeanGunzip(buffer){
  if(typeof DecompressionStream==="undefined")throw new Error("Dieser Browser unterstützt die komprimierten HYRAS-Tmean-Raster nicht.");
  const stream=new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}
async function hyrasTmeanLoadI16(path){
  if(hyrasTmeanFileCache.has(path))return hyrasTmeanFileCache.get(path);
  const promise=(async()=>{
    const response=await fetch(`${hyrasTmeanBase()}/${path}?t=${encodeURIComponent(hyrasTmeanIndex?.data_through||"")}`);
    if(!response.ok)throw new Error(`Tmean-Raster ${path} fehlt (${response.status}).`);
    return new Int16Array(await hyrasTmeanGunzip(await response.arrayBuffer()));
  })().catch(error=>{hyrasTmeanFileCache.delete(path);throw error;});
  hyrasTmeanFileCache.set(path,promise);return promise;
}
function hyrasTmeanDecodePlane(raw,width,height,scale=100,missing=-32768,offset=0,factor=1){
  const step=Math.max(1,Math.floor(Number(factor)||1));
  const outWidth=Math.ceil(width/step),outHeight=Math.ceil(height/step),n=outWidth*outHeight;
  const values=new Float32Array(n),valid=new Uint8Array(n);
  let out=0;
  for(let oy=0;oy<outHeight;oy++){
    const sy=Math.min(height-1,oy*step);
    const row=offset+sy*width;
    for(let ox=0;ox<outWidth;ox++,out++){
      const sx=Math.min(width-1,ox*step),q=raw[row+sx];
      if(q===undefined||q===missing){values[out]=NaN;continue;}
      values[out]=Number(q)/scale;valid[out]=1;
    }
  }
  return {values,valid,width:outWidth,height:outHeight,resolutionKm:step};
}
async function hyrasTmeanEnsureLoaded(){
  if(!hyrasTmeanIndex)hyrasTmeanIndex=await hyrasTmeanFetchJson("index.json");
  if(!hyrasTmeanHistoryManifest)hyrasTmeanHistoryManifest=await hyrasTmeanFetchJson(hyrasTmeanIndex.history_manifest||"history_5km/manifest.json");
  return hyrasTmeanIndex;
}
function hyrasTmeanMetricOptions(hasAnomaly=true){
  const select=document.getElementById("hyrasMetricSelect");if(!select)return;
  const previous=select.value;
  select.innerHTML=`<option value="absolute">Temperatur (°C)</option><option value="anomaly">Abweichung ${hyrasReferenceDisplay()} (K)</option>`;
  select.querySelector('option[value="anomaly"]').disabled=!hasAnomaly;
  select.value=(previous==="anomaly"&&hasAnomaly)?"anomaly":"absolute";
}
function hyrasRestorePrecipMetricOptions(){
  const select=document.getElementById("hyrasMetricSelect");if(!select)return;
  select.innerHTML=`<option value="percent">Prozent des Mittels ${hyrasReferenceDisplay()}</option><option value="sum">Niederschlagssumme</option><option value="anomaly">Abweichung zu ${hyrasReferenceDisplay()} in l/m²</option>`;
  select.value="percent";
}
function hyrasTmeanDefaultPeriod(){
  const periods=hyrasTmeanIndex?.periods||[];
  return periods.find(p=>p.period_type==="month_live")||periods.find(p=>p.period_type==="season_live")||periods.find(p=>p.key===`${hyrasTmeanIndex?.year}_${String(hyrasTmeanIndex?.latest_complete_month||1).padStart(2,"0")}`)||periods[0]||null;
}
function hyrasTmeanSelectedPeriod(){
  const key=document.getElementById("hyrasPeriodSelect")?.value;
  return (hyrasTmeanIndex?.periods||[]).find(p=>p.key===key)||hyrasTmeanDefaultPeriod();
}
function hyrasTmeanPopulatePeriods(){
  const select=document.getElementById("hyrasPeriodSelect");if(!select||!hyrasTmeanIndex)return;
  const periods=hyrasTmeanIndex.periods||[];select.innerHTML="";
  const live=document.createElement("optgroup");live.label="Aktueller Datenstand";
  const complete=document.createElement("optgroup");complete.label="Abgeschlossene Perioden 2026";
  periods.forEach(period=>{
    const opt=document.createElement("option");opt.value=period.key;opt.textContent=period.label;
    (period.live?live:complete).appendChild(opt);
  });
  if(live.children.length)select.appendChild(live);if(complete.children.length)select.appendChild(complete);
  const hist=document.createElement("optgroup");hist.label="Historische Karten";
  const hop=document.createElement("option");hop.value="__historical__";hop.textContent=`Historische Karte ${hyrasTmeanIndex.history_first_year}–${hyrasTmeanIndex.history_last_year}`;hist.appendChild(hop);select.appendChild(hist);
  const def=hyrasTmeanDefaultPeriod();if(def)select.value=def.key;
}
function hyrasTmeanPopulateHistoricalYears(){
  const select=document.getElementById("hyrasHistoricalYear"),manifest=hyrasTmeanHistoryManifest;if(!select||!manifest)return;
  const years=[...(manifest.years||[])].sort((a,b)=>b-a);select.innerHTML=years.map(y=>`<option value="${y}">${y}</option>`).join("");
  if(years.length)select.value=String(years[0]);
  const msg=document.getElementById("hyrasHistoricalMessage");if(msg)msg.textContent=`Tmean-Historie ${manifest.first_year}–${manifest.last_year} · ${manifest.resolution_km} km. Monat, Jahreszeit oder Jahr wählen.`;
}
function hyrasRestorePrecipHistoricalYears(){
  const select=document.getElementById("hyrasHistoricalYear");if(!select||!hyrasHistoricalManifest)return;
  const years=[...(hyrasHistoricalManifest.years||[])].sort((a,b)=>b-a);select.innerHTML=years.map(y=>`<option value="${y}">${y}</option>`).join("");if(years.length)select.value=String(years[0]);
}
function hyrasTmeanHistoricalSelection(year,type,month){
  if(type==="month")return [{year,month}];
  if(type==="spring")return [3,4,5].map(m=>({year,month:m}));
  if(type==="summer")return [6,7,8].map(m=>({year,month:m}));
  if(type==="autumn")return [9,10,11].map(m=>({year,month:m}));
  if(type==="winter")return [{year:year-1,month:12},{year,month:1},{year,month:2}];
  return Array.from({length:12},(_,i)=>({year,month:i+1}));
}
function hyrasTmeanHistoricalLabel(year,type,month){
  const monthNames=["","Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
  if(type==="month")return `${monthNames[month]} ${year}`;
  if(type==="spring")return `Frühling ${year}`;if(type==="summer")return `Sommer ${year}`;if(type==="autumn")return `Herbst ${year}`;if(type==="winter")return `Winter ${year}`;return `Jahr ${year}`;
}
function hyrasTmeanDays(year,month){return new Date(Date.UTC(year,month,0)).getUTCDate();}
async function hyrasTmeanLoadMonthPack(month){
  const m=Number(month);if(hyrasTmeanMonthCache.has(m))return hyrasTmeanMonthCache.get(m);
  const path=`history_${hyrasTmeanHistoryManifest.resolution_km}km/month_${String(m).padStart(2,"0")}.i16.gz`;
  const promise=hyrasTmeanLoadI16(path);hyrasTmeanMonthCache.set(m,promise);return promise;
}
async function hyrasTmeanHistoricalRaster(selection,targetYear){
  const mf=hyrasTmeanHistoryManifest,w=Number(mf.width),h=Number(mf.height),plane=w*h,years=(mf.years||[]).map(Number),yearIndex=new Map(years.map((y,i)=>[y,i])),scale=Number(mf.value_scale||100),missing=Number(mf.missing_value??-32768);
  const months=[...new Set(selection.map(x=>x.month))],packs=new Map();await Promise.all(months.map(async m=>packs.set(m,await hyrasTmeanLoadMonthPack(m))));
  const out=new Float32Array(plane),valid=new Uint8Array(plane),weightSum=new Float32Array(plane);
  for(const item of selection){
    const yi=yearIndex.get(Number(item.year));if(yi===undefined)throw new Error(`Tmean-Jahr ${item.year} nicht verfügbar.`);
    const raw=packs.get(item.month),weight=hyrasTmeanDays(item.year,item.month),offset=yi*plane;
    for(let i=0;i<plane;i++){const q=raw[offset+i];if(q===missing)continue;out[i]+=Number(q)/scale*weight;weightSum[i]+=weight;}
  }
  for(let i=0;i<plane;i++){if(weightSum[i]>0){out[i]/=weightSum[i];valid[i]=1;}else out[i]=NaN;}
  return {values:out,valid,width:w,height:h,resolutionKm:Number(mf.resolution_km||5),targetYear};
}
async function hyrasTmeanHistoricalReference(type,month){
  const mf=hyrasTmeanHistoryManifest,w=Number(mf.width),h=Number(mf.height),plane=w*h,sum=new Float64Array(plane),count=new Uint16Array(plane),refYears=hyrasReferenceYears();
  for(let year=refYears.start;year<=refYears.end;year++){
    const selection=hyrasTmeanHistoricalSelection(year,type,month),state=await hyrasTmeanHistoricalRaster(selection,year);
    for(let i=0;i<plane;i++){if(state.valid[i]){sum[i]+=state.values[i];count[i]++;}}
  }
  const values=new Float32Array(plane),valid=new Uint8Array(plane);for(let i=0;i<plane;i++){if(count[i]){values[i]=sum[i]/count[i];valid[i]=1;}else values[i]=NaN;}
  return {values,valid,width:w,height:h,resolutionKm:Number(mf.resolution_km||5)};
}
function hyrasTmeanSubtract(a,b){
  const n=a.values.length,values=new Float32Array(n),valid=new Uint8Array(n);for(let i=0;i<n;i++){if(a.valid[i]&&b.valid[i]){values[i]=a.values[i]-b.values[i];valid[i]=1;}else values[i]=NaN;}return {values,valid,width:a.width,height:a.height,resolutionKm:a.resolutionKm};
}
function hyrasTmeanMean(raster){let s=0,n=0;for(let i=0;i<raster.values.length;i++){if(raster.valid[i]&&Number.isFinite(raster.values[i])){s+=raster.values[i];n++;}}return n?s/n:NaN;}
function hyrasTmeanHexRgb(hex){const n=parseInt(hex.slice(1),16);return [(n>>16)&255,(n>>8)&255,n&255];}
function hyrasTmeanInterpColor(value,stops){
  if(!Number.isFinite(value))return [0,0,0,0];if(value<=stops[0][0])return [...hyrasTmeanHexRgb(stops[0][1]),255];if(value>=stops.at(-1)[0])return [...hyrasTmeanHexRgb(stops.at(-1)[1]),255];
  for(let i=1;i<stops.length;i++){if(value<=stops[i][0]){const [a,ca]=stops[i-1],[b,cb]=stops[i],t=(value-a)/(b-a),ra=hyrasTmeanHexRgb(ca),rb=hyrasTmeanHexRgb(cb);return [0,1,2].map(k=>Math.round(ra[k]+(rb[k]-ra[k])*t)).concat(255);}}
  return [0,0,0,255];
}
function hyrasTmeanColor(value,mode){
  const absolute=[[-15,"#313695"],[-10,"#4575b4"],[-5,"#74add1"],[0,"#abd9e9"],[5,"#e0f3f8"],[10,"#ffffbf"],[15,"#fee090"],[20,"#fdae61"],[25,"#f46d43"],[30,"#d73027"],[35,"#a50026"]];
  const anomaly=[[-6,"#313695"],[-4,"#4575b4"],[-2,"#74add1"],[-1,"#abd9e9"],[0,"#f7f7f7"],[1,"#fdae61"],[2,"#f46d43"],[4,"#d73027"],[6,"#a50026"]];
  return hyrasTmeanInterpColor(value,mode==="anomaly"?anomaly:absolute);
}
function hyrasTmeanLegend(mode){
  const vals=mode==="anomaly"?[-6,-4,-2,-1,0,1,2,4,6]:[-15,-10,-5,0,5,10,15,20,25,30,35];
  return vals.map(v=>{const [r,g,b]=hyrasTmeanColor(v,mode);return `<span><i style="background:rgb(${r},${g},${b})"></i>${v>0&&mode==="anomaly"?"+":""}${v}${mode==="anomaly"?" K":" °C"}</span>`;}).join("");
}
async function hyrasTmeanBoundaryBitmap(){
  const boundary=hyrasIndex?.interactive?.boundary_overlay_1km;
  if(!boundary)return null;
  if(!hyrasTmeanBoundaryBitmapPromise){
    hyrasTmeanBoundaryBitmapPromise=fetch(`${HYRAS_DATA_BASE}/${boundary}`,{cache:"force-cache"})
      .then(response=>{if(!response.ok)throw new Error(`HYRAS-Grenzmaske fehlt (${response.status}).`);return response.blob();})
      .then(blob=>createImageBitmap(blob))
      .catch(error=>{hyrasTmeanBoundaryBitmapPromise=null;throw error;});
  }
  return hyrasTmeanBoundaryBitmapPromise;
}
function hyrasTmeanResetExportLink(){
  const link=document.getElementById("hyrasOpenImage");
  if(link)link.onclick=null;
  if(hyrasTmeanExportObjectUrl){
    URL.revokeObjectURL(hyrasTmeanExportObjectUrl);
    hyrasTmeanExportObjectUrl=null;
  }
}
function hyrasTmeanInstallLazyExport(link,canvas,mode,boundaryPromise){
  if(!link)return;
  hyrasTmeanResetExportLink();
  link.textContent="PNG herunterladen";
  link.target="";
  link.removeAttribute("download");
  link.href="#";
  link.style.display="inline-block";
  link.onclick=async event=>{
    event.preventDefault();
    try{await boundaryPromise;}catch(_){}
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/png"));
    if(!blob)return;
    if(hyrasTmeanExportObjectUrl)URL.revokeObjectURL(hyrasTmeanExportObjectUrl);
    hyrasTmeanExportObjectUrl=URL.createObjectURL(blob);
    const a=document.createElement("a");
    a.href=hyrasTmeanExportObjectUrl;
    a.download=`hyras_tmean_${mode}.png`;
    document.body.appendChild(a);a.click();a.remove();
    window.setTimeout(()=>{
      if(hyrasTmeanExportObjectUrl){
        URL.revokeObjectURL(hyrasTmeanExportObjectUrl);
        hyrasTmeanExportObjectUrl=null;
      }
    },1500);
  };
}
async function hyrasTmeanDrawMap(raster,{title,subtitle,mode,resolutionKm}){
  const raw=document.createElement("canvas");
  raw.width=raster.width;raw.height=raster.height;
  const rctx=raw.getContext("2d",{alpha:true}),img=rctx.createImageData(raw.width,raw.height);
  for(let i=0,j=0;i<raster.values.length;i++,j+=4){
    if(!raster.valid[i]){img.data[j+3]=0;continue;}
    const [r,g,b,a]=hyrasTmeanColor(raster.values[i],mode);
    img.data[j]=r;img.data[j+1]=g;img.data[j+2]=b;img.data[j+3]=a;
  }
  rctx.putImageData(img,0,0);

  const effectiveKm=Number(raster.resolutionKm||resolutionKm||1);
  const canvas=document.createElement("canvas");
  if(effectiveKm===2&&hyrasTmeanIndex?.grid_1km){
    canvas.width=Number(hyrasTmeanIndex.grid_1km.width)||raw.width*2;
    canvas.height=Number(hyrasTmeanIndex.grid_1km.height)||raw.height*2;
  }else{
    const displayScale=effectiveKm<=1?1:4;
    canvas.width=raw.width*displayScale;
    canvas.height=raw.height*displayScale;
  }
  const ctx=canvas.getContext("2d",{alpha:true});
  // Keep downloaded maps white in image viewers, independently of their theme.
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.imageSmoothingEnabled=false;
  ctx.drawImage(raw,0,0,canvas.width,canvas.height);

  const frame=document.getElementById("hyrasMapFrame");
  frame.innerHTML="";
  const wrap=document.createElement("div");
  wrap.className="hyras-dynamic-wrap";
  wrap.innerHTML=`<div class="hyras-dynamic-title">${title}</div><div class="hyras-dynamic-subtitle">${subtitle}</div>`;
  wrap.appendChild(canvas);
  const legend=document.createElement("div");
  legend.className="hyras-dynamic-legend";
  legend.innerHTML=hyrasTmeanLegend(mode);
  wrap.appendChild(legend);
  frame.appendChild(wrap);

  const boundaryPromise=hyrasTmeanBoundaryBitmap().then(bmp=>{
    if(!bmp)return null;
    ctx.imageSmoothingEnabled=true;
    ctx.drawImage(bmp,0,0,canvas.width,canvas.height);
    return bmp;
  }).catch(error=>{console.warn("Tmean-Grenzen:",error);return null;});

  hyrasTmeanInstallLazyExport(document.getElementById("hyrasOpenImage"),canvas,mode,boundaryPromise);
}
function hyrasTmeanSetKpis({label,dateLabel,currentMean,referenceMean,anomalyMean,live=false,resolutionKm=1}){
  document.getElementById("hyrasPeriodStat").textContent=label||"–";document.getElementById("hyrasDataThrough").textContent=dateLabel||"–";
  const cur=document.getElementById("hyrasCurrentMean"),ref=document.getElementById("hyrasReferenceMean"),pct=document.getElementById("hyrasPercentMean"),detail=document.getElementById("hyrasAnomalyMean");
  if(cur?.parentElement?.querySelector("h4"))cur.parentElement.querySelector("h4").textContent="Rastermittel";if(ref?.parentElement?.querySelector("h4"))ref.parentElement.querySelector("h4").textContent="Mittel 1991–2020";if(pct?.parentElement?.querySelector("h4"))pct.parentElement.querySelector("h4").textContent="Abweichung";
  cur.textContent=Number.isFinite(currentMean)?`${currentMean.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} °C`:"–";document.getElementById("hyrasCurrentMeanDetail").textContent=`HYRAS-Tmean · ${resolutionKm} km Darstellung`;
  ref.textContent=Number.isFinite(referenceMean)?`${referenceMean.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} °C`:"–";document.getElementById("hyrasReferenceMeanDetail").textContent=live?"für laufenden Teilzeitraum noch nicht verfügbar":"gleicher Zeitraum 1991–2020";
  pct.textContent=Number.isFinite(anomalyMean)?`${anomalyMean>=0?"+":""}${anomalyMean.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} K`:"–";detail.textContent=Number.isFinite(anomalyMean)?"gegenüber 1991–2020":"Abweichung noch nicht verfügbar";
}
async function hyrasTmeanRenderCurrent(period){
  const mode=document.getElementById("hyrasMetricSelect")?.value||"absolute",hasAnomaly=Boolean(period.anomaly);hyrasTmeanMetricOptions(hasAnomaly);const selectedMode=document.getElementById("hyrasMetricSelect")?.value||"absolute";
  const selectedReference=hyrasReferencePeriod();
  const anomalyPath=period.anomaly_by_reference?.[selectedReference]||period.anomaly;
  const path=selectedMode==="anomaly"?anomalyPath:period.absolute;if(!path)throw new Error(`Für diesen Tmean-Zeitraum ist die Abweichung zu ${hyrasReferenceDisplay()} noch nicht verfügbar.`);
  const raw=await hyrasTmeanLoadI16(path),w=Number(hyrasTmeanIndex.grid_1km.width),h=Number(hyrasTmeanIndex.grid_1km.height),raster=hyrasTmeanDecodePlane(raw,w,h,100,-32768,0,HYRAS_TMEAN_CURRENT_DISPLAY_FACTOR);
  const refStats=period.stats_by_reference?.[selectedReference]||period.stats||{},stats=period.stats||{},anom=Number(refStats.anomaly_mean_k),ref=Number(refStats.reference_mean_c),cur=Number(stats.current_mean_c);
  hyrasTmeanSetKpis({label:period.label,dateLabel:`${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`,currentMean:cur,referenceMean:ref,anomalyMean:anom,live:Boolean(period.live),resolutionKm:2});
  await hyrasTmeanDrawMap(raster,{title:`HYRAS Tmean · ${period.label}`,subtitle:`${selectedMode==="anomaly"?`Abweichung ${hyrasReferenceDisplay()}`:"2-m-Temperaturmittel"} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`,mode:selectedMode,resolutionKm:2});
  const note=document.getElementById("hyrasReferenceNote");if(note)note.textContent=period.reference_exact?"Quelle: Deutscher Wetterdienst · HYRAS-DE Tmean. Abweichung gegenüber dem gleichen Zeitraum 1991–2020.":"Quelle: Deutscher Wetterdienst · HYRAS-DE Tmean. Für laufende Teilzeiträume ist in dieser Stufe zunächst die absolute Temperatur verfügbar.";
}
async function hyrasTmeanApplyHistorical(){
  const msg=document.getElementById("hyrasHistoricalMessage");try{
    await hyrasTmeanEnsureLoaded();const year=Number(document.getElementById("hyrasHistoricalYear")?.value),type=document.getElementById("hyrasHistoricalType")?.value||"month",month=Number(document.getElementById("hyrasHistoricalMonth")?.value||1);if(!Number.isFinite(year))throw new Error("Bitte ein historisches Jahr auswählen.");
    const selection=hyrasTmeanHistoricalSelection(year,type,month),available=new Set((hyrasTmeanHistoryManifest.years||[]).map(Number));for(const item of selection){if(!available.has(item.year))throw new Error(`${hyrasTmeanHistoricalLabel(year,type,month)} benötigt das nicht verfügbare Jahr ${item.year}.`);}
    if(msg)msg.textContent="Historische Tmean-Karte wird aus den Monatsrastern zusammengesetzt …";const current=await hyrasTmeanHistoricalRaster(selection,year),reference=await hyrasTmeanHistoricalReference(type,month);hyrasTmeanHistoricalState={year,type,month,label:hyrasTmeanHistoricalLabel(year,type,month),current,reference,anomaly:hyrasTmeanSubtract(current,reference)};
    const select=document.getElementById("hyrasPeriodSelect");if(select)select.value="__historical__";await hyrasTmeanRenderHistorical();if(msg)msg.textContent=`${hyrasTmeanHistoricalState.label} geladen · ${hyrasTmeanHistoryManifest.resolution_km}-km-Analyseraster.`;
  }catch(error){console.error("Tmean Historie:",error);if(msg){msg.className="hyras-custom-message error";msg.textContent=error.message;}}
}
async function hyrasTmeanRenderHistorical(){
  const state=hyrasTmeanHistoricalState;if(!state){const frame=document.getElementById("hyrasMapFrame");if(frame)frame.innerHTML='<div class="hyras-loading">Historisches Tmean-Jahr unten auswählen und „Anzeigen“ klicken.</div>';return;}
  hyrasTmeanMetricOptions(true);const mode=document.getElementById("hyrasMetricSelect")?.value||"absolute",raster=mode==="anomaly"?state.anomaly:state.current,cur=hyrasTmeanMean(state.current),ref=hyrasTmeanMean(state.reference),anom=cur-ref;
  hyrasTmeanSetKpis({label:state.label,dateLabel:`Historische HYRAS-Tmean-Karte · ${state.year}`,currentMean:cur,referenceMean:ref,anomalyMean:anom,live:false,resolutionKm:Number(hyrasTmeanHistoryManifest.resolution_km||5)});
  await hyrasTmeanDrawMap(raster,{title:`HYRAS Tmean · ${state.label}`,subtitle:`${mode==="anomaly"?`Abweichung ${hyrasReferenceDisplay()}`:"2-m-Temperaturmittel"} · Historie seit ${hyrasTmeanHistoryManifest.first_year}`,mode,resolutionKm:Number(hyrasTmeanHistoryManifest.resolution_km||5)});
  const note=document.getElementById("hyrasReferenceNote");if(note)note.textContent=`Quelle: Deutscher Wetterdienst · HYRAS-DE Tmean. Historische Karten ${hyrasTmeanHistoryManifest.first_year}–${hyrasTmeanHistoryManifest.last_year} auf ${hyrasTmeanHistoryManifest.resolution_km}-km-Analyseraster; Referenz 1991–2020.`;
}

const hyrasDailyAnomalyManifestCache=new Map();
let hyrasDailyAnomalySelectedDate=null;
function hyrasDailyAnomalyBase(parameter){return `${HYRAS_DATA_BASE}/${parameter}/regions`;}
function hyrasDailyAnomalyParameterLabel(parameter){
  return parameter==="tmax"?"Tmax":parameter==="tmin"?"Tmin":"Tmean";
}
function hyrasDailyAnomalyPanelHtml(parameter){
  return `<div class="hyras-daily-anomaly-panel" id="hyrasDailyAnomalyPanel" data-parameter="${parameter}">
    <div class="hyras-daily-anomaly-head">
      <div>
        <h4>Ganzjährige 2-m-Tagesabweichung · ${hyrasDailyAnomalyParameterLabel(parameter)}</h4>
        <p id="hyrasDailyAnomalyMeta">Tageskarte wird geladen …</p>
      </div>
      <a class="hyras-tmean-download disabled" id="hyrasDailyAnomalyAnimationDownload" href="#" aria-disabled="true">Animation wird erzeugt …</a>
    </div>
    <div class="hyras-daily-anomaly-controls">
      <button class="action" type="button" id="hyrasDailyAnomalyPrev" aria-label="Vorheriger Tag">◀</button>
      <input id="hyrasDailyAnomalyRange" type="range" min="0" max="0" value="0" step="1" aria-label="Tag auswählen">
      <button class="action" type="button" id="hyrasDailyAnomalyNext" aria-label="Nächster Tag">▶</button>
      <div class="hyras-daily-anomaly-date" id="hyrasDailyAnomalyDate">–</div>
      <label class="hyras-daily-anomaly-calendar">Datum direkt wählen <input id="hyrasDailyAnomalyCalendar" type="date" aria-label="HYRAS-Tageskarte für Datum auswählen"></label>
    </div>
    <a class="hyras-daily-anomaly-link" id="hyrasDailyAnomalyLink" target="_blank" rel="noopener">
      <img id="hyrasDailyAnomalyImage" alt="HYRAS tägliche Temperaturabweichung" loading="eager">
    </a>
    <div class="hyras-daily-anomaly-status" id="hyrasDailyAnomalyStatus">Lade Tagesanomaliekarten …</div>
  </div>`;
}
async function hyrasDailyAnomalyManifest(parameter){
  if(hyrasDailyAnomalyManifestCache.has(parameter))return hyrasDailyAnomalyManifestCache.get(parameter);
  const version=parameter==="tmean"
    ?hyrasTmeanRegionsIndex?.data_through
    :parameter==="tmax"
      ?hyrasTmaxRegionsIndex?.data_through
      :hyrasTminRegionsIndex?.data_through;
  const response=await fetch(
    `${hyrasDailyAnomalyBase(parameter)}/daily_anomaly_maps.json?v=${encodeURIComponent(version||"1")}`,
    {cache:"no-store"}
  );
  if(!response.ok)throw new Error(`Tagesanomaliekarten fehlen (${response.status}).`);
  const manifest=await response.json();
  hyrasDailyAnomalyManifestCache.set(parameter,manifest);
  return manifest;
}
function hyrasDailyAnomalyDateLabel(iso){
  if(!iso)return "–";
  const [y,m,d]=String(iso).split("-");
  return `${d}.${m}.${y}`;
}
function hyrasDailyAnomalyRowsDates(rows,manifest){
  // Die Tageskarten sind unabhängig von der oben gewählten Monats-/Gebietsauswertung.
  return Array.isArray(manifest?.available_dates)?manifest.available_dates:[];
}
function hyrasDailyAnomalySetDate(parameter,manifest,dates,index){
  const range=document.getElementById("hyrasDailyAnomalyRange");
  const calendar=document.getElementById("hyrasDailyAnomalyCalendar");
  const prev=document.getElementById("hyrasDailyAnomalyPrev");
  const next=document.getElementById("hyrasDailyAnomalyNext");
  const dateEl=document.getElementById("hyrasDailyAnomalyDate");
  const meta=document.getElementById("hyrasDailyAnomalyMeta");
  const status=document.getElementById("hyrasDailyAnomalyStatus");
  const image=document.getElementById("hyrasDailyAnomalyImage");
  const link=document.getElementById("hyrasDailyAnomalyLink");
  if(!range||!dateEl||!image||!link)return;

  const clamped=Math.max(0,Math.min(Number(index)||0,dates.length-1));
  const iso=dates[clamped];
  hyrasDailyAnomalySelectedDate=iso||null;
  range.value=String(clamped);
  if(calendar&&iso)calendar.value=iso;
  if(prev)prev.disabled=clamped<=0;
  if(next)next.disabled=clamped>=dates.length-1;
  dateEl.textContent=iso?hyrasDailyAnomalyDateLabel(iso):"–";

  const reference=hyrasReferencePeriod();
  const rel=iso?manifest?.dates?.[iso]?.[reference]:null;
  if(!rel){
    image.removeAttribute("src");
    link.removeAttribute("href");
    if(meta)meta.textContent=`${iso?hyrasDailyAnomalyDateLabel(iso):"Kein Tag"} · Referenz ${hyrasReferenceDisplay()}`;
    if(status)status.textContent="Für diesen Tag und diese Referenz ist keine Tagesanomaliekarte verfügbar.";
    return;
  }
  const src=`${hyrasDailyAnomalyBase(parameter)}/${rel}?v=${encodeURIComponent(manifest?.data_through||"1")}`;
  image.src=src;
  image.alt=`HYRAS ${hyrasDailyAnomalyParameterLabel(parameter)} Tagesabweichung ${hyrasDailyAnomalyDateLabel(iso)} gegenüber ${hyrasReferenceDisplay()}`;
  link.href=src;
  if(meta)meta.textContent=`${hyrasDailyAnomalyDateLabel(iso)} · Abweichung gegenüber ${hyrasReferenceDisplay()} · eigene Tages-Skala ±18 K`;
  if(status)status.textContent=`Nur Tagesanomalien: Skala −18 bis +18 K · Darstellung ca. ${manifest?.resolution_km||5} km`;
}
const HYRAS_DAILY_ANIMATION_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/hyras-animations";
let hyrasDailyAnomalyAnimationManifestPromise=null;
async function hyrasDailyAnomalyAnimationManifest(){
  if(!hyrasDailyAnomalyAnimationManifestPromise){
    hyrasDailyAnomalyAnimationManifestPromise=fetch(
      `${HYRAS_DAILY_ANIMATION_BASE}/manifest.json?t=${Date.now()}`,
      {cache:"no-store"}
    ).then(response=>{
      if(!response.ok)throw new Error(`Animationsmanifest fehlt (HTTP ${response.status}).`);
      return response.json();
    }).catch(error=>{
      hyrasDailyAnomalyAnimationManifestPromise=null;
      throw error;
    });
  }
  return hyrasDailyAnomalyAnimationManifestPromise;
}
async function hyrasDailyAnomalyConfigureAnimationDownload(parameter,manifest,panel){
  const link=panel?.querySelector("#hyrasDailyAnomalyAnimationDownload");
  if(!link)return;
  const reference=hyrasReferencePeriod();
  let animationManifest=null;
  try{animationManifest=await hyrasDailyAnomalyAnimationManifest();}
  catch(error){console.warn("HYRAS Tagesanomalie-Animationsmanifest:",error);}
  if(document.getElementById("hyrasDailyAnomalyPanel")!==panel)return;
  const animationParameter=animationManifest?.parameters?.[parameter];
  const animation=animationParameter?.references?.[reference];
  if(!animation?.url||animationParameter?.data_through!==manifest?.data_through){
    link.classList.add("disabled");
    link.setAttribute("aria-disabled","true");
    link.removeAttribute("href");
    link.textContent=animation?.url?"Animation wird aktualisiert …":"Animation wird erzeugt …";
    link.onclick=event=>event.preventDefault();
    return;
  }
  const url=`${HYRAS_DAILY_ANIMATION_BASE}/${animation.url}?v=${encodeURIComponent(animationParameter.data_through||"1")}`;
  const label=hyrasDailyAnomalyParameterLabel(parameter);
  const filename=`HYRAS_${label}_Tagesabweichungen_${reference}.mp4`;
  link.classList.remove("disabled");
  link.setAttribute("aria-disabled","false");
  link.href=url;
  link.textContent="Animation herunterladen (MP4)";
  link.onclick=async event=>{
    event.preventDefault();
    if(link.classList.contains("disabled"))return;
    const status=panel.querySelector("#hyrasDailyAnomalyStatus");
    const original=link.textContent;
    link.classList.add("disabled");
    link.setAttribute("aria-busy","true");
    link.textContent="MP4 wird geladen …";
    if(status)status.textContent=`Animation ${label} · Referenz ${reference.replace("-","–")} wird heruntergeladen …`;
    try{
      const response=await fetch(url,{cache:"no-store"});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const blob=await response.blob();
      const objectUrl=URL.createObjectURL(blob);
      const download=document.createElement("a");
      download.href=objectUrl;
      download.download=filename;
      document.body.appendChild(download);
      download.click();
      download.remove();
      setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
      if(status)status.textContent=`MP4-Animation · ${animation.frame_count||"?"} Tage · ${animation.fps||"?"} Bilder/s · Referenz ${reference.replace("-","–")}`;
    }catch(error){
      console.error("HYRAS Tagesanomalie-Animation:",error);
      if(status)status.textContent="Die MP4-Animation konnte nicht heruntergeladen werden.";
    }finally{
      link.classList.remove("disabled");
      link.removeAttribute("aria-busy");
      link.textContent=original;
    }
  };
}
async function hyrasDailyAnomalyMount(parameter,rows){
  const panel=document.getElementById("hyrasDailyAnomalyPanel");
  if(!panel)return;
  const mountedPanel=panel;
  const status=panel.querySelector("#hyrasDailyAnomalyStatus");
  const image=panel.querySelector("#hyrasDailyAnomalyImage");
  try{
    const manifest=await hyrasDailyAnomalyManifest(parameter);

    // Falls während des Ladens neu gerendert wurde, darf dieser alte
    // Initialisierungslauf keine Handler an die neue Box hängen.
    if(document.getElementById("hyrasDailyAnomalyPanel")!==mountedPanel)return;

    await hyrasDailyAnomalyConfigureAnimationDownload(parameter,manifest,panel);
    const dates=hyrasDailyAnomalyRowsDates(rows,manifest);
    const range=panel.querySelector("#hyrasDailyAnomalyRange");
    const calendar=panel.querySelector("#hyrasDailyAnomalyCalendar");
    const prev=panel.querySelector("#hyrasDailyAnomalyPrev");
    const next=panel.querySelector("#hyrasDailyAnomalyNext");
    if(!dates.length){
      if(image)image.removeAttribute("src");
      if(status)status.textContent="Für den gewählten Zeitraum liegen noch keine täglichen Anomaliekarten vor.";
      const meta=panel.querySelector("#hyrasDailyAnomalyMeta");
      if(meta)meta.textContent="Tageskarten werden für das vollständige Kalenderjahr aufgebaut.";
      if(range)range.disabled=true;
      if(calendar)calendar.disabled=true;
      if(prev)prev.disabled=true;
      if(next)next.disabled=true;
      return;
    }
    let initial=dates.length-1;
    if(hyrasDailyAnomalySelectedDate&&dates.includes(hyrasDailyAnomalySelectedDate)){
      initial=dates.indexOf(hyrasDailyAnomalySelectedDate);
    }
    if(range){
      range.disabled=false;
      range.min="0";
      range.max=String(dates.length-1);
      range.step="1";
      range.oninput=()=>hyrasDailyAnomalySetDate(
        parameter,manifest,dates,Number(range.value)
      );
    }
    if(calendar){
      calendar.disabled=false;
      calendar.min=dates[0];
      calendar.max=dates[dates.length-1];
      calendar.onchange=()=>{
        const wanted=calendar.value;
        const exact=dates.indexOf(wanted);
        const near=dates.findIndex(day=>day>=wanted);
        hyrasDailyAnomalySetDate(parameter,manifest,dates,exact>=0?exact:Math.max(0,near));
      };
    }
    if(prev)prev.onclick=()=>{
      const current=Number(range?.value||0);
      hyrasDailyAnomalySetDate(parameter,manifest,dates,current-1);
    };
    if(next)next.onclick=()=>{
      const current=Number(range?.value||0);
      hyrasDailyAnomalySetDate(parameter,manifest,dates,current+1);
    };
    hyrasDailyAnomalySetDate(parameter,manifest,dates,initial);
  }catch(error){
    console.warn("HYRAS Tagesanomalien:",error);
    if(document.getElementById("hyrasDailyAnomalyPanel")!==mountedPanel)return;
    if(image)image.removeAttribute("src");
    const meta=panel.querySelector("#hyrasDailyAnomalyMeta");
    if(meta)meta.textContent="Tagesanomaliekarten werden noch aufgebaut.";
    if(status)status.textContent="Noch nicht verfügbar – bitte nach Abschluss des HYRAS-Tageskarten-Workflows neu laden.";
  }
}
function hyrasTmeanRegionsBase(){return `${HYRAS_DATA_BASE}/tmean/regions`;}
async function hyrasTmeanRegionsFetch(path){
  const response=await fetch(`${hyrasTmeanRegionsBase()}/${path}?v=${encodeURIComponent(hyrasTmeanRegionsIndex?.data_through||"1")}`);
  if(!response.ok)throw new Error(`Tmean-Gebietsdaten ${path} fehlen (${response.status}).`);
  return response.json();
}
async function hyrasTmeanRegionsEnsureLoaded(){
  if(hyrasTmeanRegionsIndex&&hyrasTmeanRegionsCurrent&&hyrasTmeanRegionsClimate&&hyrasTmeanMapDownloads&&hyrasTmeanRegionsRecords)return hyrasTmeanRegionsIndex;
  if(hyrasTmeanRegionsLoading)return hyrasTmeanRegionsLoading;
  hyrasTmeanRegionsLoading=(async()=>{
    hyrasTmeanRegionsIndex=await hyrasTmeanRegionsFetch("index.json");
    const [current,climate,maps,records]=await Promise.all([
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.current_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.climate_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.map_downloads_file),
      hyrasTmeanRegionsFetch(hyrasTmeanRegionsIndex.records_file),
    ]);
    hyrasTmeanRegionsCurrent=current;hyrasTmeanRegionsClimate=climate;hyrasTmeanRegionsClimateReference=String(climate?.reference||hyrasTmeanRegionsIndex?.default_reference||"1991-2020");hyrasTmeanMapDownloads=maps;hyrasTmeanRegionsRecords=records;
    return hyrasTmeanRegionsIndex;
  })().finally(()=>{hyrasTmeanRegionsLoading=null;});
  return hyrasTmeanRegionsLoading;
}
async function hyrasTmeanEnsureClimateReference(){
  const reference=hyrasReferencePeriod();
  if(hyrasTmeanRegionsClimate&&hyrasTmeanRegionsClimateReference===reference)return hyrasTmeanRegionsClimate;
  const path=hyrasTmeanRegionsIndex?.climate_files_by_reference?.[reference]
    ||(reference==="1991-2020"?hyrasTmeanRegionsIndex?.climate_file:null);
  if(!path)throw new Error(`Tmean-Gebietskurve für Referenz ${hyrasReferenceDisplay()} ist noch nicht veröffentlicht.`);
  const climate=await hyrasTmeanRegionsFetch(path);
  if(hyrasReferencePeriod()===reference&&hyrasParameter()==="tmean"){
    hyrasTmeanRegionsClimate=climate;
    hyrasTmeanRegionsClimateReference=reference;
  }
  return climate;
}
function hyrasTmeanPopulateRegions(){
  const select=document.getElementById("hyrasTmeanRegionSelect");if(!select||!hyrasTmeanRegionsIndex)return;
  const previous=select.value||"Deutschland";
  select.innerHTML=(hyrasTmeanRegionsIndex.regions||[]).map(name=>`<option value="${name.replace(/"/g,"&quot;")}">${name}</option>`).join("");
  select.value=(hyrasTmeanRegionsIndex.regions||[]).includes(previous)?previous:"Deutschland";
}
function hyrasTmeanPopulateCurvePeriods(){
  const select=document.getElementById("hyrasPeriodSelect");if(!select||!hyrasTmeanRegionsIndex)return;
  const previous=select.value,periods=hyrasTmeanRegionsIndex.periods||[];
  select.innerHTML=periods.map(p=>`<option value="${p.key}">${p.label}</option>`).join("");
  const preferred=periods.filter(p=>p.key.startsWith("month_")).sort((a,b)=>String(b.end_date).localeCompare(String(a.end_date)))[0]||periods[0];
  if(previous&&periods.some(p=>p.key===previous))select.value=previous;else if(preferred)select.value=preferred.key;
}
function hyrasTemperatureResolvePeriod(index,populate){
  const select=document.getElementById("hyrasPeriodSelect"),periods=index?.periods||[];
  const key=select?.value,exact=periods.find(p=>p.key===key);
  if(exact)return exact;
  // Recover a selector populated by an earlier precipitation request. Never
  // silently render the first (year-to-date) period for an unknown key.
  const previous=hyrasIndex?.periods?.find(p=>p.key===key);
  const mapped=periods.find(p=>p.map_key===key&&key)||
    (previous?.period_type?.startsWith("month")?periods.find(p=>p.key.startsWith("month_")&&p.start_date===previous.start_date):null)||
    (previous?periods.find(p=>p.start_date===previous.start_date&&p.end_date===previous.end_date):null);
  populate();
  if(mapped&&select)select.value=mapped.key;
  return periods.find(p=>p.key===select?.value)||null;
}
function hyrasTmeanCurvePeriod(){
  return hyrasTemperatureResolvePeriod(hyrasTmeanRegionsIndex,hyrasTmeanPopulateCurvePeriods);
}
function hyrasTmeanRegionName(){return document.getElementById("hyrasTmeanRegionSelect")?.value||"Deutschland";}
function hyrasTmeanCurveRows(region,period){
  const dates=hyrasTmeanRegionsCurrent?.dates||[],values=hyrasTmeanRegionsCurrent?.regions?.[region]||[],climate=hyrasTmeanRegionsClimate?.regions?.[region]||{},records=hyrasTmeanRegionsRecords?.regions?.[region]||{};
  const rows=[];
  for(let i=0;i<dates.length;i++){
    const date=dates[i];if(date<period.start_date||date>period.end_date)continue;
    const mmdd=date.slice(5,10),current=Number(values[i]),normal=Number(climate[mmdd]),record=records[mmdd]||{};
    const recordMax=record.max===null||record.max===undefined?null:Number(record.max),recordMin=record.min===null||record.min===undefined?null:Number(record.min);
    rows.push({date,current:Number.isFinite(current)?current:null,normal:Number.isFinite(normal)?normal:null,recordMax:Number.isFinite(recordMax)?recordMax:null,recordMin:Number.isFinite(recordMin)?recordMin:null,recordMaxYears:Array.isArray(record.max_years)?record.max_years:[],recordMinYears:Array.isArray(record.min_years)?record.min_years:[]});
  }
  return rows;
}
function hyrasTmeanMeanOf(values){const valid=values.filter(Number.isFinite);return valid.length?valid.reduce((a,b)=>a+b,0)/valid.length:NaN;}
function hyrasTmeanFmt(value,unit="°C",signed=false){
  if(!Number.isFinite(value))return "–";const sign=signed&&value>0?"+":"";
  return `${sign}${value.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} ${unit}`;
}
function hyrasTmeanSetCurveKpis(region,period,rows){
  const current=hyrasTmeanMeanOf(rows.map(r=>r.current)),normal=hyrasTmeanMeanOf(rows.map(r=>r.normal)),anom=current-normal;
  const setHeading=(id,text)=>{const el=document.getElementById(id),h=el?.parentElement?.querySelector("h4");if(h)h.textContent=text;};
  document.getElementById("hyrasPeriodStat").textContent=period.label;
  document.getElementById("hyrasDataThrough").textContent=`${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`;
  setHeading("hyrasCurrentMean",`Mittel ${hyrasTmeanRegionsIndex.year}`);document.getElementById("hyrasCurrentMean").textContent=hyrasTmeanFmt(current);document.getElementById("hyrasCurrentMeanDetail").textContent=region;
  setHeading("hyrasReferenceMean",`Mittel ${hyrasReferenceDisplay()}`);document.getElementById("hyrasReferenceMean").textContent=hyrasTmeanFmt(normal);document.getElementById("hyrasReferenceMeanDetail").textContent="exakt dieselben Kalendertage";
  setHeading("hyrasPercentMean","Abweichung");document.getElementById("hyrasPercentMean").textContent=hyrasTmeanFmt(anom,"K",true);
  setHeading("hyrasAnomalyMean","Datentage");document.getElementById("hyrasAnomalyMean").textContent=String(rows.filter(r=>Number.isFinite(r.current)).length);
  document.getElementById("hyrasReferenceNote").textContent=hyrasTmeanRegionsIndex.method_note||`HYRAS-Tmean-Gebietsmittel, Referenz ${hyrasReferenceDisplay()}.`;
}
// HYRAS_TMEAN_MAP_DOWNLOAD_FIX_V2
function hyrasTmeanDownloadHref(path){return path?`${HYRAS_DATA_BASE}/tmean/${path}`:"#";}
function hyrasTemperaturePreviewHref(url,version){
  if(!url||url==="#")return "#";
  const separator=url.includes("?")?"&":"?";
  return `${url}${separator}v=${encodeURIComponent(version||"1")}`;
}
async function hyrasTmeanForceMapDownload(event,path,filename){
  if(event)event.preventDefault();
  if(!path)return;

  const url=hyrasTmeanDownloadHref(path);
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
    const a=document.createElement("a");
    a.href=objectUrl;
    a.download=filename||path.split("/").pop()||"hyras_tmean.png";
    a.style.display="none";
    document.body.appendChild(a);
    a.click();
    a.remove();

    window.setTimeout(()=>URL.revokeObjectURL(objectUrl),2000);
  }catch(error){
    console.error("HYRAS Tmean Kartendownload:",error);
    window.open(url,"_blank","noopener,noreferrer");
  }finally{
    if(link){
      link.style.pointerEvents="";
      link.style.opacity="";
      link.textContent=oldText;
    }
  }
}
// HYRAS_TMEAN_PDF_EXPORT_V1
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
    const exportChart=window.Chart?.getChart(canvas);
    ctx.drawImage(exportChart?chartCanvasWithWhiteBackground(exportChart):canvas,0,0);

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
    pdf.text(`${period?.label||""} | taegliches HYRAS-Gebietsmittel gegen ${hyrasReferencePeriod()}`,margin,21);

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

function hyrasTmeanRenderCurveChart(region,period,rows){
  const frame=document.getElementById("hyrasMapFrame");if(!frame)return;
  if(hyrasTmeanRegionChart){hyrasTmeanRegionChart.destroy();hyrasTmeanRegionChart=null;}
  const mapsBase=hyrasTmeanMapDownloads?.periods?.[period.map_key]||{},maps={...mapsBase,anomaly:(window.HyrasTemperatureInteractive?HyrasTemperatureInteractive.mapForReference(mapsBase, hyrasReferencePeriod(),period.start_date,period.end_date):(hyrasReferencePeriod()==='1991-2020'?mapsBase.anomaly:null))};
  const absClass=maps.absolute?"hyras-tmean-download":"hyras-tmean-download disabled";
  const anomClass=maps.anomaly?"hyras-tmean-download":"hyras-tmean-download disabled";
  frame.innerHTML=`<div class="hyras-tmean-region-panel">
    ${maps.anomaly?`<div class="hyras-tmean-anomaly-preview">
      <div class="hyras-tmean-anomaly-preview-head">
        <div>
          <h4>2-m-Temperaturabweichung</h4>
          <p>${period.label} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)} · Abweichung gegenüber ${hyrasReferenceDisplay()}</p>
        </div>
      </div>
      <a class="hyras-tmean-anomaly-preview-link" href="${hyrasTemperaturePreviewHref(hyrasTmeanDownloadHref(maps.anomaly),hyrasTmeanRegionsIndex?.data_through)}" target="_blank" rel="noopener">
        <img src="${hyrasTemperaturePreviewHref(hyrasTmeanDownloadHref(maps.anomaly),hyrasTmeanRegionsIndex?.data_through)}" alt="HYRAS 2-m-Temperaturabweichung ${period.label} gegenüber ${hyrasReferenceDisplay()}" loading="eager">
      </a>
      <div class="hyras-temperature-raster-status" role="status">Rasterabfrage wird geladen …</div>
    </div>`:`<div class="hyras-tmean-anomaly-preview"><div class="hyras-tmean-anomaly-preview-empty">Für diesen Zeitraum ist keine fertige Abweichungskarte verfügbar.</div><div class="hyras-temperature-raster-status" role="status">Rasterabfrage wird geladen …</div></div>`}
    <div class="hyras-tmean-region-head"><div><h3>Temperaturmittel – ${region}</h3><p>${period.label} · tägliches HYRAS-Gebietsmittel gegen ${hyrasReferenceDisplay()}</p></div></div>
    <div class="hyras-tmean-chart-wrap"><canvas id="hyrasTmeanRegionCanvas"></canvas></div>
    ${hyrasDailyAnomalyPanelHtml("tmean")}
    <div class="hyras-tmean-downloads">
      <a class="${absClass}" ${maps.absolute?`href="${hyrasTmeanDownloadHref(maps.absolute)}" data-tmean-map="${maps.absolute}" data-tmean-filename="hyras_tmean_${period.map_key}_temperatur.png"`:""}>Temperaturkarte herunterladen</a>
      <a class="${anomClass}" ${maps.anomaly?`href="${hyrasTmeanDownloadHref(maps.anomaly)}" data-tmean-map="${maps.anomaly}" data-tmean-filename="hyras_tmean_${period.map_key}_abweichung_${hyrasReferencePeriod().replace("-","_")}.png"`:""}>Abweichungskarte ${hyrasReferenceDisplay()} herunterladen</a>
      <a class="hyras-tmean-download" href="#" data-tmean-pdf="1">Kurve als PDF herunterladen</a>
    </div>
    <p class="hyras-tmean-region-note">${maps.anomaly?"Absolute Temperatur- und Anomaliekarte stehen als fertige PNGs bereit.":"Für diesen laufenden Zeitraum ist die absolute Temperaturkarte als fertige PNG verfügbar; die Gebietskurve nutzt trotzdem bereits die tagesgenaue 1991–2020-Referenz."}</p>
  </div>`;
  window.HyrasTemperatureInteractive?.mount(frame.querySelector(".hyras-tmean-anomaly-preview"),{entry:mapsBase,parameter:"tmean",reference:hyrasReferencePeriod(),key:period.map_key,start:period.start_date,end:period.end_date,version:hyrasTmeanRegionsIndex?.data_through||"1",base:HYRAS_DATA_BASE,boundary:hyrasIndex?.interactive?.boundary_overlay_1km});
  frame.querySelectorAll("a[data-tmean-map]").forEach(link=>{
    link.addEventListener("click",event=>hyrasTmeanForceMapDownload(
      event,
      link.dataset.tmeanMap,
      link.dataset.tmeanFilename
    ));
  });
  frame.querySelector("a[data-tmean-pdf]")?.addEventListener(
    "click",
    event=>hyrasTmeanExportCurvePdf(event,region,period)
  );
  hyrasDailyAnomalyMount("tmean",rows);
  const labels=rows.map(r=>{const [,m,d]=r.date.split("-");return `${d}.${m}.`;});
  const climate=rows.map(r=>r.normal),current=rows.map(r=>r.current),recordMax=rows.map(r=>r.recordMax),recordMin=rows.map(r=>r.recordMin);
  const recordFirst=Number(hyrasTmeanRegionsIndex.records_first_year||hyrasTmeanRegionsRecords?.first_year||1951),recordLast=Number(hyrasTmeanRegionsIndex.records_last_year||hyrasTmeanRegionsRecords?.last_year||2025);
  hyrasTmeanRegionChart=new Chart(document.getElementById("hyrasTmeanRegionCanvas"),{
    type:"line",
    data:{labels,datasets:[
      {label:`Mittel ${hyrasReferenceDisplay()}`,data:climate,borderColor:"#666",borderWidth:2,pointRadius:0,tension:.08,spanGaps:false},
      {label:`${hyrasTmeanRegionsIndex.year}`,data:current,borderColor:"#111",borderWidth:2.4,pointRadius:0,tension:.08,spanGaps:false,fill:{target:0,above:"rgba(210,55,45,.28)",below:"rgba(55,115,190,.28)"}},
      {label:`Historisches Maximum ${recordFirst}–${recordLast}`,data:recordMax,borderColor:"#b42318",backgroundColor:"transparent",borderWidth:1.5,borderDash:[6,4],pointRadius:0,tension:.04,spanGaps:false},
      {label:`Historisches Minimum ${recordFirst}–${recordLast}`,data:recordMin,borderColor:"#1f5f99",backgroundColor:"transparent",borderWidth:1.5,borderDash:[6,4],pointRadius:0,tension:.04,spanGaps:false}
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:250},interaction:{mode:"index",intersect:false},
      plugins:{legend:{display:true},datalabels:{display:false},tooltip:{filter:item=>item.datasetIndex<2,callbacks:{afterBody(items){
        if(!items?.length)return "";
        const i=items[0].dataIndex,a=current[i],b=climate[i],row=rows[i]||{},lines=[];
        if(Number.isFinite(a)&&Number.isFinite(b))lines.push(`Abweichung: ${(a-b)>=0?"+":""}${(a-b).toFixed(2).replace(".",",")} K`);
        if(Number.isFinite(row.recordMax))lines.push(`Historisches Maximum: ${row.recordMax.toFixed(2).replace(".",",")} °C (${(row.recordMaxYears||[]).join(", ")})`);
        if(Number.isFinite(row.recordMin))lines.push(`Historisches Minimum: ${row.recordMin.toFixed(2).replace(".",",")} °C (${(row.recordMinYears||[]).join(", ")})`);
        return lines;
      }}}},
      scales:{x:{ticks:{maxTicksLimit:14}},y:{title:{display:true,text:"Temperatur (°C)"}}}
    }
  });
}
// HYRAS_TMAX_FRONTEND_V1
let hyrasTmaxRegionsIndex=null;
let hyrasTmaxRegionsCurrent=null;
let hyrasTmaxRegionsClimate=null;
let hyrasTmaxRegionsClimateReference=null;
let hyrasTmaxRegionsRecords=null;
// HYRAS_TMAX_MAP_DOWNLOADS_V1
let hyrasTmaxMapDownloads=null;
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
  if(hyrasTmaxRegionsIndex&&hyrasTmaxRegionsCurrent&&hyrasTmaxRegionsClimate&&hyrasTmaxRegionsRecords&&hyrasTmaxMapDownloads){
    return hyrasTmaxRegionsIndex;
  }
  if(hyrasTmaxRegionsLoading)return hyrasTmaxRegionsLoading;

  hyrasTmaxRegionsLoading=(async()=>{
    hyrasTmaxRegionsIndex=await hyrasTmaxRegionsFetch("index.json");
    const [current,climate,records,maps]=await Promise.all([
      hyrasTmaxRegionsFetch(hyrasTmaxRegionsIndex.current_file),
      hyrasTmaxRegionsFetch(hyrasTmaxRegionsIndex.climate_file),
      hyrasTmaxRegionsFetch(hyrasTmaxRegionsIndex.records_file),
      hyrasTmaxRegionsFetch(hyrasTmaxRegionsIndex.map_downloads_file),
    ]);
    hyrasTmaxRegionsCurrent=current;
    hyrasTmaxRegionsClimate=climate;
    hyrasTmaxRegionsClimateReference=String(climate?.reference||hyrasTmaxRegionsIndex?.default_reference||"1991-2020");
    hyrasTmaxRegionsRecords=records;
    hyrasTmaxMapDownloads=maps;
    return hyrasTmaxRegionsIndex;
  })().finally(()=>{hyrasTmaxRegionsLoading=null;});

  return hyrasTmaxRegionsLoading;
}
async function hyrasTmaxEnsureClimateReference(){
  const reference=hyrasReferencePeriod();
  if(hyrasTmaxRegionsClimate&&hyrasTmaxRegionsClimateReference===reference)return hyrasTmaxRegionsClimate;
  const path=hyrasTmaxRegionsIndex?.climate_files_by_reference?.[reference]
    ||(reference==="1991-2020"?hyrasTmaxRegionsIndex?.climate_file:null);
  if(!path)throw new Error(`Tmax-Gebietskurve für Referenz ${hyrasReferenceDisplay()} ist noch nicht veröffentlicht.`);
  const climate=await hyrasTmaxRegionsFetch(path);
  if(hyrasReferencePeriod()===reference&&hyrasParameter()==="tmax"){
    hyrasTmaxRegionsClimate=climate;
    hyrasTmaxRegionsClimateReference=reference;
  }
  return climate;
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
  const preferred=periods.filter(period=>period.key.startsWith("month_")).sort((a,b)=>String(b.end_date).localeCompare(String(a.end_date)))[0]||periods.find(period=>period.key==="summer")||periods[0];
  if(previous&&periods.some(period=>period.key===previous)){
    select.value=previous;
  }else if(preferred){
    select.value=preferred.key;
  }
}
function hyrasTmaxCurvePeriod(){
  return hyrasTemperatureResolvePeriod(hyrasTmaxRegionsIndex,hyrasTmaxPopulateCurvePeriods);
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

  setHeading("hyrasReferenceMean",`Mittel ${hyrasReferenceDisplay()}`);
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
    `HYRAS-Tmax-Gebietsmittel, Referenz ${hyrasReferenceDisplay()}.`;
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
    pdf.text(`Tagesmaximum - ${region}`,margin,15);

    pdf.setFont("helvetica","normal");
    pdf.setFontSize(9.5);
    pdf.setTextColor(85,95,105);
    pdf.text(
      `${period?.label||""} | taegliches HYRAS-Tmax-Gebietsmittel gegen ${hyrasReferencePeriod()}`,
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
function hyrasTmaxMapHref(path){
  return path?`${HYRAS_DATA_BASE}/tmax/${path}`:"#";
}
async function hyrasTmaxForceMapDownload(event,path,filename){
  if(event)event.preventDefault();
  if(!path)return;

  const url=hyrasTmaxMapHref(path);
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
    anchor.download=filename||path.split("/").pop()||"hyras_tmax.png";
    anchor.style.display="none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(()=>URL.revokeObjectURL(objectUrl),2000);
  }catch(error){
    console.error("HYRAS Tmax Kartendownload:",error);
    window.open(url,"_blank","noopener,noreferrer");
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

  const mapsBase=hyrasTmaxMapDownloads?.periods?.[period.key]||{},maps={...mapsBase,anomaly:(window.HyrasTemperatureInteractive?HyrasTemperatureInteractive.mapForReference(mapsBase, hyrasReferencePeriod(),period.start_date,period.end_date):(hyrasReferencePeriod()==='1991-2020'?mapsBase.anomaly:null))};
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

  frame.innerHTML=`<div class="hyras-tmean-region-panel">
    ${maps.anomaly?`<div class="hyras-tmean-anomaly-preview">
      <div class="hyras-tmean-anomaly-preview-head">
        <div>
          <h4>2-m-Tmax-Abweichung</h4>
          <p>${period.label} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)} · Abweichung gegenüber ${hyrasReferenceDisplay()}</p>
        </div>
      </div>
      <a class="hyras-tmean-anomaly-preview-link" href="${hyrasTemperaturePreviewHref(hyrasTmaxMapHref(maps.anomaly),hyrasTmaxRegionsIndex?.data_through)}" target="_blank" rel="noopener">
        <img src="${hyrasTemperaturePreviewHref(hyrasTmaxMapHref(maps.anomaly),hyrasTmaxRegionsIndex?.data_through)}" alt="HYRAS 2-m-Tmax-Abweichung ${period.label} gegenüber ${hyrasReferenceDisplay()}" loading="eager">
      </a>
      <div class="hyras-temperature-raster-status" role="status">Rasterabfrage wird geladen …</div>
    </div>`:`<div class="hyras-tmean-anomaly-preview"><div class="hyras-tmean-anomaly-preview-empty">Für diesen Zeitraum ist keine fertige Tmax-Abweichungskarte verfügbar.</div><div class="hyras-temperature-raster-status" role="status">Rasterabfrage wird geladen …</div></div>`}
    <div class="hyras-tmean-region-head">
      <div>
        <h3>Tagesmaximum – ${region}</h3>
        <p>${period.label} · tägliches HYRAS-Tmax-Gebietsmittel gegen ${hyrasReferenceDisplay()}</p>
      </div>
    </div>
    <div class="hyras-tmean-chart-wrap">
      <canvas id="hyrasTmaxRegionCanvas"></canvas>
    </div>
    ${hyrasDailyAnomalyPanelHtml("tmax")}
    <div class="hyras-tmean-downloads">
      <a class="${absClass}" ${maps.absolute?`href="${hyrasTmaxMapHref(maps.absolute)}" data-tmax-map="${maps.absolute}" data-tmax-filename="hyras_tmax_${period.key}_temperatur.png"`:""}>Tmax-Karte herunterladen</a>
      <a class="${anomClass}" ${maps.anomaly?`href="${hyrasTmaxMapHref(maps.anomaly)}" data-tmax-map="${maps.anomaly}" data-tmax-filename="hyras_tmax_${period.key}_abweichung_${hyrasReferencePeriod().replace("-","_")}.png"`:""}>Abweichungskarte ${hyrasReferenceDisplay()} herunterladen</a>
      <a class="hyras-tmean-download" href="#" data-tmax-pdf="1">Kurve als PDF herunterladen</a>
    </div>
    <p class="hyras-tmean-region-note">
      ${maps.anomaly
        ?"Absolute Tmax- und Anomaliekarte stehen als fertige PNGs bereit."
        :"Für diesen laufenden Zeitraum ist die absolute Tmax-Karte verfügbar; eine Raster-Anomalie wird erst für vollständige Monate/Jahreszeiten angeboten."}
      Historische Tagesrekorde beziehen sich auf 1951–2025.
    </p>
  </div>`;

  window.HyrasTemperatureInteractive?.mount(frame.querySelector(".hyras-tmean-anomaly-preview"),{entry:mapsBase,parameter:"tmax",reference:hyrasReferencePeriod(),key:period.key,start:period.start_date,end:period.end_date,version:hyrasTmaxRegionsIndex?.data_through||"1",base:HYRAS_DATA_BASE,boundary:hyrasIndex?.interactive?.boundary_overlay_1km});
  frame.querySelectorAll("a[data-tmax-map]").forEach(link=>{
    link.addEventListener("click",event=>hyrasTmaxForceMapDownload(
      event,
      link.dataset.tmaxMap,
      link.dataset.tmaxFilename
    ));
  });
  frame.querySelector("a[data-tmax-pdf]")?.addEventListener(
    "click",
    event=>hyrasTmaxExportCurvePdf(event,region,period)
  );
  hyrasDailyAnomalyMount("tmax",rows);

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
            label:`Mittel ${hyrasReferenceDisplay()}`,
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
  const current=hyrasTemperatureRenderStart("tmax");
  try{
    await hyrasTmaxRegionsEnsureLoaded();
    if(!current())return;
    await hyrasTmaxEnsureClimateReference();
    if(!current())return;
    const region=hyrasTmaxRegionName();
    const period=hyrasTmaxCurvePeriod();
    if(!period)return;
    const rows=hyrasTmaxCurveRows(region,period);
    hyrasTmaxSetCurveKpis(region,period,rows);
    hyrasTmaxRenderCurveChart(region,period,rows);
  }catch(error){
    if(!current())return;
    console.error("HYRAS Tmax Gebietskurven:",error);
    const frame=document.getElementById("hyrasMapFrame");
    if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;
  }
}

async function renderHyrasTmean(){
  const current=hyrasTemperatureRenderStart("tmean");
  if(hyrasTmaxRegionChart){
    hyrasTmaxRegionChart.destroy();
    hyrasTmaxRegionChart=null;
  }
  try{
    await hyrasTmeanRegionsEnsureLoaded();if(!current())return;await hyrasTmeanEnsureClimateReference();if(!current())return;const region=hyrasTmeanRegionName(),period=hyrasTmeanCurvePeriod();if(!period)return;
    const rows=hyrasTmeanCurveRows(region,period);hyrasTmeanSetCurveKpis(region,period,rows);hyrasTmeanRenderCurveChart(region,period,rows);
  }catch(error){if(!current())return;console.error("HYRAS Tmean Gebietskurven:",error);const frame=document.getElementById("hyrasMapFrame");if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;}
}


async function hyrasSwitchParameter(){
  const temperatureParameter=hyrasParameter();
  const isTmean=temperatureParameter==="tmean";
  const isTmax=temperatureParameter==="tmax";
  // Clear the old raster immediately: otherwise slow Tmean/Tmax requests
  // leave a precipitation map on screen under a temperature selection.
  if(isTmean||isTmax){
    const frame=document.getElementById("hyrasMapFrame");
    if(frame)frame.innerHTML='<div class="hyras-loading">Temperaturdaten und Diagramm werden geladen …</div>';
  }
  const custom=document.getElementById("hyrasCustomApply")?.parentElement;
  const historical=document.getElementById("hyrasHistoricalApply")?.parentElement;
  const panel=document.getElementById("hyrasPointAnalysis");
  const metricGroup=document.getElementById("hyrasMetricSelect")?.closest(".control-group");
  const regionGroup=document.getElementById("hyrasTmeanRegionGroup");
  if(panel)panel.hidden=true;
  hyrasHistoricalState=null;hyrasCustomState=null;hyrasPresetState=null;hyrasLivePresetState=null;
  if(isTmean||isTmax){
    if(custom)custom.style.display="none";if(historical)historical.style.display="";if(metricGroup)metricGroup.style.display="none";if(regionGroup)regionGroup.hidden=false;
    const oldLink=document.getElementById("hyrasOpenImage");if(oldLink)oldLink.style.display="none";
    const status=document.getElementById("hyrasStatus");

    if(isTmean){
      if(status)status.textContent="HYRAS Tmean Gebietskurven werden geladen …";
      await hyrasTmeanRegionsEnsureLoaded();
      if(hyrasParameter()!=="tmean")return;
      hyrasTmeanPopulateRegions();
      hyrasTmeanPopulateCurvePeriods();
      if(status)status.textContent=`Tmean · Deutschland + 16 Bundesländer · Daten bis ${hyrasDate(hyrasTmeanRegionsIndex.data_through)} · Referenz ${hyrasReferenceDisplay()}`;
      await renderHyrasTmean();
    }else{
      if(status)status.textContent="HYRAS Tmax Gebietskurven werden geladen …";
      await hyrasTmaxRegionsEnsureLoaded();
      if(hyrasParameter()!=="tmax")return;
      hyrasTmaxPopulateRegions();
      hyrasTmaxPopulateCurvePeriods();
      if(status)status.textContent=`Tmax · Deutschland + 16 Bundesländer · Daten bis ${hyrasDate(hyrasTmaxRegionsIndex.data_through)} · Referenz ${hyrasReferenceDisplay()}`;
      await renderHyrasTmax();
    }
  }else{
    if(typeof hyrasTmeanResetExportLink==="function")hyrasTmeanResetExportLink();
    if(custom)custom.style.display="";if(historical)historical.style.display="";if(metricGroup)metricGroup.style.display="";if(regionGroup)regionGroup.hidden=true;
    hyrasRestorePrecipMetricOptions();populateHyrasPeriods();hyrasRestorePrecipHistoricalYears();
    const status=document.getElementById("hyrasStatus");if(status&&hyrasIndex)status.textContent=`Niederschlag · Daten bis ${hyrasDate(hyrasIndex.data_through)} · Historie ${hyrasIndex.historical_first_year}–${hyrasIndex.historical_last_year}`;
    renderHyras();
  }
}
function renderHyras(){
  if(hyrasParameter()==="tmean"){renderHyrasTmean();return;}
  if(hyrasParameter()==="tmax"){renderHyrasTmax();return;}
  if(!hyrasIndex)return;
  const special=document.getElementById("hyrasPeriodSelect")?.value;
  if(special==="__custom__"){if(hyrasCustomState)hyrasRenderCustomMap().catch(error=>console.error("HYRAS frei rendern:",error));return;}
  if(special==="__historical__"){if(hyrasHistoricalState)hyrasRenderHistoricalMap().catch(error=>console.error("HYRAS Historie rendern:",error));return;}
  const period=hyrasSelectedPeriod();if(!period)return;if(period.daily_live){hyrasRenderLiveDailyPreset(period).catch(error=>{console.error("HYRAS Live-Preset:",error);const frame=document.getElementById("hyrasMapFrame");if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;});return;}updateHyrasMetricAvailability(period);
  const stats=period.stats||{},metric=document.getElementById("hyrasMetricSelect")?.value||"percent",cfg=hyrasMetricConfig(metric),file=period.outputs?.[cfg.key];
  document.getElementById("hyrasPeriodStat").textContent=period.label||"–";document.getElementById("hyrasDataThrough").textContent=period.date_label||`${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`;document.getElementById("hyrasCurrentMean").textContent=hyrasNum(stats.current_mean_mm,"l/m²",1);document.getElementById("hyrasCurrentMeanDetail").textContent=`Rastermittel · ${period.date_label||"gewählter Zeitraum"}`;document.getElementById("hyrasReferenceMean").textContent=hyrasNum(stats.reference_mean_mm,"l/m²",1);document.getElementById("hyrasReferenceMeanDetail").textContent=period.reference_exact?"exakter gleicher Kalenderzeitraum 1991–2020":"für laufenden Teilmonat noch nicht berechnet";document.getElementById("hyrasPercentMean").textContent=hyrasNum(stats.percent_of_reference,"%",1);const anom=Number(stats.anomaly_mean_mm);document.getElementById("hyrasAnomalyMean").textContent=Number.isFinite(anom)?`${anom>=0?"+":""}${hyrasNum(anom,"l/m²",1)} zum Mittel`:"Abweichung nicht verfügbar";
  const note=document.getElementById("hyrasReferenceNote");if(note)note.textContent=period.reference_note||"Quelle: Deutscher Wetterdienst, HYRAS-DE-PR. 1-km-Raster. Mouseover zeigt die native Rasterzelle; Prozent und Abweichung basieren auf dem gleichen Kalenderzeitraum 1991–2020.";
  hyrasRenderPresetMap(period).catch(error=>{console.warn("Interaktive HYRAS-Presetkarte nicht verfügbar, PNG-Fallback:",error);hyrasRenderPresetFallback(period,cfg,file);});
}
async function ensureHyrasLoaded(force=false){
  if(hyrasLoading) return hyrasLoading;
  if(!force && hyrasIndex && Date.now()-hyrasLastFetch<5*60*1000){renderHyras();return;}
  const status=document.getElementById("hyrasStatus");
  if(status){status.className="hyras-status";status.textContent="HYRAS-Karten werden geprüft …";}
  hyrasLoading=(async()=>{
    try{
      hyrasIndex=await hyrasFetchJson("hyras_index.json");
      hyrasLastFetch=Date.now();
      populateHyrasPeriods();
      if(status){status.className="hyras-status";status.textContent=`${hyrasIndex.periods?.length||0} vordefinierte Zeiträume + freier Zeitraum · Referenz ${hyrasIndex.reference} · HYRAS-DE-PR ${hyrasIndex.resolution_km}-km-Raster · Daten bis ${hyrasDate(hyrasIndex.data_through)}`;}
      hyrasLoadWebManifest().catch(error=>console.warn("HYRAS-Webraster:",error));
      hyrasLoadHistoricalManifest().then(manifest=>{if(status)status.textContent=`${hyrasIndex.periods?.length||0} aktuelle Zeiträume + freier Zeitraum · Historie ${manifest.first_year}–${manifest.last_year} · Referenz ${hyrasIndex.reference} · Daten bis ${hyrasDate(hyrasIndex.data_through)}`;}).catch(error=>{console.warn("HYRAS-Historie:",error);const msg=document.getElementById("hyrasHistoricalMessage");if(msg){msg.className="hyras-custom-message error";msg.textContent="Historische Raster noch nicht veröffentlicht – HYRAS-Workflow einmal mit Version 15.3 ausführen.";}});
      renderHyras();
    }catch(error){
      console.error("HYRAS:",error);
      if(status){status.className="hyras-status error";status.textContent=`HYRAS-Karten noch nicht verfügbar: ${error.message}. Den Workflow „HYRAS Flächenkarten aktualisieren“ einmal starten.`;}
      const frame=document.getElementById("hyrasMapFrame");
      if(frame) frame.innerHTML='<div class="hyras-loading">Noch kein HYRAS-Kartendatensatz veröffentlicht.</div>';
    }finally{hyrasLoading=null;}
  })();
  return hyrasLoading;
}
function initHyrasControls(){
  document.getElementById("hyrasParameterSelect")?.addEventListener("change",()=>hyrasSwitchParameter());
  document.getElementById("hyrasTmeanRegionSelect")?.addEventListener("change",()=>renderHyras());
  document.getElementById("hyrasMetricSelect")?.addEventListener("change",()=>renderHyras());
  document.getElementById("hyrasReferenceSelect")?.addEventListener("change",()=>{hyrasPresetState=null;hyrasLivePresetState=null;hyrasHistoricalState=null;hyrasTmeanHistoricalState=null;hyrasTmeanRegionsClimateReference=null;hyrasTmaxRegionsClimateReference=null;hyrasTminRegionsClimateReference=null;hyrasDailyAnomalySelectedDate=null;hyrasRestorePrecipMetricOptions();const p=hyrasParameter();if(p==="precipitation"&&document.getElementById("hyrasPeriodSelect")?.value==="__historical__")hyrasApplyHistorical();else renderHyras();});
  document.getElementById("hyrasPeriodSelect")?.addEventListener("change",event=>{if(event.target.value!=="__custom__")hyrasCustomState=null;if(event.target.value!=="__historical__")hyrasHistoricalState=null;hyrasPresetState=null;hyrasLivePresetState=null;renderHyras();});
  document.getElementById("hyrasCustomApply")?.addEventListener("click",()=>hyrasApplyCustomRange());
  document.getElementById("hyrasHistoricalType")?.addEventListener("change",()=>hyrasHistoricalTypeControls());
  document.getElementById("hyrasHistoricalApply")?.addEventListener("click",()=>hyrasParameter()==="tmean"?hyrasTmeanApplyHistorical():hyrasApplyHistorical());
  hyrasHistoricalTypeControls();
}
initHyrasControls();

// HYRAS_TEMPERATURE_RANK_MAPS_V2
let hyrasRankManifest=null;
let hyrasRankManifestLoading=null;
let hyrasRankDates=[];
let hyrasRankDateIndex=-1;
let hyrasRankPlayTimer=null;
let hyrasRankPreloadActive=false;
let hyrasRankDownloadActive=false;
const hyrasRankPreloadedUrls=new Set();
const HYRAS_RANK_PLAY_DELAY=700;
const HYRAS_RANK_PRELOAD_CONCURRENCY=4;
const HYRAS_RANK_EXPORT_FRAME_MS=400;

function hyrasRankManifestUrl(){
  return `${HYRAS_DATA_BASE}/temperature_ranks/index.json?t=${Date.now()}`;
}
async function hyrasRankEnsureManifest(force=false){
  if(hyrasRankManifestLoading)return hyrasRankManifestLoading;
  if(hyrasRankManifest&&!force)return hyrasRankManifest;
  hyrasRankManifestLoading=fetch(hyrasRankManifestUrl(),{cache:"no-store"})
    .then(response=>{
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data=>{
      hyrasRankManifest=data;
      const dates=Array.isArray(data?.available_dates)
        ?data.available_dates.filter(value=>/^\d{4}-\d{2}-\d{2}$/.test(String(value))).sort()
        :[];
      const latest=String(data?.data_through||"");
      if(latest&&!dates.includes(latest))dates.push(latest);
      hyrasRankDates=[...new Set(dates)].sort();
      hyrasRankDateIndex=hyrasRankDates.length?hyrasRankDates.length-1:-1;
      hyrasRankUpdateTimelineControls();
      return data;
    })
    .catch(error=>{
      console.warn("HYRAS-Rangkarten-Manifest:",error);
      hyrasRankManifest=null;
      hyrasRankDates=[];
      hyrasRankDateIndex=-1;
      hyrasRankUpdateTimelineControls();
      return null;
    })
    .finally(()=>{hyrasRankManifestLoading=null;});
  return hyrasRankManifestLoading;
}
function hyrasRankSelectedDate(){
  return hyrasRankDateIndex>=0?hyrasRankDates[hyrasRankDateIndex]:"";
}
function hyrasRankDisplayDate(value){
  if(!value)return "aktueller Stand";
  const date=new Date(`${value}T00:00:00`);
  if(Number.isNaN(date.getTime()))return value;
  return date.toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
}
function hyrasRankStopPlay(){
  if(hyrasRankPlayTimer!==null){
    window.clearInterval(hyrasRankPlayTimer);
    hyrasRankPlayTimer=null;
  }
  const button=document.getElementById("hyrasRankPlay");
  if(button)button.textContent="▶ Abspielen";
}
function hyrasRankUpdateTimelineControls(){
  const slider=document.getElementById("hyrasRankSlider");
  const prev=document.getElementById("hyrasRankPrev");
  const next=document.getElementById("hyrasRankNext");
  const date=document.getElementById("hyrasRankTimelineDate");
  const length=hyrasRankDates.length;
  const index=length?Math.max(0,Math.min(hyrasRankDateIndex,length-1)):0;
  if(slider){
    slider.min="0";
    slider.max=String(Math.max(0,length-1));
    slider.value=String(index);
    slider.disabled=length<2;
  }
  if(prev)prev.disabled=length<2||index<=0;
  if(next)next.disabled=length<2||index>=length-1;
  if(date){
    date.textContent=length
      ?`${hyrasRankDisplayDate(hyrasRankDates[index])} · ${index+1}/${length}`
      :"aktueller Stand";
  }
}
function hyrasRankImageUrl(parameter,period){
  return `${HYRAS_DATA_BASE}/temperature_ranks/${parameter}/${period}_rank.png?t=${Date.now()}`;
}
function hyrasRankArchiveUrl(parameter,period,date){
  if(!date||!hyrasRankManifest?.archive_pattern)return hyrasRankImageUrl(parameter,period);
  return `${HYRAS_DATA_BASE}/temperature_ranks/archive/${date}/${parameter}/${period}_rank.png`;
}
function hyrasRankSetActionStatus(text,state=""){
  const status=document.getElementById("hyrasRankActionStatus");
  if(!status)return;
  status.textContent=text;
  status.className=`hyras-rank-action-status${state?` ${state}`:""}`;
}
function hyrasRankSetToolButtonsDisabled(disabled){
  for(const id of ["hyrasRankPreload","hyrasRankDownload"]){
    const button=document.getElementById(id);
    if(button)button.disabled=Boolean(disabled);
  }
}
function hyrasRankAnimationUrls(parameter){
  return hyrasRankDates.flatMap(date=>
    HYRAS_RANK_PERIODS.map(item=>hyrasRankArchiveUrl(parameter,item.key,date))
  );
}
async function hyrasRankWarmUrl(url){
  if(hyrasRankPreloadedUrls.has(url))return true;
  const response=await fetch(url,{cache:"force-cache",mode:"cors"});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  await response.blob();
  hyrasRankPreloadedUrls.add(url);
  return true;
}
async function hyrasRankRunPool(items,concurrency,worker,onProgress){
  let cursor=0;
  let done=0;
  let failed=0;
  async function runner(){
    while(true){
      const index=cursor++;
      if(index>=items.length)return;
      try{await worker(items[index],index);}
      catch(error){failed+=1;console.warn("HYRAS-Rangkarte:",items[index],error);}
      done+=1;
      onProgress?.(done,items.length,failed);
    }
  }
  const count=Math.min(Math.max(1,concurrency),Math.max(1,items.length));
  await Promise.all(Array.from({length:count},()=>runner()));
  return {done,failed};
}
async function hyrasRankPreloadAll(options={}){
  if(hyrasRankPreloadActive||hyrasRankDownloadActive)return false;
  const parameter=document.getElementById("hyrasRankParameterSelect")?.value||"tmean";
  const urls=hyrasRankAnimationUrls(parameter);
  if(!urls.length){
    hyrasRankSetActionStatus("Keine Animationstage verfügbar","error");
    return false;
  }
  hyrasRankPreloadActive=true;
  hyrasRankSetToolButtonsDisabled(true);
  const total=urls.length;
  const already=urls.filter(url=>hyrasRankPreloadedUrls.has(url)).length;
  if(!options.silent)hyrasRankSetActionStatus(
    already===total
      ?`${hyrasRankParameterLabel(parameter)} · ${total} Karten bereits vorgeladen`
      :`${hyrasRankParameterLabel(parameter)} · Vorladen 0/${total}`,
    already===total?"done":"busy"
  );
  let result={done:already,failed:0};
  try{
    const pending=urls.filter(url=>!hyrasRankPreloadedUrls.has(url));
    if(pending.length){
      const pool=await hyrasRankRunPool(
        pending,
        HYRAS_RANK_PRELOAD_CONCURRENCY,
        url=>hyrasRankWarmUrl(url),
        (done,pendingTotal,failed)=>{
          const overall=already+done;
          if(!options.silent)hyrasRankSetActionStatus(
            `${hyrasRankParameterLabel(parameter)} · Vorladen ${overall}/${total}${failed?` · ${failed} Fehler`:""}`,
            "busy"
          );
        }
      );
      result={done:already+pool.done,failed:pool.failed};
    }
    if(!options.silent){
      hyrasRankSetActionStatus(
        result.failed
          ?`${hyrasRankParameterLabel(parameter)} · ${result.done-result.failed}/${total} Karten vorgeladen · ${result.failed} Fehler`
          :`${hyrasRankParameterLabel(parameter)} · ${total} Karten vorgeladen`,
        result.failed?"error":"done"
      );
    }
    return result.failed===0;
  }finally{
    hyrasRankPreloadActive=false;
    hyrasRankSetToolButtonsDisabled(false);
  }
}
async function hyrasRankFetchDrawable(url){
  const response=await fetch(url,{cache:"force-cache",mode:"cors"});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const blob=await response.blob();
  hyrasRankPreloadedUrls.add(url);
  if(typeof createImageBitmap==="function"){
    const bitmap=await createImageBitmap(blob);
    return {image:bitmap,width:bitmap.width,height:bitmap.height,close:()=>bitmap.close?.()};
  }
  const objectUrl=URL.createObjectURL(blob);
  const image=await new Promise((resolve,reject)=>{
    const img=new Image();
    img.onload=()=>resolve(img);
    img.onerror=()=>reject(new Error("Bild konnte nicht dekodiert werden"));
    img.src=objectUrl;
  });
  return {image,width:image.naturalWidth,height:image.naturalHeight,close:()=>URL.revokeObjectURL(objectUrl)};
}
function hyrasRankDrawExportFrame(ctx,canvas,drawables,dateText,parameter,position,total){
  const width=canvas.width;
  const height=canvas.height;
  ctx.fillStyle="#ffffff";
  ctx.fillRect(0,0,width,height);
  ctx.fillStyle="#17232b";
  ctx.font="700 42px Arial, sans-serif";
  ctx.textAlign="left";
  ctx.fillText(`HYRAS Temperatur-Rangkarten · ${hyrasRankParameterLabel(parameter)}`,52,58);
  ctx.fillStyle="#53616a";
  ctx.font="26px Arial, sans-serif";
  ctx.fillText(`${hyrasRankDisplayDate(dateText)} · ${position}/${total} · Vergleich 1951–2026`,52,96);

  const labels=["Tagesrang","Monatsrang bis heute","Sommerrang bis heute"];
  const gap=24;
  const left=48;
  const top=142;
  const bottom=42;
  const colWidth=(width-left*2-gap*2)/3;
  const boxHeight=height-top-bottom;

  drawables.forEach((drawable,index)=>{
    const x=left+index*(colWidth+gap);
    ctx.fillStyle="#f6f8f9";
    ctx.fillRect(x,top,colWidth,boxHeight);
    ctx.strokeStyle="#d6dee3";
    ctx.lineWidth=2;
    ctx.strokeRect(x,top,colWidth,boxHeight);
    ctx.fillStyle="#24313a";
    ctx.font="700 24px Arial, sans-serif";
    ctx.textAlign="center";
    ctx.fillText(labels[index],x+colWidth/2,top+36);

    const pad=16;
    const areaX=x+pad;
    const areaY=top+54;
    const areaW=colWidth-pad*2;
    const areaH=boxHeight-70;
    const scale=Math.min(areaW/drawable.width,areaH/drawable.height);
    const drawW=drawable.width*scale;
    const drawH=drawable.height*scale;
    ctx.drawImage(
      drawable.image,
      areaX+(areaW-drawW)/2,
      areaY+(areaH-drawH)/2,
      drawW,
      drawH
    );
  });
}
function hyrasRankBestMp4Format(){
  if(typeof MediaRecorder==="undefined")return null;
  const candidates=[
    "video/mp4;codecs=avc1.42E01E",
    "video/mp4;codecs=avc1",
    "video/mp4"
  ];
  const mime=candidates.find(type=>
    typeof MediaRecorder.isTypeSupported!=="function"
      ?type==="video/mp4"
      :MediaRecorder.isTypeSupported(type)
  );
  return mime?{mime,extension:"mp4",label:"MP4"}:null;
}
async function hyrasRankDownloadAnimation(){
  if(hyrasRankDownloadActive||hyrasRankPreloadActive)return;
  if(hyrasRankDates.length<2){
    hyrasRankSetActionStatus("Zu wenige Animationstage für einen Download","error");
    return;
  }
  const format=hyrasRankBestMp4Format();
  const testCanvas=document.createElement("canvas");
  if(!format||typeof testCanvas.captureStream!=="function"){
    hyrasRankSetActionStatus("MP4-Export wird von diesem Browser nicht unterstützt","error");
    return;
  }

  const parameter=document.getElementById("hyrasRankParameterSelect")?.value||"tmean";
  const first=hyrasRankDates[0];
  const last=hyrasRankDates[hyrasRankDates.length-1];
  const fileName=`hyras-rangkarten_${parameter}_${first}_bis_${last}.mp4`;
  let saveHandle=null;

  if(typeof window.showSaveFilePicker==="function"){
    try{
      saveHandle=await window.showSaveFilePicker({
        id:"hyras-rank-animation",
        suggestedName:fileName,
        startIn:"downloads",
        types:[{
          description:"MP4-Video",
          accept:{"video/mp4":[".mp4"]}
        }]
      });
    }catch(error){
      if(error?.name==="AbortError"){
        hyrasRankSetActionStatus("Download abgebrochen");
        return;
      }
      console.warn("Speichern-unter-Dialog nicht verfügbar:",error);
    }
  }

  hyrasRankStopPlay();
  hyrasRankDownloadActive=true;
  hyrasRankSetToolButtonsDisabled(true);
  hyrasRankSetActionStatus(`${hyrasRankParameterLabel(parameter)} · MP4 wird vorbereitet …`,"busy");

  const canvas=document.createElement("canvas");
  canvas.width=1920;
  canvas.height=1080;
  const ctx=canvas.getContext("2d",{alpha:false});
  if(!ctx){
    hyrasRankDownloadActive=false;
    hyrasRankSetToolButtonsDisabled(false);
    hyrasRankSetActionStatus("MP4-Canvas konnte nicht erstellt werden","error");
    return;
  }

  const stream=canvas.captureStream(25);
  const chunks=[];
  let recorder;
  try{
    recorder=new MediaRecorder(stream,{mimeType:format.mime,videoBitsPerSecond:6000000});
  }catch(error){
    stream.getTracks().forEach(track=>track.stop());
    hyrasRankDownloadActive=false;
    hyrasRankSetToolButtonsDisabled(false);
    hyrasRankSetActionStatus("MP4-Encoder konnte nicht gestartet werden","error");
    return;
  }

  recorder.ondataavailable=event=>{if(event.data?.size)chunks.push(event.data);};
  const stopped=new Promise(resolve=>recorder.addEventListener("stop",resolve,{once:true}));
  recorder.start(1000);

  let failed=false;
  try{
    for(let index=0;index<hyrasRankDates.length;index++){
      const date=hyrasRankDates[index];
      hyrasRankSetActionStatus(
        `${hyrasRankParameterLabel(parameter)} · MP4 ${index+1}/${hyrasRankDates.length} · ${hyrasRankDisplayDate(date)}`,
        "busy"
      );
      const urls=HYRAS_RANK_PERIODS.map(item=>hyrasRankArchiveUrl(parameter,item.key,date));
      const drawables=await Promise.all(urls.map(url=>hyrasRankFetchDrawable(url)));
      try{
        hyrasRankDrawExportFrame(
          ctx,canvas,drawables,date,parameter,index+1,hyrasRankDates.length
        );
        await new Promise(resolve=>window.setTimeout(resolve,HYRAS_RANK_EXPORT_FRAME_MS));
      }finally{
        drawables.forEach(item=>item.close?.());
      }
    }
    await new Promise(resolve=>window.setTimeout(resolve,700));
  }catch(error){
    failed=true;
    console.error("HYRAS-Animationsdownload:",error);
    hyrasRankSetActionStatus(`MP4-Export abgebrochen: ${error.message}`,"error");
  }finally{
    if(recorder.state!=="inactive")recorder.stop();
    await stopped;
    stream.getTracks().forEach(track=>track.stop());
  }

  if(!failed&&chunks.length){
    const actualMime=recorder.mimeType||format.mime||"video/mp4";
    const blob=new Blob(chunks,{type:actualMime});
    try{
      if(saveHandle){
        const writable=await saveHandle.createWritable();
        await writable.write(blob);
        await writable.close();
      }else{
        const url=URL.createObjectURL(blob);
        const link=document.createElement("a");
        link.href=url;
        link.download=fileName;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(()=>URL.revokeObjectURL(url),15000);
      }
      hyrasRankSetActionStatus(
        `${hyrasRankParameterLabel(parameter)} · MP4 mit ${hyrasRankDates.length} Tagen gespeichert`,
        "done"
      );
    }catch(error){
      console.error("HYRAS-MP4 speichern:",error);
      hyrasRankSetActionStatus(`MP4 konnte nicht gespeichert werden: ${error.message}`,"error");
    }
  }else if(!failed){
    hyrasRankSetActionStatus("MP4-Export lieferte keine Daten","error");
  }

  hyrasRankDownloadActive=false;
  hyrasRankSetToolButtonsDisabled(false);
}
function hyrasRankParameterLabel(parameter){
  return ({tmean:"Tmean",tmax:"Tmax",tmin:"Tmin"})[parameter]||parameter;
}
function hyrasRankRender(parameter){
  const select=document.getElementById("hyrasRankParameterSelect");
  const chosen=["tmean","tmax","tmin"].includes(parameter)?parameter:(select?.value||"tmean");
  if(select&&select.value!==chosen)select.value=chosen;
  const status=document.getElementById("hyrasRankStatus");
  const token=++hyrasRankRenderToken;
  const selectedDate=hyrasRankSelectedDate();
  let pending=HYRAS_RANK_PERIODS.length;
  let loaded=0;
  let failed=0;
  if(status){
    status.className="hyras-rank-status";
    status.textContent=`${hyrasRankParameterLabel(chosen)} · ${selectedDate?hyrasRankDisplayDate(selectedDate):"aktueller Stand"} · drei Rangkarten werden geladen …`;
  }
  HYRAS_RANK_PERIODS.forEach(item=>{
    const img=document.getElementById(item.imageId);
    const placeholder=document.getElementById(item.placeholderId);
    const open=document.getElementById(item.openId);
    if(!img||!placeholder||!open)return;
    const url=hyrasRankArchiveUrl(chosen,item.key,selectedDate);
    img.hidden=true;
    img.removeAttribute("src");
    placeholder.hidden=false;
    placeholder.className="hyras-rank-placeholder";
    placeholder.textContent="Rangkarte wird geladen …";
    open.classList.add("disabled");
    open.href="#";
    img.onload=()=>{
      if(token!==hyrasRankRenderToken)return;
      loaded+=1;
      pending-=1;
      img.hidden=false;
      placeholder.hidden=true;
      open.href=url;
      open.classList.remove("disabled");
      if(status&&pending===0){
        status.className="hyras-rank-status";
        const when=selectedDate?hyrasRankDisplayDate(selectedDate):"aktueller Stand";
        status.textContent=failed
          ?`${hyrasRankParameterLabel(chosen)} · ${when} · ${loaded}/3 Rangkarten verfügbar`
          :`${hyrasRankParameterLabel(chosen)} · ${when} · Tages-, Monats- und Sommerrang`;
      }
    };
    img.onerror=()=>{
      if(token!==hyrasRankRenderToken)return;
      failed+=1;
      pending-=1;
      img.hidden=true;
      placeholder.hidden=false;
      placeholder.className="hyras-rank-placeholder error";
      placeholder.textContent="Für diesen Kartenstand ist die Rangkarte noch nicht verfügbar.";
      if(status&&pending===0){
        status.className="hyras-rank-status";
        status.textContent=`${hyrasRankParameterLabel(chosen)} · ${loaded}/3 Rangkarten verfügbar`;
      }
    };
    img.src=url;
  });
  hyrasRankUpdateTimelineControls();
}
function hyrasRankSetDateIndex(index){
  if(!hyrasRankDates.length)return;
  hyrasRankDateIndex=Math.max(0,Math.min(Number(index)||0,hyrasRankDates.length-1));
  hyrasRankUpdateTimelineControls();
  hyrasRankRender(document.getElementById("hyrasRankParameterSelect")?.value||"tmean");
}
function hyrasRankStep(delta){
  hyrasRankStopPlay();
  hyrasRankSetDateIndex(hyrasRankDateIndex+Number(delta||0));
}
function hyrasRankSliderInput(value){
  hyrasRankStopPlay();
  hyrasRankSetDateIndex(Number(value));
}
function hyrasRankTogglePlay(){
  if(hyrasRankDates.length<2)return;
  if(hyrasRankPlayTimer!==null){
    hyrasRankStopPlay();
    return;
  }
  if(hyrasRankDateIndex>=hyrasRankDates.length-1){
    hyrasRankDateIndex=0;
    hyrasRankRender(document.getElementById("hyrasRankParameterSelect")?.value||"tmean");
  }
  const button=document.getElementById("hyrasRankPlay");
  if(button)button.textContent="⏸ Pause";
  hyrasRankPlayTimer=window.setInterval(()=>{
    if(hyrasRankDateIndex>=hyrasRankDates.length-1){
      hyrasRankStopPlay();
      return;
    }
    hyrasRankDateIndex++;
    hyrasRankRender(document.getElementById("hyrasRankParameterSelect")?.value||"tmean");
  },HYRAS_RANK_PLAY_DELAY);
}
function hyrasSyncRankFromMain(){
  const parameter=document.getElementById("hyrasParameterSelect")?.value;
  if(["tmean","tmax","tmin"].includes(parameter))hyrasRankRender(parameter);
}
async function initHyrasTemperatureRanks(){
  const select=document.getElementById("hyrasRankParameterSelect");
  select?.addEventListener("change",()=>{hyrasRankStopPlay();hyrasRankSetActionStatus("Bereit");hyrasRankRender(select.value);});
  document.getElementById("hyrasParameterSelect")?.addEventListener("change",()=>window.setTimeout(hyrasSyncRankFromMain,0));
  await hyrasRankEnsureManifest();
  hyrasRankRender(select?.value||"tmean");
}
initHyrasTemperatureRanks();

