(function () {
  "use strict";
  const URL = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/icon-hazards-data/data/icon-hazards/current.json";
  const $ = id => document.getElementById(id);
  const TYPES = {
    wind: {name:"Wind / Sturm",color:"#8137bc",pattern:"slash"},
    rain: {name:"Stark- / Dauerregen",color:"#087e97",pattern:"dots"},
    snow: {name:"Schneefall",color:"#2278d7",pattern:"cross"},
    heat: {name:"Hitze",color:"#c85c10",pattern:"horizontal"},
    cold: {name:"Kälte",color:"#2454b7",pattern:"vertical"},
    fog: {name:"Nebel / Sicht (nur Gelb)",color:"#677782",pattern:"dash"}
  };
  const SEVERITY = ["Keine Schwelle","#ead44b","#f6a244","#de434c","#9a49b4"];
  const NAMES = ["Keine","Gelb","Orange","Rot","Violett"];
  // Fixed map viewport and static, low-contrast Natural Earth outlines.
  // No external street-map tiles, labels, pan or zoom.
  const map = L.map("hazardMap", {
    center:[51,13], zoom:4, minZoom:0, maxZoom:10, zoomSnap:0,
    preferCanvas:true,
    zoomControl:false, attributionControl:false, dragging:false,
    scrollWheelZoom:false, doubleClickZoom:false, touchZoom:false,
    boxZoom:false, keyboard:false, tap:false, worldCopyJump:false
  });
  // Initial view is temporary; the geographic coverage from ICON metadata
  // defines the real fixed viewport as soon as data have loaded.
  map.createPane("hazardLand");
  map.getPane("hazardLand").style.zIndex="210";
  map.getPane("hazardLand").style.pointerEvents="none";
  map.createPane("hazardBorders");
  map.getPane("hazardBorders").style.zIndex="450";
  map.getPane("hazardBorders").style.pointerEvents="none";
  const basemapIndex=-1;
  async function loadBorders() {
    // Keep an on-site 110m fallback, but prefer the significantly more
    // detailed 50m Natural Earth geometry for both land and national borders.
    for (const filename of ["wettergefahren_basemap_50m.json","wettergefahren_basemap.json"]) {
      try {
        const resp=await fetch(filename);
        if(!resp.ok)throw Error("HTTP "+resp.status);
        const geo=await resp.json();
        if(!Array.isArray(geo.countries)||geo.countries.length<50)
          throw Error("Länderpolygone nicht plausibel");
        return geo;
      } catch(err) {
        console.warn("Grenzdatei "+filename+" nicht ladbar:",err);
      }
    }
    throw Error("Keine lokale Grenzdatei verfügbar");
  }
  loadBorders().then(geo=>{
      if(!Array.isArray(geo.countries))throw Error("Keine Länderpolygone");
      for(const country of geo.countries){
        for(const polygon of country.p){
          const rings=polygon.map(ring=>ring.map(([lon,lat])=>[lat,lon]));
          if(!rings.length)continue;
          L.polygon(rings,{pane:"hazardLand",stroke:false,fill:true,
            fillColor:"#f8faf9",fillOpacity:1,interactive:false}).addTo(map);
          L.polygon(rings,{pane:"hazardBorders",stroke:true,color:"#8297a8",
            weight:1.05,opacity:0.95,fill:false,interactive:false}).addTo(map);
        }
      }
    })
    .catch(err=>{
      const msg=$("basemapStatus");
      if(msg){msg.hidden=false;msg.textContent="Ländergrenzen konnten nicht geladen werden ("+err.message+").";}
    });
  let data=null, decoded=null, currentPeriod=0, currentDuration=12,
    currentType="all", overlay;
  const cache=Object.create(null);
  let loadGeneration=0, selectionGeneration=0;
  function status(text, type) {
    const el=$("status");
    el.textContent=text;
    el.className="status"+(type ? " "+type : "");
  }
  function formatUTC(value) {
    const d=new Date(value);
    if(Number.isNaN(d.getTime()))return "–";
    return new Intl.DateTimeFormat("de-DE",{
      timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"
    }).format(d)+" UTC";
  }
  function decodePeriod(index) {
    const period=data.periods[index], count=data.grid.rows*data.grid.cols;
    const layers={};
    Object.keys(TYPES).forEach(key=>{
      const encoded=period.layers[key];
      if(!encoded){layers[key]=null;return;}
      const bytes=atob(encoded);
      const packed=data.grid.encoding==="uint4-base64";
      const length=packed?Math.ceil(count/2):count;
      if(bytes.length!==length)throw Error("Rastergröße ungültig ("+key+")");
      const arr=new Uint8Array(count);
      for(let i=0;i<count;i++){
        const value=packed?(i&1?bytes.charCodeAt(i>>1)>>4:bytes.charCodeAt(i>>1)&15)
                          :bytes.charCodeAt(i);
        arr[i]=key==="fog"?(value>0?1:0):Math.min(value,4);
      }
      layers[key]=arr;
    });
    return layers;
  }

  function typesAt(index) {
    const keys=currentType==="all"?Object.keys(TYPES):[currentType];
    return keys.filter(key=>decoded && decoded[key] && decoded[key][index]>0)
      .map(key=>({key,level:decoded[key][index]}))
      .sort((a,b)=>b.level-a.level);
  }
  function paintGlyph(ctx,type,x,y,w,h) {
    if(w<5||h<5)return;
    ctx.save();
    ctx.beginPath();ctx.rect(x,y,w,h);ctx.clip();
    ctx.lineWidth=1.5;ctx.strokeStyle=TYPES[type].color;ctx.fillStyle=TYPES[type].color;
    const m=Math.min(w,h);
    const pat=TYPES[type].pattern;
    if(pat==="slash"){
      ctx.beginPath();
      for(let p=-h;p<w+h;p+=8){ctx.moveTo(x+p,y+h);ctx.lineTo(x+p+h,y);}
      ctx.stroke();
    } else if(pat==="dots"){
      for(let yy=y+3;yy<y+h;yy+=7)for(let xx=x+3;xx<x+w;xx+=7){
        ctx.beginPath();ctx.arc(xx,yy,1.25,0,2*Math.PI);ctx.fill();
      }
    } else if(pat==="cross"){
      ctx.beginPath();
      ctx.moveTo(x+w*.25,y+h*.25);ctx.lineTo(x+w*.75,y+h*.75);
      ctx.moveTo(x+w*.75,y+h*.25);ctx.lineTo(x+w*.25,y+h*.75);
      ctx.stroke();
    } else if(pat==="horizontal"){
      ctx.beginPath();
      for(let yy=y+3;yy<y+h;yy+=7){ctx.moveTo(x,yy);ctx.lineTo(x+w,yy);}
      ctx.stroke();
    } else if(pat==="vertical"){
      ctx.beginPath();
      for(let xx=x+3;xx<x+w;xx+=7){ctx.moveTo(xx,y);ctx.lineTo(xx,y+h);}
      ctx.stroke();
    } else if(pat==="dash"){
      ctx.setLineDash([3,2]);ctx.strokeRect(x+.8,y+.8,w-1.6,h-1.6);
    }
    ctx.restore();
  }
  const RiskCanvas=L.Layer.extend({
    onAdd:function(mapRef){
      this._map=mapRef;
      this._canvas=L.DomUtil.create("canvas","risk-canvas",mapRef.getPanes().overlayPane);
      this._canvas.style.position="absolute";
      this._canvas.style.pointerEvents="none";
      this._canvas.setAttribute("aria-hidden","true");
      mapRef.on("moveend zoomend resize",this.redraw,this);
      this.redraw();
    },
    onRemove:function(mapRef){
      mapRef.off("moveend zoomend resize",this.redraw,this);
      this._canvas.remove();
    },
    redraw:function(){
      if(!this._canvas)return;
      const size=this._map.getSize(), dpr=Math.min(window.devicePixelRatio||1,2);
      this._canvas.width=Math.round(size.x*dpr);
      this._canvas.height=Math.round(size.y*dpr);
      const top=this._map.containerPointToLayerPoint([0,0]);
      L.DomUtil.setPosition(this._canvas,top);
      this._canvas.style.width=size.x+"px";
      this._canvas.style.height=size.y+"px";
      const ctx=this._canvas.getContext("2d");
      ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.clearRect(0,0,size.x,size.y);
      if(!data||!decoded)return;
      const g=data.grid,b=this._map.getBounds();
      const startRow=Math.max(0,Math.floor((b.getSouth()-g.lat_min)/g.step)-1);
      const endRow=Math.min(g.rows-1,Math.ceil((b.getNorth()-g.lat_min)/g.step)+1);
      const startCol=Math.max(0,Math.floor((b.getWest()-g.lon_min)/g.step)-1);
      const endCol=Math.min(g.cols-1,Math.ceil((b.getEast()-g.lon_min)/g.step)+1);
      for(let r=startRow;r<=endRow;r++){
        for(let c=startCol;c<=endCol;c++){
          const risks=typesAt(r*g.cols+c);
          if(!risks.length)continue;
          const left=g.lon_min+c*g.step, bottom=g.lat_min+r*g.step;
          const tl=this._map.latLngToContainerPoint([bottom+g.step,left]);
          const br=this._map.latLngToContainerPoint([bottom,left+g.step]);
          const x=Math.floor(Math.min(tl.x,br.x)), y=Math.floor(Math.min(tl.y,br.y));
          const w=Math.max(1,Math.ceil(Math.abs(br.x-tl.x)));
          const h=Math.max(1,Math.ceil(Math.abs(br.y-tl.y)));
          const level=risks[0].level;
          // Einzelansicht: nur die meteorologische Gefahrenstufe als satte
          // Fläche. Keine Muster oder Zusatzsymbole, damit die Zonen klar sind.
          const single=currentType!=="all";
          ctx.globalAlpha=single ? (.60+.05*level) : (.28+.07*level);
          ctx.fillStyle=SEVERITY[level];
          ctx.fillRect(x,y,w+1,h+1);
          if(!single){
            ctx.globalAlpha=.85;
            // Nur die Gesamtkarte braucht Struktur zum Trennen der Gefahrenarten.
            risks.slice(0,2).forEach(risk=>paintGlyph(ctx,risk.key,x,y,w,h));
            if(risks.length>2 && w>12 && h>12){
              ctx.globalAlpha=.72;ctx.fillStyle="#192e45";
              ctx.fillRect(x+w-3,y+h-3,2,2);
            }
          }
        }
      }
      ctx.globalAlpha=1;
    }
  });
  overlay=new RiskCanvas().addTo(map);
  let fittedBounds=null;
  function gridCoverageBounds(doc) {
    const g=doc.grid;
    const fallback={south:g.lat_min, west:g.lon_min,
      north:g.lat_min+g.rows*g.step, east:g.lon_min+g.cols*g.step};
    const b=g.coverage_bounds || fallback;
    // Reject invalid/injected or older coverage metadata and fall back to the
    // complete known grid; never crop to currently coloured warnings.
    const valid=["south","west","north","east"].every(k=>Number.isFinite(b[k])) &&
      b.south>=fallback.south-1e-6 && b.north<=fallback.north+1e-6 &&
      b.west>=fallback.west-1e-6 && b.east<=fallback.east+1e-6 &&
      b.south<b.north && b.west<b.east;
    const region=valid?b:fallback;
    return L.latLngBounds([region.south,region.west],[region.north,region.east]);
  }
  function fitMapToCoverage() {
    if(!data)return;
    const bounds=gridCoverageBounds(data);
    // Match the map DIV to the bounding rectangle in Leaflet's Web Mercator
    // projection. Together with zoomSnap=0 this avoids wide side/top gutters.
    const nw=map.project(bounds.getNorthWest(),0);
    const se=map.project(bounds.getSouthEast(),0);
    const projectedWidth=Math.abs(se.x-nw.x);
    const projectedHeight=Math.abs(se.y-nw.y);
    if(!Number.isFinite(projectedWidth/projectedHeight)||projectedWidth<=0||projectedHeight<=0)return;
    const mapElement=$("hazardMap");
    mapElement.style.aspectRatio=String(projectedWidth/projectedHeight);
    fittedBounds=bounds;
    map.invalidateSize({animate:false,pan:false});
    map.fitBounds(bounds,{padding:[0,0],animate:false});
  }
  if(typeof ResizeObserver!=="undefined"){
    const resizeObserver=new ResizeObserver(()=>{
      if(!fittedBounds)return;
      map.invalidateSize({animate:false,pan:false});
      map.fitBounds(fittedBounds,{padding:[0,0],animate:false});
    });
    resizeObserver.observe($("hazardMap"));
  }else{
    window.addEventListener("resize",()=>{
      if(!fittedBounds)return;
      map.invalidateSize({animate:false,pan:false});
      map.fitBounds(fittedBounds,{padding:[0,0],animate:false});
    });
  }
  function summary() {
    const layers=Object.keys(TYPES);
    const p=data.periods[currentPeriod];
    const stat=layers.map(key=>{
      const arr=decoded[key];if(!arr)return null;
      let max=0, cells=0;
      for(let i=0;i<arr.length;i++){if(arr[i])cells++;if(arr[i]>max)max=arr[i];}
      return {key,max,cells};
    }).filter(Boolean);
    const displayed=currentType==="all"?stat:stat.filter(s=>s.key===currentType);
    $("metrics").replaceChildren();
    displayed.forEach(s=>{
      const box=document.createElement("div");box.className="metric";
      const strong=document.createElement("strong");strong.textContent=NAMES[s.max];
      strong.style.color=s.max>=3?"#b73543":"#263e55";
      const small=document.createElement("span");
      small.textContent=TYPES[s.key].name+" · "+s.cells.toLocaleString("de-DE")+" Rasterfelder";
      box.append(strong,small);$("metrics").append(box);
    });
    if(!displayed.length){
      const msg=document.createElement("span");
      msg.textContent="Für diese Kategorie liegen noch keine berechneten Kartendaten vor.";
      $("metrics").append(msg);
    }
    const available=Object.entries(p.samples).filter(([key,count])=>count>0).map(([key])=>TYPES[key].name);
    $("availability").textContent="Berechnet: "+(available.join(", ")||"keine")+
      ". Fehlende Parameter bleiben transparent.";
    const counts=p.rain_intervals_available || {};
    const availableIntervals=[1,3,6,24]
      .filter(d=>d<=currentDuration && Number(counts[String(d)])>0)
      .map(d=>d+" h: "+counts[String(d)]+" Intervalle");
    $("rainCoverage").textContent="Niederschlagsprüfung: "+(availableIntervals.join(" · ")||
      "keine vollständig verfügbaren Intervalle")+
      (Number(counts["1"]||0)===0?
      " · Hinweis: Keine 1-h-Werte, kleinräumige Starkregenspitzen können fehlen.":"");
  }
  function absoluteUTC(hour) {
    const date=new Date(new Date(data.run_utc).getTime()+hour*3600000);
    return new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",
      month:"2-digit",hour:"2-digit",minute:"2-digit"}).format(date);
  }
  function updatePeriodButtons() {
    const holder=$("periodButtons");
    holder.replaceChildren();
    data.periods.forEach((period,i)=>{
      const button=document.createElement("button");
      button.type="button";
      button.dataset.index=String(i);
      button.textContent=absoluteUTC(period.start_h)+" – "+absoluteUTC(period.end_h);
      button.title="+"+period.start_h+" bis +"+period.end_h+" h · UTC";
      button.setAttribute("aria-pressed",String(i===currentPeriod));
      button.addEventListener("click",()=>{
        currentPeriod=i;
        render();
      });
      holder.append(button);
    });
    const selected=holder.querySelector('[aria-pressed="true"]');
    if(selected)holder.scrollLeft=Math.max(0,selected.offsetLeft-holder.offsetLeft-20);
  }
  function render() {
    if(!data)return;
    decoded=decodePeriod(currentPeriod);
    const p=data.periods[currentPeriod];
    document.querySelectorAll(".durations button").forEach(el=>{
      const duration=Number(el.dataset.duration);
      el.setAttribute("aria-pressed",String(duration===currentDuration));
      el.disabled=data.schema===1 && duration!==24;
      el.title=el.disabled?"Neuer ICON-EU-Datensatz noch nicht verfügbar":"";
    });
    $("periodLabel").textContent=absoluteUTC(p.start_h)+" – "+
      absoluteUTC(p.end_h)+" UTC · +"+p.start_h+" bis +"+p.end_h+" h";
    $("type").value=currentType;
    const isOverview=currentType==="all";
    $("hazardPatternLegend").hidden=!isOverview;
    $("legendExplanation").textContent=isOverview
      ? "Bei mehreren Gefahren wird die höchste Stufe eingefärbt. Die Muster helfen, unterschiedliche Gefahrenarten zu erkennen. Fehlende Felder bleiben transparent. Die Karte enthält keine Straßen oder Ortslabels."
      : "Die Einzeldarstellung zeigt ausschließlich die Gefahrenstufe als farbige Fläche – ohne Muster. Die Farben sind für bessere Lesbarkeit kräftiger. Fehlende Felder bleiben transparent.";
    $("mapTips").textContent=isOverview
      ? "In die feste Europakarte klicken, um alle verfügbaren Gefahrenstufen am Rasterpunkt anzuzeigen. Die Flächenfarbe steht für die höchste Stufe, die Muster für die Gefahrenart. Bei Überlagerungen sind maximal zwei Muster sichtbar; per Klick werden alle berechneten Gefahren angezeigt."
      : "In die Karte klicken, um die berechneten Gefahrenstufen am Rasterpunkt anzuzeigen. In dieser Einzelansicht werden nur die Gefahrenstufen farbig dargestellt, ohne zusätzliche Schraffuren oder Muster.";
    updatePeriodButtons();
    summary();
    fitMapToCoverage();
    overlay.redraw();
  }
  async function selectDuration(duration) {
    if(!data || duration===currentDuration)return;
    if(data.schema===1){
      status("6-/12-h-Daten stehen erst nach dem nächsten neuen Modelllauf zur Verfügung.","warn");
      return;
    }
    const generation=loadGeneration, selection=++selectionGeneration;
    try {
      status("ICON-EU "+duration+"-Stunden-Karten werden geladen …");
      if(!cache[duration]){
        const path=duration===24?"current.json":"current_"+duration+"h.json";
        const url=URL.replace(/current\.json$/,path);
        const response=await fetch(url+"?t="+Date.now(),{cache:"no-store"});
        if(!response.ok)throw Error("HTTP "+response.status);
        const incoming=await response.json();
        validate(incoming,duration);
        if(incoming.run_utc!==data.run_utc)
          throw Error("Die Zeitfenster stammen nicht aus demselben Modelllauf");
        cache[duration]=incoming;
      }
      if(generation!==loadGeneration||selection!==selectionGeneration)return;
      data=cache[duration];currentDuration=duration;currentPeriod=0;
      render();
      status(duration+"-h-Karten geladen · 0,25° Auswerteraster, keine amtliche Warnung.");
    }catch(error){
      if(generation!==loadGeneration||selection!==selectionGeneration)return;
      status(duration+"-h-Karten sind noch nicht verfügbar ("+error.message+
        "). Bisherige Ansicht bleibt erhalten.","warn");
    }
  }
  document.querySelectorAll(".durations button").forEach(button=>{
    button.addEventListener("click",()=>selectDuration(Number(button.dataset.duration)));
  });
  $("type").addEventListener("change",event=>{
    currentType=event.target.value;render();
  });
  $("refresh").addEventListener("click",load);
  map.on("click",event=>{
    if(!data)return;
    const g=data.grid;
    const r=Math.floor((event.latlng.lat-g.lat_min)/g.step);
    const c=Math.floor((event.latlng.lng-g.lon_min)/g.step);
    if(r<0||c<0||r>=g.rows||c>=g.cols)return;
    const idx=r*g.cols+c, rows=Object.keys(TYPES).filter(key=>decoded[key])
      .map(key=>({key,level:decoded[key][idx]})).sort((a,b)=>b.level-a.level);
    const wrapper=document.createElement("div");
    const heading=document.createElement("div");heading.className="popup-title";
    heading.textContent="ICON-EU · "+event.latlng.lat.toFixed(2)+"°N, "+event.latlng.lng.toFixed(2)+"°E";
    wrapper.append(heading);
    rows.forEach(item=>{
      const row=document.createElement("div");row.className="popup-row";
      const label=document.createElement("span");label.textContent=TYPES[item.key].name;
      const val=document.createElement("span");val.className="popup-risk";val.textContent=NAMES[item.level];
      val.style.color=item.level>=3?"#c4364b":"#364c63";
      row.append(label,val);wrapper.append(row);
    });
    const tip=document.createElement("p");tip.className="note";
    tip.textContent="Rasterwerte: maximale Gefahrenstufe innerhalb des gewählten "+currentDuration+"-h-Fensters. Keine amtliche Warnung.";
    wrapper.append(tip);
    L.popup({maxWidth:320}).setLatLng(event.latlng).setContent(wrapper).openOn(map);
  });
  function validate(doc,duration) {
    if(![1,2].includes(doc.schema) || !doc.grid ||
       !Array.isArray(doc.periods) || doc.not_official_warning!==true)
      throw Error("Dateiformat nicht plausibel");
    if(doc.schema===2 && (doc.duration_h!==duration ||
       doc.grid.step!==0.25 || doc.grid.encoding!=="uint4-base64"))
      throw Error("Auflösung oder Intervall weicht vom Datenformat ab");
    if(doc.schema===1 && duration!==24)throw Error("Veraltetes 24-h-Datenformat");
    const count=120/duration;
    if(doc.periods.length!==count)throw Error("Anzahl der Prognosefenster stimmt nicht");
    doc.periods.forEach((p,i)=>{
      if(p.start_h!==i*duration||p.end_h!==(i+1)*duration)
        throw Error("Ungültige Vorhersagezeiten");
    });
  }
  async function load() {
    const generation=++loadGeneration;
    ++selectionGeneration;
    status("Aktuelle ICON-EU-Gefahrenkarten werden abgerufen …");
    try {
      const response=await fetch(URL+"?t="+Date.now(),{cache:"no-store"});
      if(!response.ok)throw Error("HTTP "+response.status);
      const mainData=await response.json();
      validate(mainData,24);
      if(generation!==loadGeneration)return;
      for(const key of Object.keys(cache))delete cache[key];
      cache[24]=mainData;
      let selected=mainData,duration=24;
      if(mainData.schema===2){
        try{
          const r=await fetch(URL.replace(/current\.json$/,"current_12h.json")+
            "?t="+Date.now(),{cache:"no-store"});
          if(!r.ok)throw Error("HTTP "+r.status);
          const proposed=await r.json();
          validate(proposed,12);
          if(proposed.run_utc!==mainData.run_utc)
            throw Error("Läufe sind zeitlich unterschiedlich");
          selected=proposed;duration=12;cache[12]=proposed;
        }catch(e){
          console.warn("12-h-Karten noch nicht bereit:",e);
        }
      }
      if(generation!==loadGeneration)return;
      data=selected;currentDuration=duration;currentPeriod=0;
      $("runTime").textContent="ICON-EU-Lauf: "+formatUTC(data.run_utc)+
        " · Berechnung: "+formatUTC(data.generated_utc)+
        " · Auswerteraster: "+data.grid.step+"°";
      const age=(Date.now()-new Date(data.run_utc).getTime())/3600000;
      if(!Number.isFinite(age)||age>18)
        status("Achtung: Modelllauf älter als 18 Stunden. Wetterprognose möglicherweise veraltet.","warn");
      else if(data.schema===1)
        status("Noch 24-h-Altdaten · neue 6/12-h-Karten folgen mit dem nächsten vollständigen Datenlauf.","warn");
      else
        status("Gefahrenindikatoren geladen · "+duration+"-h-Zeiträume · keine amtliche Warnung.");
      render();
    }catch(error){
      if(generation!==loadGeneration)return;
      data=null;decoded=null;overlay.redraw();
      $("metrics").textContent="Noch keine berechneten Gefahrenkarten vorhanden.";
      status("Der ICON-EU-Datensatz konnte nicht geladen werden ("+error.message+
        "). Keine simulierten Daten werden angezeigt.","error");
    }
  }
  // Read-only snapshot bridge for the dedicated PNG export module.
  window.iconEuHazardExportState = () => ({
    map, data, decoded, currentPeriod, currentDuration, currentType, TYPES, SEVERITY, NAMES,
    coverageBounds: fittedBounds,
    basemapIndex, paintGlyph
  });
  load();
})();
