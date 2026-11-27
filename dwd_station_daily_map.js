(()=>{"use strict";
const BASE="europe_stations/dwd_daily_map/",MODES={tmax_anom:["Tmax-Anomalie",3,"anom"],tmean_anom:["Tmean-Anomalie",12,"anom"],tmin_anom:["Tmin-Anomalie",4,"anom"],tmax:["Tmax",1,"tmax"],tmean:["Tmean",11,"tmean"],tmin:["Tmin",2,"tmin"],records:["Stationsrekorde",null,"records"],summer_days:["Sommertage · Rekordabstand","summer_days","climate"],hot_days:["Hitzetage · Rekordabstand","hot_days","climate"],very_hot_days:["≥35 °C · Rekordabstand","very_hot_days","climate"],tropical_nights:["Tropennächte · Rekordabstand","tropical_nights","climate"],frost_days:["Frosttage · Rekordabstand","frost_days","climate"],ice_days:["Eistage · Rekordabstand","ice_days","climate"]};
let idx=null,map=null,layer=null,renderer=null,cache=new Map(),climateCache=null,selected=null,bound=false,idxCheckedAt=0,idxRequest=null,drawRevision=0;
const RECORDS=[["tmax_hi","Wärmster Tag",5,7,1,18,true],["tmin_hi","Wärmste Nacht",17,15,2,19,true],["tmax_lo","Kältester Tag",16,14,1,18,false],["tmin_lo","Kälteste Nacht",6,8,2,19,false]];
const DEFAULT_REF="1991_2020";
const $=id=>document.getElementById(id),esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const tenth=v=>(v===null||v===undefined||v==="")?null:(Number.isFinite(Number(v))?Number(v)/10:null);
const temp=v=>tenth(v)==null?"–":tenth(v).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})+" °C";
const anom=v=>tenth(v)==null?"–":(tenth(v)>0?"+":"")+tenth(v).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})+" K";
const datefmt=v=>v?new Date(v+"T12:00:00").toLocaleDateString("de-DE"):"–";
function inject(){
 if($("dwdDailyMap"))return;
 const link=document.createElement("link");link.rel="stylesheet";link.href="dwd_station_daily_map.css?v=2";document.head.appendChild(link);
 const menu=document.querySelector('.nav-dropdown[data-nav-group="stations"] .nav-dropdown-menu');
 if(menu&&!menu.querySelector('[data-dwd-daily]')){const b=document.createElement("button");b.className="tab-button";b.dataset.navGroup="stations";b.dataset.dwdDaily="1";b.textContent="DWD Tageskarte";b.onclick=()=>{switchTab("dwdDailyMap");setTimeout(load,0)};const anchor=menu.querySelector('[onclick*="stationObservations"]');(anchor?.nextSibling?menu.insertBefore(b,anchor.nextSibling):menu.appendChild(b));}
 const tab=document.createElement("div");tab.id="dwdDailyMap";tab.className="tab-content";tab.innerHTML=`
 <div class="section-header"><h2>DWD Tageskarte</h2><p>Tageswerte, Anomalien, Kalendertagsrekorde und aktueller Abstand zu jährlichen Kenntage-Rekorden aller verfügbaren DWD-KL-Stationen.</p><span class="section-status">DWD CDC Tageswerte KL · TXK/TNK/TMK</span></div>
 <div class="dwd-daily-shell">
  <aside class="dwd-daily-card"><div class="dwd-daily-controls">
   <div class="control-group"><label for="dwdDailyMetric">Darstellung</label><select id="dwdDailyMetric"><optgroup label="Tageswerte"><option value="tmax_anom">Tmax-Anomalie</option><option value="tmean_anom">Tmean-Anomalie</option><option value="tmin_anom">Tmin-Anomalie</option><option value="tmax">Tmax absolut</option><option value="tmean">Tmean absolut</option><option value="tmin">Tmin absolut</option><option value="records">Stationsrekorde</option></optgroup><optgroup label="Kenntage · Abstand zum Jahresrekord"><option value="summer_days">Sommertage ≥25 °C</option><option value="hot_days">Hitzetage ≥30 °C</option><option value="very_hot_days">Sehr heiße Tage ≥35 °C</option><option value="tropical_nights">Tropennächte ≥20 °C</option><option value="frost_days">Frosttage &lt;0 °C</option><option value="ice_days">Eistage &lt;0 °C</option></optgroup></select></div>
   <div class="control-group"><label for="dwdDailyRef">Klimareferenz</label><select id="dwdDailyRef"><option value="1991_2020">1991–2020</option></select></div>
   <div class="control-group"><label for="dwdDailyDirection">Rekordrichtung</label><select id="dwdDailyDirection"><option value="all">Alle verfügbaren</option><option value="tmax_hi">Wärmster Tag</option><option value="tmin_hi">Wärmste Nacht</option><option value="tmax_lo">Kältester Tag</option><option value="tmin_lo">Kälteste Nacht</option></select></div>
   <div class="control-group"><label for="dwdDailyYears">Rekorde ab Messjahren</label><select id="dwdDailyYears"><option value="30">30</option><option value="50">50</option><option value="75">75</option><option value="100">100</option></select></div>
   <div class="control-group"><label><input id="dwdDailyVariableSize" type="checkbox" checked> Kreisgröße nach Anomalie</label></div>
   <div class="control-group"><label>Datum</label><div class="dwd-daily-date-nav"><button id="dwdDailyPrev">‹</button><input id="dwdDailyDate" type="date"><button id="dwdDailyNext">›</button></div></div>
   <button id="dwdDailyRefresh" type="button" class="action" title="Verfügbare DWD-CDC-Tageswerte erneut abrufen">Datenstand prüfen ↻</button><p id="dwdDailyFreshness" class="note" aria-live="polite">Datenstand wird geprüft …</p><p id="dwdDailyReference" class="note">Referenz wird geladen …</p>
  </div><div id="dwdDailyStatus" class="dwd-daily-status">Daten werden geladen …</div>
  <div class="dwd-daily-kpis"><div class="dwd-daily-kpi"><div class="label">Stationen</div><div id="dwdDailyStationCount" class="value">–</div></div><div class="dwd-daily-kpi"><div class="label">mit Anomalie</div><div id="dwdDailyAnomalyCount" class="value">–</div></div><div class="dwd-daily-kpi"><div class="label">Rekordstationen</div><div id="dwdDailyRecordCount" class="value">–</div></div><div class="dwd-daily-kpi"><div class="label">Datenstand</div><div id="dwdDailyDataThrough" class="value">–</div></div></div></aside>
  <section class="dwd-daily-card"><div id="dwdDailyStationMap" class="dwd-daily-map"></div><div id="dwdDailyLegend" class="dwd-daily-legend"></div><div id="dwdDailySelected" class="dwd-daily-selected"><h3>Station auswählen</h3><p>Klicke einen Stationspunkt oder einen Ranglisten-Eintrag an.</p></div></section>
  <aside class="dwd-daily-side"><div class="dwd-daily-card"><h3 id="dwdDailyTopTitle">Top 10</h3><div id="dwdDailyTopList" class="dwd-daily-list"></div></div><div class="dwd-daily-card"><h3 id="dwdDailyBottomTitle">Bottom 10</h3><div id="dwdDailyBottomList" class="dwd-daily-list"></div></div><div class="dwd-daily-card"><h3 id="dwdDailyRecordTitle">Rekorde des Tages</h3><p id="dwdDailyRecordSummary" class="note">–</p><div id="dwdDailyRecordList" class="dwd-daily-list"></div></div></aside>
 </div>`;
 const main=document.querySelector("main.dashboard-main");
 main?.insertBefore(tab,main.querySelector(".dashboard-footer"));
 const mobile=$("mobileTabSelect");if(mobile&&!mobile.querySelector('option[value="dwdDailyMap"]')){const o=document.createElement("option");o.value="dwdDailyMap";o.textContent="DWD Tageskarte";mobile.appendChild(o);mobile.addEventListener("change",()=>{if(mobile.value==="dwdDailyMap")setTimeout(load,0)})}
}
async function gunzip(url){const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw Error("HTTP "+r.status);const b=new Uint8Array(await r.arrayBuffer());if(b[0]===31&&b[1]===139){if(!window.DecompressionStream)throw Error("gzip wird vom Browser nicht unterstützt");const s=new Blob([b]).stream().pipeThrough(new DecompressionStream("gzip"));return JSON.parse(await new Response(s).text())}return JSON.parse(new TextDecoder().decode(b))}
async function index({force=false}={}){
 if(idx&&!force&&Date.now()-idxCheckedAt<300000)return idx;
 if(idxRequest)return idxRequest;
 idxRequest=(async()=>{
  const r=await fetch(BASE+"index.json?v="+Date.now(),{cache:"no-store"});
  if(!r.ok)throw Error("HTTP "+r.status);
  const next=await r.json();
  if(!next.ready||!Array.isArray(next.dates))throw Error("Tageskarten-Daten sind noch nicht erzeugt");
  if(!idx||next.generated_at!==idx.generated_at||next.data_through!==idx.data_through){
    cache.clear();climateCache=null;selected=null;
  }
  idx=next;idxCheckedAt=Date.now();return idx;
 })();
 try{return await idxRequest}finally{idxRequest=null}
}
function showFreshness(){
 const el=$("dwdDailyFreshness");if(!el||!idx)return;
 const utcNow=new Date(),start=new Date(idx.data_through+"T00:00:00Z");
 const days=Number.isFinite(start.getTime())?Math.max(0,Math.floor((Date.UTC(utcNow.getUTCFullYear(),utcNow.getUTCMonth(),utcNow.getUTCDate())-start.getTime())/86400000)):null;
 const built=idx.generated_at?new Date(idx.generated_at).toLocaleString("de-DE",{dateStyle:"short",timeStyle:"short"}):"unbekannt";
 el.textContent="DWD-Tageswerte bis "+datefmt(idx.data_through)+" · Karten-Update: "+built+
   (days!==null&&days>=3?" · Hinweis: Datenstand "+days+" Tage zurück; DWD CDC und nächsten Update-Lauf prüfen.":" · DWD CDC veröffentlicht Tageswerte zeitversetzt.");
 el.style.color=days!==null&&days>=3?"#9a5700":"";
}
function activeRef(){return $("dwdDailyRef")?.value||idx?.default_reference||DEFAULT_REF}
function refLabel(){return idx?.references?.find(r=>r.key===activeRef())?.label||idx?.reference_period||"1991–2020"}
function mergeReference(base,ref){
 if(base.date!==ref.date)throw Error("Referenz und Tagesdatei passen nicht zusammen.");
 const by=new Map(ref.rows.map(r=>[r[0],r]));
 return {...base,reference_period:ref.reference_period,rows:base.rows.map(r=>{const x=by.get(r[0]),out=r.slice();out[3]=x?.[1]??null;out[4]=x?.[2]??null;out[12]=x?.[3]??null;out[9]=x?.[4]??0;out[10]=x?.[5]??0;out[13]=x?.[6]??0;return out})};
}
async function day(iso,key=activeRef()){
 const md=iso.slice(5),v=encodeURIComponent(idx.generated_at||"");
 function cached(k,url){if(!cache.has(k))cache.set(k,gunzip(url).catch(e=>{cache.delete(k);throw e}));return cache.get(k)}
 const base=await cached(md+"|base",BASE+"calendar/"+md+".json.gz?v="+v);
 if(base.date!==iso)throw Error("Tagesdatei passt nicht zum Datum.");
 if(key===(idx.default_reference||DEFAULT_REF))return base;
 if(!idx.references?.some(r=>r.key===key)||!/^\d{4}_\d{4}$/.test(key))throw Error("Unbekannte Klimareferenz.");
 return mergeReference(base,await cached(md+"|"+key,BASE+"calendar_ref/"+key+"/"+md+".json.gz?v="+v));
}
function isV2(){return Number(idx?.version)>=2&&Array.isArray(idx?.record_directions)}
function syncNewControls(climate){
 const ref=$("dwdDailyRef"),old=ref.value,refs=idx?.references?.length?idx.references:[{key:DEFAULT_REF,label:idx?.reference_period||"1991–2020"}];
 ref.replaceChildren(...refs.map(r=>{const o=document.createElement("option");o.value=r.key;o.textContent=r.label;return o}));
 ref.value=refs.some(r=>r.key===old)?old:(idx.default_reference||refs[0].key);ref.disabled=climate||refs.length<2;
 const dir=$("dwdDailyDirection");for(const o of dir.options)o.disabled=!isV2()&&["tmax_lo","tmin_hi"].includes(o.value);
 if(dir.selectedOptions[0]?.disabled)dir.value="all";dir.disabled=climate;
 $("dwdDailyYears").disabled=climate||!isV2();$("dwdDailyVariableSize").disabled=climate||mode()[3]!=="anom";
}
function minYears(iso){const n=Number($("dwdDailyYears")?.value||30);return iso?.slice(5)==="02-29"?Math.ceil(n/4):n}
function flags(r,iso){const dir=$("dwdDailyDirection")?.value||"all";return r?RECORDS.filter(d=>(dir==="all"||dir===d[0])&&r[d[2]]&&(!isV2()||r[d[5]]>=minYears(iso))):[]}
function recColor(f){return f.some(d=>d[6])&&f.some(d=>!d[6])?"#6c3c91":f.some(d=>d[6])?"#b83332":f.some(d=>!d[6])?"#315f9e":"#b9c0c5"}
function recText(r,iso){return flags(r,iso).map(d=>d[1]+" "+(r[d[2]]===1?"neu":"eingestellt")).join(" · ")||"kein Rekord"}
function radius(r,m,has){return !has?3.2:m[3]==="anom"&&$("dwdDailyVariableSize")?.checked?3.5+Math.min(7,Math.abs(Number(r[m[2]]))/15):5.2}
async function climate(){if(!climateCache){const r=await fetch(BASE+(idx.climate_days_file||"climate_days.json")+"?v="+encodeURIComponent(idx.generated_at||""),{cache:"no-store"});if(!r.ok)throw Error("HTTP "+r.status);climateCache=await r.json()}return climateCache}
function station(i){const s=idx.stations[i];return s&&{i,id:s[0],dwd:s[1],name:s[2],lat:+s[3],lon:+s[4],elev:s[5],state:s[6]||""}}
function mode(){const k=$("dwdDailyMetric")?.value||"tmax_anom";return [k,...MODES[k]]}
function syncClimateOptions(){const ready=!!idx?.climate_days_file;document.querySelectorAll('#dwdDailyMetric option').forEach(o=>{const m=MODES[o.value];if(m?.[2]==="climate")o.disabled=!ready});const select=$("dwdDailyMetric");if(select&&MODES[select.value]?.[2]==="climate"&&!ready)select.value="tmax_anom";return ready}
function acol(v){const n=tenth(v);if(n==null)return"#aeb6bc";return n<=-8?"#233b75":n<=-5?"#3f69a8":n<=-3?"#6f9bc3":n<=-1?"#b8d1df":n<1?"#ecebe5":n<3?"#efc6a8":n<5?"#dc8b62":n<8?"#bd5140":"#7f1d2d"}
function tcol(v,max){const n=tenth(v);if(n==null)return"#aeb6bc";if(max)return n<0?"#466f9d":n<10?"#7da6a5":n<20?"#9dbb78":n<25?"#d5c568":n<30?"#e3a04e":n<35?"#d66f43":n<40?"#b83e37":"#7b1d2b";return n<-20?"#35275f":n<-10?"#4f66a6":n<0?"#79a6c7":n<10?"#a9c9ba":n<15?"#d6cb82":n<20?"#dfa05d":n<25?"#cc684d":"#963342"}
function tmcol(v){const n=tenth(v);if(n==null)return"#aeb6bc";return n<-10?"#3f4d86":n<0?"#668bb1":n<10?"#9abfb9":n<15?"#d0c879":n<20?"#e2aa58":n<25?"#d77848":n<30?"#b6453d":"#7f2430"}
function climateColor(v){const n=Number(v);if(!Number.isFinite(n))return"#aeb6bc";return n<=-20?"#355a8a":n<=-10?"#6689ad":n<=-5?"#9eb5c8":n<0?"#d5dfe5":n===0?"#e4c767":n<5?"#e7b09d":n<10?"#d8735f":"#a73535"}
function climateDiff(v){const n=Number(v);if(!Number.isFinite(n))return"–";return(n>0?"+":"")+n.toLocaleString("de-DE")+" Tage"}
function color(r,m){return m[3]==="anom"?acol(r?.[m[2]]):m[3]==="tmax"?tcol(r?.[m[2]],1):m[3]==="tmean"?tmcol(r?.[m[2]]):m[3]==="tmin"?tcol(r?.[m[2]],0):r?.[5]&&r?.[6]?"#6c3c91":r?.[5]?"#b83332":r?.[6]?"#315f9e":"#b9c0c5"}
function val(r,m){if(m[3]==="anom")return anom(r?.[m[2]]);if(m[3]==="tmax"||m[3]==="tmean"||m[3]==="tmin")return temp(r?.[m[2]]);const x=[];if(r?.[5])x.push("Tmax "+(r[5]===1?"NEU":"eingestellt"));if(r?.[6])x.push("Tmin "+(r[6]===1?"NEU":"eingestellt"));return x.join(" · ")||"kein Rekord"}
function legend(m){let a=m[3]==="climate"?[["≤ −20","#355a8a"],["−10","#6689ad"],["−5","#9eb5c8"],["−1","#d5dfe5"],["0 · eingestellt","#e4c767"],["+1 bis +4","#e7b09d"],["+5","#d8735f"],["≥ +10","#a73535"]]:m[3]==="anom"?[["≤ −8 K","#233b75"],["−5","#3f69a8"],["−3","#6f9bc3"],["±0","#ecebe5"],["+3","#dc8b62"],["+5","#bd5140"],["≥ +8 K","#7f1d2d"]]:m[3]==="records"?[["Warmrekord","#b83332"],["Kälterekord","#315f9e"],["beides","#6c3c91"]]:m[3]==="tmax"?[["<0","#466f9d"],["10","#7da6a5"],["20","#9dbb78"],["30","#e3a04e"],["35","#d66f43"],["≥40 °C","#7b1d2b"]]:m[3]==="tmean"?[["<−10","#3f4d86"],["0","#668bb1"],["10","#9abfb9"],["15","#d0c879"],["20","#e2aa58"],["25","#d77848"],["≥30 °C","#7f2430"]]:[["<−20","#35275f"],["−10","#4f66a6"],["0","#79a6c7"],["10","#a9c9ba"],["20","#dfa05d"],["≥25 °C","#963342"]];$("dwdDailyLegend").innerHTML=a.map(x=>`<span><i style="background:${x[1]}"></i>${x[0]}</span>`).join("")}
function initMap(){if(map||!$("dwdDailyStationMap")||!window.L)return;map=L.map("dwdDailyStationMap",{preferCanvas:true,minZoom:5,maxZoom:12,maxBounds:[[46.2,4.3],[56.2,16.8]],maxBoundsViscosity:.75});L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"&copy; OpenStreetMap contributors"}).addTo(map);renderer=L.canvas({padding:.4});layer=L.layerGroup().addTo(map);map.fitBounds([[47,5.5],[55.2,15.6]])}
function detail(s,r,iso){const recordDetails=RECORDS.filter(d=>isV2()||[5,6].includes(d[2])).map(d=>{const status=r[d[3]]==null?"kein historischer Wert":r[d[4]]==null?"kein Messwert":isV2()&&r[d[5]]<minYears(iso)?"zu wenige Messjahre":r[d[2]]===1?"neu gebrochen":r[d[2]]===2?"eingestellt":"nicht erreicht";return `<div><span>${d[1]} · bisher</span><strong>${temp(r[d[3]])}</strong><small>${status}${isV2()?" · "+(r[d[5]]??0)+" Messjahre":""}</small></div>`}).join("");$("dwdDailySelected").innerHTML=`<h3>${esc(s.name)}</h3><p>${esc(s.state||"Deutschland")} · DWD ${esc(s.dwd)} · ${datefmt(iso)}</p><div class="dwd-daily-detail-grid"><div><span>Höhe</span><strong>${s.elev==null?"–":Math.round(s.elev)+" m"}</strong></div><div><span>Tmax</span><strong>${temp(r[1])}</strong></div><div><span>Tmean</span><strong>${temp(r[11])}</strong></div><div><span>Tmin</span><strong>${temp(r[2])}</strong></div><div><span>Tmax-Anomalie</span><strong>${anom(r[3])}</strong><small>${r[9]||0} Ref.-Jahre</small></div><div><span>Tmean-Anomalie</span><strong>${anom(r[12])}</strong><small>${r[13]||0} Ref.-Jahre</small></div><div><span>Tmin-Anomalie</span><strong>${anom(r[4])}</strong><small>${r[10]||0} Ref.-Jahre</small></div>${recordDetails}</div>`}
function climateDetail(s,row,metric,meta){const years=(row[4]||[]).join(", ")||"–";$("dwdDailySelected").innerHTML=`<h3>${esc(s.name)}</h3><p>${esc(s.state||"Deutschland")} · DWD ${esc(s.dwd)} · Stand ${datefmt(row[6]||meta.data_through)}</p><div class="dwd-daily-detail-grid"><div><span>Kenntag</span><strong>${esc(meta.label)}</strong><small>${esc(meta.definition)}</small></div><div><span>${idx.year}</span><strong>${row[1]} Tage</strong><small>${row[5]} gültige Tageswerte</small></div><div><span>Bisheriger Rekord</span><strong>${row[2]} Tage</strong><small>${esc(years)}</small></div><div><span>Rekordabstand</span><strong>${climateDiff(row[3])}</strong><small>${row[3]>0?"Rekord übertroffen":row[3]===0?"Rekord eingestellt":"noch bis zum Rekord"}</small></div></div>`}
function climateRowsHtml(a){return a.length?a.map(x=>`<button class="dwd-daily-row dwd-daily-row-colored" data-i="${x.s.i}" style="--dwd-row-color:${climateColor(x.r[3])}"><span><b>${esc(x.s.name)}</b><small>${x.r[1]} / Rekord ${x.r[2]}</small></span><strong>${climateDiff(x.r[3])}</strong></button>`).join(""):'<div class="dwd-daily-empty">Keine passenden Stationen.</div>'}
function rowsHtml(a,m){return a.length?a.map(x=>{const c=color(x.r,m);return `<button class="dwd-daily-row dwd-daily-row-colored" data-i="${x.s.i}" style="--dwd-row-color:${c}"><span><b>${esc(x.s.name)}</b><small>${esc(x.s.state||"DWD "+x.s.dwd)}</small></span><strong>${esc(val(x.r,m))}</strong></button>`}).join(""):'<div class="dwd-daily-empty">Keine passenden Stationen.</div>'}
function renderClimate(payload){const m=mode(),metric=m[2],meta=payload.metrics?.[metric];if(!meta)throw Error("Kenntage-Daten fehlen für "+metric);const rm=new Map((meta.rows||[]).map(r=>[+r[0],r]));legend(m);initMap();layer.clearLayers();$("dwdDailyStationCount").textContent=rm.size.toLocaleString("de-DE");const reached=[...rm.values()].filter(r=>r[3]>=0).length,broken=[...rm.values()].filter(r=>r[3]>0).length,tied=[...rm.values()].filter(r=>r[3]===0).length;$("dwdDailyAnomalyCount").textContent=reached.toLocaleString("de-DE");$("dwdDailyRecordCount").textContent=broken.toLocaleString("de-DE");$("dwdDailyDataThrough").textContent=datefmt(payload.data_through);
 for(let i=0;i<idx.stations.length;i++){const s=station(i);if(!s||!Number.isFinite(s.lat)||!Number.isFinite(s.lon))continue;const r=rm.get(i),has=!!r;const mk=L.circleMarker([s.lat,s.lon],{renderer,radius:has?5.2:3.2,weight:has?1.15:.55,color:"#26313a",opacity:has?.95:.48,fillColor:has?climateColor(r[3]):"#aeb6bc",fillOpacity:has?.92:.25}).bindTooltip("<b>"+esc(s.name)+"</b><br>"+(has?esc(meta.label)+": "+r[1]+" · Rekord "+r[2]+" · "+esc(climateDiff(r[3])):"keine ausreichenden Daten"));mk.on("click",()=>{if(r){selected=i;climateDetail(s,r,metric,meta)}});mk.addTo(layer)}
 const avail=[...rm].map(([i,r])=>({s:station(i),r,v:+r[3]})).filter(x=>x.s);const top=[...avail].sort((a,b)=>b.v-a.v).slice(0,10),bottom=[...avail].sort((a,b)=>a.v-b.v).slice(0,10);$("dwdDailyTopTitle").textContent="Größte Rekordüberschreitung";$("dwdDailyBottomTitle").textContent="Größter Abstand zum Rekord";$("dwdDailyTopList").innerHTML=climateRowsHtml(top);$("dwdDailyBottomList").innerHTML=climateRowsHtml(bottom);$("dwdDailyRecordTitle").textContent="Kenntage-Rekordstand";$("dwdDailyRecordSummary").textContent=`${reached}/${rm.size} Stationen Rekord erreicht · ${broken} übertroffen · ${tied} eingestellt`;$("dwdDailyRecordList").innerHTML=avail.filter(x=>x.r[3]>=0).sort((a,b)=>b.v-a.v).slice(0,30).map(x=>`<button class="dwd-daily-row" data-i="${x.s.i}"><span><b>${esc(x.s.name)}</b><small>${x.r[1]} / ${x.r[2]} Tage</small></span><strong>${climateDiff(x.r[3])}</strong></button>`).join("")||'<div class="dwd-daily-empty">Noch kein Stationsrekord erreicht.</div>';document.querySelectorAll("#dwdDailyTopList [data-i],#dwdDailyBottomList [data-i],#dwdDailyRecordList [data-i]").forEach(b=>b.onclick=()=>{const i=+b.dataset.i,r=rm.get(i);if(r){selected=i;climateDetail(station(i),r,metric,meta);map.setView([station(i).lat,station(i).lon],Math.max(map.getZoom(),7))}});if(selected!=null&&rm.has(selected))climateDetail(station(selected),rm.get(selected),metric,meta);setTimeout(()=>map.invalidateSize(),50)}
