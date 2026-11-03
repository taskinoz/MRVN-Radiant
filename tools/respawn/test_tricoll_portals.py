"""Original synthetic collision/visibility records; no proprietary assets."""
import math
import unittest

from portals import check_portal_records, connected, locate_cell
from tricoll import check_tricoll_records, node_count, triangle_indices
from validate_records import SCHEMAS


def records():
    return {i: [] for i in SCHEMAS}


def collision():
    r = records()
    r[2] = [(0,) * 9]
    r[3] = [(100, 100, 100), (0, 0, 0), (64, 0, 0), (0, 64, 0), (64, 64, 0)]
    r[66] = [(1 << 10 | 2 << 17,), (2 << 10 | 3 << 17,)]
    r[96] = [(0,), (0,)]
    r[69] = [(0, 0, 0, 4, 2, 0, 1, 0, 0, 0, 0, 0, 0, 0)]
    return r


def visibility():
    r = records()
    r[1] = [(1, 0, 0, 0)]
    r[106] = [(0, 1), (-1, 0), (-1, 1)]
    r[107] = [(1, 0, 1, -1), (1, 1, 1, -1)]
    r[108] = [(0, 0, 3, 0, 0, 1, 0), (1, 0, 3, 0, 0, 0, 0)]
    r[109] = [(0, 0, 0), (0, 1, 0), (0, 0, 1)]
    r[110] = [(0, 2), (0, 1), (1, 2)]
    r[111] = [(0, 1, -1, -1, -1, -1, -1, -1),
              (1, 2, -1, -1, -1, -1, -1, -1),
              (0, 2, -1, -1, -1, -1, -1, -1)]
    r[112] = [(0,), (1,), (2,)]
    r[113] = [(1,), (2,), (4,)]
    r[116] = [(0, 0)] * 3
    r[119] = [(-10, -10, -10, 0, 0, 0, 10, 10, 10, 0, 0)] * 2
    return r


class TricollTests(unittest.TestCase):
    def test_unsigned_base_deltas_and_flags(self):
        self.assertEqual(triangle_indices(0xff000000 | 1023 | 127 << 10 | 126 << 17), (1023, 1150, 1149))

    def test_three_triangle_loader_special_case(self):
        self.assertEqual([node_count(n) for n in (1, 2, 3, 4, 8, 9)], [0, 0, 0, 4, 4, 8])

    def test_node_free_quad(self):
        self.assertEqual(check_tricoll_records(collision()), [])

    def test_triangle_must_fit_its_header_not_global_vertices(self):
        r = collision()
        r[66][0] = (4 << 17,)
        self.assertIn('vertex exceeds', str(check_tricoll_records(r)))

    def test_parallel_starts_nodes_and_bevel_word_rounding(self):
        r = collision()
        r[96].pop()
        self.assertIn('bevel-start count', str(check_tricoll_records(r)))
        r = collision()
        h = list(r[69][0]); h[4] = 4; h[5] = 3
        r[69][0] = tuple(h)
        r[66] *= 2; r[96] *= 2
        r[97] = [(0,)]  # 3*11 bits needs TWO words
        issues = str(check_tricoll_records(r))
        self.assertIn('node slice', issues)
        self.assertIn('packed bevel slice', issues)

    def test_nonfinite_frame(self):
        r = collision()
        r[69][0] = (*r[69][0][:-1], math.nan)
        self.assertIn('nonfinite', str(check_tricoll_records(r)))


class PortalTests(unittest.TestCase):
    def test_front_child_zero_and_bidirectional_connectivity(self):
        r = visibility()
        self.assertEqual(check_portal_records(r), [])
        self.assertEqual(locate_cell(r, (10, 0, 0)), 0)
        self.assertEqual(locate_cell(r, (-10, 0, 0)), 1)
        self.assertTrue(connected(r, 0, 1))
        self.assertTrue(connected(r, 1, 0))
        r[107][0] = (0, 0, 1, -1)
        self.assertFalse(connected(r, 0, 1))

    def test_cycle_fails_without_recursion(self):
        r = visibility()
        r[106][0] = (0, 0)
        self.assertIn('cyclic', str(check_portal_records(r)))
        with self.assertRaises(ValueError):
            locate_cell(r, (1, 0, 0))

    def test_sky_sentinel(self):
        r = visibility()
        r[108][0] = (0, 1, 3, 0, 0, 3, 0)
        self.assertEqual(check_portal_records(r), [])
        r[108][0] = (0, 1, 3, 0, 0, 2, 0)
        self.assertIn('sky sentinel', str(check_portal_records(r)))

    def test_oriented_edge_and_intersection_sentinels(self):
        r = visibility()
        r[113][0] = (6,)
        self.assertIn('oriented portal edge', str(check_portal_records(r)))
        r = visibility()
        r[114] = [(0, -1, -1, -1, -1, -1, -1, -1)]
        r[115] = [(-1,) * 8]
        self.assertIn('intersection edge/vertex pair', str(check_portal_records(r)))

    def test_only_global_roots_allow_infinity(self):
        r = visibility()
        r[119][0] = (-math.inf, -math.inf, -math.inf, 0, 0, 0, math.inf, math.inf, math.inf, 0, 0)
        self.assertIn('invalid cell access bounds', str(check_portal_records(r)))
        r[107][0] = (1, 0, 3, -1)
        self.assertEqual(check_portal_records(r), [])


if __name__ == '__main__':
    unittest.main()
