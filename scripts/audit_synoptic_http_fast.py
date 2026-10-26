#!/usr/bin/env python3
"""Fast bounded HTTP + direct-image audit. It does not certify visual contents."""
import concurrent.futures as futures
import datetime as dt
import io
import json
import re
import threading
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
NOW=dt.datetime.now(dt.timezone.utc).isoformat()
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
limit=threading.Lock()
locks={}
def extract(path,prefix,suffix):
    s=(ROOT/path).read_text(encoding="utf-8");p=s.index(prefix)+len(prefix);q=s.index(suffix,p)
    return json.loads(s[p:q]+("]" if suffix=="];" else ""))
world=extract("weltweite_isobaren.html","const DATA=",";const REGIONS=")
eu=extract("isobaren_original.js","const CURATED_SOURCES=","];")
urls={}
for label,arr in [("weltweit",world),("original",eu)]:
    for x in arr:
        u=x.get("url","")
        if u.startswith("https://") or u.startswith("http://"):
            record=urls.setdefault(u,{"url":u,"sources":[],"pages":[]})
            record["sources"].append(x.get("name",""))
            record["pages"].append(label)

def get_response(s,url,max_bytes=4000000,timeout=(7,14)):
    r=s.get(url,allow_redirects=True,timeout=timeout,stream=True,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,image/*,*/*;q=0.8"})
    content=b""
    for chunk in r.iter_content(65536):
        if chunk:
            content+=chunk
        if len(content)>=max_bytes:break
    return r,content

def check(item):
    url=item["url"];host=urlsplit(url).netloc
    with limit:
        sem=locks.setdefault(host,threading.Semaphore(2))
    out=dict(item,status=None,final_url=None,mime=None,bytes_received=0,
             image_width=None,image_height=None,
             image_followup=None,followup_status=None,followup_mime=None,
             detected_title="",chart_terms=[],error="",classification="unresolved",checked_utc=NOW)
    with sem:
        try:
            with requests.Session() as sess:
                r,body=get_response(sess,url)
                out["status"]=r.status_code
                out["final_url"]=r.url
                out["mime"]=r.headers.get("Content-Type","")[:120]
                out["bytes_received"]=len(body)
                mim=(out["mime"] or "").lower()
                if r.status_code in [403,429]:out["classification"]="access_denied_not_proven_dead"
                elif r.status_code in [404,410]:out["classification"]="http_missing"
                elif r.status_code>=500:out["classification"]="http_server_error"
                elif r.status_code>=400:out["classification"]="http_other_error"
                elif "image/" in mim:
                    try:
                        im=Image.open(io.BytesIO(body));out["image_width"],out["image_height"]=im.size
                        out["classification"]="direct_image_valid_bytes_not_content_certified"
                    except Exception as exc:
                        out["classification"]="image_bytes_invalid_or_truncated";out["error"]=str(exc)[:110]
                elif "text/html" in mim or b"<html" in body[:500].lower():
                    soup=BeautifulSoup(body[:4000000],"html.parser")
                    out["detected_title"]=(soup.title.get_text(" ",strip=True) if soup.title else "")[:170]
                    text=soup.get_text(" ",strip=True)[:5000]
                    out["chart_terms"]=list(dict.fromkeys(re.findall(r"surface analysis|isobar|synoptic|front(?:en|al|s)?|mslp|bodenanalyse|carta sin[oó]ptica|analyse de surface|analysekaart|weather chart",text,re.I)))[:10]
                    out["classification"]="html_reached_not_visual_certified"
                    candidates=[]
                    for tag in soup.find_all("img",src=True):
                        src=urljoin(r.url,tag.get("src",""))
                        alt=tag.get("alt","")
                        if not src.startswith("http"):continue
                        score=3*int(bool(re.search(r"chart|anal|front|isobar|synop|surface|pressure|weather.map|mslp",src+" "+alt,re.I)))
                        score+=int(bool(re.search(r"chart|map",alt,re.I)))
                        candidates.append((score,src))
                    candidates.sort(key=lambda z:-z[0])
                    if candidates:
                        out["image_followup"]=candidates[0][1]
                        try:
                            imr,imgdata=get_response(sess,candidates[0][1],max_bytes=5000000,timeout=(5,10))
                            out["followup_status"]=imr.status_code
                            out["followup_mime"]=imr.headers.get("Content-Type","")[:100]
                            if imr.status_code==200 and "image" in (out["followup_mime"] or "").lower():
                                try:
                                    image=Image.open(io.BytesIO(imgdata))
                                    out["image_width"],out["image_height"]=image.size
                                except Exception:pass
                        except Exception as e:out["error"]="image follow-up: "+str(e)[:170]
                elif "pdf" in mim:out["classification"]="pdf_reachable_not_visually_checked"
                elif "json" in mim:out["classification"]="api_reachable_not_map_validated"
                else:out["classification"]="other_content_type"
        except requests.exceptions.Timeout:out["classification"]="timeout";out["error"]="request_timeout"
        except Exception as e:out["classification"]="request_error";out["error"]=str(e)[:230]
    return out

with futures.ThreadPoolExecutor(max_workers=14) as ex:
    entries=list(ex.map(check,list(urls.values())))
from collections import Counter
counts=dict(Counter(x["classification"] for x in entries))
report={"schema_version":1,"checked_utc":NOW,"unique_urls":len(entries),
        "world_entries":len(world),"original_entries":len(eu),"classifications":counts,
        "note":"Jede URL per HTTP GET geprüft; bei HTML erster passender img-Link separat geladen. JavaScript-gerenderte Seiten können nicht durch diesen HTTP-Durchlauf visuell bestätigt werden. 403 ist kein kaputter Link. Tatsächliche Karte, UTC-Gültigkeit und Nutzungsrechte müssen im separaten Chromium-Screenshot-Audit bestätigt werden.",
        "results":entries}
path=ROOT/"data/synoptic_charts/isobaren_http_probe_latest.json"
path.parent.mkdir(exist_ok=True,parents=True)
path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("FAST_HTTP_AUDIT "+json.dumps({"urls":len(entries),"classification":counts},ensure_ascii=False),flush=True)
