const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const data=require('../data.json');
const markup=fs.readFileSync('index.html','utf8');

test('real archive renders, selection, comparative detail and narrow viewport',async()=>{
  const fragment=markup.match(/<!-- ================= GEBIETSMITTEL ARCHIV START ================= -->([\s\S]*?)<!-- ================= GEBIETSMITTEL ARCHIV END ================= -->/);
  assert.ok(fragment,'Archive tab is present');
  const executablePath=process.env.CHROMIUM_PATH||(fs.existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined);
  const browser=await chromium.launch({executablePath,headless:true,args:['--no-sandbox']});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900},acceptDownloads:true});
    await page.setContent(`<html><body>${fragment[1].replace('class="tab-content"','class="tab-content active"')}</body></html>`);
    await page.addStyleTag({path:'gebietsmittel_archiv.css'});
    await page.addScriptTag({path:'gebietsmittel_archiv.js'});
    await page.evaluate(rows=>window.ensureGebietsmittelArchiveLoaded(rows),data);
    await page.selectOption('#gaYear','2025');
    assert.equal(await page.locator('#gaMonths .ga-period').count(),12);
    assert.equal(await page.locator('#gaSeasons .ga-period').count(),5);
    await page.locator('#gaMonths [data-period="06"]').click();
    assert.match(await page.locator('#gaDetailHeading').innerText(),/Juni 2025/);
    assert.match(await page.locator('#gaDetail').innerText(),/\+2,0 K/);
    assert.match(await page.locator('#gaDetail').innerText(),/78 %/);
    assert.match(await page.locator('#gaDetail').innerText(),/126 %/);
    await page.selectOption('#gaParameter','sun');
    assert.equal(await page.locator('#gaTableBody tr').count(),146);
    assert.match(await page.locator('#gaTableCaption').innerText(),/Sonnenschein/);
    await page.selectOption('#gaReference','1961');
    assert.match(await page.locator('#gaYearHeading').innerText(),/1961–1990/);
    await page.selectOption('#gaArea','Saarland');
    assert.match(await page.locator('#gaYearHeading').innerText(),/Saarland/);
    const download=page.waitForEvent('download');await page.click('#gaCsv');
    assert.match((await download).suggestedFilename(),/Saarland.*sun\.csv$/);
    await page.setViewportSize({width:390,height:844});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    assert.equal(overflow,false,'Only the historical table may scroll horizontally');
  }finally{await browser.close();}
});
