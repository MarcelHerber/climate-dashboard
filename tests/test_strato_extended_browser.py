"""Chromium viewport/download regression for all three extended stratosphere modules."""
from pathlib import Path
import re
from playwright.sync_api import sync_playwright

OUT=Path("strato-extended-browser")
OUT.mkdir(exist_ok=True)
PAGE=Path("stratosphaere.html").read_text(encoding="utf-8")
SECTIONS=[]
for element_id in ("stratoHistoryForecastPanel","stratoJointMetricsPanel","stratoVerticalPanel"):
    match=re.search(r"<section\b[^>]*\bid=\""+element_id+r"\"[^>]*>.*?</section>",PAGE,re.S)
    assert match, f"Missing new page section {element_id}"
    SECTIONS.append(match.group(0))
HTML="""<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><main><h2>Stratosphäre · Originaldaten und Modellvergleiche</h2>"""+\
    "\n".join(SECTIONS)+"""</main></body></html>"""
FAKE_DATA=r"""() => {
  const today=new Date().toISOString().slice(0,10);
  const move=(iso,n)=>{const d=new Date(iso+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+n);
    return d.toISOString().slice(0,10);};
  window.stratoNASAData.load=async(levels,from,to)=>{
    const content=new Map();
    for(const level of levels){
      const observations=new Map(),reference={};
      for(let i=-100;i<=32;i++){
        const date=move(today,i),mmdd=date.slice(5);
        reference[mmdd]={mean:20+level/8,p10:4+level/8,p90:38+level/8};
        if(i<=0)observations.set(date,28+level/10+i*.07);
      }
      content.set(level,{observations,reference,referenceLabel:'1991–2020'});
    }
    return content;
  };
  const make=(model,hour,cycleDayOffset=0)=>{
    const count=model==='gefs'?31:51;
    const members={};
    const steps=Array.from({length:16},(_,i)=>move(today,cycleDayOffset+i));
    for(let i=0;i<count;i++){
      const key=i===0?'c00':'p'+String(i).padStart(2,'0');
      members[key]=steps.map((_,lead)=>i%3===0?(lead>=4?-2:2):
        i%3===1?(lead>=9?-3:5):10);
    }
    return {provider:model==='gefs'?'NOAA GEFS':'ECMWF IFS ENS',
      latitude_deg:60,level_hpa:10,units:'m/s',
      cycle_utc:move(today,cycleDayOffset)+'T'+String(hour).padStart(2,'0')+':00:00Z',
      valid_dates:steps,members};
  };
  window.sendData=(hour=0)=>{
    const record={gefs:make('gefs',hour),eps:make('eps',hour),hour};
    window.stratoJointForecastData=record;
    window.dispatchEvent(new CustomEvent('stratosphere:joint-data-ready',{detail:record}));
  };
  window.fakeDownloads=[];
  HTMLAnchorElement.prototype.click=function(){
    window.fakeDownloads.push({name:this.download,uri:this.href});
  };
  window.fetch=async(url)=>{
    const isG=url.includes('/ensemble/'),model=isG?'gefs':'eps';
    if(url.includes('_index.json')){
      const cycle=move(today,-1)+'T00:00:00Z';
      return {ok:true,json:async()=>({provider:isG?'NOAA GEFS':'ECMWF IFS ENS',
        runs:[{cycle_utc:cycle,path:'runs/'+cycle.slice(0,10).replaceAll('-','')+'_000000.json'}]})};
    }
    if(url.includes('/runs/')){
      return {ok:true,json:async()=>make(model,0,-1)};
    }
    return {ok:false,status:404};
  };
  return true;
}"""

