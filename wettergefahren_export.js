(function () {
  "use strict";
  const button = document.getElementById("exportPng");
  const notice = document.getElementById("exportStatus");
  if (!button) return;

  const GEOGRAPHY_URL = "wettergefahren_basemap_50m.json";
  const WIDTH_LEGEND = 308;
  const PALETTE = {
    bg: "#eef3f8",
    ink: "#182b40",
    muted: "#586d80",
    ocean: "#e8f0f5",
    land: "#f8faf9",
    border: "#8297a8",
    coastline: "#8297a8"
  };
  const SOURCE = {
    osm: "Kartenbasis: © OpenStreetMap-Mitwirkende (ODbL)",
    esri: "Kartenbasis: Esri · HERE · Garmin · USGS · EPA · NPS"
  };
  let geographyPromise = null;

  function info(message, error = false) {
    if (!notice) return;
    notice.textContent = message;
    notice.className = "export-status" + (error ? " error" : "");
    notice.hidden = !message;
  }

  function text(ctx, str, x, y, font, color = PALETTE.ink) {
    ctx.font = font;
    ctx.fillStyle = color;
    ctx.fillText(String(str), x, y);
  }

  function roundRect(ctx, x, y, w, h, r, fill) {
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
    ctx.fill();
  }

  function utc(input) {
    const date = new Date(input);
    return new Intl.DateTimeFormat("de-DE", {
      day:"2-digit", month:"2-digit", year:"numeric",
      hour:"2-digit", minute:"2-digit", timeZone:"UTC"
    }).format(date) + " UTC";
  }

  function periodTime(run, hours) {
    return utc(new Date(new Date(run).getTime() + hours * 3600000));
  }

  async function geographicData() {
    if (!geographyPromise) {
      geographyPromise = (async () => {
        for (const file of [GEOGRAPHY_URL,"wettergefahren_basemap.json"]) {
          try {
            const res=await fetch(file);
            if(!res.ok)throw Error("HTTP "+res.status);
            const doc=await res.json();
            if(!Array.isArray(doc.countries)||doc.countries.length<50)
              throw Error("Ungültige Geografiedaten");
            return doc;
          } catch(error) {
            console.warn("PNG-Kartengrenzen: ",file,error);
          }
        }
        throw Error("Keine geografische Basiskarte verfügbar");
      })().catch(error=>{
        geographyPromise=null;
        throw error;
      });
    }
    return geographyPromise;
  }

  function drawVectorBackground(ctx, state, box, geography) {
    const {map} = state;
    const {x,y,w,h} = box;
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.fillStyle = PALETTE.ocean;
    ctx.fillRect(x, y, w, h);

    for (const country of geography.countries) {
      for (const polygon of country.p) {
        ctx.beginPath();
        for (const ring of polygon) {
          ring.forEach(([lon,lat],i) => {
            const pt = map.latLngToContainerPoint([lat,lon]);
            if (i===0)ctx.moveTo(x+pt.x,y+pt.y);
            else ctx.lineTo(x+pt.x,y+pt.y);
          });
          ctx.closePath();
        }
        ctx.fillStyle = PALETTE.land;
        ctx.fill("evenodd");
        ctx.strokeStyle = PALETTE.border;
        ctx.lineWidth = 0.7;
        ctx.stroke();
      }
    }

    ctx.restore();
  }

  function drawVectorBorders(ctx,state,box,geography) {
    const {map}=state;
    ctx.save();
    ctx.beginPath();ctx.rect(box.x,box.y,box.w,box.h);ctx.clip();
    ctx.strokeStyle=PALETTE.border;
    ctx.lineWidth=1.05;
    for(const country of geography.countries) {
      for(const polygon of country.p) {
        ctx.beginPath();
        for(const ring of polygon) {
          ring.forEach(([lon,lat],i)=>{
            const pt=map.latLngToContainerPoint([lat,lon]);
            if(i===0)ctx.moveTo(box.x+pt.x,box.y+pt.y);
            else ctx.lineTo(box.x+pt.x,box.y+pt.y);
          });
          ctx.closePath();
        }
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  function tileNodes(mapEl) {
    const mapBounds=mapEl.getBoundingClientRect();
    return Array.from(mapEl.querySelectorAll(".leaflet-tile-pane img.leaflet-tile-loaded"))
      .filter(img=>{
        const r=img.getBoundingClientRect();
        return !!img.currentSrc && img.naturalWidth > 0 &&
          r.right>mapBounds.left && r.left<mapBounds.right &&
          r.bottom>mapBounds.top && r.top<mapBounds.bottom &&
          r.width > 0 && r.height > 0;
      })
      .map(img=>({url:img.currentSrc,rect:img.getBoundingClientRect()}));
  }

  function crossOriginCopy(src, ms = 5500) {
    return new Promise((resolve,reject)=>{
      const image = new Image();
      let settled=false;
      const timeout = setTimeout(()=>finish(false),ms);
      function finish(ok) {
        if(settled)return;
        settled=true;clearTimeout(timeout);
        image.onload=null;image.onerror=null;
        if(ok&&image.naturalWidth)resolve(image);
        else reject(Error("Kartenkachel nicht für PNG freigegeben"));
      }
      image.crossOrigin="anonymous";
      image.onload=()=>finish(true);
      image.onerror=()=>finish(false);
      image.src=src;
      if(image.complete&&image.naturalWidth)finish(true);
    });
  }

  async function createTileSnapshot(mapEl, box) {
    const tiles=tileNodes(mapEl), rect=mapEl.getBoundingClientRect();
    if(tiles.length<2) return null;
    // Limit capture to tiles actually visible in the map. Never bulk-fetch regions.
    const loaded=await Promise.allSettled(tiles.map(tile=>crossOriginCopy(tile.url)));
    if(loaded.some(item=>item.status!=="fulfilled"))return null;
    const layer=document.createElement("canvas");
    layer.width=Math.ceil(box.w);
    layer.height=Math.ceil(box.h);
    const ctx=layer.getContext("2d");
    let painted=0;
    for(let i=0;i<tiles.length;i++){
      const tr=tiles[i].rect;
      const dx=tr.left-rect.left,dy=tr.top-rect.top;
      try {
        ctx.drawImage(loaded[i].value,dx,dy,tr.width,tr.height);
        painted++;
      } catch(error) { return null; }
    }
    // Security-check the tile canvas before it can replace the vector fallback.
    try {
      ctx.getImageData(Math.floor(box.w/2),Math.floor(box.h/2),1,1);
    } catch(error) { return null; }
    return painted>0 ? layer : null;
  }

  function drawRiskCanvas(ctx, mapEl, box) {
    const el=mapEl.querySelector("canvas.risk-canvas");
    if(!el || !el.width || !el.height)throw Error("Gefahrenraster ist nicht bereit");
    const viewport=mapEl.getBoundingClientRect();
    const bounds=el.getBoundingClientRect();
    ctx.save();
    ctx.beginPath();ctx.rect(box.x,box.y,box.w,box.h);ctx.clip();
    ctx.drawImage(el,box.x+bounds.left-viewport.left,box.y+bounds.top-viewport.top,
      bounds.width,bounds.height);
    ctx.restore();
  }

  function drawLegend(ctx, state, box) {
    const x=box.x + box.w + 23;
    const startY=box.y+4;
    const selected=state.currentType==="all"?"Gesamtübersicht":state.TYPES[state.currentType].name;
    text(ctx,"GEFAHRENSTUFEN",x,startY+24,"bold 14px Arial");
    for(let i=1;i<=4;i++){
      const top=startY+40+(i-1)*36;
      roundRect(ctx,x,top,28,20,4,state.SEVERITY[i]);
      text(ctx,state.NAMES[i],x+40,top+15,"14px Arial");
    }
    let top=startY+196;
    if(state.currentType==="all"){
      // Nur in der Gesamtübersicht werden unterschiedliche Wetterarten
      // als Schraffuren/Symbole ausgewiesen.
      top+=12;
      text(ctx,"WETTERARTEN",x,top,"bold 14px Arial");
      top+=16;
      for(const key of Object.keys(state.TYPES)){
        roundRect(ctx,x,top,31,25,4,"#ecf1f5");
        state.paintGlyph(ctx,key,x,top,31,25);
        text(ctx,state.TYPES[key].name,x+41,top+17,"12px Arial");
        top+=40;
      }
    }
    top+=14;
    ctx.strokeStyle="#e1e8ed";ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x+WIDTH_LEGEND-30,top);ctx.stroke();
    text(ctx,"KARTENAUSWAHL",x,top+28,"bold 12px Arial");
    text(ctx,selected,x,top+50,"12px Arial",PALETTE.muted);
    text(ctx,"Fenster: "+state.currentDuration+" h",x,top+82,"12px Arial",PALETTE.muted);
    text(ctx,"Auswerteraster: "+state.data.grid.step+"°",x,top+104,"12px Arial",PALETTE.muted);
  }

  async function renderExportCanvas() {
    const read=window.iconEuHazardExportState;
    if(typeof read!=="function")throw Error("Kartendaten noch nicht initialisiert");
    const state=read();
    if(!state?.data||!state.decoded)throw Error("Noch keine ICON-EU-Gefahrendaten geladen");
    const mapEl=document.getElementById("hazardMap");
    const size=state.map.getSize();
    const w=Math.round(size.x),h=Math.round(size.y);
    if(w<200||h<200)throw Error("Kartenausschnitt ist zu klein");
    const factor=2;
    const pad=28, top=142, bottom=92;
    const box={x:pad,y:top,w,h};
    const pageWidth=box.x+box.w+WIDTH_LEGEND+pad;
    const pageHeight=Math.max(top+h+bottom,880);
    const canvas=document.createElement("canvas");
    canvas.width=pageWidth*factor;canvas.height=pageHeight*factor;
    const ctx=canvas.getContext("2d",{alpha:false});
    if(!ctx)throw Error("PNG-Canvas nicht verfügbar");
    ctx.scale(factor,factor);

    ctx.fillStyle="#f8fafc";ctx.fillRect(0,0,pageWidth,pageHeight);
    ctx.fillStyle="#19344e";ctx.fillRect(0,0,pageWidth,99);
    text(ctx,"CLIMATE DASHBOARD DEUTSCHLAND",pad,30,"bold 12px Arial","#bdd2e2");
    text(ctx,"ICON-EU · Europa-Gefahrenmonitor",pad,64,"bold 27px Arial","#ffffff");
    const period=state.data.periods[state.currentPeriod];
    text(ctx,"Modelllauf "+utc(state.data.run_utc)+"  |  Zeitraum +"+period.start_h+" bis +"+period.end_h+" h",pad,123,
      "bold 14px Arial",PALETTE.ink);

    // Always prepare a local, CORS-independent geographic background first.
    let geography=null;
    try{geography=await geographicData();}
    catch(error){console.warn("Natural Earth PNG-Basiskarte:",error);}
    if(geography) drawVectorBackground(ctx,state,box,geography);
    else {
      ctx.fillStyle=PALETTE.ocean;
      ctx.fillRect(box.x,box.y,w,h);
    }

    if(!geography)throw Error("Feste Länderkarte nicht verfügbar");
    const provider="Natural Earth (Public Domain)";

    drawRiskCanvas(ctx,mapEl,box);
    drawVectorBorders(ctx,state,box,geography);
    ctx.strokeStyle="#a8b9c7";ctx.lineWidth=1;ctx.strokeRect(box.x+.5,box.y+.5,w-1,h-1);
    drawLegend(ctx,state,box);

    const footY=pageHeight-61;
    ctx.strokeStyle="#d9e4eb";ctx.beginPath();ctx.moveTo(pad,footY-15);
    ctx.lineTo(pageWidth-pad,footY-15);ctx.stroke();
    text(ctx,"Gültig: "+periodTime(state.data.run_utc,period.start_h)+" bis "+periodTime(state.data.run_utc,period.end_h),
      pad,footY+6,"12px Arial",PALETTE.ink);
    text(ctx,provider+"  ·  Modell: Deutscher Wetterdienst (DWD)",pad,footY+27,"11px Arial",PALETTE.muted);
    text(ctx,"Experimentelle Modellindikatoren · Keine amtlichen Wetterwarnungen",
      pad,footY+46,"bold 11px Arial","#9c3d33");

    const periodName=period.start_h+"-"+period.end_h+"h";
    const date=state.data.run_utc.slice(0,16).replace(/[T:]/g,"-");
    const type=state.currentType==="all"?"gesamt":state.currentType;
    const stem="ICON-EU_Gefahren_"+type+"_"+periodName+"_"+date+"UTC";
    return {canvas,stem};
  }

  async function makePNG(){
    const {canvas,stem}=await renderExportCanvas();
    const blob=await new Promise((resolve,reject)=>{
      canvas.toBlob(result=>result?resolve(result):reject(Error("PNG-Kodierung fehlgeschlagen")),"image/png");
    });
    const link=document.createElement("a");
    link.href=URL.createObjectURL(blob);
    link.download=stem+".png";
    document.body.append(link);
    link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(link.href),30000);
  }

  async function makePDF(){
    if(!window.jspdf?.jsPDF)throw Error("PDF-Bibliothek konnte nicht geladen werden");
    const {canvas,stem}=await renderExportCanvas();
    const pdf=new window.jspdf.jsPDF({orientation:"landscape",unit:"mm",format:"a4",compress:true});
    const w=pdf.internal.pageSize.getWidth(),h=pdf.internal.pageSize.getHeight();
    const margin=9;
    const ratio=Math.min((w-2*margin)/canvas.width,(h-2*margin)/canvas.height);
    const imgW=canvas.width*ratio,imgH=canvas.height*ratio;
    pdf.addImage(canvas.toDataURL("image/png"),"PNG",(w-imgW)/2,(h-imgH)/2,imgW,imgH,undefined,"FAST");
    pdf.save(stem+".pdf");
  }

  const pdfButton=document.getElementById("exportPdf");
  async function runExport(control,format){
    if(control.disabled)return;
    control.disabled=true;control.setAttribute("aria-busy","true");
    const previous=control.textContent;
    control.textContent=format==="pdf"?"PDF wird erstellt …":"PNG wird erstellt …";
    info("Exportiere die Gefahrenkarte mit geografischem Hintergrund …");
    try{
      if(format==="pdf")await makePDF();else await makePNG();
      info(format.toUpperCase()+" mit Modelllauf, Zeitraum, Legende und Gefahrenkarte erstellt.");
    }catch(error){
      console.error("ICON-EU Kartenexport:",error);
      info(format.toUpperCase()+"-Export fehlgeschlagen: "+error.message,true);
    }finally{
      control.disabled=false;control.removeAttribute("aria-busy");
      control.textContent=previous;
    }
  }
  button.addEventListener("click",()=>runExport(button,"png"));
  pdfButton?.addEventListener("click",()=>runExport(pdfButton,"pdf"));
})();