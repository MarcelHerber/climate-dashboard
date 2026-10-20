import { LAB_JS } from "./cloud-lab-client.js";
import { LAB_CSS } from "./cloud-lab-style.js";

const DATA_SOURCE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/icon-cloud-film-data/data/icon-cloud-film/";
const GEO_SOURCE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/seasonal-europe-data/data/seasonal-europe/geography_50m.json";

export function cloudLabLoginPage(){
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
  '<meta name="robots" content="noindex,nofollow,noarchive"><title>Privates Wolkenfilm-Labor · Anmeldung</title>'+
  '<style>:root{color-scheme:dark;font-family:system-ui}body{min-height:100vh;display:grid;place-items:center;margin:0;background:#0d1a2b;color:#ecf4fb}main{width:min(420px,calc(100% - 30px));background:#14273e;border:1px solid #3c5771;border-radius:16px;padding:28px;box-sizing:border-box}h1{font-size:24px;margin:0 0 10px}p{color:#a9c2d4;line-height:1.6}input{box-sizing:border-box;width:100%;padding:12px;background:#0a1c2c;border:1px solid #4e718b;border-radius:7px;color:#fff;font:inherit}button{width:100%;margin-top:13px;padding:12px;border:0;border-radius:7px;background:#277caa;color:#fff;font:inherit;font-weight:700;cursor:pointer}</style>'+
  '</head><body><main><div style="color:#b4ecce;font-size:12px;font-weight:bold">GESCHÜTZTER TESTBEREICH</div>'+
  '<h1>ICON-EU Wolkenfilm-Labor</h1><p>Nur mit dem serverseitigen Alpenwetter-Passwort zugänglich. Kein öffentlicher Navigationspunkt.</p>'+
  '<form method="POST" action="/login"><input type="hidden" name="next" value="/wolkenlabor">'+
  '<label for="pwd">Passwort</label><input id="pwd" type="password" name="password" autocomplete="current-password" required>'+
  '<button type="submit">Labor öffnen →</button></form><p style="font-size:12px">Für deine private Entwicklungsumgebung.</p></main></body></html>';
}

