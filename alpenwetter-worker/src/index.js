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

    if (url.pathname === "/api/archive") {
      return proxyArchive();
    }

    if (url.pathname === "/assets/eaws-logo.png") {
      return proxyEawsLogo();
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

  const exact = url.searchParams.get("exact") === "1";
  const maxOffset = exact ? 0 : 10;

  for (let offset = 0; offset <= maxOffset; offset += 1) {
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


async function proxyArchive() {
  const sourceUrl = "https://static.avalanche.report/eaws_bulletins/";

  try {
    const response = await fetch(sourceUrl, {
      cf: { cacheTtl: 21600, cacheEverything: true },
      headers: { "User-Agent": "ClimateDashboard-Alpenwetter/1.0" },
    });

    if (!response.ok) {
      return jsonResponse({ error: "Lawinenarchiv konnte nicht geladen werden.", status: response.status }, 502);
    }

    const html = await response.text();
    const matches = html.match(/\b20\d{2}-\d{2}-\d{2}\//g) || [];
    const dates = [...new Set(matches.map((value) => value.slice(0, 10)))]
      .filter((value) => /^20\d{2}-\d{2}-\d{2}$/.test(value))
      .sort();

    return jsonResponse({
      dates,
      count: dates.length,
      firstDate: dates[0] || null,
      lastDate: dates[dates.length - 1] || null,
      source: "avalanche.report / EAWS",
      sourceUrl,
    });
  } catch (error) {
    return jsonResponse({
      error: "Lawinenarchiv konnte nicht geladen werden.",
      detail: String(error?.message || error),
    }, 502);
  }
}

async function proxyEawsLogo() {
  const sourceUrl = "https://www.avalanches.org/wp-content/uploads/2022/04/EAWS_Logo-4c-900px-150x47.png";

  try {
    const response = await fetch(sourceUrl, {
      cf: { cacheTtl: 86400, cacheEverything: true },
      headers: { "User-Agent": "ClimateDashboard-Alpenwetter/1.0" },
    });

    if (!response.ok) {
      return new Response("EAWS-Logo konnte nicht geladen werden.", {
        status: 502,
        headers: securityHeaders({ "Content-Type": "text/plain; charset=utf-8" }),
      });
    }

    const body = await response.arrayBuffer();
    return new Response(body, {
      status: 200,
      headers: securityHeaders({
        "Content-Type": "image/png",
        "Content-Disposition": 'inline; filename="eaws-logo.png"',
      }),
    });
  } catch (error) {
    return new Response("EAWS-Logo konnte nicht geladen werden.", {
      status: 502,
      headers: securityHeaders({ "Content-Type": "text/plain; charset=utf-8" }),
    });
  }
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
    .intro { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 14px; }
    .intro p, .muted { color: #aebed1; line-height: 1.5; }
    .tabs { display: flex; gap: 8px; margin: 0 0 18px; border-bottom: 1px solid #263449; padding-bottom: 12px; }
    .tab { border: 1px solid #33445c; background: #111b2b; color: #b8c7d9; padding: 9px 14px; border-radius: 9px; font: inherit; font-weight: 800; cursor: pointer; }
    .tab.active { background: #eef3f8; color: #101827; border-color: #eef3f8; }
    .view[hidden] { display: none !important; }

    .controls { display: grid; grid-template-columns: auto minmax(160px, 210px) minmax(210px, 260px) auto 1fr; gap: 10px; align-items: end; margin: 16px 0; }
    .date-nav { display: flex; gap: 6px; }
    .date-nav button { min-width: 42px; padding-inline: 10px; }
    .control label { display: block; font-size: 12px; font-weight: 800; color: #9fb0c5; margin-bottom: 6px; text-transform: uppercase; letter-spacing: .04em; }
    input, select { width: 100%; border: 1px solid #3a4b63; border-radius: 9px; padding: 10px 11px; background: #0d1624; color: #fff; font: inherit; }
    button { border: 1px solid #3a4b63; background: #172235; color: #eef3f8; padding: 10px 13px; border-radius: 9px; font: inherit; font-weight: 750; cursor: pointer; }
    button:hover:not(:disabled) { background: #21304a; }
    button:disabled { opacity: .4; cursor: not-allowed; }
    .primary { background: #eef3f8; color: #101827; border-color: #eef3f8; }
    .primary:hover:not(:disabled) { background: #dbe4ee; }
    .status { min-height: 42px; display: flex; align-items: center; padding: 10px 12px; border-radius: 10px; background: #0e1726; border: 1px solid #233146; color: #b8c7d9; font-size: 14px; }
    .status.error { border-color: #7d3942; color: #ffd2d8; background: #33191e; }
    .export-actions { display: flex; justify-content: flex-end; gap: 8px; margin: -4px 0 14px; }
    .export-actions button { min-width: 132px; }
    .export-actions .export-primary { background: #eef3f8; color: #101827; border-color: #eef3f8; }
    .export-actions .export-primary:hover:not(:disabled) { background: #dbe4ee; }

    .layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; margin-top: 16px; }
    .map-card { padding: 12px; overflow: hidden; }
    .map-shell { position: relative; min-height: 560px; border-radius: 12px; overflow: hidden; background: radial-gradient(circle at 54% 46%, #42566f 0, #2a3b52 38%, #1a2636 78%); border: 1px solid #33445c; cursor: grab; touch-action: none; user-select: none; }
    .map-shell.dragging { cursor: grabbing; }
    .map-toolbar { position: absolute; right: 12px; top: 12px; z-index: 3; display: flex; gap: 6px; }
    .map-toolbar button { min-width: 42px; height: 38px; padding: 7px 10px; background: rgba(10,18,30,.9); border-color: #44556d; box-shadow: 0 5px 18px rgba(0,0,0,.2); }
    .map-toolbar .map-reset { min-width: 66px; font-size: 12px; }
    #avalancheMap { width: 100%; height: auto; min-height: 560px; display: block; }
    #avalancheMap path { transition: opacity .12s ease, stroke-width .12s ease; cursor: pointer; }
    #avalancheMap path:hover { opacity: 1; stroke-width: 1.8; }
    #avalancheMap path.danger-5 { stroke: #ffffff; stroke-width: 2.6; }
    #avalancheMap path.danger-5:hover { opacity: 1; stroke-width: 3.2; }
    #avalancheMap path.selected { stroke: #fff; stroke-width: 3.4; }
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

    .archive-head { display: grid; grid-template-columns: auto minmax(120px, 150px) minmax(150px, 190px) auto 1fr; gap: 10px; align-items: end; margin-bottom: 18px; }
    .archive-head .nav-month { display: flex; gap: 6px; }
    .archive-summary { align-self: stretch; display: flex; align-items: center; padding: 10px 12px; border: 1px solid #263449; background: #0e1726; border-radius: 10px; color: #aebed1; font-size: 13px; }
    .calendar { border: 1px solid #27364a; border-radius: 14px; overflow: hidden; background: #0d1624; }
    .weekday-row, .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); }
    .weekday { padding: 10px 6px; text-align: center; font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: .05em; color: #8498b0; border-bottom: 1px solid #27364a; }
    .day-cell { min-height: 92px; border-right: 1px solid #202e40; border-bottom: 1px solid #202e40; padding: 7px; background: #101a29; position: relative; }
    .day-cell:nth-child(7n) { border-right: 0; }
    .day-cell.empty-day { background: #0a121d; }
    .day-number { font-size: 12px; font-weight: 800; color: #72869f; }
    .day-cell.available { background: #142235; cursor: pointer; }
    .day-cell.available:hover { background: #1b2d46; }
    .day-cell.available .day-number { color: #f1f5f9; }
    .day-cell.selected { outline: 2px solid #eef3f8; outline-offset: -2px; z-index: 1; }
    .available-pill { position: absolute; left: 7px; right: 7px; bottom: 7px; border-radius: 999px; padding: 5px 6px; background: #1d3a2f; color: #bdf2d5; font-size: 10px; font-weight: 850; text-align: center; }
    .missing-pill { position: absolute; left: 7px; right: 7px; bottom: 7px; color: #5e7189; font-size: 10px; text-align: center; }
    .archive-note { margin-top: 14px; color: #8296ad; font-size: 12px; line-height: 1.5; }

    @media (max-width: 980px) {
      .controls { grid-template-columns: auto 1fr 1fr; }
      .status { grid-column: 1 / -1; }
      .layout { grid-template-columns: 1fr; }
      .detail { min-height: auto; }
      .archive-head { grid-template-columns: auto 1fr 1fr; }
      .archive-summary { grid-column: 1 / -1; }
    }
    @media (max-width: 620px) {
      header { padding: 15px 16px; }
      h1 { font-size: 20px; }
      main { width: min(100% - 20px, 1320px); }
      .intro { display: block; }
      .controls, .archive-head { grid-template-columns: 1fr; }
      .date-nav, .nav-month { width: 100%; }
      .date-nav button, .nav-month button { flex: 1; }
      .map-shell, #avalancheMap { min-height: 420px; }
      .day-cell { min-height: 64px; padding: 5px; }
      .available-pill, .missing-pill { display: none; }
      .weekday { font-size: 9px; }
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
          <p class="muted">EAWS-Warnregionen mit Tagesansicht und historischem Archiv. Die Archivansicht lädt einen ausgewählten Tag exakt, ohne auf einen älteren Warnstand zurückzufallen.</p>
        </div>
      </div>

      <nav class="tabs" aria-label="Alpenwetter-Ansichten">
        <button id="mapTab" class="tab active" type="button">Karte</button>
        <button id="archiveTab" class="tab" type="button">Archiv</button>
      </nav>

      <section id="mapView" class="view">
        <div class="controls">
          <div class="date-nav">
            <button id="prevDayButton" type="button" title="Vorheriger Archivtag">←</button>
            <button id="nextDayButton" type="button" title="Nächster Archivtag">→</button>
          </div>
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

        <div class="export-actions" aria-label="Kartenexport">
          <button id="exportPngButton" type="button">PNG exportieren</button>
          <button id="exportPdfButton" class="export-primary" type="button">PDF exportieren</button>
        </div>

        <div class="layout">
          <section class="card map-card">
            <div class="map-shell" id="mapShell">
              <div class="map-label">Alpenraum · EAWS-Regionen</div>
              <div class="map-toolbar" aria-label="Kartennavigation">
                <button id="zoomOutButton" type="button" title="Herauszoomen" aria-label="Herauszoomen">−</button>
                <button id="zoomInButton" type="button" title="Hineinzoomen" aria-label="Hineinzoomen">+</button>
                <button id="zoomResetButton" class="map-reset" type="button" title="Kartenausschnitt zurücksetzen">Reset</button>
              </div>
              <svg id="avalancheMap" viewBox="0 0 1000 600" role="img" aria-label="Karte der Lawinenwarnstufen im Alpenraum"></svg>
            </div>
            <div class="legend" aria-label="Legende">
              <span class="legend-item"><span class="swatch" style="background:#d8d8d8"></span>keine Einstufung</span>
              <span class="legend-item"><span class="swatch" style="background:#7ecb55"></span>1 gering</span>
              <span class="legend-item"><span class="swatch" style="background:#f3df3f"></span>2 mäßig</span>
              <span class="legend-item"><span class="swatch" style="background:#f39b33"></span>3 erheblich</span>
              <span class="legend-item"><span class="swatch" style="background:#df413b"></span>4 groß</span>
              <span class="legend-item"><span class="swatch" style="background:repeating-linear-gradient(135deg,#262626 0 7px,#ffffff 7px 9px);border:2px solid #ffffff"></span>5 sehr groß</span>
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

      <section id="archiveView" class="view" hidden>
        <div class="archive-head">
          <div class="nav-month">
            <button id="prevMonthButton" type="button" title="Vorheriger Monat">←</button>
            <button id="nextMonthButton" type="button" title="Nächster Monat">→</button>
          </div>
          <div class="control">
            <label for="archiveYear">Jahr</label>
            <select id="archiveYear"></select>
          </div>
          <div class="control">
            <label for="archiveMonth">Monat</label>
            <select id="archiveMonth">
              <option value="0">Januar</option>
              <option value="1">Februar</option>
              <option value="2">März</option>
              <option value="3">April</option>
              <option value="4">Mai</option>
              <option value="5">Juni</option>
              <option value="6">Juli</option>
              <option value="7">August</option>
              <option value="8">September</option>
              <option value="9">Oktober</option>
              <option value="10">November</option>
              <option value="11">Dezember</option>
            </select>
          </div>
          <button id="todayArchiveButton" type="button">Aktueller Monat</button>
          <div id="archiveSummary" class="archive-summary">Archivindex wird geladen …</div>
        </div>

        <div class="calendar">
          <div class="weekday-row">
            <div class="weekday">Mo</div><div class="weekday">Di</div><div class="weekday">Mi</div>
            <div class="weekday">Do</div><div class="weekday">Fr</div><div class="weekday">Sa</div><div class="weekday">So</div>
          </div>
          <div id="calendarGrid" class="calendar-grid"></div>
        </div>

        <div class="archive-note">
          Grün markierte Tage sind im öffentlichen EAWS-/avalanche.report-Tagesarchiv vorhanden. Beim Anklicken wird genau dieser Tag geladen. Einzelne Tagesordner können unvollständig sein; in diesem Fall zeigt die Karte keine Einstufung statt einen anderen Tag zu verwenden.
        </div>
      </section>
    </section>
  </main>

  <script>
    (function () {
      "use strict";

      var NS = "http://www.w3.org/2000/svg";
      var DEFAULT_MAP_BOUNDS = { minLon: 4.0, maxLon: 16.3, minLat: 43.4, maxLat: 49.2 };
      var MAP_BOUNDS = Object.assign({}, DEFAULT_MAP_BOUNDS);
      var COLORS = { 0:"#d8d8d8", 1:"#7ecb55", 2:"#f3df3f", 3:"#f39b33", 4:"#df413b", 5:"#262626" };
      var LABELS = { 0:"keine Einstufung", 1:"gering", 2:"mäßig", 3:"erheblich", 4:"groß", 5:"sehr groß" };
      var CITIES = [
        { name:"Genf", lon:6.1432, lat:46.2044, dx:10, dy:-9, anchor:"start" },
        { name:"Grenoble", lon:5.7245, lat:45.1885, dx:10, dy:-9, anchor:"start" },
        { name:"Turin", lon:7.6869, lat:45.0703, dx:10, dy:-9, anchor:"start" },
        { name:"Mailand", lon:9.1900, lat:45.4642, dx:10, dy:18, anchor:"start" },
        { name:"Zürich", lon:8.5417, lat:47.3769, dx:10, dy:-9, anchor:"start" },
        { name:"München", lon:11.5820, lat:48.1351, dx:10, dy:-9, anchor:"start" },
        { name:"Innsbruck", lon:11.4041, lat:47.2692, dx:10, dy:-9, anchor:"start" },
        { name:"Bozen", lon:11.3548, lat:46.4983, dx:10, dy:18, anchor:"start" },
        { name:"Salzburg", lon:13.0550, lat:47.8095, dx:10, dy:-9, anchor:"start" },
        { name:"Ljubljana", lon:14.5058, lat:46.0569, dx:-10, dy:-9, anchor:"end" }
      ];
      var SVG_WIDTH = 1000;
      var SVG_HEIGHT = 600;
      var MIN_VIEW_WIDTH = 180;

      var state = {
        regions: null,
        ratingsPayload: null,
        selectedId: null,
        archive: null,
        archiveSet: new Set(),
        archiveYear: null,
        archiveMonth: null,
        exactDateMode: false,
        suppressRegionClickUntil: 0,
        viewBox: {
          x: 0,
          y: 0,
          width: SVG_WIDTH,
          height: SVG_HEIGHT,
          dragging: false,
          moved: false,
          startClientX: 0,
          startClientY: 0,
          startX: 0,
          startY: 0
        }
      };

      var dateInput = document.getElementById("forecastDate");
      var modeSelect = document.getElementById("ratingMode");
      var reloadButton = document.getElementById("reloadButton");
      var statusEl = document.getElementById("status");
      var mapEl = document.getElementById("avalancheMap");
      var mapShell = document.getElementById("mapShell");
      var zoomInButton = document.getElementById("zoomInButton");
      var zoomOutButton = document.getElementById("zoomOutButton");
      var zoomResetButton = document.getElementById("zoomResetButton");
      var detailEl = document.getElementById("detailContent");
      var mapTab = document.getElementById("mapTab");
      var archiveTab = document.getElementById("archiveTab");
      var mapView = document.getElementById("mapView");
      var archiveView = document.getElementById("archiveView");
      var archiveYearSelect = document.getElementById("archiveYear");
      var archiveMonthSelect = document.getElementById("archiveMonth");
      var calendarGrid = document.getElementById("calendarGrid");
      var archiveSummary = document.getElementById("archiveSummary");
      var prevDayButton = document.getElementById("prevDayButton");
      var nextDayButton = document.getElementById("nextDayButton");
      var exportPngButton = document.getElementById("exportPngButton");
      var exportPdfButton = document.getElementById("exportPdfButton");

      var todayIso = new Date().toISOString().slice(0, 10);
      dateInput.value = todayIso;

      mapTab.addEventListener("click", function () { switchView("map"); });
      archiveTab.addEventListener("click", function () { switchView("archive"); loadArchive(); });
      reloadButton.addEventListener("click", function () { state.exactDateMode = false; loadAll(false); });
      dateInput.addEventListener("change", function () { state.exactDateMode = false; loadAll(false); });
      modeSelect.addEventListener("change", function () {
        renderMap();
        if (state.selectedId) renderDetail(state.selectedId);
      });

      document.getElementById("prevMonthButton").addEventListener("click", function () { moveArchiveMonth(-1); });
      document.getElementById("nextMonthButton").addEventListener("click", function () { moveArchiveMonth(1); });
      document.getElementById("todayArchiveButton").addEventListener("click", function () {
        var now = new Date();
        state.archiveYear = now.getUTCFullYear();
        state.archiveMonth = now.getUTCMonth();
        syncArchiveSelectors();
        renderCalendar();
      });
      archiveYearSelect.addEventListener("change", function () {
        state.archiveYear = Number(archiveYearSelect.value);
        renderCalendar();
      });
      archiveMonthSelect.addEventListener("change", function () {
        state.archiveMonth = Number(archiveMonthSelect.value);
        renderCalendar();
      });
      prevDayButton.addEventListener("click", function () { moveAvailableDay(-1); });
      nextDayButton.addEventListener("click", function () { moveAvailableDay(1); });
      exportPngButton.addEventListener("click", function () { exportLawinenkarte("png"); });
      exportPdfButton.addEventListener("click", function () { exportLawinenkarte("pdf"); });
      bindMapNavigation();

      function switchView(which) {
        var archive = which === "archive";
        mapView.hidden = archive;
        archiveView.hidden = !archive;
        mapTab.classList.toggle("active", !archive);
        archiveTab.classList.toggle("active", archive);
      }

      function setStatus(text, isError) {
        statusEl.textContent = text;
        statusEl.className = isError ? "status error" : "status";
      }

      function wait(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
      }

      async function fetchJsonChecked(url, options, label) {
        var lastError = null;

        for (var attempt = 0; attempt < 2; attempt += 1) {
          try {
            var fetchOptions = Object.assign(
              { credentials: "same-origin", cache: "no-store" },
              options || {}
            );
            fetchOptions.headers = Object.assign(
              { "Accept": "application/json" },
              (options && options.headers) || {}
            );

            var response = await fetch(url, fetchOptions);
            var text = await response.text();
            var trimmed = text.trim();
            var contentType = String(response.headers.get("content-type") || "").toLowerCase();
            var looksHtml = /^<!doctype\s+html/i.test(trimmed) || /^<html[\s>]/i.test(trimmed);

            if (looksHtml || (!contentType.includes("application/json") && trimmed.charAt(0) === "<")) {
              var isLoginPage =
                response.status === 401 ||
                response.status === 403 ||
                /Alpenwetter\s*·\s*Anmeldung|Bitte Kennwort eingeben|Kennwort nicht korrekt/i.test(text);

              if (isLoginPage) {
                throw new Error("Sitzung abgelaufen. Bitte die Seite neu laden und erneut anmelden.");
              }

              throw new Error(
                (label || "API") +
                " lieferte HTML statt JSON" +
                (response.status ? " (HTTP " + response.status + ")" : "") +
                "."
              );
            }

            var payload;
            try {
              payload = JSON.parse(text);
            } catch (parseError) {
              throw new Error(
                (label || "API") +
                " lieferte ungültiges JSON: " +
                String(parseError && parseError.message ? parseError.message : parseError)
              );
            }

            return { response: response, payload: payload };
          } catch (error) {
            lastError = error;
            if (attempt === 0) {
              await wait(450);
              continue;
            }
          }
        }

        throw lastError || new Error((label || "API") + " konnte nicht geladen werden.");
      }

      async function loadArchive() {
        if (state.archive) {
          renderCalendar();
          return;
        }

        archiveSummary.textContent = "Archivindex wird geladen …";
        try {
          var archiveResult = await fetchJsonChecked("/api/archive", null, "Lawinenarchiv");
          var response = archiveResult.response;
          var payload = archiveResult.payload;
          if (!response.ok) throw new Error(payload.error || ("HTTP " + response.status));

          state.archive = payload;
          state.archiveSet = new Set(payload.dates || []);

          var basis = dateInput.value || payload.lastDate || todayIso;
          var parts = basis.split("-");
          state.archiveYear = Number(parts[0]);
          state.archiveMonth = Number(parts[1]) - 1;

          fillArchiveYears();
          syncArchiveSelectors();
          renderCalendar();
          updateDayNavigation();

          archiveSummary.textContent =
            (payload.count || 0) + " Archivtage · " +
            (payload.firstDate ? formatDate(payload.firstDate) : "–") + " bis " +
            (payload.lastDate ? formatDate(payload.lastDate) : "–");
        } catch (error) {
          archiveSummary.textContent = "Archiv konnte nicht geladen werden: " + String(error && error.message ? error.message : error);
        }
      }

      function fillArchiveYears() {
        var years = {};
        (state.archive.dates || []).forEach(function (iso) { years[iso.slice(0, 4)] = true; });
        var list = Object.keys(years).sort(function (a, b) { return Number(b) - Number(a); });
        archiveYearSelect.innerHTML = "";
        list.forEach(function (year) {
          var option = document.createElement("option");
          option.value = year;
          option.textContent = year;
          archiveYearSelect.appendChild(option);
        });
      }

      function syncArchiveSelectors() {
        archiveYearSelect.value = String(state.archiveYear);
        archiveMonthSelect.value = String(state.archiveMonth);
      }

      function moveArchiveMonth(delta) {
        if (!state.archiveYear && state.archiveYear !== 0) return;
        var d = new Date(Date.UTC(state.archiveYear, state.archiveMonth + delta, 1));
        state.archiveYear = d.getUTCFullYear();
        state.archiveMonth = d.getUTCMonth();
        syncArchiveSelectors();
        renderCalendar();
      }

      function renderCalendar() {
        if (!state.archive) return;
        calendarGrid.innerHTML = "";

        var year = state.archiveYear;
        var month = state.archiveMonth;
        var first = new Date(Date.UTC(year, month, 1));
        var days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
        var mondayOffset = (first.getUTCDay() + 6) % 7;

        for (var i = 0; i < mondayOffset; i += 1) {
          var blank = document.createElement("div");
          blank.className = "day-cell empty-day";
          calendarGrid.appendChild(blank);
        }

        for (var day = 1; day <= days; day += 1) {
          (function (dayNumber) {
            var iso = year + "-" + String(month + 1).padStart(2, "0") + "-" + String(dayNumber).padStart(2, "0");
            var available = state.archiveSet.has(iso);
            var cell = document.createElement("div");
            cell.className = "day-cell" + (available ? " available" : "") + (dateInput.value === iso ? " selected" : "");
            cell.innerHTML =
              '<div class="day-number">' + dayNumber + '</div>' +
              (available ? '<div class="available-pill">Daten vorhanden</div>' : '<div class="missing-pill">–</div>');

            if (available) {
              cell.tabIndex = 0;
              cell.setAttribute("role", "button");
              cell.setAttribute("aria-label", formatDate(iso) + " öffnen");
              cell.addEventListener("click", function () { openArchiveDate(iso); });
              cell.addEventListener("keydown", function (event) {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  openArchiveDate(iso);
                }
              });
            }
            calendarGrid.appendChild(cell);
          })(day);
        }
      }

      async function openArchiveDate(iso) {
        dateInput.value = iso;
        state.exactDateMode = true;
        switchView("map");
        await loadAll(true);
        renderCalendar();
      }

      function moveAvailableDay(direction) {
        if (!state.archive || !state.archive.dates || !state.archive.dates.length) return;
        var dates = state.archive.dates;
        var current = dateInput.value;
        var index = dates.indexOf(current);

        if (index === -1) {
          index = direction < 0
            ? findPreviousDateIndex(dates, current)
            : findNextDateIndex(dates, current);
        } else {
          index += direction;
        }

        if (index < 0 || index >= dates.length) return;
        openArchiveDate(dates[index]);
      }

      function findPreviousDateIndex(dates, current) {
        for (var i = dates.length - 1; i >= 0; i -= 1) if (dates[i] < current) return i;
        return -1;
      }

      function findNextDateIndex(dates, current) {
        for (var i = 0; i < dates.length; i += 1) if (dates[i] > current) return i;
        return dates.length;
      }

      function updateDayNavigation() {
        if (!state.archive || !state.archive.dates) {
          prevDayButton.disabled = true;
          nextDayButton.disabled = true;
          return;
        }
        var current = dateInput.value;
        prevDayButton.disabled = findPreviousDateIndex(state.archive.dates, current) < 0;
        nextDayButton.disabled = findNextDateIndex(state.archive.dates, current) >= state.archive.dates.length;
      }

      async function loadAll(exact) {
        setStatus("EAWS-Regionen und Warnstufen werden geladen …", false);
        reloadButton.disabled = true;

        try {
          if (!state.regions) {
            var regionResult = await fetchJsonChecked("/api/regions", null, "EAWS-Regionsdaten");
            var regionResponse = regionResult.response;
            if (!regionResponse.ok) throw new Error("Regionsdaten: HTTP " + regionResponse.status);
            state.regions = regionResult.payload;
          }

          var selectedDate = dateInput.value || todayIso;
          var exactParam = exact ? "&exact=1" : "";
          var ratingResult = await fetchJsonChecked(
            "/api/ratings?date=" + encodeURIComponent(selectedDate) + exactParam,
            null,
            "Lawinenwarnstufen"
          );
          var ratingResponse = ratingResult.response;
          var ratingPayload = ratingResult.payload;

          if (!ratingResponse.ok) {
            state.ratingsPayload = {
              requestedDate: selectedDate,
              dataDate: null,
              ratings: { maxDangerRatings: {} },
              error: ratingPayload && ratingPayload.error
            };
          } else {
            state.ratingsPayload = ratingPayload;
          }

          renderMap();
          if (state.selectedId) renderDetail(state.selectedId);

          var regionCount = uniqueRegionIds().length;
          var mappedCount = countRatedRegions();
          var dateInfo = state.ratingsPayload.dataDate
            ? "Datenstand " + formatDate(state.ratingsPayload.dataDate)
            : "für diesen Tag keine Warnstufendatei gefunden";
          var fallback = Number(state.ratingsPayload.fallbackDays || 0);
          var fallbackInfo = !exact && fallback > 0 ? " · " + fallback + " Tag(e) zurückgegriffen" : "";
          var modeInfo = exact ? " · Archivtag exakt" : "";
          setStatus(regionCount + " Alpenregionen · " + mappedCount + " mit Einstufung · " + dateInfo + fallbackInfo + modeInfo + " · Detail-/Höhenflächen bevorzugt", false);

          updateDayNavigation();
        } catch (error) {
          var message = String(error && error.message ? error.message : error);
          setStatus("Laden fehlgeschlagen: " + message, true);
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

      function selectedGeometryDate() {
        var payload = state.ratingsPayload || {};
        return payload.dataDate || dateInput.value || todayIso;
      }

      function normalizeIsoDate(value) {
        if (value === undefined || value === null || value === "") return "";
        var match = String(value).match(/\d{4}-\d{2}-\d{2}/);
        return match ? match[0] : "";
      }

      function featureValidForDate(feature, iso) {
        var p = (feature && feature.properties) || {};
        var from = normalizeIsoDate(
          p.valid_from !== undefined ? p.valid_from :
          p.validFrom !== undefined ? p.validFrom :
          p.start_date !== undefined ? p.start_date :
          p.startDate
        );
        var until = normalizeIsoDate(
          p.valid_until !== undefined ? p.valid_until :
          p.validUntil !== undefined ? p.validUntil :
          p.end_date !== undefined ? p.end_date :
          p.endDate
        );

        if (from && iso < from) return false;
        if (until && iso > until) return false;
        return true;
      }

      function activeFeatures() {
        var all = state.regions && Array.isArray(state.regions.features) ? state.regions.features : [];
        var iso = selectedGeometryDate();
        return all.filter(function (feature) { return featureValidForDate(feature, iso); });
      }

      function featureElevation(feature) {
        var p = (feature && feature.properties) || {};
        var candidates = [
          p.elevation,
          p.altitude,
          p.level,
          p.elevation_class,
          p.elevationClass,
          p.band
        ];

        for (var i = 0; i < candidates.length; i += 1) {
          var value = String(candidates[i] == null ? "" : candidates[i]).toLowerCase().trim();
          if (value === "high" || value === "upper" || value === "above") return "high";
          if (value === "low" || value === "lower" || value === "below") return "low";
        }
        return "";
      }

      function dangerForKey(key) {
        var ratings = getRatings();
        var raw = ratings[key];
        if (raw === undefined || raw === null || raw === "") return 0;
        var value = Number(raw);
        return Number.isFinite(value) && value >= 1 && value <= 5 ? Math.round(value) : 0;
      }

      function firstDanger(keys) {
        for (var i = 0; i < keys.length; i += 1) {
          var value = dangerForKey(keys[i]);
          if (value) return value;
        }
        return 0;
      }

      function dangerForFeature(feature) {
        var id = featureId(feature);
        var elevation = featureElevation(feature);
        var mode = modeSelect.value || "";
        var requestedElevation = "";
        var timePart = "";

        if (mode === "high" || mode === "low") {
          requestedElevation = mode;
        } else if (mode.indexOf("high:") === 0 || mode.indexOf("low:") === 0) {
          var modeParts = mode.split(":");
          requestedElevation = modeParts[0];
          timePart = modeParts[1] || "";
        } else if (mode === "am" || mode === "pm") {
          timePart = mode;
        }

        if (requestedElevation && elevation && elevation !== requestedElevation) return 0;

        var effectiveElevation = requestedElevation || elevation;
        var keys = [];

        if (effectiveElevation && timePart) keys.push(id + ":" + effectiveElevation + ":" + timePart);
        if (timePart) keys.push(id + ":" + timePart);
        if (effectiveElevation) keys.push(id + ":" + effectiveElevation);
        if (!mode || !requestedElevation || !elevation) keys.push(id);

        return firstDanger(keys);
      }

      function renderableFeatures() {
        var groups = {};
        activeFeatures().forEach(function (feature) {
          var id = featureId(feature);
          if (!groups[id]) groups[id] = [];
          groups[id].push(feature);
        });

        var output = [];

        Object.keys(groups).forEach(function (id) {
          var group = groups[id];
          var detailed = group.filter(function (feature) {
            return !!featureElevation(feature);
          });
          var detailedRated = detailed.filter(function (feature) {
            return dangerForFeature(feature) > 0;
          });

          // Sobald echte Höhenflächen mit Warnwerten existieren, wird die grobe
          // Gesamtfläche nicht mehr gezeichnet. Ebenso werden unbewertete
          // Höhenflächen ausgeblendet, damit sie keine farbigen Details verdecken.
          if (detailedRated.length) {
            detailedRated.forEach(function (feature) { output.push(feature); });
            return;
          }

          var rated = group.filter(function (feature) {
            return dangerForFeature(feature) > 0;
          });

          // Gibt es wenigstens eine bewertete Fläche, zeichnen wir nur diese.
          // Grau bleibt damit nur dort sichtbar, wo für die Region wirklich
          // überhaupt keine Einstufung vorliegt.
          if (rated.length) {
            rated.forEach(function (feature) { output.push(feature); });
            return;
          }

          group.forEach(function (feature) { output.push(feature); });
        });

        // Grobe Flächen zuerst, Höhen-/Detailflächen zuletzt.
        output.sort(function (a, b) {
          return Number(!!featureElevation(a)) - Number(!!featureElevation(b));
        });

        return output;
      }

      function uniqueRegionIds() {
        var ids = {};
        activeFeatures().forEach(function (feature) { ids[featureId(feature)] = true; });
        return Object.keys(ids);
      }

      function countRatedRegions() {
        var rated = {};
        activeFeatures().forEach(function (feature) {
          var id = featureId(feature);
          if (dangerForFeature(feature) > 0) rated[id] = true;
        });
        return Object.keys(rated).length;
      }

      function appendDanger5Pattern() {
        var defs = document.createElementNS(NS, "defs");
        var pattern = document.createElementNS(NS, "pattern");
        pattern.setAttribute("id", "danger5Pattern");
        pattern.setAttribute("patternUnits", "userSpaceOnUse");
        pattern.setAttribute("width", "12");
        pattern.setAttribute("height", "12");
        pattern.setAttribute("patternTransform", "rotate(45)");

        var background = document.createElementNS(NS, "rect");
        background.setAttribute("x", "0");
        background.setAttribute("y", "0");
        background.setAttribute("width", "12");
        background.setAttribute("height", "12");
        background.setAttribute("fill", "#262626");
        pattern.appendChild(background);

        var stripe = document.createElementNS(NS, "line");
        stripe.setAttribute("x1", "1");
        stripe.setAttribute("y1", "-2");
        stripe.setAttribute("x2", "1");
        stripe.setAttribute("y2", "14");
        stripe.setAttribute("stroke", "#ffffff");
        stripe.setAttribute("stroke-width", "2.4");
        stripe.setAttribute("opacity", "0.95");
        pattern.appendChild(stripe);

        defs.appendChild(pattern);
        mapEl.appendChild(defs);
      }

      function clampViewBox() {
        var vb = state.viewBox;
        vb.width = Math.max(MIN_VIEW_WIDTH, Math.min(SVG_WIDTH, vb.width));
        vb.height = vb.width * SVG_HEIGHT / SVG_WIDTH;

        if (vb.height > SVG_HEIGHT) {
          vb.height = SVG_HEIGHT;
          vb.width = vb.height * SVG_WIDTH / SVG_HEIGHT;
        }

        vb.x = Math.max(0, Math.min(SVG_WIDTH - vb.width, vb.x));
        vb.y = Math.max(0, Math.min(SVG_HEIGHT - vb.height, vb.y));
      }

      function applyViewBox() {
        clampViewBox();
        mapEl.setAttribute(
          "viewBox",
          state.viewBox.x.toFixed(2) + " " +
          state.viewBox.y.toFixed(2) + " " +
          state.viewBox.width.toFixed(2) + " " +
          state.viewBox.height.toFixed(2)
        );
      }

      function resetMapView() {
        state.viewBox.x = 0;
        state.viewBox.y = 0;
        state.viewBox.width = SVG_WIDTH;
        state.viewBox.height = SVG_HEIGHT;
        applyViewBox();
      }

      function zoomMapAt(svgX, svgY, factor) {
        var vb = state.viewBox;
        var nextWidth = Math.max(MIN_VIEW_WIDTH, Math.min(SVG_WIDTH, vb.width * factor));
        var nextHeight = nextWidth * SVG_HEIGHT / SVG_WIDTH;
        var relX = vb.width ? (svgX - vb.x) / vb.width : 0.5;
        var relY = vb.height ? (svgY - vb.y) / vb.height : 0.5;

        vb.x = svgX - relX * nextWidth;
        vb.y = svgY - relY * nextHeight;
        vb.width = nextWidth;
        vb.height = nextHeight;
        applyViewBox();
      }

      function screenToSvg(clientX, clientY) {
        var rect = mapEl.getBoundingClientRect();
        return {
          x: state.viewBox.x + ((clientX - rect.left) / rect.width) * state.viewBox.width,
          y: state.viewBox.y + ((clientY - rect.top) / rect.height) * state.viewBox.height
        };
      }

      function bindMapNavigation() {
        zoomInButton.addEventListener("click", function (event) {
          event.stopPropagation();
          zoomMapAt(
            state.viewBox.x + state.viewBox.width / 2,
            state.viewBox.y + state.viewBox.height / 2,
            0.8
          );
        });

        zoomOutButton.addEventListener("click", function (event) {
          event.stopPropagation();
          zoomMapAt(
            state.viewBox.x + state.viewBox.width / 2,
            state.viewBox.y + state.viewBox.height / 2,
            1.25
          );
        });

        zoomResetButton.addEventListener("click", function (event) {
          event.stopPropagation();
          resetMapView();
        });

        mapEl.addEventListener("wheel", function (event) {
          event.preventDefault();
          var point = screenToSvg(event.clientX, event.clientY);
          zoomMapAt(point.x, point.y, event.deltaY < 0 ? 0.84 : 1.18);
        }, { passive: false });

        mapShell.addEventListener("pointerdown", function (event) {
          if (event.target.closest && event.target.closest(".map-toolbar")) return;
          if (event.pointerType === "mouse" && event.button !== 0) return;
          if (state.viewBox.width >= SVG_WIDTH - 0.01) return;

          state.viewBox.dragging = true;
          state.viewBox.moved = false;
          state.viewBox.startClientX = event.clientX;
          state.viewBox.startClientY = event.clientY;
          state.viewBox.startX = state.viewBox.x;
          state.viewBox.startY = state.viewBox.y;
          mapShell.classList.add("dragging");
        });

        mapShell.addEventListener("pointermove", function (event) {
          if (!state.viewBox.dragging) return;

          var rect = mapEl.getBoundingClientRect();
          var pixelDx = event.clientX - state.viewBox.startClientX;
          var pixelDy = event.clientY - state.viewBox.startClientY;
          if (Math.abs(pixelDx) + Math.abs(pixelDy) > 4) state.viewBox.moved = true;

          state.viewBox.x = state.viewBox.startX - (pixelDx / rect.width) * state.viewBox.width;
          state.viewBox.y = state.viewBox.startY - (pixelDy / rect.height) * state.viewBox.height;
          applyViewBox();
        });

        function stopDragging(event) {
          if (!state.viewBox.dragging) return;
          if (state.viewBox.moved) state.suppressRegionClickUntil = Date.now() + 180;
          state.viewBox.dragging = false;
          state.viewBox.moved = false;
          mapShell.classList.remove("dragging");
        }

        mapShell.addEventListener("pointerup", stopDragging);
        mapShell.addEventListener("pointercancel", stopDragging);

        mapEl.addEventListener("dblclick", function (event) {
          event.preventDefault();
          var point = screenToSvg(event.clientX, event.clientY);
          zoomMapAt(point.x, point.y, 0.72);
        });
      }

      function clientGeometryBounds(geometry) {
        if (!geometry || !geometry.coordinates) return null;

        var minLon = Infinity;
        var maxLon = -Infinity;
        var minLat = Infinity;
        var maxLat = -Infinity;

        function visit(node) {
          if (!Array.isArray(node)) return;

          if (
            node.length >= 2 &&
            typeof node[0] === "number" &&
            typeof node[1] === "number"
          ) {
            minLon = Math.min(minLon, node[0]);
            maxLon = Math.max(maxLon, node[0]);
            minLat = Math.min(minLat, node[1]);
            maxLat = Math.max(maxLat, node[1]);
            return;
          }

          node.forEach(visit);
        }

        visit(geometry.coordinates);

        return Number.isFinite(minLon)
          ? { minLon: minLon, maxLon: maxLon, minLat: minLat, maxLat: maxLat }
          : null;
      }

      function updateMapBounds(features) {
        var minLon = Infinity;
        var maxLon = -Infinity;
        var minLat = Infinity;
        var maxLat = -Infinity;

        (features || []).forEach(function (feature) {
          var bounds = clientGeometryBounds(feature && feature.geometry);
          if (!bounds) return;
          minLon = Math.min(minLon, bounds.minLon);
          maxLon = Math.max(maxLon, bounds.maxLon);
          minLat = Math.min(minLat, bounds.minLat);
          maxLat = Math.max(maxLat, bounds.maxLat);
        });

        // Die beschrifteten Referenzorte gehören ebenfalls vollständig in den Ausschnitt.
        CITIES.forEach(function (city) {
          minLon = Math.min(minLon, city.lon);
          maxLon = Math.max(maxLon, city.lon);
          minLat = Math.min(minLat, city.lat);
          maxLat = Math.max(maxLat, city.lat);
        });

        if (![minLon, maxLon, minLat, maxLat].every(Number.isFinite)) {
          MAP_BOUNDS = Object.assign({}, DEFAULT_MAP_BOUNDS);
          return;
        }

        var lonSpan = Math.max(0.5, maxLon - minLon);
        var latSpan = Math.max(0.5, maxLat - minLat);
        var lonPad = Math.max(0.18, lonSpan * 0.035);
        var latPad = Math.max(0.14, latSpan * 0.045);

        MAP_BOUNDS = {
          minLon: minLon - lonPad,
          maxLon: maxLon + lonPad,
          minLat: minLat - latPad,
          maxLat: maxLat + latPad
        };
      }

      function renderMap() {
        while (mapEl.firstChild) mapEl.removeChild(mapEl.firstChild);
        appendDanger5Pattern();

        var active = activeFeatures();
        updateMapBounds(active);
        var features = renderableFeatures();

        features.forEach(function (feature) {
          var id = featureId(feature);
          var danger = dangerForFeature(feature);
          var pathData = geometryToPath(feature.geometry);
          if (!pathData) return;

          var path = document.createElementNS(NS, "path");
          path.setAttribute("d", pathData);
          path.setAttribute("fill", danger === 5 ? "url(#danger5Pattern)" : (COLORS[danger] || COLORS[0]));
          path.setAttribute("fill-rule", "evenodd");
          path.setAttribute("stroke", danger === 5 ? "#ffffff" : "#31435b");
          path.setAttribute("stroke-width", danger === 5 ? "2.6" : "0.8");
          path.setAttribute("vector-effect", "non-scaling-stroke");
          path.setAttribute("data-region-id", id);
          if (danger === 5) path.classList.add("danger-5");
          if (id === state.selectedId) path.classList.add("selected");

          var title = document.createElementNS(NS, "title");
          title.textContent = featureName(feature) + " · " + id + " · " + (danger ? "Stufe " + danger + " (" + LABELS[danger] + ")" : "keine Einstufung");
          path.appendChild(title);

          path.addEventListener("click", function () {
            if (Date.now() < state.suppressRegionClickUntil) return;
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

        renderCityMarkers();
        applyViewBox();
      }

      function renderCityMarkers() {
        var layer = document.createElementNS(NS, "g");
        layer.setAttribute("aria-label", "Wichtige Orte");
        layer.setAttribute("pointer-events", "none");

        CITIES.forEach(function (city) {
          var xy = project(city.lon, city.lat);
          if (xy[0] < 0 || xy[0] > 1000 || xy[1] < 0 || xy[1] > 600) return;

          var marker = document.createElementNS(NS, "circle");
          marker.setAttribute("cx", xy[0].toFixed(1));
          marker.setAttribute("cy", xy[1].toFixed(1));
          marker.setAttribute("r", "5");
          marker.setAttribute("fill", "#ffffff");
          marker.setAttribute("stroke", "#0f172a");
          marker.setAttribute("stroke-width", "2.4");
          marker.setAttribute("vector-effect", "non-scaling-stroke");
          layer.appendChild(marker);

          var label = document.createElementNS(NS, "text");
          label.setAttribute("x", (xy[0] + city.dx).toFixed(1));
          label.setAttribute("y", (xy[1] + city.dy).toFixed(1));
          label.setAttribute("text-anchor", city.anchor || "start");
          label.setAttribute("dominant-baseline", "middle");
          label.setAttribute("font-family", "Arial, sans-serif");
          label.setAttribute("font-size", "15");
          label.setAttribute("font-weight", "700");
          label.setAttribute("fill", "#ffffff");
          label.setAttribute("stroke", "#0f172a");
          label.setAttribute("stroke-width", "3.5");
          label.setAttribute("paint-order", "stroke fill");
          label.setAttribute("stroke-linejoin", "round");
          label.setAttribute("vector-effect", "non-scaling-stroke");
          label.textContent = city.name;
          layer.appendChild(label);
        });

        mapEl.appendChild(layer);
      }

      function renderDetail(id) {
        var features = activeFeatures();
        var feature = features.find(function (item) { return featureId(item) === id; });
        var name = feature ? featureName(feature) : id;
        var danger = dangerForId(id);
        var color = COLORS[danger] || COLORS[0];
        var featureElevationValue = featureElevation(feature);
        var featureProps = (feature && feature.properties) || {};
        var thresholdValue = Number(featureProps.threshold);
        var elevationInfo = "";
        if (featureElevationValue) {
          elevationInfo = featureElevationValue === "high" ? "Hochlage" : "Tieflage";
          if (Number.isFinite(thresholdValue)) elevationInfo += " · Grenze " + Math.round(thresholdValue) + " m";
        }
        var dangerBadgeStyle = danger === 5
          ? "background:repeating-linear-gradient(135deg,#262626 0 7px,#ffffff 7px 9px);color:#ffffff;border-color:#ffffff"
          : "background:" + color + ";" + (danger >= 4 ? "color:#ffffff" : "color:#111111");

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
            '<div class="danger-number" style="' + dangerBadgeStyle + '">' + (danger || "–") + '</div>' +
            '<div class="danger-copy"><strong>' + (danger ? "Stufe " + danger + " · " + LABELS[danger] : "Keine Einstufung") + '</strong>' +
            '<span>' + escapeHtml(modeSelect.options[modeSelect.selectedIndex].text) + '</span>' +
            (elevationInfo ? '<span>' + escapeHtml(elevationInfo) + '</span>' : '') +
            '</div>' +
          '</div>' +
          '<div class="rating-grid">' + rowHtml + '</div>';
      }

      async function exportLawinenkarte(format) {
        if (!state.regions || !mapEl || !mapEl.childNodes.length) {
          setStatus("Export nicht möglich: Die Lawinenkarte ist noch nicht geladen.", true);
          return;
        }

        exportPngButton.disabled = true;
        exportPdfButton.disabled = true;

        try {
          var canvas = await buildExportCanvas();
          var selectedDate = dateInput.value || todayIso;
          var modeSlug = exportModeSlug();
          var filenameBase = "lawinenwarnkarte_" + selectedDate + "_" + modeSlug;

          if (format === "pdf") {
            var pdfBlob = await canvasToSinglePagePdf(canvas);
            downloadBlob(pdfBlob, filenameBase + ".pdf");
          } else {
            var pngBlob = await canvasToBlob(canvas, "image/png");
            downloadBlob(pngBlob, filenameBase + ".png");
          }

          setStatus("Export erstellt: " + filenameBase + "." + format, false);
        } catch (error) {
          setStatus("Export fehlgeschlagen: " + String(error && error.message ? error.message : error), true);
        } finally {
          exportPngButton.disabled = false;
          exportPdfButton.disabled = false;
        }
      }

      async function buildExportCanvas() {
        var canvas = document.createElement("canvas");
        var ctx = canvas.getContext("2d");
        var width = 1800;
        var padding = 60;
        var titleTop = 54;
        var mapTop = 182;
        var mapWidth = width - padding * 2;
        var mapHeight = Math.round(mapWidth * 0.6);
        var legendTop = mapTop + mapHeight + 34;
        var footerTop = legendTop + 96;
        var height = footerTop + 150;

        canvas.width = width;
        canvas.height = height;

        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, width, height);

        ctx.fillStyle = "#101827";
        ctx.font = "700 44px Arial, sans-serif";
        ctx.textBaseline = "top";
        ctx.fillText("Lawinenwarnkarte Alpenraum", padding, titleTop);

        ctx.fillStyle = "#475569";
        ctx.font = "24px Arial, sans-serif";
        ctx.fillText(exportMetaLine(), padding, titleTop + 58);

        ctx.fillStyle = "#eef2f6";
        ctx.fillRect(padding, mapTop, mapWidth, mapHeight);
        ctx.strokeStyle = "#cbd5e1";
        ctx.lineWidth = 2;
        ctx.strokeRect(padding, mapTop, mapWidth, mapHeight);

        var mapImage = await svgElementToImage(mapEl);
        ctx.drawImage(mapImage, padding, mapTop, mapWidth, mapHeight);

        drawExportLegend(ctx, padding, legendTop);

        ctx.strokeStyle = "#d6dde6";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(padding, footerTop);
        ctx.lineTo(width - padding, footerTop);
        ctx.stroke();

        var logo = await loadExportImage("/assets/eaws-logo.png");
        var logoWidth = 250;
        var logoHeight = logoWidth * (logo.naturalHeight || logo.height) / (logo.naturalWidth || logo.width);
        var footerY = footerTop + 32;
        ctx.drawImage(logo, padding, footerY, logoWidth, logoHeight);

        ctx.fillStyle = "#1f2937";
        ctx.font = "700 24px Arial, sans-serif";
        ctx.fillText("Quelle: EAWS / avalanche.report", padding + logoWidth + 28, footerY + 12);

        ctx.fillStyle = "#64748b";
        ctx.font = "20px Arial, sans-serif";
        ctx.fillText(
          "Übersichtsdarstellung. Maßgeblich bleiben die Bulletins der zuständigen offiziellen Lawinenwarndienste.",
          padding + logoWidth + 28,
          footerY + 52
        );

        return canvas;
      }

      function exportMetaLine() {
        var requested = dateInput.value || todayIso;
        var payload = state.ratingsPayload || {};
        var dataDate = payload.dataDate || requested;
        var modeLabel = modeSelect && modeSelect.options[modeSelect.selectedIndex]
          ? modeSelect.options[modeSelect.selectedIndex].text
          : "Höchste Warnstufe";

        var text = "Datenstand: " + formatDate(dataDate) + " · Darstellung: " + modeLabel;
        var fallback = Number(payload.fallbackDays || 0);
        if (!state.exactDateMode && fallback > 0 && dataDate !== requested) {
          text += " · angefragt: " + formatDate(requested);
        }
        return text;
      }

      function exportModeSlug() {
        var value = modeSelect.value || "maximum";
        return value
          .replace(/:/g, "-")
          .replace(/[^a-zA-Z0-9_-]+/g, "-")
          .replace(/^-+|-+$/g, "") || "maximum";
      }

      function drawExportLegend(ctx, x, y) {
        var items = [
          [0, "keine Einstufung"],
          [1, "1 gering"],
          [2, "2 mäßig"],
          [3, "3 erheblich"],
          [4, "4 groß"],
          [5, "5 sehr groß"]
        ];

        var cursorX = x;
        ctx.font = "21px Arial, sans-serif";
        ctx.textBaseline = "middle";

        items.forEach(function (item) {
          var level = item[0];
          var label = item[1];
          if (level === 5) {
            ctx.fillStyle = "#262626";
            ctx.fillRect(cursorX, y, 34, 26);

            ctx.save();
            ctx.beginPath();
            ctx.rect(cursorX, y, 34, 26);
            ctx.clip();
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 2;
            for (var sx = cursorX - 28; sx < cursorX + 48; sx += 8) {
              ctx.beginPath();
              ctx.moveTo(sx, y + 26);
              ctx.lineTo(sx + 26, y);
              ctx.stroke();
            }
            ctx.restore();

            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 3;
            ctx.strokeRect(cursorX, y, 34, 26);
          } else {
            ctx.fillStyle = COLORS[level] || COLORS[0];
            ctx.fillRect(cursorX, y, 34, 26);
            ctx.strokeStyle = "#475569";
            ctx.lineWidth = 1.5;
            ctx.strokeRect(cursorX, y, 34, 26);
          }

          ctx.fillStyle = "#334155";
          ctx.fillText(label, cursorX + 46, y + 13);

          cursorX += level === 0 ? 250 : 190;
        });
      }

      function svgElementToImage(svg) {
        return new Promise(function (resolve, reject) {
          var clone = svg.cloneNode(true);
          clone.setAttribute("xmlns", NS);
          clone.setAttribute("width", "1000");
          clone.setAttribute("height", "600");
          clone.setAttribute("viewBox", "0 0 1000 600");
          clone.setAttribute("preserveAspectRatio", "xMidYMid meet");

          var xml = new XMLSerializer().serializeToString(clone);
          var encoded = utf8ToBase64(xml);
          var image = new Image();

          image.onload = function () { resolve(image); };
          image.onerror = function () { reject(new Error("SVG-Karte konnte für den Export nicht gerendert werden.")); };
          image.src = "data:image/svg+xml;base64," + encoded;
        });
      }

      function utf8ToBase64(value) {
        var bytes = new TextEncoder().encode(value);
        var binary = "";
        for (var i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
        return btoa(binary);
      }

      function loadExportImage(src) {
        return new Promise(function (resolve, reject) {
          var image = new Image();
          image.onload = function () { resolve(image); };
          image.onerror = function () { reject(new Error("EAWS-Logo konnte nicht geladen werden.")); };
          image.src = src;
        });
      }

      function canvasToBlob(canvas, type, quality) {
        return new Promise(function (resolve, reject) {
          canvas.toBlob(function (blob) {
            if (blob) resolve(blob);
            else reject(new Error("Canvas konnte nicht exportiert werden."));
          }, type, quality);
        });
      }

      function downloadBlob(blob, filename) {
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      }

      async function canvasToSinglePagePdf(canvas) {
        var jpegBlob = await canvasToBlob(canvas, "image/jpeg", 0.94);
        var jpegBytes = new Uint8Array(await jpegBlob.arrayBuffer());

        var pageWidth = 842;
        var pageHeight = pageWidth * canvas.height / canvas.width;
        var contentStream =
          "q\\n" +
          pageWidth.toFixed(3) + " 0 0 " + pageHeight.toFixed(3) + " 0 0 cm\\n" +
          "/Im0 Do\\n" +
          "Q\\n";

        var encoderPdf = new TextEncoder();
        var parts = [];
        var offsets = [0];
        var length = 0;

        function pushBytes(bytes) {
          parts.push(bytes);
          length += bytes.length;
        }

        function pushText(text) {
          pushBytes(encoderPdf.encode(text));
        }

        function startObject(number) {
          offsets[number] = length;
          pushText(String(number) + " 0 obj\\n");
        }

        pushText("%PDF-1.4\\n");

        startObject(1);
        pushText("<< /Type /Catalog /Pages 2 0 R >>\\nendobj\\n");

        startObject(2);
        pushText("<< /Type /Pages /Kids [3 0 R] /Count 1 >>\\nendobj\\n");

        startObject(3);
        pushText(
          "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " +
          pageWidth.toFixed(3) + " " + pageHeight.toFixed(3) +
          "] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>\\nendobj\\n"
        );

        startObject(4);
        pushText(
          "<< /Type /XObject /Subtype /Image /Width " + canvas.width +
          " /Height " + canvas.height +
          " /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length " +
          jpegBytes.length + " >>\\nstream\\n"
        );
        pushBytes(jpegBytes);
        pushText("\\nendstream\\nendobj\\n");

        var contentBytes = encoderPdf.encode(contentStream);
        startObject(5);
        pushText("<< /Length " + contentBytes.length + " >>\\nstream\\n");
        pushBytes(contentBytes);
        pushText("endstream\\nendobj\\n");

        var xrefOffset = length;
        pushText("xref\\n0 6\\n");
        pushText("0000000000 65535 f \\n");
        for (var objectNumber = 1; objectNumber <= 5; objectNumber += 1) {
          pushText(String(offsets[objectNumber]).padStart(10, "0") + " 00000 n \\n");
        }
        pushText(
          "trailer\\n<< /Size 6 /Root 1 0 R >>\\nstartxref\\n" +
          xrefOffset + "\\n%%EOF\\n"
        );

        var merged = new Uint8Array(length);
        var position = 0;
        parts.forEach(function (part) {
          merged.set(part, position);
          position += part.length;
        });

        return new Blob([merged], { type: "application/pdf" });
      }

      function geometryToPath(geometry) {
        if (!geometry || !geometry.coordinates) return "";
        if (geometry.type === "Polygon") return polygonToPath(geometry.coordinates);
        if (geometry.type === "MultiPolygon") return geometry.coordinates.map(polygonToPath).join(" ");
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

      loadArchive();
      loadAll(false);
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
  headers.set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  return headers;
}
