import { CANARIAS_RADAR_CLIENT_SOURCE } from "./canarias-radar-client.js";

const SOURCE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/canarias-radar-data/data/canarias/";
export async function canariasRadarData(url,securityHeaders){
  const rest=url.pathname.replace(/^\/radarlabor\/api\/canarias\//,"");
  if(!/^(?:current\.json|frames\/\d{12}\.png)$/.test(rest)){
    return new Response("Ungültiger AEMET-Datenpfad",{status:400,headers:securityHeaders({"Content-Type":"text/plain; charset=utf-8"})});
  }
  try{
    const r=await fetch(SOURCE+rest,{cf:{cacheEverything:true,cacheTtl:rest==="current.json"?60:43200}});
    if(!r.ok)return new Response(JSON.stringify({error:"AEMET-Kanarenradar derzeit nicht verfügbar",status:r.status}),{
      status:r.status===404?404:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})});
    return new Response(r.body,{headers:securityHeaders({
      "Content-Type":rest.endsWith(".png")?"image/png":"application/json; charset=utf-8"
    })});
  }catch(_error){
    return new Response(JSON.stringify({error:"AEMET-Radardaten momentan nicht erreichbar"}),{
      status:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})});
  }
}
export function canariasRadarLoginPage(){
  return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive"><title>AEMET Kanaren-Radar · Anmeldung</title>'+
  '<style>:root{color-scheme:dark;font-family:system-ui}body{min-height:100vh;margin:0;background:#0b1828;color:#eef7ff;display:grid;place-items:center}main{width:min(440px,calc(100% - 36px));padding:26px;background:#162c44;border:1px solid #456d83;border-radius:15px;box-sizing:border-box}p{color:#bcd5e8;line-height:1.6}label{display:block;margin:14px 0 7px}input,button{font:inherit;padding:12px;width:100%;box-sizing:border-box;border-radius:8px}input{background:#0d1f33;color:white;border:1px solid #65859e}button{background:#2387b5;border:0;color:white;margin-top:13px;font-weight:700;cursor:pointer}</style></head><body><main>'+
  '<small>CLIMATE DASHBOARD · PASSWORTGESCHÜTZT</small><h1>Radar Kanarische Inseln</h1><p>AEMET-Reflektivität, 10-Minuten-Messungen aus Original-GeoTIFFs. Dieselbe Anmeldung wie beim Europakomposit.</p>'+
  '<form method="POST" action="/login"><input type="hidden" name="next" value="/radarlabor/kanaren">'+
  '<label for="pwd">Passwort</label><input id="pwd" name="password" type="password" autocomplete="current-password" required>'+
  '<button type="submit">Kanaren-Radar öffnen</button></form></main></body></html>';
}
const STYLES=[
":root{color-scheme:dark;background:#0b1726;color:#eaf5ff;font-family:Inter,system-ui,sans-serif}",
"*{box-sizing:border-box}body{margin:0}a{color:#9cd5f6;text-decoration:none}a:hover{text-decoration:underline}",
"header{background:#10263c;border-bottom:1px solid #36566e;padding:14px clamp(10px,2vw,28px);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}",
"header small{display:block;color:#a0c5dc;letter-spacing:.08em;font-size:11px}header strong{font-size:21px}nav{display:flex;gap:13px;flex-wrap:wrap;align-items:center}nav form{margin:0}",
"main{max-width:1580px;margin:0 auto;padding:20px clamp(8px,2vw,26px) 45px}",
"h1{font-size:clamp(23px,2.8vw,34px);margin:0 0 7px}h2{font-size:17px}",
".intro,.note{font-size:13px;color:#b8cfdf;line-height:1.65;max-width:1100px}",
".layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;margin:16px 0}",
".card{background:#152d44;border:1px solid #355e7c;border-radius:12px;padding:15px;min-width:0}",
".row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between;margin:12px 0}",
".row input[type=range]{flex:1;min-width:135px;accent-color:#80cafa}",
"button,select{font:inherit;background:#234764;color:#f0f8ff;border:1px solid #507c9a;padding:9px 12px;border-radius:8px;cursor:pointer}",
"button:hover:not(:disabled){background:#315c78}button:disabled{opacity:.46;cursor:default}button.primary{background:#187faa;font-weight:700}",
"button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #ffd37e;outline-offset:2px}",
".map{position:relative;border-radius:10px;overflow:hidden;border:1px solid #476b88;background:#e2eef5}",
".map canvas{width:100%;height:auto;display:block;aspect-ratio:1460/720}",
".stamp{position:absolute;top:10px;left:10px;background:#132b41e0;color:white;border-radius:6px;padding:8px 11px;font-size:12px;pointer-events:none}",
".tag{border:1px solid #46738b;background:#21455d;border-radius:99px;padding:5px 9px;font-size:12px}",
".status{background:#21465e;color:#d1ebfa;padding:11px;border-radius:8px;font-size:13px;line-height:1.6;margin-top:10px}",
".status.error{background:#512b36;color:#ffd7cb}",
".side select{display:block;width:100%;margin:7px 0 15px}.side label{font-size:13px;color:#c9dfef}",
".legend{display:flex;gap:5px;flex-wrap:wrap;margin:11px 0 22px}",
".swatch{display:flex;flex-direction:column;align-items:center;gap:6px;min-width:45px;font-size:10px;color:#c8e0ed}",
".color{width:46px;height:15px;border-radius:3px}",
"@media(max-width:930px){.layout{grid-template-columns:1fr}}",
"@media(max-width:540px){main{padding:12px 8px 28px}.card{padding:10px}.stamp{font-size:10px;padding:6px}header{padding:12px}}"
].join("");

