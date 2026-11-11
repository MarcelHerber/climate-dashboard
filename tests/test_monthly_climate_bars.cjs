/* Exact-chart regression tests for Climate Bars 2.0. */
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const source=fs.readFileSync("monthly_climate_bars.js","utf8");
const css=fs.readFileSync("dashboard_cleanup.css","utf8");
const html=fs.readFileSync("index.html","utf8");
const builder=fs.readFileSync("scripts/build_pages_site.sh","utf8");

function pluginInstance(){
  let plugin=null;
  const document={readyState:"loading",documentElement:{dataset:{theme:"light"}},
    getElementById(id){return id==="paramSelect"?{value:"temp"}:{id};}};
  const Chart={register(x){plugin=x;},getChart(){return null;}};
  vm.runInNewContext(source,{window:{Chart},document,console});
  assert.ok(plugin);
  return {plugin,document};
}
function chart(id,values){
  return {
    canvas:{id,addEventListener(){}},
    data:{labels:values.map((_,i)=>""+(1990+i)),datasets:[
      {type:"bar",data:values.slice(),label:"Temperatur"},
      ...(id==="monthlyChart"?[{type:"line",label:"Mittel 1991–2020",data:values.map(()=>10)}]:[])
    ]},
    width:650,chartArea:{left:30,right:590,top:15,bottom:280,width:560},
    options:{plugins:{title:{}},scales:{x:{ticks:{},grid:{}},y:{ticks:{},grid:{},title:{}}}},
    update(){this.updateCalls=(this.updateCalls||0)+1;},
    scales:{y:{min:-3,max:3,getPixelForValue(){return 170;}}},
    ctx:{save(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},restore(){}}
  };
}
test("temperature climate red/blue and chart data/orientation untouched",()=>{
  const {plugin}=pluginInstance();
  const main=chart("monthlyChart",[8,12]);
  plugin.beforeUpdate(main);
  assert.equal(main.$climateBarsStyled,true);
  assert.equal(main.options.indexAxis,undefined);
  assert.equal(main.data.datasets[0].borderRadius,6);
  assert.equal(main.data.datasets[0].borderSkipped,false);
  assert.deepEqual(Array.from(main.data.datasets[0].data),[8,12]);
  assert.deepEqual(Array.from(main.data.datasets[1].data),[10,10]);
  assert.match(main.data.datasets[0].backgroundColor[0],/39,103,190/);
  assert.match(main.data.datasets[0].backgroundColor[1],/199,62,69/);
  const other=chart("dailyChart",[8,12]);
  plugin.beforeUpdate(other);
  assert.equal(other.$climateBarsStyled,undefined);
});
test("positive negative missing values and hover dimming",()=>{
  const {plugin,document}=pluginInstance();
  const dev=chart("monthlyDeviationChart",[-2,1,null]);
  plugin.beforeUpdate(dev);
  assert.match(dev.data.datasets[0].backgroundColor[0],/39,103,190/);
  assert.match(dev.data.datasets[0].backgroundColor[1],/199,62,69/);
  assert.match(dev.data.datasets[0].backgroundColor[2],/129,145,163/);
  assert.equal(dev.options.plugins.datalabels.display({
    datasetIndex:0,dataIndex:2,dataset:dev.data.datasets[0],chart:dev
  }),false);
  dev.options.onHover({},[{datasetIndex:0,index:1}],dev);
  assert.equal(dev.$climateFocus,1);
  assert.ok(dev.updateCalls>0);
  plugin.beforeUpdate(dev);
  assert.match(dev.data.datasets[0].backgroundColor[0],/0\.220/);
  document.documentElement.dataset.theme="dark";
  plugin.beforeUpdate(dev);
  assert.equal(dev.options.scales.x.grid.display,false);
  assert.equal(dev.options.plugins.tooltip.enabled,true);
  assert.equal(dev.options.plugins.datalabels.color(),"#192d45");
  assert.doesNotThrow(()=>plugin.afterDraw(dev));
});
test("responsive styling and asset publication preserve original chart markup",()=>{
  assert.ok(css.includes("Climate Bars 2.0"));
  assert.ok(css.includes('html[data-theme="dark"] #monthly'));
  assert.ok(css.includes("@media(max-width:700px)"));
  assert.ok(html.includes('dashboard_cleanup.css?v=20261111-climatebars1'));
  assert.ok(html.includes('monthly_climate_bars.js?v=20261111-climatebars1'));
  assert.ok(builder.includes("  monthly_climate_bars.js\n"));
  assert.ok(html.includes('id="monthlyChart"'));
  assert.ok(html.includes('id="monthlyDeviationChart"'));
  assert.ok(!source.includes('indexAxis:"y"'));
  assert.doesNotThrow(()=>new Function(source));
});
