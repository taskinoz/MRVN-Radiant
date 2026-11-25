import math
import unittest

from prepare_tf1_transforms import surface_normal, hull_support


class TransformOracleTests(unittest.TestCase):
    def test_source_pitch_yaw_roll_plane_conventions(self):
        for angles, expected in (((0, 45, 0), (0, 0, 1)),
                                 ((30, 0, 0), (.5, 0, math.sqrt(3) / 2)),
                                 ((0, 0, 30), (0, -.5, math.sqrt(3) / 2))):
            for actual, wanted in zip(surface_normal(angles), expected):
                self.assertAlmostEqual(actual, wanted)
        self.assertAlmostEqual(math.hypot(*surface_normal((20, 35, 15))), 1)

    def test_box_support_uses_bottom_for_upright_and_projected_sides_for_tilt(self):
        self.assertEqual(hull_support((0, 0, 1), (-16, -16, 0), (16, 16, 72)), 0)
        self.assertEqual(hull_support((0, 0, 1), (-4, -4, -4), (4, 4, 4)), 4)
        self.assertAlmostEqual(hull_support((.6, 0, .8), (-16, -16, 0), (16, 16, 72)), 9.6)


if __name__ == '__main__':
    unittest.main()
