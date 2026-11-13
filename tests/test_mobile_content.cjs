const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const SOURCE=fs.readFileSync("mobile_content.js","utf8");
const CSS=fs.readFileSync("mobile_content.css","utf8");

function harness(withChart=true){
 const listeners={},windowListeners={},added=[];
 let narrow=true;
 let hintsCreated=0;
 const scrollNode={
  dataset:{},clientWidth:320,scrollWidth:690,attrs:{},added:[],
  closest(){return null},
  getAttribute(k){return this.attrs[k]??null},
  hasAttribute(k){return Object.hasOwn(this.attrs,k)},
  setAttribute(k,v){this.attrs[k]=v},
  insertAdjacentElement(where,node){assert.equal(where,"beforebegin");this.added.push(node)}
 };
 const doc={
  readyState:"loading",
  addEventListener(type,callback){listeners[type]=callback},
  querySelectorAll(){return [scrollNode]},
  createElement(tag){hintsCreated++;return {tag,className:"",textContent:""}}
 };
 const plugins=[];
 const chart={
  options:{
   scales:{x:{type:"category",min:0,max:16,ticks:{maxTicksLimit:13,maxRotation:50,
      autoSkip:true,font:{size:14},callback:function(value){return "Day "+value}}},
      y:{min:-50,max:80,ticks:{maxTicksLimit:17,callback:value=>value+" m/s"}}},
   plugins:{legend:{display:true,labels:{boxWidth:20,font:{size:14},filter:()=>true}}}
  },
  data:{labels:["a","b","c"],datasets:[{data:[3,5,-1]}]},
  calls:0,
  update(){this.calls++;for(const p of plugins)p.beforeUpdate(this)}
 };
 const window={
  Chart:withChart?{register(p){plugins.push(p)},instances:{"1":chart}}:null,
  matchMedia(query){return {matches:query.includes("430")?narrow:true}},
  addEventListener(type,fn){windowListeners[type]=fn},
  requestAnimationFrame(fn){fn()},
  setTimeout(fn){fn()}
 };
 vm.runInNewContext(SOURCE,{window,document:doc,WeakMap,console:{info(){}},
   Number,Object,Array,Math}, {timeout:2000});
 listeners.DOMContentLoaded();
 return {chart,scrollNode,plugins,windowListeners,doc,
   installChart(){window.Chart={register(p){plugins.push(p)},instances:{"1":chart}};},
   loadDynamicChartScript(){listeners.load({target:{tagName:"SCRIPT"}})},
   get narrow(){return narrow},setNarrow(value){narrow=value},get hintsCreated(){return hintsCreated}};
}

test("mobile axes cap tick count but retain scientific values and units",()=>{
 const h=harness(),x=h.chart.options.scales.x,y=h.chart.options.scales.y;
 assert.equal(x.ticks.maxTicksLimit,5);
 assert.equal(x.ticks.maxRotation,0);
 assert.equal(x.ticks.font.size,11);
 assert.equal(y.min,-50);
 assert.equal(y.max,80);
 assert.equal(y.ticks.maxTicksLimit,17);
 assert.equal(y.ticks.callback(-5),"-5 m/s");
 assert.equal(x.ticks.callback(2),"Day 2");
 assert.deepEqual(h.chart.data.datasets[0].data,[3,5,-1]);
 assert.equal(h.chart.options.plugins.legend.labels.boxWidth,12);
 assert.equal(h.chart.options.plugins.legend.labels.font.size,11);
 assert.equal(typeof h.chart.options.plugins.legend.labels.filter,"function");
});
test("rotation to desktop width restores original ticks and legend values",()=>{
 const h=harness();
 h.setNarrow(false);
 h.windowListeners.resize();
 const x=h.chart.options.scales.x;
 assert.equal(x.ticks.maxTicksLimit,13);
 assert.equal(x.ticks.maxRotation,50);
 assert.equal(x.ticks.font.size,14);
 assert.equal(h.chart.options.plugins.legend.labels.boxWidth,20);
 assert.equal(h.chart.options.plugins.legend.labels.font.size,14);
 assert.equal(h.plugins.length,1);
});
test("never override explicitly unsuppressed labels or hidden axis",()=>{
 const h=harness();
 const chart={options:{scales:{x:{ticks:{autoSkip:false,maxTicksLimit:25,maxRotation:90}}},
   plugins:{legend:{display:false}}}};
 h.plugins[0].beforeUpdate(chart);
 assert.equal(chart.options.scales.x.ticks.maxTicksLimit,25);
 assert.equal(chart.options.scales.x.ticks.maxRotation,90);
 chart.options.scales.x.ticks.display=false;
 h.plugins[0].beforeUpdate(chart);
 assert.equal(chart.options.scales.x.ticks.maxTicksLimit,25);
});
test("Chart.js loaded after DOMContentLoaded gets mobile scaling via script-load event",()=>{
 const h=harness(false);
 assert.equal(h.plugins.length,0);
 h.installChart();
 h.loadDynamicChartScript();
 assert.equal(h.plugins.length,1);
 assert.equal(h.chart.options.scales.x.ticks.maxTicksLimit,5);
 assert.equal(h.chart.calls>0,true);
 // Additional dynamically loaded libraries must not register the plugin twice.
 h.loadDynamicChartScript();
 assert.equal(h.plugins.length,1);
});
test("scroll hint added once to wide table and is keyboard accessible",()=>{
 const h=harness(),n=h.scrollNode;
 assert.equal(n.dataset.cdmScrollHint,"1");
 assert.equal(n.attrs.role,"region");
 assert.equal(n.attrs["aria-label"],"Breite Tabelle, horizontal scrollbar");
 assert.equal(n.tabIndex,0);
 assert.equal(n.added.length,1);
 assert.match(n.added[0].textContent,/Seitlich wischen/);
 h.windowListeners.resize();
 assert.equal(n.added.length,1);
});
test("no chart values or export pipelines overwritten, breakpoints are scoped",()=>{
 assert.ok(SOURCE.includes("beforeUpdate(chart)"));
 assert.doesNotMatch(SOURCE,/\.data\.datasets\s*=/);
 assert.doesNotMatch(SOURCE,/\.data\.labels\s*=/);
 assert.ok(CSS.includes("@media(max-width:430px)"));
 assert.ok(CSS.includes("@media(max-width:360px)"));
 assert.ok(CSS.includes(".strato-heat-scroll"));
 assert.ok(CSS.includes(".t850-export"));
 assert.ok(CSS.includes("font-size:max(16px,1em)"));
});

