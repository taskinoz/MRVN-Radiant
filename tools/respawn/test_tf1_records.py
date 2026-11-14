"""Reject v29 auxiliary records that the generic R1/R2 schema used to skip."""
import unittest
from pathlib import Path
import struct
import tempfile

from inspect_bsp import HEADER_SIZE, FormatError, inspect
from validate_records import TF1_SCHEMAS, check_tf1_records, load_records


def fixture():
    records = {index: [] for index in TF1_SCHEMAS}
    records.update({2: [(0,) * 9], 82: [(0, 0, 0, 0, 0)], 107: [(0, 0, 1, 0)]})
    records[36] = [(64., 0., 0)]
    records[83] = [(0, 2, 2)]
    records[101] = [(0,)]
    records[102] = [(0,), (0xffff,)]
    records[104] = [(0., 0., 0., 0)]
    inventory = {'lumps': [{'length': 0, 'external_files': []} for _ in range(128)]}
    inventory['lumps'][98]['length'] = 32
    inventory['lumps'][105]['length'] = 16
    return records, inventory


class Tf1AuxiliaryTests(unittest.TestCase):
    def test_valid_records_and_missing_probe_sentinel(self):
        self.assertEqual(check_tf1_records(*fixture()), [])

    def test_missing_rtl_plane_is_not_silently_accepted(self):
        records, inventory = fixture()
        inventory['lumps'][105]['length'] = 0
        self.assertIn('expected 16', str(check_tf1_records(records, inventory)))

    def test_water_range_and_material_must_be_valid(self):
        for water in ((0, 64, 0), (float('nan'), 0, 0), (64, 0, -1), (64, 0, 1)):
            records, inventory = fixture()
            records[36] = [water]
            self.assertTrue(check_tf1_records(records, inventory))

    def test_probe_indices_and_positions_are_checked(self):
        for lump, row in ((104, (0, 0, 0, 1)), (104, (0, float('inf'), 0, 0)), (102, (1,))):
            records, inventory = fixture()
            records[lump] = [row]
            self.assertTrue(check_tf1_records(records, inventory))

    def test_cell_water_indices_use_the_signed_dry_sentinel(self):
        records, inventory = fixture()
        records[107] = [(0, 0, 1, -1)]
        self.assertEqual(check_tf1_records(records, inventory), [])
        for water in (-2, 1):
            records[107] = [(0, 0, 1, water)]
            self.assertIn('cell water reference', str(check_tf1_records(records, inventory)))

    def test_light_atlas_reference_and_dimensions_are_checked(self):
        records, inventory = fixture()
        records[82] = [(0, 1, 0, 0, 0)]
        self.assertIn('outside LIGHTMAP_HEADERS', str(check_tf1_records(records, inventory)))
        records, inventory = fixture()
        records[83] = [(0, 0, 2)]
        self.assertIn('invalid lightmap dimensions', str(check_tf1_records(records, inventory)))

    def test_default_external_plane_is_used_without_client_override(self):
        records, inventory = fixture()
        inventory['lumps'][105]['external_files'] = [
            {'variant': 'client', 'size': 1}, {'variant': 'default', 'size': 16}]
        inventory['lumps'][105]['length'] = 1
        self.assertEqual(check_tf1_records(records, inventory), [])
        inventory['lumps'][105]['external_files'][1]['size'] = 15
        self.assertTrue(check_tf1_records(records, inventory))

    def test_nonfinite_world_light_is_rejected(self):
        records, inventory = fixture()
        light = [0.] * 25
        light[19] = float('nan')
        records[54] = [light]
        self.assertIn('nonfinite world light', str(check_tf1_records(records, inventory)))

    def test_tree_cycles_ranges_and_split_values_are_checked(self):
        for nodes, message in (([(3, 2)], 'leaf range'), ([(8, 0)], 'child outside'),
                               ([(0, 0), (3, 1)], 'cycle'),
                               ([(4, 0x7fc00000), (3, 1), (3, 1)], 'nonfinite')):
            records, inventory = fixture()
            records[103] = nodes
            self.assertIn(message, str(check_tf1_records(records, inventory)))
        records, inventory = fixture()
        records[103] = [(4, 0), (3, 1), (3, 1)]
        self.assertEqual(check_tf1_records(records, inventory), [])

    def test_v29_world_light_stride_does_not_leak_into_v37(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'light.bsp'
            def write(version, length, record_version):
                header = bytearray(HEADER_SIZE)
                struct.pack_into('<4s3I', header, 0, b'rBSP', version, 0, 127)
                struct.pack_into('<4I', header, 16 + 54 * 16, HEADER_SIZE, length, record_version, 0)
                path.write_bytes(header + bytes(length))
            write(29, 100, 1)
            self.assertEqual(len(load_records(path, inspect(path))[54]), 1)
            for length, version in ((99, 1), (100, 3)):
                write(29, length, version)
                with self.assertRaises(FormatError):
                    load_records(path, inspect(path))
            write(37, 112, 3)
            self.assertNotIn(54, load_records(path, inspect(path)))


if __name__ == '__main__':
    unittest.main()
