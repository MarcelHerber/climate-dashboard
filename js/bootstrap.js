/* bootstrap.js – Start-Abrufe (update_status.json, data.json); muss nach allen Funktionsdateien laufen
   Aus index.html ausgelagert (Schritt 5). Klassisches Skript, gemeinsamer globaler Scope. */



// Start-Abrufe (aus uebersicht.js / gebietsmittel.js hierher verschoben: ihre .then-Callbacks nutzen
// Funktionen aus diesem Block und dürfen erst laufen, wenn alle Dateien ausgeführt wurden)
dashboardFetch("update_status.json",{cache:"no-store"})
  .then(response=>{if(!response.ok) throw new Error(); return response.json();})
  .then(status=>{
    const parts=[];
    if(status.daily?.latest_date){
      const d=new Date(status.daily.latest_date+"T12:00:00");
      parts.push(`Tagesdaten bis ${d.toLocaleDateString("de-DE")}`);
    }
    if(status.monthly?.latest_complete_month){
      const [y,m]=status.monthly.latest_complete_month.split("-");
      parts.push(`Monatsdaten bis ${m}/${y}`);
    }
    if(status.monthly?.area_count) parts.push(`${status.monthly.area_count} Gebiete`);
    if(status.station_records?.data_through){
      const d=new Date(status.station_records.data_through+"T12:00:00");
      parts.push(`Stationsrekorde bis ${d.toLocaleDateString("de-DE")}`);
    }
    if(status.station_precip?.data_through){
      const d=new Date(status.station_precip.data_through+"T12:00:00");
      parts.push(`Stationsniederschlag bis ${d.toLocaleDateString("de-DE")}`);
    }
    if(status.station_climate_days?.data_through){
      const d=new Date(status.station_climate_days.data_through+"T12:00:00");
      parts.push(`Stations-Kenntage bis ${d.toLocaleDateString("de-DE")}`);
    }
    if(status.station_heatwaves?.data_through){
      const d=new Date(status.station_heatwaves.data_through+"T12:00:00");
      parts.push(`Stations-Hitzewellen bis ${d.toLocaleDateString("de-DE")}`);
    }
    if(status.updated_at){
      const updated=new Date(status.updated_at);
      parts.push(`zuletzt geprüft ${updated.toLocaleString("de-DE",{timeZone:"Europe/Berlin",dateStyle:"short",timeStyle:"short"})}`);
    }
    document.getElementById("dataStatus").textContent=parts.length?parts.join(" · "):"Datenstand nicht verfügbar";
    renderDashboardStatusBadges(status);
    updateOverviewStatus(status);
    if(monthlyData.length){
      updateOverviewSummary();
      if(document.getElementById("overview")?.classList.contains("active"))renderOverviewMap();
    }
  })
  .catch(()=>{
    document.getElementById("dataStatus").textContent="Datenstand nicht verfügbar";
    document.getElementById("statusBadges").innerHTML='<span class="status-badge error">Statusdatei nicht erreichbar</span>';
  });

dashboardFetch("data.json",{cache:"no-store"})
  .then(response=>{if(!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();})
  .then(raw=>{
    monthlyData=normalizeMonthly(raw);
    window.ensureGebietsmittelArchiveLoaded?.(monthlyData);
    fillAreaSelectors();
    fillCompareAreaSelectors();
    populateAccumulationYears();
    updateMonthly();
    loadMonthlyObservedLive();
    updateMonthlyAnomalyTable();
    updateClimateIndex();
    updateAccumulation();
    populateRegionalMapYears({preserve:false});
    updateRegionalMap();
    renderOverview();
  })
  .catch(error=>showError(`Monatsdaten konnten nicht geladen werden: ${error.message}`));

initializeChartExportButtons();
// Lazy modules: prefetch only in idle time, not during the initial render.
DashboardModules.afterIdle(()=>DashboardModules.loadModule("europa-stationen").then(()=>preloadEuropeStationData()).catch(()=>{}),4000);
DashboardModules.prefetch(["aktuell","era5-land","schnee"]);
// The state may point to a tab implemented by a later classic or deferred script.
// DOMContentLoaded waits for those scripts, even when their downloads are slow.
document.addEventListener("DOMContentLoaded", ()=>{initializeDashboardState();}, {once:true});