function render(payload,iso){
 const rm=new Map(payload.rows.map(r=>[+r[0],r])),m=mode();legend(m);initMap();if(!layer)throw Error("Karte momentan nicht verfügbar.");layer.clearLayers();
 const entries=[...rm].map(([i,r])=>({s:station(i),r,f:flags(r,iso)})).filter(x=>x.s),rr=entries.filter(x=>x.f.length);
 $("dwdDailyRecordTitle").textContent="Rekorde des Tages";
 $("dwdDailyStationCount").textContent=rm.size.toLocaleString("de-DE");
 $("dwdDailyAnomalyCount").textContent=entries.filter(x=>[3,4,12].some(j=>x.r[j]!=null)).length.toLocaleString("de-DE");
 $("dwdDailyRecordCount").textContent=rr.length.toLocaleString("de-DE");
 $("dwdDailyDataThrough").textContent=datefmt(iso);
 for(let i=0;i<idx.stations.length;i++){
  const s=station(i);if(!s||!Number.isFinite(s.lat)||!Number.isFinite(s.lon))continue;
  const r=rm.get(i),f=flags(r,iso),has=m[3]==="records"?!!f.length:r?.[m[2]]!=null;
  const mk=L.circleMarker([s.lat,s.lon],{renderer,radius:radius(r,m,has),weight:f.length?2.3:has?.8:.55,color:f.length?"#151515":"#26313a",opacity:has?.95:.48,fillColor:m[3]==="records"?recColor(f):color(r,m),fillOpacity:has?.92:.22}).bindTooltip("<b>"+esc(s.name)+"</b><br>"+esc(m[3]==="records"?recText(r,iso):val(r,m))+(f.length&&m[3]!=="records"?"<br>"+esc(recText(r,iso)):""));
  mk.on("click",()=>{if(r){selected=i;detail(s,r,iso)}});mk.addTo(layer);
 }
 const recordRows=arr=>arr.length?arr.map(x=>`<button class="dwd-daily-row dwd-daily-row-colored" data-i="${x.s.i}" style="--dwd-row-color:${recColor(x.f)}"><span><b>${esc(x.s.name)}</b><small>${esc(x.s.state)}</small></span><strong>${esc(recText(x.r,iso))}</strong></button>`).join(""):'<div class="dwd-daily-empty">Keine passenden Rekorde.</div>';
 if(m[3]==="records"){
  const excess=(x,warm)=>Math.max(0,...x.f.filter(d=>d[6]===warm).map(d=>Math.abs(x.r[d[4]]-x.r[d[3]])));
  for(const [warm,title,list] of [[true,"dwdDailyTopTitle","dwdDailyTopList"],[false,"dwdDailyBottomTitle","dwdDailyBottomList"]]){
   $(title).textContent="Top 10 · "+(warm?"Warmrekorde":"Kälterekorde");
   $(list).innerHTML=recordRows(rr.filter(x=>x.f.some(d=>d[6]===warm)).sort((a,b)=>excess(b,warm)-excess(a,warm)).slice(0,10));
  }
 }else{
  const a=entries.filter(x=>x.r[m[2]]!=null).map(x=>({...x,v:+x.r[m[2]]}));
  $("dwdDailyTopTitle").textContent="Top 10 · "+m[1];$("dwdDailyBottomTitle").textContent="Bottom 10 · "+m[1];
  $("dwdDailyTopList").innerHTML=rowsHtml([...a].sort((a,b)=>b.v-a.v).slice(0,10),m);
  $("dwdDailyBottomList").innerHTML=rowsHtml([...a].sort((a,b)=>a.v-b.v).slice(0,10),m);
 }
 const counts=RECORDS.filter(d=>isV2()||[5,6].includes(d[2])).map(d=>d[1]+": "+rr.filter(x=>x.f.includes(d)).length);
 $("dwdDailyRecordSummary").textContent=rr.length+"/"+rm.size+" Stationen · "+counts.join(" · ")+(isV2()?" · ≥"+minYears(iso)+" gültige historische Werte":" · bisheriges Datenformat");
 $("dwdDailyRecordList").innerHTML=recordRows(rr);
 document.querySelectorAll("#dwdDailyTopList [data-i],#dwdDailyBottomList [data-i],#dwdDailyRecordList [data-i]").forEach(b=>b.onclick=()=>{const i=+b.dataset.i,r=rm.get(i);if(r){selected=i;detail(station(i),r,iso);map.setView([station(i).lat,station(i).lon],Math.max(map.getZoom(),7))}});
 if(selected!=null&&rm.has(selected))detail(station(selected),rm.get(selected),iso);else $("dwdDailySelected").innerHTML="<h3>Station auswählen</h3><p>Klicke einen Stationspunkt oder einen Ranglisten-Eintrag an.</p>";
 if(m[3]!=="records")$("dwdDailyLegend").insertAdjacentHTML("beforeend",'<span>Schwarzer Rand: ausgewählter Tagesrekord</span>');
 setTimeout(()=>map.invalidateSize(),50);
}
async function draw(){const revision=++drawRevision;try{await index();if(revision!==drawRevision)return;syncClimateOptions();const m=mode(),isClimate=m[3]==="climate",dateInput=$("dwdDailyDate"),prev=$("dwdDailyPrev"),next=$("dwdDailyNext");syncNewControls(isClimate);dateInput.disabled=isClimate;prev.disabled=isClimate;next.disabled=isClimate;if(isClimate){$("dwdDailyStatus").textContent=m[1]+" wird geladen …";const p=await climate();if(revision!==drawRevision)return;renderClimate(p);$("dwdDailyStatus").classList.remove("error");$("dwdDailyStatus").textContent=m[1]+" · Stand "+datefmt(p.data_through)+" · "+(p.metrics?.[m[2]]?.rows?.length||0).toLocaleString("de-DE")+" Stationen · historischer Jahresrekord bis "+(idx.year-1);return}let iso=dateInput.value||idx.data_through;if(!idx.dates.includes(iso)){iso=idx.dates.filter(d=>d<=iso).at(-1)||idx.dates[0];dateInput.value=iso}$("dwdDailyStatus").textContent=datefmt(iso)+" wird geladen …";const p=await day(iso);if(revision!==drawRevision)return;render(p,iso);$("dwdDailyStatus").classList.remove("error");$("dwdDailyStatus").textContent=MODES[$("dwdDailyMetric").value][0]+" · "+datefmt(iso)+" · "+p.rows.length.toLocaleString("de-DE")+" Stationen · Referenz "+refLabel()+(idx.smoothing_half_window_days?" · ±"+idx.smoothing_half_window_days+" Tage":"");$("dwdDailyReference").textContent="Tagesanomalien: "+refLabel()+" · "+(idx.smoothing_half_window_days?"geglättet ±"+idx.smoothing_half_window_days+" Tage; Referenzjahre als Median im Fenster":"Kalendertagsmittel")+(isV2()?" · Rekordfilter: Messwerte am exakten Kalendertag":" · erweiterte Rekord- und Referenzdaten noch nicht verfügbar")}catch(e){if(revision!==drawRevision)return;console.error(e);$("dwdDailyStatus").classList.add("error");$("dwdDailyStatus").textContent="DWD-Tageskarte konnte nicht geladen werden: "+e.message}}
function bind(){if(bound)return;bound=true;$("dwdDailyRefresh").onclick=()=>load();$("dwdDailyMetric").onchange=draw;for(const id of ["dwdDailyRef","dwdDailyDirection","dwdDailyYears","dwdDailyVariableSize"])$(id).onchange=draw;$("dwdDailyDate").onchange=draw;$("dwdDailyPrev").onclick=()=>{const i=idx.dates.indexOf($("dwdDailyDate").value);if(i>0){$("dwdDailyDate").value=idx.dates[i-1];draw()}};$("dwdDailyNext").onclick=()=>{const i=idx.dates.indexOf($("dwdDailyDate").value);if(i>=0&&i<idx.dates.length-1){$("dwdDailyDate").value=idx.dates[i+1];draw()}}}
async function load(){inject();const refresh=$("dwdDailyRefresh");if(refresh){refresh.disabled=true;refresh.textContent="Prüfe …";}try{const oldThrough=idx?.data_through;await index({force:true});bind();initMap();const climateReady=syncClimateOptions(),d=$("dwdDailyDate");d.min=idx.dates[0]||"";d.max=idx.data_through||"";if(!d.value||d.value===oldThrough||d.value>idx.data_through)d.value=idx.data_through;showFreshness();$("dwdDailyReference").textContent=climateReady?"Tagesanomalien: Stationsmittel "+idx.reference_period+" · Kenntage: aktueller Jahresstand minus bisheriger Stations-Jahresrekord":"Tagesanomalien: Stationsmittel "+idx.reference_period+" · Kenntage-Rekorde werden gerade erstmalig aufgebaut …";await draw()}catch(e){$("dwdDailyStatus").classList.add("error");$("dwdDailyStatus").textContent="DWD-Tageskarte konnte nicht geladen werden: "+e.message}finally{if(refresh){refresh.disabled=false;refresh.textContent="Datenstand prüfen ↻"}}}
inject();window.ensureDwdDailyMapLoaded=load;
})();
