import { RADAR_CLIENT_SOURCE } from "./radar-client.js";

/* All /radarlabor routes are gated by the existing Cloudflare password session. */
const SOURCE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/radar-data/data/radar/";
export async function radarLabData(url, securityHeaders) {
  const path=url.pathname.replace(/^\/radarlabor\/api\//,"");
  if(!/^(?:current\.json|borders_europe\.geojson|frames\/\d{12}\.png)$/.test(path))
    return new Response("Unzulässiger Radar-Dateipfad",{status:400,headers:securityHeaders({"Content-Type":"text/plain"})});
  try{
    const r=await fetch(SOURCE+path,{
      cf:{cacheEverything:true,cacheTtl:path==="current.json"?50:21600}
    });
    if(!r.ok)return new Response(JSON.stringify({error:"DWD-Radarprodukt momentan nicht verfügbar",upstream:r.status}),{
      status:r.status===404?404:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})
    });
    return new Response(r.body,{status:200,headers:securityHeaders({
      "Content-Type":path.endsWith(".png")?"image/png":path.endsWith(".geojson")?"application/geo+json; charset=utf-8":"application/json; charset=utf-8"
    })});
  }catch(_error){
    return new Response(JSON.stringify({error:"Radarquelle nicht erreichbar"}),{
      status:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})
    });
  }
}
export function radarLoginPage(){
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive">'+
 '<title>DWD Radarkomposit · Anmeldung</title><style>:root{color-scheme:dark;font-family:system-ui}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1929;color:#e8f3ff}main{max-width:440px;width:calc(100% - 32px);background:#162b43;border:1px solid #41617d;padding:27px;border-radius:14px;box-sizing:border-box}small{color:#9bcbe9}h1{font-size:24px}p{color:#b9d1e3;line-height:1.6}input,button{font:inherit;box-sizing:border-box;width:100%;padding:12px;margin:10px 0;border-radius:8px}input{border:1px solid #54728b;background:#091d30;color:white}button{background:#1681ba;border:0;color:white;font-weight:700}</style></head><body>'+
 '<main><small>CLIMATE DASHBOARD · PRIVATES RADARLABOR</small><h1>DWD Radarkomposit</h1>'+
 '<p>Radar-Testversion mit realen DWD-RY-Messdaten im 5-Minuten-Raster.</p>'+
 '<form method="POST" action="/login"><input type="hidden" name="next" value="/radarlabor"><label for="pwd">Passwort</label><input id="pwd" type="password" autocomplete="current-password" name="password" required><button type="submit">Radarlabor öffnen</button></form></main></body></html>';
}
const CSS=[
 ":root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#091523;color:#eff7fd}",
 "*{box-sizing:border-box}body{margin:0}a{color:#95cff7;text-decoration:none}a:hover{text-decoration:underline}",
 "header{background:#11283f;border-bottom:1px solid #355873;padding:14px clamp(12px,2.5vw,30px);display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}",
 "header small{color:#a7c8dc;display:block;font-size:11px;letter-spacing:.09em}header strong{font-size:20px}",
 "nav{display:flex;gap:14px;align-items:center;flex-wrap:wrap}nav form{margin:0}",
 "main{max-width:1530px;margin:auto;padding:24px clamp(9px,2vw,28px) 38px}",
 "h1{font-size:clamp(22px,2.5vw,32px);margin:0 0 7px}h2{font-size:16px;margin:0 0 13px}",
 ".intro,.description{line-height:1.6;color:#b3cde0;font-size:13px;max-width:1050px}",
 ".layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:15px;margin:18px 0}",
 ".card{background:#142b42;border:1px solid #365b76;border-radius:13px;padding:15px;min-width:0}",
 ".mapbox{position:relative;background:#e4f0f6;border-radius:9px;overflow:hidden;border:1px solid #456783}",
 ".mapbox canvas{width:100%;height:auto;display:block;aspect-ratio:900/550;touch-action:manipulation}",
 ".mapstamp{position:absolute;top:10px;left:10px;background:#0d253adf;color:white;padding:8px 11px;border-radius:7px;font-size:12px;pointer-events:none}",
 ".bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin:12px 0}",
 "button,select{font:inherit;color:#ecf7ff;border:1px solid #57768c;background:#254762;border-radius:8px;padding:9px 11px;cursor:pointer}",
 "button:disabled{opacity:.45;cursor:default}button:hover:not(:disabled){background:#366583}",
 "button.primary{background:#218bb8;font-weight:750;border-color:#64bddd}",
 "button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #ffc76c;outline-offset:2px}",
 "input[type=range]{accent-color:#6bd1f7;flex:1;min-width:160px}label{font-size:13px;color:#d5e7f4}",
 ".side label{display:block;margin:13px 0 5px}.side select{width:100%;max-width:100%}",
 ".swatches{display:flex;flex-wrap:wrap;gap:5px;margin:9px 0 13px}.swatch{display:flex;flex-direction:column;align-items:center;gap:5px;font-size:10px;color:#c6dcea;min-width:44px}",
 ".color{height:14px;width:44px;border-radius:3px}.status{margin-top:13px;padding:11px;border-radius:7px;background:#22425a;color:#d0ebf9;font-size:13px;line-height:1.6}",
 ".status.error{background:#512b34;color:#ffded5}.note{font-size:12px;color:#a8c8dd;line-height:1.65}",
 ".badge{background:#24485e;border:1px solid #49758e;border-radius:100px;padding:4px 9px;font-size:11px}",
 "@media(max-width:900px){.layout{grid-template-columns:1fr}.side{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 14px}.side h2,.side p,.side #legend{grid-column:1/-1}}",
 "@media(max-width:550px){header{padding:12px}main{padding:13px 8px 30px}.card{padding:9px}.side{display:block}.bar{justify-content:flex-start}.mapstamp{font-size:10px;padding:5px}}"
].join("");
export function radarLabPage(){
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
 '<meta name="robots" content="noindex,nofollow,noarchive"><title>DWD Radarkomposit · Privates Radarlabor</title><style>'+CSS+'</style></head><body>'+
 '<header><div><small>CLIMATE DASHBOARD · PASSWORTGESCHÜTZT</small><strong>DWD Radar-Komposit <span class="badge">Test</span></strong></div>'+
 '<nav><a href="/radarlabor/europa">Europa-Komposit (OPERA)</a><a href="/dynamik">Dynamik-Studio</a><a href="/dynamik/shapiro">Shapiro-Keyser</a><a href="/wolkenlabor">Wolkenlabor</a><form action="/logout" method="POST"><button>Abmelden</button></form></nav></header>'+
 '<main><h1>Radarkomposit Deutschland</h1><p class="intro">DWD RADOLAN RY · 1-km-Radarverbund · qualitätsgeprüfte, aus Radarreflektivität abgeleitete Niederschlagsrate (mm/h), alle 5 Minuten. Keine Stationsaneichung und keine Vorhersage. Fehlende Radarwerte werden als fehlend und nicht als trocken dargestellt.</p>'+
 '<div class="layout"><section class="card">'+
 '<div class="bar"><strong id="product">DWD RY · Daten prüfen …</strong><span id="stamp" class="badge">–</span></div>'+
 '<div class="mapbox"><canvas id="map" width="1800" height="1100" role="img" aria-label="Georeferenziertes DWD-Radarkomposit über Deutschland"></canvas>'+
 '<div class="mapstamp" id="mapStamp">Radardaten werden geladen</div></div>'+
 '<div class="bar"><button id="prev" disabled aria-label="Vorheriges Radarbild">◀</button>'+
 '<button id="play" class="primary" disabled>▶ Animation</button><button id="next" disabled aria-label="Nächstes Radarbild">▶</button>'+
 '<input id="timeline" type="range" min="0" max="0" value="0" disabled aria-label="Radarzeitpunkt wählen"></div>'+
 '<div class="bar"><label>Tempo <select id="speed"><option value="0.5">0,5 ×</option><option value="1" selected>1 ×</option><option value="2">2 ×</option><option value="3">3 ×</option></select></label>'+
 '<label>Rückblick <select id="history"><option value="12">1 Stunde</option><option value="24">2 Stunden</option><option value="36" selected>3 Stunden</option></select></label>'+
 '<button id="refresh">↻ Neu laden</button><button id="png" disabled>PNG exportieren</button></div>'+
 '<div id="status" class="status" role="status" aria-live="polite">Prüfe veröffentlichte DWD-Radarbilder …</div></section>'+
 '<aside class="card side"><h2>Darstellung</h2>'+
 '<label for="region">Kartenausschnitt</label><select id="region"><option value="all">Deutschland und angrenzende Regionen</option>'+
 '<option value="north">Norddeutschland</option><option value="south">Süddeutschland und Alpen</option>'+
 '<option value="west">West- und Mitteldeutschland</option></select>'+
 '<label for="overlay">Radardarstellung</label><select id="overlay"><option value="rain">Niederschlag / mm/h</option><option value="none">Nur Grundkarte</option></select>'+
 '<h2 style="margin-top:24px">Feste Niederschlagsskala</h2><div id="legend" class="swatches"></div>'+
 '<p class="note">Die Skala bleibt bei jedem Bild identisch. Transparent = kein messbarer Niederschlag, grau = kein gültiger Radarwert. Farbflächen stellen Schätzungen der aktuellen Niederschlagsrate dar, keine stündlich gemessene Summe.</p>'+
 '<p class="note">Daten: Deutscher Wetterdienst, RADOLAN RY HDF5 (ODIM). Datenlizenz Deutschland – Namensnennung – Version 2.0. Kartenumrisse: Natural Earth.</p>'+
 '<p class="note">Rohdaten liegen bei DWD und im öffentlichen GitHub-Datenbranch; der Zugang zu dieser Oberfläche und ihrer Daten-API ist durch Cloudflare geschützt.</p>'+
 '</aside></div></main><script>'+RADAR_CLIENT_SOURCE+'</script></body></html>';
}
