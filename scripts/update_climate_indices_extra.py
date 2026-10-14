"""Additional independently sourced indices for the NOAA climate dashboard.

Never synthesize missing values. Each source retains its exact reference and
its last-observed date. GBI is an explicitly *derived* seasonally standardized
index from NOAA/PSL's area-mean Z500, not a CPC teleconnection eigenvector.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from math import isfinite
from statistics import mean, stdev
import re

TELE_URL="https://ftp.cpc.ncep.noaa.gov/wd52dg/data/indices/tele_index.nh"
GBI_URL="https://www.psl.noaa.gov/data/correlation/gbi.ncep.day"
SOI_URL="https://www.cpc.ncep.noaa.gov/data/indices/soi"
MEI_URL="https://psl.noaa.gov/enso/mei/data/meiv2.data"
QBO30_URL="https://www.cpc.ncep.noaa.gov/data/indices/qbo.u30.index"
QBO50_URL="https://www.cpc.ncep.noaa.gov/data/indices/qbo.u50.index"
MJO_URL="https://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
SOURCES={"tele":TELE_URL,"gbi":GBI_URL,"soi":SOI_URL,"mei":MEI_URL,
         "qbo30":QBO30_URL,"qbo50":QBO50_URL,"mjo":MJO_URL}

def parse_tele(text):
    """CPC source is fixed-width, with missing -99.90 often attached to neighbor."""
    result={"scand":[],"ea":[],"eawr":[]}
    for line in text.splitlines():
        head=re.match(r"^\s*((?:19|20)\d{2})\s+(\d{1,2})\s+(.*)$",line)
        if not head:
            continue
        y,m,rest=int(head[1]),int(head[2]),head[3]
        if not 1<=m<=12:continue
        # First ten columns hold 10 EOF pattern amplitudes, followed by variance.
        values=re.findall(r"[-+]?(?:\d+\.\d+|\d+)",rest)
        if len(values)<10:continue
        for name,position in (("ea",1),("eawr",5),("scand",6)):
            value=float(values[position])
            if abs(value)>=90:continue
            result[name].append([f"{y:04d}-{m:02d}",round(value,2)])
    for name,rows in result.items():
        if len(rows)<800 or rows[0][0]>"1952-01":
            raise ValueError(f"{name} teleconnection series invalid: {len(rows)}")
    return result

def parse_year_matrix(text,earliest,maximum,name):
    """CPC SOI/QBO monthly table: YYYY Jan..Dec; skip -999 sentinels."""
    rows={}
    for line in text.splitlines():
        parts=line.split()
        if len(parts)<4 or not re.fullmatch(r"(?:19|20)\d{2}",parts[0]):
            continue
        year=int(parts[0])
        if not earliest<=year<=date.today().year+1:continue
        for m,raw in enumerate(parts[1:13],1):
            try:val=float(raw)
            except ValueError:continue
            if not isfinite(val) or abs(val)>maximum:continue
            rows[f"{year:04d}-{m:02d}"]=round(val,2)
    result=[[key,value] for key,value in sorted(rows.items())]
    minimum=500 if earliest>=1970 else 780
    if len(result)<minimum:raise ValueError(f"{name}: too few monthly values ({len(result)})")
    return result

def parse_gbi(text):
    daily=defaultdict(list)
    for line in text.splitlines():
        parts=line.split()
        if len(parts)<4:continue
        try:
            y,m,d=map(int,parts[:3])
            day=date(y,m,d)
            v=float(parts[3])
        except ValueError:continue
        if 1948<=day.year<=date.today().year+1 and isfinite(v) and 4300<v<6100:
            daily[day.strftime("%Y-%m")].append(v)
    monthly={}
    for ym,values in daily.items():
        y,m=map(int,ym.split("-"))
        following=date(y+(m==12),m%12+1,1)
        n=(following-date(y,m,1)).days
        if len(values)>=int(n*.9):
            monthly[ym]=mean(values)
    baseline=defaultdict(list)
    for ym,v in monthly.items():
        y,m=map(int,ym.split("-"))
        if 1981<=y<=2010:baseline[m].append(v)
    if any(len(baseline[m])<25 for m in range(1,13)):
        raise ValueError("GBI: 1981–2010 reference too sparse")
    means={m:mean(baseline[m]) for m in range(1,13)}
    stdevs={m:stdev(baseline[m]) for m in range(1,13)}
    rows=[[ym,round((v-means[int(ym[5:])])/stdevs[int(ym[5:])],3)]
          for ym,v in sorted(monthly.items()) if stdevs[int(ym[5:])]>0]
    if len(rows)<750:raise ValueError(f"GBI too short: {len(rows)}")
    return rows

def parse_mjo(text):
    rows={}
    for line in text.splitlines():
        parts=line.split()
        if len(parts)<7:continue
        try:
            year,month,day=map(int,parts[:3])
            dt=date(year,month,day)
            r1,r2=float(parts[3]),float(parts[4])
            phase=int(parts[5]); amp=float(parts[6])
        except ValueError:continue
        if not 1<=phase<=8 or not (0<=amp<20) or abs(r1)>20 or abs(r2)>20:
            continue
        if dt.year<1974 or dt>date.today()+timedelta(days=3):continue
        if abs((r1*r1+r2*r2)**.5-amp)>0.09:continue
        rows[dt.isoformat()]=[dt.isoformat(),round(r1,3),round(r2,3),phase,round(amp,3)]
    result=[rows[k] for k in sorted(rows)]
    if len(result)<17000 or result[0][0]>"1975-01-01":raise ValueError("MJO RMM history incomplete")
    return result

def load_all(fetch):
    tele=parse_tele(fetch(TELE_URL))
    gbi=parse_gbi(fetch(GBI_URL))
    soi=parse_year_matrix(fetch(SOI_URL),1951,15,"SOI")
    mei=parse_year_matrix(fetch(MEI_URL),1979,15,"MEI.v2")
    q30=parse_year_matrix(fetch(QBO30_URL),1979,90,"QBO30")
    q50=parse_year_matrix(fetch(QBO50_URL),1979,90,"QBO50")
    mjo=parse_mjo(fetch(MJO_URL))
    def series(rows,source,label,unit="standardisiert",method="Originalwert"):
        return {"label":label,"unit":unit,"method":method,"source_url":source,
                "monthly":rows,"latest_month":rows[-1][0],"first_month":rows[0][0]}
    return {
        "europe":{
            **{key:series(data,TELE_URL,{"scand":"Skandinavien (SCAND)","ea":"East Atlantic (EA)","eawr":"East Atlantic / West Russia (EA/WR)"}[key],
                method="CPC rotierte EOF-Amplitude, Referenz 1981–2010")
               for key,data in tele.items()},
            "gbi":series(gbi,GBI_URL,"Grönland-Blocking (GBI)",
                method="Eigene Standardisierung des NOAA/PSL 500-hPa-Höhengebietsmittels: monatliche Anomalie / Monats-Standardabweichung 1981–2010")
        },
        "enso_extra":{
            "soi":series(soi,SOI_URL,"Southern Oscillation Index (SOI)",
                method="CPC Tahiti minus Darwin, standardisierte Monatswerte"),
            "mei":series(mei,MEI_URL,"Multivariate ENSO Index v2 (MEI.v2)",
                method="NOAA PSL JRA3Q; überlappende 2-Monatswerte, DJ..ND; Monatslabel = zweiter Monat")
        },
        "qbo":{
            "u30":series(q30,QBO30_URL,"QBO-U30, 30 hPa",unit="m/s",
                method="CPC zonaler Wind in 30 hPa, positive Werte = Westwind"),
            "u50":series(q50,QBO50_URL,"QBO-U50, 50 hPa",unit="m/s",
                method="CPC zonaler Wind in 50 hPa, positive Werte = Westwind")
        },
        "mjo":{
            "label":"Wheeler–Hendon RMM (BOM)","source_url":MJO_URL,
            "method":"Original RMM1/RMM2 und Phasen aus BOM, 1974–heute; Amplitude <1 schwach",
            "daily":mjo,"latest_date":mjo[-1][0],"first_date":mjo[0][0]
        },
        "extra_source_urls":SOURCES
    }
