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
  const map = L.map("hazardMap", {center:[49.8,12.1],zoom:4,minZoom:3,maxZoom:10,preferCanvas:true,worldCopyJump:false});
  // CARTO's formerly anonymous light_all tiles now return "API KEY REQUIRED".
  // Use a verified public OpenStreetMap basemap, switching to Esri on tile errors.
  const basemaps = [
    {
      url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      opts: {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap-Mitwirkende</a> · ICON-EU: DWD',
        maxZoom: 19
      }
    },
    {
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
      opts: {
        attribution: 'Tiles &copy; Esri, HERE, Garmin, USGS, EPA, NPS · Modell: DWD ICON-EU',
        maxZoom: 19
      }
    }
  ];
  let basemapLayer = null;
  let basemapIndex = 0;
  function useBasemap(index) {
    if (basemapLayer) map.removeLayer(basemapLayer);
    basemapIndex = index;
    const provider = basemaps[index];
    let tileFailures = 0;
    let tileSuccesses = 0;
    const candidate = L.tileLayer(provider.url, Object.assign({
      keepBuffer: 3, updateWhenIdle: true, detectRetina: false
    }, provider.opts));
    basemapLayer = candidate;
    candidate.on("tileload", () => { tileSuccesses++; });
    candidate.on("tileerror", () => {
      tileFailures++;
      if (basemapLayer !== candidate || tileSuccesses > 0 || tileFailures < 3) return;
      if (basemapIndex + 1 < basemaps.length) {
        useBasemap(basemapIndex + 1);
      } else {
        const notice = $("basemapStatus");
        if (notice) {
          notice.hidden = false;
          notice.textContent = "Die Hintergrundkarte konnte nicht geladen werden. Bitte Netzwerkzugriff auf Kartenkacheln prüfen.";
        }
      }
    });
    candidate.addTo(map);
    const notice = $("basemapStatus");
    if (notice) notice.hidden = true;
  }
  useBasemap(0);
  let data=null, decoded=null, currentPeriod=0, currentType="all", overlay;
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
    Object.keys(TYPES).forEach(key => {
      const s=period.layers[key];
      if(!s){layers[key]=null;return;}
      const bytes=atob(s);
      if(bytes.length!==count)throw new Error("Rastergröße ungültig ("+key+")");
      const arr=new Uint8Array(count);
      // Clamp older data-branch forecasts too, without waiting for a new ICON run.
      for(let i=0;i<count;i++){
        const level=bytes.charCodeAt(i);
        arr[i]=key==="fog"?(level>0?1:0):level;
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
          ctx.globalAlpha=.28+.07*level;
          ctx.fillStyle=SEVERITY[level];
          ctx.fillRect(x,y,w+1,h+1);
          ctx.globalAlpha=.85;
          // At most two independent hazard patterns to avoid illegible overlaps.
          risks.slice(0,2).forEach(risk=>paintGlyph(ctx,risk.key,x,y,w,h));
          if(risks.length>2 && w>12 && h>12){
            ctx.globalAlpha=.72;ctx.fillStyle="#192e45";
            ctx.fillRect(x+w-3,y+h-3,2,2);
          }
        }
      }
      ctx.globalAlpha=1;
    }
  });
  overlay=new RiskCanvas().addTo(map);
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
    const hourly=p.rain_intervals_available && p.rain_intervals_available["1"];
    $("rainCoverage").textContent=hourly===0 ?
      "Hinweis: In diesem Zeitfenster stehen keine exakt einstündigen Niederschlagsintervalle zur Verfügung; lokale Starkregenspitzen können fehlen." :
      "Niederschlagsprüfung: "+hourly+" einstündige Intervalle sowie verfügbare 3-, 6- und 24-Stunden-Mengen.";
  }
  function render() {
    if(!data)return;
    decoded=decodePeriod(currentPeriod);
    const p=data.periods[currentPeriod];
    document.querySelectorAll(".periods button").forEach((el,i)=>{
      el.setAttribute("aria-pressed",String(i===currentPeriod));
    });
    const runMillis=new Date(data.run_utc).getTime();
    const utcLabel=new Intl.DateTimeFormat("de-DE",{
      timeZone:"UTC",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"
    });
    const validStart=utcLabel.format(new Date(runMillis+p.start_h*3600000));
    const validEnd=utcLabel.format(new Date(runMillis+p.end_h*3600000));
    $("periodLabel").textContent=validStart+" – "+validEnd+" UTC · +"+p.start_h+" bis +"+p.end_h+" h";
    $("type").value=currentType;
    summary();
    overlay.redraw();
  }
  document.querySelectorAll(".periods button").forEach(button=>{
    button.addEventListener("click",()=>{
      currentPeriod=Number(button.dataset.index);render();
    });
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
    tip.textContent="Rasterwerte: maximale Gefahrenstufe innerhalb des gewählten 24-h-Fensters. Keine amtliche Warnung.";
    wrapper.append(tip);
    L.popup({maxWidth:320}).setLatLng(event.latlng).setContent(wrapper).openOn(map);
  });
  async function load() {
    status("Aktuelle ICON-EU-Gefahrenkarten werden abgerufen …");
    try {
      const response=await fetch(URL+"?t="+Date.now(),{cache:"no-store"});
      if(!response.ok)throw new Error("HTTP "+response.status);
      const incoming=await response.json();
      if(incoming.schema!==1 || !incoming.grid ||
        !Array.isArray(incoming.periods) || incoming.periods.length!==5 ||
        incoming.not_official_warning!==true){
        throw new Error("Dateiformat nicht plausibel");
      }
      const expected=Array.from({length:5},(_,i)=>[i*24,(i+1)*24]);
      expected.forEach((range,i)=>{
        if(incoming.periods[i].start_h!==range[0]||incoming.periods[i].end_h!==range[1]){
          throw new Error("Zeitfenster weicht von der Spezifikation ab");
        }
      });
      data=incoming;
      $("runTime").textContent="ICON-EU-Lauf: "+formatUTC(data.run_utc)+
        " · Berechnung: "+formatUTC(data.generated_utc);
      const runAge=(Date.now()-new Date(data.run_utc).getTime())/3600000;
      if(!Number.isFinite(runAge)||runAge>18){
        status("Achtung: Der zuletzt verfügbare ICON-EU-Lauf ist älter als 18 Stunden. Daten sind möglicherweise veraltet.","warn");
      }else{
        status("Gefahrenindikatoren geladen. Mit dem Zeitraum und der Wetterart kannst du die Karte umschalten.");
      }
      render();
    } catch (error) {
      data=null;decoded=null;overlay.redraw();
      $("metrics").textContent="Noch keine berechneten Gefahrenkarten vorhanden.";
      status("Es liegen derzeit keine veröffentlichten ICON-EU-Gefahrenkarten vor ("+
        error.message+"). Keine simulierten Daten werden angezeigt.","error");
    }
  }
  // Read-only snapshot bridge for the dedicated PNG export module.
  window.iconEuHazardExportState = () => ({
    map, data, decoded, currentPeriod, currentType, TYPES, SEVERITY, NAMES,
    basemapIndex, paintGlyph
  });
  load();
})();
