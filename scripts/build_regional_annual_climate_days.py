#!/usr/bin/env python3
"""Download the seven official DWD regional annual climate-day tables."""
import csv, io, json, math, re, tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from datetime import date
BASE="https://opendata.dwd.de/climate_environment/CDC/regional_averages_DE/annual/"
SOURCES={
 "frost":("Frosttage","Tmin < 0 °C","frost_days/regional_averages_tnas_year.txt"),
 "ice":("Eistage","Tmax < 0 °C","ice_days/regional_averages_txcs_year.txt"),
 "summer":("Sommertage","Tmax ≥ 25 °C","summer_days/regional_averages_txas_year.txt"),
 "hot":("Heiße Tage","Tmax ≥ 30 °C","hot_days/regional_averages_txbs_year.txt"),
 "tropical":("Tropennächte","Tmin ≥ 20 °C (DWD-Jahresprodukt)","tropical_nights_tminGE20/regional_averages_tnes_year.txt"),
 "rr10":("Niederschlagstage ≥ 10 mm","RR ≥ 10 mm","precipGE10mm_days/regional_averages_rrsfs_year.txt"),
 "rr20":("Niederschlagstage ≥ 20 mm","RR ≥ 20 mm","precipGE20mm_days/regional_averages_rrsgs_year.txt"),
}
def parse(raw):
    try: content=raw.decode("utf-8-sig")
    except UnicodeDecodeError: content=raw.decode("latin-1")
    lines=list(csv.reader(io.StringIO(content),delimiter=";"))
    pos=next(i for i,row in enumerate(lines) if len(row)>3 and row[0].strip()=="Jahr" and row[1].strip()=="Jahr")
    names=[s.strip().replace("Baden-Wuerttemberg","Baden-Württemberg").replace("Thueringen","Thüringen") for s in lines[pos][2:] if s.strip()]
    if len(names)!=len(set(names)) or "Deutschland" not in names: raise ValueError("Unexpected DWD area header")
    rows={}
    for row in lines[pos+1:]:
        if not row or not re.fullmatch(r"\d{4}",row[0].strip()): continue
        year=int(row[0]); vals=row[2:2+len(names)]
        if len(vals)!=len(names) or year in rows or row[1].strip()!="year": raise ValueError(f"Bad row {year}")
        result=[]
        for value in vals:
            value=value.strip().replace(",",".")
            if value in ("","-999","-999.0","-999.00","NaN","nan"): result.append(None); continue
            n=float(value)
            if not math.isfinite(n) or not 0<=n<=366: raise ValueError(f"Bad value {year}: {n}")
            result.append(n)
        rows[year]=result
    stamp=re.search(r"erstellt am:\s*(\d{8})",content)
    return names,rows,stamp.group(1) if stamp else None

def build():
    out=Path("data/dwd_regional_annual_climate_days.json")
    metrics={}; areas=None
    for key,(label,definition,path) in SOURCES.items():
        url=BASE+path
        with urlopen(Request(url,headers={"User-Agent":"ClimateDashboard-DWD/1.0"}),timeout=90) as r: raw=r.read()
        names,rows,stamp=parse(raw)
        if areas is None: areas=names
        if set(areas)!=set(names): raise ValueError(f"Changed area coverage: {key}")
        if len(rows)<60 or min(rows)!=1951 or max(rows)<date.today().year-2 or max(rows)>=date.today().year: raise ValueError(f"Unexpected historical coverage: {key}")
        if sorted(rows)!=list(range(min(rows),max(rows)+1)): raise ValueError(f"Year gap: {key}")
        metrics[key]={"label":label,"definition":definition,"source":url,"source_date":stamp,"years":{str(y):[vals[names.index(a)] for a in areas] for y,vals in sorted(rows.items())}}
        print(key,min(rows),max(rows),len(names),flush=True)
    result={"version":1,"areas":areas,"metrics":metrics}
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=out.parent,delete=False) as f:
        json.dump(result,f,ensure_ascii=False,separators=(",",":"),allow_nan=False); f.write("\n"); tmp=Path(f.name)
    tmp.replace(out)
def selftest():
    fixture="Zeitreihen fuer Gebietsmittel, erstellt am: 20261102\nJahr;Jahr;Baden-Wuerttemberg;Deutschland;\n1951;year;99.53;85.57;\n1952;year;-999.00;109.43;\n"
    a,r,d=parse(fixture.encode())
    assert a==["Baden-Württemberg","Deutschland"] and r[1951]==[99.53,85.57] and r[1952][0] is None and d=="20261102"
    print("Parser self-test OK")
if __name__=="__main__":
    import sys
    if "--selftest" in sys.argv: selftest()
    else: build()
