import assert from "node:assert/strict";
import {readFileSync,statSync,readFileSync as readFile} from "node:fs";
import {chromium} from "playwright";

const source=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
const start=source.indexOf("  function setMeteogramExportReady(");
const end=source.indexOf("  async function loadStationDetail(",start);
assert.ok(start>0&&end>start);
const code=source.slice(start,end);
const labelPluginSource=source.slice(source.indexOf('  const mosmixSunDayLabelPlugin='),source.indexOf('  let mosmixMidnightPluginRegistered='));
const scripts={
 chartjs:"node_modules/chart.js/dist/chart.umd.js",
 jspdf:"node_modules/jspdf/dist/jspdf.umd.min.js"
};
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const vp of [{name:"desktop",width:1440,height:900},{name:"mobile",width:390,height:844}]){
  // Chromium may block automatic downloads after ~10 files from one page.
  // Reset the browser context for each chart; the real user downloads one at a time.
  for(const selectedKey of ["temp","rain","wind","pressure","sun","sunDaily","all"]){
  const context=await browser.newContext({viewport:vp,acceptDownloads:true});
  const page=await context.newPage();
  const errors=[];
  page.on("pageerror",error=>errors.push(error.message));
  const ids=["mosmixTempChart","mosmixRainChart","mosmixWindChart","mosmixPressureChart","mosmixSunChart","mosmixSunDailyChart"];
  const keys=["temp","rain","wind","pressure","sun","sunDaily"];
  const formats=["png","pdf","svg"];
  const html='<!doctype html><html lang="de"><meta charset="utf-8">'+
    '<style>body{font:14px system-ui;background:#fff}canvas{display:block;max-width:100%}</style>'+
    '<body><h1>MOSMIX PNG/PDF Echtexport-Test</h1>'+
    '<select id="mosmixDiagramRange"><option value="all">Alle Tage</option><option value="72" selected>Ab jetzt · 3 Tage</option></select>'+
    '<div id="mosmixExportStatus"></div>'+
    ids.map(id=>'<canvas id="'+id+'" width="720" height="300"></canvas>').join("")+



    '<button id="all-png">Alle PNG</button>'+
    keys.flatMap(key=>formats.map(format=>
      '<button id="single-'+key+'-'+format+'">'+key+' '+format.toUpperCase()+'</button>'
    )).join("")+
    '</body></html>';
  await page.setContent(html);
  await page.addScriptTag({path:scripts.chartjs});
  await page.addScriptTag({path:scripts.jspdf});
  await page.addScriptTag({path:"mosmix_vector_export.js"});
  await page.evaluate(({code,labelPluginSource})=>{
    Chart.register(new Function(labelPluginSource+'\nreturn mosmixSunDayLabelPlugin;')());
    const ids=["mosmixTempChart","mosmixRainChart","mosmixWindChart","mosmixPressureChart","mosmixSunChart","mosmixSunDailyChart"];
    const charts=ids.map((id,i)=>{
      const dates=Array.from({length:i===5?4:72},(_,j)=>"2026-11-"+String(11+Math.floor(j/24)).padStart(2,"0")+" "+(j%24)+" h");
      const d1=dates.map((_,j)=>8+Math.sin(j/5)*3+i*2);
      const d2=dates.map((_,j)=>5+Math.cos(j/7)*2+i);
      const config={
        type:i===1?undefined:(i===5?"bar":"line"),
        data:{labels:dates,datasets:[
          {type:i===1||i===5?"bar":"line",label:i===0?"Temperatur":"Messwert",
           data:d1,borderColor:"#c62828",backgroundColor:"rgba(44,120,190,.65)",pointRadius:0},
          {type:"line",label:"Vergleichsstation",data:d2,
           borderColor:"#2563eb",pointRadius:0,borderDash:[5,4]}
        ]},
        options:{responsive:false,maintainAspectRatio:false,animation:false,
          scales:{x:{min:0,max:71,ticks:{maxTicksLimit:12}},
                  y:{title:{display:true,text:i===0?"°C":"Messwert"}}},
          plugins:{legend:{display:true}}
        }
      };
      if(i===0){
        const tx=dates.map((_,j)=>j===20?16.7:null),tn=dates.map((_,j)=>j===32?-1.2:null);
        config.data.datasets.push({label:'TX 12 h',data:tx,mosmixExtreme:'TX',showLine:false,pointStyle:'triangle',borderColor:'#a5271f'},
          {label:'TN 12 h',data:tn,mosmixExtreme:'TN',showLine:false,pointStyle:'rectRot',borderColor:'#1f5f99'});
      }
      if(i===4||i===5){
        config.data.datasets[0].mosmixSunLabels=[{dayIndex:1,index:35.5,start:24,end:47,hours:1.7,possibleHours:9.1,percent:19,text:'1,7 / 9,1 h (19 %)',lines:['1,7 / 9,1 h','(19 %)'],narrowLines:['1,7 h','/ 9,1 h','(19 %)']}];
        config.data.datasets[0].mosmixSunDaily=i===5;
      }
      if(i===2)config.data.datasets[1].mosmixWindLabels=[{dayIndex:1,index:35.5,start:24,end:47,value:74,source:'FXh',text:'74 km/h',lines:['74 km/h'],narrowLines:['74','km/h']}];
      if(i===5)config.options.scales.x.max=3;
      const chart=new Chart(document.getElementById(id),config);
      chart.options.scales.x.min=i===5?0:6;
      chart.options.scales.x.max=i===5?3:54;
      const drawn=[];
      if(i===0||i===2||i===4||i===5){
        const original=chart.ctx.fillText;
        chart.ctx.fillText=function(text,...args){drawn.push(String(text));return original.call(this,text,...args);};
      }
      chart.update("none");
      if(i===0&&(!drawn.some(s=>s.includes('16,7'))||!drawn.some(s=>s.includes('-1,2'))))throw Error('Missing native TX/TN labels in '+id);
      if((i===4||i===5)&&!drawn.some(s=>s.includes('19 %')))throw Error('Missing daily sunshine label in '+id);
      if(i===2&&!drawn.some(s=>s.includes('74')))throw Error('Missing daily maximum gust label in '+id);
      return chart;
    });
    const dependencies={
      document,window,meteogramCharts:charts,currentDetail:{parameters:{TTT:[8]}},
      data:{issue_time:"2026-11-11T12:00:00Z",stations:[],
        timesteps:Array.from({length:72},(_,j)=>new Date(Date.parse("2026-11-11T12:00:00Z")+3600000*j).toISOString())},
      selectedStation:{name:"Frankfurt am Main"},selectedStationKey:"FFM",
      rainPeriod:3,gustPeriod:12,
      fmtTime:date=>"11.11.2026 12 UTC",
      ensurePdfLibrary:async()=>{},ensureVectorExport:async()=>{}
    };
    const make=new Function(...Object.keys(dependencies),code+
      "\nreturn {downloadMeteogram,meteogramExportSections};");
    const api=make(...Object.values(dependencies));
    window.mosmixExportTest=api;
    // Observe actual offscreen rendering, not just the on-screen chart.
    window.mosmixPngLabels=[];
    const fillText=CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText=function(text,...args){
      if(this.canvas.width>=1540)window.mosmixPngLabels.push(String(text));
      return fillText.call(this,text,...args);
    };



    document.getElementById("all-png").addEventListener("click",()=>api.downloadMeteogram("png"));
    for(const key of ["temp","rain","wind","pressure","sun","sunDaily"]){
      for(const format of ["png","pdf","svg"]){
        document.getElementById("single-"+key+"-"+format)
          .addEventListener("click",()=>api.downloadMeteogram(format,key));
      }
    }
  },{code,labelPluginSource});
  // Every chart gets its own PNG, vector PDF and layered SVG, on both viewports.
  for(const key of selectedKey==="all"?[]:[selectedKey])for(const format of formats){
    const suffix="_"+key+"."+format;
    let download;
    try{
      [download]=await Promise.all([
        page.waitForEvent("download",{timeout:14000}),
        page.locator("#single-"+key+"-"+format).click()
      ]);
    }catch(error){
      const status=await page.locator("#mosmixExportStatus").textContent().catch(()=>"?");
      throw new Error("MOSMIX "+vp.name+" "+key+" "+format+" export failed: "+
        status+"; browser errors: "+JSON.stringify(errors)+"; "+error.message);
    }
    const filename=download.suggestedFilename();
    assert.ok(filename.endsWith(suffix),filename+" wrong suffix "+suffix);
    const path="/tmp/mosmix-real-"+vp.name+"-"+key+"."+format;
    await download.saveAs(path);
    assert.ok(statSync(path).size>(format==="png"?8000:1500),"Export output empty: "+path);
    if(format==="pdf")assert.equal(readFile(path).subarray(0,5).toString(),"%PDF-");
    else if(format==="svg"){
      const svg=readFile(path,"utf8");
      assert.match(svg,/<svg\b/);
      assert.match(svg,/inkscape:label=/);
      assert.doesNotMatch(svg,/<image\b/);
      if(key==='sun'||key==='sunDaily')assert.match(svg,/19 %/);
      if(key==='wind')assert.match(svg,/74 km\/h/);
      if(key==='temp'){assert.match(svg,/TX 16,7 °C/);assert.match(svg,/TN -1,2 °C/);}
    }else assert.deepEqual([...readFile(path).subarray(0,8)],[137,80,78,71,13,10,26,10]);
    if(key==='temp'&&format==='png'){
      const text=await page.evaluate(()=>window.mosmixPngLabels);
      assert.ok(text.includes('TX 16,7 °C')&&text.includes('TN -1,2 °C'),'Missing TX/TN in high-resolution PNG');
    }
    console.log("MOSMIX SINGLE EXPORT",vp.name,key,format,statSync(path).size,"bytes");
  }
  if(selectedKey==="all"){
  const [all]=await Promise.all([
    page.waitForEvent("download",{timeout:60000}),
    page.locator("#all-png").click()
  ]);
  assert.ok(all.suggestedFilename().endsWith(".png"));
  const allPath="/tmp/mosmix-real-"+vp.name+"-all-meteograms.png";
  await all.saveAs(allPath);
  assert.ok(statSync(allPath).size>8000);
  }
  assert.deepEqual(errors,[],"Browser JS errors "+errors.join(";"));
  await context.close();
  }
 }
}finally{await browser.close()}
console.log("PASS: 6 charts × PNG, vector PDF, layered SVG on desktop and mobile");
