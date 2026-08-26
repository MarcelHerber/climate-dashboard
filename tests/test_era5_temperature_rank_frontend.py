import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))

from patch_era5_temperature_rank_frontend import apply_patch, MARKER

FIXTURE='''
function era5EuropeUpdateViewOptions(){
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const select=document.getElementById("era5EuropeView");if(!select)return;
  const previous=select.value;let entries;
  if(parameter==="temperature") entries=[["absolute","Absolutwert (°C)"],["anomaly","Abweichung 1991–2020 (K)"]];
  else if(parameter==="precipitation") entries=[["absolute","Niederschlagssumme (mm)"],["percent","Prozent vom Mittel 1991–2020"]];
  select.innerHTML=entries.map(([value,label])=>`<option value="${value}">${label}</option>`).join("");
  if(entries.some(([value])=>value===previous))select.value=previous;
  else select.value=parameter==="precipitation"?"percent":parameter==="soil_moisture"?"percentile":"anomaly";
}
function renderEra5Europe(){
  const parameter=document.getElementById("era5EuropeParameter")?.value||"temperature";
  const view=document.getElementById("era5EuropeView")?.value||"anomaly";
  const period=era5EuropeIndex.periods?.[periodId];let parameterData=period?.[parameter];
  const mapInfo=parameterData?.[view];if(!period)return;
  const stats=parameterData.stats||{},diffLabel=document.getElementById("era5EuropeDifferenceLabel");
  if(parameter==="temperature"){
    if(diffLabel)diffLabel.textContent="Abweichung";document.getElementById("era5EuropeCurrentKpi").textContent=era5EuropeFormat(stats.current,2," °C");document.getElementById("era5EuropeReferenceKpi").textContent=era5EuropeFormat(stats.reference,2," °C");document.getElementById("era5EuropeDifferenceKpi").textContent=era5EuropeFormat(stats.difference,2," K");document.getElementById("era5EuropeDifferenceDetail").textContent="Temperaturabweichung zum Mittel";
  }else if(parameter==="precipitation"){
    // fixture
  }
  const source=document.getElementById("era5EuropeSource");if(source){let extra=era5EuropeIndex.availability_note||"";if(view==="percentile")extra=era5EuropeIndex.percentile_note||extra;source.textContent=`Quelle: ${era5EuropeIndex.source}. ${extra}`.trim();}
  if(period?.analysis_ready===false){
    era5EuropeShowMonthlyRankingPending(meta,period,Number(period?.year));
  }else{
    if(era5EuropeSelectedPoint&&era5EuropeAnalysis?.ready)renderEra5EuropePointAnalysis();
    renderEra5EuropeRankings();
  }
}
function initEra5EuropeControls(){
  era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdateViewOptions();era5EuropeUpdateMapYearOptions();
  parameter.addEventListener("change",()=>{era5EuropeUpdateSoilLayerVisibility();era5EuropeUpdateViewOptions();era5EuropeUpdatePeriodOptions();era5EuropeUpdateMapYearOptions();renderEra5Europe();});soilLayer?.addEventListener("change",()=>{renderEra5Europe();});period.addEventListener("change",()=>{era5EuropeUpdateMapYearOptions();renderEra5Europe();});mapYear?.addEventListener("change",renderEra5Europe);view.addEventListener("change",renderEra5Europe);
}
'''

def test_patch_adds_rank_view_only_for_current_ready_temperature_period():
    out,changed=apply_patch(FIXTURE)
    assert changed
    assert MARKER in out
    assert 'temperature?.rank' in out
    assert '["rank","Historischer Rang seit 1950"]' in out
    assert 'mapYear?.value==="current"' in out


def test_patch_hides_standard_ranking_panel_for_rank_map_and_updates_rank_kpi():
    out,_=apply_patch(FIXTURE)
    assert 'view==="rank"' in out
    assert 'Rang-1-Fläche' in out
    assert 'rank_area_percent' in out
    assert 'rankPanel.hidden=rankView' in out


def test_patch_recomputes_view_options_when_period_or_map_year_changes():
    out,_=apply_patch(FIXTURE)
    assert 'period.addEventListener("change",()=>{era5EuropeUpdateMapYearOptions();era5EuropeUpdateViewOptions();renderEra5Europe();});' in out
    assert 'mapYear?.addEventListener("change",()=>{era5EuropeUpdateViewOptions();renderEra5Europe();});' in out


def test_patch_is_idempotent():
    once,changed=apply_patch(FIXTURE)
    twice,changed2=apply_patch(once)
    assert changed
    assert not changed2
    assert once==twice
