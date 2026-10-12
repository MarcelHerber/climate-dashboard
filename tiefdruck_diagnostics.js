/* Atlantic low diagnostics: Bergeron deepening, real 10-m wind quadrants,
 * and nearest available ECMWF tropical-track comparison.
 * No 925-hPa radius or IFS extratropical CPS is implied. */
(function(){
"use strict";
const $=id=>document.getElementById(id);
let map=null,leaflet=null,layer=null,chart=null,selected=null,all=null,forecastHour=0;
function fmt(n,d=1){return Number.isFinite(n)?n.toLocaleString("de-DE",{maximumFractionDigits:d,minimumFractionDigits:d}):"–";}
const radians=Math.PI/180;
function distance(a,b){
 const dphi=(a.lat-b.lat)*radians,dlambda=(a.lon-b.lon)*radians;
 const v=Math.sin(dphi/2)**2+Math.cos(a.lat*radians)*Math.cos(b.lat*radians)*Math.sin(dlambda/2)**2;
 return 12742*Math.asin(Math.sqrt(Math.min(1,Math.max(0,v))));
}
function offset(lat,lon,radiusKm,bearingDeg){
 const b=bearingDeg*radians,ang=radiusKm/6371,p=lat*radians,l=lon*radians;
 const next=Math.asin(Math.sin(p)*Math.cos(ang)+Math.cos(p)*Math.sin(ang)*Math.cos(b));
 const lon2=l+Math.atan2(Math.sin(b)*Math.sin(ang)*Math.cos(p),
      Math.cos(ang)-Math.sin(p)*Math.sin(next));
 return [next/radians,((lon2/radians+540)%360)-180];
}
function current(){
 return selected?.points?.filter(p=>p.h<=forecastHour).at(-1)||selected?.points?.[0]||null;
}
function renderWind(p){
 if(!layer)return;
 layer.clearLayers();
 if(!$("windOverlay").checked||!p?.wind_radii)return;
 const caps=[
   ["gale34","#21b7d0",0.19],
   ["storm48","#f59e0b",0.24],
   ["hurricane64","#df3464",0.3]
 ];
 for(const [kind,color,opacity] of caps){
   const quadrants=p.wind_radii.quadrants?.[kind]||{};
   // Compass (clockwise from true north); these are quadrant estimates,
   // not a smoothed GEFS confidence envelope.
   const bearings={NE:[0,90],SE:[90,180],SW:[180,270],NW:[270,360]};
   for(const [quarter,limits] of Object.entries(bearings)){
     const radius=Number(quadrants[quarter]||0);
     if(radius<1)continue;
     const coords=[[p.lat,p.lon]];
     for(let deg=limits[0];deg<=limits[1];deg+=7.5)
       coords.push(offset(p.lat,p.lon,radius,deg));
     coords.push([p.lat,p.lon]);
     leaflet.polygon(coords,{
       color,weight:1.1,fillColor:color,fillOpacity:opacity,interactive:false
     }).addTo(layer);
   }
 }
}
function trend(t){
 if(chart){chart.destroy();chart=null;}
 if(!t||t.model!=="gfs")return;
 const valid=t.points.filter(p=>p.cyclogenesis_24h);
 if(!valid.length)return;
 chart=new Chart($("advDeepeningChart"),{
   type:"line",
   data:{labels:valid.map(p=>"+"+p.h+" h"),
    datasets:[{
      label:"Bergeron-Faktor",
      data:valid.map(p=>p.cyclogenesis_24h.bergeron),
      pointRadius:4,borderColor:"#0c689e",backgroundColor:"#0c689e",spanGaps:false
     },{
      label:"Explosive Zyklogenese (1,0)",
      data:valid.map(()=>1),pointRadius:0,borderDash:[5,5],
      borderColor:"#bb293d",backgroundColor:"#bb293d",borderWidth:2
    }]},
   options:{responsive:true,maintainAspectRatio:false,animation:false,
    plugins:{legend:{position:"bottom"}},
    scales:{y:{title:{display:true,text:"Bergeron-Faktor"}},
      x:{title:{display:true,text:"GFS-Vorhersagezeit"}}}}
 });
}
function chooseModels(t,p){
 const root=$("advComparison");root.replaceChildren();
 if(!t||!p||!all){root.textContent="Bitte ein Tief wählen.";return;}
 const rows=[{model:"GFS-Nordatlantik",pressure:p.mslp_hpa,km:0,wind:p.vmax_ms,reason:"Referenz"}];
 const groups=[["ifs","ECMWF IFS"],["aifs","ECMWF AIFS"],["ens","ECMWF IFS ENS"]];
 for(const [id,name] of groups){
   let best=null;
   for(const candidate of all.tracks){
     if(candidate.model!==id)continue;
     // Compare same valid date, not same forecast lead.
     for(const pt of candidate.points){
       if(pt.time!==p.time||!Number.isFinite(pt.lat)||!Number.isFinite(pt.lon))continue;
       const km=distance(pt,p);
       if(km>550||best&&km>=best.km)continue;
       best={model:name,pressure:pt.mslp_hpa,km,wind:pt.vmax_ms,reason:"TC-BUFR"};
     }
   }
   rows.push(best||{model:name,pressure:null,km:null,wind:null,reason:"Kein passender TC-BUFR-Track"});
 }
 const table=document.createElement("table");table.className="model-table";
 const labels=["Modell / Datenprodukt","Zentraldruck","Abstand","10-m-Wind"];
 const thead=document.createElement("thead"),header=document.createElement("tr");
 labels.forEach(n=>{const th=document.createElement("th");th.textContent=n;header.append(th);});
 thead.append(header);table.append(thead);
 const tbody=document.createElement("tbody");
 for(const r of rows){
   const tr=document.createElement("tr");
   [r.model+(r.reason.startsWith("Kein")?" · nicht verfügbar":""),
    Number.isFinite(r.pressure)?fmt(r.pressure)+" hPa":"–",
    Number.isFinite(r.km)?fmt(r.km,0)+" km":"–",
    Number.isFinite(r.wind)?fmt(r.wind*3.6,0)+" km/h":"–"].forEach(x=>{
       const td=document.createElement("td");td.textContent=x;tr.append(td);
    });
   tbody.append(tr);
 }
 table.append(tbody);root.append(table);
}
function update(t,d,h){
 const changed=selected?.id!==t?.id;
 selected=t;all=d;forecastHour=h;
 const p=current();
 const rate=p?.cyclogenesis_24h;
 $("advPressure").textContent=rate?fmt(rate.pressure_drop_hpa_24h,1)+" hPa":"–";
 $("advBergeron").textContent=rate?fmt(rate.bergeron,2):"–";
 $("advBergeronDetail").textContent=rate?
   (rate.explosive?"Kriterium erfüllt · explosive Zyklogenese":
    "Kriterium nicht erfüllt")+" · Schwelle "+fmt(rate.reference_hpa_24h,1)+" hPa"
    :"Nur bei durchgängiger 24-h-Zugbahn berechenbar";
 const radii=p?.wind_radii?.quadrants||null;
 const biggest=kind=>radii?Math.max(...Object.values(radii[kind]||{})):null;
 $("advGale").textContent=biggest("gale34")===null?"–":fmt(biggest("gale34"),0)+" km";
 $("advStorm").textContent=biggest("storm48")===null?"–":fmt(biggest("storm48"),0)+" km";
 $("advWarning").textContent=!t?"Bitte ein GFS-Nordatlantik-Tief wählen."
   :t.model!=="gfs"?"Für ECMWF-Tropenzyklonen-Tracks sind hier keine 10-m-Flächen und kein 24-h-Bergeron-Diagnostikum vorhanden."
   :rate?.explosive?"Dieses GFS-Tief erreicht im ausgewählten 24-h-Intervall das breitenkorrigierte Bergeron-Kriterium."
   :"GFS-Modellwerte. Negative Druckfallwerte bedeuten Druckanstieg. Sektoren schätzen radiale Windschwellenausdehnungen.";
 renderWind(p);
 if(changed)trend(t);
 chooseModels(t,p);
}
function setMap(mapReference,leafletReference){
 map=mapReference;leaflet=leafletReference;
 if(!layer)layer=leaflet.layerGroup().addTo(map);
}
$("windOverlay").addEventListener("change",()=>renderWind(current()));
window.CycloneDiagnostics={update,setMap};
})();