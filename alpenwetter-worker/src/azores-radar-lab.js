import { AZORES_RADAR_CLIENT_SOURCE } from "./azores-radar-client.js";

const IPMA_JSON="https://www.ipma.pt/resources.www/transf/radar/imgs-radar-az.json";
const IPMA_IMAGES="https://www.ipma.pt/resources.www/transf/radar/azo/";
const IPMA_LEGEND="https://www.ipma.pt/resources.www/transf/radar/png-geo/legenda-radar.png";
const IMAGE_PATH=/^[A-Za-z0-9_./-]{1,150}\.(?:png|gif|jpe?g|webp)$/i;
function validImage(name) {
  return IMAGE_PATH.test(name) && !name.startsWith("/") && !name.split("/").some(p=>p===".."||p==="."||!p);
}
function parseUTCTime(raw) {
  const t=String(raw||"").trim();
  const match=t.match(/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::(\d\d))?/);
  if(!match)return null;
  const date=new Date(Date.UTC(+match[1],+match[2]-1,+match[3],+match[4],+match[5],+(match[6]||0)));
  return Number.isNaN(date.getTime())?null:date.toISOString();
}
async function latestRadar() {
  const response=await fetch(IPMA_JSON,{cf:{cacheEverything:true,cacheTtl:45}});
  if(!response.ok)throw Error("IPMA Index HTTP "+response.status);
  const input=await response.json();
  if(!Array.isArray(input?.Azores))throw Error("IPMA Azores index changed");
  const rows=[];
  for(const x of input.Azores) {
    const path=String(x?.path||"");
    const utc=parseUTCTime(x?.date);
    if(validImage(path)&&utc)rows.push({utc,image:"frames/"+path});
  }
  rows.sort((a,b)=>a.utc.localeCompare(b.utc));
  const unique=[...new Map(rows.map(r=>[r.utc,r])).values()].slice(-40);
  if(!unique.length)throw Error("IPMA has no georeferenced Azores frames");
  return {
    schema:1,product:"IPMA Açores Radar · Intensidade Precipitação",
    source:"Instituto Português do Mar e da Atmosfera (IPMA)",
    source_url:"https://www.ipma.pt/pt/otempo/obs.remote/index-az.jsp",
    units:"mm/h",time_zone:"UTC",
    overlay_bounds:{west:-35.01827,east:-21.19264,south:32.83497,north:44.06629},
    grid_units:"official_georeferenced_IPMA_png_overlay",
    max_available_hours:3,
    last_available_utc:unique[unique.length-1].utc,
    frames:unique,
  };
}
export async function azoresRadarData(url,securityHeaders) {
  const name=url.pathname.replace(/^\/radarlabor\/api\/azoren\//,"");
  if(name==="current.json") {
    try {
      const manifest=await latestRadar();
      return new Response(JSON.stringify(manifest),{headers:securityHeaders({
        "Content-Type":"application/json; charset=utf-8","Cache-Control":"private, no-store"
      })});
    }catch(_e) {
      return new Response(JSON.stringify({error:"IPMA-Azoren-Datenindex derzeit nicht abrufbar"}),{
        status:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})
      });
    }
  }
  let src=null;
  if(name==="legend.png")src=IPMA_LEGEND;
  else if(name.startsWith("frames/") && validImage(name.slice(7)))src=IPMA_IMAGES+name.slice(7);
  if(!src)return new Response("Unzulässiger Azoren-Radar-Dateipfad",{
    status:400,headers:securityHeaders({"Content-Type":"text/plain; charset=utf-8"})
  });
  try {
    const response=await fetch(src,{cf:{cacheEverything:true,cacheTtl:src===IPMA_LEGEND?3600:300}});
    if(!response.ok)return new Response("IPMA-Radarbild aktuell nicht verfügbar",{
      status:response.status===404?404:502,headers:securityHeaders({"Content-Type":"text/plain; charset=utf-8"})
    });
    const mime=response.headers.get("Content-Type")||"";
    if(!/^image\/(?:png|gif|jpeg|webp)/i.test(mime))return new Response("Unerwartetes IPMA-Radarformat",{
      status:502,headers:securityHeaders({"Content-Type":"text/plain; charset=utf-8"})
    });
    return new Response(response.body,{status:200,headers:securityHeaders({
      "Content-Type":mime,"Cache-Control":"private, max-age=180"
    })});
  }catch(_e){
    return new Response("IPMA-Bilddienst derzeit nicht erreichbar",{
      status:502,headers:securityHeaders({"Content-Type":"text/plain; charset=utf-8"})
    });
  }
}
export function azoresRadarLoginPage(){
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
 '<meta name="robots" content="noindex,nofollow,noarchive"><title>Azoren-Radar · Anmeldung</title>'+
 '<style>:root{color-scheme:dark;font-family:system-ui}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1829;color:#eef7fd}main{width:min(440px,calc(100% - 32px));box-sizing:border-box;background:#152c45;border:1px solid #456f90;border-radius:15px;padding:28px}small{color:#a6d7f3}p{color:#b6d1e3;line-height:1.6}label{display:block;margin:14px 0 7px}input,button{font:inherit;padding:12px;width:100%;box-sizing:border-box;border-radius:9px}input{background:#0c2135;border:1px solid #6289a8;color:#fff}button{margin-top:13px;background:#1985b7;color:white;border:0;font-weight:700;cursor:pointer}</style></head>'+
 '<body><main><small>CLIMATE DASHBOARD · PASSWORTGESCHÜTZT</small><h1>Radar Azoren · IPMA</h1>'+
 '<p>Amtliches IPMA-Radarkomposit in mm/h. Melde dich mit deinem bisherigen Radarlabor-Passwort an.</p>'+
 '<form action="/login" method="POST"><input type="hidden" name="next" value="/radarlabor/azoren">'+
 '<label for="pwd">Passwort</label><input id="pwd" name="password" type="password" autocomplete="current-password" required>'+
 '<button type="submit">Azoren-Radar öffnen</button></form></main></body></html>';
}
const CSS=[
":root{color-scheme:dark;background:#091929;color:#eff8ff;font-family:Inter,system-ui,sans-serif}",
"*{box-sizing:border-box}body{margin:0}a{color:#9ed8fa;text-decoration:none}a:hover{text-decoration:underline}",
"header{background:#102940;border-bottom:1px solid #365877;padding:14px clamp(10px,2vw,28px);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}",
"header small{display:block;color:#9dc9e3;font-size:11px;letter-spacing:.07em}header strong{font-size:21px}",
"nav{display:flex;flex-wrap:wrap;align-items:center;gap:13px}nav form{margin:0}",
"main{max-width:1600px;margin:auto;padding:20px clamp(8px,2vw,28px) 44px}",
"h1{font-size:clamp(24px,3vw,33px);margin:0 0 8px}h2{font-size:17px;margin:0 0 14px}",
".intro,.note{font-size:13px;color:#bad2e3;line-height:1.65;max-width:1070px}",
".layout{display:grid;grid-template-columns:minmax(0,1fr) 304px;gap:14px;margin:16px 0}",
".card{background:#152d44;border:1px solid #3b6280;border-radius:13px;padding:15px;min-width:0}",
".row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin:11px 0}",
".row input[type=range]{flex:1;min-width:140px;accent-color:#7ed0fb}",
"button,select{font:inherit;color:#f3f8fd;background:#244b69;border:1px solid #547e9c;border-radius:8px;padding:9px 12px;cursor:pointer}",
"button:hover:not(:disabled){background:#35617f}button:disabled{opacity:.48;cursor:default}",
"button.primary{background:#147fae;font-weight:740}",
"button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #ffd275;outline-offset:2px}",
".map{position:relative;overflow:hidden;background:#d6e6ef;border:1px solid #60849c;border-radius:9px}",
".map canvas{display:block;width:100%;height:auto;aspect-ratio:1540/800}",
".stamp{position:absolute;left:10px;top:10px;background:#102a40e0;border-radius:7px;padding:8px 12px;color:white;font-size:12px;pointer-events:none}",
".tag{font-size:12px;background:#204962;border-radius:99px;border:1px solid #487189;padding:5px 9px}",
".side select{display:block;width:100%;max-width:100%;margin:7px 0 14px}.side label{font-size:13px;color:#daebf6}",
".legend img{max-width:100%;height:auto;display:block;border-radius:5px;background:#f0f5fa}",
".legend p{font-size:12px;color:#b4cbdf;line-height:1.55}",
".status{margin-top:13px;padding:11px;background:#214960;color:#d5ecfb;border-radius:7px;line-height:1.6;font-size:13px}",
".status.error{background:#532d36;color:#ffdad2}",
"@media(max-width:950px){.layout{grid-template-columns:1fr}}",
"@media(max-width:550px){main{padding:13px 8px 30px}.card{padding:10px}.stamp{font-size:10px;padding:6px}header{padding:11px}}"
].join("");
export function azoresRadarPage(){
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
 '<meta name="robots" content="noindex,nofollow,noarchive"><title>Azoren-Radarkomposit · IPMA · Privat</title><style>'+CSS+'</style></head><body>'+
 '<header><div><small>CLIMATE DASHBOARD · PRIVATES RADARLABOR</small><strong>Azoren · IPMA Radarkomposit</strong></div>'+
 '<nav><a href="/radarlabor">Deutschland</a><a href="/radarlabor/europa">Europa / Balearen</a>'+
 '<a href="/radarlabor/kanaren">Kanaren</a><form action="/logout" method="POST"><button>Abmelden</button></form></nav></header>'+
 '<main><h1>Radar der Azoren</h1><p class="intro">Amtliches IPMA-Radarkomposit der Niederschlagsintensität (mm/h), als georeferenziertes Original-Overlay dargestellt. Zeitraffer und drei Inselgruppen-Ausschnitte. Die verfügbare Geschichte und der Zeitabstand richten sich nach dem IPMA-Datenangebot; fehlende Messungen werden nicht künstlich ergänzt.</p>'+
 '<div class="layout"><section class="card"><div class="row"><strong id="product">IPMA · Datenstand wird geprüft</strong><span class="tag" id="time">–</span></div>'+
 '<div class="map"><canvas id="radar" width="1540" height="800" role="img" aria-label="IPMA-Niederschlagsradar Azoren mit hochauflösenden Inselumrissen"></canvas>'+
 '<span class="stamp" id="stamp">Prüfe Radarzeitpunkte …</span></div>'+
 '<div class="row"><button id="prev" disabled aria-label="Vorheriger Radarzeitpunkt">◀</button>'+
 '<button id="play" class="primary" disabled>▶ Animation</button>'+
 '<button id="next" disabled aria-label="Nächster Radarzeitpunkt">▶</button>'+
 '<input id="timeline" type="range" min="0" max="0" value="0" disabled aria-label="IPMA-Radarzeit wählen"></div>'+
 '<div class="row"><label>Tempo <select id="speed"><option value=".5">0,5 ×</option><option value="1" selected>1 ×</option><option value="2">2 ×</option><option value="4">4 ×</option></select></label>'+
 '<button id="refresh">↻ Daten neu laden</button><button id="png" disabled>PNG exportieren</button></div>'+
 '<div id="status" role="status" aria-live="polite" class="status">Prüfe IPMA-Radarmessungen …</div></section>'+
 '<aside class="card side"><h2>Ansicht</h2><label for="region">Kartenausschnitt</label><select id="region">'+
 '<option value="all">Azoren gesamt</option><option value="west">West · Flores / Corvo</option>'+
 '<option value="center">Mitte · Faial / Pico / Terceira</option>'+
 '<option value="east">Ost · São Miguel / Santa Maria</option></select>'+
 '<label for="showRadar">Radar-Overlay</label><select id="showRadar"><option value="on">Einblenden</option>'+
 '<option value="off">Nur Karte</option></select>'+
 '<h2>Feste IPMA-Farbskala</h2><div class="legend"><img id="legend" src="/radarlabor/api/azoren/legend.png" alt="Originale IPMA-Niederschlagsintensitäts-Legende in mm/h">'+
 '<p>Originalfarbskala des IPMA, unverändert für alle Zeitpunkte. Die Radarbilder sind keine Stationsmessungen und keine Niederschlagssummen.</p></div>'+
 '<p class="note">IPMA veröffentlicht nur einen begrenzten Rückblick, üblicherweise die letzten drei Stunden. Die Zeitangaben sind UTC.</p>'+
 '<p class="note">Außerhalb der Radarreichweite und bei Abschattung ist fehlendes Echo kein Nachweis für trockenes Wetter. Bei sicherheitsrelevanten Fragen bitte amtliche Warnungen prüfen.</p>'+
 '<p class="note">Quelle: © Instituto Português do Mar e da Atmosfera (IPMA). <a href="https://www.ipma.pt/pt/otempo/obs.remote/index-az.jsp" target="_blank" rel="noopener noreferrer">Original-Karte bei IPMA</a>. Umrisse: Natural Earth 1:10m. Die Bilder werden über einen kurzlebigen Proxy abgerufen, nicht dauerhaft im GitHub-Repository gespeichert.</p></aside></div></main>'+
 '<script>'+AZORES_RADAR_CLIENT_SOURCE+'</script></body></html>';
}
