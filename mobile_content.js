/* Mobile visuals: display-only Chart.js layout tuning and overflow indicators.
   Never modify forecast values, scale bounds, sample count, or exports. */
(()=>{
"use strict";
const MQ="(max-width: 430px)";
const MOBILE_WIDE="(max-width: 600px)";
const CHART_ID="climateMobileLegibilityV1";
const charts=new WeakMap();
let chartCtor=null;
let resizePending=false;
const match=query=>typeof window.matchMedia==="function"&&window.matchMedia(query).matches;
function isSmall(){return match(MQ)}
function parseFontSize(value){return Number.isFinite(value)?value:null}
function snapshot(chart){
 const scale=chart?.options?.scales?.x;
 const ticks=scale?.ticks;
 if(!ticks||ticks.display===false||ticks.autoSkip===false)return null;
 const legend=chart?.options?.plugins?.legend;
 const labels=legend&&typeof legend==="object"?legend.labels:null;
 const original={
  ticks, limit:ticks.maxTicksLimit,rotation:ticks.maxRotation,
  font:ticks.font&&typeof ticks.font==="object"?ticks.font:null,
  tickSize:parseFontSize(ticks.font?.size),
  legendLabels:labels&&typeof labels==="object"?labels:null,
  legendBoxWidth:labels?.boxWidth,legendFont:labels?.font&&typeof labels.font==="object"?labels.font:null,
  legendFontSize:parseFontSize(labels?.font?.size)
 };
 charts.set(chart,original);
 return original;
}
function restore(obj,field,original){
 if(original===undefined)delete obj[field];
 else obj[field]=original;
}
function adjustChart(chart){
 if(!chart?.options?.scales)return;
 const x=chart.options.scales.x;
 if(!x||!x.ticks||x.ticks.display===false||x.ticks.autoSkip===false)return;
 let state=charts.get(chart);
 if(!state||state.ticks!==x.ticks)state=snapshot(chart);
 if(!state)return;
 if(isSmall()){
  const authored=Number.isFinite(Number(state.limit))&&Number(state.limit)>0?Number(state.limit):5;
  x.ticks.maxTicksLimit=Math.min(authored,5);
  // Keep the original formatter, axes type and actual forecast timestamps.
  x.ticks.maxRotation=0;
  if(state.font&&state.tickSize!==null)state.font.size=Math.min(state.tickSize,11);
  if(state.legendLabels){
   const b=Number(state.legendBoxWidth);
   state.legendLabels.boxWidth=Number.isFinite(b)&&b>0?Math.min(12,b):12;
   if(state.legendFont&&state.legendFontSize!==null)
    state.legendFont.size=Math.min(state.legendFontSize,11);
  }
 }else{
  restore(x.ticks,"maxTicksLimit",state.limit);
  restore(x.ticks,"maxRotation",state.rotation);
  if(state.font&&state.tickSize!==null)state.font.size=state.tickSize;
  if(state.legendLabels){
   restore(state.legendLabels,"boxWidth",state.legendBoxWidth);
   if(state.legendFont&&state.legendFontSize!==null)
    state.legendFont.size=state.legendFontSize;
  }
 }
}
const plugin={id:CHART_ID,beforeUpdate(chart){adjustChart(chart)}};
function bindCharts(){
 const C=window.Chart;
 if(!C||typeof C.register!=="function")return false;
 if(C===chartCtor)return true;
 chartCtor=C;
 C.register(plugin);
 // Existing charts (for pages where Chart.js initialized before the shared script)
 // also get a responsive update; never recreate the scientific datasets.
 refreshCharts();
 return true;
}
function refreshCharts(){
 const ctor=window.Chart;
 if(!ctor||!ctor.instances)return;
 const instances=Object.values(ctor.instances);
 for(const chart of instances){
  if(!chart||typeof chart.update!=="function")continue;
  try{chart.update("none")}catch(err){console.info("Mobile chart view:",err)}
 }
}
function showScrollHints(){
 if(!match(MOBILE_WIDE))return;
 const selectors=[
  ".table-scroll",".table-wrap",".current-table-wrap",
  ".regional-ranking-table-wrap",".strato-trend-table-scroll",
  ".strato-heat-scroll",".strato-diagnostic-table",
  ".profile-table-scroll",".profile-daily-table",
  ".station-precip-monthly-wrap",".current-ranking-table-wrap",
  ".sg-panel .sg-grid"
 ];
 for(const node of document.querySelectorAll(selectors.join(","))){
  if(node.closest(".cdm-overlay"))continue;
  // Hidden panels have zero width; don't add incorrect "scroll" hints to them.
  if(node.clientWidth<=0||node.scrollWidth<=node.clientWidth+8)continue;
  if(node.dataset.cdmScrollHint==="1")continue;
  node.dataset.cdmScrollHint="1";
  node.setAttribute("role",node.getAttribute("role")||"region");
  if(!node.hasAttribute("tabindex"))node.tabIndex=0;
  if(!node.hasAttribute("aria-label"))node.setAttribute("aria-label","Breite Tabelle, horizontal scrollbar");
  const hint=document.createElement("p");
  hint.className="cdm-scroll-hint";
  hint.textContent="↔ Seitlich wischen, um weitere Spalten zu sehen";
  node.insertAdjacentElement("beforebegin",hint);
 }
}
function scheduleRefresh(){
 if(resizePending)return;
 resizePending=true;
 const task=()=>{
  resizePending=false;
  refreshCharts();
  showScrollHints();
 };
 if(typeof window.requestAnimationFrame==="function")window.requestAnimationFrame(task);
 else window.setTimeout(task,70);
}
function init(){
 bindCharts();
 showScrollHints();
 window.addEventListener("resize",scheduleRefresh,{passive:true});
 window.addEventListener("orientationchange",scheduleRefresh,{passive:true});
 // Maps and hidden dashboard tabs are created lazily; an explicit tab event
 // is safer than a whole-document MutationObserver on very large dashboards.
 document.addEventListener("click",event=>{
  const item=event.target?.closest?.(".tab-button,.nav-dropdown-toggle,.cdm-item,.mobile-tab-navigation");
  if(item)window.setTimeout(scheduleRefresh,200);
 },{passive:true});
 if(document.readyState!=="complete")
  window.addEventListener("load",()=>{bindCharts();scheduleRefresh()},{once:true});
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
})();
