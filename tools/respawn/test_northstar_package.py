"""Input safety and Quake entity conversion regressions (standard library only)."""
from pathlib import Path
import tempfile
import struct
import unittest

from build_northstar_test_mod import adapt_map, remove_foreign_lighting, MATERIAL
from pack_vpk import pack_files


class NorthstarPackageTests(unittest.TestCase):
    def test_unsafe_or_case_colliding_members_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            for name in ("../bad.bsp", "/bad.bsp", "a\\b.bsp", "c:bad.bsp", "a//b.bsp"):
                with self.assertRaises(ValueError):
                    pack_files({name: b"data"}, root, "client_test.bsp.pak000")
            with self.assertRaises(ValueError):
                pack_files({"maps/X.bsp": b"a", "maps/x.bsp": b"b"}, root,
                           "client_test.bsp.pak000")
            self.assertFalse(root.exists())

    def test_existing_archive_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, block = pack_files({"maps/test.bsp": b"old"}, tmp,
                                          "client_test.bsp.pak000")
            before = directory.read_bytes(), block.read_bytes()
            with self.assertRaises(FileExistsError):
                pack_files({"maps/test.bsp": b"new"}, tmp, "client_test.bsp.pak000")
            self.assertEqual(before, (directory.read_bytes(), block.read_bytes()))

    def test_quake_logic_removed_and_brush_preserved(self):
        text = '''{
"classname" "worldspawn"
}
{
"classname" "func_wall"
"targetname" "quake_door"
{
( 0 0 0 ) ( 1 0 0 ) ( 0 1 0 ) QUAKE 0 0 0 1 1
}
}
{
"classname" "monster_ogre"
}
{
"classname" "info_player_start"
"origin" "480 -352 88"
"angle" "90"
}
'''
        output, brushes, spawns = adapt_map(text)
        self.assertEqual((brushes, spawns), (1, 4))
        self.assertNotIn("func_wall", output)
        self.assertNotIn("monster_ogre", output)
        self.assertNotIn("quake_door", output)
        self.assertIn('( 0 0 0 ) ( 1 0 0 ) ( 0 1 0 ) world/boomtown/boomtown_wall_gapconcrete_01', output)
        self.assertEqual(output.count('"origin" "480 -352 88"'), 4)
        self.assertEqual(output.count('"script_name" "menu_scene_ref"'), 1)
        self.assertEqual(output.count('"script_name" "menu_camera_target"'), 1)

    def test_triggers_doors_and_liquids_cannot_become_static_solids(self):
        face = '( 0 0 0 ) ( 1 0 0 ) ( 0 1 0 ) STONE 0 0 0 1 1'
        entities = []
        for classname in ("worldspawn", "func_wall", "func_door", "func_door_secret", "trigger_once"):
            entities.append('{\n"classname" "' + classname + '"\n{\n' + face + '\n}\n}')
        entities.append('{\n"classname" "worldspawn"\n{\n' + face.replace('STONE', '*water') + '\n}\n}')
        entities.append('{\n"classname" "info_player_start"\n"origin" "0 0 24"\n}')
        stats = {}
        output, brushes, _ = adapt_map('\n'.join(entities), stats)
        self.assertEqual(brushes, 2)
        self.assertEqual(sum(stats["discarded_brushes"].values()), 4)
        self.assertNotIn("trigger_once", output)
        self.assertNotIn("*water", output)

    def test_foreign_lights_removed_without_changing_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.bsp"
            data = bytearray(2064 + 64)
            data[:8] = b"rBSP%\0\0\0"
            struct.pack_into("<4I", data, 16 + 3 * 16, 2064, 12, 0, 0)
            for index in (54, 99, 100):
                struct.pack_into("<4I", data, 16 + index * 16, 2076, 4, 0, 0)
            path.write_bytes(data)
            remove_foreign_lighting(path)
            actual = path.read_bytes()
            self.assertEqual(actual[2064:], bytes(data[2064:]))
            self.assertEqual(actual[16 + 3 * 16:16 + 4 * 16], bytes(data[16 + 3 * 16:16 + 4 * 16]))
            for index in (54, 99, 100):
                self.assertEqual(struct.unpack_from("<2I", actual, 16 + index * 16), (0, 0))


if __name__ == "__main__":
    unittest.main()
