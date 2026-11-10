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
