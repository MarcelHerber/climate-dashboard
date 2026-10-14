(()=>{"use strict";
const $=id=>document.getElementById(id);
const names={GLOBAL:"Weltweit",NA:"Nordatlantik",EP:"Nordost-/Zentralpazifik",WP:"Nordwestpazifik",NI:"Nordindischer Ozean",SI:"Südindischer Ozean",SP:"Südpazifik",atl:"Nordatlantik (NHC)",epac:"Nordostpazifik (NHC)"};
let datasets={},annual=null,daily=null;
const opt={responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},plugins:{legend:{position:"bottom"}}};
async function load(url){const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw Error(url+" HTTP "+r.status);const d=await r.json();if(!d.ready||!d.basins)throw Error(url+" unvollständig");return d;}
function render(keepYear=true){
 const b=datasets[$("aceBasin").value];
 if(!b)return;
 const years=Object.keys(b.years).sort((a,z)=>Number(a)-Number(z));
 const select=$("aceYear"),old=keepYear?select.value:null;
 select.replaceChildren();
 for(const y of [...years].reverse()){const o=document.createElement("option");o.value=y;o.textContent=y;select.append(o);}
 select.value=old&&b.years[old]?old:years[years.length-1];
 const y=select.value, mean=b.reference_mean;
 const totals=years.map(key=>b.years[key].total);
 $("aceKpis").textContent="Zeitraum "+b.first_year+"–"+b.last_year+" · Mittel 1991–2020: "+mean.toFixed(1)+" ACE · "+y+": "+b.years[y].total.toFixed(1)+" ACE"+(b.years[y].provisional?" (vorläufig)":"");
 $("aceStatus").textContent=b.origin==="ibtracs"?"NOAA IBTrACS · Kalenderjahre · globale Vergleichsmethodik":"NHC HURDAT2 · tropische Hurrikansaisons";
 if(annual)annual.destroy();
 annual=new Chart($("aceAnnual"),{type:"bar",data:{labels:years,datasets:[
  {label:"ACE / Jahr",data:totals,backgroundColor:years.map((key,i)=>b.years[key].provisional?"#e2a63b":totals[i]>=mean?"#c05243":"#3975b6")},
  {type:"line",label:"Mittel 1991–2020",data:years.map(()=>mean),borderColor:"#293647",pointRadius:0,borderWidth:2}
 ]},options:opt});
 renderDaily();
}
function renderDaily(){
 const b=datasets[$("aceBasin").value],y=$("aceYear").value;
 if(!b?.years[y])return;
 const last=b.years[y].last_date;
 $("aceStatus").textContent=(b.origin==="ibtracs"?"NOAA IBTrACS":"NHC HURDAT2")+" · "+(b.years[y].provisional?"2026 vorläufig, Beobachtungen bis "+last:"abgeschlossene Saison "+y);
 $("aceKpis").textContent="Zeitraum "+b.first_year+"–"+b.last_year+" · Mittel 1991–2020: "+b.reference_mean.toFixed(1)+" ACE · "+y+": "+b.years[y].total.toFixed(1)+" ACE";
 if(daily)daily.destroy();
 const axis=Array.from({length:366},(_,i)=>i+1);
 daily=new Chart($("aceDaily"),{type:"line",data:{labels:axis,datasets:[
  {label:y,data:b.years[y].daily_cumulative,borderColor:"#2772b6",pointRadius:0,borderWidth:2},
  {label:"Mittel 1991–2020",data:b.reference_daily,borderColor:"#4f5967",pointRadius:0,borderWidth:2}
 ]},options:{...opt,scales:{x:{title:{display:true,text:"Kalendertag (Schaltjahr-Achse)"}}}}});
}
function exportCanvas(){
 const width=1400,pad=48,top=130,gap=52;
 const ca=annual.canvas,cb=daily.canvas;
 const aheight=Math.round(ca.height/ca.width*(width-2*pad));
 const bheight=Math.round(cb.height/cb.width*(width-2*pad));
 const out=document.createElement("canvas");out.width=width;out.height=top+aheight+gap+bheight+95;
 const ctx=out.getContext("2d");
 ctx.fillStyle="#ffffff";ctx.fillRect(0,0,out.width,out.height);
 ctx.fillStyle="#193451";ctx.font="bold 29px Arial";
 ctx.fillText("Accumulated Cyclone Energy · "+$("aceBasin").selectedOptions[0].text,pad,48);
 ctx.fillStyle="#536477";ctx.font="19px Arial";
 const b=datasets[$("aceBasin").value],y=$("aceYear").value;
 ctx.fillText("Jahr "+y+(b.years[y].provisional?" · vorläufig bis "+b.years[y].last_date:"")+" · Mittel 1991–2020",pad,83);
 ctx.drawImage(ca,pad,top,width-2*pad,aheight);
 ctx.drawImage(cb,pad,top+aheight+gap,width-2*pad,bheight);
 ctx.fillStyle="#56687a";ctx.font="16px Arial";
 ctx.fillText("Quelle: "+(b.origin==="ibtracs"?"NOAA IBTrACS v4 · ACE-Näherung":"NHC HURDAT2")+" · 10⁴ kn²",pad,out.height-35);
 return out;
}
function download(blob,ext){
 const a=document.createElement("a"),url=URL.createObjectURL(blob);
 a.href=url;a.download="ACE_"+$("aceBasin").value+"_"+$("aceYear").value+"."+ext;
 document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),4000);
}
function exportData(kind){
 try{
  if(!annual||!daily)throw Error("Noch keine Diagramme");
  const b=datasets[$("aceBasin").value],y=$("aceYear").value;
  if(kind==="csv"){
   const years=Object.keys(b.years).sort((a,z)=>Number(a)-Number(z));
   const rows=[["Jahr","ACE (10^4 kn^2)","Vorläufig","Daten bis","Klimamittel 1991-2020"],...years.map(v=>[v,b.years[v].total,b.years[v].provisional?"ja":"nein",b.years[v].last_date||"",b.reference_mean])];
   rows.push([],["Kalendertag","Kumulierte ACE "+y,"Klimamittel 1991-2020"]);
   for(let i=0;i<366;i++)rows.push([i+1,b.years[y].daily_cumulative[i]??"",b.reference_daily[i]??""]);
   const csv="\uFEFF"+rows.map(a=>a.map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(";")).join("\r\n");
   download(new Blob([csv],{type:"text/csv;charset=utf-8"}),"csv");
  }else if(kind==="png"){
   exportCanvas().toBlob(blob=>{if(blob)download(blob,"png")}, "image/png");
  }else if(kind==="pdf"){
   if(!window.jspdf?.jsPDF)throw Error("PDF-Bibliothek nicht geladen");
   const canvas=exportCanvas();
   const pdf=new window.jspdf.jsPDF({orientation:"portrait",unit:"mm",format:"a4"});
   const scale=Math.min(186/canvas.width,270/canvas.height);
   pdf.addImage(canvas.toDataURL("image/png"),"PNG",12,12,canvas.width*scale,canvas.height*scale);
   pdf.save("ACE_"+$("aceBasin").value+"_"+$("aceYear").value+".pdf");
  }
 }catch(e){$("aceStatus").textContent="Download fehlgeschlagen: "+e.message;}
}
async function start(){
 const result=await Promise.allSettled([load("ace/global.json"),load("ace/index.json")]);
 const global=result[0].status==="fulfilled"?result[0].value:null;
 const nhc=result[1].status==="fulfilled"?result[1].value:null;
 if(global)for(const [k,v] of Object.entries(global.basins))datasets[k]={...v,origin:"ibtracs"};
 if(nhc)for(const [k,v] of Object.entries(nhc.basins))datasets[k]={...v,origin:"nhc"};
 const select=$("aceBasin");select.replaceChildren();
 for(const key of ["GLOBAL","NA","EP","WP","NI","SI","SP","atl","epac"]){
  if(!datasets[key])continue;
  const option=document.createElement("option");option.value=key;option.textContent=names[key]||key;select.append(option);
 }
 if(!select.options.length){$("aceStatus").textContent="ACE-Archive sind noch nicht importiert. GitHub-Actions-Datenlauf prüfen.";return;}
 select.value=datasets.GLOBAL?"GLOBAL":select.options[0].value;
 document.querySelectorAll("[data-ace-export]").forEach(btn=>btn.addEventListener("click",()=>exportData(btn.dataset.aceExport)));
 select.addEventListener("change",()=>render(false));
 $("aceYear").addEventListener("change",renderDaily);
 render(false);
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>start().catch(e=>{$("aceStatus").textContent=e.message;}));
else start().catch(e=>{$("aceStatus").textContent=e.message;});
})();