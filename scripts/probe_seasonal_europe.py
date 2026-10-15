import json, urllib.request
from urllib.parse import urlencode
params={"latitude":"50.1,52.5","longitude":"8.7,13.4","monthly":"temperature_2m_anomaly,precipitation_anomaly","models":"ecmwf_seas5_ensemble_mean","forecast_days":217,"timezone":"GMT","cell_selection":"nearest"}
url="https://seasonal-api.open-meteo.com/v1/seasonal?"+urlencode(params)
print("Requesting",url,flush=True)
req=urllib.request.Request(url,headers={"User-Agent":"ClimateDashboardWeatherResearch/1.0"})
with urllib.request.urlopen(req,timeout=65) as res: data=json.load(res)
print("Response type:",type(data).__name__,flush=True)
rows=data if isinstance(data,list) else [data]
for p in rows:
 print("keys",list(p),flush=True)
 print("monthly",json.dumps(p.get("monthly",{}),ensure_ascii=False)[:3500],flush=True)
 print("units",p.get("monthly_units"),flush=True)
assert len(rows)==2
assert all(p.get("monthly",{}).get("temperature_2m_anomaly") for p in rows)
assert all(p.get("monthly",{}).get("precipitation_anomaly") for p in rows)
