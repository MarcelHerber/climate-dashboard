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
      await page.locator("#arcticRecords").evaluate(el => el.open = true);
      await page.locator("#arcticSeasons").evaluate(el => el.open = true);
      await page.locator("#arcticStreaks").evaluate(el => el.open = true);
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
        " years, records, extreme overlays, historical heatmap, mobile touch, leap-day, 2 plots, 4 downloads, no overflow");
      await context.close();
    }
  } finally {
    await browser.close();
  }
}
main().catch(e => { console.error("DMI LIVE E2E FAILED:", e.stack || e); process.exitCode = 1; });
