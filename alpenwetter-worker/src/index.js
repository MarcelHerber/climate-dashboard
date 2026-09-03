const SESSION_COOKIE = "alpenwetter_session";
const SESSION_TTL_SECONDS = 12 * 60 * 60;

const encoder = new TextEncoder();

export default {
  async fetch(request, env) {
    if (!env.ALPENWETTER_PASSWORD) {
      return htmlResponse(
        "<h1>Alpenwetter ist noch nicht freigeschaltet</h1><p>Der Server-Secret <code>ALPENWETTER_PASSWORD</code> fehlt.</p>",
        503
      );
    }

    const url = new URL(request.url);

    if (url.pathname === "/login" && request.method === "POST") {
      return handleLogin(request, env);
    }

    if (url.pathname === "/logout" && request.method === "POST") {
      return redirect("/", clearSessionCookie());
    }

    const authenticated = await hasValidSession(request, env.ALPENWETTER_PASSWORD);

    if (!authenticated) {
      if (url.pathname.startsWith("/api/")) {
        return jsonResponse({ error: "Nicht angemeldet" }, 401);
      }
      return loginPage(false);
    }

    if (url.pathname === "/api/regions") {
      return proxyRegions();
    }

    if (url.pathname === "/api/ratings") {
      return proxyRatings(url);
    }

    if (url.pathname !== "/") {
      return new Response("Nicht gefunden", {
        status: 404,
        headers: securityHeaders({ "Content-Type": "text/plain; charset=utf-8" }),
      });
    }

    return protectedPage();
  },
};

async function handleLogin(request, env) {
  let form;
  try {
    form = await request.formData();
  } catch {
    return loginPage(true);
  }

  const submitted = String(form.get("password") || "");
  const ok = await passwordsMatch(submitted, env.ALPENWETTER_PASSWORD);

  if (!ok) {
    return loginPage(true);
  }

  const cookie = await createSessionCookie(env.ALPENWETTER_PASSWORD);
  return redirect("/", cookie);
}

async function passwordsMatch(a, b) {
  const [ha, hb] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(a)),
    crypto.subtle.digest("SHA-256", encoder.encode(b)),
  ]);
  return timingSafeEqual(new Uint8Array(ha), new Uint8Array(hb));
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function createSessionCookie(secret) {
  const expires = Date.now() + SESSION_TTL_SECONDS * 1000;
  const payload = String(expires);
  const signature = await sign(payload, secret);
  const token = payload + "." + signature;

  return (
    SESSION_COOKIE +
    "=" +
    token +
    "; Max-Age=" +
    SESSION_TTL_SECONDS +
    "; Path=/; HttpOnly; Secure; SameSite=Strict"
  );
}

function clearSessionCookie() {
  return SESSION_COOKIE + "=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Strict";
}

async function hasValidSession(request, secret) {
  const cookieHeader = request.headers.get("Cookie") || "";
  const cookies = parseCookies(cookieHeader);
  const token = cookies[SESSION_COOKIE];
  if (!token) return false;

  const dot = token.indexOf(".");
  if (dot <= 0) return false;

  const payload = token.slice(0, dot);
  const suppliedSignature = token.slice(dot + 1);
  const expires = Number(payload);

  if (!Number.isFinite(expires) || expires <= Date.now()) return false;

  const expectedSignature = await sign(payload, secret);
  return constantTimeStringEqual(suppliedSignature, expectedSignature);
}

async function sign(payload, secret) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const raw = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return base64Url(new Uint8Array(raw));
}

function base64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function constantTimeStringEqual(a, b) {
  const aa = encoder.encode(a);
  const bb = encoder.encode(b);
  return timingSafeEqual(aa, bb);
}

function parseCookies(header) {
  const out = {};
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    const key = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    if (key) out[key] = value;
  }
  return out;
}

function redirect(location, setCookie) {
  const headers = securityHeaders({ Location: location });
  if (setCookie) headers.set("Set-Cookie", setCookie);
  return new Response(null, { status: 303, headers });
}

