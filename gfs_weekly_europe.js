/* NOAA GFS +3..+165 h: 28 verified native 0.5° TMP2m fields / 7 days.
   Independent of Haustein's 1981–2010 chart; homogeneous CFSR/CFSv2 1991–2020. */
(() => {
  "use strict";
  const W=1400,H=760,LON0=12;
  let GW=140,GH=76,CELL=GW*GH,NORTH=71.75,WEST=-24.75;
  let extended=false,vectorRings=[];
  const PI=Math.PI,RAD=PI/180;
  // Bounds are strictly inside the verified CFSR/CFSv2 f003 grid
  // (lon -24.75…44.75°, lat 34.25…71.75°); no invented data outside it.
  const REGIONS=Object.freeze({
    europe:{name:"Europa gesamt",west:-24.5,east:44.5,south:34.5,north:71.5},
    west:{name:"Westeuropa",west:-20,east:16,south:39,north:66},
    central:{name:"Mitteleuropa",west:-6,east:31,south:43.5,north:59},
    germany:{name:"Deutschland",west:4,east:17,south:46.5,north:56},
    nordics:{name:"Skandinavien",west:1,east:35,south:53,north:71.5},
    east:{name:"Osteuropa",west:16,east:44.5,south:43,north:70},
    med:{name:"Mittelmeerraum",west:-14,east:39,south:34.5,north:49},
    iberia:{name:"Iberische Halbinsel",west:-11,east:7,south:35,north:47},
    alps:{name:"Alpenraum",west:4,east:19,south:43.5,north:49.5},
    atlantic:{name:"Ostatlantik",west:-24.5,east:9,south:47,north:70}
  });
  const WIDE_REGIONS=Object.freeze({
    europe:{name:"Europa gesamt",west:-45,east:75,south:28,north:78},
    west:{name:"Westeuropa",west:-36,east:23,south:37,north:73},
    central:{name:"Mitteleuropa",west:-10,east:39,south:40,north:64},
    germany:{name:"Deutschland",west:4,east:17,south:46.5,north:56},
    nordics:{name:"Skandinavien",west:-18,east:43,south:52,north:79},
    east:{name:"Osteuropa",west:17,east:87,south:36,north:73},
    med:{name:"Mittelmeerraum",west:-27,east:57,south:26,north:51},
    iberia:{name:"Iberische Halbinsel",west:-15,east:10,south:33,north:48},
    alps:{name:"Alpenraum",west:4,east:20,south:43,north:50},
    atlantic:{name:"Nordatlantik",west:-79,east:20,south:36,north:82},
    greenland:{name:"Grönland",west:-78,east:-5,south:56,north:84},
    iceland:{name:"Island und Nordatlantik",west:-45,east:8,south:54,north:77},
    eurasia:{name:"Eurasien bis Ural",west:-23,east:97,south:34,north:78}
  });
  function currentRegion(){
    const regions=extended?WIDE_REGIONS:REGIONS;
    return regions[el.region.value]||regions.europe;
  }
  function configureRegions(){
    if(!extended)return;
    const selected=el.region.value;
    const options=Object.entries(WIDE_REGIONS).map(([id,region])=>
      '<option value="'+id+'">'+region.name+'</option>').join("");
    el.region.innerHTML=options;
    el.region.value=WIDE_REGIONS[selected]?selected:"europe";
  }

  // Match the established Climate Dashboard / ERA5 Europe anomaly palette.
  const STOPS=[-8,-7,-6,-5,-4,-3,-2,-1,-.5,0,.5,1,2,3,4,5,6,7,8];
  const COLORS=[
    "#3A006F","#51009E","#6B03C6","#5E4FFC","#187DFD",
    "#70B1FB","#C6E4FB","#DDEBF9","#EDF4FA","#FDFCFC",
    "#FDF0BC","#FDE47C","#FDBD3E","#FC691C","#F93A19",
    "#E51B75","#FC579B","#FC83B4","#FDAFCB"
  ];
  const $=id=>document.getElementById(id);
  const el={map:$("weekMap"),status:$("weekStatus"),run:$("weekRun"),
    info:$("weekReference"),metric:$("weekMetric"),projection:$("weekProjection"),region:$("weekRegion"),
    warn:$("weekWarning"),legend:$("weekLegend"),country:$("weekCountries"),
    countryTitle:$("weekCountryHeader"),selected:$("weekSelected"),
    label:$("weekMapLabel"),png:$("weekPng"),pdf:$("weekPdf"),csv:$("weekCsv")};
  if(!el.map)return;
  let payload=null,temperature=null,anomaly=null,mask=null,countries=[],border=null;
  let shown=null,stats=[],selected=null,mapInfo=null;
  function fmtTime(iso){
    return new Date(iso).toLocaleString("de-DE",{timeZone:"UTC",day:"2-digit",
      month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"})+" UTC";
  }
  function unpack(b64){
    const raw=atob(b64);
    if(raw.length!==CELL*2)throw Error("Ungültiger GFS-Rasterumfang");
    const buf=new ArrayBuffer(raw.length),view=new DataView(buf);
    for(let i=0;i<raw.length;i++)view.setUint8(i,raw.charCodeAt(i));
    const f=new Float32Array(CELL);
    for(let i=0;i<CELL;i++){
      const x=view.getInt16(i*2,true);
      f[i]=x===-32768?NaN:x/10;
    }
    return f;
  }
  function parseMask(b64){
    const raw=atob(b64);
    if(raw.length!==CELL*2)throw Error("Ländermaske hat falsche Rastergröße");
    const buf=new ArrayBuffer(raw.length),view=new DataView(buf);
    for(let i=0;i<raw.length;i++)view.setUint8(i,raw.charCodeAt(i));
    const ids=new Int16Array(CELL);
    for(let i=0;i<CELL;i++)ids[i]=view.getInt16(i*2,true);
    return ids;
  }
  function validate(main,cpc){
    const large=main.width===361&&main.height===121;
    const refVersion=large?"cfsr-cfsv2-t2m-f003-extended-v1":"cfsr-cfsv2-t2m-f003-v1";
    if(main.schema!==1 || main.type!=="model_forecast_7day_not_observation" ||
       main.grid_degrees!==.5 || (!large&&(main.width!==140||main.height!==76)) ||
       main.period_days!==7 || main.sample_count!==28 ||
       main.reference_version!==refVersion ||
       main.reference_metadata?.reference_version!==refVersion ||
       main.reference_metadata?.source_months!==360 ||
       main.reference_metadata?.years!==30 ||
       main.reference_metadata?.forecast_hour!==3 ||
       (large&&main.reference_metadata?.old_core_max_difference_k>0.001) ||
       !Array.isArray(main.sources) || main.sources.length!==28 ||
       !Array.isArray(main.lead_hours) || main.lead_hours.length!==28 ||
       main.lead_hours.some((v,i)=>v!==i*6+3 ||
          main.sources[i]?.forecast_hour!==v || !main.sources[i]?.sha256) ||
       !main.forecast_mean_q10_b64 || !main.anomaly_mean_q10_b64)
      throw Error("Sieben-Tage-Originaldaten oder historische CFSR-Referenz nicht verifiziert");
    if(cpc.width!==main.width || cpc.height!==main.height ||
       !Array.isArray(cpc.countries) || !cpc.country_mask_b64 ||
       (large&&(!Array.isArray(cpc.rings)||cpc.rings.length<100)) ||
       (large&&(main.lat_north!==84.75||main.lon_west!==-80.25||
                 main.lat_south!==24.75||main.lon_east!==99.75)) ||
       (!large&&(main.lat_north!==71.75||main.lon_west!==-24.75)))
      throw Error("Geografische Länderlinien oder GFS/CFSR-Raster sind unvereinbar");
    GW=main.width;GH=main.height;CELL=GW*GH;
    NORTH=main.lat_north;WEST=main.lon_west;
    const t=unpack(main.forecast_mean_q10_b64);
    const a=unpack(main.anomaly_mean_q10_b64);
    if(t.some(v=>!Number.isFinite(v)) || a.some(v=>!Number.isFinite(v)))
      throw Error("Unvollständiges GFS-Anomalieraster: keine Lücken erfunden");
    payload=main;temperature=t;anomaly=a;
    mask=parseMask(cpc.country_mask_b64);countries=cpc.countries;
    extended=large;vectorRings=large?cpc.rings:[];
    configureRegions();
  }
  function rgb(hex){return [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));}
  const RGB=COLORS.map(rgb);
  function color(v,absolute){
    if(absolute){
      const u=Math.max(0,Math.min(1,(v+30)/65));
      return [Math.round(43+u*190),Math.round(115+u*15),Math.round(214-u*155)];
    }
    let i=0;
    while(i<STOPS.length-2 && v>STOPS[i+1])i++;
    const t=Math.max(0,Math.min(1,(v-STOPS[i])/(STOPS[i+1]-STOPS[i])));
    return [0,1,2].map(k=>Math.round(RGB[i][k]*(1-t)+RGB[i+1][k]*t));
  }
  function polar(lon,lat){
    const r=Math.tan((90-lat)*RAD/2),angle=(lon-LON0)*RAD;
    return [r*Math.sin(angle),-r*Math.cos(angle)];
  }
  function computeView(region){
    const pts=[];
    const n=32;
    // Sample all four geographic edges; stereographic bounds are not axis-aligned.
    for(let i=0;i<=n;i++){
      const u=i/n;
      const lon=region.west+(region.east-region.west)*u;
      const lat=region.south+(region.north-region.south)*u;
      pts.push(polar(lon,region.south),polar(lon,region.north),
               polar(region.west,lat),polar(region.east,lat));
    }
    const xmin=Math.min(...pts.map(p=>p[0])),xmax=Math.max(...pts.map(p=>p[0]));
    const ymin=Math.min(...pts.map(p=>p[1])),ymax=Math.max(...pts.map(p=>p[1]));
    const scale=Math.max((xmax-xmin)/W,(ymax-ymin)/H)*1.04;
    const cx=(xmin+xmax)/2,cy=(ymin+ymax)/2;
    return {xmin:cx-scale*W/2,ymax:cy+scale*H/2,scale};
  }
  let VIEW=computeView(REGIONS.europe);
  function geo(px,py){
    if(el.projection.value==="latlon"){
      const region=currentRegion();
      return [region.west+(px+.5)/W*(region.east-region.west),
              region.north-(py+.5)/H*(region.north-region.south)];
    }
    const x=VIEW.xmin+(px+.5)*VIEW.scale;
    const y=VIEW.ymax-(py+.5)*VIEW.scale;
    const r=Math.hypot(x,y);
    return [LON0+Math.atan2(x,-y)/RAD,90-2*Math.atan(r)/RAD];
  }
  function gridCell(lon,lat){
    const gx=(lon-WEST)*2,gy=(NORTH-lat)*2;
    if(gx<0||gx>GW-1||gy<0||gy>GH-1)return null;
    return [gx,gy];
  }
  function interpolate(field,gx,gy){
    const x0=Math.floor(gx),y0=Math.floor(gy),x1=Math.min(GW-1,x0+1),y1=Math.min(GH-1,y0+1);
    const tx=gx-x0,ty=gy-y0;
    const a=field[y0*GW+x0],b=field[y0*GW+x1],
      c=field[y1*GW+x0],d=field[y1*GW+x1];
    return (a*(1-tx)+b*tx)*(1-ty)+(c*(1-tx)+d*tx)*ty;
  }
  function borderMapPoint(lon,lat){
    if(el.projection.value==="latlon"){
      const b=currentRegion();
      return [(lon-b.west)/(b.east-b.west)*W,(b.north-lat)/(b.north-b.south)*H];
    }
    const [x,y]=polar(lon,lat);
    return [(x-VIEW.xmin)/VIEW.scale,(VIEW.ymax-y)/VIEW.scale];
  }
  function drawExpandedBorders(ctx){
    if(!extended||!vectorRings.length)return;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0,0,W,H);ctx.clip();
    ctx.strokeStyle="rgba(42,53,65,.75)";
    ctx.lineWidth=1.45;
    ctx.lineCap="round";
    ctx.lineJoin="round";
    ctx.beginPath();
    for(const ring of vectorRings){
      if(ring.length<2)continue;
      for(let k=0;k<ring.length;k++){
        const [x,y]=borderMapPoint(ring[k][0],ring[k][1]);
        if(k===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      }
    }
    ctx.stroke();
    ctx.restore();
  }
  function draw(){
    if(!payload)return;
    VIEW=computeView(currentRegion());
    shown=el.metric.value==="absolute"?temperature:anomaly;
    const ctx=el.map.getContext("2d",{alpha:false});
    const image=ctx.createImageData(W,H),d=image.data;
    const lutSize=2401,lut=[];
    const abs=el.metric.value==="absolute";
    for(let i=0;i<lutSize;i++)lut.push(color(abs?-40+i/20:-30+i/40,abs));
    for(let y=0;y<H;y++){
      for(let x=0;x<W;x++){
        const i=(y*W+x)*4;
        const [lon,lat]=geo(x,y),cell=gridCell(lon,lat);
        let rr=237,gg=243,bb=247;
        if(cell){
          const v=interpolate(shown,cell[0],cell[1]);
          const j=abs?Math.max(0,Math.min(lutSize-1,Math.round((v+40)*20))):
            Math.max(0,Math.min(lutSize-1,Math.round((v+30)*40)));
          [rr,gg,bb]=lut[j];
          if(border&&!extended){
            // Reproject the original aligned and transparent CPC country lines
            // from the same geographical source as the 0.5° country grid.
            const bx=Math.max(0,Math.min(W-1,Math.round(cell[0]/(GW-1)*(W-1))));
            const by=Math.max(0,Math.min(H-1,Math.round(cell[1]/(GH-1)*(H-1))));
            const k=(by*W+bx)*4,alpha=border[k+3]/255;
            if(alpha>0.08){
              rr=Math.round(rr*(1-alpha)+border[k]*alpha);
              gg=Math.round(gg*(1-alpha)+border[k+1]*alpha);
              bb=Math.round(bb*(1-alpha)+border[k+2]*alpha);
            }
          }
        }
        d[i]=rr;d[i+1]=gg;d[i+2]=bb;d[i+3]=255;
      }
    }
    ctx.putImageData(image,0,0);
    drawExpandedBorders(ctx);
    el.map.setAttribute("aria-label",abs?"GFS-Mitteltemperatur nächste 7 Tage in °C":
      "GFS-Temperaturabweichung nächste 7 Tage in Kelvin gegenüber 1991–2020");
    el.label.textContent=currentRegion().name+" · "+
      (el.projection.value==="stereo"?"Stereografische Europaansicht":"Breiten-Längen-Ansicht")+" · 0,5°";
    legend(abs);countriesTable();
  }
  function legend(abs){
    if(abs){
      el.legend.innerHTML='<small>2-m-Temperatur in °C · kühler = bläulich, wärmer = rötlich. Kein klimatologischer Mittelwert.</small>';
      return;
    }
    const stops=COLORS.map((c,i)=>c+" "+((STOPS[i]+8)/16*100).toFixed(2)+"%").join(",");
    el.legend.innerHTML='<div class="weekly-gradient" style="background:linear-gradient(to right,'+stops+')"></div>'+
      '<div class="weekly-steps"><span>≤ −8 K</span><span>−4 K</span><span>−2 K</span><span>0 K</span><span>+2 K</span><span>+4 K</span><span>≥ +8 K</span></div>'+
      '<small>ERA5-orientierte Climate-Dashboard-Farben. Skala bei ±8 K begrenzt; Klimareferenz 1991–2020.</small>';
  }
  function countryMeans(){
    const totals=new Float64Array(countries.length),weights=new Float64Array(countries.length);
    const count=new Uint32Array(countries.length),visible=new Uint32Array(countries.length);
    const box=currentRegion();
    for(let y=0;y<GH;y++){
      const lat=NORTH-y*.5,w=Math.cos(lat*RAD);
      const inLat=lat>=box.south&&lat<=box.north;
      for(let x=0;x<GW;x++){
        const i=y*GW+x,id=mask[i],v=shown[i];
        if(id>=0&&id<countries.length&&Number.isFinite(v)){
          // Country means always reflect all original cells inside the full
          // verified source domain, never a cosmetically clipped mean.
          totals[id]+=w*v;weights[id]+=w;count[id]++;
          // The larger source domain includes North Africa and North America.
          // List only countries whose grids intersect the selected map view.
          if(inLat && (WEST+x*.5)>=box.west && (WEST+x*.5)<=box.east)visible[id]++;
        }
      }
    }
    return countries.map(c=>({id:c.id,name:c.name,
      value:weights[c.id]?totals[c.id]/weights[c.id]:NaN,
      coverage:c.cells?count[c.id]/c.cells:0,
      visible:visible[c.id]
    })).filter(x=>Number.isFinite(x.value)&&x.coverage>=.45&&
      (!extended||x.visible>0))
      .sort((a,b)=>b.value-a.value);
  }
  function choose(id){
    selected=id;
    el.country.querySelectorAll("tr[data-country]").forEach(tr=>
      tr.classList.toggle("active",Number(tr.dataset.country)===selected));
    const item=stats.find(c=>c.id===id);
    el.selected.textContent=item?item.name+": "+(item.value>=0?"+":"")+item.value.toFixed(2)+
      (el.metric.value==="anomaly"?" K":" °C"):"Land auswählen";
  }
  function countriesTable(){
    stats=countryMeans();
    el.countryTitle.textContent=el.metric.value==="anomaly"?"Abweichung (K)":"Temperatur (°C)";
    el.country.innerHTML=stats.length?stats.map(c=>
      '<tr tabindex="0" data-country="'+c.id+'"><td>'+c.name+'</td><td class="'+
      (c.value>=0?"warm":"cold")+'">'+(c.value>=0?"+":"")+c.value.toFixed(2)+
      (el.metric.value==="anomaly"?" K":" °C")+'</td><td>'+
      Math.round(c.coverage*100)+' %</td></tr>').join(""):
      '<tr><td colspan="3">Keine ausreichende Rasterabdeckung</td></tr>';
    el.country.querySelectorAll("tr[data-country]").forEach(tr=>{
      const handle=()=>choose(Number(tr.dataset.country));
      tr.addEventListener("click",handle);
      tr.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();handle();}});
    });
    if(!stats.some(c=>c.id===selected))selected=stats[0]?.id??null;
    choose(selected);
  }
  function download(url,name){
    const a=document.createElement("a");a.href=url;a.download=name;
    document.body.appendChild(a);a.click();a.remove();
  }
  function savePng(){
    if(!payload)return;
    const out=document.createElement("canvas");out.width=W;out.height=950;
    const ctx=out.getContext("2d");
    ctx.fillStyle="#fff";ctx.fillRect(0,0,W,950);
    ctx.fillStyle="#193a55";ctx.font="bold 29px Arial";
    ctx.fillText("Europa · GFS Sieben-Tage-Temperaturabweichung",32,45);
    ctx.font="18px Arial";
    ctx.fillText("GFS "+fmtTime(payload.run_utc)+" · "+
      (el.metric.value==="anomaly"?"CFSR/CFSv2 1991–2020":"2-m-Temperatur °C")+
      " · "+currentRegion().name,32,75);
    ctx.drawImage(el.map,0,100,W,H);
    ctx.font="15px Arial";ctx.fillText("Gültig "+fmtTime(payload.valid_from_utc)+" bis "+fmtTime(payload.valid_to_utc),32,895);
    ctx.fillText("NOAA GFS 0,5° f003–f165 · 28 echte Felder · 7 Tage · "+el.projection.options[el.projection.selectedIndex].text,32,925);
    out.toBlob(blob=>{if(!blob)return;const url=URL.createObjectURL(blob);
      download(url,"gfs_europa_7tage_"+payload.run_utc.slice(0,10)+".png");
      setTimeout(()=>URL.revokeObjectURL(url),5000);},"image/png");
  }
  function saveCsv(){
    if(!payload)return;
    const rows=["Land;Wert;Einheit;Abdeckung_Prozent;Modelllauf_UTC;Gueltig_von_UTC;Gueltig_bis_UTC;Referenz"];
    const unit=el.metric.value==="anomaly"?"K":"°C";
    for(const s of stats)rows.push([s.name,s.value.toFixed(3).replace(".",","),
      unit,Math.round(s.coverage*100),payload.run_utc,payload.valid_from_utc,
      payload.valid_to_utc,"CFSR/CFSv2 1991-2020 f003"].join(";"));
    const url=URL.createObjectURL(new Blob(["\ufeff"+rows.join("\r\n")],{type:"text/csv;charset=utf-8"}));
    download(url,"gfs_europa_7tage_laendermittel.csv");
    setTimeout(()=>URL.revokeObjectURL(url),5000);
  }
  el.metric.addEventListener("change",draw);
  el.projection.addEventListener("change",draw);
  el.region.addEventListener("change",draw);
  el.map.addEventListener("click",event=>{
    if(!payload||!mask)return;
    const box=el.map.getBoundingClientRect();
    const x=(event.clientX-box.left)/box.width*W,y=(event.clientY-box.top)/box.height*H;
    if(x<0||x>=W||y<0||y>=H)return;
    const [lon,lat]=geo(x,y),cell=gridCell(lon,lat);
    if(!cell)return;
    const ix=Math.round(cell[0]),iy=Math.round(cell[1]),id=mask[iy*GW+ix];
    if(id>=0&&id<countries.length)choose(id);
  });
  el.png.addEventListener("click",savePng);
  el.csv.addEventListener("click",saveCsv);
  el.pdf.addEventListener("click",()=>{if(payload)window.print();});
  async function start(){
    try{
      // The larger original grid becomes available ONLY after the complete
      // 1991–2020 f003 archive and its independent 50m geography are published.
      // Until then preserve the verified historic 76x140 map unchanged.
      let current=null,cpc=null;
      const [wide,geography]=await Promise.all([
        fetch("gfs_analysis_europe/weekly_f003_extended.json?v=1",{cache:"no-store"}),
        fetch("gfs_analysis_europe/extended_geography.json?v=1",{cache:"force-cache"})
      ]);
      if(wide.ok!==geography.ok)
        throw Error("Erweitertes GFS-Raster ist noch unvollständig veröffentlicht");
      if(wide.ok&&geography.ok){
        [current,cpc]=await Promise.all([wide.json(),geography.json()]);
        validate(current,cpc);
      }else{
        const [g,c]=await Promise.all([
          fetch("gfs_analysis_europe/weekly_f003.json?v=1",{cache:"no-store"}),
          fetch("cpc_europe/index.json?v=1",{cache:"force-cache"})
        ]);
        if(!g.ok||!c.ok)throw Error("GFS-Sieben-Tage-Daten oder Ländermaske noch nicht veröffentlicht");
        [current,cpc]=await Promise.all([g.json(),c.json()]);
        validate(current,cpc);
        const img=new Image();img.src="cpc_europe/boundaries.png?v=1";
        await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject;});
        if(img.naturalWidth<1000)throw Error("Ländergrenzen unvollständig");
        const off=document.createElement("canvas");off.width=W;off.height=H;
        const bx=off.getContext("2d");bx.drawImage(img,0,0,W,H);
        border=bx.getImageData(0,0,W,H).data;
      }
      el.run.textContent="Lauf "+fmtTime(payload.run_utc);
      el.status.textContent="Vorhersage "+fmtTime(payload.valid_from_utc)+" bis "+
        fmtTime(payload.valid_to_utc)+" · 28 Originalfelder";
      el.info.textContent="Echte NOAA-GFS-Sieben-Tage-Prognose · +3 bis +165 h · "+
        "CFSR/CFSv2-Temperaturklima 1991–2020 (360 historische Quellmonate) · "+
        (extended?"erweitertes Originalraster 80°W–100°O / 25–85°N":
                  "bisheriges Europa-Originalraster; geografische Erweiterung noch nicht veröffentlicht")+".";
      draw();
      [el.png,el.pdf,el.csv].forEach(btn=>btn.disabled=false);
    }catch(err){
      el.warn.hidden=false;
      el.warn.textContent=String(err.message||err);
      el.status.textContent="Sieben-Tage-Prognose konnte nicht geprüft werden";
      el.country.innerHTML='<tr><td colspan="3">Keine verifizierten Daten verfügbar</td></tr>';
    }
  }
  start();
})();
