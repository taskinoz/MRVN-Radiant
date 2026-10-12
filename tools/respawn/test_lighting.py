"""Lighting corruption, occlusion and experimental writer regressions."""
import math
from pathlib import Path
import struct
import tempfile
import unittest

from bake_direct import BrushTree, evaluate, convex_segment
from inspect_bsp import HEADER_SIZE, inspect
from lighting import (append_lumps, encode_point_lights, records, WORLD_FORMATS,
                      png_rgba, write_atlas_probe, inspect_lighting, payload)


def triangle_bsp(path):
    data = bytearray(HEADER_SIZE)
    struct.pack_into("<4s3I", data, 0, b"rBSP", 37, 1, 127)
    entries = {
        2: (1, "3f6i", [(0, 0, 0, 0, 64, 64, 64, 64, 0)]),
        3: (0, "3f", [(0, 0, 0), (32, 0, 0), (0, 32, 0)]),
        14: (0, "6f2I", [(0, 0, 0, 32, 32, 0, 0, 1)]),
        30: (0, "3f", [(0, 0, 1)]),
        73: (1, "2I2f4B4f2I", [(i, 0, 0, 0, 255, 255, 255, 255, -20, 30, 0, 0, 0, 0) for i in range(3)]),
        79: (0, "H", [(0,), (1,), (2,)]),
        80: (0, "I3H6b2h2BHI", [(0, 1, 0, 2, 0, -1, 0, -1, -1, -1, 0, 0, 0, 0, 0, 0x200)]),
        81: (0, "8f", [(16, 16, 0, 23, 16, 16, 0, 0)]),
        82: (0, "4hi", [(0, -1, -1, 0, 0)]),
    }
    for index, (version, fmt, rows) in entries.items():
        data.extend(bytes((-len(data)) % 4))
        content = b"".join(struct.pack("<" + fmt, *r) for r in rows)
        struct.pack_into("<4I", data, 16 + index * 16, len(data), len(content), version, 0)
        data.extend(content)
    path.write_bytes(data)


def unit_box():
    return (((-1, -1, -1), (1, 1, 1)),
            [(1, 0, 0, 1), (-1, 0, 0, 1), (0, 1, 0, 1),
             (0, -1, 0, 1), (0, 0, 1, 1), (0, 0, -1, 1)])


class LightingTests(unittest.TestCase):
    def test_probe_binds_atlas_and_preserves_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "source.bsp", Path(tmp) / "probe.bsp"
            triangle_bsp(source)
            original = source.read_bytes()
            write_atlas_probe(source, output, "rtl-c", (12, 34, 56, 78), 8)
            result = inspect_lighting(output)
            self.assertEqual(result["issues"], [])
            self.assertEqual(result["sky"]["bytes"], 8 * 8 * 8)
            self.assertEqual(result["rtl"]["bytes"], 8 * 8 * 9)
            self.assertEqual(result["material_lightmap_indices"], {0: 1})
            self.assertEqual(result["pool_73_uv"]["min"], 0.5)
            self.assertEqual(result["pool_73_uv"]["max"], 0.5)
            self.assertEqual(payload(source, inspect(source), 3)[0], payload(output, inspect(output), 3)[0])
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(ValueError):
                write_atlas_probe(output, Path(tmp) / "rebake.bsp", "sky-a", (0, 0, 0, 0))

    def test_missing_atlas_plane_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "source.bsp", Path(tmp) / "bad.bsp"
            triangle_bsp(source)
            append_lumps(source, output, {83: (1, struct.pack("<I2H", 1, 8, 8)),
                                           98: (0, b"\0" * (8 * 8 * 8)),
                                           105: (0, b"\0" * (8 * 8 * 8))})
            self.assertIn("rtl: expected 576", str(inspect_lighting(output)["issues"]))

    def test_blocker_removes_direct_but_preserves_ambient(self):
        lights = [{"origin": (3, 0, 0), "intensity": (1, 0.5, 0.25),
                   "radius": 10, "attenuation": (1, 0, 0)}]
        lit, visible, blocked = evaluate((-3, 0, 0), (1, 0, 0), lights, BrushTree([]))
        self.assertEqual((visible, blocked), (1, 0))
        dark, visible, blocked = evaluate((-3, 0, 0), (1, 0, 0), lights, BrushTree([unit_box()]))
        self.assertEqual((visible, blocked), (0, 1))
        self.assertEqual(dark, (0.03, 0.03, 0.03))
        self.assertGreater(lit[0], dark[0])

    def test_plane_clipping_beats_bounding_box_false_positive(self):
        # Cut the +X,+Y corner off the box: x+y<=0.
        bounds, planes = unit_box()
        tree = BrushTree([(bounds, planes + [(1, 1, 0, 0)])])
        self.assertFalse(tree.blocked((0.8, 0.8, -2), (0.8, 0.8, 2)))
        self.assertTrue(tree.blocked((-0.8, -0.8, -2), (-0.8, -0.8, 2)))

    def test_backface_and_radius_reject_lights(self):
        light = {"origin": (10, 0, 0), "intensity": (1, 1, 1), "radius": 20}
        self.assertEqual(evaluate((0, 0, 0), (-1, 0, 0), [light], BrushTree([]))[0], (0.03,) * 3)
        light["radius"] = 1
        self.assertEqual(evaluate((0, 0, 0), (1, 0, 0), [light], BrushTree([]))[0], (0.03,) * 3)

    def test_invalid_lights_rejected(self):
        for extra in ({"origin": (math.nan, 0, 0)}, {"intensity": (-1, 0, 0)},
                      {"radius": -1}, {"attenuation": (0, 0, 0)}):
            light = {"origin": (1, 2, 3), "intensity": (1, 1, 1)}
            light.update(extra)
            with self.assertRaises(ValueError):
                encode_point_lights([light])

    def test_authored_point_light_record(self):
        data = encode_point_lights([{"origin": (1, 2, 3), "intensity": (0.2, 0.3, 0.4)}])
        self.assertEqual(len(data), 112)
        self.assertEqual(struct.unpack_from("<3f", data), (1, 2, 3))
        # The type field is a point light, cluster and texture references unset.
        self.assertEqual(struct.unpack_from("<3i", data, 48), (-1, 1, 0))
        self.assertEqual(struct.unpack_from("<2i", data, 92), (-1, -1))

    def test_append_preserves_other_offsets_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "input.bsp", Path(tmp) / "output.bsp"
            data = bytearray(HEADER_SIZE)
            struct.pack_into("<4s3I", data, 0, b"rBSP", 37, 1, 127)
            struct.pack_into("<4I", data, 16 + 35 * 16, HEADER_SIZE, 4, 1, 0)
            data.extend(b"TEST")
            source.write_bytes(data)
            append_lumps(source, output, {54: (3, encode_point_lights([]))})
            self.assertEqual(output.read_bytes()[16 + 35 * 16:16 + 36 * 16], data[16 + 35 * 16:16 + 36 * 16])
            self.assertEqual(source.read_bytes(), bytes(data))
            with self.assertRaises(FileExistsError):
                append_lumps(source, output, {54: (3, b"")})
            source.with_name("input.bsp.0036.bsp_lump").write_bytes(b"x")
            with self.assertRaises(ValueError):
                append_lumps(source, Path(tmp) / "sidecar-output.bsp", {54: (3, b"")})

    def test_partial_world_record_and_bad_image_rejected(self):
        with self.assertRaises(ValueError):
            records(b"x", WORLD_FORMATS[3], "test world lights")
        with self.assertRaises(ValueError):
            png_rgba(2, 2, b"\0" * 4)


if __name__ == "__main__":
    unittest.main()
