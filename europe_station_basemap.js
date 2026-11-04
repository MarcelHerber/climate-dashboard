/* Resilient basemap for Europe station records.
   Natural Earth countries are shipped with the site, so national outlines
   remain visible even when third-party raster tile servers are blocked. */
(function () {
  "use strict";
  const LOCAL_GEOGRAPHY = "wettergefahren_basemap.json"; // Published root asset, Natural Earth public domain.
  const TILE_SERVERS = [
    {
      url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
      opts: { subdomains: "abcd", maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende &copy; CARTO' }
    },
    {
      url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      opts: { maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende' }
    }
  ];
  let leafletLoadPromise = null;

  function setStatus(message) {
    const el = document.getElementById("europeStationBasemapStatus");
    if (!el) return;
    el.textContent = message || "";
    el.hidden = !message;
  }

  function ensureLeaflet() {
    if (window.L?.map && window.L?.tileLayer && window.L?.geoJSON) {
      return Promise.resolve(window.L);
    }
    if (leafletLoadPromise) return leafletLoadPromise;
    leafletLoadPromise = new Promise((resolve, reject) => {
      let finished = false;
      let fallbackStarted = false;
      const started = Date.now();
      const finish = error => {
        if (finished) return;
        finished = true;
        clearInterval(interval);
        if (error) reject(error);
        else resolve(window.L);
      };
      function check() {
        if (window.L?.map && window.L?.tileLayer && window.L?.geoJSON) {
          finish();
          return;
        }
        const elapsed = Date.now() - started;
        if (elapsed >= 2500 && !fallbackStarted) {
          fallbackStarted = true;
          if (!document.getElementById("europeStationLeafletFallbackCss")) {
            const style = document.createElement("link");
            style.id = "europeStationLeafletFallbackCss";
            style.rel = "stylesheet";
            style.href = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css";
            document.head.appendChild(style);
          }
          const script = document.createElement("script");
          script.src = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js";
          script.async = true;
          script.onload = check;
          // A failed fallback CDN must not suppress a late response from
          // the original unpkg Leaflet script in index.html.
          script.onerror = () => {};
          document.head.appendChild(script);
        }
        if (elapsed >= 13000) finish(new Error("Kartenbibliothek nicht erreichbar (unpkg und jsDelivr)."));
      }
      const interval = setInterval(check, 100);
      check();
    }).finally(() => { leafletLoadPromise = null; });
    return leafletLoadPromise;
  }

  function createCountryFallback(map) {
    if (!map.createPane || !window.L?.geoJSON) return Promise.resolve(false);
    const paneName = "europeStationGeographyPane";
    const pane = map.getPane(paneName) || map.createPane(paneName);
    // The geographic vector layer sits *behind* fetched image tiles, while
    // the original record symbols stay above both in Leaflet's overlayPane.
    pane.style.zIndex = "195"; // tilePane = 200, overlayPane = 400
    pane.style.pointerEvents = "none";
    return fetch(LOCAL_GEOGRAPHY, { cache: "force-cache" })
      .then(response => {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(data => {
        if (!Array.isArray(data.countries) || data.countries.length < 30)
          throw new Error("Natural-Earth-Ländergeometrie unvollständig");
        const features = data.countries
          .filter(country => Array.isArray(country.p) && country.p.length)
          .map(country => ({
            type: "Feature",
            properties: { name: country.n || "" },
            geometry: { type: "MultiPolygon", coordinates: country.p }
          }));
        const layer = window.L.geoJSON({
          type: "FeatureCollection", features
        }, {
          pane: paneName,
          interactive: false,
          style: {
            color: "#92a5ae",
            opacity: .95,
            weight: 1.1,
            fillColor: "#e7ebea",
            fillOpacity: 1
          }
        }).addTo(map);
        map.__europeStationGeographyLayer = layer;
        return true;
      })
      .catch(error => {
        console.warn("Europa-Umrisskarte konnte nicht geladen werden:", error);
        return false;
      });
  }

  function attach(map) {
    if (!map || map.__europeStationBasemapAttached) return;
    map.__europeStationBasemapAttached = true;
    const geography = createCountryFallback(map);
    // Do not wait for the outside tile provider before allowing station records
    // to load; vector fallback and tiles are independent of station data.
    let currentLayer = null;
    let activeIndex = -1;
    let successCount = 0;
    let errorCount = 0;
    let watchdog = null;

    function clearWatchdog() {
      if (watchdog !== null) {
        clearTimeout(watchdog);
        watchdog = null;
      }
    }
    function select(index) {
      if (index < 0 || index >= TILE_SERVERS.length) return;
      if (activeIndex >= index) return;
      clearWatchdog();
      if (currentLayer) {
        map.removeLayer(currentLayer);
        currentLayer = null;
      }
      activeIndex = index;
      successCount = 0;
      errorCount = 0;
      const source = TILE_SERVERS[index];
      currentLayer = window.L.tileLayer(source.url, source.opts);
      const expectedIndex = index;
      currentLayer.on("tileload", () => {
        if (activeIndex !== expectedIndex) return;
        successCount++;
        clearWatchdog();
        setStatus("");
      });
      currentLayer.on("tileerror", () => {
        if (activeIndex !== expectedIndex) return;
        errorCount++;
        if (errorCount >= 2 && index + 1 < TILE_SERVERS.length)
          select(index + 1);
        else if (errorCount >= 2)
          setStatus("Kartenserver nicht erreichbar · europäische Länderumrisse bleiben sichtbar");
      });
      currentLayer.addTo(map);
      if (index > 0) setStatus("Kartenhintergrund: alternativer Kartenserver wird geprüft …");
      watchdog = setTimeout(() => {
        if (activeIndex !== expectedIndex || successCount) return;
        if (index + 1 < TILE_SERVERS.length) select(index + 1);
        else setStatus("Kartenserver antwortet nicht · europäische Länderumrisse bleiben sichtbar");
      }, 7000);
    }
    // Provide a geographic fallback before/independently from the tile load.
    // The tile load watchdog is not allowed to remove that fallback layer.
    geography.then(ok => {
      if (!ok && !successCount)
        setStatus("Kartenumrisse fehlen · prüfe den Hintergrundkarten-Dienst");
    });
    select(0);
    map.on("unload", clearWatchdog);
    map.__europeStationGetBasemapState = () => ({
      sourceIndex: activeIndex,
      successCount,
      errorCount,
      geographyLoaded: !!map.__europeStationGeographyLayer
    });
  }

  window.ensureEuropeStationLeaflet = ensureLeaflet;
  window.attachEuropeStationBasemap = attach;
})();