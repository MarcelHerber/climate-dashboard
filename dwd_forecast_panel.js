(()=>{"use strict";
const ROOT="data/synoptic_charts/";
const SOURCE="https://opendata.dwd.de/weather/charts/forecasts/icon/global/na/";
const stamp=x=>{const d=new Date(x);return Number.isFinite(d.getTime())?
new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(d)+" UTC":"–"};
const make=(tag,cls,txt)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(txt!==undefined)el.textContent=txt;return el};
const safe=x=>x&&x.source_id==="dwd_icon_hptfg_na"&&x.kind==="Prognoseblatt"&&
x.multiple_valid_times===true&&x.has_single_valid_utc===false&&!("valid_utc" in x)&&
Number.isInteger(x.forecast_from_hours)&&Number.isInteger(x.forecast_to_hours)&&
0<=x.forecast_from_hours&&x.forecast_from_hours<x.forecast_to_hours&&x.forecast_to_hours<=168&&
typeof x.image==="string"&&/^images\/dwd_icon_na_[0-9]{3}_[0-9]{3}_[0-9]{8}_[0-9]{6}\.webp$/.test(x.image)&&
typeof x.source_url==="string"&&x.source_url.startsWith(SOURCE)&&
Number.isFinite(Date.parse(x.generated_utc));
for(const root of document.querySelectorAll("[data-dwd-forecast]")){
 const grid=root.querySelector(".df-grid"),status=root.querySelector(".df-status");
 const range=root.querySelector(".df-range"),reload=root.querySelector(".df-reload");
 let sheets=[];
 const label=s=>"+"+s.forecast_from_hours+" bis +"+s.forecast_to_hours+" h";
 function render(){
  grid.replaceChildren();
  const filtered=range.value==="all"?sheets:sheets.filter(s=>String(s.forecast_from_hours)+"-"+String(s.forecast_to_hours)===range.value);
  if(!filtered.length){grid.append(make("p","sg-empty","Für diesen Prognosezeitraum liegt noch kein überprüftes DWD-Originalblatt vor."));return}
  for(const s of filtered){
   const card=make("article","sg-card");
   const head=make("div","sg-card-head");
   head.append(make("strong","sg-name","DWD ICON · "+label(s)),make("span","sg-kind","Mehrere Prognosezeiten"));
   const a=make("a","sg-image-link");a.href=ROOT+s.image;a.target="_blank";a.rel="noopener noreferrer";
   const img=make("img","sg-image");img.loading="lazy";img.decoding="async";img.src=ROOT+s.image;
   img.alt="DWD-Nordatlantik, Bodendruck/Wetter/Fronten, Prognoseblatt "+label(s);
   img.addEventListener("error",()=>{img.remove();a.append(make("p","sg-image-fallback","Originalblatt nicht ladbar. Bitte die Quelle beim DWD öffnen."));});
   a.append(img);
   const info=make("div","sg-card-details");
   info.append(make("div","sg-time","Vorhersagebereich: "+label(s)),
      make("div","sg-small","DWD-Datei erzeugt: "+stamp(s.generated_utc)),
      make("div","sg-small","Das Kartenblatt enthält mehrere Gültigkeitszeiten. Genaue Uhrzeiten stehen im Originalbild."),
      make("div","sg-credit","Quelle: Deutscher Wetterdienst (DWD) · ICON Nordatlantik"));
   const links=make("div","sg-links"),orig=make("a","","DWD-Original ↗");orig.href=s.source_url;orig.target="_blank";orig.rel="noopener noreferrer";
   const full=make("a","","Großansicht ↗");full.href=ROOT+s.image;full.target="_blank";full.rel="noopener noreferrer";
   links.append(orig,full);info.append(links);card.append(head,a,info);grid.append(card);
  }
 }
 async function load(){
  status.textContent="Lade DWD ICON-Prognoseblätter …";reload.disabled=true;
  try{
   const response=await fetch(ROOT+"dwd_forecasts.json?v="+Date.now(),{cache:"no-store"});
   if(!response.ok)throw Error("Noch kein veröffentlichtes Prognosearchiv (HTTP "+response.status+")");
   const data=await response.json();
   if(data.schema_version!==1||!Array.isArray(data.sheets)||data.sheet_count!==data.sheets.length)throw Error("Unvollständiger DWD-Kartenindex");
   sheets=data.sheets.filter(safe).sort((a,b)=>a.forecast_from_hours-b.forecast_from_hours||a.forecast_to_hours-b.forecast_to_hours);
   if(!sheets.length)throw Error("Noch keine geprüften Prognoseblätter verfügbar");
   const previous=range.value;range.replaceChildren();
   range.add(new Option("Alle verfügbaren Prognosebereiche","all"));
   for(const sheet of sheets)range.add(new Option(label(sheet),sheet.forecast_from_hours+"-"+sheet.forecast_to_hours));
   if([...range.options].some(x=>x.value===previous))range.value=previous;
   const age=Date.now()-Date.parse(data.generated_utc);
   status.textContent=sheets.length+" DWD-Originalblätter · bis +"+data.max_forecast_hours+" h · Verzeichnisstand "+stamp(data.generated_utc)+
    (age>16*3600000?" · Achtung: Datenstand älter als 16 Stunden":"")+
    " · keine einzelne gültige UTC-Zeit pro Kartenblatt.";
   render();
  }catch(error){
   sheets=[];grid.replaceChildren();
   status.textContent="DWD-Prognosebilder derzeit nicht automatisch verfügbar: "+error.message+". Die Originalkarten kannst du direkt beim DWD öffnen.";
   const a=make("a","","DWD ICON-Prognosekarten öffnen ↗");a.href=SOURCE;a.target="_blank";a.rel="noopener noreferrer";grid.append(a);
  }finally{reload.disabled=false}
 }
 range.addEventListener("change",render);
 reload.addEventListener("click",load);
 load();
}
})();