#!/usr/bin/env python3
"""Inspect one actual latest DWD RY ODIM HDF5 before designing the radar decoder."""
from io import BytesIO
import logging
import requests, h5py, numpy as np
URL="https://opendata.dwd.de/weather/radar/radolan/ry/raa01-ry_10000-latest-dwd---bin.hdf5"
r=requests.get(URL,timeout=45,headers={"User-Agent":"ClimateDashboardRadarResearch/1.0"})
print("HTTP",r.status_code,"bytes",len(r.content),"content-type",r.headers.get("content-type"))
r.raise_for_status()
with h5py.File(BytesIO(r.content),"r") as h:
 def walk(name, obj):
  if name.count("/")>4: return
  if hasattr(obj,"shape"):print("DATA",name,obj.shape,str(obj.dtype))
  attrs={k:(v.decode() if isinstance(v,bytes) else v.tolist() if isinstance(v,np.ndarray) else v) for k,v in obj.attrs.items()}
  if attrs:print("META",name,attrs)
 h.visititems(walk)
 d=h["dataset1/data1/data"][:]
 print("SAMPLE_PIXEL",{"shape":d.shape,"dtype":str(d.dtype),"min":float(np.nanmin(d)),"max":float(np.nanmax(d)),"unique":np.unique(d[::20,::20])[:60].tolist()})
