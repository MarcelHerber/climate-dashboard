import { SHAPIRO_CLIENT_SOURCE } from "./shapiro-client.js";

const SOURCE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/shapiro-data/data/shapiro/";
const FRAME_RE=/^(?:current\.json|frames\/\d{10}\/(?:thetae|msl|fgen|wind850|wind700|rh700|rh500|pv|jet300|gh500|omega700|u850|v850|profile_(?:wind|rh|omega|theta))_\d{3}\.png)$/;

export async function shapiroData(url,securityHeaders){
 const name=url.pathname.replace(/^\/dynamik\/api\/shapiro\//,"");
 if(!FRAME_RE.test(name))return new Response("Ungültiger Modellpfad",{status:400,headers:securityHeaders({"Content-Type":"text/plain"})});
 try{
  const r=await fetch(SOURCE+name,{cf:{cacheEverything:true,cacheTtl:name==="current.json"?90:86400}});
  if(!r.ok)return new Response(JSON.stringify({error:"Kein vollständig geprüfter Shapiro-Datenlauf",status:r.status}),{
   status:r.status===404?404:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})});
  return new Response(r.body,{status:200,headers:securityHeaders({"Content-Type":name.endsWith(".png")?"image/png":"application/json; charset=utf-8"})});
 }catch(e){return new Response(JSON.stringify({error:"ECMWF-Daten derzeit nicht erreichbar"}),{
  status:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})});}
}

export function shapiroLoginPage(){
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive"><title>Shapiro-Keyser-Monitor · Anmeldung</title>'+
 '<style>:root{color-scheme:dark;font-family:system-ui}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a1828;color:#eff5fc}main{max-width:430px;width:calc(100% - 32px);padding:28px;border:1px solid #31526a;background:#14283f;border-radius:16px}p{color:#a9cadf}label{display:block;margin:12px 0 7px}input,button{width:100%;padding:12px;font:inherit;box-sizing:border-box;border-radius:8px}input{border:1px solid #5a7d97;background:#10273a;color:white}button{background:#247caa;color:white;border:0;margin-top:12px;font-weight:700}</style>'+
 '</head><body><main><small>CLIMATE DASHBOARD · PRIVAT</small><h1>Shapiro-Keyser- &amp; Sting-Jet-Monitor</h1><p>Dasselbe Passwort wie für dein ECMWF-Dynamik-Studio.</p>'+
 '<form method="POST" action="/login"><input type="hidden" name="next" value="/dynamik/shapiro"><label for="pwd">Passwort</label>'+
 '<input id="pwd" type="password" name="password" autocomplete="current-password" required><button type="submit">Monitor öffnen</button></form></main></body></html>';
}

