#!/usr/bin/env python3
"""Chromium viewport screenshots against original repo HTML + CSS.
App scripts/data fetches are excluded: visual layout verification, not live science."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from inject_mobile_navigation import inject

WIDTHS=(320,360,390,430)
TARGETS=(
 ("startseite","index.html",None),
 ("ensembles","index.html","t850-ensembles"),
 ("mosmix","mosmix.html",None),
 ("stratosphaere","stratosphaere.html",None),
 ("isobaren","isobaren_original.html",None),
)
SCRIPTS=re.compile(r"<script\b[^>]*>[\s\S]*?</script\s*>",re.I)
LINKS=re.compile(r"<link\b[^>]*>",re.I)

def static_document(root:Path,name:str)->str:
 text=SCRIPTS.sub("",inject((root/name).read_text(encoding="utf-8")))
 def replace(match):
  tag=match.group()
  if not re.search(r"\brel\s*=\s*['\x22]stylesheet['\x22]",tag,re.I):
   return tag
  found=re.search(r"\bhref\s*=\s*['\x22]([^'\x22]+)['\x22]",tag,re.I)
  if not found:return ""
  href=found.group(1).split("?",1)[0].removeprefix("./")
  if href.startswith(("https:","http:","//")) or ".." in Path(href).parts:return ""
  css=root/href
  return "<style data-from='"+escape(href,quote=True)+"'>\n"+css.read_text(encoding="utf-8")+"\n</style>" if css.is_file() else ""
 text=LINKS.sub(replace,text)
 scripts="\n".join("<script>\n"+(root/file).read_text(encoding="utf-8")+"\n</script>"
                  for file in ("mobile_navigation.js","mobile_content.js"))
 return re.sub(r"</body\s*>",lambda m:scripts+"\n"+m.group(0),text,count=1,flags=re.I)

METRICS="""() => {
 const width=innerWidth, root=document.documentElement;
 const trigger=document.getElementById("cdMobileMenuButton");
 const rect=trigger?.getBoundingClientRect();
 const seen=[...document.body.querySelectorAll("*")].filter(e=>{
   let r=e.getBoundingClientRect(),s=getComputedStyle(e);
   if(s.display==="none"||s.visibility==="hidden"||r.width<1||r.height<1)return false;
   if(r.right<=width+3)return false;
   for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement)
     if(["scroll","auto","hidden","clip"].includes(getComputedStyle(p).overflowX))return false;
   return true;
 }).slice(0,12).map(e=>({tag:e.tagName,id:e.id||"",
   cls:typeof e.className==="string"?e.className.slice(0,70):"",
   right:Math.round(e.getBoundingClientRect().right)}));
 return {viewport:width,scrollWidth:root.scrollWidth,
   overflow:Math.max(0,root.scrollWidth-width),
   menuVisible:!!(rect&&rect.width>0&&rect.height>0),
   menuHeight:Math.round(rect?.height||0),offenders:seen};
}"""

def audit(root:Path,output:Path,chromium:str|None=None)->dict:
 from playwright.sync_api import sync_playwright
 output.mkdir(parents=True,exist_ok=True)
 docs={file:static_document(root,file) for _,file,_ in TARGETS}
 checks=[]
 with sync_playwright() as p:
  args={"headless":True,"args":["--no-sandbox"]}
  if chromium:args["executable_path"]=chromium
  browser=p.chromium.launch(**args)
  try:
   for width in WIDTHS:
    ctx=browser.new_context(viewport={"width":width,"height":812},
      is_mobile=True,has_touch=True,device_scale_factor=1,reduced_motion="reduce")
    for label,path,tab in TARGETS:
     page=ctx.new_page()
     try:
      page.set_content(docs[path],wait_until="load",timeout=30000)
      if tab:
       page.evaluate("""tab=>{
        document.querySelectorAll(".tab-content").forEach(e=>e.classList.remove("active"));
        const panel=document.getElementById(tab);
        if(panel)panel.classList.add("active");
       }""",tab)
      page.wait_for_timeout(90)
      measured=page.evaluate(METRICS)
      measured["page"]=label
      png=f"{label}_{width}px.png"
      page.screenshot(path=str(output/png),full_page=False,animations="disabled")
      measured["screenshot"]=png
      if label=="startseite":
       menu=page.locator("#cdMobileMenuButton")
       menu.click(timeout=2000)
       measured["drawerOpened"]=page.locator("#cdMobileMenu").is_visible()
       page.locator(".cdm-search").fill("Stratosphäre")
       measured["searchFound"]=page.locator(".cdm-results .cdm-search-item").count()>=1
       page.screenshot(path=str(output/f"menue_{width}px.png"),animations="disabled")
       page.keyboard.press("Escape")
       measured["escapeClosed"]=not page.locator("#cdMobileMenu").is_visible()
      measured["ok"]=measured["menuVisible"] and measured["menuHeight"]>=40 and measured["overflow"]<=3
      if label=="startseite":
       measured["ok"]=measured["ok"] and all(measured.get(k) for k in ("drawerOpened","searchFound","escapeClosed"))
      checks.append(measured)
     except Exception as exc:
      checks.append({"page":label,"viewport":width,"ok":False,"error":str(exc)[:450]})
     finally:page.close()
    ctx.close()
  finally:browser.close()
 report={"checked_at_utc":datetime.now(timezone.utc).isoformat(),
         "mode":"Chromium emulation with real HTML/CSS, app data requests suppressed",
         "checked":len(checks),"passed":sum(bool(c.get("ok")) for c in checks),
         "results":checks,
         "limitations":"Not physical Safari/Android. Actual dynamic chart content needs separate live QA."}
 (output/"audit.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
 md=["# Mobile viewport audit","", "Full-size native repository CSS and HTML; scripts for weather data disabled.","",
     "| Page | 320 | 360 | 390 | 430 |","|---|---|---|---|---|"]
 for name,_,_ in TARGETS:
  row=[next((r for r in checks if r["page"]==name and r["viewport"]==w),{}) for w in WIDTHS]
  md.append("| "+name+" | "+" | ".join(("OK" if x.get("ok") else "FAIL")+
             (f" ({x.get('overflow')}px overflow)" if x.get("overflow",0)>3 else "") for x in row)+" |")
 md+=["",f"Pass: {report['passed']}/{report['checked']}.",
      "PNG screenshots per page and width; menu screenshots named menue_320px.png etc.",
      "These screenshots do not verify dynamic live weather maps, model datasets, or original chart exports."]
 (output/"README.md").write_text("\n".join(md)+"\n",encoding="utf-8")
 return report

def main():
 a=argparse.ArgumentParser()
 a.add_argument("--root",type=Path,default=ROOT)
 a.add_argument("--output",type=Path,default=Path("mobile_viewport_reports"))
 a.add_argument("--chromium",default=None)
 args=a.parse_args()
 result=audit(args.root,args.output,args.chromium)
 print((args.output/"README.md").read_text(encoding="utf-8"))
 for row in result["results"]:
  if not row.get("ok"):print(json.dumps(row,ensure_ascii=False)[:750])
 return 0 if result["passed"]==result["checked"] else 1

if __name__=="__main__":sys.exit(main())
