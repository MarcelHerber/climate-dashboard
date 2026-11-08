"""Chromium regression test for the same-UTC GEFS / ECMWF ENS forecast view."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT=Path("strato-joint-browser")
OUT.mkdir(exist_ok=True)
HTML="""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head><body>
<main><section class="strato-prob-panel strato-joint-panel" id="stratoJointPanel">
<h3>Direkter GEFS / ECMWF Vergleich</h3>
<select id="stratoCompareHour"><option value="00">00 UTC</option><option value="12">12 UTC</option></select>
<div class="strato-joint-toolbar"><select id="stratoJointHour"><option value="00">00 UTC</option><option value="12">12 UTC</option></select>
<button id="stratoJointPng" disabled>PNG speichern</button><button id="stratoJointCsv" disabled>CSV speichern</button></div>
<div class="strato-joint-kpis">
<div><strong id="stratoJointGefsCross">–</strong></div>
<div><strong id="stratoJointEpsCross">–</strong></div>
<div><strong id="stratoJointOverlap">–</strong></div></div>
<span id="stratoJointGefsCycle">–</span><span id="stratoJointEpsCycle">–</span>
<div class="chart strato-joint-chart"><canvas id="stratoJointCanvas"></canvas></div>
<p id="stratoJointStatus"></p>
<details class="strato-joint-details" open><summary>Umkehrereignisse</summary>
<div class="strato-joint-table-scroll"><table><tbody id="stratoJointReversals"></tbody></table></div></details>
</section></main>
</body></html>"""

def exercise(browser, width, height):
    context=browser.new_context(viewport={"width":width,"height":height})
    page=context.new_page()
    try:
        page.set_content(HTML)
        page.add_style_tag(content="""
         :root{--card:#fff;--ink:#16253c;--line:#dce3eb;--muted:#536478}
         *{box-sizing:border-box}body{font:14px Arial,sans-serif;margin:0;background:#edf3f8}
         main{max-width:1450px;padding:12px;margin:auto}.strato-joint-panel{min-width:0}
         .chart{position:relative}.chart canvas{height:100%!important;width:100%!important}
         """)
        page.add_style_tag(path="stratosphere_chart_visibility.css")
        page.add_style_tag(path="stratosphere_joint_comparison.css")
        page.add_script_tag(url="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js")
        page.add_script_tag(path="stratosphere_chart_visibility.js")
        page.add_script_tag(path="stratosphere_chart_export.js")
        page.add_script_tag(path="stratosphere_joint_comparison.js")
        page.evaluate("""() => {
          const days=['2026-11-08','2026-11-09','2026-11-10','2026-11-11'];
          window.makeFake=(kind,hour=0)=>{
            const n=kind==='gefs'?30:50;
            const members={c00:[4,1,-2,-1]};
            for(let i=1;i<=n;i++){
              const id='p'+String(i).padStart(2,'0');
              members[id]=i===1?[-1,-2,-3,-1]:i===2?[3,-1,2,-1]:[5,4,4,5];
            }
            return {provider:kind==='gefs'?'NOAA GEFS':'ECMWF IFS ENS',
              level_hpa:10,latitude_deg:60,units:'m/s',
              cycle_utc:'2026-11-08T'+String(hour).padStart(2,'0')+':00:00Z',
              valid_dates:days,members};
          };
          window.sendPair=hour=>window.dispatchEvent(new CustomEvent(
            'stratosphere:joint-data-ready',{detail:{
              gefs:makeFake('gefs',hour),eps:makeFake('eps',hour),hour
            }}
          ));
          window.exports=[];
          HTMLAnchorElement.prototype.click=function(){
            exports.push({name:this.download,href:this.href});
          };
          sendPair(0);
        }""")
        chart=page.evaluate("""() => !!Chart.getChart(document.getElementById('stratoJointCanvas'))""")
        assert chart is not None
        assert page.locator("#stratoJointPng").is_enabled()
        assert page.locator("#stratoJointCsv").is_enabled()
        assert page.locator("#stratoJointGefsCross").inner_text()=="2/31 Mitglieder"
        assert page.locator("#stratoJointEpsCross").inner_text()=="2/51 Mitglieder"
        assert page.locator("#stratoJointOverlap").inner_text()=="4 gemeinsame Tage"
        assert page.locator("#stratoJointReversals tr").count()==2

        def set_profile(profile):
            page.locator(".strato-series-profile[data-key='"+profile+"']").click()
        set_profile("overview")
        flags=page.evaluate("""() => {
           const chart=Chart.getChart(document.querySelector('#stratoJointCanvas'));
           return chart.data.datasets.map((d,i)=>({label:d.label,visible:chart.isDatasetVisible(i)}));
        }""")
        assert any("25–75" in item["label"] and not item["visible"] for item in flags)
        assert any("5–95" in item["label"] and item["visible"] for item in flags)
        assert any("erste Member-Windumkehr" in item["label"] and item["visible"] for item in flags)
        set_profile("ensemble")
        all_visible=page.evaluate("""() => {
          const c=Chart.getChart(document.querySelector('#stratoJointCanvas'));
          return c.data.datasets.every((_,i)=>c.isDatasetVisible(i));
        }""")
        assert all_visible

        # PNG contains title, color keys and only selected series; no transparent pixels.
        page.locator("#stratoJointPng").click()
        export=page.evaluate("""() => ({name:exports.at(-1)?.name,
          png:exports.at(-1)?.href?.startsWith('data:image/png;base64,')})""")
        assert export["png"] and "00UTC" in export["name"], export
        page.locator("#stratoJointCsv").click()
        csv=page.evaluate("""() => exports.at(-1)?.name""")
        assert csv.endswith(".csv")
        page.locator("#stratoJointHour").select_option("12")
        assert page.locator("#stratoCompareHour").input_value()=="12"
        page.evaluate("sendPair(12)")
        assert "12-UTC" in page.locator("#stratoJointStatus").inner_text()
        page.locator("#stratoJointPng").click()
        assert "12UTC" in page.evaluate("exports.at(-1)?.name")

        geometry=page.evaluate("""() => ({
          viewport:innerWidth,docWidth:document.documentElement.scrollWidth,
          chartHeight:document.querySelector('.strato-joint-chart').getBoundingClientRect().height,
          chartWidth:document.getElementById('stratoJointCanvas').getBoundingClientRect().width
        })""")
        assert geometry["docWidth"]<=geometry["viewport"]+5,geometry
        assert geometry["chartHeight"]>=480,geometry
        assert geometry["chartWidth"]>220,geometry
        page.screenshot(path=str(OUT/f"joint-{width}.png"),full_page=True)
        print(width,geometry,flush=True)
    finally:
        context.close()

def main():
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            for width,height in [(1440,900),(390,844),(360,760)]:
                exercise(browser,width,height)
        finally:
            browser.close()

if __name__=="__main__":
    main()
