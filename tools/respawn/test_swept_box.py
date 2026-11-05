import unittest

from swept_box import sweep_triangle, sweep_mesh, sweep_halfspaces


class SweptBoxTests(unittest.TestCase):
    flat = ((-128,-128,64), (-128,128,64), (128,128,64))

    def test_flat_plane_contact_uses_lower_box_face(self):
        self.assertAlmostEqual(sweep_triangle((-32,32,192), (-32,32,-32), (-8,-8,0), (8,8,32), self.flat), 4/7)
        self.assertAlmostEqual(sweep_triangle((-32,32,192), (-32,32,-32), (-8,-8,-16), (8,8,16), self.flat), 0.5)

    def test_slope_support_uses_the_highest_corner_under_the_box(self):
        tri = ((-128,-128,32), (-128,128,32), (128,128,96))
        # Center x=-32 gives z56; the box reaches x=-24, where z58.
        fraction = sweep_triangle((-32,32,192), (-32,32,-32), (-8,-8,0), (8,8,32), tri)
        self.assertAlmostEqual(fraction, (192-58)/224)

    def test_triangle_edges_clip_the_expanded_plane(self):
        self.assertIsNone(sweep_triangle((140,32,192), (140,32,-32), (-8,-8,0), (8,8,32), self.flat))
        # The diagonal is x=y. The center is outside, but the box overlaps it.
        self.assertAlmostEqual(sweep_triangle((40,32,192), (40,32,-32), (-8,-8,0), (8,8,32), self.flat), 4/7)
        self.assertIsNone(sweep_triangle((60,32,192), (60,32,-32), (-8,-8,0), (8,8,32), self.flat))

    def test_stationary_and_parallel_sweeps(self):
        self.assertIsNone(sweep_triangle((-32,32,192), (-16,32,192), (-8,-8,0), (8,8,32), self.flat))
        self.assertEqual(sweep_triangle((-32,32,48), (-32,32,48), (-8,-8,0), (8,8,32), self.flat), 0)
        self.assertIsNone(sweep_triangle((-32,32,48), (-32,32,48), (0,0,0), (0,0,0), self.flat))

    def test_subdivision_and_winding_do_not_change_the_reference(self):
        a,b,c = self.flat
        middle = tuple((x+y)/2 for x,y in zip(a,c))
        args = ((-32,32,192), (-32,32,-32), (-8,-8,0), (8,8,32))
        expected = sweep_triangle(*args, self.flat)
        self.assertAlmostEqual(sweep_mesh(*args, ((a,b,middle),(middle,b,c))), expected)
        self.assertAlmostEqual(sweep_triangle(*args, (c,b,a)), expected)
        self.assertIsNone(sweep_mesh(*args, ()))

    def test_invalid_geometry_is_rejected(self):
        for tri in (((0,0,0),)*3, ((0,0,0), (1,0,0)), ((0,0,float('nan')), (1,0,0), (0,1,0))):
            with self.assertRaises(ValueError):
                sweep_triangle((0,0,1),(0,0,-1),(0,0,0),(0,0,0),tri)
        with self.assertRaises(ValueError):
            sweep_triangle((0,0,1),(0,0,-1),(1,0,0),(0,0,0),self.flat)

    def test_halfspace_box_expansion_and_start_overlap(self):
        planes = ((1,0,0,64),(-1,0,0,0),(0,1,0,64),(0,-1,0,0),(0,0,1,64),(0,0,-1,0))
        self.assertAlmostEqual(sweep_halfspaces((32,32,192),(32,32,-32),(-8,-8,0),(8,8,32),planes),4/7)
        self.assertEqual(sweep_halfspaces((32,32,32),(32,32,32),(-8,-8,0),(8,8,32),planes),0)
        self.assertIsNone(sweep_halfspaces((96,32,192),(96,32,-32),(-8,-8,0),(8,8,32),planes))

    def test_invalid_halfspaces(self):
        for plane in ((0,0,0,1),(1,0,0),(1,0,0,float('nan'))):
            with self.assertRaises(ValueError):
                sweep_halfspaces((0,0,0),(1,0,0),(0,0,0),(0,0,0),(plane,))
