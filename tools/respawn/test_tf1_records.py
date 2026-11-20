"""Reject v29 auxiliary records that the generic R1/R2 schema used to skip."""
import unittest
from pathlib import Path
import struct
import tempfile

from inspect_bsp import HEADER_SIZE, FormatError, inspect
from validate_records import TF1_SCHEMAS, check_tf1_mesh_metadata, check_tf1_records, load_records


def fixture():
    records = {index: [] for index in TF1_SCHEMAS}
    records.update({2: [(0,) * 9], 80: [], 82: [(0, 0, 0, 0, 0)], 107: [(0, 0, 1, 0)]})
    records[36] = [(64., 0., 0)]
    records[83] = [(0, 2, 2)]
    records[101] = [(0,)]
    records[102] = [(0,), (0xffffffff,)]
    records[104] = [(0., 0., 0., 0)]
    inventory = {'lumps': [{'length': 0, 'external_files': []} for _ in range(128)]}
    inventory['lumps'][98]['length'] = 32
    inventory['lumps'][105]['length'] = 16
    return records, inventory


class Tf1AuxiliaryTests(unittest.TestCase):
    def test_mesh_metadata_uses_inclusive_unsigned_sort_span(self):
        records, _ = fixture()
        records[80] = [(0, 2, 0, 4, 3, *([0] * 8), 0, 0x600),
                       (6, 2, 65530, 5, 3, *([0] * 8), 0, 0x600)]
        records[82] = [(0, 0, 0, -1, 0)]
        self.assertEqual(check_tf1_mesh_metadata(records), [])
        mesh = records[80][0]
        records[80][0] = (*mesh[:4], 2, *mesh[5:])
        records[82][0] = (0, 0, 0, -2, 0)
        self.assertEqual([issue['lump'] for issue in check_tf1_mesh_metadata(records)], [80, 82])

    def test_shadow_mesh_local_indices_and_pool_selection(self):
        records, inventory = fixture()
        records[124] = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
        records[125] = [(0., 0., 1., 0., 0.)] * 3
        records[126] = [(0,), (1,), (2,)] * 2
        records[127] = [(0, 1, 1, -1), (0, 1, 0, 0)]
        self.assertEqual(check_tf1_records(records, inventory), [])
        records[127][1] = (1, 1, 0, 0)
        self.assertIn('mesh-local index', str(check_tf1_records(records, inventory)))

    def test_shadow_stream_lengths_selectors_and_materials(self):
        for mesh, message in (((0, 1, 2, -1), 'opaque selector'),
                              ((0, 1, 0, -1), 'shadow material'),
                              ((0, 1, 1, 1), 'shadow material'),
                              ((4, 0, 1, -1), 'vertex base'),
                              ((0, 2, 1, -1), 'triangle range')):
            records, inventory = fixture()
            records[124] = [(0., 0., 0.)] * 3
            records[126] = [(0,), (1,), (2,)]
            records[127] = [mesh]
            self.assertIn(message, str(check_tf1_records(records, inventory)))
        records, inventory = fixture()
        records[126] = [(0,)]
        self.assertIn('do not consume', str(check_tf1_records(records, inventory)))

    def test_occlusion_triangles_and_finite_shadow_vertices(self):
        records, inventory = fixture()
        records[117] = [(0., 0., 0.)] * 3
        records[118] = [(0,), (1,), (2,)]
        self.assertEqual(check_tf1_records(records, inventory), [])
        records[118] = [(3,)]
        issues = str(check_tf1_records(records, inventory))
        self.assertIn('not a triangle list', issues)
        self.assertIn('occlusion index outside', issues)
        for lump, vertex in ((117, (float('nan'), 0., 0.)),
                             (124, (0., float('inf'), 0.)),
                             (125, (0., 0., 0., float('nan'), 0.))):
            records, inventory = fixture()
            records[lump] = [vertex]
            self.assertIn('nonfinite occlusion/shadow vertex', str(check_tf1_records(records, inventory)))

    def test_csm_bounds_children_and_reference_ranges(self):
        # One root with a leaf child and one shadow-object reference.
        root = (0., 0., 0., 1, 0, 1, 10., 10., 10., 1, 0)
        leaf = (0., 0., 0., 0, 1, 1, 10., 10., 10., 0, 0)
        records, inventory = fixture()
        records[99], records[100] = [root, leaf], [(60000,)]
        self.assertEqual(check_tf1_records(records, inventory), [])
        # Without LEVEL_INFO, only the reference slice can be checked.
        for field, value, message in ((0, float('nan'), 'bounds'), (6, -1., 'bounds'),
                                      (9, 2, 'child range'), (5, 2, 'reference range'),
                                      (4, 2, 'reference range')):
            bad = list(root)
            bad[field] = value
            records[99] = [tuple(bad), leaf]
            self.assertIn(message, str(check_tf1_records(records, inventory)))

    def test_csm_prop_ids_use_aligned_level_info_range(self):
        records, inventory = fixture()
        records[123] = [(0, 0, 5, 2, 0., 0., 0.)]
        records[99] = [(0., 0., 0., 0, 2, 2, 1., 1., 1., 0, 0)]
        records[100] = [(64,), (65,)]
        self.assertEqual(check_tf1_records(records, inventory), [])
        records[100] = [(5,), (66,)]
        self.assertEqual([issue['lump'] for issue in check_tf1_records(records, inventory)], [100, 100])

    def test_csm_cycles_are_rejected(self):
        records, inventory = fixture()
        records[99] = [(0., 0., 0., 1, 0, 0, 1., 1., 1., 0, 0)]
        self.assertIn('CSM tree cycle', str(check_tf1_records(records, inventory)))

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


    def test_v29_tangent_words_index_vertex_normals(self):
        records, inventory = fixture()
        records[3], records[30] = [(0., 0., 0.)], [(0., 0., 1.), (1., 0., 0.)]
        records[73] = [(0, 0, 0., 0., 0, 0, 0, 0, 0., 0., 0., 0., 1, 0)]
        records[74] = [(0, 0, 0., 0., 0, 0, 0, 0, 0, 1)]
        self.assertEqual(check_tf1_records(records, inventory), [])
        records[73] = [(0, 0, 0., 0., 0, 0, 0, 0, 0., 0., 0., 0., 2, 0)]
        records[74] = [(0, 0, 0., 0., 0, 0, 0, 0, 0, 0x80000001)]
        self.assertEqual([issue['lump'] for issue in check_tf1_records(records, inventory)], [73, 74])

    def test_blinn_phong_references_and_values(self):
        records, inventory = fixture()
        records[3], records[30] = [(0., 0., 0.)], [(0., 0., 1.)]
        vertex = (0, 0, 0., 0., 0, 0, 0, 0, 0., 0., 0., 0., 0., 1.)
        records[75] = [vertex]
        self.assertEqual(check_tf1_records(records, inventory), [])
        for field, value, message in ((0, 1, 'position or normal'), (1, 1, 'position or normal'),
                                      (2, float('nan'), 'nonfinite'), (13, float('inf'), 'nonfinite')):
            bad = list(vertex)
            bad[field] = value
            records[75] = [tuple(bad)]
            self.assertIn(message, str(check_tf1_records(records, inventory)))

    def test_blinn_phong_and_probe_strides(self):
        self.assertEqual(struct.calcsize('<' + TF1_SCHEMAS[75][0]), 44)
        self.assertEqual(struct.calcsize('<' + TF1_SCHEMAS[102][0]), 4)


if __name__ == '__main__':
    unittest.main()
