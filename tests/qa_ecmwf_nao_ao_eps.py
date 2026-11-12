#!/usr/bin/env python3
"""Real browser verification of independent EPS NAO/AO forecasts and NOAA comparisons."""
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

SITE="https://marcelherber.github.io/climate-dashboard/zirkulation.html"


def verify(page,out:Path,label:str):
    errors=[]
    page.on("pageerror",lambda err:errors.append(str(err)))
    response=page.goto(SITE,wait_until="domcontentloaded",timeout=90000)
    assert response and response.status==200
    expect(page.locator("#epsEofPanel")).to_be_visible()
    page.wait_for_function("""() => {
      const c=window.Chart?.getChart(document.getElementById("epsChart"));
      return c && !document.getElementById("epsPNG").disabled &&
        c.data.datasets.filter(s=>s.label.startsWith("EPS-Mitglied ")).length===50 &&
        document.getElementById("epsStatus").textContent.includes("50 echte Mitgliedsprognosen");
    }""",timeout=60000)

    def datasets():
        return page.evaluate("""() => {
          const c=Chart.getChart(document.getElementById("epsChart"));
          return {count:c.data.datasets.length,labels:c.data.datasets.map(s=>s.label),
                  points:c.data.labels.length};
        }""")

    initial=datasets()
    assert initial["points"]>=16 and initial["count"]>=53,initial
    assert "NOAA GEFS" in " ".join(initial["labels"])
    assert "keine offiziellen CPC-Indexprognosen" in page.locator("#epsEofPanel").inner_text().lower() or "nicht die originale CPC" in page.locator("#epsEofPanel").inner_text()
    page.locator("#epsMembers").uncheck()
    assert len([x for x in datasets()["labels"] if x.startswith("EPS-Mitglied ")])==0
    page.locator("#epsMembers").check()
    assert len([x for x in datasets()["labels"] if x.startswith("EPS-Mitglied ")])==50

    # Compare optional NOAA series on matching valid dates.
    page.locator("#epsCompare").uncheck()
    assert "NOAA GEFS" not in " ".join(datasets()["labels"])
    page.locator("#epsCompare").check()
    assert "NOAA GEFS" in " ".join(datasets()["labels"])

    page.locator("#epsMode").select_option("probability")
    assert datasets()["count"]==5,datasets()
    page.locator("#epsDays").select_option("7")
    assert datasets()["points"]==8,datasets()
    page.locator("#epsIndex").select_option("ao")
    assert "AO" in page.locator("#epsStatus").inner_text()
    page.locator("#epsMode").select_option("ensemble")
    page.locator("#epsDays").select_option("15")
    assert len([x for x in datasets()["labels"] if x.startswith("EPS-Mitglied ")])==50

    for button,ext in (("#epsCSV","csv"),("#epsPNG","png"),("#epsPDF","pdf")):
        with page.expect_download(timeout=35000) as info:
            page.locator(button).click()
        obj=info.value
        assert obj.suggested_filename.endswith("."+ext),obj.suggested_filename
        target=out/(label+"_eps."+ext)
        obj.save_as(target)
        b=target.read_bytes()
        assert len(b)>2500,(ext,len(b))
        if ext=="png": assert b.startswith(bytes.fromhex("89504e470d0a1a0a"))
        if ext=="pdf": assert b.startswith(b"%PDF-")
        if ext=="csv":
            assert b"EPS-Mitglied" in b and b"NOAA GEFS" in b and len(b)>9000,(len(b),b[:250])

    metrics=page.evaluate("""() => ({
       screen:innerWidth,content:document.documentElement.scrollWidth,
       panel:document.querySelector('#epsEofPanel').getBoundingClientRect().width,
       chart:document.querySelector('#epsChart').getBoundingClientRect().width
    })""")
    assert metrics["chart"]<=metrics["panel"]+2,metrics
    assert metrics["content"]<=metrics["screen"]+3,metrics
    assert not errors,errors[:5]
    page.screenshot(path=str(out/(label+"_eps_screenshot.png")),full_page=True,animations="disabled")
    print(json.dumps({"viewport":label,"dataset_count":initial["count"],"member_count":50,
                      "export_count":3,"metrics":metrics}),flush=True)


if __name__=="__main__":
    root=Path("/tmp/ecmwf-eps-live");root.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
        try:
            for label,width,height in (("desktop",1440,900),("phone320",320,740),("phone390",390,844)):
                page=browser.new_page(viewport={"width":width,"height":height},accept_downloads=True)
                try:verify(page,root,label)
                finally:page.close()
        finally:browser.close()
