"""Real Chromium integration checks for Chart.js visibility controls.
No meteorological figures are synthesized on the live page: the synthetic
fixtures below only test the user interface, not the dashboard's data.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT = Path("strato-control-browser")
OUTPUT.mkdir(exist_ok=True)
HTML = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body><main><section class="card">
<h1>Test der Stratosphären-Diagrammsteuerung</h1>
<div class="chart ensemble-chart"><canvas id="stratoDemoChart"></canvas></div>
</section></main></body></html>"""


def exercise(browser, width, height, label):
    context = browser.new_context(viewport={"width": width, "height": height},
                                  device_scale_factor=1)
    page = context.new_page()
    try:
        page.set_content(HTML)
        page.add_style_tag(content="""
        :root {--card:#fff;--ink:#16253c;--line:#dce3eb}
        * {box-sizing:border-box}
        body {margin:0;font:15px Arial,sans-serif;background:#eef3f8}
        .chart {position:relative;width:100%;height:520px}
        .chart canvas {width:100%!important;height:100%!important}
        """)
        page.add_style_tag(path="stratosphere_chart_visibility.css")
        page.add_script_tag(url="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js")
        page.add_script_tag(path="stratosphere_chart_visibility.js")
        page.add_script_tag(path="stratosphere_chart_export.js")
        page.evaluate("""() => {
          const source = [
            {label:'_P10–P90 Untergrenze',data:[2,1,3],borderColor:'transparent',borderWidth:0},
            {label:'P10–P90',data:[7,8,9],borderColor:'transparent',
              fill:{target:'-1',above:'rgba(30,100,180,.2)'}},
            {label:'Mittelwert',data:[4,5,6],borderColor:'#d32828',borderWidth:3},
            {label:'_EPS p01',data:[3,5,4],borderColor:'#567'},
            {label:'_EPS p02',data:[5,6,7],borderColor:'#678'}
          ];
          window.makeDemo = () => new Chart(document.getElementById('stratoDemoChart'), {
            type:'line',data:{labels:['01.11.','02.11.','03.11.'],datasets:source},
            options:{responsive:true,maintainAspectRatio:false,animation:false,
              plugins:{legend:{display:true}}}
          });
          window.demo = window.makeDemo();
        }""")
        panel = page.locator(".strato-series-panel")
        panel.wait_for(timeout=15000)
        assert panel.locator("button[data-action='toggle']").count() == 4
        assert page.evaluate("demo.options.plugins.legend.display") is False

        # Both source datasets of a filled interval are switched as a pair.
        panel.locator("button[data-action='toggle']").filter(has_text="P10–P90").click()
        assert page.evaluate("[demo.isDatasetVisible(0),demo.isDatasetVisible(1),demo.isDatasetVisible(2)]") == [False,False,True]
        panel.locator("button[data-action='toggle']").filter(has_text="P10–P90").click()
        assert page.evaluate("[demo.isDatasetVisible(0),demo.isDatasetVisible(1)]") == [True,True]

        # The mean's preference persists across a re-created Chart.js instance.
        panel.locator("button[data-action='toggle']").filter(has_text="Mittelwert").click()
        assert page.evaluate("demo.isDatasetVisible(2)") is False
        page.evaluate("demo.destroy(); demo = makeDemo();")
        assert page.evaluate("demo.isDatasetVisible(2)") is False

        # Individual EPS members and bulk member toggles.
        panel.locator("summary").click()
        panel.locator("button[data-action='members-off']").click()
        assert page.evaluate("[demo.isDatasetVisible(3),demo.isDatasetVisible(4)]") == [False,False]
        assert page.evaluate("demo.isDatasetVisible(0)") is True
        panel.locator("button[data-action='members-on']").click()
        assert page.evaluate("[demo.isDatasetVisible(3),demo.isDatasetVisible(4)]") == [True,True]
        panel.locator("button[data-action='all-on']").click()
        assert page.evaluate("demo.isDatasetVisible(2)") is True

        # PNG always contains a title, source and a colored legend of *visible* data.
        export_state = page.evaluate("""() => {
          const visible = window.stratoChartExport.visibleEntries(window.demo).map(e => e.label);
          const output = window.stratoChartExport.fromChart(window.demo, {
            title: 'Zonaler Wind 60° N / 10 hPa',
            subtitle: 'Testlauf · 00 UTC',
            source: 'Quelle: Originaldaten der jeweiligen Modelle'
          });
          const ctx = output.getContext('2d');
          const first = ctx.getImageData(0,0,1,1).data;
          const png = output.toDataURL('image/png');
          window.exportPreview = document.createElement('img');
          window.exportPreview.alt = 'Beschrifteter Diagrammexport';
          window.exportPreview.style.maxWidth='100%';
          window.exportPreview.src=png;
          document.querySelector('main').appendChild(window.exportPreview);
          return {visible,width:output.width,height:output.height,
            chartHeight:demo.canvas.height,firstPixel:Array.from(first),
            validPng:png.startsWith('data:image/png;base64,')};
        }""")
        assert export_state["visible"] == ["P10–P90","Mittelwert","EPS p01","EPS p02"], export_state
        assert export_state["height"] > export_state["chartHeight"] + 100, export_state
        assert export_state["firstPixel"] == [255,255,255,255], export_state
        assert export_state["validPng"], export_state
        # Previously hidden series must be absent from PNG legend metadata.
        panel.locator("button[data-action='toggle']").filter(has_text="Mittelwert").click()
        without_mean = page.evaluate("""() =>
          window.stratoChartExport.visibleEntries(window.demo).map(e => e.label)""")
        assert "Mittelwert" not in without_mean

        geometry = page.evaluate("""() => ({
          viewport: innerWidth, documentWidth: document.documentElement.scrollWidth,
          chartHeight: Math.round(document.querySelector('.chart').getBoundingClientRect().height),
          canvasWidth: Math.round(document.querySelector('#stratoDemoChart').getBoundingClientRect().width),
          controlsWidth: Math.round(document.querySelector('.strato-series-panel').getBoundingClientRect().width)
        })""")
        assert geometry["documentWidth"] <= geometry["viewport"] + 5, geometry
        assert geometry["canvasWidth"] >= 220, geometry
        assert geometry["chartHeight"] >= 440, geometry
        page.screenshot(path=str(OUTPUT / f"{label}.png"),full_page=True)
        print(label, geometry, flush=True)
    finally:
        context.close()


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for w,h,name in [(1440,900,"desktop"),(390,844,"mobile-390"),(360,760,"mobile-360")]:
                exercise(browser,w,h,name)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