export function cloudLabPage(){
 const layerLabels=[["clcl","Tiefe Wolken"],["clcm","Mittelhohe Wolken"],["clch","Hohe Wolken"],["clct","Gesamtbewölkung"]];
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
 '<meta name="robots" content="noindex,nofollow,noarchive"><title>ICON-EU Wolkenfilm-Labor · Privat</title><style>'+
 LAB_CSS+'</style></head><body><header><div><div class="sub">Climate Dashboard · privates Studio</div><strong>ICON-EU Wolkenfilm-Labor</strong> <span class="badge">Geschützt</span></div>'+
 '<nav><a href="/">Alpenwetter</a><form action="/logout" method="POST"><button type="submit">Abmelden</button></form></nav></header>'+
 '<main><h1>Wolkenfilm-Studio</h1><p class="lead">Experimentelle TV-Wetterfilm-Darstellung auf Basis echter ICON-EU-Wolkenprognosen. Drei Höhenschichten lassen sich unabhängig in Deckkraft, Kontrast, Farbtönung und Bedeckungsschwelle anpassen. Keine Polarlichtprodukte und keine künstlichen Wolkenfelder.</p>'+
 '<div class="layout"><section class="card">'+
 '<div class="toolbar"><div><strong>Feste Europakarte</strong> <span class="pill" id="runLabel">ICON-EU lädt …</span></div>'+
 '<div><button id="reloadCloud" type="button">↻ Neuer Datenstand</button></div></div>'+
 '<div class="stage"><canvas id="filmCanvas" width="1120" height="700" role="img" aria-label="ICON-EU-Wolkenfilm mit Ländergrenzen auf Europa"></canvas>'+
 '<div class="overlay" id="cloudOverlay">Echte DWD-Modellfelder werden geladen …</div></div>'+
 '<div class="timing"><strong id="forecastTime">–</strong><span>Interpolierte Visualisierung zwischen Modellzeitschritten</span></div>'+
 '<div class="controls"><button id="playCloud" class="main" disabled>▶ Abspielen</button>'+
 '<input id="frameSlider" type="range" min="0" max="12" step="1" value="0" aria-label="Prognosezeit auswählen">'+
 '<label>Geschwindigkeit <select id="speedCloud"><option value="0.5">Langsam</option><option value="1" selected>Normal</option><option value="2">Schnell</option><option value="4">Sehr schnell</option></select></label></div>'+
 '<div class="controls"><button id="saveCloud" type="button" disabled>PNG speichern ↓</button>'+
 '<button id="recordCloud" type="button" disabled>WebM-Film aufnehmen ↓</button>'+
 '<span class="secondary">Videodownload je nach Browser als WebM.</span></div>'+
 '<div class="status" id="cloudStatus" role="status">Datenprüfung startet …</div></section>'+
 '<aside class="card"><h2>Darstellung bearbeiten</h2>'+
 '<label class="secondary" for="mode">Sicht</label><select id="mode">'+
 '<option value="mix">Gemeinsamer Wolkenfilm</option>'+
 '<option value="clcl">Nur tiefe Wolken (CLCL)</option>'+
 '<option value="clcm">Nur mittelhohe Wolken (CLCM)</option>'+
 '<option value="clch">Nur hohe Wolken (CLCH)</option>'+
 '<option value="clct">Nur Gesamtbewölkung (CLCT)</option>'+
 '<option value="panel">4er-Panel der Wolkenfelder</option></select>'+
 '<p class="secondary">Die Wolkenebenen sind separate Modell-Bedeckungsgrade – sie werden nicht als Prozentzahlen addiert.</p>'+
 '<div class="divider"></div><label class="secondary" for="theme">Kartenstil</label>'+
 '<select id="theme"><option value="tv">Fernsehkarte / hellere Landflächen</option><option value="sat">Satellitenlook / dunkler Hintergrund</option></select>'+
 '<div class="divider"></div><h2>Wolkenschichten</h2><div class="layerGrid" id="layerGrid"></div>'+
 '<p class="secondary">Grenzwert: Bedeckung unterhalb des eingestellten Prozents erscheint transparenter. Jeder Regler beeinflusst nur die Darstellung – nicht die DWD-Modelldaten.</p>'+
 '</aside></div><p class="footer">Datenquelle: Deutscher Wetterdienst, ICON-EU Open Data (CLCL, CLCM, CLCH, CLCT; regelmäßiges Lat/Lon-Raster). Die Darstellung ist ein experimenteller, nicht amtlicher Wolkenfilm. Keine Vorhersage von Wolkengattung, vertikaler Mächtigkeit oder Wolkenuntergrenzen. Zugang ausschließlich nach serverseitiger Anmeldung; der ursprüngliche DWD-Datensatz ist öffentlich.</p>'+
 '</main><script>'+LAB_JS+'</script></body></html>';
}

export async function cloudLabData(request,url,securityHeaders){
 const suffix=url.pathname.slice("/wolkenlabor/data/".length);
 let source,mime;
 if(suffix==="current.json"){source=DATA_SOURCE+"current.json";mime="application/json; charset=utf-8";}
 else if(suffix==="geo.json"){source=GEO_SOURCE;mime="application/json; charset=utf-8";}
 else if(/^frames\/\d{10}\/(?:clcl|clcm|clch|clct)_\d{3}\.png$/.test(suffix)){
   source=DATA_SOURCE+suffix;mime="image/png";
 }else return new Response("Unbekannter Datenpfad",{status:404,headers:securityHeaders({"Content-Type":"text/plain; charset=utf-8"})});
 try{
   const response=await fetch(source,{cf:{cacheTtl:suffix==="geo.json"?86400:120,cacheEverything:true},headers:{"User-Agent":"Climate-Dashboard-Cloud-Labor/1.0"}});
   if(!response.ok)return new Response(JSON.stringify({error:"ICON-EU-Wolkenbild nicht bereit",status:response.status}),
     {status:response.status===404?503:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})});
   const h=securityHeaders({"Content-Type":mime});
   // Do not allow authenticated content to be shared-cached by the browser.
   h.set("Cache-Control","private, no-store");
   return new Response(response.body,{status:200,headers:h});
 }catch(err){
   return new Response(JSON.stringify({error:"Datenabruf vorübergehend nicht erreichbar"}),
     {status:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})});
 }
}
