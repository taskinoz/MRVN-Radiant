"""Original synthetic conversion regressions; no game assets required."""
import io
import math
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from game_lump import ENTRY, PROP
from inspect_bsp import FormatError
from repair_tf1_port import OLD_PROP, append, bake_input, recover_zip, restore_props, source_props


def fixtures():
    names = struct.pack('<I', 1) + b'models/test.mdl'.ljust(128, b'\0')
    # Source v12: 0.7 scale, white modulation, unit fade scale.
    old = (10., 20., 30., 0., 90., 0., 0, 0, 0, 6, 4, 2, -1,
           -1., -1., 10., 20., 30., 1., 0, 0, 0, 0, 255, 255, 255, 255, 0, .7, 0x400000, 0x200400b)
    counts = struct.pack('<3I', 1, 1, 0)
    payload = names + struct.pack('<I', 0) + counts + OLD_PROP.pack(*old)
    original = struct.pack('<I', 1) + ENTRY.pack(b'prps', 0, 12, 4096+20, len(payload)) + payload
    port_prop = (*old[:6], 1., 0, 6, 4, 2, 0xffff, -1., 0., 0., 0., -1, -1, -1, -1, 0, 0, 0, 0, 0, 0)
    payload = names + counts + PROP.pack(*port_prop)  # Missing TF2 trailer
    port = struct.pack('<I', 1) + ENTRY.pack(b'prps', 0, 13, 8192+20, len(payload)) + payload
    return original, port


class PortRepairTests(unittest.TestCase):
    def test_bridge_light_vectors_keep_direction_separate_from_colour(self):
        data = bytearray(2064)
        inv = {'lumps': [{'offset': 0, 'length': 0} for _ in range(128)]}
        for index, payload in {43: b'world/test\0', 44: struct.pack('<I', 0),
                               83: struct.pack('<I2H', 1, 64, 64), 104: struct.pack('<3fI', 0, 0, 0, 0)}.items():
            inv['lumps'][index] = {'offset': len(data), 'length': len(payload)}
            data += payload
        records = {14: [(0, 0, 0, 64, 64, 64, 0, 0)], 80: [], 85: [], 92: []}
        light = (10, 20, 30, .25, .5, .75, 0, 0, -1, 0, 0, 0,
                 0, 3, 0, 1, 0, 0, 0, 1, 0, 0, 24, -1, -1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'test.rbl'
            bake_input(path, data, inv, records, [light])
            stream = path.read_bytes()
        values = struct.unpack_from('<15d', stream, struct.calcsize('<4s5I3d')+8+16)
        self.assertEqual(values[:3], (10, 20, 30))
        self.assertEqual(values[3:6], (0, 0, -1))
        self.assertEqual(values[6:9], (.25, .5, .75))

    def test_restores_source_fields_and_missing_trailer(self):
        a, b = fixtures()
        payload, report, changes = restore_props(a, 4096, b, 8192)
        p = report['placements'][0]
        self.assertAlmostEqual(p['scale'], .7)
        self.assertEqual(p['diffuse_modulation'], (255, 255, 255, 255))
        self.assertEqual(p['fade_scale'], 1.)
        self.assertEqual(p['skin'], 2)
        self.assertEqual(p['cubemap_raw'], 65535)
        self.assertEqual(p['cpu_levels'], (-1, -1))
        self.assertEqual(p['gpu_levels'], (-1, -1))
        self.assertEqual(payload[-4:], bytes(4))
        self.assertEqual(changes['restored'], {'scale': 1, 'fade_scale': 1, 'diffuse_modulation': 1})

    def test_does_not_truncate_unmapped_contents_masks(self):
        a, b = fixtures()
        _, report, changes = restore_props(a, 4096, b, 8192)
        self.assertEqual(report['placements'][0]['collision_flags'], (0, 0))
        self.assertEqual(changes['unmapped_collision_masks'][0]['tf1_add'], 0x400000)

    def test_rejects_different_prop_identity(self):
        a, b = fixtures()
        b = bytearray(b)
        struct.pack_into('<f', b, 20+132+12, 999.)
        with self.assertRaisesRegex(FormatError, 'identity differs'):
            restore_props(a, 4096, b, 8192)

    def test_rejects_source_tail_and_nonfinite_scale(self):
        a, b = fixtures()
        a = bytearray(a)
        struct.pack_into('<f', a, 20+132+4+12+72, math.nan)
        with self.assertRaisesRegex(FormatError, 'original scale'):
            restore_props(a, 4096, b, 8192)
        a, _ = fixtures()
        a = bytearray(a)
        struct.pack_into('<I', a, 16, len(a)-19)
        a.append(0)
        with self.assertRaisesRegex(FormatError, 'prop size or trailing'):
            source_props(a, 4096)

    def test_repairs_four_byte_shifted_zip_and_excludes_padding(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr('materials/test.vmt', 'test')
        payload = stream.getvalue()
        start = 4096
        data = bytes(start) + payload + bytes(3) + b'LIGHTS'
        inv = {'lumps': [{'offset': start+4, 'length': len(payload)} for _ in range(128)]}
        inv['lumps'][105] = {'offset': start+len(payload)+3, 'length': 6}
        offset, size, members = recover_zip(data, inv)
        self.assertEqual((offset, size), (start, len(payload)))
        self.assertEqual(list(members), ['materials/test.vmt'])

    def test_refuses_zip_guess_when_signature_is_missing(self):
        inv = {'lumps': [{'offset': 4096, 'length': 8} for _ in range(128)]}
        with self.assertRaisesRegex(FormatError, 'signature'):
            recover_zip(bytes(8192), inv)

    def test_append_preserves_existing_payload_and_aligns_directory(self):
        data = bytearray(2067)
        data[-3:] = b'OLD'
        at = append(data, 54, 3, b'NEW')
        self.assertEqual(at % 16, 0)
        self.assertEqual(data[2064:2067], b'OLD')
        self.assertEqual(data[at:], b'NEW')
        self.assertEqual(struct.unpack_from('<4I', data, 16+54*16), (at, 3, 3, 0))


if __name__ == '__main__':
    unittest.main()