test("Phase 2: mobile chart arrow navigation, visible tooltip and touch hint are idempotent",()=>{
 const h=harness(),plugin=h.plugins[0],events={},nodes={},host={inserted:[]};
 host.insertAdjacentElement=(where,node)=>{
  assert.equal(where,"afterend");host.inserted.push(node);nodes[node.id]=node;
 };
 h.doc.getElementById=id=>nodes[id]||null;
 const attrs={};
 const canvas={
  id:"stratoPanelChart",parentElement:host,tabIndex:-1,
  closest(){return host},
  addEventListener(name,callback){events[name]=callback},
  hasAttribute(name){return Object.hasOwn(attrs,name)},
  getAttribute(name){return attrs[name]??null},
  setAttribute(name,value){attrs[name]=value}
 };
 const labels=Array.from({length:10},(_,i)=>"Day "+i);
 const data0=[null,...Array(9).fill(null)];
 const data1=[...Array(9).fill(3),9];
 const instances=[];
 const chart={
  canvas,config:{type:"line"},
  data:{labels,datasets:[{data:data0},{data:data1}]},
  isDatasetVisible(i){return i!==0},
  getDatasetMeta(){return {data:labels.map((_,i)=>({tooltipPosition:()=>({x:i,y:10})}))}},
  setActiveElements(elements){this.selected=elements},
  tooltip:{setActiveElements(elements,position){instances.push({elements,position})}},
  update(){this.updateCalls=(this.updateCalls||0)+1}
 };
 plugin.afterUpdate(chart);
 assert.equal(canvas.tabIndex,0);
 assert.equal(host.inserted.length,1);
 assert.match(host.inserted[0].textContent,/Diagramm antippen/);
 assert.match(attrs["aria-describedby"],/cdm-chart-tip-stratoPanelChart/);
 plugin.afterUpdate(chart);
 assert.equal(host.inserted.length,1,"No duplicate hint on repeated updates");
 let prevented=0;
 events.keydown({key:"ArrowLeft",preventDefault(){prevented++}});
 assert.equal(chart.selected[0].index,9,"First left arrow selects latest point");
 events.keydown({key:"ArrowRight",preventDefault(){prevented++}});
 assert.equal(chart.selected[0].index,0,"Wraps across the first point");
 events.keydown({key:"Escape",preventDefault(){prevented++}});
 assert.equal(chart.selected.length,0);
 assert.equal(prevented,3);
 assert.equal(instances.length,3);
 assert.equal(data0[0],null);
 assert.equal(data1[9],9);
 assert.match(CSS,/cdm-chart-touch-hint/);
 assert.match(CSS,/chart-export-tools/);
});

test("Phase 2: chart-specific month-year keyboard shortcuts are not rebound",()=>{
 const h=harness(),plugin=h.plugins[0];
 const canvas={id:"monthlyChart",addEventListener(){throw Error("Double-binding would change existing navigation")}};
 plugin.afterUpdate({canvas,data:{labels:Array(15).fill("x"),datasets:[{data:Array(15).fill(1)}]},$climateKeyboardBound:true});
});

test("Phase 2: keyboard skips timestamped points with missing Y observations",()=>{
 const h=harness(),events={};
 const canvas={
  id:"missingYChart",parentElement:{insertAdjacentElement(){}},
  closest(){return null},
  addEventListener(type,fn){events[type]=fn},
  hasAttribute(){return false},
  getAttribute(){return null},
  setAttribute(){}
 };
 const chart={
  canvas,config:{type:"line"},
  data:{labels:Array.from({length:9},(_,i)=>"T"+i),datasets:[{
   data:[{x:0,y:null},{x:1,y:4},...Array.from({length:7},(_,i)=>({x:i+2,y:undefined}))]
  }]},
  isDatasetVisible(){return true},
  getDatasetMeta(){return {data:Array.from({length:9},(_,i)=>({tooltipPosition:()=>({x:i,y:0})}))}},
  setActiveElements(points){this.selected=points},
  tooltip:{setActiveElements(){}},update(){}
 };
 h.plugins[0].afterUpdate(chart);
 let prevented=0;
 events.keydown({key:"ArrowRight",preventDefault(){prevented++}});
 assert.equal(chart.selected[0].index,1,"Timestamp-only points must not be selected");
 assert.equal(prevented,1);
});
