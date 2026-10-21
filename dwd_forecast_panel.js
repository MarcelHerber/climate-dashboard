(()=>{"use strict";
const ROOT="data/synoptic_charts/";
const SOURCE="https://opendata.dwd.de/weather/charts/forecasts/icon/global/na/";
const HOUR=3600000,STEP=6*HOUR;
const stamp=x=>{const d=new Date(x);return Number.isFinite(d.getTime())?
 new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(d)+" UTC":"–"};
const make=(tag,cls,txt)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(txt!==undefined)el.textContent=txt;return el};
const fmtTime=t=>new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",weekday:"long",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(t))+" UTC";
const slotLabel=t=>{
 const d=new Date(t),now=new Date();
 const utcMidnight=x=>Date.UTC(x.getUTCFullYear(),x.getUTCMonth(),x.getUTCDate());
 const days=(utcMidnight(d)-utcMidnight(now))/86400000;
 const relative=days===0?"Heute":days===1?"Morgen":days===2?"Übermorgen":null;
 return (relative||new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",weekday:"long"}).format(d))+
   ", "+new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit"}).format(d)+
   " · "+String(d.getUTCHours()).padStart(2,"0")+" UTC";
};
const safe=x=>x&&x.source_id==="dwd_icon_hptfg_na"&&x.kind==="Prognoseblatt"&&
 x.multiple_valid_times===true&&x.has_single_valid_utc===false&&!("valid_utc" in x)&&
 Number.isInteger(x.forecast_from_hours)&&Number.isInteger(x.forecast_to_hours)&&
 0<=x.forecast_from_hours&&x.forecast_from_hours<x.forecast_to_hours&&x.forecast_to_hours<=168&&
 typeof x.image==="string"&&/^images\/dwd_icon_na_[0-9]{3}_[0-9]{3}_[0-9]{8}_[0-9]{6}\.webp$/.test(x.image)&&
 typeof x.source_url==="string"&&x.source_url.startsWith(SOURCE)&&
 Number.isFinite(Date.parse(x.generated_utc));
/* Old manifests may predate the run_utc field. The DWD filename encodes the
   actual ICON initialization as YYYYMMDDHHMM. Never infer it from upload time. */
const extractRun=x=>{
 if(typeof x.run_utc==="string"&&Number.isFinite(Date.parse(x.run_utc)))return Date.parse(x.run_utc);
 const decoded=decodeURIComponent(x.source_url||"");
 const match=decoded.match(/_([0-9]{12})_WV[0-9]+\.png$/i);
 if(!match)return NaN;
 const digits=match[1];
 const iso=digits.slice(0,4)+"-"+digits.slice(4,6)+"-"+digits.slice(6,8)+"T"+digits.slice(8,10)+":"+digits.slice(10,12)+":00Z";
 const when=Date.parse(iso);
 return Number.isFinite(when)&&new Date(when).toISOString().slice(0,16)===iso.slice(0,16)?when:NaN;
};
const leadRange=s=>"+"+s.forecast_from_hours+" bis +"+s.forecast_to_hours+" h";
function chooseCycle(raw){
 const runs=new Map();
 for(const s of raw){const r=extractRun(s);if(!Number.isFinite(r))continue;
  if(!runs.has(r))runs.set(r,[]);
  runs.get(r).push(s);
 }
 const cycles=[...runs.entries()];
 if(!cycles.length)return null;
 const complete=cycles.filter(([,ss])=>ss.some(s=>s.forecast_to_hours===168));
 const selected=(complete.length?complete:cycles).sort((a,b)=>b[0]-a[0])[0];
 const latest=new Map();
 for(const s of selected[1]){const key=s.forecast_from_hours+"-"+s.forecast_to_hours;
  if(!latest.has(key)||Date.parse(s.generated_utc)>Date.parse(latest.get(key).generated_utc))latest.set(key,s);
 }
 return {run:selected[0],sheets:[...latest.values()].sort((a,b)=>a.forecast_from_hours-b.forecast_from_hours||a.forecast_to_hours-b.forecast_to_hours)};
}
function slotsFor(run,sheets,mode,now){
 const max=Math.max(...sheets.map(s=>s.forecast_to_hours));
 const horizon=run+Math.min(max,168)*HOUR;
 const start=Math.ceil(Math.max(now,run)/STEP)*STEP;
 const slots=[];
 for(let t=start;t<=horizon;t+=STEP){
  if(mode==="daily"&&new Date(t).getUTCHours()!==12)continue;
  const lead=Math.round((t-run)/HOUR);
  const match=sheets.filter(s=>s.forecast_from_hours<=lead&&lead<=s.forecast_to_hours)
     .sort((a,b)=>(a.forecast_to_hours-a.forecast_from_hours)-(b.forecast_to_hours-b.forecast_from_hours)||
       b.forecast_from_hours-a.forecast_from_hours||Date.parse(b.generated_utc)-Date.parse(a.generated_utc))[0];
  slots.push({time:t,lead,sheet:match||null});
 }
 return slots;
}
for(const root of document.querySelectorAll("[data-dwd-forecast]")){
 const grid=root.querySelector(".df-grid"),status=root.querySelector(".df-status");
 const mode=root.querySelector(".df-mode"),target=root.querySelector(".df-target"),reload=root.querySelector(".df-reload");
 if(!grid||!status||!mode||!target||!reload)continue;
 let cycle=null,generated=null;
 function fillTargets(slots){
  const selected=target.value;
  target.replaceChildren(new Option("Alle verfügbaren Zielzeiten","all"));
  for(const slot of slots)target.add(new Option(slotLabel(slot.time),String(slot.time)));
  if([...target.options].some(o=>o.value===selected))target.value=selected;
  else target.value="all";
  target.disabled=mode.value==="sheets";
 }
 function cardFor(sheet,title,subtitle,detail){
  const card=make("article","sg-card df-card");
  const head=make("div","sg-card-head");
  head.append(make("strong","sg-name",title),make("span","sg-kind",subtitle));
  const a=make("a","sg-image-link");a.href=ROOT+sheet.image;a.target="_blank";a.rel="noopener noreferrer";
  const img=make("img","sg-image");img.loading="lazy";img.decoding="async";img.src=ROOT+sheet.image;
  img.alt="DWD ICON Nordatlantik · Original-Prognoseblatt "+leadRange(sheet)+". "+title;
  img.addEventListener("error",()=>{img.remove();a.append(make("p","sg-image-fallback","Originalkarte konnte nicht geladen werden. DWD-Quelle öffnen."));});
  a.append(img);
  const info=make("div","sg-card-details");
  info.append(make("div","sg-time",detail),
    make("div","sg-small","ICON-Modelllauf: "+stamp(cycle.run)),
    make("div","sg-small","Originalblatt: "+leadRange(sheet)+"; Dateierzeugung: "+stamp(sheet.generated_utc)),
    make("div","sg-credit","Quelle: Deutscher Wetterdienst (DWD) · ICON Nordatlantik"));
  const caution=make("p","df-caution","Wichtig: Dieses Originalblatt enthält mehrere Termine. Die Zuordnung erfolgt nach dem DWD-Stundenbereich; der ausgewählte 6h-Termin ist kein separat geprüftes Einzelbild. Einzelzeiten bitte im Blatt ablesen.");
  info.append(caution);
  const links=make("div","sg-links");
  const orig=make("a","","Beim DWD öffnen ↗");orig.href=sheet.source_url;orig.target="_blank";orig.rel="noopener noreferrer";
  const full=make("a","","Großansicht ↗");full.href=ROOT+sheet.image;full.target="_blank";full.rel="noopener noreferrer";
  links.append(orig,full);info.append(links);card.append(head,a,info);
  return card;
 }
 function render(){
  grid.replaceChildren();if(!cycle)return;
  const m=mode.value;
  const slots=m==="sheets"?[]:slotsFor(cycle.run,cycle.sheets,m,Date.now());
  fillTargets(slots);
  const max=Math.max(...cycle.sheets.map(s=>s.forecast_to_hours));
  const outdated=Date.now()-Date.parse(generated)>16*HOUR;
  if(m==="sheets"){
   for(const sheet of cycle.sheets)grid.append(cardFor(sheet,"DWD · "+leadRange(sheet),"Originalblatt","Mehrere Prognosetermine in einem Originalbild"));
   status.textContent=cycle.sheets.length+" Prognoseblätter · ICON-Lauf "+stamp(cycle.run)+
     " · bis +"+max+" h · "+(outdated?"Datenstand veraltet":"Datenstand "+stamp(generated));
   return;
  }
  const showing=target.value==="all"?slots:slots.filter(x=>String(x.time)===target.value);
  for(const slot of showing){
   if(!slot.sheet){
    const item=make("article","sg-card df-card");
    item.append(make("strong","sg-name",slotLabel(slot.time)),
      make("p","sg-empty","Kein geprüftes Originalblatt für diesen Stundenbereich verfügbar."));
    grid.append(item);continue;
   }
   grid.append(cardFor(slot.sheet,slotLabel(slot.time), "Zielzeit · +"+slot.lead+" h",
     "Gewünschter Termin: "+fmtTime(slot.time)+" · Zeitbereich des Blatts: "+leadRange(slot.sheet)));
  }
  if(!showing.length)grid.append(make("p","sg-empty","Für den gewählten ICON-Lauf liegen ab jetzt keine zukünftigen UTC-Zeiten in dieser Ansicht vor."));
  status.textContent=slots.length+" "+(m==="daily"?"tägliche 12-UTC-Zielzeiten":"Zielzeiten in 6-Stunden-Schritten")+
    " · ICON-Lauf "+stamp(cycle.run)+" · bis +"+max+" h · "+
    (outdated?"Achtung: Datenstand älter als 16 Stunden":"Datenstand "+stamp(generated))+
    " · Anzeige passender mehrteiliger DWD-Originalblätter, keine Einzelkarten je UTC.";
 }
 async function load(){
  status.textContent="Lade ICON-Prognosen …";reload.disabled=true;
  try{
   const response=await fetch(ROOT+"dwd_forecasts.json?v="+Date.now(),{cache:"no-store"});
   if(!response.ok)throw Error("DWD-Datenindex fehlt (HTTP "+response.status+")");
   const data=await response.json();
   if(data.schema_version!==1||!Array.isArray(data.sheets)||data.sheet_count!==data.sheets.length)
     throw Error("Ungültiger DWD-Datenindex");
   const chosen=chooseCycle(data.sheets.filter(safe));
   if(!chosen||!chosen.sheets.length)throw Error("Noch keine verifizierten ICON-Prognoseblätter mit Modelllaufzeit");
   cycle=chosen;generated=data.generated_utc;render();
  }catch(error){
   cycle=null;grid.replaceChildren();
   status.textContent="DWD-Prognosebilder aktuell nicht verfügbar: "+error.message;
   const a=make("a","","DWD-Originalverzeichnis öffnen ↗");a.href=SOURCE;a.target="_blank";a.rel="noopener noreferrer";
   grid.append(a);
  }finally{reload.disabled=false}
 }
 mode.addEventListener("change",()=>{target.value="all";render()});
 target.addEventListener("change",render);
 reload.addEventListener("click",load);
 load();
}
})();