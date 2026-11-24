#!/usr/bin/env python3
"""Cold mobile Chromium startup trace, CPU samples, task timings and DOM evidence."""
import collections
import gzip
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

url,variant=sys.argv[1:3]
out=Path("reports")/variant
out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel="chrome",headless=True)
    for run in range(1,4):
        ctx=browser.new_context(viewport={"width":390,"height":844},is_mobile=True,
            has_touch=True,device_scale_factor=2,service_workers="block")
        page=ctx.new_page()
        page.add_init_script("""window.__startup={longTasks:[],lcp:[]};
          try{new PerformanceObserver(l=>{for(const e of l.getEntries())
            window.__startup.longTasks.push({start:e.startTime,duration:e.duration,name:e.name});
          }).observe({type:'longtask',buffered:true});}catch(e){}
          try{new PerformanceObserver(l=>{for(const e of l.getEntries())
            window.__startup.lcp.push({start:e.startTime,size:e.size,element:e.element?.id||e.element?.tagName,url:e.url});
          }).observe({type:'largest-contentful-paint',buffered:true});}catch(e){}""")
        cdp=ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled",{"cacheDisabled":True})
        cdp.send("Network.emulateNetworkConditions",{"offline":False,"latency":150,
            "downloadThroughput":200000,"uploadThroughput":93750})
        cdp.send("Emulation.setCPUThrottlingRate",{"rate":4})
        cdp.send("Profiler.enable")
        cdp.send("Profiler.setSamplingInterval",{"interval":1000})
        cdp.send("Profiler.start")
        trace=[]
        cdp.on("Tracing.dataCollected",lambda e:trace.extend(e["value"]))
        done=[]
        cdp.on("Tracing.tracingComplete",lambda e:done.append(True))
        cdp.send("Tracing.start",{"categories":"devtools.timeline,blink.user_timing,loading,v8,disabled-by-default-devtools.timeline,disabled-by-default-devtools.timeline.stack","transferMode":"ReportEvents"})
        page.goto(url,wait_until="domcontentloaded",timeout=120000)
        page.wait_for_function("performance.now()>=12000",timeout=120000)
        evidence=page.evaluate("""() => ({
          longTasks:window.__startup.longTasks,lcp:window.__startup.lcp,
          domNodes:document.querySelectorAll('*').length,
          selects:[...document.querySelectorAll('select')].map(s=>({id:s.id,options:s.options.length})),
          canvases:[...document.querySelectorAll('canvas')].map(c=>({id:c.id,visible:!!c.getClientRects().length})),
          resources:performance.getEntriesByType('resource').map(e=>({url:e.name,initiator:e.initiatorType,
             start:e.startTime,end:e.responseEnd,transfer:e.transferSize,decoded:e.decodedBodySize})),
          nav:performance.getEntriesByType('navigation')[0]?.toJSON()
        })""")
        profile=cdp.send("Profiler.stop")["profile"]
        cdp.send("Tracing.end")
        for _ in range(100):
            if done:break
            page.wait_for_timeout(100)
        assert done,"incomplete Chromium trace"
        nodes={n["id"]:n["callFrame"] for n in profile["nodes"]}
        totals=collections.Counter()
        for ident,delta in zip(profile.get("samples",[]),profile.get("timeDeltas",[])):
            f=nodes.get(ident,{})
            label=f.get("functionName") or "(anonymous)"
            loc=f.get("url","")
            totals[(label,loc,f.get("lineNumber",-1)+1)]+=delta/1000
        evidence["cpu_self_ms_top30"]=[{"function":k[0],"url":k[1],"line":k[2],"ms":round(v,1)}
            for k,v in totals.most_common(30)]
        evidence["long_task_count"]=len(evidence["longTasks"])
        evidence["observed_blocking_ms_12s"]=round(sum(max(0,e["duration"]-50)
            for e in evidence["longTasks"]),1)
        # This 12s observation is not Lighthouse's TBT window.
        (out/f"startup-{run}.json").write_text(json.dumps(evidence,indent=2))
        (out/f"startup-{run}.cpuprofile").write_text(json.dumps(profile))
        with gzip.open(out/f"startup-{run}.trace.json.gz","wt") as f:
            json.dump({"traceEvents":trace},f)
        print(json.dumps({"variant":variant,"run":run,"dom":evidence["domNodes"],
            "long_tasks":evidence["long_task_count"],"blocking_12s":evidence["observed_blocking_ms_12s"],
            "cpu_top":evidence["cpu_self_ms_top30"][:15]}),flush=True)
        ctx.close()
    browser.close()
