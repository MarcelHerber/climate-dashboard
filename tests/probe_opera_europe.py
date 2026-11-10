#!/usr/bin/env python3
"""Probe live OPERA ODIM composite and Natural Earth 10m metadata; never publish guesses."""
from datetime import datetime,timezone,timedelta
from urllib.parse import quote
import requests,xml.etree.ElementTree as ET, io
import h5py, numpy as np
s=requests.Session()
s.headers["User-Agent"]="ClimateDashboard-OPERA-Test/0.1 (meteorological noncommercial research)"
utc=datetime.now(timezone.utc)
api="https://api.meteogate.eu/eu-eumetnet-weather-radar/collections/observations/locations/0-20010-0-OPERA"
for standard in ["DBZH","RATE"]:
 start=(utc-timedelta(minutes=80)).replace(second=0,microsecond=0).isoformat().replace("+00:00","Z")
 end=utc.isoformat().replace("+00:00","Z")
 params={"datetime":f"{start}/{end}","f":"CoverageJSON","standard_name":standard,"format":"ODIM"}
 try:
  r=s.get(api,params=params,timeout=30)
  print("API",standard,r.status_code,len(r.content),r.url,"BODY",r.text[:1300])
 except Exception as e: print("API_ERROR",standard,str(e))
for standard in ["DBZH","RATE"]:
 for day in [utc,utc-timedelta(days=1)]:
  prefix=f"{day:%Y/%m/%d}/OPERA/COMP/"
  url="https://s3.waw3-1.cloudferro.com/openradar-24h/"
  try:
   r=s.get(url,params={"list-type":"2","prefix":prefix,"max-keys":"5"},timeout=25)
   print("S3_LIST",standard,prefix,r.status_code,len(r.content),r.text[:1200])
  except Exception as e:print("S3_ERROR",str(e))
try:
 r=s.get("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson",timeout=45)
 print("BORDERS",r.status_code,len(r.content),r.text[:140])
except Exception as e:print("BORDERS_ERROR",str(e))

for kind,stamp in (("DBZH","20261110T1835"),("RATE","20261110T1830")):
 for ext in ("h5","tiff"):
  url=f"https://s3.waw3-1.cloudferro.com/openradar-24h/2026/11/10/OPERA/COMP/OPERA@{stamp}@0@{kind}.{ext}"
  try:
   r=s.get(url,timeout=55)
   print("FILE",kind,ext,r.status_code,len(r.content),r.headers.get("content-type"))
   if r.status_code!=200:continue
   if ext=="h5":
    with h5py.File(io.BytesIO(r.content),"r") as h:
     def walk(k,obj):
      if k.count("/")>3:return
      at={a:(v.decode(errors="replace") if isinstance(v,bytes) else v.tolist() if isinstance(v,np.ndarray) else v) for a,v in obj.attrs.items()}
      if at:print("H5",k,at)
      if hasattr(obj,"shape"):print("H5_DATA",k,obj.shape,str(obj.dtype))
     h.visititems(walk)
   else:
    import tempfile,os
    import rasterio
    with tempfile.NamedTemporaryFile(suffix=".tif",delete=False) as tmp:
     tmp.write(r.content);tmpname=tmp.name
    with rasterio.open(tmpname) as ds:
     print("TIFF_META",kind,{"shape":ds.shape,"crs":str(ds.crs),"transform":str(ds.transform),"nodata":ds.nodata,"scales":ds.scales,"offsets":ds.offsets,"tags":ds.tags(),"bandtags":ds.tags(1),"dtype":ds.dtypes,"bounds":str(ds.bounds)})
     a=ds.read(1,out_shape=(100,100))
     print("TIFF_SAMPLES",int(np.min(a)),int(np.max(a)),np.unique(a)[:30].tolist())
    os.remove(tmpname)
  except Exception as e:print("FILE_ERROR",kind,ext,str(e)[:300])
