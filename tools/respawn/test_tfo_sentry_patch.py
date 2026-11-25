"""Synthetic tests for the reversible TFO sentry.dll patch; no game files touched."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tfo_sentry_patch as patcher


class TfoSentryPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        original = bytearray(b'\xcc' * (patcher.DLL_MAIN_OFFSET + 32))
        original[patcher.DLL_MAIN_OFFSET:patcher.DLL_MAIN_OFFSET + 4] = patcher.ORIGINAL_PREFIX
        self.original = bytes(original)
        patched = bytearray(original)
        patched[patcher.DLL_MAIN_OFFSET:patcher.DLL_MAIN_OFFSET + len(patcher.PATCH)] = patcher.PATCH
        self.patched = bytes(patched)
        self.dll = root / 'Bin' / 'sentry.dll'
        self.dll.parent.mkdir()
        self.dll.write_bytes(self.original)
        self.backup = root / 'backup.dll'
        patches = [
            mock.patch.object(patcher, 'ORIGINAL_SHA256', hashlib.sha256(self.original).hexdigest()),
            mock.patch.object(patcher, 'PATCHED_SHA256', hashlib.sha256(self.patched).hexdigest()),
        ]
        for override in patches:
            override.start()
            self.addCleanup(override.stop)

    def test_make_patched_bytes_and_hash_guard(self):
        self.assertEqual(patcher.make_patched_bytes(self.original), self.patched)
        wrong = bytearray(self.original)
        wrong[patcher.DLL_MAIN_OFFSET] = 0x90
        with self.assertRaisesRegex(ValueError, 'unexpected DllMain prologue'):
            patcher.make_patched_bytes(bytes(wrong))

    def test_state(self):
        self.assertEqual(patcher.state(self.dll), 'original')
        self.dll.write_bytes(self.patched)
        self.assertEqual(patcher.state(self.dll), 'patched')
        self.dll.write_bytes(b'unknown')
        self.assertTrue(patcher.state(self.dll).startswith('unknown ('))

    def test_apply_and_revert(self):
        self.assertEqual(patcher.do_apply(self.dll, self.backup), 0)
        self.assertEqual(self.dll.read_bytes(), self.patched)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(patcher.state(self.backup), 'original')
        self.assertEqual(patcher.do_revert(self.dll, self.backup), 0)
        self.assertEqual(self.dll.read_bytes(), self.original)

    def test_refuses_unexpected_dll(self):
        self.dll.write_bytes(b'unexpected payload for state test')
        with self.assertRaises(SystemExit):
            patcher.do_apply(self.dll, self.backup)


if __name__ == '__main__':
    unittest.main()
