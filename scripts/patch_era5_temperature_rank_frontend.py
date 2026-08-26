from __future__ import annotations

from pathlib import Path

MARKER='// ERA5_TEMPERATURE_RANK_FRONTEND_V1'


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count=text.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: expected exactly one match, got {count}')
    return text.replace(old,new,1)


def apply_patch(text: str) -> tuple[str,bool]:
    if MARKER in text:
        return text,False

    old_view='''function era5EuropeUpdateViewOptions(){\n  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";\n  const select=document.getElementById("era5EuropeView");if(!select)return;\n  const previous=select.value;let entries;\n  if(parameter==="temperature") entries=[["absolute","Absolutwert (°C)"],["anomaly","Abweichung 1991–2020 (K)"]];'''
    new_view=f'''{MARKER}\nfunction era5EuropeUpdateViewOptions(){{\n  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";\n  const select=document.getElementById("era5EuropeView");if(!select)return;\n  const previous=select.value;let entries;\n  const mapYear=document.getElementById("era5EuropeMapYear"),periodId=document.getElementById("era5EuropePeriod")?.value||"latest_month";\n  const rankReady=parameter==="temperature"&&mapYear?.value==="current"&&Boolean(era5EuropeIndex?.periods?.[periodId]?.temperature?.rank);\n  if(parameter==="temperature"){{entries=[["absolute","Absolutwert (°C)"],["anomaly","Abweichung 1991–2020 (K)"]];if(rankReady)entries.push(["rank","Historischer Rang seit 1950"]);}}'''
    text=_replace_once(text,old_view,new_view,'view options')

    old_temp='''  if(parameter==="temperature"){\n    if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,2," °C");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,2," °C");document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.difference,2," K");document.getElementById("era5EuropeDifferenceDetail").textContent="Temperaturabweichung zum Mittel";\n  }else if(parameter==="precipitation"){'''
    new_temp='''  if(parameter==="temperature"){\n    if(view==="rank"){\n      const rankStats=parameterData?.rank?.stats||{};\n      if(diffLabel)diffLabel.textContent="Rang-1-Fläche";document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,2," °C");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,2," °C");document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(rankStats.rank_area_percent,1," %");document.getElementById("era5EuropeDifferenceDetail").textContent=`Rang 1 = wärmster Wert seit ${parameterData?.rank?.history_start||1950} · Top 3: ${era5EuropeFormat(rankStats.top3_area_percent,1," %")}`;\n    }else{\n      if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,2," °C");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,2," °C");document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.difference,2," K");document.getElementById("era5EuropeDifferenceDetail").textContent="Temperaturabweichung zum Mittel";\n    }\n  }else if(parameter==="precipitation"){'''
    text=_replace_once(text,old_temp,new_temp,'temperature KPI')

    old_source='''if(view==="percentile")extra=era5EuropeIndex.percentile_note||extra;'''
    new_source='''if(view==="percentile")extra=era5EuropeIndex.percentile_note||extra;if(parameter==="temperature"&&view==="rank")extra=parameterData?.rank?.note||`Historischer Temperaturrang seit ${parameterData?.rank?.history_start||1950}; Rang 1 ist der wärmste Wert am jeweiligen 0,1°-Gitterpunkt.`;'''
    text=_replace_once(text,old_source,new_source,'rank source note')

    old_ranking='''  if(period?.analysis_ready===false){\n    era5EuropeShowMonthlyRankingPending(meta,period,Number(period?.year));\n  }else{'''
    new_ranking='''  const rankPanel=document.getElementById("era5EuropeRanking"),rankView=parameter==="temperature"&&view==="rank";\n  if(rankPanel)rankPanel.hidden=rankView;\n  if(rankView){if(era5EuropeSelectedPoint&&era5EuropeAnalysis?.ready)renderEra5EuropePointAnalysis();return;}\n  if(period?.analysis_ready===false){\n    era5EuropeShowMonthlyRankingPending(meta,period,Number(period?.year));\n  }else{'''
    text=_replace_once(text,old_ranking,new_ranking,'rank panel')

    old_init='''era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdateViewOptions();era5EuropeUpdateMapYearOptions();'''
    new_init='''era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdateMapYearOptions();era5EuropeUpdateViewOptions();'''
    text=_replace_once(text,old_init,new_init,'initial control order')

    old_param='''parameter.addEventListener("change",()=>{era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdateViewOptions();era5EuropeUpdatePeriodOptions();era5EuropeUpdateMapYearOptions();renderEra5Europe();});'''
    new_param='''parameter.addEventListener("change",()=>{era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdatePeriodOptions();era5EuropeUpdateMapYearOptions();era5EuropeUpdateViewOptions();renderEra5Europe();});'''
    text=_replace_once(text,old_param,new_param,'parameter handler')

    old_period='''period.addEventListener("change",()=>{era5EuropeUpdateMapYearOptions();renderEra5Europe();});'''
    new_period='''period.addEventListener("change",()=>{era5EuropeUpdateMapYearOptions();era5EuropeUpdateViewOptions();renderEra5Europe();});'''
    text=_replace_once(text,old_period,new_period,'period handler')

    old_year='''mapYear?.addEventListener("change",renderEra5Europe);'''
    new_year='''mapYear?.addEventListener("change",()=>{era5EuropeUpdateViewOptions();renderEra5Europe();});'''
    text=_replace_once(text,old_year,new_year,'map year handler')
    return text,True


def main() -> int:
    root=Path(__file__).resolve().parents[1]
    path=root/'index.html'
    text=path.read_text(encoding='utf-8')
    text,changed=apply_patch(text)
    if changed:
        path.write_text(text,encoding='utf-8')
        print('ERA5 Temperatur-Rangansicht im Frontend ergänzt.')
    else:
        print('ERA5 Temperatur-Rangansicht im Frontend ist bereits aktuell.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