export function canariasRadarPage(){
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
 '<meta name="robots" content="noindex,nofollow,noarchive"><title>AEMET-Kanaren-Radar · Privat</title><style>'+STYLES+'</style></head><body>'+
 '<header><div><small>CLIMATE DASHBOARD · PRIVATES RADARLABOR</small><strong>AEMET · Kanarische Inseln</strong></div>'+
 '<nav><a href="/radarlabor/azoren">Azoren · IPMA</a><a href="/radarlabor/europa">OPERA Europa / Balearen</a><a href="/radarlabor">Deutschland</a>'+
 '<form action="/logout" method="POST"><button>Abmelden</button></form></nav></header>'+
 '<main><h1>Radar Kanarische Inseln</h1><p class="intro">Amtliches AEMET-Kanarenradar (LPA / Com-Canarias). Reflektivität der untersten 0,5°-Elevation in dBZ, im 10-Minuten-Raster. Die GeoTIFFs werden geografisch umgerechnet und anhand der originalen AEMET-Farbklassen dargestellt.</p>'+
 '<div class="layout"><section class="card"><div class="row"><strong id="model">AEMET · Radardaten prüfen</strong><span class="tag" id="time">–</span></div>'+
 '<div class="map"><canvas id="radar" width="1460" height="720" role="img" aria-label="Georeferenzierte AEMET-Radarmessungen für die Kanarischen Inseln"></canvas>'+
 '<span id="stamp" class="stamp">Messwerte werden geprüft</span></div>'+
 '<div class="row"><button id="prev" disabled>◀</button><button id="play" class="primary" disabled>▶ Animation</button><button id="next" disabled>▶</button>'+
 '<input id="timeline" type="range" min="0" max="0" value="0" disabled aria-label="Zeitpunkt der AEMET-Radarmessung wählen"></div>'+
 '<div class="row"><label>Tempo <select id="speed"><option value=".5">0,5 ×</option><option value="1" selected>1 ×</option><option value="2">2 ×</option><option value="4">4 ×</option></select></label>'+
 '<button id="refresh">↻ Daten neu laden</button><button id="png" disabled>PNG speichern</button></div>'+
 '<div id="status" class="status" role="status" aria-live="polite">AEMET-Kanaren-Radardaten werden geladen …</div></section>'+
 '<aside class="card side"><h2>Ansicht</h2><label for="region">Ausschnitt</label><select id="region">'+
 '<option value="all">Alle Kanarischen Inseln</option><option value="west">La Palma / El Hierro / La Gomera</option>'+
 '<option value="central">Teneriffa / Gran Canaria</option><option value="east">Lanzarote / Fuerteventura</option></select>'+
 '<label for="layer">Radardarstellung</label><select id="layer"><option value="rain">Reflektivität anzeigen</option><option value="off">Nur Basiskarte</option></select>'+
 '<h2>Feste AEMET-dBZ-Skala</h2><div id="legend" class="legend"></div>'+
 '<p class="note">Die Radarfarbklassen stammen aus der Originaldatei (ESCALA). Transparente Flächen sind ohne dekodiertes Echo oder außerhalb der tatsächlichen Radar-Abdeckung – sie sind <strong>kein Nachweis für trockenes Wetter</strong>.</p>'+
 '<p class="note">Das AEMET-Radar deckt nicht zwangsläufig jede Insel und jede Höhenlage vollständig ab. Niedrige Niederschläge können wegen Abschattung oder Strahlhöhe übersehen werden.</p>'+
 '<p class="note">Quelle: © AEMET, mit Quellenangabe weiterverwendet. Küsten- und Landesgrenzen: Natural Earth, 1:10 Millionen.</p></aside></div>'+
 '</main><script>'+CANARIAS_RADAR_CLIENT_SOURCE+'</script></body></html>';
}
