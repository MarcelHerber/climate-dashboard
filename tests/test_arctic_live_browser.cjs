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
      for (const selector of ["#arcticRecords > summary", "#arcticSeasons > summary"]) {
        if (device.mobile) await page.locator(selector).tap();
        else await page.locator(selector).click();
      }
      assert.ok(await page.locator("#arcticRecords").evaluate(el => el.open));
      assert.ok(await page.locator("#arcticSeasons").evaluate(el => el.open));
      const year = String(doc.latest_year);
      await page.locator("#arcticYear").selectOption(year);
      const index = doc.years[year].findLastIndex(v => Number.isFinite(v));
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
      await page.screenshot({ path: path.join(outDir, "dmi-" + device.name + ".png"), fullPage: true });
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(overflow <= 6, device.name + " horizontal overflow " + overflow + "px");
      assert.deepEqual(errors, [], "Unhandled browser JS errors");
      assert.deepEqual(failedRequests.filter(v => /arktis_temperatur|arctic80_temperature/.test(v)),
        [], "Main Arctic resources must load");
      console.log("PASS " + device.name +
        " live: " + doc.last_date + ", " + Object.keys(doc.years).length +
        " years, records, months, seasons, leap-day, both plots, 4 downloads, no overflow");
      await context.close();
    }
  } finally {
    await browser.close();
  }
}
main().catch(e => { console.error("DMI LIVE E2E FAILED:", e.stack || e); process.exitCode = 1; });
