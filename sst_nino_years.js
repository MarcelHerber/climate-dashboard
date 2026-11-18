(function () {
  "use strict";
  // Daily SST by NOAA OISST v2.1, published as ready-to-use daily regional CSVs.
  // Source calculations: https://earthindicators.org/methods.html
  const BASE = "https://raw.githubusercontent.com/tsjuri/earthindicators/main/data/";
  const FALLBACK = "https://cdn.jsdelivr.net/gh/tsjuri/earthindicators@main/data/";
  const REGIONS = {
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
    const n = Number(value);
    return Number.isFinite(n) && n >= 10 && n <= 35 ? n : null;
  }
  function parseDailyCsv(csv) {
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
    return { years, lastDate, count, currentYear };
  }
  async function getData(region) {
    if (cache.has(region)) return cache.get(region);
    const file = REGIONS[region][1];
    const urlSuffix = file + "?t=" + Math.floor(Date.now() / 3600000);
    const promise = (async function () {
      let lastError;
      for (const base of [BASE, FALLBACK]) {
        try {
          const response = await fetch(base + urlSuffix, { cache: "no-store" });
          if (!response.ok) throw new Error("HTTP " + response.status);
          const data = parseDailyCsv(await response.text());
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
        normalized: true, parsing: false, spanGaps: true,
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
    text("sstYearsMeta", "NOAA OISST v2.1 · " + REGIONS[region][2] + " · " + years[0] + "–" +
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
      text("sstYearsStatus", "Tagesdaten derzeit nicht verfügbar: " + error.message);
      text("sstYearsMeta", "Quelle: Earth Indicators, berechnet aus NOAA OISST v2.1.");
    }
  }
  function mount() {
    const tab = el("sst-europe");
    if (!tab || el("sstYearsSection")) return;
    const panel = document.createElement("section");
    panel.id = "sstYearsSection";
    panel.className = "sst-years-panel sst-europe-card";
    panel.innerHTML = '<h3>Jahresverläufe der Meeresoberflächentemperatur</h3>' +
      '<p class="sst-years-explain">Tägliche Gebietsmittel der vier Niño-Regionen. Alle Jahre im direkten Vergleich, aktuelle Messreihe rot und Klimamittel gelb.</p>' +
      '<div class="sst-years-controls">' +
      '<label>Niño-Region<select id="sstYearsRegion"><option value="nino12" selected>Niño 1+2</option><option value="nino3">Niño 3</option><option value="nino34">Niño 3.4</option><option value="nino4">Niño 4</option></select></label>' +
      '<label>Darstellung<select id="sstYearsMetric"><option value="absolute">SST absolut (°C)</option><option value="anomaly">Abweichung zum Mittel (K)</option></select></label>' +
      '<label>Historische Jahre<select id="sstYearsHistory"><option value="all">Alle Jahre</option><option value="year">Einzeljahr hervorheben</option><option value="none">Nur aktuelles Jahr + Mittel</option></select></label>' +
      '<label>Vergleichsjahr<select id="sstYearsYear"></select></label>' +
      '</div>' +
      '<div class="sst-years-actions"><span class="sst-years-legend"><b class="sst-years-red"></b> Aktuelles Jahr <b class="sst-years-yellow"></b> Mittel 1991–2020 <b class="sst-years-blue"></b> Ältere Jahre</span>' +
      '<button id="sstYearsPng" type="button" disabled>PNG</button><button id="sstYearsCsv" type="button" disabled>CSV</button></div>' +
      '<div class="sst-years-graph"><canvas id="sstYearsCanvas" role="img" aria-label="Tägliche SST aller Jahre im Vergleich"></canvas></div>' +
      '<p id="sstYearsStatus" class="sst-years-status" aria-live="polite"></p><p id="sstYearsMeta" class="sst-years-meta"></p>' +
      '<p class="sst-years-source">Daten: <a href="https://earthindicators.org/nino.html" target="_blank" rel="noopener noreferrer">Earth Indicators</a> (tägliche Gebietsmittel aus <a href="https://psl.noaa.gov/data/gridded/data.noaa.oisst.v2.highres.html" target="_blank" rel="noopener noreferrer">NOAA OISST v2.1</a>). Nicht mit dem offiziellen 3-Monats-ONI gleichsetzen. Die jüngsten OISST-Tage sind vorläufig. Diese vier Niño-Boxen sind unabhängig von den Kartenausschnitten.</p>';
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
    loadRegion();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();