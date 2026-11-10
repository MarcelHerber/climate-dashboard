#!/usr/bin/env python3
"""Discover official current AEMET Canary radar GeoTIFF endpoints, no invented URLs."""
import re,requests,bs4,json
from urllib.parse import urljoin,urlparse
s=requests.Session();s.headers.update({"User-Agent":"Mozilla/5.0 ClimateDashboard Radar Research","Accept-Language":"es"})
base="https://www.aemet.es"
urls=[
 base+"/es/eltiempo/observacion/radar?p=LPA",
 base+"/es/eltiempo/observacion/radar?p=LPA&w=1",
 base+"/es/api-eltiempo/radar/download/regional/LPA",
 base+"/es/api-eltiempo/radar/download/compo",
 "https://opendata.aemet.es/opendata/api/red/radar/regional/lp",
 "https://opendata.aemet.es/opendata/api/red/radar/regional/lpa",
]
for u in urls:
 try:
  r=s.get(u,timeout=28)
  print("URL",r.status_code,len(r.content),r.url,r.headers.get("content-type"),"BODY",r.text[:250] if "text" in r.headers.get("content-type","") or "json" in r.headers.get("content-type","") else "[binary]")
  if "radar?p=" in u and r.ok:
   html=r.text
   for pattern in (r".{0,180}(?:geotiff|tif|download|radar/|LPA|/api-eltiempo|/imagenes/).{0,240}",r"<script[^>]+src=[^>]+>",r"<img[^>]+>"):
    candidates=re.findall(pattern,html,re.I)
    print("MATCH",pattern,len(candidates))
    for line in candidates[:25]: print(line[:380].replace("\n"," "))
   doc=bs4.BeautifulSoup(html,"html.parser")
   print("SCRIPTS",[(tag.get("src")) for tag in doc.select("script[src]") if any(x in str(tag.get("src")).lower() for x in ["radar","observ","api","map"])][:24])
 except Exception as e: print("ERR",u,str(e)[:300])
