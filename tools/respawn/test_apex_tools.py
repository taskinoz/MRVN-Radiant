"""Offline tests for the Apex staging, Cast conversion and fixture tools.

Original implementation, GPL-2.0-or-later.
"""
import json
import struct
import tempfile
import unittest
from pathlib import Path

import apex_native_regression
import cast_to_obj
import stage_r5_map


def cast_property(ptype, name, values, fmt, width=1):
    payload = struct.pack(f"<{len(values) * width}{fmt}", *[c for v in values for c in (v if width > 1 else (v,))])
    return struct.pack("<HHI", ptype, len(name), len(values)) + name.encode() + payload


def cast_node(kind, hash_, properties, children=()):
    body = b"".join(properties) + b"".join(children)
    return struct.pack("<IIQII", kind, 24 + len(body), hash_, len(properties), len(children)) + body


def minimal_bsp(mins, maxs):
    header = bytearray(16 + 128 * 16)
    header[:4] = b"rBSP"
    struct.pack_into("<H", header, 4, 47)
    model = struct.pack("<6f", *mins, *maxs) + bytes(8)
    struct.pack_into("<II", header, 16 + 14 * 16, len(header), len(model))
    return bytes(header) + model


class CastToObjTest(unittest.TestCase):
    def test_triangle_is_written_y_up_with_reversed_winding(self):
        mesh = cast_node(cast_to_obj.NODE_MESH, 2, [
            cast_property(0x7633, "vp", [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)], "f", 3),
            cast_property(0x62, "f", [0, 1, 2], "B")])
        data = struct.pack("<IIII", cast_to_obj.CAST_MAGIC, 1, 1, 0) + cast_node(0x746F6F72, 1, [], [mesh])
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder, "m_LOD0.cast"), Path(folder, "m.obj")
            source.write_bytes(data)
            self.assertEqual(cast_to_obj.cast_to_obj(source, target)["triangles"], 1)
            lines = target.read_text().splitlines()
        self.assertIn("v 1.000000 3.000000 -2.000000", lines)
        self.assertIn("f 1 3 2", lines)

    def test_rejects_non_cast(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "x.cast")
            path.write_bytes(b"nope" + bytes(12))
            with self.assertRaises(ValueError):
                cast_to_obj.read_cast(path)


class StageR5MapTest(unittest.TestCase):
    def test_package_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "build").mkdir()
            bsp = root / "build/box.bsp"
            bsp.write_bytes(minimal_bsp((-64, -64, 0), (64, 64, 128)))
            (root / "build/box_spawn.ent").write_bytes(
                b'ENTITIES02 num_models=1\n{\n"classname" "info_player_start"\n"origin" "8 16 32"\n}\n\0')
            manifest = stage_r5_map.build_package(bsp, root / "pkg", "mp_mrvn_unit")
            for part in stage_r5_map.PARTITIONS:
                self.assertIn(f"maps/mp_mrvn_unit_{part}.ent", manifest["files"])
            self.assertIn("vpk/englishserver_mp_mrvn_unit.bsp.pak000_dir.vpk", manifest["files"])
            self.assertIn("vpk/englishclient_mp_mrvn_unit.bsp.pak000_dir.vpk", manifest["files"])
            script = (root / "pkg/platform/scripts/vscripts/mp/levels/_mp_mrvn_unit.nut").read_text()
            self.assertIn("<8.0,16.0,32.0>", script)

            game = root / "game"
            game.mkdir()
            installed = stage_r5_map.install(root / "pkg", game)
            self.assertTrue((game / "maps/mp_mrvn_unit.bsp").is_file())
            # Reinstalling over our own files is allowed.
            stage_r5_map.install(root / "pkg", game)
            removed = stage_r5_map.uninstall(game, "mp_mrvn_unit")
            self.assertEqual(sorted(removed), sorted(installed))
            self.assertFalse((game / "maps/mp_mrvn_unit.bsp").exists())

    def test_refuses_unowned_files_and_bad_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bsp = root / "box.bsp"
            bsp.write_bytes(minimal_bsp((0, 0, 0), (1, 1, 1)))
            stage_r5_map.build_package(bsp, root / "pkg", "mp_mrvn_owned")
            game = root / "game"
            (game / "maps").mkdir(parents=True)
            (game / "maps/mp_mrvn_owned.bsp").write_bytes(b"someone else's")
            with self.assertRaises(FileExistsError):
                stage_r5_map.install(root / "pkg", game)
            with self.assertRaises(ValueError):
                stage_r5_map.level_name("mp_rr_canyonlands")

    def test_rejects_other_bsp_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            bsp = Path(folder, "old.bsp")
            data = bytearray(minimal_bsp((0, 0, 0), (1, 1, 1)))
            struct.pack_into("<H", data, 4, 37)
            bsp.write_bytes(data)
            with self.assertRaises(ValueError):
                stage_r5_map.bsp_bounds(bsp)


class FixtureTest(unittest.TestCase):
    def test_fixture_brushes_and_expected_fractions(self):
        text = apex_native_regression.fixture(with_props=True)
        self.assertEqual(text.count('"classname" "prop_static"'), 3)
        self.assertEqual(text.count("{"), text.count("}"))
        expected = {name: value for name, _, _, _, value in apex_native_regression.checks(True)}
        self.assertAlmostEqual(expected["ramp_middle"], 300 / 410)
        self.assertAlmostEqual(expected["ceiling_hull"], 184 / 512)
        self.assertNotIn("barrel_side", {c[0] for c in apex_native_regression.checks(False)})

    def test_ramp_planes_face_outward(self):
        # Radiant plane normal = (c - a) x (b - a); every side must face away
        # from the wedge's interior point.
        inside = (-700, -700, 50)
        for line in apex_native_regression.ramp(-900, -900, -500, -500, 200).splitlines()[1:-1]:
            points = [tuple(map(float, p.split())) for p in line.split(")")[:3] for p in [p.split("(")[1]]]
            a, b, c = points
            u = [c[i] - a[i] for i in range(3)]
            v = [b[i] - a[i] for i in range(3)]
            normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            offset = sum(normal[i] * (inside[i] - a[i]) for i in range(3))
            self.assertLess(offset, 0, line)


if __name__ == "__main__":
    unittest.main()
