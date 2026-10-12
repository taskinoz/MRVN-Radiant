"""Budget boundaries and engine-version gating without proprietary binaries."""
import unittest

from audit_tf2_budget import budget, ENGINE_SHA256, INDEX_CAPACITY, SORT_CAPACITY


class BudgetTests(unittest.TestCase):
    def test_padding_is_per_mesh(self):
        report = budget([(0, 1), (3, 1), (6, 2)], 2, ENGINE_SHA256)
        self.assertEqual(report["serialized_index_count"], 12)
        self.assertEqual(report["all_visible_padded_index_estimate"], 18)
        self.assertEqual(report["issues"], [])
        self.assertIsNone(report["draw_batches"])

    def test_exact_capacity_and_overflow(self):
        triangles = INDEX_CAPACITY // 3
        self.assertEqual(budget([(0, triangles)], SORT_CAPACITY, ENGINE_SHA256)["issues"], [])
        self.assertTrue(budget([(0, triangles + 1)], SORT_CAPACITY, ENGINE_SHA256)["issues"])
        self.assertTrue(budget([], SORT_CAPACITY + 1, ENGINE_SHA256)["issues"])

    def test_unknown_hash_does_not_apply_known_engine_limits(self):
        report = budget([(0, INDEX_CAPACITY)], SORT_CAPACITY + 1, "0" * 64)
        self.assertFalse(report["engine_profile_matched"])
        self.assertIsNone(report["index_capacity"])
        self.assertEqual(report["issues"], [])
        self.assertIn("unknown engine hash", str(report["warnings"]))


if __name__ == "__main__":
    unittest.main()
