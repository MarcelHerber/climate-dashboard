import {europeTmaxPage} from "./europe-tmax.js";
import {europeTminPage} from "./europe-tmin.js";

export function germanyTemperaturePage(kind){
 let html=kind==="tmin"?europeTminPage():europeTmaxPage();
 const window=kind==="tmin"?"18–06 UTC":"06–18 UTC";
 html=html.replace(/const MAIN=\{[^\n]+\};\nconst INSETS=\[[\s\S]*?\n\];/, 
 `const REGIONS={Deutschland:[5,16.5,47,56],Nord:[6,15,51.5,55.5],West:[5,10.5,48.5,53.5],Ost:[10,16,50,55],Süd:[7,14,47,50.5],NI:[6.5,12,51,54],NRW:[5.5,9.7,50.2,52.6],RP:[6,8.7,48.8,51.1],BW:[7.4,10.6,47.4,49.9]};
 function regionGeometry(name){const [west,east,south,north]=REGIONS[name]||REGIONS.Deutschland;const ratio=(east-west)*Math.cos((north+south)/2*Math.PI/180)/(north-south);const w=Math.min(1670,835*ratio),h=w/ratio;return {west,east,south,north,x:(1920-w)/2,y:108+(835-h)/2,w,h};}
 let MAIN=regionGeometry("Deutschland");const INSETS=[];`);
 html=html.replaceAll('const PREFIX="/wolkenlabor/data/europa-'+kind+'/";','const PREFIX="/wolkenlabor/data/deutschland-'+kind+'/";')
  .replaceAll("climate-europa-"+kind+"-editor-v1","climate-deutschland-"+kind+"-editor-v1")
  .replaceAll("data.days.length!==5","(data.days.length<1||data.days.length>2)")
  .replaceAll("d.stations?.length===31","d.stations?.length>=15")
  .replaceAll("catalog.stations.length<1000","catalog.stations.length<100")
  .replaceAll("s."+(kind==="tmin"?"tn":"tx")+".length===5","s."+(kind==="tmin"?"tn":"tx")+".length===data.days.length")
  .replaceAll("Europa ·","Deutschland ·").replaceAll("Europa_"+(kind==="tmin"?"Tmin":"Tmax"),"Deutschland_"+(kind==="tmin"?"Tmin":"Tmax"))
  .replaceAll("Europa "+(kind==="tmin"?"Tmin":"Tmax"),"Deutschland "+(kind==="tmin"?"Tmin":"Tmax"))
  .replaceAll("Europakarte","Deutschlandkarte").replaceAll("Europa- oder Inselkarte","Deutschlandkarte")
  .replaceAll("ICON-EU","ICON-D2").replaceAll(" · Inselkästchen: MOS","")
  .replaceAll(/Fünf (?:tägliche Prognosen|Nachtprognosen)[^.]*\./g,"Nur vollständige 12-Stunden-Prognosefenster im verfügbaren ICON-D2-Lauf.")
  .replaceAll(/sechs­stündige Temperatur(?:maximum|minimum)felder mit Ende [^.]*\./g,"lückenlos passende Extremwertintervalle laut GRIB-Metadaten.")
  .replaceAll("0,125°","0,025°")
  .replaceAll("Inselwerte für Azoren und Kanaren stehen in eigenen geografischen Ausschnitten, ohne ICON-D2-Fläche. ","")
  .replaceAll("100 km","35 km");
 html=html.replace('<div class="tmax-options">','<div class="tmax-options"><label>Ausschnitt <select id="germanyRegion">'+["Deutschland","Nord","West","Ost","Süd","NI","NRW","RP","BW"].map(x=>'<option>'+x+'</option>').join("")+'</select></label><label><input id="germanyBorders" type="checkbox" checked> Bundeslandgrenzen</label>');
 html=html.replace('const GEO="/wolkenlabor/data/geo.json";','const GEO="/wolkenlabor/data/deutschland-'+kind+'/geo.json";');
 html=html.replace("for(const country of state.geo.countries){","for(const country of [...state.geo.countries,...($('germanyBorders').checked?(state.geo.states||[]):[])]){");
 html=html.replace('initEditor();setButtons();render();void load();',`$("germanyRegion").addEventListener("change",e=>{MAIN=regionGeometry(e.target.value);render();});
 $("germanyBorders").addEventListener("change",render);
 initEditor();setButtons();render();void load();`);
 html=html.replace('<a href="/wolkenlabor/europa-tmin">Tmin</a>','<a href="/wolkenlabor/europa-tmin">Europa Tmin</a><a href="/wolkenlabor/deutschland-tmax">Deutschland Tmax</a><a href="/wolkenlabor/deutschland-tmin">Deutschland Tmin</a>');
 return html;
}
