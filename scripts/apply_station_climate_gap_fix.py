from pathlib import Path

path = Path("index.html")
text = path.read_text(encoding="utf-8")

old = '''    const barRows=historical.map(item=>({year:String(item.year),count:item.count,validDays:item.validDays,current:false}));
    if(currentPeriod.elapsedDays>0){
      barRows.push({year:currentLabel,count:currentPeriod.count,validDays:currentPeriod.validDays,current:true});
    }
    if(stationClimateDaysBarChart) stationClimateDaysBarChart.destroy();
    stationClimateDaysBarChart=new Chart(document.getElementById("stationClimateDaysBarChart"),{
      type:"bar",
      data:{
        labels:barRows.map(item=>item.year),
        datasets:[{
          label:metric.label,
          data:barRows.map(item=>item.count),
          backgroundColor:barRows.map(item=>item.current?(metric.color||"#c43d2f"):stationClimateDaysHexToRgba(metric.color,.58)),
          borderColor:barRows.map(item=>item.current?"#111":stationClimateDaysHexToRgba(metric.color,.85)),
          borderWidth:barRows.map(item=>item.current?2:0)
        }]
      },
      options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{
          title:{display:true,text:`${metric.label} je ${period.label} – ${station.name}`},
          datalabels:{display:false},
          tooltip:{callbacks:{afterLabel:context=>{
            const row=barRows[context.dataIndex];
            return row.current?"Aktueller, gegebenenfalls noch unvollständiger Zeitraum":`${row.validDays} gültige Tageswerte`;
          }}},
          zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
        },
        scales:{
          x:{ticks:{maxTicksLimit:20,maxRotation:60,minRotation:0}},
          y:{beginAtZero:true,ticks:{precision:0},title:{display:true,text:"Anzahl der Kenntage"}}
        }
      }
    });'''

new = '''    const historicalByYear=new Map(historical.map(item=>[Number(item.year),item]));
    const historyStart=Number(station.start_year);
    const historyEnd=Number(station.end_year);
    const barRows=[];
    if(Number.isFinite(historyStart) && Number.isFinite(historyEnd) && historyEnd>=historyStart){
      for(let year=historyStart;year<=historyEnd;year++){
        const item=historicalByYear.get(year);
        barRows.push(item
          ?{year:String(year),count:item.count,validDays:item.validDays,current:false,noData:false}
          :{year:String(year),count:null,validDays:0,current:false,noData:true});
      }
    }else{
      historical.forEach(item=>barRows.push({year:String(item.year),count:item.count,validDays:item.validDays,current:false,noData:false}));
    }
    if(currentPeriod.elapsedDays>0){
      const currentHasData=currentPeriod.validDays>0;
      barRows.push({
        year:currentLabel,
        count:currentHasData?currentPeriod.count:null,
        validDays:currentPeriod.validDays,
        current:true,
        noData:!currentHasData
      });
    }
    const realCounts=barRows.filter(item=>!item.noData && Number.isFinite(Number(item.count))).map(item=>Number(item.count));
    const highestRealBar=realCounts.length?Math.max(...realCounts):0;
    const noDataHeight=highestRealBar>0?highestRealBar*0.5:1;
    const hasNoDataBars=barRows.some(item=>item.noData);

    if(stationClimateDaysBarChart) stationClimateDaysBarChart.destroy();
    stationClimateDaysBarChart=new Chart(document.getElementById("stationClimateDaysBarChart"),{
      type:"bar",
      data:{
        labels:barRows.map(item=>item.year),
        datasets:[
          {
            label:metric.label,
            data:barRows.map(item=>item.noData?null:item.count),
            backgroundColor:barRows.map(item=>item.current?(metric.color||"#c43d2f"):stationClimateDaysHexToRgba(metric.color,.58)),
            borderColor:barRows.map(item=>item.current?"#111":stationClimateDaysHexToRgba(metric.color,.85)),
            borderWidth:barRows.map(item=>item.current?2:0),
            grouped:false
          },
          {
            label:"Keine Daten",
            data:barRows.map(item=>item.noData?noDataHeight:null),
            backgroundColor:"rgba(145,145,145,.34)",
            borderColor:"#707070",
            borderWidth:2,
            borderDash:[6,4],
            borderSkipped:false,
            grouped:false,
            isNoDataDataset:true
          }
        ]
      },
      options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{
          title:{display:true,text:`${metric.label} je ${period.label} – ${station.name}`},
          subtitle:{display:hasNoDataBars,text:"Grau gestrichelt: keine Daten vorhanden · Platzhalterhöhe = 50 % des höchsten Messwerts",color:"#666",font:{size:12},padding:{bottom:8}},
          legend:{labels:{filter:item=>item.text!=="Keine Daten"}},
          datalabels:{display:false},
          tooltip:{
            filter:context=>{
              const row=barRows[context.dataIndex];
              return context.dataset.isNoDataDataset?Boolean(row?.noData):!row?.noData;
            },
            callbacks:{
              label:context=>{
                const row=barRows[context.dataIndex];
                if(row?.noData) return "Keine Daten vorhanden";
                return `${metric.label}: ${row.count} ${row.count===1?"Tag":"Tage"}`;
              },
              afterLabel:context=>{
                const row=barRows[context.dataIndex];
                if(row?.noData) return "";
                return row.current?"Aktueller, gegebenenfalls noch unvollständiger Zeitraum":`${row.validDays} gültige Tageswerte`;
              }
            }
          },
          zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
        },
        scales:{
          x:{ticks:{maxTicksLimit:20,maxRotation:60,minRotation:0}},
          y:{beginAtZero:true,ticks:{precision:0},title:{display:true,text:"Anzahl der Kenntage"}}
        }
      }
    });'''

count = text.count(old)
if count != 1:
    raise SystemExit(f"Sicherheitsabbruch: erwarteter Kenntage-Block {count}x gefunden (erwartet 1x). index.html bleibt unverändert.")

patched = text.replace(old, new, 1)

# Sicherheitsprüfungen gegen genau den Fehler, der zuvor passiert ist.
if len(patched) < len(text) - 1000:
    raise SystemExit("Sicherheitsabbruch: Patch würde die index.html unerwartet verkleinern.")
if patched.count('Grau gestrichelt: keine Daten vorhanden') != 1:
    raise SystemExit("Sicherheitsabbruch: Datenlücken-Markierung nicht eindeutig eingefügt.")
if 'highestRealBar*0.5' not in patched:
    raise SystemExit("Sicherheitsabbruch: gewünschte 50%-Höhe fehlt.")
if 'if(row?.noData) return "Keine Daten vorhanden";' not in patched:
    raise SystemExit("Sicherheitsabbruch: Tooltip für Datenlücken fehlt.")

path.write_text(patched, encoding="utf-8")
print(f"OK: index.html sicher gepatcht ({len(text)} -> {len(patched)} Zeichen).")
