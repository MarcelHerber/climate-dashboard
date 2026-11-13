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
// Phase 2: keyboard selection and a one-time touch hint for the other
// scientific Chart.js diagrams. Values, visibility, zoom, color scales and
// export rendering are intentionally not changed.
const enhanced=new WeakSet();
function chartPoint(chart,index){
 const sets=chart.data?.datasets||[];
 for(let datasetIndex=0;datasetIndex<sets.length;datasetIndex++){
  if(chart.isDatasetVisible?.(datasetIndex)===false)continue;
  const value=sets[datasetIndex]?.data?.[index];
  if(value===null||value===undefined)continue;
  if(typeof value==="number"&&!Number.isFinite(value))continue;
  // For {x, y} time series, x is only the timestamp: a missing y is not
  // an observed value and must not receive a keyboard tooltip.
  if(typeof value==="object"&&value!==null){
   if(Object.hasOwn(value,"y")&&(value.y==null||!Number.isFinite(Number(value.y))))continue;
   if(!Object.values(value).some(v=>typeof v==="number"&&Number.isFinite(v)))continue;
  }
  return {datasetIndex,index};
 }
 return null;
}
function touchHint(chart){
 if(!match(MOBILE_WIDE)||!chart.canvas?.id||!document.getElementById)return;
 const container=chart.canvas.closest?.(".chart-container,.chart-box,.t850-chart-shell,.strato-diagnostic-chart,.strato-trend-chart,.mosmix-chart-wrap")
   ||chart.canvas.parentElement;
 if(!container?.insertAdjacentElement)return;
 const id="cdm-chart-tip-"+chart.canvas.id;
 if(document.getElementById(id))return;
 const hint=document.createElement("p");
 hint.id=id;
 hint.className="cdm-chart-touch-hint";
 hint.textContent="Diagramm antippen: Werte anzeigen. Mit ← und → durch Termine wechseln.";
 container.insertAdjacentElement("afterend",hint);
 const old=chart.canvas.getAttribute?.("aria-describedby")||"";
 chart.canvas.setAttribute?.("aria-describedby",(old+" "+id).trim());
}
function improveChartInteraction(chart){
 if(!match(MOBILE_WIDE)||!chart?.canvas||enhanced.has(chart))return;
 const canvas=chart.canvas;
 // The Gebietsmittel already has a dedicated year/tooltip keyboard handler.
 if(chart.$climateKeyboardBound||/^(monthlyChart|monthlyDeviationChart)$/.test(canvas.id||""))return;
 if(!canvas.addEventListener||!chart.data?.datasets?.length||!chart.data.labels?.length)return;
 if(chart.data.labels.length<8||/^(pie|doughnut|polarArea)$/.test(chart.config?.type||""))return;
 enhanced.add(chart);
 if(!canvas.hasAttribute?.("tabindex"))canvas.tabIndex=0;
 if(!canvas.hasAttribute?.("aria-label"))
  canvas.setAttribute?.("aria-label","Meteorologisches Diagramm. Pfeiltasten wählen Datenpunkte, Escape beendet die Auswahl.");
 let active=-1;
 const select=index=>{
  active=index;
  const point=index<0?null:chartPoint(chart,index);
  const elements=point?[point]:[];
  chart.setActiveElements?.(elements);
  let position={x:0,y:0};
  if(point)position=chart.getDatasetMeta?.(point.datasetIndex)?.data?.[index]?.tooltipPosition?.()||position;
  chart.tooltip?.setActiveElements?.(elements,position);
  chart.update?.("none");
 };
 canvas.addEventListener("keydown",event=>{
  if(event.key==="Escape"&&active>=0){
   event.preventDefault();select(-1);return;
  }
  if(event.key!=="ArrowRight"&&event.key!=="ArrowLeft")return;
  const length=chart.data?.labels?.length||0;
  if(!length)return;
  const delta=event.key==="ArrowRight"?1:-1;
  for(let step=0;step<length;step++){
   const start=active<0?(delta===1?-1:0):active;
   const index=((start+delta*(step+1))%length+length)%length;
   if(chartPoint(chart,index)){
    event.preventDefault();select(index);return;
   }
  }
 });
 canvas.addEventListener("blur",()=>{if(active>=0)select(-1);});
 touchHint(chart);
}
const plugin={
 id:CHART_ID,
 beforeUpdate(chart){adjustChart(chart)},
 afterUpdate(chart){improveChartInteraction(chart)}
};
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
 // MOSMIX loads Chart.js only after a user selects a station. The ordinary
 // page load event has already fired by then, so listen for the actual
 // dynamically added chart-library <script> load and register the
 // mobile-only tick/legend plugin before the first meteogram is created.
 document.addEventListener("load",event=>{
  if(event.target?.tagName==="SCRIPT"&&window.Chart&&chartCtor!==window.Chart){
   bindCharts();
   scheduleRefresh();
  }
 },true);
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