const CSS=[
":root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#0a1524;color:#ecf4fd}",
"*{box-sizing:border-box}body{margin:0}a{color:#9bd8ff;text-decoration:none}a:hover{text-decoration:underline}",
"header{padding:14px clamp(12px,2vw,30px);background:#102238;border-bottom:1px solid #345069;display:flex;gap:12px;justify-content:space-between;align-items:center;flex-wrap:wrap}",
"header small{display:block;color:#a3c5db;font-size:11px;letter-spacing:.07em}header strong{font-size:20px}nav{display:flex;align-items:center;gap:12px;flex-wrap:wrap}nav form{margin:0}",
"button,select{font:inherit;background:#1b3a57;border:1px solid #54748d;border-radius:8px;color:#e7f6ff;padding:9px 12px;cursor:pointer}",
"button:hover:not(:disabled){background:#2f5c7e}button:disabled{opacity:.48;cursor:default}button.primary,button[aria-pressed=true]{background:#d6ecf9;color:#102a42;border-color:#d6ecf9;font-weight:750}",
"button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #f2bb67;outline-offset:2px}",
"main{padding:20px clamp(9px,2vw,28px) 44px;max-width:1740px;margin:auto}h1{font-size:clamp(23px,2.7vw,34px);margin:0 0 8px}h2{font-size:17px;margin:0 0 11px}",
".lead{font-size:13px;max-width:1120px;line-height:1.6;color:#afc9db;margin:0 0 17px}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between}",
".tabs{display:flex;flex-wrap:wrap;gap:9px;margin:12px 0}.card{border:1px solid #31516a;background:#13273d;border-radius:12px;padding:15px;min-width:0}",
".layout{display:grid;grid-template-columns:minmax(0,1fr) 315px;gap:13px;align-items:start}.map{margin-top:10px;background:#d9eafa;border:1px solid #40617c;border-radius:8px;overflow:hidden}",
".map canvas{width:100%;height:auto;display:block;aspect-ratio:16/9;touch-action:manipulation;cursor:crosshair}.section canvas{width:100%;height:auto;display:block;aspect-ratio:1600/490;background:#f0f6fb;border-radius:6px}",
".controls{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin:12px 0}.controls input[type=range]{flex:1;min-width:120px;accent-color:#7bc7f5}.controls select{max-width:180px}",
".meta{font-size:12px;color:#c2d9e9;font-variant-numeric:tabular-nums}.legend{display:flex;align-items:center;gap:9px;margin:12px 0;font-size:12px;flex-wrap:wrap}",
".legendBar{width:min(420px,100%);height:13px;border-radius:5px}.status{background:#1b3d55;border-radius:7px;padding:11px;font-size:13px;line-height:1.6;color:#bfe2f3;margin-top:10px}",
".status.error{background:#522c36;color:#ffd1c8}.explain{color:#bad0e0;font-size:12px;line-height:1.65;margin:7px 0 12px}.side label{display:block;color:#e1effa;font-size:13px;margin:12px 0}",
".side select{max-width:100%;width:100%;margin-top:7px}.side button{max-width:100%}.candidate{border:1px solid #3d627c;border-radius:9px;background:#1b3750;margin:8px 0;padding:10px;text-align:left;width:100%;font-size:12px;line-height:1.6}",
".candidate[aria-pressed=true]{background:#e8eef4;color:#162d42}.note{font-size:12px;color:#afc5d5;line-height:1.65}.section{margin-top:14px}.section .row{margin-bottom:12px}#crossHint{color:#bfd6e8;font-size:12px;margin:8px 0}",
"@media(max-width:970px){.layout{grid-template-columns:1fr}main{padding:13px 9px 36px}.side{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 18px}.side h2{grid-column:1/-1;margin-top:8px}}",
"@media(max-width:550px){header{padding:12px}.side{display:block}.card{padding:10px}.tabs button{flex:1 1 100%;text-align:left}#play{min-width:110px}}"
].join("");

