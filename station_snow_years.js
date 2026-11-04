/* DWD stations: per-hydrological-year snow depth curves.
   All values come from DWD SHK_TAG; absent observations remain null. */
(function(root){
  "use strict";
  function yearList(archive, currentYear, currentAvailable) {
    const list=(Array.isArray(archive?.years)?archive.years:[])
      .filter(entry=>Number.isInteger(Number(entry.year)) && Array.isArray(entry.values))
      .map(entry=>({year:Number(entry.year),coverage:Number(entry.coverage)||0,
        validDays:Number(entry.valid_days)||0,accepted:entry.accepted===true,
        isCurrent:false}));
    if(currentAvailable && Number.isInteger(Number(currentYear))) {
      const year=Number(currentYear);
      const existing=list.findIndex(entry=>entry.year===year);
      if(existing>=0)list.splice(existing,1);
      list.push({year,coverage:null,validDays:null,accepted:false,isCurrent:true});
    }
    return list.sort((a,b)=>b.year-a.year);
  }
  function values(archive, year, monthDays, currentYear, currentByMonthDay) {
    const yearNumber=Number(year);
    if(yearNumber===Number(currentYear)) {
      return monthDays.map(day=>{
        const value=currentByMonthDay?.get(day)?.snow;
        return value===null || value===undefined || !Number.isFinite(Number(value))
          ?null:Number(value);
      });
    }
    const row=archive?.years?.find(entry=>Number(entry.year)===yearNumber);
    if(!row || !Array.isArray(row.values))return monthDays.map(()=>null);
    const axis=Array.isArray(archive?.month_days)?archive.month_days:null;
    const byDay=axis?new Map(axis.map((day,i)=>[day,row.values[i]])):null;
    return monthDays.map((day,i)=>{
      const value=byDay?byDay.get(day):row.values[i];
      return value===null || value===undefined || !Number.isFinite(Number(value))
        ?null:Number(value);
    });
  }
  function color(year, currentYear) {
    if(Number(year)===Number(currentYear))return "#d9342b";
    const hue=((Number(year)*67)%360+360)%360;
    return `hsl(${hue},65%,40%)`;
  }
  function curves({archive,selectedYears,monthDays,currentYear,currentByMonthDay,median}) {
    const series=[];
    for(const year of selectedYears||[]) {
      const yearValues=values(archive,year,monthDays,currentYear,currentByMonthDay);
      if(!yearValues.some(value=>value!==null))continue;
      const current=Number(year)===Number(currentYear);
      const paint=color(year,currentYear);
      series.push({
        year:Number(year),
        label:`Hydrologisches Jahr ${year}${current?" (aktuell)":""}`,
        values:yearValues,
        deviations:yearValues.map((value,i)=>{
          const baseline=median[i];
          return value===null || baseline===null || baseline===undefined?null:
            Math.round((value-Number(baseline))*10)/10;
        }),
        color:paint,current
      });
    }
    // Current-season line comes last and thus stays above historical lines.
    return series.sort((a,b)=>Number(a.current)-Number(b.current));
  }
  root.StationSnowYears=Object.freeze({yearList,values,color,curves});
})(window);
