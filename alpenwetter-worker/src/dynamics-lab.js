import { DYNAMICS_CLIENT_SOURCE } from "./dynamics-client.js";
/* Protected ECMWF upper-air dynamics studio. All interactive controls require a valid Worker session. */
const DYNAMICS_SOURCE = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/dynamics-data/data/dynamik/";

export async function dynamicsLabData(url, securityHeaders) {
  const rest = url.pathname.replace(/^\/dynamik\/api\/data\//, "");
  if (!/^(?:current\.json|frames\/\d{10}\/(?:tcwv|jet|ascent|pv|iru|irv)_\d{3}\.png)$/.test(rest)) {
    return new Response("Ungültige Datenadresse", { status: 400, headers: securityHeaders({"Content-Type":"text/plain"}) });
  }
  try {
    const response = await fetch(DYNAMICS_SOURCE + rest, {
      cf: {cacheEverything: true, cacheTtl: rest === "current.json" ? 120 : 86400}
    });
    if (!response.ok) {
      return new Response(JSON.stringify({error: "Kein bestätigter ECMWF-Datensatz", upstream: response.status}), {
        status: response.status === 404 ? 404 : 502,
        headers: securityHeaders({"Content-Type":"application/json; charset=utf-8"})
      });
    }
    return new Response(response.body, {
      status: 200,
      headers: securityHeaders({"Content-Type":rest.endsWith(".json") ? "application/json; charset=utf-8" : "image/png"})
    });
  } catch (error) {
    return new Response(JSON.stringify({error:"Modelldaten derzeit nicht erreichbar"}), {
      status:502, headers: securityHeaders({"Content-Type":"application/json; charset=utf-8"})
    });
  }
}

export async function dynamicsBoundaries(securityHeaders) {
  try {
    const response = await fetch("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson", {
      cf:{cacheEverything:true,cacheTtl:86400}
    });
    if(!response.ok) throw Error("Natural Earth HTTP "+response.status);
    return new Response(response.body, {
      headers:securityHeaders({"Content-Type":"application/geo+json; charset=utf-8"})
    });
  } catch (_error) {
    return new Response(JSON.stringify({type:"FeatureCollection",features:[]}), {
      status:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})
    });
  }
}

const STYLE = [
":root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#0b1524;color:#e9f3ff}",
"*{box-sizing:border-box}body{margin:0}a{color:#acdff9;text-decoration:none}a:hover{text-decoration:underline}",
"header{padding:16px 2.5vw;border-bottom:1px solid #2e4761;background:#101f31;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}",
"header small{display:block;color:#90b1c9;font-size:11px;letter-spacing:.12em}header strong{font-size:19px}nav{display:flex;gap:12px;align-items:center;flex-wrap:wrap}nav form{margin:0}",
"main{max-width:1620px;margin:auto;padding:22px 2vw 44px}h1{font-size:clamp(21px,3vw,32px);margin:0 0 8px}h2{font-size:17px;margin:0 0 14px}p{line-height:1.55}.lead{color:#b4c8da;font-size:14px;max-width:900px;margin:0 0 20px}",
".layout{display:grid;grid-template-columns:minmax(0,1fr) 305px;gap:15px;align-items:start}",
".card{background:#13263b;border:1px solid #304b65;border-radius:13px;padding:15px;min-width:0;box-shadow:0 8px 30px #0003}",
".map{position:relative;background:#b6d6e7;border:1px solid #46627c;border-radius:9px;overflow:hidden}.map canvas{width:100%;display:block;aspect-ratio:16/9}",
"button,select{font:inherit;background:#203e59;color:#e9f4fb;border:1px solid #46657e;border-radius:8px;padding:9px 11px;cursor:pointer}",
"button:hover:not(:disabled){background:#315575}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #ffc36a;outline-offset:2px}",
"button:disabled{opacity:.45;cursor:default}button.primary{background:#227aaf;border-color:#4691c1;font-weight:750}",
"label{display:block;color:#d2e7f6;font-size:13px}select{max-width:100%;margin-top:5px}.settings label{display:flex;align-items:center;gap:9px;padding:10px 0;border-bottom:1px solid #2a445e}",
".settings input{width:17px;height:17px;accent-color:#64b9f4}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:space-between;margin:12px 0}",
".row input[type=range]{flex:1;min-width:130px;accent-color:#6fc6f5}.timestamp{font-size:13px;font-variant-numeric:tabular-nums;color:#d1e8f9}",
".status{margin-top:12px;border-radius:9px;padding:12px;background:#1c3750;color:#cfe5f7;font-size:13px;line-height:1.6}",
".status.error{background:#4a2a2d;color:#ffd4cd}.note{color:#a8c1d7;font-size:12px;line-height:1.6}",
".legend{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:12px;font-size:11px;color:#bfd5e6}",
".bar{height:13px;width:min(450px,100%);border-radius:4px;background:linear-gradient(to right,#f7f9fc,#d1f2ff,#83d3d3,#419947,#e8e458,#ec6f28,#9b1a58)}",
".pill{font-size:11px;border:1px solid #345976;border-radius:99px;padding:4px 8px;color:#b7e6ca;background:#183c36}",
"@media(max-width:900px){.layout{grid-template-columns:1fr}.settings{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:12px}.card{padding:12px}}",
"@media(max-width:530px){header{padding:12px}main{padding:13px 8px}.settings{display:block}.row{justify-content:flex-start}.map canvas{aspect-ratio:16/9}}"
].join("");