export function shapiroLabPage(){
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
 '<meta name="robots" content="noindex,nofollow,noarchive"><title>Shapiro-Keyser-Monitor · ECMWF · Privat</title><style>'+CSS+'</style></head><body>'+
 '<header><div><small>CLIMATE DASHBOARD · PASSWORTGESCHÜTZT</small><strong>Shapiro-Keyser- &amp; Sting-Jet-Monitor</strong></div><nav>'+
 '<a href="/radarlabor">Radarkomposit (Test)</a><a href="/dynamik">ECMWF Dynamik-Studio</a><a href="/wolkenlabor">Wolkenlabor</a><form action="/logout" method="POST"><button>Abmelden</button></form></nav></header>'+
 '<main><h1>Extratropische Zyklonen untersuchen</h1><p class="lead">Drei synchronisierte Diagnosekarten, vertikale Modellquerschnitte und objektive Tiefdruck-Kandidaten. Reale ECMWF-IFS-Felder · 0,25° · alle 3 Stunden. Ein Verdachtsfall ist keine Bestätigung einer Shapiro-Keyser-Zyklone oder eines Sting Jets.</p>'+
 '<div class="tabs" role="group" aria-label="Diagnosekarte wählen">'+
 '<button id="viewA" aria-pressed="true" type="button">A · Frontalstruktur / Warm Seclusion</button>'+
 '<button id="viewB" aria-pressed="false" type="button">B · Wind / Sting-Jet-Potenzial</button>'+
 '<button id="viewC" aria-pressed="false" type="button">C · PV / Höhendynamik</button></div>'+
 '<div class="layout"><section class="card"><div class="row"><strong id="modelRun">ECMWF-Datenstand wird geprüft</strong><span id="time" class="meta">–</span></div>'+
 '<div class="map"><canvas id="synopticMap" width="1600" height="900" role="img" aria-label="Shapiro-Keyser-Diagnosekarte mit Ländergrenzen und Wetterfeldern"></canvas></div>'+
 '<div class="legend"><strong id="legendName">Theta-e 850 hPa</strong><span id="legendLow">260 K</span><div id="legendBar" class="legendBar"></div><span id="legendHigh">370 K</span></div>'+
 '<div class="controls"><button id="play" class="primary" disabled>▶ Abspielen</button><input id="slider" type="range" min="0" max="0" value="0" disabled aria-label="Prognosezeit wählen">'+
 '<label>Tempo <select id="speed"><option value="0.5">0,5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option></select></label></div>'+
 '<div class="controls"><button id="save" disabled>PNG speichern</button><button id="reload">↻ Daten neu prüfen</button>'+
 '<label>Region <select id="region"><option value="atlantic">Nordatlantik &amp; Europa</option><option value="europe">Europa</option>'+
 '<option value="northeast">Nordatlantik / Britische Inseln</option><option value="mediterranean">Mittelmeer / Westeuropa</option></select></label></div>'+
 '<p id="panelNote" class="explain">Theta-e 850 hPa (Farbflächen), 4-hPa-Isobaren, kinematische 850-hPa-Frontogenese (Rot) und Frontolyse (Blau).</p>'+
 '<div id="status" class="status" role="status">Prüfe aktuelle ECMWF-Prognosen …</div></section>'+
 '<aside class="card side"><h2>Automatische Kandidatensuche</h2><p class="note">Lokale Bodendruck-Minima werden mit Druckausprägung, 850-hPa-Frontogenese, Wind und einem Theta-e-Kernindikator abgeglichen. Kein automatischer Nachweis des Zyklonentyps.</p>'+
 '<div id="candidateList" aria-live="polite">Noch keine Prognosen geladen.</div><div id="candidateDetails" class="status">Wähle einen Kandidaten für die Diagnosewerte.</div>'+
 '<h2>Methodik und Einschränkungen</h2><p class="note">Frontogenese: kinematischer Horizontalanteil aus geglätteter 850-hPa-Theta-e. PV: dreistufige 200–300-hPa-Näherung. Die trockene Intrusion wird über RH700/RH500 nur indikativ markiert; ein Sting Jet benötigt vertikale und möglichst Lagrangesche Untersuchung.</p>'+
 '<p class="note">Für große Gefahrenlagen hochaufgelöste Modell- und Beobachtungsdaten zusätzlich vergleichen. Feste Skalen. Daten: ECMWF IFS Open Data CC BY 4.0.</p></aside></div>'+
 '<section class="card section"><div class="row"><h2>Vertikaler Querschnitt · 925–300 hPa</h2><div class="controls">'+
 '<button id="crossPick" type="button" aria-pressed="false">Punkte A–B auf Karte wählen</button><button id="crossClear">Linie zurücksetzen</button>'+
 '<label>Feld <select id="profile"><option value="wind">Windgeschwindigkeit (m/s)</option><option value="rh">Relative Feuchte (%)</option>'+
 '<option value="omega">Vertikalgeschwindigkeit (Pa/s)</option><option value="theta">Potenzielle Temperatur (K)</option></select></label></div></div>'+
 '<p id="crossHint">„Punkte A–B auf Karte wählen“ aktivieren und zwei Stellen auf der Wetterkarte anklicken. Unterirdische Druckflächen werden maskiert.</p>'+
 '<canvas id="crossCanvas" width="1600" height="490" role="img" aria-label="Vertikaler ECMWF-Modellquerschnitt zwischen zwei gewählten Punkten"></canvas>'+
 '<p class="note">Interpolation zwischen originalen Druckniveaus entlang gerader Länge-/Breite-Linie. Kein Luftpaket-Trajektorienmodell; unterirdische Druckflächen mit ECMWF-Oberflächendruck maskiert.</p>'+
 '</section></main><script>'+SHAPIRO_CLIENT_SOURCE+'</script></body></html>';
}
