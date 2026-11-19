(function () {
  "use strict";
  // Daily SST by NOAA OISST v2.1, published as ready-to-use daily regional CSVs.
  // Source calculations: https://earthindicators.org/methods.html
  const BASE = "https://raw.githubusercontent.com/tsjuri/earthindicators/main/data/";
  const FALLBACK = "https://cdn.jsdelivr.net/gh/tsjuri/earthindicators@main/data/";
  const OWN_BASE = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/sst-regional-years-data/";
  const OWN_FALLBACK = "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@sst-regional-years-data/";
  const REGIONS = {
    world: ["Global (60°S–60°N)", "world_daily_sst.csv", "60°S–60°N · 1°-Stichprobe"],
    natl: ["Nordatlantik (Standardbox)", "natl_daily_sst.csv", "0–60°N, 80–0°W · 0,5°-Stichprobe"],
    npac: ["Nordpazifik", "npac_daily_sst.csv", "0–60°N, 120°E–100°W · 0,75°-Stichprobe"],
    spna: ["Subpolarer Nordatlantik", "spna_daily_sst.csv", "45–60°N, 45–20°W · 0,25°"],
    europe: ["Europa gesamt (Kartenausschnitt)", "europe_daily_sst.csv", "25–72°N, 30°W–45°E", true],
    mediterranean: ["Mittelmeer (Kartenausschnitt)", "mediterranean_daily_sst.csv", "30–46°N, 18°W–36°E", true],
    north_atlantic: ["Nordatlantik (Kartenausschnitt)", "north_atlantic_daily_sst.csv", "20–78°N, 65°W–25°E", true],
    nordic_seas: ["Nordmeer / Skandinavien (Kartenausschnitt)", "nordic_seas_daily_sst.csv", "50–84°N, 35°W–50°E", true],
    pacific: ["Pazifik (Kartenausschnitt)", "pacific_daily_sst.csv", "60°S–60°N, 120°E–70°W", true],
    indian_ocean: ["Indischer Ozean (Kartenausschnitt)", "indian_ocean_daily_sst.csv", "60°S–30°N, 20–120°E", true],
    nino12: ["Niño 1+2", "nino12_daily_sst.csv", "0–10°S, 90–80°W"],
    nino3: ["Niño 3", "nino3_daily_sst.csv", "5°S–5°N, 150–90°W"],
    nino34: ["Niño 3.4", "nino34_daily_sst.csv", "5°S–5°N, 170–120°W"],
    nino4: ["Niño 4", "nino4_daily_sst.csv", "5°S–5°N, 160°E–150°W"]
  };
  const MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
  const DAYS = Array.from({ length: 366 }, function (_, day) {
    return new Date(Date.UTC(2024, 0, day + 1)).toISOString().slice(5, 10);
  });
  const DAY_INDEX = new Map(DAYS.map(function (day, i) { return [day, i]; }));
  const cache = new Map();
  let chart = null;
  let current = null;
  let requestId = 0;
  function el(id) { return document.getElementById(id); }
  function text(id, value) { const node = el(id); if (node) node.textContent = value; }
  function numeric(value) {
    if (!value.trim()) return null;
    const n = Number(value);
    return Number.isFinite(n) && n >= -2.5 && n <= 36 ? n : null;
  }
  function parseDailyCsv(csv, strictArchive) {
    const lines = csv.trim().split(/\r?\n/);
    if (lines.length < 12000 || lines[0].trim().toLowerCase().replace(/"/g, "") !== "date,sst") {
      throw new Error("Unerwartetes Format der SST-Tagesdaten (erwartet: date,sst).");
    }
    const years = {};
    let lastDate = "";
    let count = 0;
    for (const line of lines.slice(1)) {
      const parts = line.trim().split(",");
      if (parts.length !== 2) continue;
      const iso = parts[0].trim();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(iso) || iso <= lastDate) continue;
      const date = new Date(iso + "T00:00:00Z");
      if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0,10) !== iso) continue;
      const value = numeric(parts[1]);
      if (value === null) continue;
      const year = iso.slice(0, 4), day = DAY_INDEX.get(iso.slice(5));
      if (day === undefined) continue;
      if (!years[year]) years[year] = Array(366).fill(null);
      years[year][day] = value;
      lastDate = iso; count++;
    }
    const currentYear = String(new Date().getUTCFullYear());
    const age = (Date.now() - new Date(lastDate + "T00:00:00Z").getTime()) / 86400000;
    if (count < 12000 || !years["1991"] || !years["2020"] || age > 60 || age < -3) {
      throw new Error("Tagesreihe unvollständig oder nicht aktuell genug.");
    }
    if (strictArchive && (Object.keys(years).sort()[0] !== "1982" || count !== Math.round((new Date(lastDate + "T00:00:00Z") - Date.UTC(1982,0,1)) / 86400000) + 1)) {
      throw new Error("Das eigene Archiv seit 1982 ist noch nicht vollständig.");
    }
    return { years, lastDate, count, currentYear };
  }
  async function getData(region) {
    if (cache.has(region)) return cache.get(region);
    const file = REGIONS[region][1];
    const urlSuffix = file + "?t=" + Math.floor(Date.now() / 3600000);
    const promise = (async function () {
      let lastError;
      for (const base of REGIONS[region][3] ? [OWN_BASE, OWN_FALLBACK] : [BASE, FALLBACK]) {
        try {
          const response = await fetch(base + urlSuffix, { cache: "no-store" });
          if (!response.ok) throw new Error("HTTP " + response.status);
          const data = parseDailyCsv(await response.text(), REGIONS[region][3]);
          data.source = base + file;
          return data;
        } catch (err) { lastError = err; }
      }
      throw lastError || new Error("Die Tagesdaten sind nicht erreichbar.");
    }());
    cache.set(region, promise);
    promise.catch(function () { cache.delete(region); });
    return promise;
  }
  function reference(data) {
    const result = DAYS.map(function (_, d) {
      const values = [];
      for (let year = 1991; year <= 2020; year++) {
        const n = data.years[String(year)]?.[d];
        if (Number.isFinite(n)) values.push(n);
      }
      return values.length >= (d === DAY_INDEX.get("02-29") ? 6 : 25)
        ? values.reduce(function (a, b) { return a + b; }, 0) / values.length : null;
    });
    // A fixed five-day window reduces daily sampling noise in the climatic mean.
    return result.map(function (_, d) {
      let sum = 0, n = 0;
      for (let j = -2; j <= 2; j++) {
        const value = result[(d + j + 366) % 366];
        if (Number.isFinite(value)) { sum += value; n++; }
      }
      return n ? sum / n : null;
    });
  }
  function palette(year, latest) {
    if (year === latest) return "#ff373b";
    const hue = 198 + ((Number(year) * 29) % 35);
    return "hsla(" + hue + ",79%,77%,0.38)";
  }
  function renderPlot() {
    if (!current || !window.Chart) return;
    const data = current.data;
    const region = current.region;
    const years = Object.keys(data.years).sort();
    const latestYear = years[years.length - 1];
    const ref = reference(data);
    const anomaly = el("sstYearsMetric").value === "anomaly";
    const mode = el("sstYearsHistory").value;
    const picked = el("sstYearsYear").value;
    const normalize = function (values) {
      return values.map(function (v, day) {
        return Number.isFinite(v) && Number.isFinite(ref[day])
          ? (anomaly ? +(v - ref[day]).toFixed(3) : v) : null;
      });
    };
    const shownYears = mode === "all" ? years : (mode === "year" ? [picked, latestYear] : [latestYear]);
    const datasets = [];
    for (const year of years) {
      if (!shownYears.includes(year) || year === latestYear) continue;
      datasets.push({
        label: year, data: normalize(data.years[year]),
        borderColor: palette(year, latestYear), borderWidth: year === picked && mode === "year" ? 2.1 : 1,
        pointRadius: 0, spanGaps: true, tension: 0, fill: false
      });
    }
    datasets.push({
      label: "Mittel 1991–2020", data: anomaly ? Array(366).fill(0) : ref,
      borderColor: "#fff42d", borderWidth: 3, pointRadius: 0, tension: 0, fill: false
    });
    datasets.push({
      label: latestYear, data: normalize(data.years[latestYear]),
      borderColor: "#ff373b", borderWidth: 3, pointRadius: 0, tension: 0, fill: false
    });
    if (chart) chart.destroy();
    const background = {
      id: "sstYearsBackground",
      beforeDraw: function (instance) {
        const ctx = instance.ctx;
        ctx.save(); ctx.fillStyle = "#080c15";
        ctx.fillRect(0, 0, instance.width, instance.height); ctx.restore();
      }
    };
    chart = new Chart(el("sstYearsCanvas").getContext("2d"), {
      type: "line",
      data: { labels: DAYS, datasets },
      plugins: [background],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        normalized: true, parsing: true, spanGaps: true,
        interaction: { intersect: false, mode: "nearest", axis: "xy" },
        plugins: {
          legend: { display: false },
          datalabels: { display: false },
          title: { display: true, text: REGIONS[region][0] + " · täglicher Jahresverlauf (" + (anomaly ? "Anomalie" : "SST") + ")", color: "#f8fafc",
                   font: { size: 16, weight: "bold" }, padding: 12 },
          tooltip: { callbacks: { title: function (items) {
            const value = items[0]?.label || "";
            return value.slice(3) + "." + value.slice(0, 2) + ".";
          }, label: function (item) {
            return " " + item.dataset.label + ": " + Number(item.parsed.y).toLocaleString("de-DE", { maximumFractionDigits: 2 }) + (anomaly ? " K" : " °C");
          } } }
        },
        scales: {
          x: { grid: { color: "rgba(255,255,255,.08)" }, border: { color: "#697483" },
            ticks: { color: "#d4dce5", autoSkip: false, maxRotation: 0,
              callback: function (value) {
                const d = DAYS[value]; return d && d.slice(3) === "01" ? MONTHS[Number(d.slice(0, 2)) - 1] : "";
              }
            }
          },
          y: { grid: { color: "rgba(255,255,255,.12)" }, border: { color: "#697483" },
            title: { display: true, text: anomaly ? "SST-Anomalie (K)" : "SST (°C)", color: "#e5e7eb" },
            ticks: { color: "#e2e8f0" } }
        }
      }
    });
    text("sstYearsMeta", "NOAA OISST v2.1 · " + REGIONS[region][2] + (REGIONS[region][3] ? " · 0,25° · eigener flächengewichteter Mittelwert" : " · Earth Indicators") + " · " + years[0] + "–" +
      latestYear + " · letzter Messwert " + data.lastDate + " · Klimamittel 1991–2020 (5-Tage-geglättet).");
    text("sstYearsStatus", "");
    el("sstYearsPng").disabled = false;
    el("sstYearsCsv").disabled = false;
  }
  function exportCsv() {
    if (!current) return;
    const data = current.data, years = Object.keys(data.years).sort();
    const ref = reference(data);
    const lines = ["month-day,mean_1991_2020," + years.join(",")];
    DAYS.forEach(function (day, index) {
      lines.push([day, ref[index] == null ? "" : ref[index].toFixed(4)].concat(
        years.map(function (year) { const v = data.years[year][index]; return v == null ? "" : v.toFixed(4); })
      ).join(","));
    });
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "NOAA_OISST_" + current.region + "_Tageswerte.csv";
    document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  async function loadRegion() {
    const sequence = ++requestId;
    const region = el("sstYearsRegion").value;
    current = null;
    if (chart) { chart.destroy(); chart = null; }
    text("sstYearsMeta", "");
    text("sstYearsStatus", "Tägliche SST-Reihen werden geladen …");
    el("sstYearsPng").disabled = true;
    el("sstYearsCsv").disabled = true;
    try {
      const data = await getData(region);
      if (sequence !== requestId) return;
      current = { region, data };
      const years = Object.keys(data.years).sort();
      const select = el("sstYearsYear");
      const previous = select.value;
      select.innerHTML = "";
      years.forEach(function (year) {
        const option = document.createElement("option"); option.value = year; option.textContent = year;
        select.appendChild(option);
      });
      select.value = years.includes(previous) ? previous : years[years.length - 2];
      renderPlot();
    } catch (error) {
      if (sequence !== requestId) return;
      current = null;
      if (chart) { chart.destroy(); chart = null; }
      text("sstYearsStatus", (REGIONS[region][3] ? "Eigene Tagesreihe noch nicht verfügbar (Archivaufbau oder Datenverbindung): " : "Tagesdaten derzeit nicht verfügbar: ") + error.message);
      text("sstYearsMeta", REGIONS[region][3] ? "NOAA OISST v2.1 · Kartenausschnitt · 0,25°" : "Quelle: Earth Indicators, berechnet aus NOAA OISST v2.1.");
    }
  }
  function mount() {
    const tab = el("sst-europe");
    if (!tab || el("sstYearsSection")) return;
    const panel = document.createElement("section");
    panel.id = "sstYearsSection";
    panel.className = "sst-years-panel sst-europe-card";
    panel.innerHTML = '<h3>Jahresverläufe der Meeresoberflächentemperatur</h3>' +
      '<p class="sst-years-explain">Tägliche Gebietsmittel weltweit, für Ozeanregionen und unsere Kartenausschnitte. Alle Jahre im direkten Vergleich, aktuelles Jahr rot und Klimamittel gelb.</p>' +
      '<div class="sst-years-controls">' +
      '<label>SST-Gebiet<select id="sstYearsRegion">' +
      Object.entries(REGIONS).map(function ([key, region]) { return '<option value="' + key + '">' + region[0] + '</option>'; }).join('') + '</select></label>' +
      '<label>Darstellung<select id="sstYearsMetric"><option value="absolute">SST absolut (°C)</option><option value="anomaly">Abweichung zum Mittel (K)</option></select></label>' +
      '<label>Historische Jahre<select id="sstYearsHistory"><option value="all">Alle Jahre</option><option value="year">Einzeljahr hervorheben</option><option value="none">Nur aktuelles Jahr + Mittel</option></select></label>' +
      '<label>Vergleichsjahr<select id="sstYearsYear"></select></label>' +
      '</div>' +
      '<div class="sst-years-actions"><span class="sst-years-legend"><b class="sst-years-red"></b> Aktuelles Jahr <b class="sst-years-yellow"></b> Mittel 1991–2020 <b class="sst-years-blue"></b> Ältere Jahre</span>' +
      '<button id="sstYearsPng" type="button" disabled>PNG</button><button id="sstYearsCsv" type="button" disabled>CSV</button></div>' +
      '<div class="sst-years-graph"><canvas id="sstYearsCanvas" role="img" aria-label="Tägliche SST aller Jahre im Vergleich"></canvas></div>' +
      '<p id="sstYearsStatus" class="sst-years-status" aria-live="polite"></p><p id="sstYearsMeta" class="sst-years-meta"></p>' +
      '<p class="sst-years-source">Daten: <a href="https://earthindicators.org/methods.html" target="_blank" rel="noopener noreferrer">Earth Indicators</a> und eigene flächengewichtete Mittel aus <a href="https://psl.noaa.gov/data/gridded/data.noaa.oisst.v2.highres.html" target="_blank" rel="noopener noreferrer">NOAA OISST v2.1</a>. Die eigenen Reihen nutzen alle gültigen SST-Gitterpunkte der rechteckigen Kartenausschnitte einschließlich der SST-Schätzung unter Meereis; das Mittelmeer-Fenster enthält daher auch angrenzende Meeresflächen. Die globale Standardreihe reicht von 60°S bis 60°N. Niño-Tageswerte sind nicht der offizielle 3-Monats-ONI. Jüngste OISST-Tage sind vorläufig.</p>';
    tab.appendChild(panel);
    ["sstYearsMetric", "sstYearsHistory", "sstYearsYear"].forEach(function (id) {
      el(id).addEventListener("change", renderPlot);
    });
    el("sstYearsRegion").addEventListener("change", loadRegion);
    el("sstYearsPng").addEventListener("click", function () {
      if (!chart || !current) return;
      const anchor = document.createElement("a");
      anchor.href = chart.toBase64Image("image/png", 1);
      anchor.download = "SST_" + current.region + "_Jahresverlauf.png";
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
    });
    el("sstYearsCsv").addEventListener("click", exportCsv);
    const mapRegion = el("sstRegion");
    if (mapRegion && mapRegion.value === "nino34") el("sstYearsRegion").value = "nino34";
    if (mapRegion) mapRegion.addEventListener("change", function () {
      if (REGIONS[mapRegion.value]) { el("sstYearsRegion").value = mapRegion.value; loadRegion(); }
    });
    loadRegion();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
