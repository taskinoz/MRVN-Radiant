"""Cross-reference tests with synthetic records, without proprietary assets."""
from pathlib import Path
import struct
import tempfile
import unittest

from inspect_bsp import FormatError, HEADER_SIZE, inspect
from validate_records import SCHEMAS, check_records, load_records, validate


def fixture():
    r = {i: [] for i in SCHEMAS}
    r[1] = [(1, 0, 0, 0), (0.7, 0, 0.7, 64)]
    r[2] = [(0,) * 9]
    r[85] = [(256, 0, 0, 1, 1, 0, 1)]
    r[86] = [(0, 1), (1, 0)]
    r[87] = [(0, 1, 0)]
    r[88] = [(0, 0, 0, -32768, 66, 66, 66, 0)]
    r[91] = [(1,)]
    r[14] = [(0, 0, 0, 64, 64, 64, 0, 1)]
    r[92] = [(0, 0, 0, 1, 1, 0, 64, 64, 64, 0),
             (128, 0, 0, 0, 0, 1, 32, 32, 32, 1)]
    r[93] = [(0,)]
    r[94] = [(0,)] * 13
    r[95] = [(0,) * 8] * 13
    r[3] = [(0, 0, 0)]
    r[30] = [(0, 0, 1)]
    r[71] = [(0, 0, 0, 0, 255, 255, 255, 255)]
    r[79] = [(0,)] * 6  # one triangle plus its degenerate pair padding
    r[80] = [(0, 1, 0, 0, 0, 0, -1, -1, -1, 0, 0, 0, 0, 0, 0x400)]
    r[81] = [(0, 0, 0, 2, 1, 1, 1, 0)]
    r[82] = [(0, -1, -1, 0, 0)]
    return r


class RecordTests(unittest.TestCase):
    def test_surface_range_uses_sort_base_and_inclusive_last(self):
        r = fixture()
        r[71] *= 4
        r[82][0] = (0, -1, -1, 0, 2)
        self.assertEqual(check_records(r), [])
        mesh = list(r[80][0])
        mesh[2] = 2  # Wrong absolute offset: engine adds the base again.
        r[80][0] = tuple(mesh)
        self.assertIn("inclusive surface vertex range", str(check_records(r)))
        mesh[2], mesh[3] = 0, 2  # Wrong count rather than last index.
        r[80][0] = tuple(mesh)
        self.assertIn("inclusive surface vertex range", str(check_records(r)))

    def test_triangles_must_belong_to_surface_range(self):
        r = fixture()
        r[71] *= 2
        r[79][0] = (1,)
        self.assertIn("triangle vertex outside inclusive", str(check_records(r)))

    def test_odd_meshes_need_pair_padding(self):
        r = fixture()
        r[79] = [(0,)] * 3
        self.assertIn("degenerate padding triangle", str(check_records(r)))
        r = fixture()
        r[79] = [(0,)] * 9
        r[80].append(r[80][0][:0] + (3,) + r[80][0][1:])
        self.assertIn("triangle slice not aligned", str(check_records(r)))

    def test_valid_slope_followed_by_box(self):
        self.assertEqual(check_records(fixture()), [])

    def test_axial_brush_requires_accumulated_side_offset(self):
        r = fixture()
        r[92][1] = r[92][1][:-1] + (0,)
        self.assertIn("preceding non-axial", str(check_records(r)))

    def test_plane_reference_underflow(self):
        r = fixture()
        r[93] = [(2,)]
        self.assertIn("cutting plane", str(check_records(r)))

    def test_texture_flags_are_separate_from_index(self):
        r = fixture()
        r[94][0] = (0x4000,)
        self.assertEqual(check_records(r), [])
        r[94][0] = (0x4001,)
        self.assertIn("texture reference", str(check_records(r)))

    def test_triangle_uses_material_sort_offset(self):
        r = fixture()
        r[71].append(r[71][0])
        r[82][0] = (0, -1, -1, 0, 1)
        self.assertEqual(check_records(r), [])
        r[79][0] = (1,)
        self.assertIn("selected vertex pool", str(check_records(r)))

    def test_tangent_space_unlit_selects_own_pool(self):
        r = fixture()
        r[80][0] = r[80][0][:-1] + (0x600,)
        self.assertIn("selected vertex pool", str(check_records(r)))
        r[74] = [(0, 0, 0, 0, 255, 255, 255, 255, 0, 0)]
        self.assertEqual(check_records(r), [])

    def test_zero_radius_and_parallel_side_counts(self):
        r = fixture()
        r[81][0] = (0, 0, 0, 0, 1, 1, 1, 0)
        r[95].pop()
        issues = str(check_records(r))
        self.assertIn("zero bounding radius", issues)
        self.assertIn("different counts", issues)

    def test_collision_grid_and_geo_set_ranges(self):
        r = fixture()
        r[86][0] = (1, 1)
        self.assertIn("geo-set slice", str(check_records(r)))
        r = fixture()
        r[87][0] = (0, 1, 2 << 8)
        self.assertIn("brush reference", str(check_records(r)))
        r = fixture()
        r[87][0] = (0, 2, 0)
        self.assertIn("primitive slice", str(check_records(r)))

    def test_collision_contents_and_grid_shape(self):
        r = fixture()
        r[87][0] = (0, 1, 1)
        self.assertIn("contents reference", str(check_records(r)))
        r = fixture()
        r[85][0] = (0, 0, 0, 1, 1, 0, 1)
        self.assertIn("grid scale", str(check_records(r)))
        r = fixture()
        r[86].pop()
        self.assertIn("grid-cell count", str(check_records(r)))

    def test_default_sidecar_is_used_and_bad_stride_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.bsp"
            header = bytearray(struct.pack("<4s3I", b"rBSP", 29, 0, 127))
            header.extend(bytes(HEADER_SIZE - len(header)))
            path.write_bytes(header)
            sidecar = path.with_name(path.name + ".005d.bsp_lump")
            sidecar.write_bytes(struct.pack("<H", 5))
            self.assertEqual(load_records(path, inspect(path))[93], [(5,)])
            sidecar.write_bytes(b"x")
            with self.assertRaises(FormatError):
                load_records(path, inspect(path))

    def test_unknown_schema_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.bsp"
            path.write_bytes(struct.pack("<4s3I", b"rBSP", 47, 0, 127) + bytes(2048))
            with self.assertRaises(FormatError):
                validate(path)

    def test_encoded_records_are_not_decoded_as_plain_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.bsp"
            header = bytearray(struct.pack("<4s3I", b"rBSP", 29, 0, 127) + bytes(2048))
            struct.pack_into("<4I", header, 16 + 93 * 16, HEADER_SIZE, 2, 0, 1)
            path.write_bytes(header + b"xx")
            with self.assertRaises(FormatError):
                validate(path)

    def test_client_sidecar_does_not_hide_invalid_default_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.bsp"
            header = bytearray(struct.pack("<4s3I", b"rBSP", 29, 0, 127) + bytes(2048))
            struct.pack_into("<4I", header, 16 + 93 * 16, 0, 2, 0, 0)
            path.write_bytes(header)
            path.with_name(path.name + ".005d.bsp_lump.client").write_bytes(b"xx")
            with self.assertRaises(FormatError):
                validate(path)


if __name__ == "__main__":
    unittest.main()