export function dynamicsLabPage() {
  return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<meta name="robots" content="noindex,nofollow,noarchive"><title>ECMWF Dynamik-Studio · Privat</title><style>' + STYLE + '</style></head><body>' +
    '<header><div><small>CLIMATE DASHBOARD · GESCHÜTZTES LABOR</small><strong>ECMWF Dynamik- &amp; Jetstream-Studio</strong> <span class="pill">Privat</span></div>' +
    '<nav><a href="/dynamik/shapiro">Shapiro-Keyser-Monitor</a><a href="/wolkenlabor">Wolkenlabor</a><a href="/">Alpenwetter</a><form action="/logout" method="POST"><button>Abmelden</button></form></nav></header>' +
    '<main><h1>Strömung, Feuchte &amp; Tropopausendynamik</h1><p class="lead">Originale ECMWF-IFS-Ausgangsfelder mit transparent gekennzeichneten Berechnungen. Die Animation zeigt nur bestätigte Modellzeitpunkte; fehlende Daten werden nicht ergänzt.</p>' +
    '<div class="layout"><section class="card"><div class="row"><strong id="run">ECMWF IFS · Datenstand wird geprüft</strong><span class="timestamp" id="valid">–</span></div>' +
    '<div class="map"><canvas id="map" width="1600" height="900" aria-label="ECMWF-Karte mit atmosphärischen Dynamikfeldern" role="img"></canvas></div>' +
    '<div class="legend"><strong>PWAT</strong><span>0 mm</span><div class="bar"></div><span>70+ mm</span></div>' +
    '<div class="row"><button id="play" class="primary" disabled>▶ Start</button>' +
    '<input id="timeline" type="range" min="0" max="0" value="0" aria-label="Prognosestunde" disabled>' +
    '<label>Tempo <select id="speed"><option value="0.5">0,5 ×</option><option value="1" selected>1 ×</option><option value="2">2 ×</option><option value="4">4 ×</option></select></label></div>' +
    '<div class="row"><button id="save" disabled>PNG exportieren</button><button id="record" disabled>WebM aufnehmen</button><button id="refresh">↻ Lauf prüfen</button></div>' +
    '<div class="status" id="status" role="status" aria-live="polite">Suche nach vollständigen ECMWF-Modellfeldern …</div>' +
    '</section><aside class="card"><h2>Karte einstellen</h2><label for="region">Region</label><select id="region">' +
    '<option value="atlantik" selected>Europa &amp; Nordatlantik</option><option value="europa">Europa</option>' +
    '<option value="suedwest">Südwesteuropa · Azoren · Kanaren</option></select>' +
    '<h2 style="margin-top:25px">Ebenen einzeln schalten</h2><div class="settings">' +
    '<label><input id="tcwv" type="checkbox" checked>Niederschlagbares Wasser · mm</label>' +
    '<label><input id="jet" type="checkbox" checked>250-hPa-Jet · schwarze Linien</label>' +
    '<label><input id="ascent" type="checkbox" checked>400–600-hPa-Aufstieg · rot</label>' +
    '<label><input id="pv" type="checkbox" checked>200–300-hPa-PV · violett</label>' +
    '<label><input id="irrot" type="checkbox" checked>Irrotationaler Höhenwind · Pfeile</label></div>' +
    '<p class="note">Feste PWAT-Skala 0–70 mm. Jet-Konturen 30–100 m/s, Aufstieg 0,2–1,0 Pa/s und PV-Konturen 1,5–8 PVU. Die Farben ändern sich nicht zwischen Prognosezeiten.</p>' +
    '<h2>Wissenschaftliche Einordnung</h2><p class="note">PV: dreistufige isobare Ertel-PV-Näherung samt Kipptermen. Irrotationaler Wind: regionale Poisson-Inversion (Neumann-Randbedingungen, vereinfachte Metrik). Beide Diagnosen sind keine Originalfelder und insbesondere am Kartenrand nur eingeschränkt interpretierbar.</p>' +
    '<p class="note">Daten: ECMWF IFS 0,25° Open Data · CC BY 4.0. Kartengrenzen: Natural Earth. Videoexport: WebM (browserabhängig). Die Anmeldung schützt die Oberfläche und den Datenproxy; ECMWF-Rohdaten sind öffentlich.</p>' +
    '</aside></div></main><script>' + DYNAMICS_CLIENT_SOURCE + '</script></body></html>';
}

export function dynamicsLabLoginPage() {
  return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
   '<meta name="robots" content="noindex,nofollow,noarchive"><title>Privates Dynamik-Studio · Anmeldung</title>' +
   '<style>:root{color-scheme:dark;font-family:system-ui}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0d1929;color:#eff7ff}' +
   'main{width:min(430px,calc(100% - 30px));background:#142a40;border:1px solid #395c75;border-radius:15px;padding:26px;box-sizing:border-box}' +
   'p{color:#bed3e5}label{display:block;margin:12px 0 6px}input,button{box-sizing:border-box;width:100%;padding:12px;font:inherit;border-radius:8px}' +
   'input{color:white;background:#0b1d30;border:1px solid #57758f}button{background:#237aad;border:0;margin-top:13px;color:white;font-weight:700;cursor:pointer}</style>' +
   '</head><body><main><small>GESCHÜTZTER TESTBEREICH</small><h1>ECMWF Dynamik-Studio</h1>' +
   '<p>Die interaktive Modellanimation erfordert das vorhandene Alpenwetter-Passwort.</p>' +
   '<form method="POST" action="/login"><input type="hidden" name="next" value="/dynamik">' +
   '<label for="pwd">Passwort</label><input id="pwd" type="password" name="password" autocomplete="current-password" required>' +
   '<button type="submit">Studio öffnen</button></form></main></body></html>';
}
