import { LAB_CSS } from "./cloud-lab-style.js";
import { TMAX_JS } from "./europe-tmax-client.js";

// Served ONLY after verifying the same session cookie as /wolkenlabor.
// Never add this route to the public GitHub Pages navigation.
const STYLE = `
.tmax-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.tmax-head .pill{font-size:12px;color:#d7edfd}
.tmax-preview{max-width:1480px;margin:0 auto}
.tmax-stage{border:1px solid #45657e;border-radius:11px;overflow:hidden;background:#dfe8ed}
.tmax-stage canvas{display:block;width:100%;height:auto;aspect-ratio:16/9}
.tmax-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}
.tmax-toolbar button{min-width:80px}
.tmax-days{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.tmax-days button{font-size:12px;padding:9px 11px}
.tmax-days button[aria-pressed=true]{background:#daefff;color:#12324b;border-color:#c8e7fa;font-weight:850}
.tmax-options{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:13px 0}
.tmax-options label{display:flex;gap:6px;align-items:center;font-size:12px}
.tmax-options input[type=checkbox]{accent-color:#60b7fa;width:17px;height:17px}
.tmax-options select{color:#eff7ff;background:#162e46;border:1px solid #48627a;border-radius:8px;padding:6px}
.tmax-help{font-size:12px;line-height:1.7;color:#b9cee2}
.tmax-help strong{color:#f4f9ff}
.tmax-edit-panel{padding:15px;border-radius:12px;border:1px solid #49667f;background:#11293d;margin:13px 0}
.tmax-edit-panel[hidden]{display:none!important}
.tmax-edit-controls{display:flex;flex-wrap:wrap;align-items:center;gap:9px;margin-bottom:9px}
.tmax-edit-controls input{background:#071b2c;color:#eaf3fb;border:1px solid #54748c;border-radius:8px;padding:10px;max-width:310px;min-width:210px;font:inherit}
.tmax-edit-controls button[aria-pressed=true]{background:#daefff;color:#12324b;border-color:#bfe4ff}
.tmax-edit-panel p{font-size:12px;color:#b8ccdc;line-height:1.55}
.tmax-matches{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 11px}
.tmax-matches button{font-size:12px}
.tmax-station-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:5px 12px;max-height:210px;overflow:auto;padding:9px;border:1px solid #3b5a75;border-radius:7px}
.tmax-station-row{display:flex;align-items:center;gap:7px;font-size:12px;color:#e3edf6}
.tmax-station-row button{font-size:11px;padding:4px 7px;white-space:nowrap}
.tmax-station-row .station-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tmax-station-row input{accent-color:#68bfff}
.tmax-stage.editing canvas{cursor:crosshair;touch-action:none}
.tmax-edit-note{font-size:12px;padding:7px 0;color:#d5e9fb}

#tmaxStatus{margin-top:12px}
.tmax-card{max-width:1550px;margin:0 auto}
.tmax-card .tools{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
@media(max-width:700px){.tmax-days button{flex:1}.tmax-options{gap:10px}.tmax-head h1{font-size:23px}}
`;

