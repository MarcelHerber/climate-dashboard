(() => {
  "use strict";

  const DATA_URL = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/mosmix-data/data/mosmix/mosmix_ttt.json";
  const DETAIL_BASE = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/mosmix-data/data/mosmix/stations/";
  const STATES_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json";
  const TAB_ID = "mosmix";

  let data = null;
  let map = null;
  let markerLayer = null;
  let sliderIndex = 0;
  let playTimer = null;
  let loaded = false;
  let selectedStationKey = null;
  let meteogramCharts = [];
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
      ".mosmix-controls{display:grid;grid-template-columns:minmax(260px,1fr) auto auto;gap:12px;align-items:end}",
      ".mosmix-slider-wrap label{display:flex;justify-content:space-between;gap:12px;font-size:13px;font-weight:700;color:#334155;margin-bottom:7px}",
      ".mosmix-slider{width:100%}",
      ".mosmix-button{appearance:none;border:1px solid #cbd5df;border-radius:7px;background:#fff;color:#172033;padding:9px 13px;font-weight:700;cursor:pointer}",
      ".mosmix-button:hover{background:#f5f8fa}",
      ".mosmix-map{height:650px;border:1px solid #d5dde4;border-radius:9px;overflow:hidden;background:#eef2f5}",
      ".mosmix-map .leaflet-control-attribution{font-size:9px}",
      ".mosmix-topline{display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px;margin-bottom:12px}",
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
      ".mosmix-chart-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}",
      ".mosmix-chart-card{min-width:0;border:1px solid #dce3e8;border-radius:8px;padding:10px 12px;background:#fff}.mosmix-chart-card h4{margin:0 0 7px;font-size:13px;color:#334155}",
      ".mosmix-chart-wrap{position:relative;height:280px}.mosmix-chart-wrap canvas{width:100%!important;height:100%!important}",
      "@media(max-width:900px){.mosmix-chart-grid{grid-template-columns:1fr}.mosmix-station-search{width:100%}.mosmix-station-search input{min-width:0;flex:1}}",
      "@media(max-width:800px){.mosmix-controls{grid-template-columns:1fr 1fr}.mosmix-slider-wrap{grid-column:1/-1}.mosmix-map{height:540px}.mosmix-chart-wrap{height:250px}}"
    ].join("");
    document.head.appendChild(style);
  }

  function sectionHtml() {
    return [
      '<div id="mosmix" class="tab-content">',
      '<div class="section-header">',
      '<h2>DWD MOSMIX – Vorhersagekarte</h2>',
      '<p>MOSMIX-L Punktprognosen für Deutschland. Erste Version: 2-m-Temperatur (TTT) mit stündlichem Zeitschieber und Animation.</p>',
      '<div class="section-status" id="mosmixSectionStatus">Daten werden geladen …</div>',
      '</div>',
      '<div class="mosmix-grid">',
      '<div class="mosmix-card">',
      '<div class="mosmix-topline"><div class="mosmix-status" id="mosmixRunInfo">MOSMIX-L wird geladen …</div><div class="mosmix-status" id="mosmixValidInfo"></div></div>',
      '<div class="mosmix-controls">',
      '<div class="mosmix-slider-wrap"><label><span>Vorhersagezeitpunkt</span><strong id="mosmixSliderLabel">–</strong></label><input id="mosmixSlider" class="mosmix-slider" type="range" min="0" max="0" step="1" value="0"></div>',
      '<button id="mosmixPlay" class="mosmix-button" type="button">▶ Animation</button>',
      '<button id="mosmixNow" class="mosmix-button" type="button">Nächster Termin</button>',
      '</div></div>',
      '<div class="mosmix-card">',
      '<div id="mosmixMap" class="mosmix-map"></div>',
      '<div id="mosmixLegend" class="mosmix-legend"></div>',
      '<p class="mosmix-note">Quelle: Deutscher Wetterdienst (DWD), MOSMIX-L. Gezeigt werden originale MOSMIX-Punktprognosen. Eine flächige Interpolation wird separat ergänzt und ausdrücklich als interpolierte Darstellung gekennzeichnet.</p>',
      '</div>',
      '<div class="mosmix-card mosmix-meteogram-card">',
      '<div class="mosmix-meteogram-head">',
      '<div><h3>MOSMIX-Meteogramm</h3><p class="mosmix-note">Station suchen oder einen Punkt in der Karte anklicken.</p></div>',
      '<div class="mosmix-station-search"><input id="mosmixStationSearch" list="mosmixStationList" type="search" placeholder="z. B. Frankfurt, Saarbrücken …" autocomplete="off"><datalist id="mosmixStationList"></datalist><button id="mosmixStationButton" class="mosmix-button" type="button">Diagramm anzeigen</button></div>',
      '</div>',
      '<div id="mosmixMeteogramStatus" class="mosmix-meteogram-status">Noch keine Station ausgewählt.</div>',
      '<div class="mosmix-chart-grid">',
      '<div class="mosmix-chart-card"><h4>Temperatur &amp; Taupunkt</h4><div class="mosmix-chart-wrap"><canvas id="mosmixTempChart"></canvas></div></div>',
      '<div class="mosmix-chart-card"><h4>Niederschlag &amp; Bewölkung</h4><div class="mosmix-chart-wrap"><canvas id="mosmixRainChart"></canvas></div></div>',
      '<div class="mosmix-chart-card"><h4>Wind &amp; Böen</h4><div class="mosmix-chart-wrap"><canvas id="mosmixWindChart"></canvas></div></div>',
      '<div class="mosmix-chart-card"><h4>Luftdruck</h4><div class="mosmix-chart-wrap"><canvas id="mosmixPressureChart"></canvas></div></div>',
      '</div>',
      '<p class="mosmix-note">Wind wird in km/h, Niederschlag in mm und Luftdruck in hPa dargestellt. Einzelne Parameter oder Termine können in MOSMIX fehlen.</p>',
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

  async function loadData() {
    const response = await fetch(DATA_URL + "?v=" + Date.now(), {cache:"no-store"});
    if (!response.ok) throw new Error("MOSMIX-Daten HTTP " + response.status);
    const json = await response.json();
    if (!Array.isArray(json.timesteps) || !Array.isArray(json.stations)) {
      throw new Error("Ungültiges MOSMIX-Datenformat");
    }
    return json;
  }

  async function loadStates() {
    try {
      const response = await fetch(STATES_URL, {cache:"force-cache"});
      if (!response.ok) return;
      const geo = await response.json();
      L.geoJSON(geo, {
        style: {color:"#55616d",weight:1,opacity:.85,fillOpacity:0}
      }).addTo(map);
    } catch (err) {
      console.warn("MOSMIX Bundesländergrenzen:", err);
    }
  }

  function makeMap() {
    if (map) return;
    map = L.map("mosmixMap", {
      center:[51.05,10.35],
      zoom:6,
      minZoom:5,
      maxZoom:10,
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

  function renderLegend() {
    const values = [-15,-10,-5,0,5,10,15,20,25,30,35];
    document.getElementById("mosmixLegend").innerHTML = values.map(function(v) {
      return '<span><i style="background:' + colorForTemp(v) + '"></i>' + v + '°</span>';
    }).join("");
  }

  function popupHtml(station, value, valid) {
    return '<strong>' + esc(station.name) + '</strong><br>' +
      'MOSMIX-ID: ' + esc(station.id) + '<br>' +
      'Temperatur: <strong>' + value.toFixed(1).replace(".", ",") + ' °C</strong><br>' +
      'Gültig: ' + esc(fmtTime(valid));
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
      return weekday + " " + date + " " + hour + "h";
    });
  }

  function compass(deg) {
    if (!Number.isFinite(deg)) return "";
    const dirs = ["N","NO","O","SO","S","SW","W","NW"];
    return dirs[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
  }

  function baseChartOptions(yTitle) {
    return {
      responsive:true,
      maintainAspectRatio:false,
      animation:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        legend:{display:true,labels:{boxWidth:18,usePointStyle:true}},
        tooltip:{enabled:true}
      },
      scales:{
        x:{ticks:{maxTicksLimit:12,maxRotation:0,autoSkip:true},grid:{display:false}},
        y:{title:{display:true,text:yTitle}}
      }
    };
  }

  function createMeteogram(detail) {
    if (!window.Chart) throw new Error("Chart.js ist nicht verfügbar.");
    destroyMeteogramCharts();

    const p = detail.parameters || {};
    const labels = meteogramLabels();
    const commonLine = {pointRadius:0,pointHoverRadius:3,borderWidth:2,tension:.18,spanGaps:true};

    meteogramCharts.push(new Chart(document.getElementById("mosmixTempChart"), {
      type:"line",
      data:{labels:labels,datasets:[
        Object.assign({label:"Temperatur",data:p.TTT || [],borderColor:"#c62828",backgroundColor:"rgba(198,40,40,.08)"},commonLine),
        Object.assign({label:"Taupunkt",data:p.Td || [],borderColor:"#1769c2",backgroundColor:"rgba(23,105,194,.08)"},commonLine)
      ]},
      options:baseChartOptions("°C")
    }));

    const rainOptions = baseChartOptions("mm / h");
    rainOptions.scales.y.beginAtZero = true;
    rainOptions.scales.yCloud = {
      position:"right",min:0,max:100,
      title:{display:true,text:"Bewölkung (%)"},
      grid:{drawOnChartArea:false}
    };
    meteogramCharts.push(new Chart(document.getElementById("mosmixRainChart"), {
      data:{labels:labels,datasets:[
        {type:"bar",label:"1-h-Niederschlag",data:p.RR1c || [],yAxisID:"y",backgroundColor:"rgba(23,105,194,.58)",borderWidth:0,barPercentage:.9,categoryPercentage:1},
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
        Object.assign({label:"Böen",data:p.FX1 || [],borderColor:"#d97706",backgroundColor:"rgba(217,119,6,.06)",borderDash:[5,3]},commonLine)
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
  }

  async function loadStationDetail(station) {
    if (!station || !station.key) throw new Error("Für diesen Punkt fehlen Detaildaten.");
    if (detailCache.has(station.key)) return detailCache.get(station.key);

    const response = await fetch(DETAIL_BASE + encodeURIComponent(station.key) + ".json?v=" + encodeURIComponent(data.issue_time || ""), {
      cache:"no-store"
    });
    if (!response.ok) throw new Error("Meteogramm-Daten HTTP " + response.status);
    const detail = await response.json();
    detailCache.set(station.key, detail);
    return detail;
  }

  async function selectStation(station) {
    if (!station) return;
    selectedStationKey = station.key;
    const input = document.getElementById("mosmixStationSearch");
    if (input) input.value = stationDisplay(station);

    const status = document.getElementById("mosmixMeteogramStatus");
    if (status) status.textContent = "Meteogramm für " + station.name + " wird geladen …";

    try {
      const detail = await loadStationDetail(station);
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

  function render() {
    if (!data || !map || !markerLayer) return;
    const i = sliderIndex;
    const valid = data.timesteps[i];
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
      const value = station.values && station.values[i];
      if (!Number.isFinite(value)) return;
      vals.push(value);
      shown++;
      const color = colorForTemp(value);
      const latlng = L.latLng(station.lat,station.lon);

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
            .bindPopup(popupHtml(station,value,valid))
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
      }).bindPopup(popupHtml(station,value,valid))
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
      info += ' · ' + min.toFixed(1).replace(".", ",") + ' bis ' + max.toFixed(1).replace(".", ",") + ' °C';
    }
    document.getElementById("mosmixValidInfo").innerHTML = info;
  }

  function setIndex(index) {
    sliderIndex = Math.max(0, Math.min(data.timesteps.length - 1, Number(index) || 0));
    document.getElementById("mosmixSlider").value = String(sliderIndex);
    render();
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
      setIndex((sliderIndex + 1) % data.timesteps.length);
    }, 650);
  }

  async function init() {
    if (loaded) {
      setTimeout(function(){ if (map) map.invalidateSize(); }, 50);
      return;
    }
    if (!window.L) return;
    loaded = true;

    try {
      makeMap();
      data = await loadData();

      const slider = document.getElementById("mosmixSlider");
      slider.max = String(data.timesteps.length - 1);
      slider.addEventListener("input", function(){ setIndex(slider.value); });
      document.getElementById("mosmixPlay").addEventListener("click", togglePlay);
      document.getElementById("mosmixNow").addEventListener("click", function(){ setIndex(chooseInitialIndex()); });
      document.getElementById("mosmixStationButton").addEventListener("click", selectStationFromSearch);
      document.getElementById("mosmixStationSearch").addEventListener("keydown", function(event){
        if (event.key === "Enter") {
          event.preventDefault();
          selectStationFromSearch();
        }
      });
      populateStationSearch();
      map.on("zoomend", render);

      document.getElementById("mosmixRunInfo").innerHTML =
        'Lauf: <strong>' + esc(fmtTime(data.issue_time)) + '</strong> · ' +
        data.station_count + ' Punkte · ' + data.timesteps.length + ' Zeitschritte';
      document.getElementById("mosmixSectionStatus").textContent =
        'MOSMIX-L TTT · Lauf ' + fmtTime(data.issue_time);

      renderLegend();
      setIndex(chooseInitialIndex());

      const preferred = data.stations.find(function(station){
        return /FRANKFURT.*MAIN|FRANKFURT\/M/i.test(station.name);
      });
      if (preferred) selectStation(preferred);

      setTimeout(function(){ map.invalidateSize(); }, 100);
    } catch (err) {
      loaded = false;
      console.error("MOSMIX:", err);
      const status = document.getElementById("mosmixSectionStatus");
      if (status) status.textContent = "MOSMIX-Daten derzeit nicht verfügbar";
      const run = document.getElementById("mosmixRunInfo");
      if (run) run.textContent = "Fehler: " + err.message;
    }
  }

  function boot() {
    addCss();
    addSection();
    addNavigation();
    if (document.getElementById(TAB_ID) && document.getElementById(TAB_ID).classList.contains("active")) init();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
