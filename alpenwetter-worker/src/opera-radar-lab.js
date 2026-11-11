import {OPERA_RADAR_CLIENT_SOURCE} from "./opera-radar-client.js";

/* URLs and data validated server-side; public OPERA upstream is queried only via
   this same-origin route after existing Cloudflare password cookie check. */
const BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/opera-radar-data/data/opera/";
export async function operaRadarData(url,securityHeaders){
  const path=url.pathname.replace(/^\/radarlabor\/api\/opera\//,"");
  if(!/^(?:current\.json|frames\/(?:dbzh|rate)_\d{12}\.png)$/.test(path)){
    return new Response("Ungültiger OPERA-Radar-Dateipfad",{status:400,headers:securityHeaders({"Content-Type":"text/plain; charset=utf-8"})});
  }
  try{
    const r=await fetch(BASE+path,{
      cf:{cacheEverything:true,cacheTtl:path==="current.json"?65:43200}
    });
    if(!r.ok){
      return new Response(JSON.stringify({error:"Europäischer OPERA-Radardatensatz nicht verfügbar",upstream:r.status}),{
        status:r.status===404?404:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})
      });
    }
    return new Response(r.body,{
      headers:securityHeaders({"Content-Type":path.endsWith(".png")?"image/png":"application/json; charset=utf-8"})
    });
  }catch(_error){
    return new Response(JSON.stringify({error:"OPERA-Daten derzeit nicht erreichbar"}),{
      status:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})
    });
  }
}
export function operaRadarLoginPage(){
  return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive">'+
  '<title>OPERA Europa-Radar · Passwort</title><style>:root{font-family:system-ui;color-scheme:dark}body{margin:0;background:#0c1928;min-height:100vh;color:#eff8ff;display:grid;place-items:center}main{background:#142d44;border:1px solid #315c77;border-radius:15px;padding:26px;width:min(440px,calc(100% - 30px));box-sizing:border-box}p{line-height:1.6;color:#b9d2e5}label{display:block;margin:12px 0 5px}input,button{display:block;font:inherit;padding:12px;width:100%;box-sizing:border-box;border-radius:8px}input{background:#10263d;border:1px solid #54839d;color:white}button{background:#167daf;border:0;color:white;margin-top:14px;cursor:pointer;font-weight:700}</style></head><body><main>'+
  '<small>CLIMATE DASHBOARD · PRIVATES RADARLABOR</small><h1>OPERA-Europakomposit</h1><p>Amtliche Radarprodukte von EUMETNET OPERA. Anmeldung wie beim deutschen Radarlabor.</p>'+
  '<form method="POST" action="/login"><input type="hidden" name="next" value="/radarlabor/europa"><label for="password">Passwort</label><input id="password" type="password" name="password" autocomplete="current-password" required><button type="submit">Europa-Radar öffnen</button></form></main></body></html>';
}
const CSS=[
":root{color-scheme:dark;background:#0b1928;color:#edf5fa;font-family:Inter,system-ui,sans-serif}",
"*{box-sizing:border-box}body{margin:0}a{color:#a6daf7;text-decoration:none}a:hover{text-decoration:underline}",
"header{background:#102942;border-bottom:1px solid #365873;padding:13px clamp(10px,2.5vw,28px);display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}",
"header small{display:block;color:#a6c9db;letter-spacing:.06em;font-size:11px}header strong{font-size:19px}nav{display:flex;gap:14px;align-items:center;flex-wrap:wrap}nav form{margin:0}",
"main{max-width:1640px;margin:auto;padding:20px clamp(8px,2vw,25px) 36px}h1{font-size:clamp(23px,3vw,33px);margin:0 0 8px}h2{font-size:17px;margin:0 0 13px}",
".intro,.note{font-size:13px;color:#b6cfe1;line-height:1.65;max-width:1000px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;margin:16px 0}",
".card{background:#152d44;border:1px solid #335c79;border-radius:13px;padding:14px;min-width:0}",
".tabs{display:flex;flex-wrap:wrap;gap:9px;margin:15px 0}.tabs button[aria-pressed=true]{background:#b9e2f9;color:#0c2843;font-weight:750}",
"button,select{background:#234967;color:#f0f8ff;font:inherit;border:1px solid #527e9e;border-radius:8px;padding:9px 11px;cursor:pointer}",
"button:disabled{opacity:.45;cursor:default}button:hover:not(:disabled){background:#346488}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #f9d185;outline-offset:2px}",
"button.primary{background:#187fb0;font-weight:700;border-color:#40a9c9}label{font-size:13px;color:#cfdfef}",
".row{display:flex;gap:9px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:11px 0}.row input[type=range]{flex:1;min-width:140px;accent-color:#54c3eb}",
".map{position:relative;border:1px solid #60809b;border-radius:8px;overflow:hidden;background:#e0eaf1}",
".map canvas{display:block;width:100%;height:auto;aspect-ratio:74/44;touch-action:manipulation}",
".stamp{position:absolute;top:11px;left:11px;padding:7px 11px;background:#0e273de0;color:white;border-radius:6px;font-size:12px;pointer-events:none}",
".tag{font-size:12px;background:#20455e;border-radius:99px;border:1px solid #3f6c87;padding:5px 9px}",
".legend{display:flex;flex-wrap:wrap;gap:5px;margin-top:13px}.item{display:flex;flex-direction:column;gap:5px;align-items:center;font-size:10px;color:#c7dceb;min-width:45px}",
".swatch{width:45px;height:14px;border-radius:3px}.side label{display:block;margin:13px 0 5px}.side select{width:100%;max-width:100%}",
".status{margin-top:12px;padding:11px;border-radius:8px;background:#214760;color:#d7edfb;line-height:1.6;font-size:13px}",
".status.error{background:#4e2d39;color:#ffd5d6}.explainer{font-size:12px;color:#b7cede;line-height:1.65}",
"@media(max-width:940px){.layout{grid-template-columns:1fr}}@media(max-width:520px){main{padding:12px 7px 32px}.card{padding:9px}.stamp{font-size:10px;padding:5px}.tabs button{flex:1 1 100%}}"
].join("");
export function operaRadarPage(){
  return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
  '<meta name="robots" content="noindex,nofollow,noarchive"><title>OPERA Europa-Radarkomposit · Privat</title><style>'+CSS+'</style></head><body>'+
  '<header><div><small>CLIMATE DASHBOARD · PASSWORTGESCHÜTZT</small><strong>EUMETNET OPERA · Europa-Radarkomposit</strong></div>'+
  '<nav><a href="/radarlabor/azoren">Azoren · IPMA</a><a href="/radarlabor/kanaren">Kanaren · AEMET</a><a href="/radarlabor">DWD Deutschland</a><a href="/dynamik">Dynamik-Studio</a><form action="/logout" method="POST"><button>Abmelden</button></form></nav></header>'+
  '<main><h1>Radar über Europa</h1><p class="intro">Zwei getrennte amtliche Radarkomposite: CIRRUS zeigt maximale Reflektivität in dBZ (1 km, 5 min); NIMBUS zeigt Niederschlagsrate in mm/h (2 km, 15 min). Beide mit festen Skalen, hochauflösenden Ländergrenzen und geografisch korrekter Projektion. Fehlende Daten sind kein Niederschlagsnachweis.</p>'+
  '<div class="tabs" role="group" aria-label="Radarkomposit wählen"><button id="dbzh" aria-pressed="true">Reflektivität · dBZ · 5 min</button><button id="rate" aria-pressed="false">Niederschlag · mm/h · 15 min</button></div>'+
  '<div class="layout"><section class="card"><div class="row"><strong id="product">OPERA · Daten prüfen …</strong><span id="time" class="tag">–</span></div>'+
  '<div class="map"><canvas id="map" width="1776" height="1056" aria-label="EUMETNET OPERA Radar Europakomposit" role="img"></canvas><span class="stamp" id="stamp">Daten abrufen</span></div>'+
  '<div class="row"><button id="previous" disabled aria-label="Vorheriges Radarbild">◀</button><button class="primary" id="play" disabled>▶ Abspielen</button><button id="next" disabled aria-label="Nächstes Radarbild">▶</button>'+
  '<input id="timeline" type="range" min="0" max="0" value="0" aria-label="OPERA Radarzeitpunkt" disabled></div>'+
  '<div class="row"><label>Tempo <select id="speed"><option value=".5">0,5 ×</option><option value="1" selected>1 ×</option><option value="2">2 ×</option><option value="4">4 ×</option></select></label>'+
  '<button id="reload">↻ Daten prüfen</button><button id="save" disabled>PNG speichern</button></div>'+
  '<div class="status" id="status" role="status" aria-live="polite">Lade OPERA-Europadaten …</div></section>'+
  '<aside class="card side"><h2>Darstellung</h2><label for="region">Kartenausschnitt</label>'+
  '<select id="region"><option value="all">Europa und Nordatlantik</option><option value="central">Mitteleuropa</option><option value="north">Nord- und Westeuropa</option><option value="south">Südeuropa / Mittelmeer</option><option value="balearics">Balearen – Mallorca, Menorca, Ibiza</option></select>'+
  '<label for="overlay">Radarebene</label><select id="overlay"><option value="on">Einblenden</option><option value="off">Ausblenden</option></select>'+
  '<h2 style="margin-top:22px">Feste Farblegende</h2><div id="legend" class="legend"></div>'+
  '<p id="legendNote" class="explainer">Die dBZ-Skala beschreibt Radarreflektivität und ist keine direkt gemessene Regenrate.</p>'+
  '<p class="explainer">Radar ohne Echo = transparent. Radar ohne gültige Beobachtung = grau. Die Projektion entspricht dem geografischen WGS84-Ausschnitt; Europa-Raster werden direkt aus den amtlichen OPERA-GeoTIFFs reprojiziert.</p>'+
  '<p class="explainer">Quelle: © EUMETNET OPERA, CC BY 4.0, bereitgestellt über MeteoGate/ORD. Ländergrenzen: Natural Earth 1:10m (Public Domain).</p>'+
  '</aside></div></main><script>'+OPERA_RADAR_CLIENT_SOURCE+'</script></body></html>';
}
