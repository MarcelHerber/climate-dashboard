import base64, zlib, unittest, sys
from datetime import date
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from build_bundeslaender_station_temperature import decode, panel_series, average, extremes, MISSING, FIRST

class StationPanelTests(unittest.TestCase):
    def test_leap_year_and_column_order(self):
        a=np.full((2,366,3),MISSING,dtype="<i2")
        a[0,0]=[100,-30,20]
        a[1,59]=[120,-10,40]
        d={"format":"dwd-tx-tn-tm-zlib16-v1","years":[1981,1984],"data":base64.b64encode(zlib.compress(a.tobytes())).decode()}
        out=decode(d,date(1985,1,1))
        self.assertEqual(out[0].tolist(),[100,-30,20])
        self.assertEqual(out[(date(1984,2,29)-FIRST).days].tolist(),[120,-10,40])
        self.assertEqual(out[(date(1982,1,1)-FIRST).days,0],MISSING)
    def test_fixed_panel_missing_not_zero(self):
        a=np.full((101,3),10,dtype=np.int16)
        b=a.copy();b[:,0]=20;b[50,0]=MISSING
        panel=panel_series([("a",a),("b",b)],100,0)
        self.assertEqual([x[0] for x in panel],["a"])
        self.assertEqual(average([("a",a),("b",b)],0,101)[0],1.5)
        self.assertIsNone(average([("a",a),("b",b)],0,101)[50])
        self.assertEqual(average([],0,2),[None,None])
    def test_extrema_switch_stations(self):
        a=np.array([[-70,0,0],[-46,0,0],[MISSING,0,0]],dtype=np.int16)
        b=np.array([[-66,0,0],[-80,0,0],[MISSING,0,0]],dtype=np.int16)
        self.assertEqual(extremes([("a",a),("b",b)],0,3,"low"),([-7.0,-8.0,None],["a","b",None],[2,2,0]))
if __name__=="__main__":unittest.main()
