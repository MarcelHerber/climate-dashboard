/* Direct GEFS–ECMWF ENS U60N/10hPa forecast comparison.
   Reuses strictly validated, identical-UTC-hour data already loaded by
   stratosphere_ecmwf_ens.js; never combines 00 UTC with 12 UTC forecasts.
   Wind reversal marker = FIRST sampled transition U >= 0 to U < 0 per member.
   It is not a Major SSW forecast and does not imply an onset between samples.
*/
(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const finite = n => typeof n === 'number' && Number.isFinite(n) && n > -160 && n < 170;
  const average = arr => arr.reduce((sum, value) => sum + value, 0) / arr.length;
  const percentile = (values, fraction) => {
    const sorted = [...values].sort((a,b) => a-b);
    const at = (sorted.length-1)*fraction, lo = Math.floor(at), hi = Math.min(sorted.length-1,lo+1);
    return sorted[lo] + (sorted[hi]-sorted[lo])*(at-lo);
  };

  function summarize(data, hour, model) {
    const count=model==='gefs'?31:51;
    const source=model==='gefs'?'NOAA GEFS':'ECMWF IFS ENS';
    if (!data || data.provider!==source || data.level_hpa!==10 ||
      data.latitude_deg!==60 || data.units!=='m/s' ||
      Number(data.cycle_utc?.slice(11,13))!==hour ||
      !Array.isArray(data.valid_dates) || !data.valid_dates.length ||
      Object.keys(data.members||{}).length!==count) return null;
    const arrays=Object.values(data.members);
    if (arrays.some(values=>!Array.isArray(values) ||
      values.length!==data.valid_dates.length || !values.every(finite))) return null;
    if (!arrays.every(arr=>arr.length===data.valid_dates.length)) return null;
    const firstCrossings=Array(data.valid_dates.length).fill(0);
    let crossed=0;
    for(const member of arrays) {
      for(let i=1;i<member.length;i++){
        if(member[i-1]>=0 && member[i]<0) {
          firstCrossings[i]++;
          crossed++;
          break; // A member can only register its first reversal once.
        }
      }
    }
    const rows=data.valid_dates.map((date,i)=>{
      const points=arrays.map(values=>values[i]);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw Error('Malformed forecast date');
      const negative=points.filter(v=>v<0).length;
      return {date,mean:average(points),p05:percentile(points,.05),
        p25:percentile(points,.25),p75:percentile(points,.75),
        p95:percentile(points,.95),control:data.members.c00?.[i]??null,
        negative,first:firstCrossings[i],total:count};
    });
    return {model,count,cycle:data.cycle_utc,hour,rows,crossed};
  }

  function align(gefs,eps) {
    if(!gefs||!eps)return [];
    const gmap=new Map(gefs.rows.map(row=>[row.date,row]));
    const emap=new Map(eps.rows.map(row=>[row.date,row]));
    return [...gmap.keys()].filter(date=>emap.has(date)).sort()
      .map(date=>({date,g:gmap.get(date),e:emap.get(date)}));
  }

  window.stratoJointMath={summarize,align,percentile};
  const root=$('stratoJointPanel');
  if(!root)return;

  let comparison=null, chart=null, currentRows=[], stats=null;
  function setStatus(message) {$('stratoJointStatus').textContent=message;}
  function fmt(value,d=1) {return Number.isFinite(value)?value.toLocaleString('de-DE',{maximumFractionDigits:d,minimumFractionDigits:d}):'–';}
  function destroyChart() {if(chart){chart.destroy();chart=null;}}
  const line=(label,values,color,width=2,options={})=>({
    label,data:values,borderColor:color,backgroundColor:color,
    borderWidth:width,pointRadius:0,pointHoverRadius:4,
    spanGaps:false,tension:0,fill:false,...options
  });
  function band(rows,model,low,high,label,color) {
    return [
      line('_'+label+' Untergrenze',rows.map(row=>row[model][low]),'transparent',0),
      line(label,rows.map(row=>row[model][high]),'transparent',0,
        {fill:{target:'-1',above:color,below:color}})
    ];
  }
  function updateMarkers(rows) {
    const tbody=$('stratoJointReversals');
    tbody.replaceChildren();
    const reversed=rows.filter(row=>row.g.first>0 || row.e.first>0);
    if(!reversed.length) {
      const tr=document.createElement('tr'),td=document.createElement('td');
      td.colSpan=5;td.textContent='Keine neue Windumkehr zwischen den vorliegenden Tageswerten prognostiziert.';
      tr.append(td);tbody.append(tr);return;
    }
    for(const row of reversed) {
      const tr=document.createElement('tr');
      const cells=[
        row.date,
        row.g.first+' / 31',
        row.e.first+' / 51',
        row.g.negative+' / 31',
        row.e.negative+' / 51'
      ];
      for(const cell of cells) {
        const td=document.createElement('td');td.textContent=cell;tr.append(td);
      }
      tbody.append(tr);
    }
  }

  function render() {
    const hour=Number($('stratoJointHour').value);
    const raw=comparison?.hour===hour?comparison:null;
    stats={g:summarize(raw?.gefs,hour,'gefs'),e:summarize(raw?.eps,hour,'eps')};
    currentRows=align(stats.g,stats.e);
    $('stratoJointGefsCycle').textContent=stats.g?.cycle||'nicht verfügbar';
    $('stratoJointEpsCycle').textContent=stats.e?.cycle||'nicht verfügbar';
    $('stratoJointGefsCross').textContent=stats.g?stats.g.crossed+'/31 Mitglieder':'–';
    $('stratoJointEpsCross').textContent=stats.e?stats.e.crossed+'/51 Mitglieder':'–';
    $('stratoJointOverlap').textContent=currentRows.length+' gemeinsame Tage';
    $('stratoJointPng').disabled=!currentRows.length;
    $('stratoJointCsv').disabled=!currentRows.length;
    updateMarkers(currentRows);
    destroyChart();
    if(!stats.g||!stats.e) {
      setStatus('Für '+String(hour).padStart(2,'0')+
        ' UTC fehlen aktuell gültige GEFS- oder ECMWF-ENS-Originaldaten. Kein Ersatz durch einen anderen UTC-Lauf.');
      return;
    }
    if(!currentRows.length) {
      setStatus('Es sind keine gemeinsamen Gültigkeitsdaten vorhanden; die Reihen werden nicht interpoliert.');
      return;
    }
    const labels=currentRows.map(row=>row.date);
    const sets=[
      ...band(currentRows,'g','p05','p95','GEFS · 5–95 %','#2575ba24'),
      ...band(currentRows,'e','p05','p95','ECMWF ENS · 5–95 %','#de74412d'),
      ...band(currentRows,'g','p25','p75','GEFS · 25–75 %','#2575ba50'),
      ...band(currentRows,'e','p25','p75','ECMWF ENS · 25–75 %','#de74414d'),
      line('GEFS · Ensemble-Mittel',currentRows.map(row=>row.g.mean),'#1167ac',3.2),
      line('ECMWF ENS · Ensemble-Mittel',currentRows.map(row=>row.e.mean),'#c34825',3.2),
      line('GEFS · Kontrolllauf',currentRows.map(row=>row.g.control),'#1167ac',1.8,{borderDash:[7,4]}),
      line('ECMWF ENS · Kontrolllauf',currentRows.map(row=>row.e.control),'#c34825',1.8,{borderDash:[7,4]}),
      line('GEFS · erste Member-Windumkehr',currentRows.map(row=>row.g.first>0?0:null),'#1768b2',0,
        {showLine:false,pointRadius:7,pointHoverRadius:9,pointStyle:'triangle',backgroundColor:'#1768b2'}),
      line('ECMWF ENS · erste Member-Windumkehr',currentRows.map(row=>row.e.first>0?0:null),'#ba3c22',0,
        {showLine:false,pointRadius:6,pointHoverRadius:8,pointStyle:'rectRot',backgroundColor:'#ba3c22'}),
      line('0 m/s · Windumkehrschwelle',labels.map(()=>0),'#263f55',1.3,{borderDash:[4,4]})
    ];
    chart=new Chart($('stratoJointCanvas'),{
      type:'line',data:{labels,datasets:sets},
      options:{responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
        interaction:{mode:'nearest',intersect:false},
        plugins:{legend:{display:false},tooltip:{callbacks:{
          title:items=>items[0]?.label+' · '+String(hour).padStart(2,'0')+' UTC',
          label:item=>{
            const row=currentRows[item.dataIndex];
            if(item.dataset.label.includes('erste Member-Windumkehr')) {
              const target=item.dataset.label.startsWith('GEFS')?row.g:row.e;
              return item.dataset.label+': '+target.first+'/'+target.total+
                ' erstmalige Übergänge; am Tag '+target.negative+'/'+target.total+' bei U < 0 m/s';
            }
            return item.dataset.label+': '+fmt(item.parsed.y,2)+' m/s';
          }
        }}},
        scales:{x:{ticks:{maxTicksLimit:12,maxRotation:0},grid:{display:false},
          title:{display:true,text:'Gültigkeitsdatum · '+String(hour).padStart(2,'0')+' UTC'}},
          y:{title:{display:true,text:'Zonal gemittelter Wind (m/s)'}}}
      }
    });
    const peakG=currentRows.reduce((p,row)=>Math.max(p,row.g.negative),0);
    const peakE=currentRows.reduce((p,row)=>Math.max(p,row.e.negative),0);
    setStatus('Vergleich nur gemeinsamer '+String(hour).padStart(2,'0')+'-UTC-Termine: '+currentRows.length+
      ' Tage. Höchster Tagesanteil mit U < 0 m/s: GEFS '+peakG+'/31, ECMWF ENS '+peakE+
      '/51. Dreiecke/Rauten markieren erstmalige Übergänge einzelner Mitglieder, keine bestätigten Major SSW.');
  }

  $('stratoJointHour').addEventListener('change',()=>{
    const hour=$('stratoJointHour').value;
    const other=$('stratoCompareHour');
    if(other && other.value!==hour) {
      other.value=hour;
      other.dispatchEvent(new Event('change',{bubbles:true}));
    } else render();
  });
  window.addEventListener('stratosphere:joint-data-ready',event=>{
    comparison=event.detail||null;
    if(comparison && $('stratoJointHour').value!==String(comparison.hour).padStart(2,'0')) {
      $('stratoJointHour').value=String(comparison.hour).padStart(2,'0');
    }
    render();
  });

  $('stratoJointPng').addEventListener('click',()=>{
    if(!chart)return;
    const hour=String(stats.g.hour).padStart(2,'0');
    const image=window.stratoChartExport.fromChart(chart,{
      title:'Polarwirbel · GEFS vs. ECMWF ENS · 60° N / 10 hPa',
      subtitle:'Zonalwind · gemeinsame Gültigkeitsdaten '+hour+' UTC · GEFS-Lauf '+
        stats.g.cycle+' · ECMWF-ENS-Lauf '+stats.e.cycle,
      source:'Quelle: NOAA GEFS / ECMWF IFS ENS · Windumkehrmarker ≠ bestätigtes Major SSW'
    });
    const a=document.createElement('a');a.href=image.toDataURL('image/png');
    a.download='Stratosphaere_GEFS_ECMWF_ENS_Zonalwind_'+hour+'UTC.png';
    document.body.append(a);a.click();a.remove();
  });
  $('stratoJointCsv').addEventListener('click',()=>{
    if(!currentRows.length)return;
    const header=['date_utc','hour_utc','gefs_mean_ms','eps_mean_ms',
      'gefs_p05','gefs_p25','gefs_p75','gefs_p95','eps_p05','eps_p25','eps_p75','eps_p95',
      'gefs_control_ms','eps_control_ms','gefs_first_reversal_n','eps_first_reversal_n',
      'gefs_negative_daily_n','eps_negative_daily_n'];
    const all=[header.join(';'),...currentRows.map(row=>[
      row.date,String(stats.g.hour).padStart(2,'0'),
      row.g.mean,row.e.mean,row.g.p05,row.g.p25,row.g.p75,row.g.p95,
      row.e.p05,row.e.p25,row.e.p75,row.e.p95,row.g.control,row.e.control,
      row.g.first,row.e.first,row.g.negative,row.e.negative
    ].join(';'))];
    const url=URL.createObjectURL(new Blob(['\ufeff'+all.join('\r\n')],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;
    a.download='Stratosphaere_GEFS_ECMWF_ENS_Zonalwind_'+
      String(stats.g.hour).padStart(2,'0')+'UTC.csv';
    document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),3000);
  });

  if(window.stratoJointForecastData){
    comparison=window.stratoJointForecastData;
    $('stratoJointHour').value=String(comparison.hour).padStart(2,'0');
    render();
  }
})();
