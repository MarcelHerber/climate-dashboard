/* Resilient basemap for Europe station records.
   Natural Earth countries are shipped with the site, so national outlines
   remain visible even when third-party raster tile servers are blocked. */
(function () {
  "use strict";
  const LOCAL_GEOGRAPHY = "wettergefahren_basemap.json"; // Published root asset, Natural Earth public domain.
  // OSM standard raster tiles do not require a CARTO API key.
  // They are an OPTIONAL detail layer: self-hosted borders are the baseline.
  const TILE_SERVERS = [{
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    opts: { maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende' }
  }];
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
    // The geographic borders MUST sit ABOVE raster image tiles. Previously
    // z-index 195 hid them below CARTO's opaque "API KEY REQUIRED" images.
    // Keep the borders BELOW the station canvas (overlayPane = 400).
    pane.style.zIndex = "350"; // tilePane = 200, overlayPane = 400
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
          // The stations map uses preferCanvas:true for thousands of markers.
          // Force its basemap countries into a separate SVG renderer; otherwise
          // the vector fallback shares a canvas and may disappear behind tiles.
          renderer: window.L.svg({ pane: paneName, padding: .15 }),
          pane: paneName,
          interactive: false,
          style: {
            color: "#92a5ae",
            opacity: .95,
            weight: 1.1,
            fillColor: "#e7ebea",
            fillOpacity: .94
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
    const container = map.getContainer?.();
    if (container) container.style.backgroundColor = "#dcebf2";
    // The local Natural Earth SVG layer is always on and is above the raster.
    // Raster tiles only provide additional roads and place labels when available.
    const geography = createCountryFallback(map);
    let tileLayer = null;
    let successCount = 0;
    let errorCount = 0;
    let rasterDisabled = false;
    let watchdog = null;

    function clearWatchdog() {
      if (watchdog !== null) {
        clearTimeout(watchdog);
        watchdog = null;
      }
    }
    function updateLocalLayer() {
      const vector = map.__europeStationGeographyLayer;
      if (vector?.setStyle) vector.setStyle({
        fillOpacity: rasterDisabled || !successCount ? .94 : .12
      });
    }
    function disableRaster(message) {
      if (rasterDisabled) return;
      rasterDisabled = true;
      clearWatchdog();
      if (tileLayer) {
        map.removeLayer(tileLayer);
        tileLayer = null;
      }
      updateLocalLayer();
      setStatus(message || "Kartendetails nicht erreichbar · lokale Ländergrenzen bleiben sichtbar");
    }

    geography.then(ok => {
      updateLocalLayer();
      if (!ok) setStatus("Lokale Ländergrenzen konnten nicht geladen werden");
      else if (!rasterDisabled && successCount > 0) setStatus("");
    });
    // Never request CARTO: their key-required placeholder is a valid image and
    // therefore fooled tileload-based fallback detection.
    const source = TILE_SERVERS[0];
    tileLayer = window.L.tileLayer(source.url, source.opts);
    tileLayer.on("tileload", () => {
      if (rasterDisabled) return;
      successCount++;
      clearWatchdog();
      updateLocalLayer();
      if (map.__europeStationGeographyLayer) setStatus("");
    });
    tileLayer.on("tileerror", () => {
      if (rasterDisabled) return;
      errorCount++;
      if (errorCount >= 2) disableRaster();
    });
    tileLayer.addTo(map);
    watchdog = setTimeout(() => {
      if (!successCount) disableRaster("Kartenserver antwortet nicht · lokale Ländergrenzen bleiben sichtbar");
    }, 7000);
    map.on("unload", clearWatchdog);
    map.__europeStationGetBasemapState = () => ({
      sourceIndex: rasterDisabled ? -1 : 0,
      successCount,
      errorCount,
      rasterDisabled,
      geographyLoaded: !!map.__europeStationGeographyLayer
    });
  }

  window.ensureEuropeStationLeaflet = ensureLeaflet;
  window.attachEuropeStationBasemap = attach;
})();