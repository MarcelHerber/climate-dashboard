import assert from "node:assert/strict";
import {readFileSync,statSync,readFileSync as readFile} from "node:fs";
import {chromium} from "playwright";

const source=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
const start=source.indexOf("  function setMeteogramExportReady(");
const end=source.indexOf("  async function loadStationDetail(",start);
assert.ok(start>0&&end>start);
const code=source.slice(start,end);
const scripts={
 chartjs:"node_modules/chart.js/dist/chart.umd.js",
 jspdf:"node_modules/jspdf/dist/jspdf.umd.min.js"
};
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const vp of [{name:"desktop",width:1440,height:900},{name:"mobile",width:390,height:844}]){
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
    '<button id="single-temp-png">Nur Temperatur PNG</button>'+
    '<button id="single-rain-pdf">Nur Regen PDF</button>'+
    '<button id="single-temp-svg">Nur Temperatur SVG</button>'+
    '<button id="all-png">Alle PNG</button>'+
    keys.flatMap(key=>formats.map(format=>
      '<button id="single-'+key+'-'+format+'">'+key+' '+format.toUpperCase()+'</button>'
    )).join("")+
    '</body></html>';
  await page.setContent(html);
  await page.addScriptTag({path:scripts.chartjs});
  await page.addScriptTag({path:scripts.jspdf});
  await page.addScriptTag({path:"mosmix_vector_export.js"});
  await page.evaluate(code=>{
    const ids=["mosmixTempChart","mosmixRainChart","mosmixWindChart","mosmixPressureChart","mosmixSunChart","mosmixSunDailyChart"];
    const charts=ids.map((id,i)=>{
      const dates=Array.from({length:72},(_,j)=>"2026-11-"+String(11+Math.floor(j/24)).padStart(2,"0")+" "+(j%24)+" h");
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
      const chart=new Chart(document.getElementById(id),config);
      chart.options.scales.x.min=6;
      chart.options.scales.x.max=54;
      chart.update("none");
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
    document.getElementById("single-temp-png").addEventListener("click",()=>api.downloadMeteogram("png","temp"));
    document.getElementById("single-rain-pdf").addEventListener("click",()=>api.downloadMeteogram("pdf","rain"));
    document.getElementById("single-temp-svg").addEventListener("click",()=>api.downloadMeteogram("svg","temp"));
    document.getElementById("all-png").addEventListener("click",()=>api.downloadMeteogram("png"));
    for(const key of ["temp","rain","wind","pressure","sun","sunDaily"]){
      for(const format of ["png","pdf","svg"]){
        document.getElementById("single-"+key+"-"+format)
          .addEventListener("click",()=>api.downloadMeteogram(format,key));
      }
    }
  },code);
  // Every chart gets its own PNG, vector PDF and layered SVG, on both viewports.
  for(const key of keys)for(const format of formats){
    const suffix="_"+key+"."+format;
    const [download]=await Promise.all([
      page.waitForEvent("download",{timeout:55000}),
      page.locator("#single-"+key+"-"+format).click()
    ]);
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
    }else assert.deepEqual([...readFile(path).subarray(0,8)],[137,80,78,71,13,10,26,10]);
    console.log("MOSMIX SINGLE EXPORT",vp.name,key,format,statSync(path).size,"bytes");
  }
  const [all]=await Promise.all([
    page.waitForEvent("download",{timeout:60000}),
    page.locator("#all-png").click()
  ]);
  assert.ok(all.suggestedFilename().endsWith(".png"));
  const allPath="/tmp/mosmix-real-"+vp.name+"-all-meteograms.png";
  await all.saveAs(allPath);
  assert.ok(statSync(allPath).size>8000);
  assert.deepEqual(errors,[],"Browser JS errors "+errors.join(";"));
  await context.close();
 }
}finally{await browser.close()}
console.log("PASS: 6 charts × PNG, vector PDF, layered SVG on desktop and mobile");
