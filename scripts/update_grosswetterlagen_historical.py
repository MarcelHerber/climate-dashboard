"""Convert PIK Report 119, annex 7.2, to daily Hess/Brezowsky CSV.
Source: Werner & Gerstengarbe (2010), PIK Report 119, pp. 104ff.
The original PDF stays with its publisher. Reject incomplete or ambiguous tables.
"""
import argparse
import calendar
import csv
import re
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://publications.pik-potsdam.de/rest/items/item_16367_5/component/file_16368/content"
OUT = Path("data/grosswetterlagen/hb.csv")
MONTHS = dict(zip("JANUAR FEBRUAR MÄRZ APRIL MAI JUNI JULI AUGUST SEPTEMBER OKTOBER NOVEMBER DEZEMBER".split(), range(1,13)))
MONTHS.update({"MAERZ":3, "MARZ":3})
CODES = set("WA WZ WS WW SWA SWZ NWA NWZ HM BM TM NA NZ HNA HNZ HB TRM NEA NEZ HFA HFZ HNFA HNFZ SEA SEZ SA SZ TB TRW U".split())
# Page numbers rotated in the outer margin may share a row with table text.
# Permit numeric margin fragments only outside the two matching year labels.
ROW = re.compile(r"^[\s\d]*?(18\d{2}|19\d{2}|200\d)\s+(.+?)\s+\1[\s\d]*$")
START, END = date(1881,1,1), date(2009,12,31)

def parse_layout(text):
    rows = {}
    month = None
    for line in text.splitlines():
        words = line.strip().upper().split()
        if not words:
            continue
        if words[0] in MONTHS:
            month = MONTHS[words[0]]
        if month is None:
            continue
        match = ROW.fullmatch(line)
        if not match:
            continue
        year = int(match[1])
        if not 1881 <= year <= 2009:
            continue
        codes = match[2].upper().split()
        ndays = calendar.monthrange(year,month)[1]
        if len(codes)>ndays and all(x in ("-", "–", "—") for x in codes[ndays:]):
            codes = codes[:ndays]
        if len(codes) != ndays or not set(codes) <= CODES:
            raise ValueError(f"Ambiguous PIK row {year}-{month:02d}: {codes}")
        for day, code in enumerate(codes,1):
            d = date(year,month,day)
            if d in rows:
                raise ValueError(f"Duplicate date {d}")
            rows[d] = code
    expected = {START+timedelta(days=i) for i in range((END-START).days+1)}
    missing = expected-rows.keys()
    if missing or rows.keys()-expected:
        raise ValueError(f"Coverage mismatch: {len(rows)} days, {len(missing)} missing; affected months {sorted({d.isoformat()[:7] for d in missing})}")
    if set(rows.values()) != CODES:
        raise ValueError("Unexpected weather type coverage")
    if rows[START] != "HM" or rows[date(1882,1,1)] != "WA":
        raise ValueError("Published January sample does not match")
    return rows

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, help="Use a locally downloaded original PIK report")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        pdf = args.pdf or Path(tmp)/"report.pdf"
        if not args.pdf:
            with urlopen(Request(URL,headers={"User-Agent":"Climate Dashboard Deutschland"}),timeout=120) as res:
                pdf.write_bytes(res.read(40_000_001))
        if not pdf.read_bytes().startswith(b"%PDF-"):
            raise ValueError("Not an original PDF")
        layout = subprocess.check_output(["pdftotext","-f","104","-layout",str(pdf),"-"],text=True,encoding="utf-8")
        rows = parse_layout(layout)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.writer(stream,delimiter=";",lineterminator="\n")
        writer.writerow(("Datum","GWL"))
        writer.writerows((d.isoformat(),rows[d]) for d in sorted(rows))
    tmp.replace(OUT)
    print(f"Validated historical catalogue: {len(rows)} days, {START} to {END}, 29 GWL plus U")
if __name__=="__main__":
    main()
