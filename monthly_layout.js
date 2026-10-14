/* Gebietsmittel navigation, expandable map resize and accessible reveal.
   No data or chart computations are modified. */
(() => {
  "use strict";
  const byId=id=>document.getElementById(id);
  function resizeMonthlyMaps(){
    // Leaflet containers that were initially hidden by <details> need a real
    // size after opening, otherwise only a corner of the map is drawn.
    for(const name of ["regionalMap","regionalMapB","regionalMapDiff"]){
      try{
        const map=typeof window[name]!=="undefined" ? window[name] : null;
        if(map && typeof map.invalidateSize==="function")map.invalidateSize({animate:false});
      }catch(error){console.warn("Gebietsmittel-Kartengröße:",name,error);}
    }
    // Top-level let bindings are not window properties; access the global
    // lexical environment directly (the main dashboard uses classic scripts).
    try{
      for(const map of [
        typeof regionalMap!=="undefined" ? regionalMap : null,
        typeof regionalMapB!=="undefined" ? regionalMapB : null,
        typeof regionalMapDiff!=="undefined" ? regionalMapDiff : null
      ])if(map&&typeof map.invalidateSize==="function")map.invalidateSize({animate:false});
      for(const chart of [
        typeof regionalDetailChart!=="undefined" ? regionalDetailChart : null,
        typeof regionalDetailDiffChart!=="undefined" ? regionalDetailDiffChart : null
      ])if(chart&&typeof chart.resize==="function")chart.resize();
    }catch(error){console.warn("Gebietsmittel-Kartenansicht:",error);}
    window.dispatchEvent(new Event("resize"));
  }
  function refreshMapPanel(){
    if(!byId("monthlyMapSection")?.open)return;
    if(!byId("monthly")?.classList.contains("active"))return;
    try{
      if(typeof updateRegionalMap==="function")updateRegionalMap();
    }catch(error){console.warn("Gebietsmittel-Kartenvergleich:",error);}
    // Leaflet loads boundary geometries asynchronously; repeat after rendering.
    for(const ms of [60,260,800])window.setTimeout(resizeMonthlyMaps,ms);
  }
  function setup(){
    const root=byId("monthly");
    if(!root||root.dataset.cleanupBound==="true")return;
    root.dataset.cleanupBound="true";
    const map=byId("monthlyMapSection");
    map?.addEventListener("toggle",()=>{if(map.open)refreshMapPanel();});
    root.querySelectorAll("[data-monthly-target]").forEach(button=>{
      button.addEventListener("click",()=>{
        const id=button.getAttribute("data-monthly-target");
        const target=byId(id);
        if(!target)return;
        if(target.tagName==="DETAILS")target.open=true;
        const panel=byId("monthlyMapSection");
        if(target===panel)refreshMapPanel();
        window.setTimeout(()=>target.scrollIntoView({behavior:"smooth",block:"start"}),75);
      });
    });
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",setup,{once:true});
  else setup();
})();
