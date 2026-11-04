/* A fully labeled, opaque white PNG export for Stratosphere Chart.js graphs.
   Include all VISIBLE series in an independent, printable legend. A shaded
   interval made of a hidden lower boundary and filled upper bound is one item.
   The export never changes the on-screen Chart.js legend or dataset visibility.
*/
(() => {
  'use strict';

  const getGroups = chart => {
    if (!chart?.data?.datasets) return [];
    const shared = window.stratoSeriesVisibility?.groups;
    if (typeof shared === 'function') return shared(chart);
    return chart.data.datasets.map((dataset, index) => ({
      indexes:[index],label:String(dataset.label || 'Datensatz ' + (index + 1)),
      color:String(dataset.borderColor || dataset.backgroundColor || '#475569'),
      filled:!!dataset.fill
    }));
  };
  const isVisible = (chart, item) => item.indexes.every(index => chart.isDatasetVisible(index));
  const visibleEntries = chart => getGroups(chart).filter(item => isVisible(chart,item)).map(item => {
    const dataset = chart.data.datasets[item.indexes[item.indexes.length - 1]];
    return {
      label:item.label,
      color:item.color,
      filled:item.filled,
      dashed:Array.isArray(dataset.borderDash) && dataset.borderDash.length > 0,
      type:dataset.type || chart.config?.type || 'line',
      member:item.member
    };
  });

  function wrapping(ctx, value, maxWidth) {
    const words = String(value).split(/\s+/).filter(Boolean), result = [];
    let line = '';
    for (const word of words) {
      const next = line ? line + ' ' + word : word;
      if (line && ctx.measureText(next).width > maxWidth) {
        result.push(line);
        line = word;
      } else {
        line = next;
      }
    }
    if (line) result.push(line);
    return result.length ? result : ['–'];
  }

  function createLayout(ctx, width, sections) {
    const scale = Math.max(1, Math.min(1.65, width / 960));
    const margin = Math.max(16, Math.round(20 * scale));
    const colGap = Math.round(16 * scale);
    const columns = width >= 1450 ? 4 : width >= 1050 ? 3 : width >= 650 ? 2 : 1;
    const colWidth = (width - 2 * margin - (columns - 1) * colGap) / columns;
    const font = Math.round(14 * scale);
    const lineHeight = Math.round(font * 1.34);
    const swatch = Math.round(27 * scale);
    const textMax = colWidth - swatch - Math.round(10 * scale);
    ctx.font = '500 ' + font + 'px Arial, Helvetica, sans-serif';

    let position = Math.round(42 * scale), blocks = [];
    for (const section of sections) {
      if (section.name) position += Math.round(27 * scale);
      const rows = section.entries.length ? section.entries : [
        {label:'Keine Linien oder Flächen eingeblendet',color:'#64748b',filled:false,empty:true}
      ];
      const cells = rows.map(item => {
        const lines = wrapping(ctx,item.label,textMax);
        const height = Math.max(lineHeight,lines.length * lineHeight) + Math.round(10 * scale);
        return {item, lines, height};
      });
      let rowStart = position, rowEnd = position, index = 0;
      while (index < cells.length) {
        let rowHeight = 0;
        for (let column = 0; column < columns && index + column < cells.length; column++) {
          rowHeight = Math.max(rowHeight,cells[index + column].height);
        }
        for (let column = 0; column < columns && index + column < cells.length; column++) {
          Object.assign(cells[index + column], {x:margin + column * (colWidth + colGap), y:rowStart});
        }
        rowStart += rowHeight;
        index += columns;
      }
      rowEnd = rowStart;
      blocks.push({section,cells,headingY:position - Math.round(19 * scale)});
      position = rowEnd + Math.round(10 * scale);
    }
    const footer = Math.round(58 * scale);
    return {scale,margin,colWidth,font,lineHeight,swatch,blocks,height:position+footer,columns};
  }

  function paintLegend(ctx, baseTop, width, sections, layout, opts = {}) {
    const {scale,margin,colWidth,font,lineHeight,swatch,blocks} = layout;
    ctx.fillStyle = '#19324a';
    ctx.font = '700 ' + Math.round(17 * scale) + 'px Arial, Helvetica, sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText('Legende · eingeblendete Kurven und Flächen',margin,baseTop+Math.round(10*scale),width-2*margin);
    ctx.strokeStyle = '#d4e0eb';
    ctx.lineWidth = Math.max(1,Math.round(scale));
    ctx.beginPath();ctx.moveTo(margin,baseTop+Math.round(35*scale));
    ctx.lineTo(width-margin,baseTop+Math.round(35*scale));ctx.stroke();

    for(const block of blocks) {
      if (block.section.name) {
        ctx.fillStyle='#284963';
        ctx.font='700 '+Math.round(14*scale)+'px Arial, Helvetica, sans-serif';
        ctx.fillText(block.section.name,margin,baseTop+block.headingY,width-2*margin);
      }
      for(const cell of block.cells) {
        const {item,lines,x,y} = cell;
        const cy=baseTop+y+Math.round(6*scale);
        ctx.save();
        if (!item.empty) {
          if (item.filled) {
            ctx.fillStyle=item.color||'#7697c7';
            ctx.fillRect(x,cy,Math.round(21*scale),Math.round(12*scale));
            ctx.strokeStyle='#71869a';
            ctx.strokeRect(x,cy,Math.round(21*scale),Math.round(12*scale));
          } else if(item.type==='bar') {
            ctx.fillStyle=item.color||'#7697c7';
            ctx.fillRect(x,cy,Math.round(12*scale),Math.round(15*scale));
          } else {
            ctx.strokeStyle=item.color||'#7697c7';
            ctx.lineWidth=Math.max(2,Math.round(3*scale));
            ctx.setLineDash(item.dashed?[Math.round(6*scale),Math.round(4*scale)]:[]);
            ctx.beginPath();ctx.moveTo(x,cy+Math.round(7*scale));
            ctx.lineTo(x+Math.round(22*scale),cy+Math.round(7*scale));ctx.stroke();
          }
        }
        ctx.fillStyle='#24364a';
        ctx.font='500 '+font+'px Arial, Helvetica, sans-serif';
        for(let i=0;i<lines.length;i++) {
          ctx.fillText(lines[i],x+swatch,baseTop+y+i*lineHeight,colWidth-swatch);
        }
        ctx.restore();
      }
    }
    const footerY=baseTop+layout.height-Math.round(46*scale);
    ctx.fillStyle='#52677b';
    ctx.font=Math.round(12*scale)+'px Arial, Helvetica, sans-serif';
    const note='Ausgeblendete Datenreihen sind im Bild und in der Legende nicht enthalten.';
    ctx.fillText(note,margin,footerY,width-2*margin);
    if(opts.source) ctx.fillText(opts.source,margin,footerY+Math.round(19*scale),width-2*margin);
  }

  function compose(base, charts, opts={}) {
    if (!base || typeof base.width!=='number' || typeof base.height!=='number') throw Error('PNG-Quelle fehlt');
    const items=(Array.isArray(charts)?charts:[charts]).map(entry => ({
      chart:entry.chart || entry,
      name:entry.chart?entry.title||'':undefined
    }));
    const sections=items.map(item=>({name:item.name,entries:visibleEntries(item.chart)}));
    const sample=document.createElement('canvas').getContext('2d');
    const layout=createLayout(sample,base.width,sections);
    const scale=layout.scale;
    const header=opts.title?Math.round(95*scale):0;
    const result=document.createElement('canvas');
    result.width=base.width;
    result.height=header+base.height+layout.height;
    const ctx=result.getContext('2d');
    if(!ctx)throw Error('PNG-Zeichenfläche konnte nicht erstellt werden');
    ctx.fillStyle='#ffffff';ctx.fillRect(0,0,result.width,result.height);
    if(opts.title) {
      const margin=layout.margin;
      ctx.fillStyle='#172c42';
      ctx.textBaseline='top';
      ctx.font='700 '+Math.round(21*scale)+'px Arial, Helvetica, sans-serif';
      ctx.fillText(opts.title,margin,Math.round(10*scale),result.width-2*margin);
      if(opts.subtitle) {
        ctx.fillStyle='#456074';
        ctx.font=Math.round(13*scale)+'px Arial, Helvetica, sans-serif';
        const lines=wrapping(ctx,opts.subtitle,result.width-2*margin);
        lines.slice(0,2).forEach((line,i)=>ctx.fillText(line,margin,Math.round(43*scale)+i*Math.round(17*scale),result.width-2*margin));
      }
    }
    ctx.drawImage(base,0,header);
    paintLegend(ctx,header+base.height,base.width,sections,layout,opts);
    return result;
  }
  const fromChart=(chart,opts={})=>compose(chart.canvas,chart,opts);
  const append=(base,charts,opts={})=>compose(base,charts,opts);

  window.stratoChartExport={fromChart,append,visibleEntries};
})();
