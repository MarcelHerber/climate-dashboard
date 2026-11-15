import unittest
import numpy as np
from scripts.build_temperature_contrast import scan, MISSING


class ContrastTests(unittest.TestCase):
    def test_exact_constraints_and_simultaneity(self):
        hot = np.array([[200, 0, 130], [100, -100, 120]], dtype=np.int16)
        cold = hot.copy()
        dist = np.array([[0, 300, 20], [300, 0, 40], [20, 40, 0]], dtype=float)
        height = np.array([[0, 0, 500], [0, 0, 500], [500, 500, 0]], dtype=float)
        result = scan(hot, cold, dist, height, np.array([25., 9999.]), np.array([200., 9999.]), 2)
        self.assertEqual(result[0, 0, 0, 0], MISSING)
        self.assertEqual(result[0, 0, 1, 0], 70)
        self.assertEqual(result[0, 1, 1, 0], 220)
        self.assertEqual(result[0, 1, 1, 3], 1)

    def test_daily_distinct_stations_and_missing(self):
        hot = np.array([[300, 140, MISSING]], dtype=np.int16)
        cold = np.array([[-200, 0, MISSING]], dtype=np.int16)
        dist = np.zeros((3, 3))
        result = scan(hot, cold, dist, dist, np.array([100.]), np.array([100.]), 1)
        self.assertEqual(list(result[0, 0, 0, :3]), [340, 1, 0])

    def test_random_against_brute_force(self):
        rng = np.random.default_rng(17)
        hot = rng.integers(-200, 400, (12, 7), dtype=np.int16)
        cold = rng.integers(-300, 150, (12, 7), dtype=np.int16)
        hot[2, 1] = cold[4, 2] = MISSING
        d = rng.integers(0, 200, (7, 7)).astype(float)
        h = rng.integers(0, 500, (7, 7)).astype(float)
        radii, heights = np.array([25., 100., 9999.]), np.array([200., 9999.])
        result = scan(hot, cold, d, h, radii, heights, 3)
        for day in range(4):
            for r, radius in enumerate(radii):
                for k, height in enumerate(heights):
                    candidates = [int(hot[t,i])-int(cold[t,j]) for t in range(day*3,day*3+3) for i in range(7) for j in range(7) if i!=j and d[i,j]<=radius and h[i,j]<=height and hot[t,i]!=MISSING and cold[t,j]!=MISSING]
                    self.assertEqual(result[day,r,k,0], max(candidates,default=MISSING))

    def test_negative_valid_daily_pair(self):
        hot=np.array([[0,MISSING]],dtype=np.int16)
        cold=np.array([[MISSING,20]],dtype=np.int16)
        d=np.zeros((2,2))
        self.assertEqual(scan(hot,cold,d,d,np.array([25.]),np.array([200.]),1)[0,0,0,0],-20)
