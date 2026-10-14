let era5SynopticIndex=null;
let era5SynopticBusy=null;
const era5SynopticCache=new Map();

async function era5SynopticFetchJSON(path){
  const response=await fetch(path+"?v="+Date.now(),{cache:"no-store"});
  if(!response.ok)throw new Error("ERA5-Archiv HTTP "+response.status);
  return response.json();
}

async function era5SynopticDiscover(){
  try{
    const idx=await era5SynopticFetchJSON("era5_europe/synoptic/index.json");
    era5SynopticIndex=idx;
    const hasData=(idx.days?.length||0)+(idx.monthly_events?.length||0)>0;
    const link=document.getElementById("era5SynopticNav");
    if(link)link.hidden=!hasData;
    return idx;
  }catch(error){
    console.info("ERA5-Synoptikarchiv noch nicht veröffentlicht",error);
    return null;
  }
}

function era5SynopticFill(){
  const mode=document.getElementById("era5SynopticMode")?.value||"daily";
  const dates=mode==="daily"?(era5SynopticIndex?.days||[]):(era5SynopticIndex?.monthly_events||[]);
  const dateSelect=document.getElementById("era5SynopticDate");
  if(!dateSelect)return;
  const previous=dateSelect.value;
  dateSelect.replaceChildren();
  [...dates].sort().reverse().forEach(v=>{
    const opt=document.createElement("option");opt.value=v;
    if(mode==="daily")opt.textContent=new Intl.DateTimeFormat("de-DE",{day:"numeric",month:"long",year:"numeric",timeZone:"UTC"}).format(new Date(v+"T12:00:00Z"));
    else opt.textContent=new Intl.DateTimeFormat("de-DE",{month:"long",year:"numeric",timeZone:"UTC"}).format(new Date(v+"-15T12:00:00Z"));
    dateSelect.appendChild(opt);
  });
  if(dates.includes(previous))dateSelect.value=previous;
  const row=document.getElementById("era5SynopticDateControl");
  if(row)row.hidden=!dates.length;
}

async function era5SynopticRender(){
  const mode=document.getElementById("era5SynopticMode")?.value||"daily";
  const date=document.getElementById("era5SynopticDate")?.value;
  const status=document.getElementById("era5SynopticStatus");
  const key=document.getElementById("era5SynopticParameter")?.value;
  const image=document.getElementById("era5SynopticImage");
  const title=document.getElementById("era5SynopticTitle");
  const note=document.getElementById("era5SynopticNote");
  const download=document.getElementById("era5SynopticDownload");
  if(!date){
    if(status)status.textContent="Für diesen Bereich sind noch keine geprüften ERA5-Karten verfügbar.";
    if(image)image.hidden=true;
    if(download)download.hidden=true;
    return;
  }
  try{
    if(status)status.textContent="ERA5-Synoptik wird geladen …";
    const path=mode==="daily"?`era5_europe/synoptic/days/${date}.json`:`era5_europe/synoptic/months/${date}.json`;
    let entry=era5SynopticCache.get(path);
    if(!entry){entry=await era5SynopticFetchJSON(path);era5SynopticCache.set(path,entry);}
    if(!entry.ready)throw new Error("Analyse nicht geprüft");
    const select=document.getElementById("era5SynopticParameter");
    if(select){
      const prior=select.value;
      select.replaceChildren();
      Object.entries(entry.products||{}).forEach(([k,p])=>{
        const opt=document.createElement("option");opt.value=k;
        opt.textContent=p.label||k;select.appendChild(opt);
      });
      if([...select.options].some(o=>o.value===prior))select.value=prior;
    }
    const chosen=entry.products?.[select?.value]||entry.products?.[key]||Object.values(entry.products||{})[0];
    if(!chosen?.file)throw new Error("Für diese Auswahl fehlt eine verifizierte Karte");
    if(image){
      image.hidden=false;
      image.onerror=()=>{image.hidden=true;if(status)status.textContent="Kartenbild konnte nicht geladen werden."};
      image.src=chosen.file;
      image.alt=(chosen.label||"ERA5-Karte")+" "+date;
    }
    if(title)title.textContent=chosen.label||"ERA5 Synoptik";
    if(download){download.hidden=false;download.href=chosen.file;}
    if(note)note.textContent=mode==="daily"?
      "12:00 UTC · ERA5-Stundenanalyse · 0,5° · kein Tages- oder Monatsmittel":
      "Ereignishäufigkeit aus allen "+entry.hours+" geprüften Stunden · 0,5° · keine Monatsmittel-Proxys";
    if(status)status.textContent=mode==="daily"?"ERA5-Reanalyse "+date+" · 12:00 UTC":
      "Vollständige stündliche Ereignisstatistik "+date;
  }catch(error){
    if(status)status.textContent="ERA5-Synoptik konnte nicht geladen werden: "+error.message;
    if(image)image.hidden=true;
    if(download)download.hidden=true;
  }
}

function era5SynopticChangeMode(){
  era5SynopticFill();
  era5SynopticRender();
}

async function ensureEra5SynopticLoaded(){
  if(era5SynopticBusy)return era5SynopticBusy;
  era5SynopticBusy=(async()=>{
    const idx=await era5SynopticDiscover();
    if(!idx)return;
    era5SynopticFill();
    const mode=document.getElementById("era5SynopticMode");
    if(mode&&!mode.dataset.bound){
      mode.addEventListener("change",era5SynopticChangeMode);mode.dataset.bound="1";
      document.getElementById("era5SynopticDate")?.addEventListener("change",era5SynopticRender);
      document.getElementById("era5SynopticParameter")?.addEventListener("change",era5SynopticRender);
    }
    await era5SynopticRender();
  })().finally(()=>{era5SynopticBusy=null;});
  return era5SynopticBusy;
}

document.addEventListener("DOMContentLoaded",()=>{era5SynopticDiscover();});