async function proxyRegions() {
  const sourceUrl = "https://eaws.gitlab.io/eaws-regions/micro-regions_elevation.geojson";
  try {
    const response = await fetch(sourceUrl, {
      cf: { cacheTtl: 21600, cacheEverything: true },
      headers: { "User-Agent": "ClimateDashboard-Alpenwetter/1.0" },
    });
    if (!response.ok) {
      return jsonResponse({ error: "Regionsdaten konnten nicht geladen werden.", status: response.status }, 502);
    }
    const data = await response.json();
    const features = Array.isArray(data?.features) ? data.features.filter(isAlpineFeature) : [];
    return jsonResponse({
      type: "FeatureCollection",
      features,
      source: "EAWS Regions",
      sourceUrl: "https://eaws.gitlab.io/eaws-regions/",
    });
  } catch (error) {
    return jsonResponse({ error: "Regionsdaten konnten nicht geladen werden.", detail: String(error?.message || error) }, 502);
  }
}

async function proxyRatings(url) {
  const requested = String(url.searchParams.get("date") || "").trim();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(requested) ? requested : isoDate(new Date());

  for (let offset = 0; offset <= 10; offset += 1) {
    const candidateDate = shiftDate(date, -offset);
    const candidates = [
      `https://static.avalanche.report/eaws_bulletins/${candidateDate}/${candidateDate}.ratings.json`,
      `https://static.avalanche.report/eaws_bulletins/eaws_bulletins/${candidateDate}/${candidateDate}.ratings.json`,
    ];

    for (const sourceUrl of candidates) {
      try {
        const response = await fetch(sourceUrl, {
          cf: { cacheTtl: 1800, cacheEverything: true },
          headers: { "User-Agent": "ClimateDashboard-Alpenwetter/1.0" },
        });
        if (!response.ok) continue;
        const data = await response.json();
        return jsonResponse({
          requestedDate: date,
          dataDate: candidateDate,
          fallbackDays: offset,
          ratings: data,
          source: "avalanche.report / EAWS",
        });
      } catch {
        // Nächsten Kandidaten probieren.
      }
    }
  }

  return jsonResponse({
    error: "Für das gewählte Datum und die zehn Tage davor wurden keine zusammengefassten Lawinenwarnstufen gefunden.",
    requestedDate: date,
  }, 404);
}

function isAlpineFeature(feature) {
  const p = feature?.properties || {};
  const id = String(p.id || p.region_id || p.regionId || "");
  if (/^(AT-|CH|DE-BY|SI)/.test(id)) return true;

  const bounds = geometryBounds(feature?.geometry);
  if (!bounds) return false;

  const intersectsAlps =
    bounds.maxLon >= 4.0 &&
    bounds.minLon <= 16.3 &&
    bounds.maxLat >= 43.4 &&
    bounds.minLat <= 49.2;

  if (/^IT-/.test(id)) return intersectsAlps && bounds.maxLat >= 44.4;
  if (/^FR/.test(id)) return intersectsAlps && bounds.maxLon >= 4.5 && bounds.minLon <= 8.5;
  return false;
}

function geometryBounds(geometry) {
  if (!geometry?.coordinates) return null;
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  const visit = (node) => {
    if (!Array.isArray(node)) return;
    if (node.length >= 2 && typeof node[0] === "number" && typeof node[1] === "number") {
      const lon = node[0], lat = node[1];
      minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
      return;
    }
    for (const child of node) visit(child);
  };
  visit(geometry.coordinates);
  return Number.isFinite(minLon) ? { minLon, maxLon, minLat, maxLat } : null;
}

function shiftDate(iso, days) {
  const d = new Date(iso + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: securityHeaders({
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, max-age=0",
    }),
  });
}

