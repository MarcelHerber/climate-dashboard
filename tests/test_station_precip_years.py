import ast
import base64
import calendar
import struct
import unittest
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

SOURCE = globals().get("SOURCE") or (Path(__file__).resolve().parents[1] / "scripts/update_station_precip.py").read_text()
tree = ast.parse(SOURCE)
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "observations_to_year_daily_tenths"]
namespace = dict(globals())
exec(compile(ast.Module(body=functions, type_ignores=[]), "<production>", "exec"), namespace)

class HistoricalYearsTest(unittest.TestCase):
    def test_complete_years_are_encoded_losslessly_including_february_29(self):
        rows = []
        for year in (2023, 2024, 2025, 2026):
            day = date(year, 1, 1)
            while day.year == year:
                if day != date(2025, 6, 1):
                    value = 2.5 if (day.month, day.day) == (2, 29) else 0.1
                    rows.append(SimpleNamespace(day=day, values={"rsk_high": value}))
                day += timedelta(days=1)
        encode = namespace.get("observations_to_year_daily_tenths")
        self.assertIsNotNone(encode, "Individual historical curves must be exported")
        payload = encode(rows, 2026)
        self.assertEqual(set(payload), {"2023", "2024"})
        self.assertEqual(sum(struct.unpack(">365H", base64.b64decode(payload["2023"]))), 365)
        leap = struct.unpack(">366H", base64.b64decode(payload["2024"]))
        self.assertEqual(leap[59], 25)
        self.assertEqual(sum(leap), 390)

if __name__ == "__main__":
    unittest.main()
