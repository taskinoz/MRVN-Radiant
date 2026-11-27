#!/usr/bin/env python3
"""Tests for entity_corpus.py on a synthetic map."""
import struct
import tempfile
import unittest
from pathlib import Path

import entity_corpus


def write_map(folder, name, lump, partitions):
    entities = lump.encode() + b"\0"
    header = b"rBSP" + struct.pack("<ii", 37, 1) + struct.pack("<i", 127)
    directory = struct.pack("<iiii", 16 + 128 * 16, len(entities), 0, 0) + bytes(16 * 127)
    bsp = folder / f"{name}.bsp"
    bsp.write_bytes(header + directory + entities)
    for part, text in partitions.items():
        (folder / f"{name}_{part}.ent").write_bytes(b"ENTITIES01\n" + text.encode() + b"\0")
    return bsp


class EntityCorpusTests(unittest.TestCase):
    def test_survey_partitions_keys_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bsp = write_map(folder, "mp_test",
                            '{\n"classname" "worldspawn"\n}\n{\n"classname" "func_brush"\n"model" "*1"\n}\n',
                            {"env": '{\n"classname" "light"\n"_light" "255 255 255 200"\n}\n'
                                    '{\n"classname" "light"\n"_light" "255 0 0 200"\n}\n',
                             "script": '{\n"classname" "info_target"\n"editorclass" "info_target_fx"\n'
                                       '"targetname" "a"\n}\n'
                                       '{\n"classname" "trigger_multiple"\n"model" "*2"\n"*coll0" "x"\n}\n'})
            data = entity_corpus.survey([bsp])
            self.assertEqual(data["light"]["partition"], "env")
            self.assertEqual(data["light"]["count"], 2)
            self.assertEqual(data["func_brush"]["partition"], "bsp")
            self.assertTrue(data["func_brush"]["brush"])
            self.assertFalse(data["func_brush"]["coll"])
            self.assertTrue(data["trigger_multiple"]["coll"])
            self.assertIn("info_target_fx", data)  # editorclass names the editor class
            self.assertEqual(data["info_target_fx"]["classnames"], {"info_target": 1})
            xml = entity_corpus.ent_xml("Test", data, {"worldspawn"})
            self.assertIn('<group name="func_brush"', xml)
            self.assertNotIn('name="worldspawn"', xml)
            self.assertNotIn('key="*coll0"', xml)
            self.assertIn('<color key="_light" name="_light" value="255 255 255 200">', xml)  # half share keeps it
            header = entity_corpus.header({"Test": (["mp_test"], data)})
            self.assertIn('{"trigger_multiple", EntPartition::Script, true}', header)
            self.assertIn('{"light", EntPartition::Env, false}', header)


if __name__ == "__main__":
    unittest.main()
