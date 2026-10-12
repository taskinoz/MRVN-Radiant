import math
import unittest
from recover_collision_map import cross, plane_points


class PlaneRecoveryTests(unittest.TestCase):
    def test_map_winding_and_distance(self):
        for plane in [(1,0,0,64), (-1,0,0,32), (0,0,1,128),
                      (0,0,-1,-16), (1,1,1,96), (0,1,0,0)]:
            a,b,c = plane_points(plane)
            normal = cross(tuple(a[i]-b[i] for i in range(3)),
                           tuple(c[i]-b[i] for i in range(3)))
            length = math.sqrt(sum(v*v for v in normal))
            original_length = math.sqrt(sum(v*v for v in plane[:3]))
            for i in range(3):
                self.assertAlmostEqual(normal[i]/length, plane[i]/original_length)
            for point in (a,b,c):
                self.assertAlmostEqual(sum(plane[i]*point[i] for i in range(3)), plane[3])

    def test_bad_planes_rejected(self):
        for plane in [(0,0,0,1), (math.nan,1,0,0), (1,0,0,math.inf)]:
            with self.assertRaises(ValueError):
                plane_points(plane)


if __name__ == '__main__':
    unittest.main()