function loginPage(hasError) {
  const error = hasError
    ? '<div class="error">Kennwort nicht korrekt.</div>'
    : "";

  return htmlResponse(`<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <title>Alpenwetter · Anmeldung</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0b1220; color: #eef3f8; padding: 24px; }
    .card { width: min(430px, 100%); background: #131d2c; border: 1px solid #263449; border-radius: 18px; padding: 28px; box-shadow: 0 20px 70px rgba(0,0,0,.35); }
    .eyebrow { color: #91a8c5; font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    h1 { margin: 8px 0 8px; font-size: 28px; }
    p { margin: 0 0 22px; color: #b9c7d8; line-height: 1.5; }
    label { display: block; margin-bottom: 8px; font-weight: 700; }
    input { width: 100%; border: 1px solid #3a4b63; border-radius: 10px; padding: 12px 13px; background: #0d1624; color: #fff; font: inherit; outline: none; }
    input:focus { border-color: #91a8c5; box-shadow: 0 0 0 3px rgba(145,168,197,.15); }
    button { width: 100%; margin-top: 14px; border: 0; border-radius: 10px; padding: 12px 14px; font: inherit; font-weight: 800; cursor: pointer; background: #eef3f8; color: #101827; }
    .error { margin: 0 0 16px; border: 1px solid #9b4d55; background: #3b1d23; color: #ffd9dd; border-radius: 10px; padding: 10px 12px; }
    .note { margin-top: 18px; font-size: 12px; color: #7f91a7; }
  </style>
</head>
<body>
  <main class="card">
    <div class="eyebrow">Geschützter Bereich</div>
    <h1>Alpenwetter</h1>
    <p>Dieser Bereich ist nicht öffentlich. Bitte Kennwort eingeben.</p>
    ${error}
    <form method="post" action="/login">
      <label for="password">Kennwort</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
      <button type="submit">Anmelden</button>
    </form>
    <div class="note">Die Sitzung bleibt nach erfolgreicher Anmeldung bis zu 12 Stunden gültig.</div>
  </main>
</body>
</html>`, hasError ? 401 : 200);
}

