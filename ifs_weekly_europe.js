/* ECMWF IFS native 0.1°: 29 original 6-hourly 2m temperature fields. ERA5 1991–2020, native 0.25° reference bilinearly remapped. */
(() => {
  "use strict";
  const W=2100,H=1140,LON0=12;
  let GW=1801,GH=601,CELL=GW*GH,NORTH=85,WEST=-80;
  let extended=true,vectorRings=[];
  const PI=Math.PI,RAD=PI/180;
  // Regional views use the original 0.1° IFS domain; no extrapolation.
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
    if(raw.length!==CELL*2)throw Error("Ungültiger IFS-0,1°-Rasterumfang");
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
    const ref=main.reference_metadata;
    const verified=main.reference_ready===true;
    const run=Date.parse(main.run_utc), end=Date.parse(main.valid_to_utc);
    if(main.schema!==1||main.type!=="ifs_0p1_seven_day_forecast"||
       main.grid_degrees!==.1||main.width!==1801||main.height!==601||
       main.lat_north!==85||main.lat_south!==25||main.lon_west!==-80||main.lon_east!==100||
       main.period_days!==7||main.sample_count!==29||
       !Number.isFinite(run)||Date.parse(main.valid_from_utc)!==run||end-run!==168*3600000||
       !Array.isArray(main.lead_hours)||main.lead_hours.length!==29||
       !Array.isArray(main.sources)||main.sources.length!==29||
       main.lead_hours.some((h,i)=>h!==6*i||main.sources[i]?.forecast_hour!==h||
           Date.parse(main.sources[i]?.valid_utc)!==run+h*3600000||
           !/^[a-f0-9]{64}$/.test(main.sources[i]?.sha256)||main.sources[i]?.bytes<1000)||
       !main.forecast_mean_q10_b64)
      throw Error("Keine vollständig geprüfte originale IFS-0,1°-Prognose");
    if(verified&&(main.reference_version!=="era5-t2m-calendar-hour-1991-2020-v1"||
        ref?.period!=="1991–2020"||ref?.years!==30||ref?.native_grid_degrees!==.25||
        ref?.interpolation!=="bilinear"||!main.anomaly_mean_q10_b64))
      throw Error("ERA5-Referenz nicht vollständig geprüft");
    if(cpc.width!==1801||cpc.height!==601||cpc.grid_degrees!==.1||
       !Array.isArray(cpc.countries)||!cpc.country_mask_b64||
       !Array.isArray(cpc.rings)||cpc.rings.length<100)
      throw Error("Geografisches Raster nicht kompatibel");
    GW=main.width;GH=main.height;CELL=GW*GH;NORTH=main.lat_north;WEST=main.lon_west;
    temperature=unpack(main.forecast_mean_q10_b64);
    anomaly=verified?unpack(main.anomaly_mean_q10_b64):null;
    if(temperature.some(v=>!Number.isFinite(v))||anomaly?.some(v=>!Number.isFinite(v)))
      throw Error("Unvollständiges IFS-Raster");
    payload=main;mask=parseMask(cpc.country_mask_b64);countries=cpc.countries;
    vectorRings=cpc.rings;extended=true;
    el.metric.querySelector('option[value="anomaly"]').disabled=!verified;
    if(!verified)el.metric.value="absolute";
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
    const gx=(lon-WEST)*10,gy=(NORTH-lat)*10;
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
    ctx.lineWidth=2.175;
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
    el.map.setAttribute("aria-label",abs?"IFS-Mitteltemperatur nächste 7 Tage in °C":
      "IFS-Temperaturabweichung nächste 7 Tage in Kelvin gegenüber 1991–2020");
    el.label.textContent=currentRegion().name+" · "+
      (el.projection.value==="stereo"?"Stereografische Europaansicht":"Breiten-Längen-Ansicht")+" · 0,1° IFS";
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
      '<small>ERA5-orientierte Climate-Dashboard-Farben. Skala bei ±8 K begrenzt; ERA5 1991–2020 (0,25°), auf 0,1° interpoliert.</small>';
  }
  function countryMeans(){
    const totals=new Float64Array(countries.length),weights=new Float64Array(countries.length);
    const count=new Uint32Array(countries.length),visible=new Uint32Array(countries.length);
    const box=currentRegion();
    for(let y=0;y<GH;y++){
      const lat=NORTH-y*.1,w=Math.cos(lat*RAD);
      const inLat=lat>=box.south&&lat<=box.north;
      for(let x=0;x<GW;x++){
        const i=y*GW+x,id=mask[i],v=shown[i];
        if(id>=0&&id<countries.length&&Number.isFinite(v)){
          // Country means always reflect all original cells inside the full
          // verified source domain, never a cosmetically clipped mean.
          totals[id]+=w*v;weights[id]+=w;count[id]++;
          // The larger source domain includes North Africa and North America.
          // List only countries whose grids intersect the selected map view.
          if(inLat && (WEST+x*.1)>=box.west && (WEST+x*.1)<=box.east)visible[id]++;
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
  // Draw the *same* palette as the map into its downloadable image.
  // Legend values come from color(), so neither projections nor map smoothing
  // can accidentally introduce a second, mismatching colour scale.
  function drawExportLegend(ctx,absolute){
    const x=205,y=752,w=990,h=94;
    ctx.save();
    ctx.fillStyle="rgba(255,255,255,0.94)";
    ctx.fillRect(x,y,w,h);
    ctx.strokeStyle="rgba(25,58,85,0.45)";
    ctx.lineWidth=1;ctx.strokeRect(x+.5,y+.5,w-1,h-1);
    ctx.fillStyle="#193a55";ctx.font="bold 16px Arial";
    ctx.textBaseline="alphabetic";
    ctx.fillText(absolute?"2-m-Mitteltemperatur (°C)":
      "Temperaturabweichung gegenüber 1991–2020 (K)",x+20,y+23);
    const bx=x+20,by=y+33,bw=w-40,bh=19;
    const low=absolute?-30:-8,high=absolute?35:8;
    for(let i=0;i<bw;i++){
      const v=low+(high-low)*i/(bw-1);
      const [r,g,b]=color(v,absolute);
      ctx.fillStyle="rgb("+r+","+g+","+b+")";
      ctx.fillRect(bx+i,by,1,bh);
    }
    ctx.strokeStyle="#8299ae";ctx.strokeRect(bx+.5,by+.5,bw-1,bh-1);
    const ticks=absolute?[-30,-20,-10,0,10,20,35]:[-8,-4,-2,0,2,4,8];
    ctx.fillStyle="#193a55";ctx.font="14px Arial";ctx.textBaseline="top";
    for(let i=0;i<ticks.length;i++){
      const v=ticks[i],tx=bx+(v-low)/(high-low)*bw;
      ctx.textAlign=i===0?"left":i===ticks.length-1?"right":"center";
      const label=absolute?(i===0?"≤ −30":i===ticks.length-1?"≥ +35":
        (v>0?"+":"")+v):(i===0?"≤ −8":i===ticks.length-1?"≥ +8":
        (v>0?"+":"")+v);
      ctx.fillText(label,tx,by+bh+8);
    }
    ctx.restore();
  }
  function exportMapCanvas(){
    if(!payload)return null;
    const absolute=el.metric.value==="absolute";
    const out=document.createElement("canvas");out.width=W;out.height=1425;
    const ctx=out.getContext("2d");ctx.scale(1.5,1.5);
    ctx.fillStyle="#fff";ctx.fillRect(0,0,1400,950);
    ctx.fillStyle="#193a55";ctx.font="bold 29px Arial";
    ctx.fillText("Europa · IFS Sieben-Tage-"+(absolute?"Mitteltemperatur":"Temperaturabweichung"),32,45);
    ctx.font="18px Arial";
    ctx.fillText("ECMWF IFS "+fmtTime(payload.run_utc)+" · "+
      (absolute?"2-m-Temperatur °C":"ERA5 1991–2020 (0,25° → 0,1°)")+
      " · "+currentRegion().name,32,75);
    ctx.drawImage(el.map,0,100,1400,760);
    drawExportLegend(ctx,absolute);
    ctx.fillStyle="#193a55";ctx.font="15px Arial";
    ctx.fillText("Gültig "+fmtTime(payload.valid_from_utc)+" bis "+fmtTime(payload.valid_to_utc),32,895);
    ctx.fillText("ECMWF IFS 0,1° · +0 bis +168 h · 29 Originalfelder · "+
      el.projection.options[el.projection.selectedIndex].text,32,925);
    return out;
  }
  function savePng(){
    const out=exportMapCanvas();if(!out)return;
    out.toBlob(blob=>{if(!blob)return;const url=URL.createObjectURL(blob);
      download(url,"ifs_europa_7tage_"+payload.run_utc.slice(0,10)+".png");
      setTimeout(()=>URL.revokeObjectURL(url),5000);},"image/png");
  }
  function savePdf(){
    const out=exportMapCanvas();if(!out)return;
    document.getElementById("weekPrintPage")?.remove();
    const container=document.createElement("div");
    container.id="weekPrintPage";
    container.setAttribute("aria-hidden","true");
    const img=new Image();
    img.alt="IFS-Sieben-Tage-Karte mit integrierter Farbskala";
    container.appendChild(img);document.body.appendChild(container);
    const cleanup=()=>{
      document.body.classList.remove("weekly-export-print");
      container.remove();
    };
    window.addEventListener("afterprint",cleanup,{once:true});
    img.onload=()=>{
      document.body.classList.add("weekly-export-print");
      window.print();
    };
    img.onerror=cleanup;
    img.src=out.toDataURL("image/png");
  }
  function saveCsv(){
    if(!payload)return;
    const rows=["Land;Wert;Einheit;Abdeckung_Prozent;Modelllauf_UTC;Gueltig_von_UTC;Gueltig_bis_UTC;Referenz"];
    const unit=el.metric.value==="anomaly"?"K":"°C";
    for(const s of stats)rows.push([s.name,s.value.toFixed(3).replace(".",","),
      unit,Math.round(s.coverage*100),payload.run_utc,payload.valid_from_utc,
      payload.valid_to_utc,(unit==="K"?"ERA5 1991-2020 0.25° bilinear":"keine")].join(";"));
    const url=URL.createObjectURL(new Blob(["\ufeff"+rows.join("\r\n")],{type:"text/csv;charset=utf-8"}));
    download(url,"ifs_europa_7tage_laendermittel.csv");
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
  el.pdf.addEventListener("click",savePdf);
  async function start(){
    try{
      const [combined,geoResponse]=await Promise.all([
        fetch("ifs_weekly_europe/current.json",{cache:"no-store"}),
        fetch("ifs_weekly_europe/geography.json",{cache:"force-cache"})
      ]);
      const response=combined.ok?combined:await fetch("ifs_weekly_europe/forecast.json",{cache:"no-store"});
      if(!response.ok||!geoResponse.ok)throw Error("Geprüfte IFS-0,1°-Daten noch nicht veröffentlicht.");
      validate(await response.json(),await geoResponse.json());
      el.run.textContent="Lauf "+fmtTime(payload.run_utc);
      el.status.textContent="Vorhersage "+fmtTime(payload.valid_from_utc)+" bis "+
        fmtTime(payload.valid_to_utc)+" · 29 Originalfelder";
      el.info.textContent=payload.reference_ready?
        "ECMWF IFS 0,1° · ERA5 1991–2020, kalender- und UTC-stundengenau (0,25° bilinear auf 0,1° interpoliert).":
        "ECMWF IFS 0,1° · ERA5-Klimareferenz noch in Prüfung; nur absolute Temperatur.";
      draw();
      [el.png,el.pdf,el.csv].forEach(btn=>btn.disabled=false);
    }catch(err){
      el.warn.hidden=false;el.warn.textContent=String(err.message||err);
      el.status.textContent="Keine geprüfte Sieben-Tage-Prognose verfügbar";
      el.country.innerHTML='<tr><td colspan="3">Keine verifizierten Daten verfügbar</td></tr>';
    }
  }
  start();
})();
