import {europeTmaxPage} from "./europe-tmax.js";
import {europeTminPage} from "./europe-tmin.js";

export function germanyTemperaturePage(kind){
 let html=kind==="tmin"?europeTminPage():europeTmaxPage();
 html=html.replace(/const MAIN=\{[^\n]+\};\nconst INSETS=\[[\s\S]*?\n\];/, 
 `const REGIONS={Deutschland:[5,16.5,47,56],Nord:[6,15,51.5,55.5],West:[5,10.5,48.5,53.5],Ost:[10,16,50,55],Süd:[7,14,47,50.5],NI:[6.5,12,51,54],NRW:[5.5,9.7,50.2,52.6],RP:[6,8.7,48.8,51.1],BW:[7.4,10.6,47.4,49.9],Bayern:[8.8,14.1,47,50.7],Berlin:[13,13.8,52.3,52.8],Brandenburg:[11.1,14.9,51.2,53.6],Bremen:[8.4,9,52.9,53.7],Hamburg:[9.6,10.4,53.3,54],Hessen:[7.6,10.3,49.3,51.8],MV:[10.4,14.5,53,54.9],Saarland:[6.2,7.5,49,49.7],Sachsen:[11.7,15.2,50,51.8],ST:[10.4,13.3,50.9,53.2],SH:[7.8,11.5,53.3,55.1],Thüringen:[9.6,12.8,50.1,51.8]};
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
 html=html.replace('<div class="tmax-options">','<div class="tmax-options"><label>Ausschnitt <select id="germanyRegion">'+Object.entries({Deutschland:"Deutschland",Nord:"Norddeutschland",West:"Westdeutschland",Ost:"Ostdeutschland",Süd:"Süddeutschland",NI:"Niedersachsen",NRW:"Nordrhein-Westfalen",RP:"Rheinland-Pfalz",BW:"Baden-Württemberg",Bayern:"Bayern",Berlin:"Berlin",Brandenburg:"Brandenburg",Bremen:"Bremen",Hamburg:"Hamburg",Hessen:"Hessen",MV:"Mecklenburg-Vorpommern",Saarland:"Saarland",Sachsen:"Sachsen",ST:"Sachsen-Anhalt",SH:"Schleswig-Holstein",Thüringen:"Thüringen"}).map(([v,x])=>'<option value="'+v+'">'+x+'</option>').join("")+'</select></label><label><input id="germanyBorders" type="checkbox" checked> Bundeslandgrenzen</label>');
 html=html.replace('const GEO="/wolkenlabor/data/geo.json";','const GEO="/wolkenlabor/data/deutschland-'+kind+'/geo.json";');
 html=html.replace("for(const country of state.geo.countries){","for(const country of [...state.geo.countries,...($('germanyBorders').checked?(state.geo.states||[]):[])]){");
 html=html.replace('PNG · Full HD ↓</button>','PNG · Full HD ↓</button><button id="germany4k" type="button">PNG · 4K ↓</button>');
 html=html.replace('initEditor();setButtons();render();void load();',`$("germanyRegion").addEventListener("change",e=>{MAIN=regionGeometry(e.target.value);render();});
 $("germanyBorders").addEventListener("change",render);
 $("germany4k").addEventListener("click",()=>{if(!state.data||!state.pictures.has(state.data.days[state.index].date))return;const date=state.data.days[state.index].date;try{canvas.width=3840;canvas.height=2160;ctx.setTransform(2,0,0,2,0,0);render();canvas.toBlob(blob=>{if(!blob)return;const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="Deutschland_ICON-D2_4K_"+date+".png";a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);},"image/png");}finally{canvas.width=1920;canvas.height=1080;render();}});
 initEditor();setButtons();render();void load();`);
 return html;
}
