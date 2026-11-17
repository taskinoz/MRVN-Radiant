"""Export ownership/rollback tests with an original synthetic BSP and fake native session."""
from pathlib import Path
import struct
from unittest.mock import patch
import tempfile
import unittest

from build_tf1_navigation import export
from inspect_bsp import HEADER_SIZE


class FakeControl:
    def console(self, command):
        if command.startswith('updateain "'):
            path = Path(command[len('updateain "'):-1])
            path.write_bytes(struct.pack('<4I', 54, 6, 0, 1) + bytes(68) + bytes(8))


class FakeHarness:
    AIN_BUILD_FLAG = '-r1delta_build_ain_no_existing'

    def __init__(self):
        self.run_checks = lambda *args: None
        self.prepared = []
        self.cleaned = []
        self.fail = False

    def find_app(self):
        return Path('fake-app')

    def find_game(self):
        return Path('fake-game')

    def prepare(self, app, game, maps, name):
        if (maps / 'graphs' / (name + '.ain')).exists():
            raise AssertionError('pre-existing graph was staged before native build')
        session = {'map': name, 'maps': maps}
        self.prepared.append(session)
        return session

    def validate_checks(self, checks):
        return checks

    def attempt(self, session, checks, output, timeout):
        if not session['build_navigation']:
            raise AssertionError('native initialization was not requested')
        if self.fail:
            raise RuntimeError('fake launch failed')
        self.run_checks(FakeControl(), checks, 1, output, [], [])
        return {'loaded': True, 'finished': True, 'errors': []}

    def cleanup(self, session):
        self.cleaned.append(session)

    def navigation_graph(self, bsp):
        return (bsp.parent / 'graphs' / (bsp.stem + '.ain')).read_bytes()


class NavigationExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.maps = self.root / 'source'
        self.maps.mkdir()
        self.output = self.root / 'export'
        self.h = FakeHarness()
        self.runtime_guard = patch('build_tf1_navigation.validate_runtime', return_value={})
        self.runtime_guard.start()
        self.addCleanup(self.runtime_guard.stop)
        self.bsp = self.maps / 'mp_original.bsp'
        header = bytearray(HEADER_SIZE)
        struct.pack_into('<4s3I', header, 0, b'rBSP', 29, 6, 127)
        struct.pack_into('<4I', header, 16 + 3 * 16, HEADER_SIZE, 9, 0, 0)
        self.bsp.write_bytes(header + b'123456789')

    def test_native_copy_and_source_graph_are_preserved(self):
        (self.maps / 'graphs').mkdir()
        original = self.maps / 'graphs/mp_original.ain'
        original.write_bytes(b'original source graph must not be touched')
        prior = self.h.run_checks
        result = export(self.h, self.maps, 'mp_original', self.output)
        self.assertEqual(original.read_bytes(), b'original source graph must not be touched')
        self.assertEqual(result['crc']['map_crc'], 0x340bc6d9)
        self.assertFalse(result['crc']['graph']['crc_matches'])
        self.assertEqual(self.h.cleaned, self.h.prepared)
        self.assertIs(self.h.run_checks, prior)
        self.assertEqual((self.output / 'maps/mp_original.bsp').read_bytes(), self.bsp.read_bytes())
        self.assertEqual(struct.unpack_from('<I', (self.output / 'native-built.ain').read_bytes(), 8)[0], 0)
        self.assertEqual(struct.unpack_from('<I', (self.output / 'maps/graphs/mp_original.ain').read_bytes(), 8)[0], 0x340bc6d9)

    def test_failed_native_attempt_cleans_owned_session_and_restores_hook(self):
        self.h.fail = True
        prior = self.h.run_checks
        with self.assertRaisesRegex(RuntimeError, 'fake launch failed'):
            export(self.h, self.maps, 'mp_original', self.output)
        self.assertEqual(self.h.cleaned, self.h.prepared)
        self.assertIs(self.h.run_checks, prior)
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_unknown_runtime_fails_before_output_or_game_mutation(self):
        with patch('build_tf1_navigation.validate_runtime', side_effect=ValueError('profile mismatch')):
            with self.assertRaisesRegex(ValueError, 'profile mismatch'):
                export(self.h, self.maps, 'mp_original', self.output)
        self.assertEqual(self.h.prepared, [])
        self.assertFalse(self.output.exists())

    def test_existing_output_is_not_mutated(self):
        self.output.mkdir()
        marker = self.output / 'user.txt'
        marker.write_text('keep')
        with self.assertRaises(FileExistsError):
            export(self.h, self.maps, 'mp_original', self.output)
        self.assertEqual(marker.read_text(), 'keep')
        self.assertEqual(self.h.prepared, [])

    def test_unsupported_adapter_name_and_timeout_fail_before_launch(self):
        for name, timeout in (('../mp_original', 300), ('mp_original', float('nan')),
                              ('mp_original', float('inf')), ('mp_original', 0)):
            with self.subTest(name=name, timeout=timeout), self.assertRaises(ValueError):
                export(self.h, self.maps, name, self.output, timeout=timeout)
            self.assertFalse(self.output.exists())
            self.assertEqual(self.h.prepared, [])
        self.h.AIN_BUILD_FLAG = None
        with self.assertRaises(ValueError):
            export(self.h, self.maps, 'mp_original', self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
