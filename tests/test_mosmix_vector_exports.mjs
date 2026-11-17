import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
const root=new URL("../",import.meta.url);
const main=readFileSync(new URL("mosmix.js",root),"utf8");
const html=readFileSync(new URL("mosmix.html",root),"utf8");
const vector=readFileSync(new URL("mosmix_vector_export.js",root),"utf8");
const build=readFileSync(new URL("scripts/build_pages_site.sh",root),"utf8");
new Function(main);new Function(vector);
assert.match(build,/^  mosmix_vector_export\.js$/m);
assert.match(main,/mosmix_vector_export\.js\?v=/);
assert.match(html,/mosmix\.js\?v=/);
for(const key of ["temp","rain","wind","pressure","sun","sunDaily"]){
 for(const format of ["png","pdf","svg"]){
  const pattern=new RegExp('data-mosmix-export-chart="'+key+'" data-mosmix-export-format="'+format+'"',"g");
  assert.equal((main.match(pattern)||[]).length,1,key+" "+format+" missing/duplicate");
 }
}
assert.match(main,/format === "svg" && onlyKey/);
const pdfSource=main.slice(main.indexOf("  function exportCombinedPdf()"),main.indexOf("  function singleMeteogramFilename"));
assert.doesNotMatch(pdfSource,/addImage\(/,"PDF output must not embed a bitmap");
const window={};
vm.runInNewContext(vector,{window,Date,Intl,Number,Math,Array,Map,String,Set,Error,RegExp});
const api=window.MosmixVectorExport;
assert.ok(api,"Vector renderer missing");
const start=Date.parse("2026-11-11T10:00:00Z");
const timesteps=Array.from({length:145},(_,i)=>new Date(start+i*3600000).toISOString());
function mockChart(hours,daily=false){
 const ys={min:-5,max:20,ticks:[{value:0},{value:10},{value:20}],options:{title:{text:"°C"},display:true}};
 const series=daily
   ? [{label:"Sonne",type:"bar",data:[3,5,8,0],backgroundColor:["#ff2","#fc0","#f90","#eee"]}]
   : [{label:"Temperatur",type:"line",borderColor:"#c62828",data:timesteps.map((_,i)=>4+Math.sin(i/8)*6)},
      {label:"Taupunkt",type:"line",borderColor:"#1769c2",data:timesteps.map((_,i)=>2+Math.sin(i/12)*3)},
      {label:"Vorlauf",type:"line",borderColor:"#999",data:timesteps.map(()=>4),hidden:true}];
 return {config:{type:daily?"bar":"line"},data:{labels:daily?["Mi","Do","Fr","Sa"]:timesteps,datasets:series},
  scales:{x:{min:0,max:hours},y:ys},isDatasetVisible:i=>!series[i].hidden};
}
const paths=[];
const pdf={internal:{pageSize:{getWidth:()=>297,getHeight:()=>210}},
 setFont(){},setFontSize(){},setTextColor(){},setDrawColor(){},setFillColor(){},setLineWidth(){},
 setLineDashPattern(){},line(){},rect(){},circle(){},text(){},path(c,s){paths.push({c,s})}};
for(const hours of [72,120]){
 const scene=api.buildScene(mockChart(hours),{key:"temp",title:"Temperatur",station:"Speyer",issue:"2026-11-11",range:hours+"h",timesteps});
 assert.equal(scene.axes.filter(x=>x.kind==="text"&&x.text==="00 Uhr").length,hours===72?3:5);
 assert.equal(scene.series.length,2,"hidden member exported");
 const svg=api.toSvg(scene);
 assert.match(svg,/inkscape:label="Temperatur"/);
 assert.match(svg,/inkscape:label="Taupunkt"/);
 assert.doesNotMatch(svg,/<image|data:image\/png/);
 paths.length=0;
 api.drawPdf(pdf,scene);
 assert.equal(paths.length,2,"PDF should contain two independent vector paths");
 assert.ok(paths.every(x=>x.c.length>40));
}
const scene=api.buildScene(mockChart(3,true),{key:"sunDaily",title:"Sonnenschein",station:"Speyer",issue:"2026-11-11",range:"all",timesteps});
assert.equal(scene.series[0].items.length,4);
assert.equal(new Set(scene.series[0].items.map(x=>JSON.stringify(x.fill))).size,4);
const sunLabel={dayIndex:0,index:11.5,start:0,end:23,hours:1.7,possibleHours:9.1,percent:19,text:'1,7 / 9,1 h (19 %)',lines:['1,7 / 9,1 h','(19 %)'],narrowLines:['1,7 h','/ 9,1 h','(19 %)']};
for(const key of ['sun','sunDaily']){
 const isDaily=key==='sunDaily',c=mockChart(isDaily?3:71,isDaily);
 c.data.datasets[0].mosmixSunLabels=[sunLabel];
 const s=api.buildScene(c,{key,timesteps});
 const svg=api.toSvg(s);
 assert.match(svg,/1,7 \/ 9,1 h/); assert.match(svg,/\(19 %\)/);
 assert.ok(s.series.some(x=>x.name==='Tagesbeschriftungen'),key+' editable labels');
 c.scales.x.min=1;
 assert.doesNotMatch(api.toSvg(api.buildScene(c,{key,timesteps})),/\(19 %\)/);
}
const oneDay=mockChart(0,true);
oneDay.data.datasets[0].mosmixSunLabels=[sunLabel];
assert.match(api.toSvg(api.buildScene(oneDay,{key:'sunDaily',timesteps})),/\(19 %\)/);
const wind=mockChart(71);
wind.data.datasets[1].mosmixWindLabels=[{...sunLabel,text:'74 km/h',lines:['74 km/h'],narrowLines:['74','km/h']}];
const windScene=api.buildScene(wind,{key:'wind',timesteps});
assert.match(api.toSvg(windScene),/74 km\/h/);
assert.ok(windScene.series.some(s=>s.name==='Tagesmaximalböen'));
wind.scales.x.min=24;
assert.doesNotMatch(api.toSvg(api.buildScene(wind,{key:'wind',timesteps})),/74 km\/h/);
console.log("PASS MOSMIX vector assets, SVG buttons and independent PDF paths.");
// Reproduce missing TX/TN labels without the optional ChartDataLabels plugin.
const extreme=mockChart(71);
function extremeSeries(kind,index,value){
 const data=Array(145).fill(null);data[index]=value;
 return {label:kind,mosmixExtreme:kind,showLine:false,pointStyle:kind==='TX'?'triangle':'rectRot',data,borderColor:kind==='TX'?'#a5271f':'#1f5f99'};
}
extreme.data.datasets.push(extremeSeries('TX',20,16.7),extremeSeries('TN',32,-1.2));
let rendered=api.toSvg(api.buildScene(extreme,{key:'temp',timesteps}));
assert.match(rendered,/TX 16,7 °C/);assert.match(rendered,/TN -1,2 °C/);
const textCalls=[];api.drawPdf({...pdf,text:t=>textCalls.push(t)},api.buildScene(extreme,{key:'temp',timesteps}));
assert.ok(textCalls.includes('TX 16,7 °C'));assert.ok(textCalls.includes('TN -1,2 °C'));
extreme.scales.x.min=21;extreme.data.datasets.at(-1).hidden=true;
rendered=api.toSvg(api.buildScene(extreme,{key:'temp',timesteps}));
assert.doesNotMatch(rendered,/TX 16,7 °C|TN -1,2 °C/);
const pluginSource=main.slice(main.indexOf('  const mosmixSunDayLabelPlugin='),main.indexOf('  let mosmixMidnightPluginRegistered='));
const plugin=new Function(pluginSource+'\nreturn mosmixSunDayLabelPlugin;')();
const seen=[];
const ctx={save(){},restore(){},fillRect(){},strokeRect(){},measureText:t=>({width:t.length*6}),fillText(t){seen.push(t);}};
const fake={data:{datasets:[extremeSeries('TX',20,16.7),extremeSeries('TN',32,-1.2)]},scales:{x:{min:0,max:71}},chartArea:{left:0,right:720,top:0,bottom:300},ctx,options:{},isDatasetVisible:()=>true,getDatasetMeta:i=>({data:Array.from({length:145},(_,j)=>({x:j*10,y:i?250:50,skip:false}))})};
plugin.afterDatasetsDraw(fake);
assert.deepEqual(seen,['TX 16,7 °C','TN -1,2 °C']);
seen.length=0;fake.scales.x.min=21;fake.isDatasetVisible=i=>i===0;plugin.afterDatasetsDraw(fake);assert.deepEqual(seen,[]);
