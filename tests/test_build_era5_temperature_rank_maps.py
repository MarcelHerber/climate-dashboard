import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))

from build_era5_temperature_rank_maps import current_temperature_targets


def test_current_temperature_targets_include_latest_summer_and_current_months_only():
    payload={
      'latest_month_key':'2026-07',
      'periods':{
        'latest_month':{'year':2026,'months':[7],'temperature':{}},
        'summer':{'year':2026,'months':[6,7],'temperature':{}},
        'month_01':{'year':2026,'months':[1],'temperature':{},'analysis_ready':False},
        'month_07':{'year':2026,'months':[7],'temperature':{},'analysis_ready':False},
        'month_08':{'year':2025,'months':[8],'temperature':{},'historical_only':True},
      }
    }
    targets=current_temperature_targets(payload)
    assert [(t['id'],t['months']) for t in targets]==[
      ('latest_month',[7]),('summer',[6,7]),('month_01',[1]),('month_07',[7])
    ]
