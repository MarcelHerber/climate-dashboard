(()=>{"use strict";
const ROOT="data/synoptic_charts/";
const DWD="https://www.dwd.de/DWD/wetter/wv_spez/hobbymet/wetterkarten/";
const LEADS=[36,48,60,84,108];
const displayTime=x=>{const d=new Date(x);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(d)+" UTC":"–"};
const el=(tag,cls,t)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(t!==undefined)x.textContent=t;return x};
const origin=lead=>DWD+"ico_tkboden_na_"+String(lead).padStart(3,"0")+".png";
const safe=m=>m&&m.source_id==="dwd_tkb_original"&&LEADS.includes(m.lead_hours)&&
 m.source_url===origin(m.lead_hours)&&m.image==="images/dwd_tkb_"+String(m.lead_hours).padStart(3,"0")+".webp";
for(const root of document.querySelectorAll("[data-dwd-forecast]")){
 const grid=root.querySelector(".df-grid"),status=root.querySelector(".df-status"),
       selector=root.querySelector(".df-lead"),reload=root.querySelector(".df-reload");
 if(!grid||!status||!selector||!reload)continue;
 let maps=new Map(),generated=null;
 function draw(){
  grid.replaceChildren();
  let visible=selector.value==="all"?LEADS:LEADS.filter(l=>String(l)===selector.value);
  const old=generated&&Date.now()-Date.parse(generated)>24*3600000;
  let ready=0;
  for(const lead of visible){
   const record=maps.get(lead);
   const card=el("article","sg-card df-card");
   const head=el("div","sg-card-head");
   head.append(el("strong","sg-name","DWD · Bodenprognose +"+lead+" h"),el("span","sg-kind","Einzelkarte · Fronten & Isobaren"));
   card.append(head);
   if(record&&!old){
    const a=el("a","sg-image-link");a.href=ROOT+record.image;a.target="_blank";a.rel="noopener noreferrer";
    const img=el("img","sg-image");img.loading="lazy";img.decoding="async";img.src=ROOT+record.image;
    img.alt="Originale synoptische DWD-TKB-Bodenprognosekarte mit Isobaren und Fronten, +"+lead+" Stunden.";
    img.addEventListener("error",()=>{img.remove();a.append(el("p","sg-image-fallback","Bild derzeit nicht abrufbar. Originalquelle öffnen."));});
    a.append(img);card.append(a);ready++;
   }else{
    const no=el("p","sg-image-fallback",old?
       "Die letzte veröffentlichte Karte ist älter als 24 Stunden und wird nicht als aktuelle Prognose ausgegeben.":
       "DWD-Originalbild konnte noch nicht automatisch heruntergeladen werden.");
    card.append(no);
   }
   const info=el("div","sg-card-details");
   info.append(el("div","sg-time","Prognose +"+lead+" h"));
   info.append(el("div","sg-small","Gültigkeitsdatum und Ausgangslauf: im Kartenfuß des DWD-Originals"));
   info.append(el("div","sg-credit","Quelle: Deutscher Wetterdienst (DWD) · TKBoden"));
   const links=el("div","sg-links"),direct=el("a","","DWD-Originalbild ↗");direct.href=origin(lead);direct.rel="noopener noreferrer";direct.target="_blank";links.append(direct);
   if(record&&!old){const big=el("a","","Großansicht ↗");big.href=ROOT+record.image;big.rel="noopener noreferrer";big.target="_blank";links.append(big);}
   info.append(links);card.append(info);grid.append(card);
  }
  const stamp=generated?" · Datenstand: "+displayTime(generated):"";
  status.textContent=ready+" von "+visible.length+" TKB-Einzelkarten im Dashboard sichtbar"+stamp+
   (old?" · Veröffentlichung veraltet, daher keine vermeintlich aktuelle Karte.":"")+
   " · ausschließlich DWD +36, +48, +60, +84 und +108 h.";
 }
 async function load(){
  status.textContent="Lade DWD-TKB-Einzelkarten …";reload.disabled=true;
  try{
   const res=await fetch(ROOT+"dwd_tkb.json?v="+Date.now(),{cache:"no-store"});
   if(!res.ok)throw Error("Noch kein erfolgreicher DWD-TKB-Bildabruf");
   const meta=await res.json();
   if(meta.schema_version!==1||meta.single_map_per_lead!==true||!Array.isArray(meta.maps)||
      meta.products.join(",")!==LEADS.join(","))throw Error("Datenindex unvollständig");
   maps=new Map(meta.maps.filter(safe).map(m=>[m.lead_hours,m]));
   generated=meta.generated_utc;draw();
  }catch(e){
   maps=new Map();generated=null;draw();
   status.textContent="Die echten DWD-TKB-Einzelkarten sind noch nicht lokal verfügbar: "+e.message+
     ". Hier stehen die fünf amtlichen direkten Bildlinks bereit; keine Mehrfachblätter.";
  }finally{reload.disabled=false}
 }
 selector.addEventListener("change",draw);reload.addEventListener("click",load);load();
}
})();