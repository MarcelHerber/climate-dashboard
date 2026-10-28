(() => {
  "use strict";

  // Use the small same-origin Pages copy first; avoid cross-origin fetch stalls
  // for the first map. Remote sources are retained for independent updates.
  const DATA_LOCAL_URL = "./data/mosmix/mosmix_ttt.json";
  const DATA_COMPRESSED_URL = "./data/mosmix/mosmix_ttt.json.gz";
  const DATA_URL = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/mosmix-data/data/mosmix/mosmix_ttt.json";
  // A second CDN prevents a blocked raw.githubusercontent.com request from
  // leaving the MOSMIX section in an endless loading state.
  const DATA_BACKUP_URL = "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@mosmix-data/data/mosmix/mosmix_ttt.json";
  const DATA_TIMEOUT_MS = 15000;
  const MANIFEST_URL = "./data/mosmix/manifest.json";
  const MANIFEST_BACKUP_URL = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/mosmix-data/data/mosmix/manifest.json";
  const MAP_BACKUP_BASE = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/mosmix-data/data/mosmix/";
  const MAP_BASE = "./data/mosmix/";
  const DETAIL_BASE = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/mosmix-data/data/mosmix/stations/";
  const STATES_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json";
  const TAB_ID = "mosmix";

  let data = null;
  let map = null;
  let markerLayer = null;
  let sliderIndex = 0;
  let playTimer = null;
  let loaded = false;
  let mapMode = "hourly";
  let extremaFrames = [];
  let statesGeo = null;
  let selectedStationKey = null;
  let meteogramCharts = [];
  let currentDetail = null;
  let comparePreviousRun = false;
  let selectedStation = null;
  let rainPeriod = "1";
  let gustPeriod = "1";
  const RAIN_PERIODS = {"1":"RR1c","3":"RR3c","6":"RR6c","12":"RRhc","24":"RRdc"};
  const GUST_PERIODS = {"1":"FX1","3":"FX3","12":"FXh"};
  const MAP_VARIANTS = {
    rain:[["rain1","1 Stunde"],["rain3","3 Stunden"],["rain6","6 Stunden"],["rain12","12 Stunden"],["rain24","24 Stunden (gleitend)"],["rainDay","Kalendertag (Summe RR1c)"]],
    gust:[["gust1","1 Stunde"],["gust3","3 Stunden"],["gust12","12 Stunden"],["gustDay","Kalendertag (Maximum FX1)"]],
    cloud:[["cloudN","Gesamt"],["cloudNeff","Effektiv"],["cloudNl","Tief"],["cloudNm","Mittel"],["cloudNh","Hoch"]]
  };
  let mapVariant = "rain1";
  let mapRequestSequence = 0;
  const mapChunkCache = new Map();
  const detailCache = new Map();

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function(ch) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch];
    });
  }

  function fmtTime(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return new Intl.DateTimeFormat("de-DE", {
      timeZone: "Europe/Berlin",
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    }).format(d) + " Uhr";
  }

  function colorForTemp(t) {
    if (!Number.isFinite(t)) return "#9ca3af";
    const stops = [
      [-25,"#4b0082"],[-15,"#335dff"],[-10,"#2b8cbe"],[-5,"#41b6c4"],
      [0,"#7fcdbb"],[5,"#c7e9b4"],[10,"#ffffbf"],[15,"#fed976"],
      [20,"#fd8d3c"],[25,"#f03b20"],[30,"#bd0026"],[35,"#7f0000"]
    ];
    let best = stops[0][1];
    for (const stop of stops) {
      if (t >= stop[0]) best = stop[1];
      else break;
    }
    return best;
  }

  function colorForSun(value) {
    if (!Number.isFinite(value)) return "#9ca3af";
    const t=Math.max(0,Math.min(24,value));
    // Daily sunshine hours: continuous palette from overcast to long sunshine.
    const stops=[[0,"#94a3b8"],[1,"#c2dce3"],[2,"#b8e1d4"],[4,"#f7e8a0"],
      [6,"#fbd16a"],[8,"#f6a63a"],[10,"#ea732f"],[12,"#d9542e"],
      [16,"#b13a4a"],[24,"#772260"]];
    let a=stops[0],b=stops[stops.length-1];
    for(let i=0;i<stops.length-1;i++){
      if(t<=stops[i+1][0]){a=stops[i];b=stops[i+1];break;}
    }
    const fraction=(t-a[0])/(b[0]-a[0]||1);
    const mix=(idx)=>Math.round(
      parseInt(a[1].slice(idx,idx+2),16)*(1-fraction)+
      parseInt(b[1].slice(idx,idx+2),16)*fraction).toString(16).padStart(2,"0");
    return "#"+mix(1)+mix(3)+mix(5);
  }

  function textColor(bg) {
    const hex = bg.replace("#","");
    const r = parseInt(hex.slice(0,2),16);
    const g = parseInt(hex.slice(2,4),16);
    const b = parseInt(hex.slice(4,6),16);
    return (0.299*r + 0.587*g + 0.114*b) > 160 ? "#111827" : "#ffffff";
  }

  function addCss() {
    if (document.getElementById("mosmix-style")) return;
    const style = document.createElement("style");
    style.id = "mosmix-style";
    style.textContent = [
      ".mosmix-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}",
      ".mosmix-card{background:#fff;border:1px solid var(--border);border-radius:9px;box-shadow:var(--shadow);padding:16px}",
      ".mosmix-controls{display:flex;flex-wrap:wrap;gap:12px;align-items:end}.mosmix-mode-group{flex:0 0 auto}.mosmix-slider-wrap{flex:1 1 260px}",
      ".mosmix-mode-group{display:flex;flex-wrap:wrap;border:1px solid #cbd5df;border-radius:8px;overflow:hidden;background:#fff}",
      ".mosmix-mode-button{appearance:none;border:0;border-right:1px solid #dbe2e8;background:#fff;color:#334155;padding:9px 12px;font-weight:750;cursor:pointer;white-space:nowrap}",
      ".mosmix-mode-button:last-child{border-right:0}",
      ".mosmix-mode-button.active{background:#10213d;color:#fff}",
      ".mosmix-map-variant{display:flex;gap:8px;align-items:center;color:#475569;font-size:12px;font-weight:700}",
      ".mosmix-map-variant select{padding:8px;border:1px solid #cbd5df;background:#fff;color:#172033;border-radius:7px}",
      ".mosmix-map-variant[hidden]{display:none!important}",
      ".mosmix-download-button{background:#10213d;color:#fff;border-color:#10213d}",
      ".mosmix-slider-wrap label{display:flex;justify-content:space-between;gap:12px;font-size:13px;font-weight:700;color:#334155;margin-bottom:7px}",
      ".mosmix-slider{width:100%}",
      ".mosmix-button{appearance:none;border:1px solid #cbd5df;border-radius:7px;background:#fff;color:#172033;padding:9px 13px;font-weight:700;cursor:pointer}",
      ".mosmix-button:hover{background:#f5f8fa}",
      ".mosmix-map{height:650px;border:1px solid #d5dde4;border-radius:9px;overflow:hidden;background:#eef2f5}",
      ".mosmix-map .leaflet-control-attribution{font-size:9px}",
      ".mosmix-topline{display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px;margin-bottom:12px}",
      ".mosmix-topline-actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:10px}",
      ".mosmix-topline-actions .mosmix-button{padding:6px 10px;font-size:12px}",
      ".mosmix-status{font-size:13px;color:#475569}.mosmix-status strong{color:#0f172a}",
      ".mosmix-legend{display:flex;flex-wrap:wrap;gap:5px 9px;align-items:center;margin-top:11px;font-size:11px;color:#64748b}",
      ".mosmix-legend span{display:inline-flex;align-items:center;gap:4px}.mosmix-legend i{display:inline-block;width:18px;height:10px;border:1px solid rgba(0,0,0,.16);border-radius:2px}",
      ".mosmix-note{margin:10px 0 0;color:#64748b;font-size:12px;line-height:1.5}",
      ".mosmix-point-label{background:transparent!important;border:0!important}",
      ".mosmix-point-label>div{min-width:34px;padding:3px 5px;border:1px solid rgba(0,0,0,.35);border-radius:5px;font-size:11px;font-weight:800;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.22)}",
      ".mosmix-meteogram-card h3{margin:0 0 4px;font-size:20px}.mosmix-meteogram-card p{margin:0}",
      ".mosmix-meteogram-head{display:flex;flex-wrap:wrap;justify-content:space-between;gap:14px;align-items:flex-end;margin-bottom:12px}",
      ".mosmix-station-search{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.mosmix-station-search input{min-width:280px;padding:9px 10px;border:1px solid #bcc6cf;border-radius:7px;font:inherit}",
      ".mosmix-meteogram-status{margin:0 0 12px;padding:10px 12px;border-radius:7px;background:#f5f8fa;border:1px solid #dde4e9;color:#475569;font-size:12px}",
      ".mosmix-meteogram-actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:8px;margin:0 0 12px}",
      ".mosmix-chart-toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:8px 0 12px;font-size:12px;color:#475569}",
      ".mosmix-chart-toolbar select{padding:6px 8px;border:1px solid #cbd5df;border-radius:6px}",
      ".mosmix-chart-toolbar label{display:flex;gap:5px;align-items:center}",
      ".mosmix-meteogram-actions .mosmix-button{font-size:12px;padding:7px 11px}",
      ".mosmix-button:disabled,.mosmix-period-button:disabled{opacity:.42;cursor:not-allowed}",
      ".mosmix-period-head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px;margin-bottom:7px}",
      ".mosmix-period-head h4{margin:0!important}",
      ".mosmix-period-group{display:flex;flex-wrap:wrap;gap:3px;align-items:center}",
      ".mosmix-period-button{border:1px solid #cbd5df;border-radius:5px;background:#fff;color:#334155;font-size:11px;font-weight:700;line-height:1.2;padding:5px 7px;cursor:pointer}",
      ".mosmix-period-button.active{background:#10213d;color:#fff;border-color:#10213d}",
      ".mosmix-period-hint{font-size:10px;color:#64748b;margin:0 0 4px}",
      ".mosmix-export-status{font-size:11px;color:#475569;margin-right:auto}",
      ".mosmix-chart-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}",
      ".mosmix-chart-card.mosmix-chart-wide{grid-column:1/-1}",
      ".mosmix-chart-wrap.mosmix-chart-short{height:230px}",
      ".mosmix-chart-card{min-width:0;border:1px solid #dce3e8;border-radius:8px;padding:10px 12px;background:#fff}.mosmix-chart-card h4{margin:0 0 7px;font-size:13px;color:#334155}",
      ".mosmix-chart-wrap{position:relative;height:280px}.mosmix-chart-wrap canvas{width:100%!important;height:100%!important}",
      "@media(max-width:900px){.mosmix-chart-grid{grid-template-columns:1fr}.mosmix-station-search{width:100%}.mosmix-station-search input{min-width:0;flex:1}}",
      "@media(max-width:1050px){.mosmix-controls{grid-template-columns:1fr 1fr 1fr}.mosmix-mode-group,.mosmix-slider-wrap{grid-column:1/-1}}",
      "@media(max-width:800px){.mosmix-controls{grid-template-columns:1fr 1fr}.mosmix-mode-group,.mosmix-slider-wrap{grid-column:1/-1}.mosmix-map{height:540px}.mosmix-chart-wrap{height:250px}.mosmix-download-button{grid-column:1/-1}}" 
    ].join("");
    document.head.appendChild(style);
  }

  function sectionHtml() {
    return [
      '<div id="mosmix" class="tab-content">',
      '<div class="section-header">',
      '<h2>DWD MOSMIX – Vorhersagekarte</h2>',
      '<p>MOSMIX-L Punktvorhersagen: stündliche 2-m-Temperatur (TTT), originales 12-h-Maximum TX (18 UTC), Minimum TN (06 UTC) und Tagessonnenschein (SunD1).</p>',
      '<div class="section-status" id="mosmixSectionStatus">Daten werden geladen …</div>',
      '</div>',
      '<div class="mosmix-grid">',
      '<div class="mosmix-card">',
      '<div class="mosmix-topline"><div class="mosmix-status" id="mosmixRunInfo">MOSMIX-L wird geladen …</div><div class="mosmix-topline-actions"><div class="mosmix-status" id="mosmixValidInfo"></div><button class="mosmix-button" id="mosmixReload" type="button" title="Aktuellsten DWD MOSMIX-L Lauf vom Datenserver laden">Neuen Lauf laden ↻</button></div></div>',
      '<div class="mosmix-controls">',
      '<div class="mosmix-mode-group"><button class="mosmix-mode-button active" data-mosmix-mode="hourly" type="button">Stündlich</button><button class="mosmix-mode-button" data-mosmix-mode="tmax" type="button" title="MOSMIX TX: Maximum der letzten 12 Stunden bis 18 UTC">Tmax (12 h)</button><button class="mosmix-mode-button" data-mosmix-mode="tmin" type="button" title="MOSMIX TN: Minimum der letzten 12 Stunden bis 06 UTC">Tmin (12 h)</button><button class="mosmix-mode-button" data-mosmix-mode="sun" type="button" title="SunD1-Summe pro vollständigem Kalendertag (Ortszeit Deutschland)">Sonne (Tag)</button><button class="mosmix-mode-button" data-mosmix-mode="rain" type="button">Niederschlag</button><button class="mosmix-mode-button" data-mosmix-mode="gust" type="button">Böen</button><button class="mosmix-mode-button" data-mosmix-mode="cloud" type="button">Wolken</button></div><label class="mosmix-map-variant" id="mosmixMapVariantWrap" hidden>Zeitraum / Höhe <select id="mosmixMapVariant"></select></label>',
      '<div class="mosmix-slider-wrap"><label><span id="mosmixSliderTitle">Vorhersagezeitpunkt</span><strong id="mosmixSliderLabel">–</strong></label><input id="mosmixSlider" class="mosmix-slider" type="range" min="0" max="0" step="1" value="0"></div>',
      '<button id="mosmixPlay" class="mosmix-button" type="button">▶ Animation</button>',
      '<button id="mosmixNow" class="mosmix-button" type="button">Nächster Termin</button>',
      '<button id="mosmixAreaDownload" class="mosmix-button mosmix-download-button" type="button">⬇ Flächenkarte PNG</button>',
      '</div></div>',
      '<div class="mosmix-card">',
      '<div id="mosmixMap" class="mosmix-map"></div>',
      '<div id="mosmixLegend" class="mosmix-legend"></div>',
      '<p class="mosmix-note">Quelle: Deutscher Wetterdienst (DWD), MOSMIX-L. Stündlich = TTT (2 m), Tmax = originales TX der letzten 12 Stunden bis 18 UTC (20 Uhr MESZ), Tmin = originales TN bis 06 UTC (08 Uhr MESZ). Im Kartenexport wird eine Interpolation ausdrücklich gekennzeichnet. Für Sonne (Tag) werden SunD1-Stundenwerte vollständiger lokaler Kalendertage (00–24 Uhr Europe/Berlin) addiert. Unvollständige Tage oder Stationswerte bleiben ausgeblendet. DWD weist auf Ungenauigkeiten von SunD1 nahe Sonnenauf- und -untergang hin. Die Stationsauswahl und der Modelllauf können sich von Metmaps unterscheiden.</p>',
      '</div>',
      '<div class="mosmix-card mosmix-meteogram-card">',
      '<div class="mosmix-meteogram-head">',
      '<div><h3>MOSMIX-Meteogramm</h3><p class="mosmix-note">Station suchen oder einen Punkt in der Karte anklicken.</p></div>',
      '<div class="mosmix-station-search"><input id="mosmixStationSearch" list="mosmixStationList" type="search" placeholder="z. B. Frankfurt, Saarbrücken …" autocomplete="off"><datalist id="mosmixStationList"></datalist><button id="mosmixStationButton" class="mosmix-button" type="button">Diagramm anzeigen</button></div>',
      '</div>',
      '<div id="mosmixMeteogramStatus" class="mosmix-meteogram-status">Noch keine Station ausgewählt.</div>',
      '<div class="mosmix-chart-toolbar"><label>Diagrammzeitraum <select id="mosmixDiagramRange"><option value="all">Alle Tage</option><option value="72">Ab jetzt · 3 Tage</option><option value="120">Ab jetzt · 5 Tage</option></select></label><label><input type="checkbox" id="mosmixComparePrevious" disabled> Vorherigen Lauf vergleichen (Temperatur, TX/TN)</label><span id="mosmixCompareStatus">Vorheriger Lauf noch nicht geladen</span></div>',
      '<div class="mosmix-meteogram-actions"><span class="mosmix-export-status" id="mosmixExportStatus" role="status">Export für ausgewählte Station</span><button class="mosmix-button" id="mosmixDiagramPng" type="button" disabled>⬇ Alle Diagramme PNG</button><button class="mosmix-button" id="mosmixDiagramPdf" type="button" disabled>⬇ Alle Diagramme PDF</button></div>',
      '<div class="mosmix-chart-grid">',
      '<div class="mosmix-chart-card"><h4>Temperatur &amp; Taupunkt</h4><div class="mosmix-chart-wrap"><canvas id="mosmixTempChart"></canvas></div></div>',
      '<div class="mosmix-chart-card"><div class="mosmix-period-head"><h4>Niederschlag &amp; Bewölkung</h4><div class="mosmix-period-group" role="group" aria-label="Niederschlagssumme Zeitraum"><button class="mosmix-period-button active" data-mosmix-period="rain" data-hours="1" type="button">1 h</button><button class="mosmix-period-button" data-mosmix-period="rain" data-hours="3" type="button">3 h</button><button class="mosmix-period-button" data-mosmix-period="rain" data-hours="6" type="button">6 h</button><button class="mosmix-period-button" data-mosmix-period="rain" data-hours="12" type="button">12 h</button><button class="mosmix-period-button" data-mosmix-period="rain" data-hours="24" type="button">24 h</button></div></div><div class="mosmix-period-hint" id="mosmixRainPeriodInfo">DWD-Niederschlagssumme der letzten 1 Stunde</div><div class="mosmix-chart-wrap"><canvas id="mosmixRainChart"></canvas></div></div>',
      '<div class="mosmix-chart-card"><div class="mosmix-period-head"><h4>Wind &amp; Böen</h4><div class="mosmix-period-group" role="group" aria-label="Windböen Maximum Zeitraum"><button class="mosmix-period-button active" data-mosmix-period="gust" data-hours="1" type="button">1 h</button><button class="mosmix-period-button" data-mosmix-period="gust" data-hours="3" type="button">3 h</button><button class="mosmix-period-button" data-mosmix-period="gust" data-hours="12" type="button">12 h</button></div></div><div class="mosmix-period-hint" id="mosmixGustPeriodInfo">Maximale DWD-Windböe der letzten 1 Stunde</div><div class="mosmix-chart-wrap"><canvas id="mosmixWindChart"></canvas></div></div>',
      '<div class="mosmix-chart-card"><h4>Luftdruck</h4><div class="mosmix-chart-wrap"><canvas id="mosmixPressureChart"></canvas></div></div>',
      '<div class="mosmix-chart-card"><h4>Sonnenschein pro Stunde &amp; Globalstrahlung</h4><div class="mosmix-period-hint">SunD1-Stundenbalken (Minuten), gleitende 24-h-Summe (Stunden) und optionale Globalstrahlung.</div><div class="mosmix-chart-wrap"><canvas id="mosmixSunChart"></canvas></div></div>',
      '<div class="mosmix-chart-card mosmix-chart-wide"><h4>Sonnenscheindauer pro Tag</h4><div class="mosmix-period-hint">Balken in Stunden für vollständige Kalendertage (00–24 Uhr Europe/Berlin). Unvollständige Prognosetage und fehlende Werte werden nicht als Null dargestellt.</div><div class="mosmix-chart-wrap mosmix-chart-short"><canvas id="mosmixSunDailyChart"></canvas></div></div>',
      '</div>',
      '<p class="mosmix-note">TTT zeigt stündliche 2-m-Temperaturwerte. TX/TN sind eigenständige 12-h-Extremprognosen. Niederschlag: originale DWD-Summen, Böen: originale DWD-Maxima (jeweils rückblickender Zeitraum bis zum Gültigkeitstermin). Wind in km/h, Niederschlag in mm. Ausgegraute Zeiträume sind im geladenen Lauf nicht verfügbar.</p>',
      '</div></div></div>'
    ].join("");
  }

  function addNavigation() {
    if (document.querySelector('[data-mosmix-nav="1"]')) return;

    const menu = document.querySelector('.nav-dropdown[data-nav-group="germany"] .nav-dropdown-menu');
    if (menu) {
      const divider = document.createElement("div");
      divider.className = "nav-menu-divider";
      divider.dataset.mosmixNav = "1";

      const heading = document.createElement("div");
      heading.className = "nav-menu-heading";
      heading.textContent = "Vorhersage";

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tab-button";
      btn.dataset.navGroup = "germany";
      btn.dataset.mosmixNav = "1";
      btn.textContent = "DWD MOSMIX";
      btn.setAttribute("onclick", "switchTab('mosmix')");
      btn.addEventListener("click", function(){ setTimeout(init,0); });

      menu.appendChild(divider);
      menu.appendChild(heading);
      menu.appendChild(btn);
    }

    const mobile = document.querySelector(".mobile-tab-navigation select");
    if (mobile && !mobile.querySelector('option[value="mosmix"]')) {
      const opt = document.createElement("option");
      opt.value = TAB_ID;
      opt.textContent = "DWD MOSMIX";
      mobile.appendChild(opt);
      mobile.addEventListener("change", function() {
        if (mobile.value === TAB_ID) setTimeout(init, 0);
      });
    }
  }

  function addSection() {
    if (document.getElementById(TAB_ID)) return;
    const main = document.querySelector(".dashboard-main") || document.body;
    const footer = main.querySelector(".dashboard-footer");
    const wrapper = document.createElement("div");
    wrapper.innerHTML = sectionHtml();
    const node = wrapper.firstElementChild;
    if (footer) main.insertBefore(node, footer);
    else main.appendChild(node);
  }

  async function fetchMosmixSource(url, forceRefresh) {
    const controller = new AbortController();
    const timer = setTimeout(function(){controller.abort();},DATA_TIMEOUT_MS);
    try {
      // Raw GitHub already sends short-lived cache headers. Use browser cache
      // for normal entry; the explicit reload button bypasses that cache.
      const response = await fetch(url, {
        cache:forceRefresh?"no-store":"default",signal:controller.signal
      });
      if(!response.ok)throw new Error("HTTP "+response.status);
      let json;
      if(url===DATA_COMPRESSED_URL){
        if(typeof DecompressionStream==="undefined"||!response.body)
          throw new Error("Dieser Browser unterstützt keinen komprimierten Datenstream");
        const stream=response.body.pipeThrough(new DecompressionStream("gzip"));
        json=await new Response(stream).json();
      } else {
        json=await response.json();
      }
      if(!Array.isArray(json.timesteps)||!Array.isArray(json.stations)||
         !json.timesteps.length||!json.stations.length){
        throw new Error("Ungültiger oder leerer MOSMIX-Datensatz");
      }
      return json;
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadData(forceRefresh) {
    const status=document.getElementById("mosmixSectionStatus");
    // A few hundred KB of metadata, followed by just the chosen day's layer.
    // The data branch is the fallback if Pages has not yet been redeployed.
    for(const source of (forceRefresh?[MANIFEST_BACKUP_URL,MANIFEST_URL]:[MANIFEST_URL,MANIFEST_BACKUP_URL])){
      const remote=source===MANIFEST_BACKUP_URL;
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),9000);
      try {
        if(status)status.textContent="Lade kompakten MOSMIX-Katalog ("+
          (remote?"Datenserver":"Website")+") …";
        const response=await fetch(source,{
          cache:remote||forceRefresh?"no-store":"default",signal:controller.signal
        });
        if(!response.ok)continue;
        const manifest=await response.json();
        if(manifest.schema!==2||!Array.isArray(manifest.stations)||
           manifest.stations.length<=100||!Array.isArray(manifest.timesteps)||
           !manifest.modes?.hourly?.length)continue;
        manifest._split=true;
        manifest._mosmixSource=remote?"Datenserver (Tagespakete)":"Website (Tagespakete)";
        manifest._mapsBase=remote?MAP_BACKUP_BASE:MAP_BASE;
        return manifest;
      }catch(error){
        console.warn("MOSMIX Tageskatalog nicht erreichbar:",source,error);
      }finally{clearTimeout(timer);}
    }
    const endpoints=forceRefresh ? [DATA_URL,DATA_BACKUP_URL,DATA_COMPRESSED_URL,DATA_LOCAL_URL] :
      [DATA_COMPRESSED_URL,DATA_LOCAL_URL,DATA_URL,DATA_BACKUP_URL];
    const errors=[];
    for(let i=0;i<endpoints.length;i++){
      const url=endpoints[i];
      const name=url===DATA_COMPRESSED_URL?"Website (komprimiert)":
        url===DATA_LOCAL_URL?"Website":url===DATA_URL?"GitHub":"Ersatzquelle";
      if(status)status.textContent="Lade Deutschland-MOSMIX-Daten ("+name+") …";
      try {
        const result=await fetchMosmixSource(url,!!forceRefresh);
        result._mosmixFallback=url===DATA_BACKUP_URL;
        result._mosmixSource=name;
        return result;
      } catch(error) {
        errors.push(name+": "+
          (error.name==="AbortError"?"Zeitüberschreitung":error.message));
      }
    }
    throw new Error("Keine MOSMIX-Quelle erreichbar. "+errors.join("; "));
  }

  async function loadStates() {
    try {
      const response = await fetch(STATES_URL, {cache:"force-cache"});
      if (!response.ok) return;
      const geo = await response.json();
      statesGeo = geo;
      L.geoJSON(geo, {
        style: {color:"#55616d",weight:1,opacity:.85,fillOpacity:0}
      }).addTo(map);
    } catch (err) {
      console.warn("MOSMIX Bundesländergrenzen:", err);
    }
  }


  let leafletLoadPromise=null;

  function ensureLeaflet(){
    if(window.L)return Promise.resolve();
    if(leafletLoadPromise)return leafletLoadPromise;
    const status=document.getElementById("mosmixSectionStatus");
    if(status)status.textContent="MOSMIX-Daten vorhanden. Lade Kartenbibliothek über Ersatzserver …";
    leafletLoadPromise=new Promise(function(resolve,reject){
      const script=document.createElement("script");
      script.src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js";
      script.async=true;
      let done=false;
      let timer=null;
      function finish(error){
        if(done)return;
        done=true;
        clearTimeout(timer);
        script.onload=null;script.onerror=null;
        if(error)reject(error);
        else resolve();
      }
      timer=setTimeout(function(){
        finish(new Error("Kartenbibliothek nach 10 Sekunden nicht erreichbar. Bitte Netzwerk oder Skriptblocker prüfen."));
      },10000);
      script.onload=function(){
        if(window.L)finish();
        else finish(new Error("Kartenbibliothek wurde geladen, aber nicht initialisiert."));
      };
      script.onerror=function(){finish(new Error("Kartenbibliothek über beide Server nicht verfügbar."));};
      if(!document.getElementById("mosmix-leaflet-css-fallback")){
        const css=document.createElement("link");
        css.id="mosmix-leaflet-css-fallback";
        css.rel="stylesheet";
        css.href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(css);
      }
      document.head.appendChild(script);
    }).finally(function(){leafletLoadPromise=null;});
    return leafletLoadPromise;
  }

  // Standalone view does not load heavy chart/PDF libraries until needed.
  let chartLoadPromise=null;
  let pdfLoadPromise=null;
  function loadLibrary(url,label){
    return new Promise(function(resolve,reject){
      const script=document.createElement("script");
      script.src=url;script.async=true;
      let finished=false;
      const timer=setTimeout(function(){
        finish(new Error(label+" nach 12 Sekunden nicht erreichbar."));
      },12000);
      function finish(error){
        if(finished)return;
        finished=true;
        clearTimeout(timer);
        script.onload=null;script.onerror=null;
        if(error)reject(error);else resolve();
      }
      script.onload=function(){finish();};
      script.onerror=function(){finish(new Error(label+" konnte nicht geladen werden."));};
      document.head.appendChild(script);
    });
  }
  function ensureCharts(){
    if(window.Chart)return Promise.resolve();
    if(!chartLoadPromise)chartLoadPromise=loadLibrary(
      "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",
      "Chart.js").then(function(){
        if(!window.Chart)throw new Error("Chart.js konnte nicht initialisiert werden.");
      }).finally(function(){chartLoadPromise=null;});
    return chartLoadPromise;
  }
  function ensurePdfLibrary(){
    if(window.jspdf?.jsPDF)return Promise.resolve();
    if(!pdfLoadPromise)pdfLoadPromise=loadLibrary(
      "https://cdn.jsdelivr.net/npm/jspdf@4.2.1/dist/jspdf.umd.min.js",
      "PDF-Bibliothek").then(function(){
        if(!window.jspdf?.jsPDF)throw new Error("PDF-Bibliothek konnte nicht initialisiert werden.");
      }).finally(function(){pdfLoadPromise=null;});
    return pdfLoadPromise;
  }

  function makeMap() {
    if (map) return;
    map = L.map("mosmixMap", {
      center:[51.05,10.35],
      zoom:6,
      minZoom:2,
      maxZoom:11,
      preferCanvas:true
    });
    markerLayer = L.layerGroup().addTo(map);
    loadStates();
    setTimeout(function(){ map.invalidateSize(); }, 100);
  }

  function chooseInitialIndex() {
    const now = Date.now();
    let best = 0;
    for (let i=0; i<data.timesteps.length; i++) {
      if (new Date(data.timesteps[i]).getTime() >= now) {
        best = i;
        break;
      }
      best = i;
    }
    return best;
  }

  function mapKey(){
    return MAP_VARIANTS[mapMode] ? mapVariant : mapMode;
  }
  function mapUnit(){
    if(mapMode==="sun")return "h";
    if(mapMode==="rain")return "mm";
    if(mapMode==="gust")return "km/h";
    if(mapMode==="cloud")return "%";
    return "°C";
  }
  function colorForMap(value){
    if(mapMode==="sun")return colorForSun(value);
    if(mapMode==="rain"){
      const stops=[[0,"#e7edf3"],[0.1,"#b8e2f7"],[1,"#64b2e3"],[3,"#247bbf"],[8,"#135095"],[15,"#6937a7"],[30,"#a3276e"],[60,"#e83345"]];
      return thresholdColor(value,stops);
    }
    if(mapMode==="gust")return thresholdColor(value,[[0,"#b8d9cb"],[20,"#9dd5ae"],[40,"#f3e18e"],[60,"#edab46"],[80,"#eb6d31"],[100,"#c52d37"],[120,"#8a32a0"],[150,"#512566"]]);
    if(mapMode==="cloud")return thresholdColor(value,[[0,"#fcfcfd"],[10,"#eff1f4"],[25,"#d4d9df"],[50,"#a3acb6"],[75,"#687485"],[90,"#414d60"],[100,"#263244"]]);
    return colorForTemp(value);
  }
  function thresholdColor(value,stops){
    if(!Number.isFinite(value))return "#9ca3af";
    let color=stops[0][1];
    for(const [limit,next] of stops){if(value>=limit)color=next;else break;}
    return color;
  }
  function renderLegend() {
    const values=mapMode==="sun"?[0,1,2,4,6,8,10,12,16,24]:
      mapMode==="rain"?[0,.1,1,3,8,15,30,60]:
      mapMode==="gust"?[0,20,40,60,80,100,120,150]:
      mapMode==="cloud"?[0,10,25,50,75,90,100]:
      [-15,-10,-5,0,5,10,15,20,25,30,35];
    const unit=mapUnit();
    document.getElementById("mosmixLegend").innerHTML = values.map(function(v) {
      return '<span><i style="background:' + colorForMap(v) + '"></i>' + v + (unit==="°C"?"°":" "+unit) + '</span>';
    }).join("");
  }

  function popupHtml(station, value, valid, kind) {
    const daily=MAP_VARIANTS[kind]&&mapVariant.endsWith("Day");
    const label=kind==="rain" ? (daily?"Tagesniederschlag · Summe RR1c":"Niederschlag · Originalintervall") :
      kind==="gust" ? (daily?"Tagesmaximalböe · Maximum FX1":"Maximalböe · Originalintervall") :
      kind==="cloud" ? "Bedeckungsgrad · Modellzeitpunkt" :
      kind==="tmax" ? "TX · Maximum der letzten 12 h" :
      kind==="tmin" ? "TN · Minimum der letzten 12 h" :
      kind==="sun" ? "SunD1 · Sonnenscheindauer am Kalendertag" : "TTT · Temperatur 2 m";
    return '<strong>' + esc(station.name) + '</strong><br>' +
      'MOSMIX-ID: ' + esc(station.id) + '<br>' +
      esc(label)+': <strong>' + value.toFixed(1).replace(".", ",") + ' '+esc(kind==="rain"?"mm":kind==="gust"?"km/h":kind==="cloud"?"%":kind==="sun"?"h":"°C")+'</strong><br>' +
      (kind==="sun"||daily ? 'Kalendertag: '+esc(valid) : 'Gültig: '+esc(fmtTime(valid)));
  }


  function stationDisplay(station) {
    return station.name + " (" + station.id + ")";
  }

  function populateStationSearch() {
    const list = document.getElementById("mosmixStationList");
    if (!list || !data) return;
    list.innerHTML = "";
    const frag = document.createDocumentFragment();
    data.stations.forEach(function(station) {
      const option = document.createElement("option");
      option.value = stationDisplay(station);
      frag.appendChild(option);
    });
    list.appendChild(frag);
  }

  function findStation(query) {
    const q = String(query || "").trim().toLocaleLowerCase("de-DE");
    if (!q || !data) return null;

    let station = data.stations.find(function(s) {
      return stationDisplay(s).toLocaleLowerCase("de-DE") === q;
    });
    if (station) return station;

    station = data.stations.find(function(s) {
      return String(s.id).toLocaleLowerCase("de-DE") === q ||
        String(s.name).toLocaleLowerCase("de-DE") === q;
    });
    if (station) return station;

    return data.stations.find(function(s) {
      return String(s.name).toLocaleLowerCase("de-DE").includes(q) ||
        String(s.id).toLocaleLowerCase("de-DE").includes(q);
    }) || null;
  }

  function rollingSunshine24h(values){
    if(!Array.isArray(values))return [];
    return values.map(function(_v,i){
      if(i<23)return null;
      const window=values.slice(i-23,i+1);
      if(window.length!==24||window.some(v=>!Number.isFinite(v)))return null;
      return Math.round(window.reduce((a,b)=>a+b,0)/60*10)/10;
    });
  }

  // A SunD1 sample represents the preceding hour. Midnight hour-end
  // belongs to the previous day; UTC elapsed time handles DST 23/25h days.
  function sunDayFramesFromTimesteps(timesteps) {
    const days=new Map();
    (timesteps||[]).forEach(function(iso,index){
      const end=Date.parse(iso);
      if(!Number.isFinite(end))return;
      const parts=berlinDateParts(new Date(end-1).toISOString());
      if(!parts)return;
      const key=dateKey(parts.year,parts.month,parts.day,0);
      if(!days.has(key))days.set(key,[]);
      days.get(key).push({index:index,end:end});
    });
    return [...days].map(function(entry){
      const key=entry[0],rows=entry[1];
      const first=rows[0].end,last=rows[rows.length-1].end;
      const begin=berlinDateParts(new Date(first-3600000).toISOString());
      const finish=berlinDateParts(new Date(last).toISOString());
      if(!begin||!finish||begin.hour!==0||finish.hour!==0||
         dateKey(begin.year,begin.month,begin.day,0)!==key||
         dateKey(finish.year,finish.month,finish.day,0)!==dateKey(begin.year,begin.month,begin.day,1)||
         rows.some(function(row,i){return i>0&&row.end-rows[i-1].end!==3600000;}))return null;
      const label=new Intl.DateTimeFormat("de-DE",{
        timeZone:"UTC",weekday:"short",day:"2-digit",month:"2-digit",year:"numeric"
      }).format(new Date(key+"T12:00:00Z"));
      return {key:key,label:label,indices:rows.map(row=>row.index),kind:"sunDay"};
    }).filter(Boolean);
  }

  function sunDayValue(values,frame) {
    if(!Array.isArray(values)||!frame||!Array.isArray(frame.indices))return null;
    let minutes=0;
    for(const index of frame.indices){
      const value=values[index];
      if(!Number.isFinite(value)||value<0||value>60)return null;
      minutes+=value;
    }
    return Math.round(minutes/60*10)/10;
  }

  function buildSunFrames(){
    return sunDayFramesFromTimesteps(data.timesteps).map(function(frame){
      frame.valuesByKey=new Map();
      data.stations.forEach(function(station){
        const value=sunDayValue(station.sun1,frame);
        if(value!==null)frame.valuesByKey.set(station.key,value);
      });
      return frame;
    }).filter(frame=>frame.valuesByKey.size>0);
  }

  function destroyMeteogramCharts() {
    meteogramCharts.forEach(function(chart) {
      try { chart.destroy(); } catch (_) {}
    });
    meteogramCharts = [];
  }

  function meteogramLabels() {
    return data.timesteps.map(function(iso) {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return iso;
      const weekday = new Intl.DateTimeFormat("de-DE", {
        timeZone:"Europe/Berlin", weekday:"short"
      }).format(d);
      const date = new Intl.DateTimeFormat("de-DE", {
        timeZone:"Europe/Berlin", day:"2-digit", month:"2-digit"
      }).format(d);
      const hour = new Intl.DateTimeFormat("de-DE", {
        timeZone:"Europe/Berlin", hour:"2-digit", hour12:false
      }).format(d);
      return weekday + " " + date + " " + hour + " Uhr";
    });
  }

  function compass(deg) {
    if (!Number.isFinite(deg)) return "";
    const dirs = ["N","NO","O","SO","S","SW","W","NW"];
    return dirs[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
  }

  function berlinDateParts(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone:"Europe/Berlin",
      year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",hour12:false
    }).formatToParts(d);
    const get = function(type) {
      const hit = parts.find(function(part){ return part.type === type; });
      return hit ? hit.value : "";
    };
    return {
      year:Number(get("year")),
      month:Number(get("month")),
      day:Number(get("day")),
      hour:Number(get("hour"))
    };
  }

  function dateKey(year,month,day,addDays) {
    const d = new Date(Date.UTC(year, month - 1, day + (addDays || 0), 12));
    return [
      d.getUTCFullYear(),
      String(d.getUTCMonth() + 1).padStart(2,"0"),
      String(d.getUTCDate()).padStart(2,"0")
    ].join("-");
  }

  const mosmixAxisCache = new Map();

  function mosmixAxisTime(index) {
    const iso = data && data.timesteps && data.timesteps[index];
    if (!iso) return null;
    if (mosmixAxisCache.has(iso)) return mosmixAxisCache.get(iso);
    const parts = berlinDateParts(iso);
    if (!parts) return null;
    const weekday = new Intl.DateTimeFormat("de-DE", {
      timeZone:"Europe/Berlin",weekday:"short"
    }).format(new Date(iso)).replace(/\.$/, "");
    const day = String(parts.day).padStart(2,"0");
    const month = String(parts.month).padStart(2,"0");
    const result = {hour:parts.hour,dayLabel:weekday+" "+day+"."+month+"."};
    mosmixAxisCache.set(iso,result);
    return result;
  }

  function baseChartOptions(yTitle) {
    return {
      responsive:true,
      maintainAspectRatio:false,
      animation:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        legend:{display:true,labels:{boxWidth:18,usePointStyle:true}},
        tooltip:{enabled:true},
        datalabels:{display:false}
      },
      scales:{
        x:{
          ticks:{
            autoSkip:false,maxRotation:0,minRotation:0,padding:8,
            font:{size:11},
            callback:function(value,index) {
              const t = mosmixAxisTime(index);
              if (!t) return "";
              // Show the date once per day, and 00/12 local time only.
              if (t.hour === 0) return [t.dayLabel,"00 Uhr"];
              if (t.hour === 12 && window.innerWidth >= 700 &&
                  data.timesteps.length <= 120) return "12 Uhr";
              return "";
            }
          },
          grid:{
            drawTicks:true,
            color:function(ctx) {
              const t = mosmixAxisTime(ctx.index);
              return t && t.hour === 0 ? "rgba(100,116,139,.38)" :
                t && t.hour === 12 ? "rgba(148,163,184,.16)" : "rgba(0,0,0,0)";
            },
            lineWidth:function(ctx) {
              const t = mosmixAxisTime(ctx.index);
              return t && t.hour === 0 ? 1.5 : 0.8;
            }
          }
        },
        y:{title:{display:true,text:yTitle}}
      }
    };
  }

  function hasMeteogramValues(detail, param) {
    const values = detail && detail.parameters && detail.parameters[param];
    return Array.isArray(values) && values.some(Number.isFinite);
  }

  function syncMeteogramPeriods(detail) {
    if (!hasMeteogramValues(detail, RAIN_PERIODS[rainPeriod])) {
      rainPeriod = Object.keys(RAIN_PERIODS).find(function(h){ return hasMeteogramValues(detail, RAIN_PERIODS[h]); }) || "1";
    }
    if (!hasMeteogramValues(detail, GUST_PERIODS[gustPeriod])) {
      gustPeriod = Object.keys(GUST_PERIODS).find(function(h){ return hasMeteogramValues(detail, GUST_PERIODS[h]); }) || "1";
    }
    document.querySelectorAll("[data-mosmix-period]").forEach(function(button) {
      const isRain = button.dataset.mosmixPeriod === "rain";
      const selected = isRain ? rainPeriod : gustPeriod;
      const field = (isRain ? RAIN_PERIODS : GUST_PERIODS)[button.dataset.hours];
      button.disabled = !hasMeteogramValues(detail, field);
      button.classList.toggle("active",button.dataset.hours===selected);
      button.setAttribute("aria-pressed",String(button.dataset.hours===selected));
      button.title = button.disabled ? "Für diese Station bzw. diesen MOSMIX-Lauf nicht verfügbar" : "";
    });
    const rainInfo = document.getElementById("mosmixRainPeriodInfo");
    if (rainInfo) rainInfo.textContent = "DWD-Niederschlagssumme, letzte "+rainPeriod+" h · "+RAIN_PERIODS[rainPeriod];
    const gustInfo = document.getElementById("mosmixGustPeriodInfo");
    if (gustInfo) gustInfo.textContent = "Maximale DWD-Windböe, letzte "+gustPeriod+" h · "+GUST_PERIODS[gustPeriod];
  }

  function selectMeteogramPeriod(kind, hours) {
    if (!currentDetail) return;
    const fields = kind === "rain" ? RAIN_PERIODS : kind === "gust" ? GUST_PERIODS : null;
    if (!fields || !fields[hours] || !hasMeteogramValues(currentDetail, fields[hours])) return;
    if (kind === "rain") rainPeriod = hours;
    else gustPeriod = hours;
    syncMeteogramPeriods(currentDetail);
    const chart = meteogramCharts[kind === "rain" ? 1 : 2];
    if (!chart) return;
    const ds = chart.data.datasets[kind === "rain" ? 0 : 1];
    ds.data = currentDetail.parameters[fields[hours]];
    ds.label = kind === "rain" ? hours+"-h-Niederschlagssumme" : hours+"-h-Maximalböe";
    chart.update("none");
  }

  function createMeteogram(detail) {
    if (!window.Chart) throw new Error("Chart.js ist nicht verfügbar.");
    destroyMeteogramCharts();

    currentDetail = detail;
    syncMeteogramPeriods(detail);
    const p = detail.parameters || {};
    const labels = meteogramLabels();
    const commonLine = {pointRadius:0,pointHoverRadius:3,borderWidth:2,tension:.18,spanGaps:true};

    const officialTX=(p.TX||[]).map(function(v,i){
      return new Date(data.timesteps[i]).getUTCHours()===18 && Number.isFinite(v) ? v : null;
    });
    const officialTN=(p.TN||[]).map(function(v,i){
      return new Date(data.timesteps[i]).getUTCHours()===6 && Number.isFinite(v) ? v : null;
    });
    const previous=detail.previous;
    const validPrevious=previous&&previous.issue_time!==data.issue_time&&
      Array.isArray(previous.timesteps)&&Array.isArray(previous.TTT);
    const beforeIndex=validPrevious?new Map(previous.timesteps.map((iso,i)=>[iso,i])):null;
    const previousSeries=function(field){
      if(!validPrevious)return [];
      return data.timesteps.map(function(iso){
        const index=beforeIndex.get(iso);
        if(index===undefined)return null;
        const value=field==="TTT"?previous.TTT[index]:
          (previous[field]||{})[String(index)];
        return Number.isFinite(value)?value:null;
      });
    };
    const tempOptions = baseChartOptions("°C");
    tempOptions.plugins.datalabels = {
      display:function(context){
        return (context.datasetIndex===2||context.datasetIndex===3) &&
          Number.isFinite(context.dataset.data[context.dataIndex]);
      },
      formatter:function(value,context){
        return (context.datasetIndex===2?"TX ":"TN ")+
          value.toFixed(1).replace(".",",")+" °C";
      },
      anchor:"end",
      align:function(context){return context.datasetIndex===2?"top":"bottom";},
      offset:4,clamp:true,clip:false,
      color:function(context){return context.datasetIndex===2?"#a5271f":"#1f5f99";},
      backgroundColor:"rgba(255,255,255,.9)",
      borderColor:"rgba(100,116,139,.25)",
      borderWidth:1,borderRadius:4,
      padding:{top:3,right:5,bottom:3,left:5},font:{size:10,weight:"700"}
    };

    meteogramCharts.push(new Chart(document.getElementById("mosmixTempChart"), {
      type:"line",
      data:{labels:labels,datasets:[
        Object.assign({},commonLine,{
          label:"Temperatur",
          data:p.TTT || [],
          borderColor:"#c62828",
          backgroundColor:"rgba(198,40,40,.08)",
          pointRadius:0,
          pointHoverRadius:4
        }),
        Object.assign({label:"Taupunkt",data:p.Td || [],borderColor:"#1769c2",backgroundColor:"rgba(23,105,194,.08)"},commonLine),
        {label:"TX 12 h · 18 UTC",data:officialTX,showLine:false,pointRadius:3.5,
         pointHoverRadius:5,pointStyle:"triangle",borderColor:"#a5271f",backgroundColor:"#a5271f"},
        {label:"TN 12 h · 06 UTC",data:officialTN,showLine:false,pointRadius:3.5,
         pointHoverRadius:5,pointStyle:"rectRot",borderColor:"#1f5f99",backgroundColor:"#1f5f99"},
        Object.assign({label:"Vorheriger Lauf · Temperatur",data:previousSeries("TTT"),
         borderColor:"#a45e5e",borderDash:[6,4],pointRadius:0,
         hidden:!comparePreviousRun||!validPrevious},commonLine),
        {label:"Vorheriger Lauf · TX",data:previousSeries("TX"),showLine:false,
         pointRadius:3,pointStyle:"triangle",borderColor:"#ad6c62",backgroundColor:"#ad6c62",
         hidden:!comparePreviousRun||!validPrevious},
        {label:"Vorheriger Lauf · TN",data:previousSeries("TN"),showLine:false,
         pointRadius:3,pointStyle:"rectRot",borderColor:"#688ba8",backgroundColor:"#688ba8",
         hidden:!comparePreviousRun||!validPrevious}
      ]},
      options:tempOptions
    }));

    const rainOptions = baseChartOptions("mm");
    rainOptions.scales.y.beginAtZero = true;
    rainOptions.scales.yCloud = {
      position:"right",min:0,max:100,
      title:{display:true,text:"Bewölkung (%)"},
      grid:{drawOnChartArea:false}
    };
    meteogramCharts.push(new Chart(document.getElementById("mosmixRainChart"), {
      data:{labels:labels,datasets:[
        {type:"bar",label:rainPeriod+"-h-Niederschlagssumme",data:p[RAIN_PERIODS[rainPeriod]] || [],yAxisID:"y",backgroundColor:"rgba(23,105,194,.58)",borderWidth:0,barPercentage:.9,categoryPercentage:1},
        Object.assign({type:"line",label:"Bewölkung",data:p.N || [],yAxisID:"yCloud",borderColor:"#64748b",backgroundColor:"rgba(100,116,139,.06)"},commonLine)
      ]},
      options:rainOptions
    }));

    const windOptions = baseChartOptions("km/h");
    windOptions.scales.y.beginAtZero = true;
    windOptions.plugins.tooltip.callbacks = {
      afterBody:function(items) {
        if (!items || !items.length) return "";
        const i = items[0].dataIndex;
        const dd = p.DD && p.DD[i];
        return Number.isFinite(dd) ? "Windrichtung: " + Math.round(dd) + "° (" + compass(dd) + ")" : "";
      }
    };
    meteogramCharts.push(new Chart(document.getElementById("mosmixWindChart"), {
      type:"line",
      data:{labels:labels,datasets:[
        Object.assign({label:"Wind",data:p.FF || [],borderColor:"#15806c",backgroundColor:"rgba(21,128,108,.06)"},commonLine),
        Object.assign({label:gustPeriod+"-h-Maximalböe",data:p[GUST_PERIODS[gustPeriod]] || [],borderColor:"#d97706",backgroundColor:"rgba(217,119,6,.06)",borderDash:[5,3]},commonLine)
      ]},
      options:windOptions
    }));

    meteogramCharts.push(new Chart(document.getElementById("mosmixPressureChart"), {
      type:"line",
      data:{labels:labels,datasets:[
        Object.assign({label:"Luftdruck",data:p.PPPP || [],borderColor:"#4f46e5",backgroundColor:"rgba(79,70,229,.06)"},commonLine)
      ]},
      options:baseChartOptions("hPa")
    }));
    const sunOptions=baseChartOptions("Sonnenschein (Minuten pro Stunde)");
    sunOptions.scales.y.min=0;
    sunOptions.scales.y.max=60;
    sunOptions.scales.y24={type:"linear",position:"right",min:0,max:24,
      title:{display:true,text:"24-h-Sonnenschein (h)"},
      grid:{drawOnChartArea:false}};
    sunOptions.scales.rad={type:"linear",display:false,position:"right",min:0,
      grid:{drawOnChartArea:false}};
    const sunshine=p.SunD1||[];
    const radiation=p.Rad1h||[];
    meteogramCharts.push(new Chart(document.getElementById("mosmixSunChart"),{
      type:"bar",data:{labels:labels,datasets:[
        {label:"Sonnenschein letzte 1 h (min)",data:sunshine,
         yAxisID:"y",backgroundColor:"rgba(238,175,26,.68)",borderWidth:0},
        Object.assign({type:"line",label:"Gleitende 24-h-Sonnenscheindauer (h)",
         data:rollingSunshine24h(sunshine),yAxisID:"y24",borderColor:"#c65a14",
         backgroundColor:"rgba(198,90,20,.07)"},commonLine),
        Object.assign({type:"line",label:"Globalstrahlung (kJ/m², 1 h)",
         data:radiation,yAxisID:"rad",hidden:true,borderColor:"#7751ad"},commonLine)
      ]},options:sunOptions
    }));
    const dayFrames=sunDayFramesFromTimesteps(data.timesteps);
    const dayValues=dayFrames.map(frame=>sunDayValue(sunshine,frame));
    const dayOptions=baseChartOptions("Sonnenscheindauer (h pro Tag)");
    dayOptions.plugins.legend.display=false;
    dayOptions.scales.y.min=0;
    dayOptions.scales.y.suggestedMax=12;
    dayOptions.scales.x={ticks:{autoSkip:true,maxTicksLimit:10,minRotation:0,maxRotation:0},
      grid:{display:false}};
    meteogramCharts.push(new Chart(document.getElementById("mosmixSunDailyChart"),{
      type:"bar",data:{
        labels:dayFrames.map(frame=>frame.label.slice(0,-4)),
        datasets:[{label:"Sonnenschein pro Tag (h)",data:dayValues,
          backgroundColor:dayValues.map(value=>Number.isFinite(value)?colorForSun(value):"#cbd5e1"),
          borderRadius:4,maxBarThickness:44}]
      },options:dayOptions
    }));
    const toggle=document.getElementById("mosmixComparePrevious");
    const status=document.getElementById("mosmixCompareStatus");
    if(toggle){toggle.disabled=!validPrevious;toggle.checked=validPrevious&&comparePreviousRun;}
    if(status)status.textContent=validPrevious?
      "Vorheriger Lauf: "+fmtTime(previous.issue_time)+" · gleiche UTC-Termine":
      "Kein archivierter Vorlauf verfügbar.";
    applyMeteogramRange();
    setMeteogramExportReady(true);
  }

  function applyMeteogramRange(){
    if(!data||!meteogramCharts.length)return;
    const range=document.getElementById("mosmixDiagramRange")?.value||"all";
    const hours=Number(range);
    let first=undefined,last=undefined;
    if(Number.isFinite(hours)&&hours>0){
      const now=Date.now();
      first=data.timesteps.findIndex(iso=>Date.parse(iso)>=now);
      if(first<0)first=Math.max(0,data.timesteps.length-1);
      last=Math.min(data.timesteps.length-1,first+hours);
    }
    meteogramCharts.slice(0,5).forEach(function(chart){
      chart.options.scales.x.min=first;
      chart.options.scales.x.max=last;
      chart.update("none");
    });
  }

  function setMeteogramExportReady(ready) {
    ["mosmixDiagramPng","mosmixDiagramPdf"].forEach(function(id) {
      const el = document.getElementById(id);
      if (el) el.disabled = !ready;
    });
  }

  function meteogramExportMeta() {
    const station = selectedStation || (data && data.stations.find(function(s){return s.key === selectedStationKey;}));
    return {
      station:station ? station.name : "MOSMIX",
      issue:fmtTime(data && data.issue_time),
      filename:"mosmix_"+(station ? station.name : "station").replace(/[^a-zA-Z0-9äöüÄÖÜß._-]+/g,"_")+
        "_"+String(data && data.issue_time || "lauf").replace(/[^a-zA-Z0-9]+/g,"").slice(0,18)
    };
  }

  function meteogramExportSections() {
    if (!currentDetail || meteogramCharts.length !== 6) throw new Error("Bitte zuerst eine Station mit fünf Diagrammen laden.");
    const specs = [
      ["mosmixTempChart","Temperatur und Taupunkt"],
      ["mosmixRainChart","Niederschlag und Bewölkung · "+rainPeriod+" h"],
      ["mosmixWindChart","Wind und maximale Böen · "+gustPeriod+" h"],
      ["mosmixPressureChart","Luftdruck"],
      ["mosmixSunChart","Stündlicher Sonnenschein und Globalstrahlung · SunD1 / Rad1h"],
      ["mosmixSunDailyChart","Sonnenscheindauer pro Kalendertag (h)"]
    ];
    return specs.map(function(spec) {
      const source = document.getElementById(spec[0]);
      if (!source || !source.width || !source.height) throw new Error("Diagramm noch nicht fertig gezeichnet.");
      const width = 1100, pad = 24, innerWidth = width - 2*pad;
      const plotHeight = Math.round(innerWidth * source.height/source.width);
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = plotHeight + 74;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0,0,canvas.width,canvas.height);
      ctx.font = "700 24px Arial";
      ctx.fillStyle = "#172033";
      ctx.fillText(spec[1],pad,33);
      ctx.strokeStyle = "#e2e8f0";
      ctx.beginPath();ctx.moveTo(pad,51);ctx.lineTo(width-pad,51);ctx.stroke();
      ctx.drawImage(source,pad,65,innerWidth,plotHeight);
      return canvas;
    });
  }

  function exportCombinedPng() {
    const sections = meteogramExportSections();
    const meta = meteogramExportMeta();
    const width = 1100, gap = 15, pad = 25, header = 118, footer = 55;
    const height = header + footer + pad + sections.reduce(function(n,c){return n+c.height+gap;},0);
    const out = document.createElement("canvas");
    out.width = width;out.height = height;
    const ctx = out.getContext("2d");
    ctx.fillStyle = "#fff";ctx.fillRect(0,0,width,height);
    ctx.fillStyle = "#0f172a";ctx.font = "bold 31px Arial";
    ctx.fillText("DWD MOSMIX-L · Meteogramme",pad,47);
    ctx.fillStyle = "#475569";ctx.font = "19px Arial";
    ctx.fillText(meta.station+" · Lauf "+meta.issue,pad,83);
    let y = header;
    sections.forEach(function(section){ ctx.drawImage(section,0,y);y+=section.height+gap; });
    ctx.fillStyle = "#64748b";ctx.font = "16px Arial";
    ctx.fillText("Quelle: Deutscher Wetterdienst (DWD), MOSMIX-L · originale Zeitraumsummen und Windböen",pad,height-24);
    const link = document.createElement("a");
    link.download = meta.filename+".png";
    link.href = out.toDataURL("image/png");
    document.body.appendChild(link);link.click();link.remove();
  }

  function exportCombinedPdf() {
    if (!window.jspdf || !window.jspdf.jsPDF) throw new Error("PDF-Bibliothek ist nicht geladen.");
    const sections = meteogramExportSections();
    const meta = meteogramExportMeta();
    const pdf = new window.jspdf.jsPDF({orientation:"portrait",unit:"mm",format:"a4"});
    const pageWidth = 210, margin = 12, width = pageWidth - 2*margin;
    let y = 0, pageNumber = 0;
    function startPage() {
      if (pageNumber) pdf.addPage();
      pageNumber++;
      pdf.setFont("helvetica","bold");pdf.setFontSize(14);
      pdf.text("DWD MOSMIX-L · Meteogramme",margin,17);
      pdf.setFont("helvetica","normal");pdf.setFontSize(9);
      pdf.text((meta.station+" · Lauf "+meta.issue).slice(0,92),margin,24);
      pdf.setDrawColor(210,218,225);pdf.line(margin,28,pageWidth-margin,28);
      pdf.setFontSize(8);
      pdf.text("Quelle: DWD MOSMIX-L · Originalwerte, Zeitsummen und Böen",margin,287);
      y = 34;
    }
    startPage();
    sections.forEach(function(section) {
      const h = section.height / section.width * width;
      if (y+h>279) startPage();
      const scaledHeight = Math.min(h,240);
      const scaledWidth = width * (scaledHeight/h);
      pdf.addImage(section.toDataURL("image/png"),"PNG",margin,y,scaledWidth,scaledHeight);
      y += scaledHeight + 6;
    });
    pdf.save(meta.filename+".pdf");
  }

  async function downloadMeteogram(format) {
    const status = document.getElementById("mosmixExportStatus");
    try {
      if (format === "pdf") {
        if(status)status.textContent="PDF-Bibliothek laden …";
        await ensurePdfLibrary();
        exportCombinedPdf();
      }
      else exportCombinedPng();
      if (status) status.textContent = (format === "pdf" ? "PDF" : "PNG")+"-Export vorbereitet.";
    } catch(err) {
      console.error("MOSMIX-Export:",err);
      if (status) status.textContent = "Download fehlgeschlagen: "+err.message;
    }
  }

  async function loadStationDetail(station) {
    if (!station || !station.key) throw new Error("Für diesen Punkt fehlen Detaildaten.");
    if (detailCache.has(station.key)) return detailCache.get(station.key);

    const response = await fetch(DETAIL_BASE + encodeURIComponent(station.key) + ".json?v=" + encodeURIComponent(data.issue_time || ""), {
      cache:"no-store"
    });
    if (!response.ok) throw new Error("Meteogramm-Daten HTTP " + response.status);
    const detail = await response.json();
    if(detail.issue_time!==data.issue_time)
      throw new Error("Stationsdatei und Kartenkatalog stammen aus verschiedenen MOSMIX-Läufen. Bitte „Neuen Lauf laden“ verwenden.");
    detailCache.set(station.key, detail);
    return detail;
  }

  async function selectStation(station) {
    if (!station) return;
    selectedStationKey = station.key;
    selectedStation = station;
    currentDetail = null;
    setMeteogramExportReady(false);
    const input = document.getElementById("mosmixStationSearch");
    if (input) input.value = stationDisplay(station);

    const status = document.getElementById("mosmixMeteogramStatus");
    if (status) status.textContent = "Meteogramm für " + station.name + " wird geladen …";

    try {
      const detail = await loadStationDetail(station);
      if (selectedStationKey !== station.key) return;
      if(status)status.textContent="Station geladen – Diagrammbibliothek wird vorbereitet …";
      await ensureCharts();
      if (selectedStationKey !== station.key) return;
      createMeteogram(detail);
      if (status) {
        status.innerHTML =
          "<strong>" + esc(station.name) + "</strong> · MOSMIX-ID " + esc(station.id) +
          (Number.isFinite(station.elev_m) ? " · " + Math.round(station.elev_m) + " m" : "") +
          " · Lauf " + esc(fmtTime(data.issue_time));
      }
    } catch (err) {
      console.error("MOSMIX Meteogramm:", err);
      if (status) status.textContent = "Meteogramm konnte nicht geladen werden: " + err.message;
    }
  }

  function selectStationFromSearch() {
    const input = document.getElementById("mosmixStationSearch");
    const station = findStation(input && input.value);
    const status = document.getElementById("mosmixMeteogramStatus");
    if (!station) {
      if (status) status.textContent = "Keine passende MOSMIX-Station gefunden.";
      return;
    }
    selectStation(station);
    if (map) {
      map.setView([station.lat,station.lon], Math.max(map.getZoom(),8));
    }
  }

  function extremaFrameLabel(mode,key) {
    const parts=String(key).split("-");
    const d=new Date(Date.UTC(Number(parts[0]),Number(parts[1])-1,Number(parts[2]),12));
    const date=new Intl.DateTimeFormat("de-DE",{timeZone:"Europe/Berlin",weekday:"short",day:"2-digit",month:"2-digit"}).format(d);
    return (mode==="tmax" ? "Tmax (TX, 12 h bis 18 UTC) " : "Tmin (TN, 12 h bis 06 UTC) ") + date;
  }

  function buildExtremaFrames(mode) {
    // DWD MOSMIX-L TX/TN are independent 12-hour forecasts; extrema must
    // never be reconstructed from the individual hourly TTT forecasts.
    // The DWD recommends TX valid at 18 UTC for European stations;
    // TN valid at 06 UTC describes the preceding night.
    const kind=mode==="tmax" ? "tx12" : "tn12";
    const hour=mode==="tmax" ? 18 : 6;
    return data.timesteps.map(function(iso,index) {
      const valid=new Date(iso);
      if (Number.isNaN(valid.getTime()) || valid.getUTCHours()!==hour) return null;
      const hasValues=data.stations.some(function(station) {
        return Number.isFinite(station[kind] && station[kind][index]);
      });
      if (!hasValues) return null;
      return {key:valid.toISOString().slice(0,10),
        index:index,indices:[index],kind:kind,
        label:extremaFrameLabel(mode,valid.toISOString().slice(0,10))};
    }).filter(Boolean);
  }

  function extremaHit(station,frame) {
    if (!station || !frame) return null;
    const value=frame.kind==="sunDay" ? frame.valuesByKey.get(station.key) :
      station[frame.kind] && station[frame.kind][frame.index];
    return Number.isFinite(value) ? {value:value,index:frame.index} : null;
  }

  function renderExtrema() {
    if (!data || !map || !markerLayer || !extremaFrames.length) return;
    const frame=extremaFrames[sliderIndex];
    if (!frame) return;

    markerLayer.clearLayers();
    const zoom=map.getZoom();
    const useLabels=zoom>=8;
    const bounds=map.getBounds().pad(.08);
    const occupied=new Set();
    const labelCell=zoom>=10 ? 38 : (zoom>=9 ? 46 : 56);
    const vals=[];
    let shown=0;
    let labelled=0;
    let above20=0;

    data.stations.forEach(function(station) {
      const hit=extremaHit(station,frame);
      if (!hit) return;
      const value=hit.value;
      vals.push(value);
      shown++;
      if(mapMode==="tmax" && value>=20) above20++;
      const color=mapMode==="sun"?colorForSun(value):colorForTemp(value);
      const latlng=L.latLng(station.lat,station.lon);
      // Avoid creating thousands of invisible Leaflet objects off screen.
      if(!bounds.contains(latlng))return;

      if (useLabels && bounds.contains(latlng)) {
        const p=map.latLngToContainerPoint(latlng);
        const key=Math.floor(p.x/labelCell)+":"+Math.floor(p.y/labelCell);
        if (!occupied.has(key)) {
          occupied.add(key);
          labelled++;
          const icon=L.divIcon({
            className:"mosmix-point-label",
            html:'<div style="background:'+color+';color:'+textColor(color)+'">'+value.toFixed(1).replace(".",",")+'</div>',
            iconSize:[38,22],
            iconAnchor:[19,11]
          });
          L.marker(latlng,{icon:icon})
            .bindPopup(popupHtml(station,value,mapMode==="sun"?frame.label:data.timesteps[hit.index],mapMode))
            .on("click",function(){ selectStation(station); })
            .addTo(markerLayer);
          return;
        }
      }

      L.circleMarker(latlng,{
        radius:zoom>=8 ? 3.3 : 4.5,
        color:"#ffffff",
        weight:.8,
        fillColor:color,
        fillOpacity:.9
      }).bindPopup(popupHtml(station,value,mapMode==="sun"?frame.label:data.timesteps[hit.index],mapMode))
        .on("click",function(){ selectStation(station); })
        .addTo(markerLayer);
    });

    const min=vals.length ? Math.min.apply(null,vals) : NaN;
    const max=vals.length ? Math.max.apply(null,vals) : NaN;
    document.getElementById("mosmixSliderLabel").textContent=frame.label;

    let info='Auswahl: <strong>'+esc(frame.label)+'</strong> · '+shown+' Punkte';
    if (useLabels) info+=' · '+labelled+' Werte beschriftet';
    if (Number.isFinite(min)) info+=' · '+min.toFixed(1).replace(".",",")+' bis '+max.toFixed(1).replace(".",",")+(mapMode==="sun"?' h Sonnenschein':' °C');
    if(mapMode==="tmax") info+=" · <strong>"+above20+" Stationen ≥ 20,0 °C</strong> (Kartenausschnitt)";
    document.getElementById("mosmixValidInfo").innerHTML=info;
  }

  async function loadSplitFrame(frame){
    if(!frame)throw Error("Kein MOSMIX-Zeitpunkt vorhanden.");
    if(mapChunkCache.has(frame.path)){
      const cached=mapChunkCache.get(frame.path);
      mapChunkCache.delete(frame.path);
      mapChunkCache.set(frame.path,cached);
      return cached;
    }
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),12000);
    let promise=fetch((data._mapsBase||MAP_BASE)+frame.path,{cache:"default",signal:controller.signal})
      .then(async function(response){
        if(!response.ok)throw Error("Kartendatei HTTP "+response.status);
        const chunk=await response.json();
        if(chunk.issue_time!==data.issue_time||!Array.isArray(chunk.values))
          throw Error("Kartendatei gehört nicht zum aktuellen MOSMIX-Lauf.");
        return chunk;
      }).finally(()=>clearTimeout(timer));
    mapChunkCache.set(frame.path,promise);
    try {
      const result=await promise;
      if(mapChunkCache.size>6)mapChunkCache.delete(mapChunkCache.keys().next().value);
      return result;
    } catch(error){
      mapChunkCache.delete(frame.path);
      throw error;
    }
  }

  function splitFrameValues(chunk,frame){
    const vals=chunk?.values?.[frame.slot];
    if(!Array.isArray(vals)||vals.length!==data.stations.length)
      throw Error("Unvollständiges MOSMIX-Datenpaket.");
    return vals;
  }

  async function renderSplitMap(){
    if(!data?._split||!map||!markerLayer)return;
    const request=++mapRequestSequence;
    const frame=extremaFrames[sliderIndex];
    if(!frame)return;
    const info=document.getElementById("mosmixValidInfo");
    if(info)info.textContent="Lade "+frame.label+" · "+mapKey()+" …";
    try {
      const chunk=await loadSplitFrame(frame);
      if(request!==mapRequestSequence)return;
      const values=splitFrameValues(chunk,frame);
      markerLayer.clearLayers();
      const zoom=map.getZoom(),useLabels=zoom>=8;
      const bounds=map.getBounds().pad(.08);
      const occupied=new Set(),labelCell=zoom>=10?38:(zoom>=9?46:56);
      const nums=[];
      let shown=0,labelled=0;
      const unit=mapUnit();
      data.stations.forEach(function(station,index){
        const value=values[index];
        if(!Number.isFinite(value))return;
        nums.push(value);
        shown++;
        const latlng=L.latLng(station.lat,station.lon);
        if(!bounds.contains(latlng))return;
        const color=colorForMap(value);
        let marker=null;
        if(useLabels){
          const p=map.latLngToContainerPoint(latlng);
          const key=Math.floor(p.x/labelCell)+":"+Math.floor(p.y/labelCell);
          if(!occupied.has(key)){
            occupied.add(key);labelled++;
            marker=L.marker(latlng,{icon:L.divIcon({
              className:"mosmix-point-label",
              html:'<div style="background:'+color+';color:'+textColor(color)+'">'+value.toFixed(1).replace(".",",")+'</div>',
              iconSize:[38,22],iconAnchor:[19,11]
            })});
          }
        }
        if(!marker)marker=L.circleMarker(latlng,{radius:zoom>=8?3.3:4.5,
          color:"#fff",weight:.8,fillColor:color,fillOpacity:.9});
        marker.bindPopup(popupHtml(station,value,frame.valid,mapMode))
          .on("click",function(){void selectStation(station);}).addTo(markerLayer);
      });
      document.getElementById("mosmixSliderLabel").textContent=frame.label;
      let message="Auswahl: "+frame.label+" · "+shown+" Originalwerte";
      if(useLabels)message+=" · "+labelled+" beschriftet";
      if(nums.length)message+=" · "+Math.min(...nums).toFixed(1).replace(".",",")+" bis "+
        Math.max(...nums).toFixed(1).replace(".",",")+" "+unit;
      if(info)info.textContent=message;
    }catch(error){
      if(request!==mapRequestSequence)return;
      markerLayer.clearLayers();
      if(info)info.textContent="Karte nicht geladen: "+error.message+
        " · Anderen Termin wählen oder Seite neu laden.";
      console.warn("MOSMIX-Kartendatei:",error);
    }
  }

  function renderCurrentMap() {
    if(data?._split){void renderSplitMap();return;}
    if (mapMode==="hourly") render();
    else renderExtrema();
  }

  function chooseExtremaIndex() {
    if (!extremaFrames.length) return 0;
    const nowParts=berlinDateParts(new Date().toISOString());
    const today=nowParts ? dateKey(nowParts.year,nowParts.month,nowParts.day,0) : "";
    const found=extremaFrames.findIndex(function(frame){ return frame.key>=today; });
    return found>=0 ? found : extremaFrames.length-1;
  }

  function setMapMode(mode) {
    mapMode=["hourly","tmax","tmin","sun","rain","gust","cloud"].includes(mode) ? mode : "hourly";
    if(!data?._split && MAP_VARIANTS[mapMode])mapMode="hourly";
    const variants=MAP_VARIANTS[mapMode];
    const variantWrap=document.getElementById("mosmixMapVariantWrap");
    const select=document.getElementById("mosmixMapVariant");
    if(variantWrap)variantWrap.hidden=!variants;
    if(variants&&select){
      if(!variants.some(row=>row[0]===mapVariant))mapVariant=variants[0][0];
      select.innerHTML=variants.map(row=>
        '<option value="'+row[0]+'">'+row[1]+'</option>').join("");
      select.value=mapVariant;
    }
    renderLegend();
    document.querySelectorAll("[data-mosmix-mode]").forEach(function(button) {
      button.classList.toggle("active",button.dataset.mosmixMode===mapMode);
    });

    const slider=document.getElementById("mosmixSlider");
    const title=document.getElementById("mosmixSliderTitle");
    const nowButton=document.getElementById("mosmixNow");

    if(data?._split){
      extremaFrames=data.modes?.[mapKey()]||[];
      slider.max=String(Math.max(0,extremaFrames.length-1));
      sliderIndex=mapMode==="hourly" ? Math.max(0,extremaFrames.findIndex(frame=>
        Date.parse(frame.valid)>=Date.now())) : chooseExtremaIndex();
      if(sliderIndex<0||sliderIndex>=extremaFrames.length)sliderIndex=0;
      title.textContent=mapMode==="sun"?"Sonnenscheindauer · Kalendertag":
        mapMode==="rain"?(mapVariant==="rainDay"?"Niederschlag · voller Kalendertag":"Niederschlag · DWD-Originalintervall"):
        mapMode==="gust"?(mapVariant==="gustDay"?"Maximalböe · voller Kalendertag":"Windböen · DWD-Originalintervall"):
        mapMode==="cloud"?"Bewölkung · Prognosetermin":"Vorhersagezeitpunkt";
      nowButton.textContent=mapMode==="hourly"?"Nächster Termin":"Aktueller Tag / Termin";
      slider.value=String(sliderIndex);
      if(!extremaFrames.length){
        markerLayer?.clearLayers();
        document.getElementById("mosmixSliderLabel").textContent="Keine Originalwerte vorhanden";
        document.getElementById("mosmixValidInfo").textContent=
          "Dieser MOSMIX-Lauf enthält für die gewählte Kartenart noch keine Originaldaten.";
        return;
      }
      renderCurrentMap();
      return;
    }

    if (mapMode==="hourly") {
      extremaFrames=[];
      slider.max=String(data.timesteps.length-1);
      sliderIndex=chooseInitialIndex();
      title.textContent="Vorhersagezeitpunkt";
      nowButton.textContent="Nächster Termin";
      slider.value=String(sliderIndex);
      render();
      return;
    }

    extremaFrames=mapMode==="sun" ? buildSunFrames() : buildExtremaFrames(mapMode);
    slider.max=String(Math.max(0,extremaFrames.length-1));
    if(!extremaFrames.length){
      markerLayer?.clearLayers();
      title.textContent=mapMode==="sun"?"Sonnenschein · Kalendertag":mapMode==="tmax"?"MOSMIX TX · 12 h":"MOSMIX TN · 12 h";
      document.getElementById("mosmixSliderLabel").textContent="Noch keine Originalwerte";
      document.getElementById("mosmixValidInfo").textContent=mapMode==="sun"?
        "Noch kein vollständig abgedeckter Kalendertag mit SunD1-Werten verfügbar. Unvollständige Tage werden nicht als Tagessumme ausgegeben.":
        "Dieser Datenlauf enthält noch keine echten MOSMIX-"+
        (mapMode==="tmax"?"TX-":"TN-")+"Werte am DWD-Standardtermin. "+
        "Der Datenimport wird aktualisiert – stündliche TTT-Werte sind kein Ersatz.";
      return;
    }
    sliderIndex=chooseExtremaIndex();
    title.textContent=mapMode==="sun"?"Sonnenschein · Kalendertag":"Vorhersagetag";
    nowButton.textContent="Aktueller Tag";
    slider.value=String(sliderIndex);
    renderExtrema();
  }

  function drawGeo(ctx,geometry,project) {
    if (!geometry) return;
    const polygons=geometry.type==="Polygon" ? [geometry.coordinates] :
      (geometry.type==="MultiPolygon" ? geometry.coordinates : []);
    polygons.forEach(function(polygon) {
      polygon.forEach(function(ring) {
        ring.forEach(function(coord,index) {
          const p=project(coord[0],coord[1]);
          if (index===0) ctx.moveTo(p.x,p.y);
          else ctx.lineTo(p.x,p.y);
        });
        ctx.closePath();
      });
    });
  }

  function buildBins(points,binSize) {
    const bins=new Map();
    points.forEach(function(p) {
      const key=Math.floor(p.lon/binSize)+":"+Math.floor(p.lat/binSize);
      if (!bins.has(key)) bins.set(key,[]);
      bins.get(key).push(p);
    });
    return bins;
  }

  function interpolatedValue(lon,lat,bins,binSize) {
    const bx=Math.floor(lon/binSize);
    const by=Math.floor(lat/binSize);
    let candidates=[];
    for (let ring=0; ring<=3 && candidates.length<12; ring++) {
      for (let dx=-ring; dx<=ring; dx++) {
        for (let dy=-ring; dy<=ring; dy++) {
          if (ring>0 && Math.abs(dx)!==ring && Math.abs(dy)!==ring) continue;
          const list=bins.get((bx+dx)+":"+(by+dy));
          if (list) candidates=candidates.concat(list);
        }
      }
    }
    if (!candidates.length) return null;
    const nearest=candidates.map(function(p) {
      const dx=(p.lon-lon)*Math.cos(lat*Math.PI/180);
      const dy=p.lat-lat;
      return {p:p,d2:dx*dx+dy*dy};
    }).sort(function(a,b){ return a.d2-b.d2; }).slice(0,8);
    if (nearest[0].d2<1e-10) return nearest[0].p.value;
    let num=0,den=0;
    nearest.forEach(function(item) {
      const w=1/Math.pow(item.d2,1.15);
      num+=w*item.p.value;
      den+=w;
    });
    return den ? num/den : null;
  }

  async function downloadAreaMap() {
    const button=document.getElementById("mosmixAreaDownload");
    const oldText=button.textContent;
    button.disabled=true;
    button.textContent="Flächenkarte wird berechnet …";
    try {
      if (!statesGeo) {
        const response=await fetch(STATES_URL,{cache:"force-cache"});
        if (!response.ok) throw new Error("Deutschlandgrenzen HTTP "+response.status);
        statesGeo=await response.json();
      }

      let label="";
      let points=[];
      if(data._split){
        const frame=extremaFrames[sliderIndex];
        if(!frame)throw Error("Keine Karte gewählt.");
        const chunk=await loadSplitFrame(frame);
        const values=splitFrameValues(chunk,frame);
        label=frame.label;
        data.stations.forEach(function(station,i){
          const value=values[i];
          if(Number.isFinite(value))points.push({lat:station.lat,lon:station.lon,value});
        });
      } else if (mapMode==="hourly") {
        const index=sliderIndex;
        label=fmtTime(data.timesteps[index]);
        data.stations.forEach(function(station) {
          const value=station.values&&station.values[index];
          if(Number.isFinite(value))points.push({lat:station.lat,lon:station.lon,value});
        });
      } else {
        const frame=extremaFrames[sliderIndex];
        label=frame ? frame.label : "";
        data.stations.forEach(function(station) {
          const hit=frame ? extremaHit(station,frame) : null;
          if(hit)points.push({lat:station.lat,lon:station.lon,value:hit.value});
        });
      }
      if (points.length<100) throw new Error("Zu wenige MOSMIX-Punkte.");

      const width=1100,height=1320;
      const margin={left:74,right:54,top:142,bottom:142};
      const lonMin=5.45,lonMax=15.55,latMin=47.15,latMax=55.15;
      const mapW=width-margin.left-margin.right;
      const mapH=height-margin.top-margin.bottom;
      const canvas=document.createElement("canvas");
      canvas.width=width;canvas.height=height;
      const ctx=canvas.getContext("2d");
      ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);

      const project=function(lon,lat) {
        return {x:margin.left+(lon-lonMin)/(lonMax-lonMin)*mapW,y:margin.top+(latMax-lat)/(latMax-latMin)*mapH};
      };
      const unproject=function(x,y) {
        return {lon:lonMin+(x-margin.left)/mapW*(lonMax-lonMin),lat:latMax-(y-margin.top)/mapH*(latMax-latMin)};
      };

      ctx.save();
      ctx.beginPath();
      statesGeo.features.forEach(function(feature){ drawGeo(ctx,feature.geometry,project); });
      ctx.clip();

      const cell=10,binSize=.45,bins=buildBins(points,binSize);
      for (let y=margin.top;y<margin.top+mapH;y+=cell) {
        for (let x=margin.left;x<margin.left+mapW;x+=cell) {
          const ll=unproject(x+cell/2,y+cell/2);
          const value=interpolatedValue(ll.lon,ll.lat,bins,binSize);
          if (!Number.isFinite(value)) continue;
          ctx.fillStyle=colorForMap(value);
          ctx.fillRect(x,y,cell+1,cell+1);
        }
      }
      ctx.restore();

      ctx.beginPath();
      statesGeo.features.forEach(function(feature){ drawGeo(ctx,feature.geometry,project); });
      ctx.strokeStyle="rgba(30,41,59,.72)";
      ctx.lineWidth=1.15;
      ctx.stroke();

      const selectedVariant=(MAP_VARIANTS[mapMode]||[]).find(row=>row[0]===mapVariant);
      const intervalName=selectedVariant?selectedVariant[1]:"";
      const title=mapMode==="tmax" ? "DWD MOSMIX-L · Tagesmaximum" :
        mapMode==="tmin" ? "DWD MOSMIX-L · Nachtminimum" :
        mapMode==="sun" ? "DWD MOSMIX-L · Sonnenscheindauer pro Kalendertag" :
        mapMode==="rain" ? "DWD MOSMIX-L · Niederschlag · "+intervalName :
        mapMode==="gust" ? "DWD MOSMIX-L · Windböe · "+intervalName :
        mapMode==="cloud" ? "DWD MOSMIX-L · Wolken "+mapVariant.slice(5) :
        "DWD MOSMIX-L · 2-m-Temperatur";
      ctx.fillStyle="#0f172a";ctx.font="700 30px Arial";ctx.fillText(title,margin.left,48);
      ctx.font="600 18px Arial";ctx.fillText(label,margin.left,80);
      ctx.fillStyle="#64748b";ctx.font="14px Arial";
      ctx.fillText("Lauf: "+fmtTime(data.issue_time)+" · "+points.length+" MOSMIX-Punkte",margin.left,106);

      const legendValues=mapMode==="sun"?[0,1,2,4,6,8,10,12,16,24]:
        mapMode==="rain"?[0,.1,1,3,8,15,30,60]:
        mapMode==="gust"?[0,20,40,60,80,100,120,150]:
        mapMode==="cloud"?[0,10,25,50,75,90,100]:
        [-15,-10,-5,0,5,10,15,20,25,30,35];
      const legendY=height-94,boxW=74;
      legendValues.forEach(function(v,index) {
        const x=margin.left+index*boxW;
        ctx.fillStyle=colorForMap(v);ctx.fillRect(x,legendY,boxW,18);
        ctx.strokeStyle="rgba(0,0,0,.15)";ctx.strokeRect(x,legendY,boxW,18);
        ctx.fillStyle="#334155";ctx.font="12px Arial";ctx.fillText(v+" "+mapUnit(),x+2,legendY+35);
      });
      ctx.fillStyle="#64748b";ctx.font="12px Arial";
      ctx.fillText("Interpoliert aus DWD-MOSMIX-L-Punktprognosen · keine amtliche DWD-Rasterkarte",margin.left,height-28);

      const blob=await new Promise(function(resolve){ canvas.toBlob(resolve,"image/png",1); });
      if (!blob) throw new Error("PNG konnte nicht erzeugt werden.");
      const url=URL.createObjectURL(blob);
      const link=document.createElement("a");
      link.href=url;
      link.download=("mosmix_"+mapMode+"_"+label+".png").replace(/[^0-9A-Za-zÄÖÜäöüß._-]+/g,"_");
      document.body.appendChild(link);link.click();link.remove();
      setTimeout(function(){ URL.revokeObjectURL(url); },1500);
    } catch (err) {
      console.error("MOSMIX Flächenkarte:",err);
      alert("Flächenkarte konnte nicht erstellt werden: "+err.message);
    } finally {
      button.disabled=false;
      button.textContent=oldText;
    }
  }

  function render() {
    if (!data || !map || !markerLayer) return;
    const i = sliderIndex;
    const valid = data.timesteps[i];
    const isSun=false;
    markerLayer.clearLayers();

    const zoom = map.getZoom();
    const useLabels = zoom >= 8;
    const bounds = map.getBounds().pad(.08);
    const occupied = new Set();
    const labelCell = zoom >= 10 ? 38 : (zoom >= 9 ? 46 : 56);
    let shown = 0;
    let labelled = 0;
    const vals = [];

    data.stations.forEach(function(station) {
      const source=isSun?station.sun1:station.values;
      const value = source && source[i];
      if (!Number.isFinite(value)) return;
      vals.push(value);
      shown++;
      const color = isSun?colorForSun(value):colorForTemp(value);
      const latlng = L.latLng(station.lat,station.lon);
      if(!bounds.contains(latlng))return;

      if (useLabels && bounds.contains(latlng)) {
        const p = map.latLngToContainerPoint(latlng);
        const key = Math.floor(p.x/labelCell) + ":" + Math.floor(p.y/labelCell);
        if (!occupied.has(key)) {
          occupied.add(key);
          labelled++;
          const icon = L.divIcon({
            className:"mosmix-point-label",
            html:'<div style="background:' + color + ';color:' + textColor(color) + '">' + value.toFixed(1).replace(".", ",") + '</div>',
            iconSize:[38,22],
            iconAnchor:[19,11]
          });
          L.marker(latlng, {icon:icon})
            .bindPopup(popupHtml(station,value,valid,mapMode))
            .on("click", function(){ selectStation(station); })
            .addTo(markerLayer);
          return;
        }
      }

      L.circleMarker(latlng, {
        radius:zoom >= 8 ? 3.3 : 4.5,
        color:"#ffffff",
        weight:.8,
        fillColor:color,
        fillOpacity:.9
      }).bindPopup(popupHtml(station,value,valid,mapMode))
        .on("click", function(){ selectStation(station); })
        .addTo(markerLayer);
    });

    let min = NaN, max = NaN;
    if (vals.length) {
      min = Math.min.apply(null, vals);
      max = Math.max.apply(null, vals);
    }

    document.getElementById("mosmixSliderLabel").textContent = fmtTime(valid);
    let info = 'Gültig: <strong>' + esc(fmtTime(valid)) + '</strong> · ' + shown + ' Punkte';
    if (useLabels) info += ' · ' + labelled + ' Werte beschriftet';
    if (Number.isFinite(min)) {
      info += ' · ' + min.toFixed(1).replace(".", ",") + ' bis ' + max.toFixed(1).replace(".", ",") + (isSun?' min Sonnenschein':' °C');
    }
    document.getElementById("mosmixValidInfo").innerHTML = info;
  }

  function setIndex(index) {
    const maxIndex=data?._split ? Math.max(0,extremaFrames.length-1) :
      mapMode==="hourly" ? data.timesteps.length-1 : Math.max(0,extremaFrames.length-1);
    sliderIndex=Math.max(0,Math.min(maxIndex,Number(index)||0));
    document.getElementById("mosmixSlider").value=String(sliderIndex);
    renderCurrentMap();
  }

  function togglePlay() {
    const button = document.getElementById("mosmixPlay");
    if (playTimer) {
      clearInterval(playTimer);
      playTimer = null;
      button.textContent = "▶ Animation";
      return;
    }
    button.textContent = "❚❚ Pause";
    playTimer = setInterval(function() {
      const total=data?._split?Math.max(1,extremaFrames.length):
        mapMode==="hourly" ? data.timesteps.length : Math.max(1,extremaFrames.length);
      setIndex((sliderIndex + 1) % total);
    }, 650);
  }

  function updateIssueDisplay(){
    document.getElementById("mosmixRunInfo").innerHTML =
      'DWD MOSMIX-L · Lauf <strong>' + esc(fmtTime(data.issue_time)) + '</strong> · ' +
      data.station_count + ' Punkte · ' + data.timesteps.length + ' Zeitschritte' +
      (data._mosmixSource?' · Quelle: '+esc(data._mosmixSource):'');
    document.getElementById("mosmixSectionStatus").textContent =
      'MOSMIX-L: TTT stündlich · TX 12 h bis 18 UTC · TN 12 h bis 06 UTC · Lauf '+
      fmtTime(data.issue_time)+(data._mosmixFallback?
      ' · Ersatzquelle (Laufdatum beachten)':'');
  }

  async function refreshForecast(){
    const button=document.getElementById("mosmixReload");
    const previousKey=selectedStationKey;
    if(button){button.disabled=true;button.textContent="Aktualisiere …";}
    try{
      const updated=await loadData(true);
      data=updated;
      mapChunkCache.clear();
      mapRequestSequence++;
      detailCache.clear();
      selectedStationKey=null;
      selectedStation=null;
      populateStationSearch();
      updateIssueDisplay();
      setMapMode(mapMode);
      currentDetail = null;
      comparePreviousRun=false;
      destroyMeteogramCharts();
      setMeteogramExportReady(false);
      const target=data.stations.find(s=>s.key===previousKey);
      if(target)selectStation(target);
      else document.getElementById("mosmixMeteogramStatus").textContent="Aktuellen Lauf geladen. Bitte Station auswählen.";
      setTimeout(function(){map?.invalidateSize();},75);
    }catch(error){
      document.getElementById("mosmixRunInfo").textContent =
        "MOSMIX-L: Aktualisierung fehlgeschlagen ("+error.message+"). Der bisherige Lauf bleibt erhalten.";
    }finally{
      if(button){button.disabled=false;button.textContent="Neuen Lauf laden ↻";}
    }
  }

  async function init() {
    if (loaded) {
      setTimeout(function(){ if (map) map.invalidateSize(); }, 50);
      return;
    }
    loaded = true;

    try {
      // Fetch data independently. Missing Leaflet must never silently stop
      // the module with a permanent "Daten werden geladen" placeholder.
      if (!data) data = await loadData(false);
      updateIssueDisplay();
      if (!window.L) await ensureLeaflet();
      makeMap();

      const slider = document.getElementById("mosmixSlider");
      slider.max = String(data.timesteps.length - 1);
      slider.addEventListener("input", function(){ setIndex(slider.value); });
      document.querySelectorAll("[data-mosmix-mode]").forEach(function(button){
        button.addEventListener("click",function(){ setMapMode(button.dataset.mosmixMode); });
      });
      document.getElementById("mosmixPlay").addEventListener("click", togglePlay);
      document.getElementById("mosmixNow").addEventListener("click", function(){
        setIndex(data?._split?chooseExtremaIndex():mapMode==="hourly"?chooseInitialIndex():chooseExtremaIndex());
      });
      document.getElementById("mosmixMapVariant").addEventListener("change",function(event){
        mapVariant=event.target.value;
        setMapMode(mapMode);
      });
      document.getElementById("mosmixAreaDownload").addEventListener("click", downloadAreaMap);
      document.getElementById("mosmixReload").addEventListener("click", refreshForecast);
      document.getElementById("mosmixStationButton").addEventListener("click", selectStationFromSearch);
      document.querySelectorAll("[data-mosmix-period]").forEach(function(button) {
        button.addEventListener("click",function(){
          selectMeteogramPeriod(button.dataset.mosmixPeriod,button.dataset.hours);
        });
      });
      document.getElementById("mosmixDiagramRange").addEventListener("change",applyMeteogramRange);
      document.getElementById("mosmixComparePrevious").addEventListener("change",function(event){
        comparePreviousRun=event.target.checked;
        if(currentDetail)createMeteogram(currentDetail);
      });
      document.getElementById("mosmixDiagramPng").addEventListener("click",function(){downloadMeteogram("png");});
      document.getElementById("mosmixDiagramPdf").addEventListener("click",function(){downloadMeteogram("pdf");});
      document.getElementById("mosmixStationSearch").addEventListener("keydown", function(event){
        if (event.key === "Enter") {
          event.preventDefault();
          selectStationFromSearch();
        }
      });
      populateStationSearch();
      map.on("zoomend moveend", renderCurrentMap);

      updateIssueDisplay();

      setMapMode(mapMode);

      // Load individual meteograms only after a station is selected.
      // Avoid extra network requests on the first map paint.

      setTimeout(function(){ map.invalidateSize(); }, 100);
    } catch (err) {
      loaded = false;
      console.error("MOSMIX:", err);
      const status = document.getElementById("mosmixSectionStatus");
      if (status) status.textContent = "MOSMIX konnte nicht gestartet werden: "+err.message+
        " · Über „Erneut versuchen“ neu laden. Keine endlose Warteschleife.";
      const run = document.getElementById("mosmixRunInfo");
      if (run) run.textContent = "Fehler: " + err.message;
      const retry=document.getElementById("mosmixReload");
      if(retry){
        retry.textContent="Erneut versuchen";
        retry.addEventListener("click",function(){
          retry.textContent="Neuen Lauf laden ↻";
          void init();
        },{once:true});
      }
    }
  }

  function boot() {
    addCss();
    addSection();
    addNavigation();
    if(document.body.hasAttribute("data-mosmix-standalone")){
      const node=document.getElementById(TAB_ID);
      if(node)node.classList.add("active");
    }
    if (document.getElementById(TAB_ID) && document.getElementById(TAB_ID).classList.contains("active")) init();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