function protectedPage() {
  return htmlResponse(`<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <title>Alpenwetter · Lawinengefahr</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #0b1220; color: #eef3f8; min-height: 100vh; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 26px; border-bottom: 1px solid #263449; background: #101827; position: sticky; top: 0; z-index: 5; }
    h1 { margin: 0; font-size: 24px; }
    h2, h3 { margin-top: 0; }
    .badge { display: inline-block; margin-left: 10px; vertical-align: middle; font-size: 11px; letter-spacing: .05em; text-transform: uppercase; background: #1d3a2f; color: #bdf2d5; padding: 5px 8px; border-radius: 999px; }
    main { width: min(1320px, calc(100% - 32px)); margin: 24px auto 48px; }
    .card { border: 1px solid #263449; background: #131d2c; border-radius: 16px; padding: 20px; box-shadow: 0 10px 35px rgba(0,0,0,.14); }
    .intro { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 16px; }
    .intro p, .muted { color: #aebed1; line-height: 1.5; }
    .controls { display: grid; grid-template-columns: minmax(160px, 210px) minmax(210px, 260px) auto 1fr; gap: 12px; align-items: end; margin: 16px 0; }
    .control label { display: block; font-size: 12px; font-weight: 800; color: #9fb0c5; margin-bottom: 6px; text-transform: uppercase; letter-spacing: .04em; }
    input, select { width: 100%; border: 1px solid #3a4b63; border-radius: 9px; padding: 10px 11px; background: #0d1624; color: #fff; font: inherit; }
    button { border: 1px solid #3a4b63; background: #172235; color: #eef3f8; padding: 10px 13px; border-radius: 9px; font: inherit; font-weight: 750; cursor: pointer; }
    button:hover { background: #21304a; }
    .primary { background: #eef3f8; color: #101827; border-color: #eef3f8; }
    .primary:hover { background: #dbe4ee; }
    .status { min-height: 42px; display: flex; align-items: center; padding: 10px 12px; border-radius: 10px; background: #0e1726; border: 1px solid #233146; color: #b8c7d9; font-size: 14px; }
    .status.error { border-color: #7d3942; color: #ffd2d8; background: #33191e; }
    .layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; margin-top: 16px; }
    .map-card { padding: 12px; overflow: hidden; }
    .map-shell { position: relative; min-height: 560px; border-radius: 12px; overflow: hidden; background: radial-gradient(circle at 54% 46%, #24344a 0, #172335 35%, #0e1725 78%); border: 1px solid #263449; }
    #avalancheMap { width: 100%; height: auto; min-height: 560px; display: block; }
    #avalancheMap path { transition: opacity .12s ease, stroke-width .12s ease; cursor: pointer; }
    #avalancheMap path:hover { opacity: .82; stroke-width: 1.8; }
    #avalancheMap path.selected { stroke: #fff; stroke-width: 3; }
    .map-label { position: absolute; left: 14px; top: 12px; background: rgba(10,18,30,.86); border: 1px solid #2b3a50; border-radius: 9px; padding: 8px 10px; font-size: 12px; color: #b7c6d7; pointer-events: none; }
    .legend { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .legend-item { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; color: #b8c7d9; }
    .swatch { width: 22px; height: 14px; border-radius: 3px; border: 1px solid rgba(255,255,255,.38); }
    .detail { min-height: 560px; }
    .region-id { font-size: 12px; color: #91a4bb; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; margin-bottom: 6px; }
    .danger-big { display: flex; gap: 12px; align-items: center; margin: 15px 0; padding: 14px; border-radius: 12px; background: #0e1726; }
    .danger-number { width: 58px; height: 58px; border-radius: 12px; display: grid; place-items: center; font-size: 28px; font-weight: 900; color: #111; border: 1px solid rgba(255,255,255,.45); }
    .danger-copy strong { display: block; font-size: 17px; }
    .danger-copy span { color: #9eb0c5; font-size: 13px; }
    .rating-grid { display: grid; grid-template-columns: 1fr 48px; gap: 0; border-top: 1px solid #27364a; margin-top: 14px; }
    .rating-grid div { padding: 8px 4px; border-bottom: 1px solid #27364a; font-size: 13px; }
    .rating-grid div:nth-child(even) { text-align: right; font-weight: 800; }
    .source-note { margin-top: 14px; font-size: 12px; color: #8195ac; line-height: 1.5; }
    .empty { color: #8fa2b9; line-height: 1.55; }
    @media (max-width: 900px) {
      .controls { grid-template-columns: 1fr 1fr; }
      .layout { grid-template-columns: 1fr; }
      .detail { min-height: auto; }
    }
    @media (max-width: 560px) {
      header { padding: 15px 16px; }
      h1 { font-size: 20px; }
      main { width: min(100% - 20px, 1320px); }
      .intro { display: block; }
      .controls { grid-template-columns: 1fr; }
      .map-shell, #avalancheMap { min-height: 420px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Alpenwetter <span class="badge">geschützt</span></h1>
    <form method="post" action="/logout"><button type="submit">Abmelden</button></form>
  </header>

  <main>
    <section class="card">
      <div class="intro">
        <div>
          <h2>Lawinengefahr im Alpenraum</h2>
          <p class="muted">EAWS-Warnregionen mit der jeweils gewählten Gefahrenstufe. Weiß bzw. grau bedeutet: für diese Ansicht liegt keine Einstufung vor.</p>
        </div>
      </div>

      <div class="controls">
        <div class="control">
          <label for="forecastDate">Datum</label>
          <input id="forecastDate" type="date">
        </div>
        <div class="control">
          <label for="ratingMode">Darstellung</label>
          <select id="ratingMode">
            <option value="">Höchste Warnstufe</option>
            <option value="am">Vormittag</option>
            <option value="pm">Nachmittag</option>
            <option value="high">Hochlagen</option>
            <option value="low">Tieflagen</option>
            <option value="high:am">Hochlagen · Vormittag</option>
            <option value="high:pm">Hochlagen · Nachmittag</option>
            <option value="low:am">Tieflagen · Vormittag</option>
            <option value="low:pm">Tieflagen · Nachmittag</option>
          </select>
        </div>
        <button id="reloadButton" class="primary" type="button">Laden</button>
        <div id="status" class="status">Lawinendaten werden vorbereitet …</div>
      </div>

      <div class="layout">
        <section class="card map-card">
          <div class="map-shell">
            <div class="map-label">Alpenraum · EAWS-Regionen</div>
            <svg id="avalancheMap" viewBox="0 0 1000 600" role="img" aria-label="Karte der Lawinenwarnstufen im Alpenraum"></svg>
          </div>
          <div class="legend" aria-label="Legende">
            <span class="legend-item"><span class="swatch" style="background:#d8d8d8"></span>keine Einstufung</span>
            <span class="legend-item"><span class="swatch" style="background:#7ecb55"></span>1 gering</span>
            <span class="legend-item"><span class="swatch" style="background:#f3df3f"></span>2 mäßig</span>
            <span class="legend-item"><span class="swatch" style="background:#f39b33"></span>3 erheblich</span>
            <span class="legend-item"><span class="swatch" style="background:#df413b"></span>4 groß</span>
            <span class="legend-item"><span class="swatch" style="background:#262626"></span>5 sehr groß</span>
          </div>
        </section>

        <aside class="card detail">
          <h3>Regionsdetails</h3>
          <div id="detailContent" class="empty">Klicke auf eine Warnregion in der Karte, um die verfügbaren Warnstufen anzuzeigen.</div>
          <div class="source-note">
            Quelle: EAWS / avalanche.report. Die Karte ist eine Übersicht; maßgeblich bleibt der jeweilige offizielle Lawinenwarndienst und dessen Bulletin.
          </div>
        </aside>
      </div>
    </section>
  </main>

  <script>
    (function () {
      "use strict";

      var NS = "http://www.w3.org/2000/svg";
      var MAP_BOUNDS = { minLon: 4.0, maxLon: 16.3, minLat: 43.4, maxLat: 49.2 };
      var COLORS = {
        0: "#d8d8d8",
        1: "#7ecb55",
        2: "#f3df3f",
        3: "#f39b33",
        4: "#df413b",
        5: "#262626"
      };
      var LABELS = {
        0: "keine Einstufung",
        1: "gering",
        2: "mäßig",
        3: "erheblich",
        4: "groß",
        5: "sehr groß"
      };
      var state = { regions: null, ratingsPayload: null, selectedId: null };

      var dateInput = document.getElementById("forecastDate");
      var modeSelect = document.getElementById("ratingMode");
      var reloadButton = document.getElementById("reloadButton");
      var statusEl = document.getElementById("status");
      var mapEl = document.getElementById("avalancheMap");
      var detailEl = document.getElementById("detailContent");

      dateInput.value = new Date().toISOString().slice(0, 10);

      reloadButton.addEventListener("click", loadAll);
      dateInput.addEventListener("change", loadAll);
      modeSelect.addEventListener("change", function () {
        renderMap();
        if (state.selectedId) renderDetail(state.selectedId);
      });

      function setStatus(text, isError) {
        statusEl.textContent = text;
        statusEl.className = isError ? "status error" : "status";
      }

      async function loadAll() {
        setStatus("EAWS-Regionen und Warnstufen werden geladen …", false);
        reloadButton.disabled = true;

        try {
          if (!state.regions) {
            var regionResponse = await fetch("/api/regions", { credentials: "same-origin" });
            if (!regionResponse.ok) throw new Error("Regionsdaten: HTTP " + regionResponse.status);
            state.regions = await regionResponse.json();
          }

          var selectedDate = dateInput.value || new Date().toISOString().slice(0, 10);
          var ratingResponse = await fetch("/api/ratings?date=" + encodeURIComponent(selectedDate), { credentials: "same-origin" });
          state.ratingsPayload = await ratingResponse.json();

          if (!ratingResponse.ok) {
            state.ratingsPayload = {
              requestedDate: selectedDate,
              dataDate: null,
              ratings: { maxDangerRatings: {} },
              error: state.ratingsPayload && state.ratingsPayload.error
            };
          }

          renderMap();
          if (state.selectedId) renderDetail(state.selectedId);

          var regionCount = uniqueRegionIds().length;
          var mappedCount = countRatedRegions();
          var dateInfo = state.ratingsPayload.dataDate
            ? "Datenstand " + formatDate(state.ratingsPayload.dataDate)
            : "keine Warnstufendatei gefunden";
          var fallback = Number(state.ratingsPayload.fallbackDays || 0);
          var fallbackInfo = fallback > 0 ? " · " + fallback + " Tag(e) zurückgegriffen" : "";
          setStatus(regionCount + " Alpenregionen · " + mappedCount + " mit Einstufung · " + dateInfo + fallbackInfo, false);
        } catch (error) {
          setStatus("Laden fehlgeschlagen: " + String(error && error.message ? error.message : error), true);
        } finally {
          reloadButton.disabled = false;
        }
      }

      function getRatings() {
        var p = state.ratingsPayload || {};
        var r = p.ratings || {};
        return r.maxDangerRatings || r.ratings || p.maxDangerRatings || {};
      }

      function featureId(feature) {
        var p = (feature && feature.properties) || {};
        return String(p.id || p.region_id || p.regionId || p.code || p.region || "unbekannt");
      }

      function featureName(feature) {
        var p = (feature && feature.properties) || {};
        return String(p.name_de || p.name || p.label || p.region_name || featureId(feature));
      }

      function modeKey(id) {
        var mode = modeSelect.value || "";
        return mode ? id + ":" + mode : id;
      }

      function dangerForId(id) {
        var ratings = getRatings();
        var raw = ratings[modeKey(id)];
        if (raw === undefined || raw === null || raw === "") return 0;
        var value = Number(raw);
        return Number.isFinite(value) && value >= 1 && value <= 5 ? Math.round(value) : 0;
      }

      function dangerValue(id, suffix) {
        var ratings = getRatings();
        var key = suffix ? id + ":" + suffix : id;
        var value = Number(ratings[key]);
        return Number.isFinite(value) && value >= 1 && value <= 5 ? Math.round(value) : 0;
      }

      function uniqueRegionIds() {
        var ids = {};
        var features = state.regions && Array.isArray(state.regions.features) ? state.regions.features : [];
        features.forEach(function (f) { ids[featureId(f)] = true; });
        return Object.keys(ids);
      }

      function countRatedRegions() {
        return uniqueRegionIds().filter(function (id) { return dangerForId(id) > 0; }).length;
      }

      function renderMap() {
        while (mapEl.firstChild) mapEl.removeChild(mapEl.firstChild);
        var features = state.regions && Array.isArray(state.regions.features) ? state.regions.features : [];

        features.forEach(function (feature) {
          var id = featureId(feature);
          var danger = dangerForId(id);
          var pathData = geometryToPath(feature.geometry);
          if (!pathData) return;

          var path = document.createElementNS(NS, "path");
          path.setAttribute("d", pathData);
          path.setAttribute("fill", COLORS[danger] || COLORS[0]);
          path.setAttribute("fill-rule", "evenodd");
          path.setAttribute("stroke", "#31435b");
          path.setAttribute("stroke-width", "0.8");
          path.setAttribute("vector-effect", "non-scaling-stroke");
          path.setAttribute("data-region-id", id);
          if (id === state.selectedId) path.classList.add("selected");

          var title = document.createElementNS(NS, "title");
          title.textContent = featureName(feature) + " · " + id + " · " + (danger ? "Stufe " + danger + " (" + LABELS[danger] + ")" : "keine Einstufung");
          path.appendChild(title);

          path.addEventListener("click", function () {
            state.selectedId = id;
            renderMap();
            renderDetail(id);
          });

          mapEl.appendChild(path);
        });

        if (!features.length) {
          var message = document.createElementNS(NS, "text");
          message.setAttribute("x", "500");
          message.setAttribute("y", "300");
          message.setAttribute("text-anchor", "middle");
          message.setAttribute("fill", "#b7c6d7");
          message.setAttribute("font-size", "22");
          message.textContent = "Keine EAWS-Regionsgeometrien geladen";
          mapEl.appendChild(message);
        }
      }

      function renderDetail(id) {
        var features = state.regions && Array.isArray(state.regions.features) ? state.regions.features : [];
        var feature = features.find(function (f) { return featureId(f) === id; });
        var name = feature ? featureName(feature) : id;
        var danger = dangerForId(id);
        var color = COLORS[danger] || COLORS[0];

        var rows = [
          ["Maximum", dangerValue(id, "")],
          ["Vormittag", dangerValue(id, "am")],
          ["Nachmittag", dangerValue(id, "pm")],
          ["Hochlagen", dangerValue(id, "high")],
          ["Tieflagen", dangerValue(id, "low")],
          ["Hoch · Vormittag", dangerValue(id, "high:am")],
          ["Hoch · Nachmittag", dangerValue(id, "high:pm")],
          ["Tief · Vormittag", dangerValue(id, "low:am")],
          ["Tief · Nachmittag", dangerValue(id, "low:pm")]
        ];

        var rowHtml = rows.map(function (row) {
          return "<div>" + escapeHtml(row[0]) + "</div><div>" + (row[1] || "–") + "</div>";
        }).join("");

        detailEl.className = "";
        detailEl.innerHTML =
          '<div class="region-id">' + escapeHtml(id) + '</div>' +
          '<h3>' + escapeHtml(name) + '</h3>' +
          '<div class="danger-big">' +
            '<div class="danger-number" style="background:' + color + '">' + (danger || "–") + '</div>' +
            '<div class="danger-copy"><strong>' + (danger ? "Stufe " + danger + " · " + LABELS[danger] : "Keine Einstufung") + '</strong>' +
            '<span>' + escapeHtml(modeSelect.options[modeSelect.selectedIndex].text) + '</span></div>' +
          '</div>' +
          '<div class="rating-grid">' + rowHtml + '</div>';
      }

      function geometryToPath(geometry) {
        if (!geometry || !geometry.coordinates) return "";
        if (geometry.type === "Polygon") return polygonToPath(geometry.coordinates);
        if (geometry.type === "MultiPolygon") {
          return geometry.coordinates.map(polygonToPath).join(" ");
        }
        return "";
      }

      function polygonToPath(rings) {
        if (!Array.isArray(rings)) return "";
        return rings.map(function (ring) {
          if (!Array.isArray(ring) || !ring.length) return "";
          var parts = [];
          ring.forEach(function (point, index) {
            if (!Array.isArray(point) || point.length < 2) return;
            var xy = project(Number(point[0]), Number(point[1]));
            parts.push((index === 0 ? "M" : "L") + xy[0].toFixed(1) + "," + xy[1].toFixed(1));
          });
          if (parts.length) parts.push("Z");
          return parts.join(" ");
        }).join(" ");
      }

      function project(lon, lat) {
        var x = (lon - MAP_BOUNDS.minLon) / (MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon) * 1000;
        var y = (MAP_BOUNDS.maxLat - lat) / (MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat) * 600;
        return [x, y];
      }

      function formatDate(value) {
        if (!value) return "–";
        var parts = value.split("-");
        return parts.length === 3 ? parts[2] + "." + parts[1] + "." + parts[0] : value;
      }

      function escapeHtml(value) {
        return String(value == null ? "" : value)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#039;");
      }

      loadAll();
    })();
  </script>
</body>
</html>`);
}

function htmlResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: securityHeaders({ "Content-Type": "text/html; charset=utf-8" }),
  });
}

function securityHeaders(extra = {}) {
  const headers = new Headers(extra);
  headers.set("Cache-Control", "no-store, max-age=0");
  headers.set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  return headers;
}
