#!/usr/bin/env node
// End-to-end test of the LIVE DMI Arctic page, after GitHub Pages deployment.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const BASE = process.env.DMI_LIVE_URL ||
  "https://marcelherber.github.io/climate-dashboard/arktis_temperatur.html";
const outDir = path.join(process.cwd(), "artifacts");
fs.mkdirSync(outDir, { recursive: true });

async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const device of [
      { name: "desktop", width: 1440, height: 900, mobile: false },
      { name: "mobile", width: 390, height: 844, mobile: true }
    ]) {
      const context = await browser.newContext({
        viewport: { width: device.width, height: device.height },
        hasTouch: device.mobile,
        isMobile: device.mobile,
        acceptDownloads: true
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      const failedRequests = [];
      page.on("requestfailed", request => failedRequests.push(
        request.url() + " " + (request.failure()?.errorText || "")));
      const response = await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 90000 });
      assert.equal(response.status(), 200, "Page must load with HTTP 200");
      await page.waitForFunction(() => {
        const a = document.querySelector("#arcticRecordSummary");
        const b = document.querySelector("#arcticPeriodSummary");
        const c = document.querySelector("#arcticPeriod");
        const y = document.querySelector("#arcticYear");
        return a && b && c && y && c.options.length === 16 &&
          !a.textContent.includes("Lade Statistik") &&
          !b.textContent.includes("Lade Statistik") && !y.disabled;
      }, null, { timeout: 90000 });
      const doc = await page.evaluate(async () => {
        const result = await fetch("data/arctic80_temperature.json", { cache: "no-store" });
        if (!result.ok) throw new Error("Live DMI JSON HTTP " + result.status);
        return await result.json();
      });
      assert.equal(doc.schema, 1);
      assert.equal(doc.days.length, 366);
      assert.ok(Object.keys(doc.years).length >= 60);
      assert.equal(doc.days[59], "02-29");
      const available = Object.entries(doc.years).flatMap(([y, a]) =>
        a.flatMap((v, i) => Number.isFinite(v) ? [y + "-" + doc.days[i]] : []));
      assert.equal(doc.last_date, available.sort().at(-1), "Live date must match data");
      assert.ok(await page.locator("#arcticRecordHot tr").count() > 0);
      assert.ok(await page.locator("#arcticRecordCold tr").count() > 0);
      assert.ok(await page.locator("#arcticPeriodHot tr").count() > 0);
      assert.ok(await page.locator("#arcticPeriodCold tr").count() > 0);
      assert.ok(await page.locator("#arcticAnnualChart").count() === 1);
      assert.ok(await page.locator("#arcticAnomalyChart").count() === 1);
      const charts = await page.evaluate(() => ({
        a: !!window.Chart?.getChart?.(document.getElementById("arcticAnnualChart")),
        b: !!window.Chart?.getChart?.(document.getElementById("arcticAnomalyChart"))
      }));
      assert.ok(charts.a && charts.b, "Both Chart.js plots must render");
      // These selectors are intentionally inside collapsed <details> panels.
      // Exercise the real disclosure controls before selecting values.
      for (const selector of ["#arcticRecords > summary", "#arcticSeasons > summary", "#arcticStreaks > summary"]) {
        if (device.mobile) await page.locator(selector).tap();
        else await page.locator(selector).click();
      }
      assert.ok(await page.locator("#arcticRecords").evaluate(el => el.open));
      assert.ok(await page.locator("#arcticSeasons").evaluate(el => el.open));
      assert.ok(await page.locator("#arcticStreaks").evaluate(el => el.open));
      // Complete-year climate trends, selectable window, seasonal rankings, and two charts.
      await page.waitForFunction(() =>
        document.getElementById("arcticLongTermLoad")?.textContent.includes("Auswertung bereit") &&
        document.querySelector("#arcticTrendFrom")?.options.length>35 &&
        document.querySelectorAll("#arcticSeasonWarmBody tr").length>0,
        null,{timeout:60000});
      const chartsNew=await page.evaluate(()=>["arcticTrendDaysCanvas","arcticTrendDurationCanvas","arcticSeasonCanvas"]
        .map(id=>!!window.Chart?.getChart?.(document.getElementById(id))));
      assert.deepEqual(chartsNew,[true,true,true],"Trend and seasonal charts must render");
      await page.locator("#arcticLongTermPanel").evaluate(el=>el.open=true);
      await page.locator("#arcticClimateSeasonPanel").evaluate(el=>el.open=true);
      const firstTrend=Number(await page.locator("#arcticTrendFrom").inputValue());
      const finalTrend=Number(await page.locator("#arcticTrendTo").inputValue());
      assert.ok(finalTrend>=2024&&firstTrend<=1970);
      assert.equal(await page.locator("#arcticTrendCoverage").inputValue(),"0.95");
      let chartYears=await page.evaluate(()=>
        Chart.getChart(document.getElementById("arcticTrendDaysCanvas")).data.labels.map(Number));
      assert.ok(chartYears.includes(2018),"Default 95% coverage must retain 2010s");
      assert.ok(!chartYears.includes(2026),"Ongoing incomplete year must remain outside trends");
      assert.ok((await page.locator("#arcticTrendStatus").innerText()).includes("95 %"));
      await page.locator("#arcticTrendCoverage").selectOption("1");
      chartYears=await page.evaluate(()=>
        Chart.getChart(document.getElementById("arcticTrendDaysCanvas")).data.labels.map(Number));
      assert.ok(!chartYears.includes(2018),"Strict mode must exclude incomplete 2018");
      await page.locator("#arcticTrendCoverage").selectOption("0.95");
      chartYears=await page.evaluate(()=>
        Chart.getChart(document.getElementById("arcticTrendDaysCanvas")).data.labels.map(Number));
      assert.ok(chartYears.includes(2018));
      assert.ok((await page.locator("#arcticTrendSlope").innerText()).includes("365"));

      const shortStart=String(Math.max(firstTrend,2000));
      await page.locator("#arcticTrendFrom").selectOption(shortStart);
      assert.ok((await page.locator("#arcticTrendStatus").innerText()).includes(shortStart));
      const countWithTrend=await page.evaluate(()=>Chart.getChart(
        document.getElementById("arcticTrendDaysCanvas")).data.datasets.length);
      assert.equal(countWithTrend,4);
      await page.locator("#arcticTrendLines").uncheck();
      const countWithoutTrend=await page.evaluate(()=>Chart.getChart(
        document.getElementById("arcticTrendDaysCanvas")).data.datasets.length);
      assert.equal(countWithoutTrend,2);
      await page.locator("#arcticTrendLines").check();
      await page.locator("#arcticTrendFrom").selectOption(String(firstTrend));
      assert.ok(await page.locator("#arcticDecadeBody tr").count()>=5);
      for(const s of ["djf","mam","jja","son"]){
        await page.locator("#arcticSeasonChoose").selectOption(s);
        assert.ok((await page.locator("#arcticSeasonStatus").innerText()).includes("vollständige Perioden"));
        assert.ok(await page.locator("#arcticSeasonWarmBody tr").count()>=8);
        assert.ok(await page.locator("#arcticSeasonColdBody tr").count()>=8);
      }
      await page.locator("#arcticSeasonChoose").selectOption("djf");
      assert.ok((await page.locator("#arcticSeasonStatus").innerText()).includes("Winterjahr"));
      assert.ok((await page.locator("#arcticSeasonSelected").innerText()).includes("2026"));
      const summaryReady=await page.evaluate(()=>!!window.Arctic80LongTermMath &&
        window.Arctic80LongTermMath.analyze(window.Arctic80LoadedData).seasons.djf.some(s=>s.year===2026));
      assert.ok(summaryReady,"Seasonal DJF should join Dec 2025 with Jan/Feb 2026");
      // ERA5 Arctic spatial maps: no synthetic fallback; validate real maps when available.
      // Verify all three real ERA5 polar regions on the deployed website.
      const era5Panel=page.locator("#arcticEra5MapPanel");
      assert.equal(await era5Panel.count(),1);
      await era5Panel.evaluate(el=>el.open=true);
      const era5Meta=await page.evaluate(async()=>{
        const res=await fetch("data/arctic_era5_maps/index.json",{cache:"no-store"});
        return res.ok?await res.json():null;
      });
      await page.waitForFunction(()=>!document.querySelector("#arcticEra5MapStatus")
          .textContent.includes("Prüfe ERA5-Datenverfügbarkeit"),null,{timeout:45000});
      assert.ok(await page.locator("#arcticEra5MapRegion").count());
      assert.ok(await page.locator("#arcticEra5Calendar").count());
      assert.ok((await page.locator("#arcticEra5ArchiveProgress").innerText()).includes("30") ||
        (await page.locator("#arcticEra5ArchiveProgress").innerText()).includes("nicht verfügbar"));
      if(era5Meta?.ready===true){
        assert.ok(era5Meta.days.length>0);
        assert.equal(era5Meta.reference_period,"1991-2020");
        assert.equal(era5Meta.anomaly_reference,"monthly_mean_same_calendar_month");
        if(era5Meta.schema===2){
          assert.deepEqual(era5Meta.regions,[80,70,60]);
          assert.equal(era5Meta.target_days,30);
          assert.equal(era5Meta.archive_policy,"append_only");
          assert.equal(era5Meta.archive_days,era5Meta.days.length);
          assert.ok(era5Meta.days.length>=era5Meta.initial_backfill_days,
            "Append-only archive must retain all previously verified dates");
          assert.equal(era5Meta.fully_mapped_days,era5Meta.days.length,
            "Every published day must include all three polar regions");
          assert.ok(era5Meta.days.every(day=>["60","70","80"].every(region=>
            day.regions?.[region]?.boundary_version===3)),
            "All published polar maps require current coastline version");
          assert.ok(era5Meta.days.every(day=>Object.keys(day.regions||{}).every(k=>
            ["60","70","80"].includes(k))));
        }
        await era5Panel.scrollIntoViewIfNeeded();
        for(const region of ["80","70","60"]){
          await page.locator("#arcticEra5MapRegion").selectOption(region);
          const count=await page.locator("#arcticEra5MapDate option").count();
          const status=await page.locator("#arcticEra5MapStatus").innerText();
          const selected=await page.locator("#arcticEra5MapDate").inputValue();
          const expected=era5Meta.days.filter(row=>
            era5Meta.schema===2?!!row.regions?.[region]:region==="80");
          if(!expected.length){
            assert.ok(status.includes("noch keine geprüften Karten") ||
              status.includes("nicht verfügbar"),"Unavailable region must be clear");
            assert.equal(await page.locator("#arcticEra5Pdf").isDisabled(),true);
            continue;
          }
          assert.equal(count,expected.length);
          assert.ok(expected.some(row=>row.date===selected));
          assert.equal(await page.locator("#arcticEra5Calendar").inputValue(),selected);
          await page.waitForFunction(()=>[
            document.querySelector("#arcticEra5TempMap"),
            document.querySelector("#arcticEra5AnomalyMap")
          ].every(el=>el.complete&&el.naturalWidth>=800),null,{timeout:45000});
          assert.ok((await page.locator("#arcticEra5MeanTemp").innerText()).includes("°C"));
          assert.ok((await page.locator("#arcticEra5MeanAnomaly").innerText()).includes("K"));
          for(const id of ["#arcticEra5TempPng","#arcticEra5AnomalyPng"]){
            const href=await page.locator(id).getAttribute("href");
            assert.match(href,/\.png\?map=b[23]$/);
            const response=await page.request.get(new URL(href,BASE).toString());
            assert.equal(response.status(),200);
            const bytes=await response.body();
            assert.equal(bytes.subarray(0,8).toString("hex"),"89504e470d0a1a0a");
            assert.ok(bytes.length>=25000);
          }
          await page.locator("#arcticEra5MapMode").selectOption("anomaly");
          assert.equal(await page.locator("#arcticEra5TempFrame").isVisible(),false);
          await page.locator("#arcticEra5MapMode").selectOption("both");
          assert.ok(await page.locator("#arcticEra5TempFrame").isVisible());
          assert.ok(await page.locator("#arcticEra5Pdf").isEnabled());
          if(region==="80"||region==="60"){
            const downloadPromise=page.waitForEvent("download",{timeout:35000});
            await page.locator("#arcticEra5Pdf").click();
            const download=await downloadPromise;
            assert.ok(download.suggestedFilename().includes(region+"-90N"));
            assert.equal(fs.readFileSync(await download.path()).subarray(0,4).toString(),"%PDF");
          }
          if(expected.length>1){
            // Region switches preserve selected date, including the oldest day.
            // Start from the newest day before testing the "previous" button.
            await page.locator("#arcticEra5MapDate").selectOption(expected[0].date);
            assert.equal(await page.locator("#arcticEra5MapPrev").isEnabled(),true);
            await page.locator("#arcticEra5MapPrev").click();
            assert.equal(await page.locator("#arcticEra5MapDate").inputValue(),expected[1].date);
            await page.locator("#arcticEra5MapNext").click();
            assert.equal(await page.locator("#arcticEra5MapDate").inputValue(),expected[0].date);
            await page.locator("#arcticEra5Calendar").fill(expected.at(-1).date);
            assert.equal(await page.locator("#arcticEra5MapDate").inputValue(),expected.at(-1).date);
          }
        }
        await page.locator("#arcticEra5MapRegion").selectOption("80");
        // DMI/ERA5 synchronized day selection using real repository/Pages data.
        const allDates=era5Meta.days.filter(d=>d.regions?.["80"]).map(d=>d.date);
        assert.ok(allDates.length>=2,"Two-day ERA5 comparison requires at least 2 actual archived dates");
        await page.waitForFunction(()=>window.ArcticEra5Sync?.getState?.().ready===true);
        await page.locator("#arcticEra5MapDate").selectOption(allDates[0]);
        await page.waitForFunction(date=>document.getElementById("arcticRecordDay")?.value===date.slice(5),allDates[0]);
        assert.equal(await page.locator("#arcticYear").inputValue(),allDates[0].slice(0,4));

        // Actual mouse click or touchscreen tap on the DMI Chart.js plot.
        await page.locator("#arcticAnnualChart").scrollIntoViewIfNeeded();
        const clickPoint=await page.evaluate(date=>{
          const canvas=document.getElementById("arcticAnnualChart");
          const chart=Chart.getChart(canvas),rect=canvas.getBoundingClientRect();
          const i=window.Arctic80LoadedData.days.indexOf(date.slice(5));
          if(i<0)throw Error("Target day missing in DMI calendar");
          return {x:rect.left+chart.scales.x.getPixelForValue(i),
            y:rect.top+(chart.chartArea.top+chart.chartArea.bottom)/2};
        },allDates[1]);
        if(device.mobile)await page.touchscreen.tap(clickPoint.x,clickPoint.y);
        else await page.mouse.click(clickPoint.x,clickPoint.y);
        await page.waitForFunction(date=>window.ArcticEra5Sync.getState().primaryDate===date,allDates[1]);
        assert.ok((await page.locator("#arcticEra5SyncStatus").innerText()).includes("Synchronisiert"));

        // A historical DMI-only date must not be silently replaced by a false ERA5 date.
        await page.locator("#arcticYear").selectOption("1990");
        await page.locator("#arcticAnnualChart").scrollIntoViewIfNeeded();
        if(device.mobile)await page.touchscreen.tap(clickPoint.x,clickPoint.y);
        else await page.mouse.click(clickPoint.x,clickPoint.y);
        assert.equal(await page.locator("#arcticEra5MapDate").inputValue(),allDates[1]);
        assert.ok((await page.locator("#arcticEra5SyncStatus").innerText()).includes("noch keine geprüfte ERA5-Karte"));
        await page.locator("#arcticYear").selectOption(String(doc.latest_year));

        // Comparison renders two independent real days in the same polar region.
        await page.locator("#arcticEra5CompareEnabled").check();
        await page.locator("#arcticEra5CompareDate").selectOption(allDates[0]);
        assert.ok(await page.locator("#arcticEra5CompareGrid").isVisible());
        assert.ok(!await page.locator("#arcticEra5Maps").isVisible());
        assert.ok((await page.locator("#arcticEra5CompareSummary").innerText()).includes("Tag B minus Tag A"));
        await page.waitForFunction(()=>[
          "arcticEra5CompareATemp","arcticEra5CompareAAnomaly",
          "arcticEra5CompareBTemp","arcticEra5CompareBAnomaly"
        ].every(id=>{const img=document.getElementById(id);return img.complete&&img.naturalWidth>=800;}),null,{timeout:45000});
        for(const id of ["arcticEra5CompareATempPng","arcticEra5CompareBAnomalyPng"]){
          const url=await page.locator("#"+id).getAttribute("href");
          assert.match(url,/^data\/arctic_era5_maps\/maps\//);
          assert.equal((await page.request.get(new URL(url,BASE).toString())).status(),200);
        }
        const comparePdfPromise=page.waitForEvent("download",{timeout:45000});
        await page.locator("#arcticEra5ComparePdf").click();
        const comparePdf=await comparePdfPromise;
        assert.ok(comparePdf.suggestedFilename().includes("Vergleich"));
        assert.equal(fs.readFileSync(await comparePdf.path()).subarray(0,4).toString(),"%PDF");

        // Keyboard navigation changes map A and the linked DMI day.
        await page.locator("#arcticEra5CompareGrid").focus();
        await page.keyboard.press("ArrowLeft");
        await page.waitForFunction(date=>window.ArcticEra5Sync.getState().primaryDate===date,allDates[2]||allDates[1]);
        assert.equal(await page.locator("#arcticRecordDay").inputValue(),(allDates[2]||allDates[1]).slice(5));
        // Mobile gestures use a horizontal swipe; vertical scrolling must remain possible.
        if(device.mobile){
          const surface=page.locator("#arcticEra5CompareGrid");
          await surface.evaluate(el=>{
            const start=new Touch({identifier:8,target:el,clientX:280,clientY:240});
            const end=new Touch({identifier:8,target:el,clientX:90,clientY:242});
            el.dispatchEvent(new TouchEvent("touchstart",{bubbles:true,touches:[start],targetTouches:[start]}));
            el.dispatchEvent(new TouchEvent("touchend",{bubbles:true,changedTouches:[end],touches:[],targetTouches:[]}));
          });
          const next=allDates[3]||allDates[2]||allDates[1];
          await page.waitForFunction(date=>window.ArcticEra5Sync.getState().primaryDate===date,next);
        }
        await page.locator("#arcticEra5CompareSwap").click();
        assert.ok((await page.locator("#arcticEra5CompareSummary").innerText()).includes("Tag B minus Tag A"));
        await page.locator("#arcticEra5MapRegion").selectOption("70");
        assert.match(await page.locator("#arcticEra5CompareATemp").getAttribute("src"),/t2m_70n_/);
        await page.locator("#arcticEra5CompareEnabled").uncheck();
        assert.ok(await page.locator("#arcticEra5Maps").isVisible());
      }else{
        const status=await page.locator("#arcticEra5MapStatus").innerText();
        assert.ok(status.includes("nicht verfügbar") ||
          status.includes("noch keine"),"No synthetic maps while ERA5 unavailable");
        assert.equal(await page.locator("#arcticEra5Pdf").isDisabled(),true);
      }
      const year = String(doc.latest_year);
      await page.locator("#arcticYear").selectOption(year);
      const index = doc.years[year].findLastIndex(v => Number.isFinite(v));
      // Streak monitor: real data, both modes, minimum-duration filter,
      // highlighted-year response, and live threshold math all work in-browser.
      await page.waitForFunction(() =>
        !document.querySelector("#arcticStreakStatus").textContent.includes("Lade historische Serien"),null,{timeout:30000});
      assert.ok(await page.locator("#arcticStreakEvents tr").count()>=1);
      assert.ok(await page.locator("#arcticStreakYears tr").count()>=1);
      assert.equal(await page.locator("#arcticStreakMonths > div").count(),12);
      await page.locator("#arcticStreakType").selectOption("cold");
      assert.ok((await page.locator("#arcticStreakDays").innerText()).includes("Kalttage"));
      await page.locator("#arcticStreakMinDays").selectOption("30");
      assert.ok((await page.locator("#arcticStreakStatus").innerText()).includes("30 Tagen"));
      await page.locator("#arcticStreakType").selectOption("warm");
      assert.ok((await page.locator("#arcticStreakDays").innerText()).includes("Warmtage"));
      await page.locator("#arcticStreakMinDays").selectOption("7");
      const mathReady = await page.evaluate(() =>
        !!window.Arctic80StreaksMath && typeof window.Arctic80StreaksMath.analyze === "function");
      assert.ok(mathReady,"Streak engine must be present");
      await page.locator("#arcticYear").selectOption("2023");
      assert.ok((await page.locator("#arcticStreakCoverage").innerText()).includes("Kalendertagen"));
      await page.locator("#arcticYear").selectOption(year);
      // Historical heatmap: all 69 year rows and every calendar day draw on a real canvas.
      await page.waitForFunction(() => window.Arctic80VisualState?.loaded?.() &&
        document.querySelector("#arcticHeatmapCanvas")?.height > 800 &&
        document.querySelector("#arcticHeatmapCount")?.textContent.includes("Jahre"),
        null,{timeout:30000});
      const geometry=await page.evaluate(()=>({
        height:document.querySelector("#arcticHeatmapCanvas").height,
        width:document.querySelector("#arcticHeatmapCanvas").width,
        scroll:document.querySelector("#arcticHeatmapScroll").clientWidth
      }));
      assert.ok(geometry.width>1000&&geometry.height>800,"Full 366-day by 69-year heatmap");
      assert.ok(geometry.scroll<=device.width,"Heatmap must scroll inside mobile viewport");

      await page.locator("#arcticYear").selectOption("2018");
      const initialSegments=await page.evaluate(()=>window.Arctic80VisualState.segments());
      assert.ok(initialSegments.some(s=>s.kind==="warm"&&s.start==="2018-09-25"&&s.end==="2018-11-12"),
        "Chart overlays must include the 49-day autumn 2018 warm spell");
      await page.locator("#arcticVisualWarm").uncheck();
      assert.ok((await page.evaluate(()=>window.Arctic80VisualState.segments())).every(s=>s.kind!=="warm"),
        "Warm overlay toggle must hide warm spells");
      await page.locator("#arcticVisualWarm").check();
      await page.locator("#arcticVisualCold").uncheck();
      assert.ok((await page.evaluate(()=>window.Arctic80VisualState.segments())).every(s=>s.kind!=="cold"));
      await page.locator("#arcticVisualCold").check();
      await page.locator("#arcticVisualMinimum").selectOption("14");
      assert.ok((await page.evaluate(()=>window.Arctic80VisualState.segments())).every(s=>s.days>=14));
      await page.locator("#arcticVisualMinimum").selectOption("7");

      await page.locator("#arcticStreakType").selectOption("warm");
      await page.locator("#arcticStreakMinDays").selectOption("7");
      const firstSpell=page.locator("#arcticStreakEvents tr[role='button']").first();
      await firstSpell.click();
      assert.ok((await page.locator("#arcticVisualInfo").innerText()).includes("49 Tage"),
        "Clicking ranking must focus record spell in both plots");
      assert.equal(await page.locator("#arcticYear").inputValue(),"2018");
      const focused=await page.evaluate(()=>window.Arctic80VisualState.focused());
      assert.equal(focused.start,"2018-09-25");

      // Actual chart click should select a calendar day and show its threshold status.
      const chartCoordinates=await page.evaluate(()=>{
        const chart=Chart.getChart(document.getElementById("arcticAnnualChart"));
        return {x:chart.scales.x.getPixelForValue(274),
          y:chart.chartArea.top+Math.min(20,(chart.chartArea.bottom-chart.chartArea.top)/2)};
      });
      if(device.mobile)await page.locator("#arcticAnnualChart").tap({position:chartCoordinates});
      else await page.locator("#arcticAnnualChart").click({position:chartCoordinates});
      assert.ok((await page.locator("#arcticVisualInfo").innerText()).includes("01.10.2018"),
        "Plot interaction must choose selected calendar day");

      // Heatmap cell click: first row / Jan 2 -> main year 1958 and daily date 01-02.
      await page.locator("#arcticHeatmapPanel").scrollIntoViewIfNeeded();
      const heatmap=page.locator("#arcticHeatmapCanvas");
      if(device.mobile)await heatmap.tap({position:{x:52,y:38}});
      else await heatmap.click({position:{x:52,y:38}});
      assert.equal(await page.locator("#arcticYear").inputValue(),"1958");
      assert.equal(await page.locator("#arcticRecordDay").inputValue(),"01-02");
      assert.ok((await page.locator("#arcticVisualInfo").innerText()).includes("02.01.1958"));
      await page.locator("#arcticYear").selectOption(year);
      await page.locator("#arcticRecordDay").selectOption(doc.days[index]);
      assert.ok((await page.locator("#arcticRecordSummary").innerText()).includes("°C"));
      const expected = doc.years[year][index];
      const observedText = await page.locator("#arcticRecordSummary").innerText();
      const shown = Number(observedText.match(/^-?[0-9]+(?:,[0-9]+)?/)?.[0].replace(",", "."));
      assert.ok(Math.abs(shown - expected) < 0.06, "Day value must match JSON");
      await page.locator("#arcticPeriod").selectOption("m10");
      assert.ok((await page.locator("#arcticPeriodSummary").innerText()).includes("°C"));
      await page.locator("#arcticPeriod").selectOption("djf");
      assert.ok(await page.locator("#arcticPeriodHot tr").count() >= 5);
      await page.locator("#arcticRecordDay").selectOption("02-29");
      await page.locator("#arcticYear").selectOption("2023");
      assert.ok((await page.locator("#arcticRecordSummary").innerText()).includes("kein Wert"),
        "Non-leap-year February 29 must stay missing");
      await page.locator("#arcticYear").selectOption(year);
      await page.locator("#arcticRecordDay").selectOption(doc.days[index]);
      await page.locator("#arcticHistoryMode").selectOption("none");
      await page.locator("#arcticHistoryMode").selectOption("recent");
      await page.locator("#arcticShow7").uncheck();
      await page.locator("#arcticShow30").uncheck();
      await page.locator("#arcticShow7").check();
      await page.locator("#arcticShow30").check();
      for (const [selector, extension] of [
        ["#arcticCsv", ".csv"], ["#arcticPngAnnual", ".png"],
        ["#arcticPngAnomaly", ".png"], ["#arcticPdf", ".pdf"]
      ]) {
        const downloadPromise = page.waitForEvent("download", { timeout: 25000 });
        await page.locator(selector).click();
        const download = await downloadPromise;
        assert.ok(download.suggestedFilename().endsWith(extension));
        const filepath = await download.path();
        assert.ok(filepath && fs.statSync(filepath).size > 200, "Nonempty " + extension);
        if (extension === ".csv") {
          const content = fs.readFileSync(filepath, "utf8");
          assert.equal(content.split("\r\n").filter(Boolean).length, 367);
          assert.ok(content.includes(doc.days[index]));
        }
      }
      // Test all CSV, high-resolution PNG and multipage PDF exports against live data.
      const exportChecks=[
        ["#arcticTrendPng",".png"],["#arcticTrendPdf",".pdf"],
        ["#arcticAnnualStatsCsv",".csv"],["#arcticEventsCsv",".csv"],
        ["#arcticSeasonPng",".png"],["#arcticSeasonPdf",".pdf"],
        ["#arcticSeasonCsv",".csv"],["#arcticHeatmapPng",".png"],
        ["#arcticHeatmapPdf",".pdf"],["#arcticHeatmapCsv",".csv"]
      ];
      for(const [selector,extension] of exportChecks){
        const pending=page.waitForEvent("download",{timeout:45000});
        await page.locator(selector).click();
        const download=await pending;
        assert.ok(download.suggestedFilename().endsWith(extension),
          selector+" produced "+download.suggestedFilename());
        const filepath=await download.path();
        const bytes=fs.readFileSync(filepath);
        assert.ok(bytes.length>500,selector+" must contain actual exported content");
        if(extension===".png")assert.equal(bytes.subarray(0,4).toString("hex"),"89504e47");
        if(extension===".pdf")assert.equal(bytes.subarray(0,4).toString(),"%PDF");
        if(extension===".csv"){
          const content=bytes.toString("utf8");
          assert.ok(content.includes("DMI"),"CSV should identify DMI");
          assert.ok(content.includes("1958"),"CSV should identify reference period");
          if(selector==="#arcticHeatmapCsv")
            assert.ok(content.split("\r\n").length>20000,"Include every day since 1958");
          if(selector==="#arcticEventsCsv")
            assert.ok(content.includes("Wärme")&&content.includes("Kälte"),"Both event types");
          if(selector==="#arcticSeasonCsv")
            assert.ok(content.includes("djf")&&content.includes("son"),"All four seasons");
        }
      }
      await page.locator("#arcticRecords").evaluate(el => el.open = true);
      await page.locator("#arcticSeasons").evaluate(el => el.open = true);
      await page.locator("#arcticStreaks").evaluate(el => el.open = true);
      await page.locator("#arcticLongTermPanel").evaluate(el => el.open = true);
      await page.locator("#arcticClimateSeasonPanel").evaluate(el => el.open = true);
      await page.screenshot({ path: path.join(outDir, "dmi-" + device.name + ".png"), fullPage: true });
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 6) {
        const offenders = await page.evaluate(() => {
          const viewport = document.documentElement.clientWidth;
          return {viewport,innerWidth:window.innerWidth,
            scrollWidth:document.documentElement.scrollWidth,
            offenders:[...document.querySelectorAll("body *")].map(el => ({
              tag:el.tagName,id:el.id,cls:String(el.className||"").slice(0,70),
              right:Math.round(el.getBoundingClientRect().right),
              left:Math.round(el.getBoundingClientRect().left),
              width:Math.round(el.getBoundingClientRect().width)
            })).filter(x=>x.right>viewport+5 && x.width>3).slice(0,20)};
        });
        console.error("Mobile overflow elements:",JSON.stringify(offenders));
      }
      assert.ok(overflow <= 6, device.name + " horizontal overflow " + overflow + "px");
      assert.deepEqual(errors, [], "Unhandled browser JS errors");
      assert.deepEqual(failedRequests.filter(v => /arktis_temperatur|arctic80_temperature/.test(v)),
        [], "Main Arctic resources must load");
      console.log("PASS " + device.name +
        " live: " + doc.last_date + ", " + Object.keys(doc.years).length +
        " years, extreme overlays, heatmap, climate trends, seasonal ranks, 14 live exports, leap day, no overflow");
      await context.close();
    }
  } finally {
    await browser.close();
  }
}
main().catch(e => { console.error("DMI LIVE E2E FAILED:", e.stack || e); process.exitCode = 1; });
