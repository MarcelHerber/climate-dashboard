#!/usr/bin/env python3
from __future__ import annotations

import csv, html, io, math, re, sys, time, urllib.request, zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser

BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl"
RECENT = BASE + "/recent/"
META = RECENT + "KL_Tageswerte_Beschreibung_Stationen.txt"
OVERVIEW = BASE + "/timeseries_overview/"
UA = "climate-dashboard-dwd-snow-probe/1.0"
WORKERS = 10

STATES = (
    "Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg",
    "Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen",
    "Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt",
    "Schleswig-Holstein","Thüringen",
)
ALIASES = {
    "Baden-Wuerttemberg":"Baden-Württemberg",
    "Baden Württemberg":"Baden-Württemberg",
    "Mecklenburg Vorpommern":"Mecklenburg-Vorpommern",
    "Nordrhein Westfalen":"Nordrhein-Westfalen",
    "Rheinland Pfalz":"Rheinland-Pfalz",
    "Sachsen Anhalt":"Sachsen-Anhalt",
    "Schleswig Holstein":"Schleswig-Holstein",
}

@dataclass(frozen=True)
class Meta:
    sid: str
    name: str
    state: str
    height: float | None

@dataclass(frozen=True)
class Overview:
    sid: str
    start: str
    end: str
    span: float
    missing: float
    gap: str
    name: str
    state: str
    @property
    def net(self): return max(0.0, self.span - self.missing)

