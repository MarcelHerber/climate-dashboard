/* NOAA/NSIDC G02135 v4 · observed sea-ice extent · 1991–2020 normals */
(()=>{"use strict";
const find=(panel,key)=>panel.querySelector('[data-ice-'+key+']');
const number=new Intl.NumberFormat("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2});
const fmt=v=>Number.isFinite(v)?number.format(v):"–";
const labels={north:"Arktis",south:"Antarktis"};
const years={north:null,south:null};
const charts={north:[],south:[]};
const baseColors={north:"#1769b4",south:"#b23d7a"};
let archive=null;
function formattedDate(iso){
 if(!iso)return"–";
 const [y,m,d]=iso.split("-");return d+"."+m+"."+y;
}
function setMessage(panel,text){find(panel,"status").textContent=text;}
function dayLabels(){return archive.calendar_days;}
function monthTick(value){
 const iso=dayLabels()[Number(value)];
 if(!iso||!iso.endsWith("-01"))return "";
 return ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"][Number(iso.slice(0,2))-1];
}
function arrayOf(key,year){return archive[key].years[String(year)] || Array(366).fill(null);}
function anomaly(raw,norm,mode){
 if(!Number.isFinite(raw)||!Array.isArray(norm))return null;
 const m=norm[0],sd=norm[1],difference=raw-m;
 if(mode==="percent")return m===0?null:100*difference/m;
 if(mode==="sigma")return sd===0?null:difference/sd;
 return difference;
}
function modeUnit(mode){return mode==="absolute"?"Mio. km²":mode==="percent"?"%":"σ";}
function currentYear(hemisphere){return Number(archive[hemisphere].latest_date.slice(0,4));}
function selectedYear(panel){return Number(find(panel,'control="year"')?.value);}
// Dedicated accessors avoid deriving DOM selectors from raw input.
function control(panel,id){return panel.querySelector('[data-ice-control="'+id+'"]');}
function action(panel,id){return panel.querySelector('[data-ice-export="'+id+'"]');}
function canvas(panel,id){return panel.querySelector('[data-ice-chart="'+id+'"]');}
function chartAxes(yTitle){
 return {
  x:{grid:{display:false},ticks:{maxRotation:0,minRotation:0,autoSkip:false,
     callback:function(val){return monthTick(val)},font:{size:11},color:"#62738b"}},
  y:{title:{display:true,text:yTitle},grid:{color:"rgba(148,163,184,.18)"},
     ticks:{callback:v=>Number(v).toLocaleString("de-DE",{maximumFractionDigits:2})}}
 };
}
function commonOptions(title,unit){
 return {responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
  interaction:{mode:"index",intersect:false},
  elements:{line:{tension:0,spanGaps:false},point:{radius:0,hoverRadius:3,hitRadius:8}},
  scales:chartAxes(unit),
  plugins:{
   datalabels:{display:false},
   legend:{position:"bottom",labels:{usePointStyle:true,boxWidth:14,
     filter:item=>!item.text.startsWith("__")}},
   tooltip:{callbacks:{
    title:items=>{
     if(!items.length)return"";
     const idx=items[0].dataIndex,day=dayLabels()[idx]||"";
     return day?day.slice(3)+"."+day.slice(0,2)+".":"";
    },
    label:item=>{
     const v=item.parsed.y;
     return item.dataset.label+": "+fmt(v)+" "+unit;
    }
   }}
  }
 };
}
function datasetsFor(hemi,compare,showCompare){
 const h=archive[hemi],latest=currentYear(hemi);
 const norm=h.normal;
 const lower=norm.map(v=>v[0]-v[1]),upper=norm.map(v=>v[0]+v[1]);
 const band="#94a3b8";
 const list=[
  {label:"__untere 1σ",data:lower,borderColor:"rgba(0,0,0,0)",backgroundColor:"transparent",pointRadius:0,borderWidth:0},
  {label:"±1 Standardabweichung",data:upper,borderColor:"rgba(0,0,0,0)",backgroundColor:"rgba(100,116,139,.20)",
   fill:{target:0,above:"rgba(100,116,139,.20)",below:"rgba(100,116,139,.20)"},pointRadius:0,borderWidth:0},
  {label:"Mittel 1991–2020",data:norm.map(v=>v[0]),borderColor:"#49596c",backgroundColor:"#49596c",borderWidth:2.5}
 ];
 if(showCompare&&compare!==latest&&h.years[String(compare)])list.push(
  {label:"Vergleich "+compare,data:arrayOf(hemi,compare),borderColor:"#db8b33",
    backgroundColor:"#db8b33",borderDash:[5,3],borderWidth:1.7}
 );
 list.push({label:"Aktuell "+latest,data:arrayOf(hemi,latest),
    borderColor:baseColors[hemi],backgroundColor:baseColors[hemi],borderWidth:2.5});
 return list;
}
function anomaliesFor(hemi,compare,mode,showCompare){
 const h=archive[hemi],latest=currentYear(hemi),normal=h.normal;
 const calc=year=>arrayOf(hemi,year).map((value,i)=>anomaly(value,normal[i],mode));
 const plotted=calc(latest);
 const datasets=[
  {label:"Abweichung "+latest,data:plotted,borderColor:"#1b70ab",borderWidth:2,
   segment:{borderColor:ctx=>{
    const a=ctx.p0?.parsed.y,b=ctx.p1?.parsed.y;
    return Number.isFinite(a)&&Number.isFinite(b)&&(a+b)/2>0?"#c05243":"#1b70ab";
   }}}
 ];
 if(showCompare&&compare!==latest&&h.years[String(compare)])datasets.push(
  {label:"Abweichung "+compare,data:calc(compare),borderColor:"#d28c38",borderDash:[5,4],borderWidth:1.6}
 );
 datasets.push({label:"Nulllinie",data:normal.map(()=>0),borderColor:"#64748b",
   borderWidth:1,borderDash:[5,4],pointRadius:0});
 return datasets;
}
function kpi(name,value,note){
 const div=document.createElement("div");div.className="kpi";
 const label=document.createElement("span");label.textContent=name;
 const strong=document.createElement("b");strong.textContent=value;
 const small=document.createElement("small");small.textContent=note;
 div.append(label,strong,small);return div;
}

function annualExtremes(hemi){
 const h=archive[hemi],all=Object.keys(h.years).map(Number).sort((a,b)=>a-b);
 return all.filter(y=>y>=1979&&y<currentYear(hemi)).map(y=>{
  const vals=h.years[String(y)];
  const valid=vals.filter(Number.isFinite);
  // Reject missing days; tolerate February 29 absent in ordinary years.
  const expected=(y%4===0&&(y%100!==0||y%400===0))?366:365;
  if(valid.length!==expected)return null;
  return {year:y,min:Math.min(...valid),max:Math.max(...valid)};
 }).filter(Boolean);
}
function drawExtremes(hemi,panel){
 const rows=annualExtremes(hemi),ref=rows.filter(r=>r.year>=1991&&r.year<=2020);
 const avg=k=>ref.reduce((sum,r)=>sum+r[k],0)/ref.length;
 const minAvg=avg("min"),maxAvg=avg("max");
 const options={responsive:true,maintainAspectRatio:false,animation:false,
  interaction:{mode:"index",intersect:false},
  scales:{x:{grid:{display:false},ticks:{maxTicksLimit:12,color:"#62738b"}},
   y:{title:{display:true,text:"Mio. km²"},grid:{color:"rgba(148,163,184,.18)"}}},
  plugins:{legend:{position:"bottom"},datalabels:{display:false},
   tooltip:{callbacks:{label:ctx=>ctx.dataset.label+": "+fmt(ctx.parsed.y)+" Mio. km²"}}}};
 const datasets=[
  {label:"Jahresminimum",data:rows.map(r=>r.min),borderColor:"#1769b4",backgroundColor:"#1769b4",borderWidth:2,pointRadius:1},
  {label:"Jahresmaximum",data:rows.map(r=>r.max),borderColor:"#c05b4b",backgroundColor:"#c05b4b",borderWidth:2,pointRadius:1},
  {label:"Minimum-Mittel 1991–2020",data:rows.map(()=>minAvg),borderColor:"#1769b4",borderDash:[5,4],borderWidth:1.3,pointRadius:0},
  {label:"Maximum-Mittel 1991–2020",data:rows.map(()=>maxAvg),borderColor:"#c05b4b",borderDash:[5,4],borderWidth:1.3,pointRadius:0}
 ];
 charts[hemi].push(new Chart(canvas(panel,"extremes"),{type:"line",data:{labels:rows.map(r=>r.year),datasets},options}));
 const note=panel.querySelector("[data-ice-extreme-note]");
 note.textContent=rows.length?"Vollständige Jahre: "+rows.length+" · "+rows[0].year+"–"+rows[rows.length-1].year+
 " · Mittel der Jahresminima 1991–2020: "+fmt(minAvg)+" Mio. km² · Mittel der Jahresmaxima: "+fmt(maxAvg)+" Mio. km².":
 "Keine vollständigen Jahresreihen für diese Auswertung gefunden.";
}

function updatePanel(hemi){
 if(!archive)return;
 const panel=document.querySelector('[data-ice-region="'+hemi+'"]');
 const h=archive[hemi],compare=Number(control(panel,"year").value),
       show=control(panel,"compare").checked,mode=control(panel,"mode").value;
 const latest=currentYear(hemi);
 for(const chart of charts[hemi])chart.destroy();
 charts[hemi]=[];
 const extentCfg=commonOptions("Ausdehnung","Mio. km²");
 const anomalyCfg=commonOptions("Abweichung",modeUnit(mode));
 charts[hemi].push(new Chart(canvas(panel,"extent"),{
  type:"line",data:{labels:dayLabels(),datasets:datasetsFor(hemi,compare,show)},
  options:extentCfg
 }));
 charts[hemi].push(new Chart(canvas(panel,"anomaly"),{
  type:"line",data:{labels:dayLabels(),datasets:anomaliesFor(hemi,compare,mode,show)},
  options:anomalyCfg
 }));
 drawExtremes(hemi,panel);
 const date=h.latest_date,md=date.slice(5),index=dayLabels().indexOf(md);
 const observed=index<0?null:arrayOf(hemi,latest)[index];
 const ref=index<0?null:h.normal[index];
 const delta=anomaly(observed,ref,"absolute"),pct=anomaly(observed,ref,"percent"),
       z=anomaly(observed,ref,"sigma");
 const box=find(panel,"kpis");box.replaceChildren(
  kpi("Letzte Beobachtung",formattedDate(date),h.count.toLocaleString("de-DE")+" Tageswerte im Archiv"),
  kpi("Ausdehnung",fmt(observed)+" Mio. km²","Beobachtet"),
  kpi("Abweichung zu 1991–2020",(delta>0?"+":"")+fmt(delta)+" Mio. km²",
      (pct>0?"+":"")+fmt(pct)+" %"),
  kpi("Standardisierte Abweichung",(z>0?"+":"")+fmt(z)+" σ",
      "Referenz σ: "+fmt(ref?.[1])+" Mio. km²")
 );
 setMessage(panel,"NSIDC v4 · letzter Datentag "+formattedDate(date)+" · Vergleich "+compare+
   " · Tagesmittel ±1σ (1991–2020).");
 find(panel,"footer").textContent="1991–2020 Tagesmittel und 1σ aus je 30 Vergleichsjahren; 29. Februar mit "+
   h.normal[dayLabels().indexOf("02-29")][2]+" Schaltjahren. "+
   "Frühe Satellitenmessungen teils nur jeden zweiten Tag; Datenlücken werden nicht ergänzt.";
 ["png","pdf","csv"].forEach(x=>action(panel,x).disabled=false);
}
function buildExport(hemi){
 if(charts[hemi].length<2)throw Error("Noch keine Diagramme");
 const panel=document.querySelector('[data-ice-region="'+hemi+'"]');
 const big=charts[hemi][0].canvas,small=charts[hemi][1].canvas;
 const width=1300,header=160,pad=45,area=width-2*pad,between=48,footer=54;
 const high1=Math.round(area*big.height/big.width),high2=Math.round(area*small.height/small.width);
 const out=document.createElement("canvas");out.width=width;out.height=header+high1+between+high2+footer;
 const ctx=out.getContext("2d");ctx.fillStyle="#fff";ctx.fillRect(0,0,out.width,out.height);
 ctx.fillStyle="#172740";ctx.font="bold 30px Arial";
 ctx.fillText(labels[hemi]+" · Meereisausdehnung",pad,48);
 ctx.fillStyle="#48596e";ctx.font="18px Arial";
 ctx.fillText("NSIDC v4 · Referenz 1991–2020 · Mittelwert ±1σ · Vergleich "+
   control(panel,"year").value,pad,86);
 ctx.font="16px Arial";
 ctx.fillText("Ausdehnung / Abweichung in "+modeUnit(control(panel,"mode").value),pad,118);
 ctx.drawImage(big,pad,header,area,high1);
 ctx.drawImage(small,pad,header+high1+between,area,high2);
 ctx.fillStyle="#65748a";ctx.font="15px Arial";
 ctx.fillText("Quelle: NOAA/NSIDC Sea Ice Index v4 · doi:10.7265/a98x-0f50 · Tagesbeobachtungen",pad,out.height-20);
 return out;
}
function save(blob,hemi,ext){
 const href=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=href;a.download="meereis_"+hemi+"_1991-2020."+ext;
 document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(href),2000);
}
function exportFile(hemi,type){
 const panel=document.querySelector('[data-ice-region="'+hemi+'"]');
 try{
  if(type==="png"){
   buildExport(hemi).toBlob(blob=>{if(blob)save(blob,hemi,"png")},"image/png");
  }else if(type==="pdf"){
   if(!window.jspdf?.jsPDF)throw Error("PDF-Bibliothek nicht geladen");
   const image=buildExport(hemi);
   const pdf=new window.jspdf.jsPDF({orientation:"portrait",format:"a4",unit:"mm"});
   const scale=Math.min(186/image.width,270/image.height);
   pdf.addImage(image.toDataURL("image/png"),"PNG",12,12,image.width*scale,image.height*scale);
   pdf.save("meereis_"+hemi+"_1991-2020.pdf");
  }else if(type==="csv"){
   const h=archive[hemi],latest=currentYear(hemi),compare=Number(control(panel,"year").value);
   const rows=[["Datum (MM-TT)","Mittel 1991–2020 (Mio km2)","Standardabw. (Mio km2)","n","Aktuell "+latest,
     "Vergleich "+compare,"Aktuelle Anomalie (Mio km2)","Aktuelle Anomalie (%)","Aktuelle Anomalie (sigma)"]];
   dayLabels().forEach((day,i)=>{
    const norm=h.normal[i],value=arrayOf(hemi,latest)[i],prior=arrayOf(hemi,compare)[i];
    rows.push([day,norm[0],norm[1],norm[2],value??"",prior??"",
      anomaly(value,norm,"absolute")??"",anomaly(value,norm,"percent")??"",
      anomaly(value,norm,"sigma")??""]);
   });
   const csv="\uFEFF"+rows.map(row=>row.map(v=>'"'+String(v??"").replace(/"/g,'""')+'"').join(";")).join("\r\n");
   save(new Blob([csv],{type:"text/csv;charset=utf-8"}),hemi,"csv");
  }
 }catch(err){console.error(err);setMessage(panel,"Download fehlgeschlagen: "+err.message)}
}
async function start(){
 for(const hemi of ["north","south"]){
  const panel=document.querySelector('[data-ice-region="'+hemi+'"]');
  for(const id of ["year","mode","compare"])control(panel,id).addEventListener("change",()=>updatePanel(hemi));
  for(const ext of ["png","pdf","csv"])action(panel,ext).addEventListener("click",()=>exportFile(hemi,ext));
 }
 try{
  if(!window.Chart)throw Error("Chart.js fehlt");
  const response=await fetch("sea_ice/index.json",{cache:"no-store"});
  if(!response.ok)throw Error("NSIDC-Archiv HTTP "+response.status);
  archive=await response.json();
  if(!archive.ready||archive.reference_period?.join("-")!=="1991-2020"||
    archive.calendar_days?.length!==366||!archive.north?.years||!archive.south?.years)
    throw Error("NSIDC-Datenarchiv ist unvollständig");
  for(const hemi of ["north","south"]){
   const panel=document.querySelector('[data-ice-region="'+hemi+'"]');
   const years=Object.keys(archive[hemi].years).map(Number).sort((a,b)=>b-a);
   const latest=currentYear(hemi);
   const controlYear=control(panel,"year");
   controlYear.replaceChildren();
   for(const y of years){
    if(y===latest)continue;
    const option=document.createElement("option");option.value=String(y);option.textContent=String(y);
    controlYear.appendChild(option);
   }
   controlYear.value=String(years.includes(hemi==="north"?2012:2023)?(hemi==="north"?2012:2023):years.find(y=>y<latest));
   controlYear.disabled=false;
   updatePanel(hemi);
  }
  document.getElementById("seaIceUpdated").textContent="Aktualisiert "+String(archive.created_utc||"").slice(0,16).replace("T"," ")+" UTC";
 }catch(e){
  console.error("NSIDC sea ice:",e);
  for(const hemi of ["north","south"]){
   const panel=document.querySelector('[data-ice-region="'+hemi+'"]');
   setMessage(panel,"Daten noch nicht verfügbar: "+e.message+". Bitte NSIDC-Aktualisierung prüfen.");
  }
 }
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);else start();
})();