export function europeTmaxPage() {
 return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
  '<meta name="robots" content="noindex,nofollow,noarchive"><title>Europa Tmax · MOS + ICON | Privates Wolkenlabor</title>'+
  '<style>'+LAB_CSS+STYLE+'</style></head><body>'+
  '<header><div><div class="sub">Climate Dashboard · geschütztes Wolkenlabor</div>'+
  '<strong>Wolkenfilm / Europa Tmax</strong> <span class="badge">Experimentell · privat</span></div>'+
  '<nav><a href="/wolkenlabor">← Wolkenfilm</a><a href="/">Alpenwetter</a>'+
  '<form method="POST" action="/logout"><button type="submit">Abmelden</button></form></nav></header>'+
  '<main><section class="card tmax-card">'+
  '<div class="tmax-head"><div><h1>Europäische Höchsttemperaturen</h1>'+
  '<p class="lead">Echte MOSMIX-L-Tageshöchstwerte über der ICON-EU-Temperaturfläche. '+ 
  'Fünf tägliche Prognosen, gleiche Bezugszeit 06–18 UTC. Keine simulierten Zahlen.</p></div>'+
  '<span class="pill">Nur im Passwortbereich</span></div>'+
  '<div class="tmax-toolbar"><button id="tmaxPrev" type="button" disabled aria-label="Vorheriger Tag">←</button>'+
  '<div class="tmax-days" id="tmaxDays" role="group" aria-label="Vorhersagetage"></div>'+
  '<button id="tmaxNext" type="button" disabled aria-label="Nächster Tag">→</button>'+
  '<button type="button" id="tmaxRefresh">↻ Daten prüfen</button>'+
  '<button class="main" id="tmaxSave" type="button" disabled>PNG · Full HD ↓</button></div>'+
  '<div class="tmax-options">'+
  '<label><input type="checkbox" id="tmaxField" checked> ICON-EU-Fläche</label>'+
  '<label><input type="checkbox" id="tmaxPoints" checked> MOS-Zahlen</label>'+
  '<label><input type="checkbox" id="tmaxNames" checked> Städtenamen</label>'+
  '<label for="tmaxDensity">Stationsdichte <select id="tmaxDensity">'+
  '<option value="sparse">Locker</option><option value="medium">Mittel</option>'+
  '<option value="dense" selected>Alle Vorlagenstädte</option></select></label>'+
  '<button type="button" id="tmaxEditorToggle" aria-expanded="false">✎ Karte bearbeiten</button></div>'+
  '<section class="tmax-edit-panel" id="tmaxEditor" hidden aria-label="Karteneditor">'+
  '<strong>Orte und Temperaturkästchen bearbeiten</strong>'+
  '<p>Ort/Station suchen und hinzufügen oder auf „Punkt setzen“ klicken und direkt auf der Karte markieren. Es werden ausschließlich reale MOSMIX-TX-Daten verwendet.</p>'+
  '<div class="tmax-edit-controls"><input type="search" id="tmaxFind" autocomplete="off" placeholder="Ort oder MOSMIX-Station suchen" aria-label="Stationsname suchen">'+
  '<input id="tmaxPinLabel" type="text" placeholder="Name für neuen Punkt (optional)" maxlength="35" aria-label="Eigener Name für Kartenpunkt">'+
  '<button id="tmaxAdd" type="button" disabled>+ Ort hinzufügen</button>'+
  '<button id="tmaxPin" type="button" aria-pressed="false">⌖ Punkt setzen</button>'+
  '<button id="tmaxMove" type="button" aria-pressed="false">↔ Kästchen verschieben</button>'+
  '<button id="tmaxReset" type="button">Standard wiederherstellen</button></div>'+
  '<div class="tmax-matches" id="tmaxMatches" aria-live="polite"></div>'+
  '<div class="tmax-edit-note" id="tmaxEditNote" role="status">Wähle einen Ort oder setze einen Punkt.</div>'+
  '<div class="tmax-station-list" id="tmaxStationList" aria-label="Temperaturkästchen ein- und ausblenden"></div>'+
  '<p>Beim Verschieben ändert sich ausschließlich die Position auf der Karte – der echte MOSMIX-Stationswert bleibt unverändert. Änderungen werden nur in diesem Browser gespeichert und nicht an GitHub übertragen.</p>'+
  '</section>'+
  '<div class="tmax-preview"><div class="tmax-stage" id="tmaxStage"><canvas id="tmaxCanvas" width="1920" height="1080" role="img" '+ 
  'aria-label="Experimentelle Europakarte mit echten MOSMIX-Höchsttemperaturen als Boxen über ICON-EU-Temperaturfläche"></canvas></div></div>'+
  '<div class="status" id="tmaxStatus" role="status" aria-live="polite">Warte auf verifizierte Daten …</div>'+
  '<p class="tmax-help"><strong>Meteorologischer Zeitraum:</strong> 06–18 UTC desselben Kalendertages.'+
  ' MOSMIX-TX ist das 12-Stunden-Maximum gültig 18 UTC; der ICON-EU-Hintergrund kombiniert echte'+
  ' sechs­stündige Temperaturmaximumfelder mit Ende 06, 12 und 18 UTC. '+ 
  ' Die ICON-EU-Ausgabe wird zur Kartendarstellung auf 0,125° umgerechnet – nicht als natives Modellgitter ausgewiesen.'+
  ' Inselwerte für Azoren und Kanaren stehen in eigenen geografischen Ausschnitten, ohne ICON-EU-Fläche. Städtewerte stammen jeweils von einer realen MOSMIX-Station höchstens 100 km entfernt;'+
  ' fehlen Modellfelder oder Stationen, wird nichts erfunden. Pfeiltasten links/rechts blättern durch die Tage.</p>'+
  '<p class="tmax-help"><strong>Quellen:</strong> Deutscher Wetterdienst (DWD), MOSMIX-L und ICON-EU Open Data. '+ 
  'Prognosewerte, keine Messungen. Vor Veröffentlichung redaktionell prüfen. Experimenteller Testbereich ohne öffentlichen Navigationslink.</p>'+
  '</section></main><script>'+TMAX_JS+'</script></body></html>';
}
