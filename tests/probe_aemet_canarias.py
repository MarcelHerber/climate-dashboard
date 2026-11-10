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

import tarfile,io
import numpy as np
import rasterio
archive=s.get("https://www.aemet.es/es/api-eltiempo/radar/download/regional/LPA",timeout=120)
archive.raise_for_status()
with tarfile.open(fileobj=io.BytesIO(archive.content),mode="r:gz") as ar:
 items=[m for m in ar.getmembers() if m.isfile()]
 print("ARCHIVE",len(items),sum(m.size for m in items))
 for item in items[:65]:
  print("ITEM",item.name,item.size)
 tif=[m for m in items if m.name.lower().endswith((".tif",".tiff"))]
 for item in tif[:5]:
  data=ar.extractfile(item).read()
  with rasterio.MemoryFile(data) as mem:
   with mem.open() as ds:
    print("GEOTIFF",item.name,"shape",ds.shape,"count",ds.count,"crs",ds.crs,"bounds",ds.bounds,"nodata",ds.nodata,
          "dtype",ds.dtypes,"tags",ds.tags(),"scales",ds.scales,"offsets",ds.offsets,"colorinterp",ds.colorinterp)
    for band in range(1,min(ds.count,4)+1):
     a=ds.read(band,out_shape=(150,150))
     print("BAND",band,"tags",ds.tags(band),"sample",np.unique(a)[:30].tolist(),"minmax",(np.min(a),np.max(a)),
           "colormap",str(ds.colormap(band))[:400] if ds.count==1 else "-")

 print("LPA_PPI_COUNT",len([m for m in items if "down_LPA" in m.name and ".PPI.Z_" in m.name]))
 for item in sorted([m for m in items if "down_LPA" in m.name and ".PPI.Z_" in m.name],key=lambda m:m.name)[-4:]:
  with rasterio.MemoryFile(ar.extractfile(item).read()) as mem:
   with mem.open() as ds:
    print("LPA_PPI",item.name,item.size,"shape",ds.shape,"bounds",str(ds.bounds),
          "crs",ds.crs,"data_types",ds.dtypes,"tags",str(ds.tags())[:1800],"interp",ds.colorinterp)
    values=ds.read(out_shape=(4,190,190),masked=False)
    rgba=values.transpose(1,2,0)
    print("LPA_STATS","avg_rgb",rgba[:,:,:3].mean(axis=(0,1)).tolist(),
      "alpha_gt_0",float((rgba[:,:,3]>0).mean()),
      "alpha_255",float((rgba[:,:,3]==255).mean()),
      "white_fraction",float(np.all(rgba[:,:,:3]>245,axis=2).mean()),
      "sample_unique",np.unique(rgba.reshape(-1,4),axis=0)[:25].tolist())
