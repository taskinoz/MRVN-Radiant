"""Original synthetic collision/visibility records; no proprietary assets."""
import math
import unittest

from portals import check_portal_records, connected, locate_cell
from tricoll import bevel_index, check_bevel_chain, check_tricoll_records, node_count, triangle_indices
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

    def test_bevel_ranges_must_fit_header(self):
        r = collision()
        h = list(r[69][0]); h[5] = 2
        r[69][0] = tuple(h)
        r[97] = [(0,)]
        r[66][0] = (r[66][0][0] | 1 << 24,)
        r[96] = [(1,), (0,)]
        self.assertEqual(check_tricoll_records(r), [])
        for offsets in ([(2,), (0,)], [(0,), (3,)]):
            r[96] = offsets
            self.assertIn('bevel range', str(check_tricoll_records(r)))

    def test_packed_bevel_indices_and_special_count(self):
        packed = 1 | (2 << 11) | (1025 << 22)
        words = [(packed & 0xffffffff,), (packed >> 32,)]
        self.assertEqual([bevel_index(words, 0, index) for index in range(3)], [1, 2, 1025])
        packed_tf1 = 3 | (7 << 10) | (513 << 20) | (9 << 30)
        words_tf1 = [(packed_tf1 & 0xffffffff,), (packed_tf1 >> 32,)]
        self.assertEqual([bevel_index(words_tf1, 0, index, 10) for index in range(4)], [3, 7, 513, 9])
        r = collision()
        h = list(r[69][0]); h[5] = 1
        r[69][0] = tuple(h)
        r[97] = [(2,)]
        r[66][0] = (r[66][0][0] | 1 << 24,)
        self.assertIn('bevel triangle index', str(check_tricoll_records(r)))
        r[66][0] = ((r[66][0][0] & ~(15 << 24)) | 15 << 24,)
        self.assertIn('bevel chain', str(check_tricoll_records(r)))
        h = list(r[69][0]); h[5] = 3
        r[69][0] = tuple(h)
        r[97] = [(1 | 1 << 22,), (0,)]
        self.assertEqual(check_tricoll_records(r), [])
        r[97] = [(1 | 2 << 22,), (0,)]
        self.assertIn('bevel chain', str(check_tricoll_records(r)))

    def test_cross_header_bevel_chain_in_both_formats(self):
        headers = [(0, 0, 0, 3, 2), (0, 0, 0, 3, 3)]
        for width in (10, 11):
            values = [129, 0, 2, 1, 0, 1]
            packed = sum(value << (width * index) for index, value in enumerate(values))
            words = [((packed >> offset) & 0xffffffff,) for offset in range(0, width * len(values), 32)]
            self.assertTrue(check_bevel_chain(words, 0, 0, len(values), width, headers, 0))
            self.assertFalse(check_bevel_chain(words, 0, 0, len(values) - 1, width, headers, 0))


    def test_zero_count_foreign_segment_does_not_terminate_native_chain(self):
        headers = [(0, 0, 0, 3, 1), (0, 0, 0, 3, 1)]
        for width in (10, 11):
            def words(values):
                packed = sum(value << (width * i) for i, value in enumerate(values))
                return [((packed >> bit) & 0xffffffff,) for bit in range(0, width * len(values), 32)]
            self.assertFalse(check_bevel_chain(words([0,0]),0,0,2,width,headers,1))
            self.assertTrue(check_bevel_chain(words([0,0,128,0]),0,0,4,width,headers,1))
            self.assertTrue(check_bevel_chain(words([128,0]),0,0,2,width,headers,1))


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

    def test_native_cell_mask_reserves_two_sentinels(self):
        for version in (29, 37):
            r = visibility()
            r[107] = [(0, 0, 1, -1)] * 1022
            r[119] = [r[119][0]] * 1022
            self.assertEqual(check_portal_records(r, version), [])
            r[107].append((0, 0, 1, -1))
            r[119].append(r[119][0])
            self.assertIn('1024-bit native mask', str(check_portal_records(r, version)))

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

    def test_empty_global_root_uses_float32_accumulation_sentinels(self):
        r = visibility()
        maximum = float.fromhex('0x1.fffffep+127')
        r[119][0] = (maximum, maximum, maximum, 0, 0, 0, -maximum, -maximum, -maximum, 0, 0)
        self.assertIn('invalid cell access bounds', str(check_portal_records(r, 29)))
        r[107][0] = (1, 0, 3, -1)
        self.assertEqual(check_portal_records(r, 29), [])
        n = list(r[119][0]); n[5] = 1; r[119][0] = tuple(n)
        self.assertIn('invalid cell access bounds', str(check_portal_records(r, 29)))

    def test_access_node_must_enclose_its_references(self):
        r = visibility()
        r[119][0] = (-10, -10, -10, 0, 1, 1, 10, 10, 10, 0, 0)
        r[120] = [(0,)]
        r[121] = [(-5, -5, -5, 0, 5, 5, 5, 0)]
        self.assertEqual(check_portal_records(r), [])
        r[121] = [(-5, -5, -5, 0, 50, 5, 5, 0)]  # a mesh reaching past its cell's root
        self.assertIn('does not enclose', str(check_portal_records(r)))

    def test_only_global_roots_allow_infinity(self):
        r = visibility()
        r[119][0] = (-math.inf, -math.inf, -math.inf, 0, 0, 0, math.inf, math.inf, math.inf, 0, 0)
        self.assertIn('invalid cell access bounds', str(check_portal_records(r)))
        r[107][0] = (1, 0, 3, -1)
        self.assertEqual(check_portal_records(r), [])


if __name__ == '__main__':
    unittest.main()
