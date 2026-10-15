(()=>{
  "use strict";
  const root="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/seasonal-europe-data/data/seasonal-europe/";
  const $=id=>document.getElementById(id);
  const metadata={
    temperature:{name:"2-m-Temperatur",unit:"K",desc:"Monatliche Temperaturabweichung"},
    precipitation:{name:"Niederschlag",unit:"mm",desc:"Monatliche Niederschlagsabweichung"},
    snowfall:{name:"Schneefall",unit:"cm",desc:"Monatliche Schneefallabweichung"}
  };
  let data=null,version="";
  function monthName(period){
    if(!/^\d{4}-\d{2}$/.test(period))return period;
    const d=new Date(period+"-01T12:00:00Z");
    return d.toLocaleDateString("de-DE",{year:"numeric",month:"long",timeZone:"UTC"});
  }
  function status(message,type=""){
    $("seasonalStatus").textContent=message;
    $("seasonalStatus").className="status"+(type?" "+type:"");
  }
  function imgSrc(path){return root+path+"?v="+encodeURIComponent(version);}
  function chooseDefaultMonth(periods){
    const now=new Date();
    const firstOfNext=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth()+1,1))
      .toISOString().slice(0,7);
    return periods.find(x=>x.month===firstOfNext)?.month||periods[0]?.month||"";
  }
  function updateMonths(){
    const previous=$("seasonalMonth").value;
    const param=$("seasonalParameter").value;
    const options=(data?.periods||[]).filter(row=>row.fields?.[param]);
    $("seasonalMonth").replaceChildren();
    for(const row of options){
      const option=document.createElement("option");
      option.value=row.month;
      option.textContent=monthName(row.month);
      $("seasonalMonth").append(option);
    }
    $("seasonalMonth").disabled=!options.length;
    if(options.length)$("seasonalMonth").value=options.some(x=>x.month===previous)?previous:chooseDefaultMonth(options);
    render();
  }
  function render(){
    const image=$("seasonalMapImage"),loading=$("seasonalMapLoading");
    image.hidden=true;
    $("saveSeasonal").disabled=true;
    const month=$("seasonalMonth").value;
    const key=$("seasonalParameter").value;
    const current=data?.periods?.find(x=>x.month===month);
    const entry=current?.fields?.[key];
    if(!entry){
      loading.hidden=false;
      loading.textContent=data?"Für die Auswahl liegen keine vollständigen Modelldaten vor.":"Es sind noch keine echten Saisonkarten veröffentlicht.";
      $("seasonalMapTitle").textContent="ECMWF SEAS5 · Europa";
      $("seasonalTarget").textContent="Zielmonat: –";
      return;
    }
    const info=metadata[key];
    loading.hidden=false;
    loading.textContent="Feste Europa-Monatskarte wird geladen …";
    $("seasonalMapTitle").textContent=info.name+" · "+monthName(month);
    $("seasonalUnit").textContent=info.desc+" ("+entry.unit+")";
    $("seasonalTarget").textContent="Zielmonat: "+monthName(month);
    const uri=imgSrc(entry.image);
    image.onload=()=>{
      if(image.getAttribute("data-request-url")!==uri)return;
      loading.hidden=true;image.hidden=false;$("saveSeasonal").disabled=false;
    };
    image.onerror=()=>{
      if(image.getAttribute("data-request-url")!==uri)return;
      image.hidden=true;loading.hidden=false;
      loading.textContent="Die Kartenabbildung konnte nicht geladen werden. Bitte später erneut versuchen.";
      $("saveSeasonal").disabled=true;
      status("Die Modellmetadaten wurden geladen, das Kartenbild ist aber noch nicht erreichbar.","warn");
    };
    image.alt=info.name+" · saisonale Anomalie für Europa, "+monthName(month)+" · ECMWF SEAS5, Modellklimatologie";
    image.setAttribute("data-request-url",uri);
    image.src=uri;
  }
  async function refresh(){
    status("Lade ECMWF-SEAS5-Saisonprognosen …");
    try{
      const response=await fetch(root+"index.json?t="+Date.now(),{cache:"no-store"});
      if(!response.ok)throw new Error("HTTP "+response.status);
      const manifest=await response.json();
      if(manifest.schema!==1||manifest.model!=="ecmwf_seas5_ensemble_mean"||
         !Array.isArray(manifest.periods)||manifest.periods.length<3){
        throw new Error("Ungültiger Saisonindex");
      }
      if(!manifest.periods.some(row=>row.fields?.temperature&&row.fields?.precipitation)){
        throw new Error("Keine vollständigen Prognoseparameter");
      }
      data=manifest;version=manifest.render_revision||manifest.retrieved_utc||manifest.base_model_month||"1";
      const modelReference=manifest.anomaly_reference;
      $("seasonalReference").textContent =
        (modelReference?.reference_years_verified_for_api && modelReference?.api_reference_years)
        ? "Bezugsbasis: SEAS5-Modellklimatologie ("+modelReference.api_reference_years+")"
        : "Bezugsbasis: SEAS5-Modellklimatologie (Open-Meteo: Bezugsjahre nicht separat ausgewiesen)";
      $("seasonalRun").textContent="Modell-Ausgabe: "+monthName(manifest.base_model_month)+" · ECMWF SEAS5 · Kartendaten: "+manifest.sample_resolution_deg+"°-Raster";
      const stamp=new Date(manifest.retrieved_utc);
      $("seasonalFetched").textContent="Berechnet: "+(Number.isNaN(stamp.getTime())?"–":stamp.toLocaleString("de-DE",{timeZone:"UTC",timeZoneName:"short",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}));
      updateMonths();
      const age=(Date.now()-new Date(manifest.retrieved_utc).getTime())/86400000;
      status(age>45?"Achtung: Prognosekarten sind älter als 45 Tage – der letzte Datenabruf muss überprüft werden.":"Saisonale ECMWF-SEAS5-Karten bereit. Parameter und Zielmonat wählen.",age>45?"warn":"");
    }catch(error){
      data=null;
      $("seasonalMonth").disabled=true;
      $("saveSeasonal").disabled=true;
      $("seasonalMapImage").hidden=true;
      $("seasonalMapLoading").hidden=false;
      $("seasonalMapLoading").textContent="Noch keine vollständigen monatlichen ECMWF-SEAS5-Karten veröffentlicht.";
      status("Aktuell fehlen veröffentlichte saisonale Kartendaten ("+error.message+"). Es werden keine Ersatzprognosen angezeigt.","error");
    }
  }
  async function downloadPNG(){
    const period=data?.periods?.find(p=>p.month===$("seasonalMonth").value);
    const key=$("seasonalParameter").value;
    const relative=period?.fields?.[key]?.image;
    if(!relative)return;
    const url=imgSrc(relative),btn=$("saveSeasonal");
    btn.disabled=true;
    try{
      const res=await fetch(url,{mode:"cors",cache:"no-store"});
      if(!res.ok)throw new Error("HTTP "+res.status);
      const blob=await res.blob();
      if(!blob.type.startsWith("image/")||blob.size<12000)throw new Error("Ungültiges PNG");
      const temp=URL.createObjectURL(blob);
      const a=document.createElement("a");
      a.href=temp;
      a.download="SEAS5_Europa_"+key+"_"+period.month+"_init_"+data.base_model_month+".png";
      document.body.appendChild(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(temp),30000);
    }catch(error){
      console.error("SEAS5-Kartendownload:",error);
      status("PNG konnte nicht heruntergeladen werden. Kartenabbildung in neuem Tab öffnen oder erneut versuchen.","warn");
      window.open(url,"_blank","noopener,noreferrer");
    }finally{
      btn.disabled=false;
    }
  }
  $("seasonalParameter").addEventListener("change",updateMonths);
  $("seasonalMonth").addEventListener("change",render);
  $("refreshSeasonal").addEventListener("click",refresh);
  $("saveSeasonal").addEventListener("click",downloadPNG);
  refresh();
})();