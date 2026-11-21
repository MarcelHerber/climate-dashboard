/* loader.js – bedarfsgesteuertes Nachladen von Fachmodulen (Schritt 3a)
   Klassisches Skript. Muss VOR core.js geladen werden.
   Module teilen sich weiter den globalen Scope; der Zustand (let/const) bleibt in core.js. */
(function(){
  "use strict";

  // Dateiversionen. In Schritt 4 (automatische Cache-Versionierung) wird diese Tabelle generiert.
  const VERSIONS={
    "aktuell":"20261120-1",
    "era5-land":"20261121-1",
    "europa-stationen":"20261121-1",
    "schnee":"20261122-1"
  };
  // Tab-ID -> Module, die vor dem ersten Rendern des Tabs geladen sein müssen
  const TAB_MODULES={
    current:["aktuell"],
    era5Europe:["era5-land"],
    europeStations:["europa-stationen"],
    stationSnow:["schnee"]
  };
  // Inline-Handler im HTML, die vor dem Laden des Moduls aufrufbar sein müssen
  const HANDLER_STUBS={
    "schnee":["resetStationSnowZoom"]
  };
  // Zeit bis zum Vorladen im Leerlauf (ms nach window.load). false = kein Vorladen.
  const PREFETCH_DELAY=6000;

  const loaded=new Set();
  const loading=new Map();
  const restoredTabs=new Set();
  const visits=new Map();

  const OPTIMIZED_MODULES={};
  const moduleUrl=name=>OPTIMIZED_MODULES[name]||"js/"+name+".js"+(VERSIONS[name]?"?v="+VERSIONS[name]:"");

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
  const loadTab=tab=>Promise.all((TAB_MODULES[tab]||[]).map(loadModule));

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

  Object.entries(HANDLER_STUBS).forEach(([module,names])=>names.forEach(name=>{
    if(typeof window[name]==="function") return;
    const stub=function(...args){
      return loadModule(module).then(()=>{
        const real=window[name];
        if(typeof real==="function"&&real!==stub) return real.apply(window,args);
      });
    };
    window[name]=stub;
  }));

  window.DashboardModules={loadModule,loadTab,tabReady,whenTabReady,prefetch,afterIdle,moduleUrl};
  window.whenTabModulesReady=whenTabReady;
  window.isDashboardLazyPending=isPending;
})();
