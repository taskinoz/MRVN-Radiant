"""Synthetic tests for TFO harness path handling; no game files touched."""
import tempfile
import unittest
from pathlib import Path

import tfo_harness


class TfoHarnessPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_accepts_maps_folder(self):
        maps = self.root / 'maps'
        maps.mkdir()
        (maps / 'mp_test.bsp').write_bytes(b'')
        self.assertEqual(tfo_harness.map_source(maps, 'mp_test'), maps)

    def test_accepts_build_root(self):
        maps = self.root / 'maps'
        maps.mkdir()
        (maps / 'mp_test.bsp').write_bytes(b'')
        self.assertEqual(tfo_harness.map_source(self.root, 'mp_test'), maps)

    def test_rejects_nested_wrong_map(self):
        maps = self.root / 'maps'
        maps.mkdir()
        (maps / 'mp_other.bsp').write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'missing compiled map'):
            tfo_harness.map_source(self.root, 'mp_test')


if __name__ == '__main__':
    unittest.main()
