/* ECMWF IFS ENS geopotential maps: spatial CONTEXT, not standardized CPC index forecasts. */
(() => {
  "use strict";
  if (document.body.dataset.climateModule !== "nao-ao") return;
  const $=id=>document.getElementById(id);
  const MANIFEST="data/nao_ao_forecast/ecmwf_maps/index.json";
  const ROOT="data/nao_ao_forecast/ecmwf_maps/";
  let manifest=null,active=null;
  function state(message,bad=false){
    const el=$("teleMapStatus");if(!el)return;
    el.textContent=message;el.classList.toggle("tele-error",bad);
  }
  function human(iso){
    const d=new Date(iso);
    return Number.isFinite(d.getTime())?d.toLocaleString("de-DE",{timeZone:"UTC",
      year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})+" UTC":"–";
  }
  function show(){
    if(!manifest)return;
    const level=Number($("teleMapLevel").value),step=Number($("teleMapLead").value);
    const entry=manifest.maps.find(x=>x.level_hpa===level&&x.step_hours===step);
    const img=$("teleMapImage");
    img.hidden=true;
    $("teleMapDownload").disabled=true;
    if(!entry||!/^ifs_ens_gh_(500|1000)hpa_f(072|144|240)[.]png$/.test(entry.file)){
      state("Für diese Auswahl wurde kein überprüftes ECMWF-Kartenbild veröffentlicht.",true);return;
    }
    active=entry;
    state("Lade echtes ECMWF-ENS-Mittelfeld …");
    img.onload=()=>{
      img.hidden=false;
      $("teleMapDownload").disabled=false;
      state("ECMWF IFS-ENS · "+level+" hPa · +"+step+" h · Modelllauf "+human(manifest.model_run_utc));
    };
    img.onerror=()=>{img.hidden=true;$("teleMapDownload").disabled=true;
      state("Das Kartendokument ist nicht erreichbar. Bitte Datenquelle prüfen.",true);};
    img.src=ROOT+encodeURIComponent(entry.file);
    $("teleMapInfo").textContent="Gültig "+human(entry.valid_time_utc)+" · IFS ENS-Mittel der absoluten "+
      level+"-hPa-Geopotenzialhöhe (gpm). Feste Farbskala für alle Vorhersagetermine je Niveau. "+
      "Keine Anomalie, kein CPC-NAO/AO-Index. Ausgangsdaten 0,25°, Kartenvisualisierung 0,5°. "+
      "Quelle: ECMWF Open Data · CC BY 4.0.";
  }
  async function load(){
    state("Prüfe verifizierte ECMWF-ENS-Karten …");
    try{
      const r=await fetch(MANIFEST+"?t="+Date.now(),{cache:"no-store"});
      if(!r.ok)throw Error("Noch kein ECMWF-Kartenarchiv veröffentlicht (HTTP "+r.status+").");
      const doc=await r.json();
      if(doc.schema!==1||doc.ready!==true||doc.is_index_forecast!==false||
         doc.is_anomaly!==false||doc.parameter!=="absolute_geopotential_height"||
         !Array.isArray(doc.maps)||doc.maps.length<6)
        throw Error("Unvollständiges Kartenmanifest – keine Karte eingeblendet.");
      const run=Date.parse(doc.model_run_utc);
      if(!Number.isFinite(run))throw Error("Modelllauf fehlt.");
      if(Date.now()-run>5*86400000)throw Error("Modelllauf ist älter als 5 Tage: "+doc.model_run_utc);
      manifest=doc;show();
    }catch(e){
      manifest=null;active=null;
      $("teleMapImage").hidden=true;
      $("teleMapDownload").disabled=true;
      state("ECMWF-Karten derzeit nicht verfügbar: "+e.message,true);
    }
  }
  function save(){
    if(!active)return;
    const a=document.createElement("a");
    a.href=ROOT+encodeURIComponent(active.file);
    a.download=active.file;
    document.body.appendChild(a);a.click();a.remove();
  }
  function init(){
    if(!$("teleMapImage"))return;
    $("teleMapLevel").addEventListener("change",show);
    $("teleMapLead").addEventListener("change",show);
    $("teleMapReload").addEventListener("click",load);
    $("teleMapDownload").addEventListener("click",save);
    load();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
