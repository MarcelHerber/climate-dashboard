#!/usr/bin/env python3
"""Find actual live IPMA Azores radar image endpoints in the official page.
Does not publish, cache or scrape radar media."""
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from datetime import datetime,timezone

SITES=[
 "https://www.ipma.pt/pt/otempo/obs.remote/index-az.jsp",
 "https://www.ipma.pt/pt/otempo/obs.radar/",
 "https://www.ipma.pt/pt/otempo/obs.radar/index.jsp?selArea=flr&selGrandeza=rn1",
 "https://api.ipma.pt/open-data/observation/",
 "https://www.ipma.pt/pt/otempo/obs.remote/index-composito_old.jsp",
]
s=requests.Session()
s.headers.update({"User-Agent":"Mozilla/5.0 (compatible; ClimateDashboardAzoresRadarResearch/1.0)","Accept-Language":"pt"})
REGEX=re.compile(r"(azores|açores|radar|composit|image|wms|tile|getcapabilit|geoserver|anim|precip|/rad/|.png|.gif|.jpg)",re.I)
for url in SITES:
 try:
  r=s.get(url,timeout=32)
  print("\nURL",url,"STATUS",r.status_code,"BYTES",len(r.content),"TYPE",r.headers.get("content-type"),"FINAL",r.url)
  if not r.ok:continue
  if "html" not in r.headers.get("content-type","") and not url.endswith("/"):continue
  html=r.text
  soup=BeautifulSoup(html,"html.parser")
  for tag in soup.find_all(["img","iframe","link","script","source"]):
   ref=tag.get("src") or tag.get("href")
   if ref:
    full=urljoin(r.url,ref)
    if tag.name=="script" or REGEX.search(full):print("ASSET",tag.name,full[:360])
  for t in soup.find_all("script"):
   if not t.get("src"):
    js=t.text
    hits=list(REGEX.finditer(js))
    for m in hits[:36]:
     print("INLINE",js[max(0,m.start()-110):m.end()+260].replace("\n"," ")[:450])
  if "obs.remote" in url or "obs.radar" in url:
   scripts=[urljoin(r.url,e.get("src")) for e in soup.find_all("script",src=True)]
   for script in scripts:
    try:
     sr=s.get(script,timeout=28)
     if not sr.ok or len(sr.content)>1000000:continue
     js=sr.text
     hits=list(REGEX.finditer(js))
     print("JS",script,sr.status_code,len(js),"HITS",len(hits))
     for m in hits[:24]:
      print("JS_MATCH",js[max(0,m.start()-95):m.end()+190].replace("\n"," ")[:330])
    except Exception as e:print("SCRIPT_ERROR",script,str(e)[:120])
 except Exception as e:print("ERROR",url,str(e)[:220])
