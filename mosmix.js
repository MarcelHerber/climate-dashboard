(() => {
  "use strict";

  const DATA_URL = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/mosmix-data/data/mosmix/mosmix_ttt.json";
  const STATES_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json";
  const TAB_ID = "mosmix";

  let data = null;
  let map = null;
  let markerLayer = null;
  let sliderIndex = 0;
  let playTimer = null;
  let loaded = false;

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
      "@media(max-width:800px){.mosmix-controls{grid-template-columns:1fr 1fr}.mosmix-slider-wrap{grid-column:1/-1}.mosmix-map{height:540px}}"
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
      btn.setAttribute("onclick", "switchTab('mosmix');window.setTimeout(function(){window.dispatchEvent(new Event('mosmix-open'));},0)");

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
      }).bindPopup(popupHtml(station,value,valid)).addTo(markerLayer);
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
      map.on("zoomend", render);

      document.getElementById("mosmixRunInfo").innerHTML =
        'Lauf: <strong>' + esc(fmtTime(data.issue_time)) + '</strong> · ' +
        data.station_count + ' Punkte · ' + data.timesteps.length + ' Zeitschritte';
      document.getElementById("mosmixSectionStatus").textContent =
        'MOSMIX-L TTT · Lauf ' + fmtTime(data.issue_time);

      renderLegend();
      setIndex(chooseInitialIndex());
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
    window.addEventListener("mosmix-open", init);
    if (document.getElementById(TAB_ID) && document.getElementById(TAB_ID).classList.contains("active")) init();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