def exercise(browser,width,height):
    context=browser.new_context(viewport={"width":width,"height":height},device_scale_factor=1)
    page=context.new_page()
    try:
        page.set_content(HTML)
        page.add_style_tag(content="""
        :root{--card:#fff;--ink:#16253c;--line:#dce3eb;--muted:#536478}
        *{box-sizing:border-box}body{background:#f2f6fa;color:#16253c;margin:0;font:14px Arial,sans-serif}
        main{max-width:1600px;margin:auto;padding:12px}
        .chart{position:relative;min-width:0}
        .chart canvas{height:100%!important;width:100%!important}
        """)
        for path in ("stratosphere_chart_visibility.css","stratosphere_joint_comparison.css",
                     "stratosphere_analysis_forecast.css"):
            page.add_style_tag(path=path)
        page.add_script_tag(url="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js")
        page.add_script_tag(path="stratosphere_chart_visibility.js")
        page.add_script_tag(path="stratosphere_chart_export.js")
        page.add_script_tag(path="stratosphere_nasa_common.js")
        page.evaluate(FAKE_DATA)
        page.add_script_tag(path="stratosphere_joint_comparison.js")
        page.add_script_tag(path="stratosphere_analysis_forecast.js")
        page.add_script_tag(path="stratosphere_comparison_metrics.js")
        page.add_script_tag(path="stratosphere_vertical_profile.js")
        page.evaluate("sendData(0)")
        page.wait_for_function("""() =>
          !!Chart.getChart('stratoHistoryForecastCanvas') &&
          !!Chart.getChart('stratoMetricDiffChart') &&
          !!Chart.getChart('stratoVerticalLineChart') &&
          document.querySelector('#stratoVerticalTable tr')?.cells.length===4
        """,timeout=25000)
        assert page.locator("#stratoHistoryForecastPng").is_enabled()
        assert page.locator("#stratoHistoryForecastCsv").is_enabled()
        assert page.locator("#stratoMetricPng").is_enabled()
        assert page.locator("#stratoMetricCsv").is_enabled()
        assert page.locator("#stratoVerticalPng").is_enabled()
        assert page.locator("#stratoVerticalHeatPng").is_enabled()
        assert page.locator("#stratoVerticalTable tr").count()==5
        table_text=page.locator("#stratoVerticalTable tr").all_inner_texts()
        print("Vertical row diagnostics:",repr(table_text),flush=True)
        assert any("10 hPa" in text for text in table_text),table_text
        assert any("100 hPa" in text for text in table_text),table_text
        assert "10 hPa" in page.locator("#stratoVerticalStatus").inner_text()
        assert "12" not in page.locator("#stratoHistoryForecastStatus").inner_text().split("Modell")[0]
        mean=page.locator("#stratoMetricG7").inner_text()
        assert "%" in mean and "/" in mean,mean
        assert "%" in page.locator("#stratoMetricE15").inner_text()
        page.locator("#stratoHistoryForecastMode").select_option("anomaly")
        page.wait_for_function("""() => !!Chart.getChart('stratoHistoryForecastCanvas') &&
          Chart.getChart('stratoHistoryForecastCanvas').data.datasets[2].data.some(v=>v===0)""")
        page.locator("#stratoVerticalMode").select_option("anomaly")
        assert "Anomalien" in page.locator("#stratoVerticalStatus").inner_text()
        page.locator("#stratoMetricThreshold").select_option("5")
        assert "≥ 5 m/s" in page.locator("#stratoMetricDivergence").inner_text()
        for name in ("stratoHistoryForecastPng","stratoHistoryForecastCsv",
                     "stratoMetricPng","stratoMetricCsv",
                     "stratoVerticalPng","stratoVerticalHeatPng"):
            page.locator("#"+name).click()
        downloads=page.evaluate("fakeDownloads.map(x=>({name:x.name,png:x.uri.startsWith('data:image/png;base64,')}))")
        assert len(downloads)==6,downloads
        assert sum(1 for item in downloads if item["png"])==4,downloads
        assert all(item["name"].endswith((".csv",".png")) for item in downloads)
        # Model forecasts cannot magically appear on unarchived 30–100 hPa levels.
        datasets=page.evaluate("""() => Chart.getChart('stratoVerticalLineChart').data.datasets.map(d=>d.label)""")
        assert len([label for label in datasets if "Prognose" in label])==2
        assert all("10 hPa" in label for label in datasets if "Prognose" in label)
        geometry=page.evaluate("""() => ({
          viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,
          firstChart:document.getElementById('stratoHistoryForecastCanvas').getBoundingClientRect().width,
          verticalHeight:document.getElementById('stratoVerticalLineChart').getBoundingClientRect().height,
          heatmapCells:document.getElementById('stratoVerticalHeatmap').width
        })""")
        assert geometry["documentWidth"]<=geometry["viewport"]+6,geometry
        assert geometry["firstChart"]>240,geometry
        assert geometry["verticalHeight"]>=450,geometry
        assert geometry["heatmapCells"]==1220,geometry
        page.screenshot(path=str(OUT/f"stratosphere-{width}.png"),full_page=True)
        print(width,geometry,downloads,flush=True)
    finally:
        context.close()

def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            for w,h in [(1440,900),(390,844),(360,760)]:
                exercise(browser,w,h)
        finally:
            browser.close()

if __name__=="__main__":
    main()