class Table(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="tr": self.row=[]
        elif tag.lower() in ("td","th") and self.row is not None: self.cell=[]
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag in ("td","th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join(html.unescape("".join(self.cell)).split())); self.cell=None
        elif tag=="tr" and self.row is not None:
            if self.row: self.rows.append(self.row)
            self.row=None; self.cell=None

def get(url, tries=4):
    last=None
    for n in range(tries):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":UA,"Accept-Encoding":"identity"})
            with urllib.request.urlopen(req, timeout=90) as r: return r.read()
        except Exception as e:
            last=e
            if n+1<tries: time.sleep(1.5*(n+1))
    raise RuntimeError(f"Abruf fehlgeschlagen {url}: {last}")

def text(url):
    raw=get(url)
    for enc in ("utf-8","cp1252","latin-1"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    return raw.decode("latin-1",errors="replace")

def norm_state(v):
    v=" ".join(v.strip().split()); v=ALIASES.get(v,v)
    return v if v in STATES else "Unbekannt"

def parse_meta(s):
    lines=s.splitlines()
    hi=next((i for i,l in enumerate(lines) if "Stations_id" in l and "Bundesland" in l),None)
    if hi is None: raise RuntimeError("Stationskopf fehlt")
    rx=re.compile(r"^\s*(\d{1,5})\s+(\d{8})\s+(\d{8})\s+(-?\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)\s+(.+?)\s*$")
    state_patterns=[(x,re.compile(rf"(?<!\S){re.escape(x)}(?=\s|$)")) for x in sorted(set(STATES)|set(ALIASES),key=len,reverse=True)]
    out={}
    for line in lines[hi+1:]:
        m=rx.match(line.rstrip())
        if not m: continue
        sid,_,_,h,_,_,tail=m.groups()
        best=None; pos=-1
        for raw,p in state_patterns:
            for sm in p.finditer(tail):
                if sm.start()>pos: best=raw; pos=sm.start()
        name=tail[:pos].strip() if best else tail.strip()
        try: height=float(h.replace(",","."))
        except: height=None
        out[sid.zfill(5)]=Meta(sid.zfill(5),name or sid.zfill(5),norm_state(best or ""),height)
    if len(out)<300: raise RuntimeError(f"Nur {len(out)} Metadaten")
    if sum(x.state!="Unbekannt" for x in out.values())<100: raise RuntimeError("Bundesländer nicht erkannt")
    return out

def recent_files():
    s=text(RECENT)
    out={sid:fn for fn,sid in re.findall(r"(tageswerte_KL_(\d{5})_akt\.zip)",s,re.I)}
    if len(out)<300: raise RuntimeError(f"Nur {len(out)} Recent-KL-ZIPs")
    return out

def scan_zip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.lower().endswith(".txt") and n.split("/")[-1].lower().startswith("produkt_")]
        if not names: raise RuntimeError("produkt_*.txt fehlt")
        b=z.read(names[0])
    s=b.decode("utf-8",errors="replace")
    if "MESS_DATUM" not in s: s=b.decode("cp1252",errors="replace")
    r=csv.DictReader(io.StringIO(s),delimiter=";")
    fields=[(f or "").strip() for f in (r.fieldnames or [])]
    lut={f.upper():f for f in fields}
    shk=lut.get("SHK_TAG") or lut.get("SHK")
    if not shk: raise RuntimeError(f"SHK_TAG fehlt: {fields}")
    vals=[]
    for rr in r:
        row={(k or "").strip():(v.strip() if isinstance(v,str) else v) for k,v in rr.items()}
        d=str(row.get("MESS_DATUM") or "")
        try: day=__import__("datetime").datetime.strptime(d,"%Y%m%d")
        except: continue
        try: v=float(str(row.get(shk)).replace(",","."))
        except: continue
        if math.isfinite(v) and 0<=v<1000: vals.append((day,v))
    vals.sort()
    return vals,fields

def scan_one(sid,fn):
    try:
        vals,fields=scan_zip(get(RECENT+fn))
        if not vals: return sid,None,None
        md,mv=max(vals,key=lambda x:x[1])
        return sid,{"first":vals[0][0],"last":vals[-1][0],"latest":vals[-1][1],"max":mv,"max_day":md,"count":len(vals),"positive":sum(v>0 for _,v in vals)},None
    except Exception as e: return sid,None,str(e)

def fnum(s):
    s=s.strip().replace(",",".")
    if s.startswith("."): s="0"+s
    return 0.0 if s in ("","-","–") else float(s)

def overview(years):
    url=OVERVIEW+f"ZeitReihen_klima_tag_GE_{years}Jahre_SHK_TAG.html"
    p=Table(); p.feed(text(url)); out={}
    for c in p.rows:
        if len(c)<9 or not c[0].strip().isdigit(): continue
        try:
            sid=c[0].zfill(5); span=fnum(c[3]); miss=fnum(c[4])
        except: continue
        out[sid]=Overview(sid,c[1],c[2],span,miss,c[6],c[7],norm_state(c[8]))
    if not out: raise RuntimeError(f"Übersicht {years} Jahre leer")
    return out

def main():
    print("=== DWD SCHNEEHÖHE · SCHRITT 1 ===",flush=True)
    print("Parameter: SHK_TAG = tägliche Schneehöhe [cm]",flush=True)
    print("Noch kein historischer Vollaufbau / keine Website-Änderung.\n",flush=True)

    meta=parse_meta(text(META)); files=recent_files()
    print(f"Stationsmetadaten: {len(meta):,}",flush=True)
    print(f"Aktuelle KL-ZIPs: {len(files):,}",flush=True)
    print("Prüfe Recent-KL-ZIPs auf echte SHK_TAG-Werte ...",flush=True)

    usable={}; errors=[]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fut={ex.submit(scan_one,sid,fn):sid for sid,fn in files.items()}
        for i,f in enumerate(as_completed(fut),1):
            sid,info,err=f.result()
            if info: usable[sid]=info
            if err: errors.append(f"{sid}: {err}")
            if i%50==0 or i==len(fut):
                print(f"  geprüft {i:,}/{len(fut):,} | mit gültigem SHK_TAG: {len(usable):,}",flush=True)

    active=set(usable)
    print("\n=== AKTIVE SCHNEEHÖHENSTATIONEN ===",flush=True)
    print(f"Aktuelle Stationen mit gültigem SHK_TAG: {len(active):,}",flush=True)
    cnt=Counter(meta[s].state for s in active if s in meta)
    for state in STATES: print(f"  {state}: {cnt.get(state,0)}",flush=True)
    if cnt.get("Unbekannt"): print(f"  Unbekannt: {cnt['Unbekannt']}",flush=True)

    o30,o50,o100=overview(30),overview(50),overview(100)
    print("\n=== DWD-LANGZEITÜBERSICHT ===",flush=True)
    print(f"Alle DWD-SHK-Reihen >=30 Jahre Spanne: {len(o30):,}",flush=True)
    print(f"Alle DWD-SHK-Reihen >=50 Jahre Spanne: {len(o50):,}",flush=True)
    print(f"Alle DWD-SHK-Reihen >=100 Jahre Spanne: {len(o100):,}",flush=True)
    a30=active & set(o30); a50=active & set(o50); a100=active & set(o100)
    print("\nDavon aktuell aktiv mit SHK_TAG:",flush=True)
    print(f"  >=30 Jahre Spanne: {len(a30):,}",flush=True)
    print(f"  >=50 Jahre Spanne: {len(a50):,}",flush=True)
    print(f"  >=100 Jahre Spanne: {len(a100):,}",flush=True)

    n30={s for s in a30 if o30[s].net>=30}
    n50={s for s in a30 if o30[s].net>=50}
    n100={s for s in a30 if o30[s].net>=100}
    print("\nKonservativ: Anzahl_Jahre minus Fehl_Jahre:",flush=True)
    print(f"  >=30 Netto-Jahre: {len(n30):,}",flush=True)
    print(f"  >=50 Netto-Jahre: {len(n50):,}",flush=True)
    print(f"  >=100 Netto-Jahre: {len(n100):,}",flush=True)

    print("\n=== LÄNGSTE AKTUELLEN REIHEN ===",flush=True)
    rows=sorted((o30[s] for s in active if s in o30),key=lambda r:(r.net,r.span),reverse=True)
    for r in rows[:40]:
        m=meta.get(r.sid)
        state=m.state if m else r.state
        h=f"{m.height:.0f} m" if m and m.height is not None else "?"
        gap=r.gap if r.gap not in ("","-") else "kein >=25-J.-Gap"
        print(f"{r.sid} | {r.name} | {state} | {h} | {r.start}–{r.end} | Spanne {r.span:.1f} J. | Fehl {r.missing:.1f} J. | netto {r.net:.1f} J. | {gap}",flush=True)

    print("\n=== RECENT-STICHPROBEN ===",flush=True)
    wanted=("Zugspitze","Brocken","Fichtelberg","Wasserkuppe","Oberstdorf","Kahler","Braunlage","Freiburg","Frankfurt","Saarbrücken")
    samples=[]
    for w in wanted:
        mm=[s for s in active if s in meta and w.casefold() in meta[s].name.casefold()]
        if mm:
            s=sorted(mm)[0]
            if s not in samples: samples.append(s)
    for s in samples[:10]:
        i=usable[s]; m=meta[s]; r=o30.get(s)
        ser=f"{r.span:.1f} J. Spanne / {r.net:.1f} Netto-J." if r else "<30 J."
        print(f"{s} | {m.name} | {m.state} | Recent {i['first']:%d.%m.%Y}–{i['last']:%d.%m.%Y} | {i['count']} gültige Tage | {i['positive']} Tage >0 cm | letzter {i['latest']:.1f} cm | Recent-Max {i['max']:.1f} cm am {i['max_day']:%d.%m.%Y} | {ser}",flush=True)

    print("\n=== FAZIT FÜR SCHRITT 2 ===",flush=True)
    print("Für den Vollaufbau würde ich aktive Stationen mit mindestens 30 Netto-Jahren SHK_TAG verwenden.",flush=True)
    print("Dann berechnen wir aus den echten Tageswerten hydrologische Jahre 01.11.–31.10. vollständig neu.",flush=True)
    print("Referenz 1991–2020: hydrologische Jahre 1991…2020, also 01.11.1990–31.10.2020.",flush=True)
    if errors:
        print(f"\nEinzelfehler Recent-Scan: {len(errors)}",flush=True)
        for e in errors[:20]: print("  - "+e,flush=True)
    return 0

def self_test():
    lines=["Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge Stationsname Bundesland Abgabe",
           "01420 19490101 20261231 100 50.0 8.5 Frankfurt/Main Hessen extra"]
    for i in range(300): lines.append(f"{50000+i:05d} 20000101 20261231 100 50.0 8.0 Test {i} Bayern extra")
    m=parse_meta("\n".join(lines)); assert m["01420"].state=="Hessen"; assert m["01420"].name=="Frankfurt/Main"
    product=("STATIONS_ID;MESS_DATUM;QN_4;SHK_TAG;eor\n"
             "1420;20260101;10;0;eor\n1420;20260102;10;12;eor\n1420;20260103;10;-999;eor\n")
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w",zipfile.ZIP_DEFLATED) as z: z.writestr("produkt_klima_tag_test.txt",product)
    vals,_=scan_zip(b.getvalue()); assert len(vals)==2 and vals[-1][1]==12
    p=Table(); p.feed("<table><tr><td>1691</td><td>01.05.1858</td><td>13.05.2025</td><td>167.15</td><td>19.88</td><td>7258</td><td>-</td><td>Göttingen</td><td>Niedersachsen</td></tr></table>")
    assert p.rows[0][7]=="Göttingen"
    print("DWD snow-height probe self-test OK")

if __name__=="__main__":
    if "--self-test" in sys.argv: self_test()
    else: raise SystemExit(main())
