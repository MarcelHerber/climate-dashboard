/* GEFS ensemble reversal diagnostics. Real 31-member 10hPa / 60N U wind, no SSW claim. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
let chart=null,rows=[],lastCycle="";
function pct(n,total=31){return Math.round(n/total*100)+" %";}
function render(){
 const data=window.stratoGefsEnsemble;
 if(!data || data.provider!=="NOAA GEFS" || data.level_hpa!==10 || data.latitude_deg!==60 ||
    !Array.isArray(data.valid_dates)||!data.members||
    Object.keys(data.members).length!==31 ||!Object.values(data.members).every(row=>Array.isArray(row)&&row.length===data.valid_dates.length)){
  $("stratoProbStatus").textContent="Kein validierter 31-Member-GEFS-Lauf verfügbar.";
  for(const id of ["stratoProbAny","stratoProbPeak","stratoProbCycle"])$(id).textContent="–";
  rows=[];if(chart){chart.destroy();chart=null;}return;
 }
 lastCycle=data.cycle_utc;
 const members=Object.values(data.members);
 if(members.some(arr=>arr.some(v=>typeof v!=="number"||!Number.isFinite(v)||v<=-160||v>=170))){
   $("stratoProbStatus").textContent="Ungültige GEFS-Einzelwerte; keine Wahrscheinlichkeit berechnet.";return;
 }
 // A new reversal requires a signed transition across zero.
 // A member already in easterlies at step 0 is NOT a newly forecast reversal.
 const crossed=members.filter(arr=>arr.some((v,i)=>i>0&&arr[i-1]>=0&&v<0)).length;
 rows=data.valid_dates.map((date,i)=>{
   const count=members.filter(arr=>arr[i]<0).length;
   const first=members.filter(arr=>arr[i]<0&&arr.slice(0,i).every(v=>v>=0)).length;
   return {date,count,first,p:100*count/31};
 });
 const peak=rows.reduce((a,b)=>b.p>a.p?b:a,rows[0]);
 $("stratoProbAny").textContent=pct(crossed);
 $("stratoProbPeak").textContent=pct(peak.count)+" · "+peak.date;
 $("stratoProbCycle").textContent=lastCycle.slice(0,16).replace("T"," ")+" UTC";
 $("stratoProbStatus").textContent="Täglich "+rows.length+" gültige Prognosetermine, "+members.length+" echte Mitglieder. "+
   "Eine neue Windumkehr zählt nur beim Übergang von U ≥ 0 auf U < 0 m/s. Tagesbalken zeigen den Anteil mit Ostwind. Lauf: "+lastCycle+
   " · Prognose bis "+rows.at(-1).date+".";
 if(chart)chart.destroy();
 chart=new Chart($("stratoProbCanvas"),{
  type:"bar",
  data:{labels:rows.map(row=>row.date.slice(5)),datasets:[
    {label:"Mitglieder mit Ostwind am jeweiligen Tag",data:rows.map(row=>row.p),
      backgroundColor:"rgba(26,93,164,.70)",borderColor:"#185c9d",borderWidth:1,borderRadius:3}
  ]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,
   interaction:{mode:"index",intersect:false},
   plugins:{legend:{display:false},tooltip:{callbacks:{
     title:items=>rows[items[0]?.dataIndex]?.date||"",
     label:ctx=>pct(rows[ctx.dataIndex].count)+" ("+rows[ctx.dataIndex].count+"/31 Mitglieder)"
   }}},
   scales:{
    x:{ticks:{maxTicksLimit:14,maxRotation:0},title:{display:true,text:"Gültigkeitsdatum (00 UTC)"}},
    y:{min:0,max:100,title:{display:true,text:"GEFS-Mitglieder mit U < 0 m/s (%)"},ticks:{callback:v=>v+" %"}}
   }
  }
 });
}
$("stratoProbCsv").addEventListener("click",()=>{
 if(!rows.length)return;
 const out=["valid_date_00UTC;members_negative;members_total;probability_percent;first_negative_members",
  ...rows.map(r=>[r.date,r.count,31,r.p.toFixed(2),r.first].join(";"))].join("\r\n");
 const blob=new Blob(["\ufeff"+out],{type:"text/csv;charset=utf-8"}),url=URL.createObjectURL(blob);
 const a=document.createElement("a");a.href=url;a.download="Stratosphaere_GEFS_Windumkehrwahrscheinlichkeit.csv";
 a.click();setTimeout(()=>URL.revokeObjectURL(url),2500);
});
window.addEventListener("stratosphere:gefs-loaded",render);
if(window.stratoGefsEnsemble)render();
})();
