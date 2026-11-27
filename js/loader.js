/* loader.js – bedarfsgesteuertes Nachladen von Fachmodulen (Schritt 3a/3b)
   Klassisches Skript. Muss VOR core.js geladen werden.
   Module teilen sich weiter den globalen Scope; der Zustand (let/const) bleibt in core.js. */
(function(){
  "use strict";

  // Dateiversionen werden beim Pages-Build von tools/version_assets.py erzeugt.
  const MODULES={
    "aktuell":["js/aktuell.js","20261120-1"],
    "era5-land":["js/era5-land.js","20261121-1"],
    "europa-stationen":["js/europa-stationen.js","20261121-1"],
    "schnee":["js/schnee.js","20261122-1"],
    "hyras_regional":["hyras_regional.js","20261127-vector-pdf-v3"],
    "hyras_temperature_interactive":["hyras_temperature_interactive.js","20261127-national-pdf-v1"],
    "hyras":["js/hyras.js","20261124-contour-1"],
    "hyras-tmin":["js/hyras-tmin.js","20261124-downloads-1"],
    "hyras_historical_temperature_1km":["hyras_historical_temperature_1km.js","5"],
    "t850_ensembles":["t850_ensembles.js","20261126-ensemble-desktop-png-v1"],
    "sst_europe":["sst_europe.js","20261118-sst-history-1"],
    "state_monthly_ensemble":["state_monthly_ensemble.js","20261121-rollover-1"],
    "gebietsmittel_archiv":["gebietsmittel_archiv.js","20261125-season"],
    "era5_europe":["era5_europe.js","20261014-era5-sync-fix"],
    "station_snow_years":["station_snow_years.js","20261104-2"],
    "station_snow_accumulation":["station_snow_accumulation.js","20261104-2"],
    "station_snow_explorer":["station_snow_explorer.js","20261105-2"],
    "europe_station_basemap":["europe_station_basemap.js","20261104-3"]
  };
  // Tab-ID -> Module, die vor dem ersten Rendern des Tabs geladen sein müssen
  const TAB_MODULES={
    current:["aktuell"],
    era5Europe:["era5-land"],
    europeStations:["europe_station_basemap","europa-stationen"],
    stationSnow:["europe_station_basemap","station_snow_years","station_snow_accumulation","station_snow_explorer","schnee"],
    hyras:["hyras_regional","hyras_temperature_interactive","hyras","hyras-tmin","hyras_historical_temperature_1km"],
    "t850-ensembles":["t850_ensembles"],
    "sst-europe":["sst_europe"],
    "state-monthly-ensemble":["state_monthly_ensemble"],
    gebietsmittelArchive:["gebietsmittel_archiv"],
    era5Atmosphere:["era5_europe"]
  };
  // Inline-Handler im HTML, die vor dem Laden des Moduls aufrufbar sein müssen
  const HANDLER_STUBS={
    stationSnow:["resetStationSnowZoom"],
    hyras:["hyrasRankStep","hyrasRankTogglePlay","hyrasRankSliderInput","hyrasRankPreloadAll","hyrasRankDownloadAnimation"]
  };
  // Zeit bis zum Vorladen im Leerlauf (ms nach window.load). false = kein Vorladen.
  const PREFETCH_DELAY=6000;

  const loaded=new Set();
  const loading=new Map();
  const restoredTabs=new Set();
  const visits=new Map();

  const OPTIMIZED_MODULES={};
  const moduleUrl=name=>{const entry=MODULES[name];if(!entry)throw new Error("Unbekanntes Modul: "+name);return OPTIMIZED_MODULES[name]||entry[0]+"?v="+entry[1];};

  function loadModule(name){
    if(loaded.has(name)) return Promise.resolve();
    if(loading.has(name)) return loading.get(name);
    const promise=new Promise((resolve,reject)=>{
      const script=document.createElement("script");
      script.src=moduleUrl(name);
      script.async=false;
      script.onload=()=>{loaded.add(name);loading.delete(name);resolve();};
      script.onerror=()=>{loading.delete(name);script.remove();reject(new Error("Modul \""+name+"\" konnte nicht geladen werden."));};
      document.head.appendChild(script);
    });
    loading.set(name,promise);
    return promise;
  }

  const tabReady=tab=>!TAB_MODULES[tab]||TAB_MODULES[tab].every(name=>loaded.has(name));
  // Do not execute a dependent script until its predecessor has succeeded.
  // A retry resumes at the missing dependency without re-executing prior scripts.
  async function loadTab(tab){for(const name of TAB_MODULES[tab]||[])await loadModule(name);}

  // Steuerelemente eines noch nicht geladenen Tabs werden von restoreDashboardControls() übersprungen
  // und nach dem Laden des Moduls gezielt wiederhergestellt (dann sind die Listener vorhanden).
  function isPending(control){
    const tabId=control&&control.closest?control.closest(".tab-content")?.id:null;
    return !!tabId&&!!TAB_MODULES[tabId]&&!restoredTabs.has(tabId);
  }

  function clearNotice(tabEl){
    tabEl?.querySelectorAll(":scope > .module-load-notice").forEach(node=>node.remove());
  }
  function showNotice(tabEl,text,retry){
    if(!tabEl) return;
    clearNotice(tabEl);
    const box=document.createElement("div");
    box.className="module-load-notice";
    box.setAttribute("role",retry?"alert":"status");
    box.style.cssText="margin:12px 0;padding:10px 14px;border-radius:8px;border:1px solid rgba(128,128,128,.35);font-size:.95em";
    box.append(document.createTextNode(text));
    if(retry){
      const button=document.createElement("button");
      button.type="button";
      button.textContent="Erneut versuchen";
      button.style.cssText="margin-left:12px;cursor:pointer";
      button.addEventListener("click",retry);
      box.append(button);
    }
    tabEl.prepend(box);
  }

  // Führt callback aus, sobald alle Module des Tabs geladen sind (sofort, wenn das schon der Fall ist).
  function whenTabReady(tab,callback){
    const tabEl=document.getElementById(tab);
    const visit=(visits.get(tab)||0)+1;
    visits.set(tab,visit);
    const isCurrent=()=>visits.get(tab)===visit&&(!tabEl||tabEl.classList.contains("active"));
    const retry=()=>whenTabReady(tab,callback);
    const activate=()=>{
      if(!isCurrent()) return;
      clearNotice(tabEl);
      if(!restoredTabs.has(tab)){
        restoredTabs.add(tab);
        if(typeof window.restoreDashboardControls==="function") window.restoreDashboardControls(tabEl||document);
      }
      return Promise.resolve().then(callback).catch(error=>{
        if(isCurrent()) showNotice(tabEl,"Daten konnten nicht geladen werden: "+error.message,retry);
      });
    };
    if(tabReady(tab)) return activate();
    showNotice(tabEl,"Modul wird geladen …");
    return loadTab(tab).then(activate,error=>{
      if(isCurrent()) showNotice(tabEl,error.message+" Bitte Verbindung prüfen.",retry);
    });
  }

  function afterIdle(fn,delay){
    const run=()=>window.setTimeout(()=>{
      if("requestIdleCallback" in window) window.requestIdleCallback(fn,{timeout:5000}); else fn();
    },delay||0);
    if(document.readyState==="complete") run(); else window.addEventListener("load",run,{once:true});
  }
  function saveDataMode(){
    const connection=navigator.connection;
    return !!(connection&&(connection.saveData||/(^|-)2g$/.test(connection.effectiveType||"")));
  }
  // Legt die Dateien nur in den HTTP-Cache (rel=prefetch), führt sie nicht aus.
  function prefetch(names){
    if(PREFETCH_DELAY===false||saveDataMode()) return;
    afterIdle(()=>names.forEach(name=>{
      if(loaded.has(name)||loading.has(name)) return;
      const link=document.createElement("link");
      link.rel="prefetch";link.as="script";link.href=moduleUrl(name);
      document.head.appendChild(link);
    }),PREFETCH_DELAY);
  }

  Object.entries(HANDLER_STUBS).forEach(([tab,names])=>names.forEach(name=>{
    if(typeof window[name]==="function") return;
    const stub=function(...args){
      return loadTab(tab).then(()=>{
        const real=window[name];
        if(typeof real==="function"&&real!==stub) return real.apply(window,args);
      }).catch(error=>{
        const tabEl=document.getElementById(tab);
        if(tabEl?.classList.contains("active")&&!tabEl.querySelector(":scope > .module-load-notice"))showNotice(tabEl,error.message+" Bitte Verbindung prüfen.",()=>stub(...args));
      });
    };
    window[name]=stub;
  }));

  window.DashboardModules={loadModule,loadTab,tabReady,whenTabReady,prefetch,afterIdle,moduleUrl};
  window.whenTabModulesReady=whenTabReady;
  window.isDashboardLazyPending=isPending;
})();
