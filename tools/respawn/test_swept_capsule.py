import math
import unittest

from swept_capsule import sweep_capsule_triangle, sweep_capsule_mesh


class SweptCapsuleTests(unittest.TestCase):
    flat = ((-128,-128,64),(-128,128,64),(128,128,64))

    def test_plane_slope_support_matches_closed_form(self):
        triangle = ((-128,-128,32),(-128,128,32),(128,128,96))
        for radius in (8,16):
            hit = sweep_capsule_triangle((-32,32,192),(-32,32,-32),(-radius,-radius,0),(radius,radius,72),triangle)
            expected_z = 56+radius*(math.sqrt(1+0.25**2)-1)
            self.assertAlmostEqual(192-hit*224,expected_z,places=6)

    def test_finite_edge_uses_spherical_cap(self):
        hit = sweep_capsule_triangle((-132,0,192),(-132,0,-32),(-8,-8,0),(8,8,72),self.flat)
        self.assertAlmostEqual(192-hit*224,64-8+math.sqrt(8**2-4**2),places=6)
        self.assertIsNone(sweep_capsule_triangle((-145,0,192),(-145,0,-32),(-8,-8,0),(8,8,72),self.flat))

    def test_flat_center_sphere_and_ray(self):
        for high in (0,16,72):
            radius = 0 if high == 0 else 8
            self.assertAlmostEqual(sweep_capsule_triangle((-32,32,192),(-32,32,-32),(-radius,-radius,0),(radius,radius,high),self.flat),4/7,places=7)

    def test_stationary_and_initial_overlap(self):
        self.assertEqual(sweep_capsule_triangle((-32,32,60),(-32,32,60),(-8,-8,0),(8,8,72),self.flat),0)
        self.assertIsNone(sweep_capsule_triangle((-32,32,192),(-16,32,192),(-8,-8,0),(8,8,72),self.flat))
        self.assertIsNone(sweep_capsule_mesh((0,0,192),(0,0,-32),(-8,-8,0),(8,8,72),()))

    def test_invalid_capsule(self):
        with self.assertRaises(ValueError):
            sweep_capsule_triangle((0,0,192),(0,0,-32),(-8,-16,0),(8,16,72),self.flat)
        with self.assertRaises(ValueError):
            sweep_capsule_triangle((0,0,192),(0,0,-32),(-8,-8,0),(8,8,8),self.flat)
