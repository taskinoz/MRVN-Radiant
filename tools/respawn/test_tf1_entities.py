"""Original entity syntax and v29 partition fixtures, without game assets."""
from pathlib import Path
import struct
import tempfile
import unittest

from entity_text import parse_entities, parse_partition
from inspect_bsp import FormatError, HEADER_SIZE, inspect
from validate_records import check_tf1_entities


class Tf1EntityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bsp = self.root / 'mp_probe.bsp'
        self.side = self.root / 'mp_probe_spawn.ent'
        self.write_map()
        self.side.write_bytes(b'ENTITIES01\n{ "classname" "info_spawnpoint_human" }\n')

    def write_map(self, declaration=b'01* spawn\0', entities=b'{ "classname" "worldspawn" }\0'):
        header = bytearray(HEADER_SIZE)
        struct.pack_into('<4s3I', header, 0, b'rBSP', 29, 0, 127)
        struct.pack_into('<4I', header, 16, HEADER_SIZE, len(entities), 0, 0)
        struct.pack_into('<4I', header, 16 + 24 * 16, HEADER_SIZE + len(entities), len(declaration), 0, 0)
        self.bsp.write_bytes(header + entities + declaration)

    def check(self):
        return check_tf1_entities(self.bsp, inspect(self.bsp))

    def test_embedded_and_declared_counts(self):
        issues, counts = self.check()
        self.assertEqual(issues, [])
        self.assertEqual(counts, {'embedded': 1, 'spawn': 1})

    def test_missing_empty_and_malformed_partitions(self):
        self.side.unlink()
        self.assertIn('missing', str(self.check()[0]))
        for payload in (b'', b'ENTITIES01', b'ENTITIES02\n{}', b'ENTITIES01\n{ "key" }'):
            self.side.write_bytes(payload)
            self.assertTrue(self.check()[0])

    def test_paths_and_duplicate_partitions_are_rejected(self):
        for declaration in (b'01* ../spawn\0', b'01* spawn spawn\0', b'01* spawn SPAWN\0', b'02* spawn\0', b'01* \xff\0'):
            self.write_map(declaration=declaration)
            self.assertTrue(self.check()[0])

    def test_default_partition_table_override_is_used(self):
        self.bsp.with_name(self.bsp.name + '.0018.bsp_lump').write_bytes(b'01* env\0')
        issues, counts = self.check()
        self.assertIn('mp_probe_env.ent', str(issues))
        self.assertNotIn('spawn', counts)

    def test_embedded_syntax_and_nul_termination(self):
        for text in (b'{ "key" }', b'{ "key" "unfinished }', b'{}\0{}', b'{ {} }'):
            self.write_map(entities=text)
            self.assertTrue(self.check()[0])
        self.assertEqual(parse_entities('{}\0\0\n'), [[]])

    def test_duplicate_outputs_and_paths_survive_parsing(self):
        text = '// comment\n{ "classname" "info_target" "OnTrigger" "one" "OnTrigger" "two" "model" "models\\probe.mdl" }'
        rows = parse_entities(text)
        self.assertEqual(rows[0][1:3], [['OnTrigger', 'one'], ['OnTrigger', 'two']])
        self.assertEqual(rows[0][3][1], 'models\\probe.mdl')
        self.assertEqual(parse_partition(('ENTITIES01\r\n' + text).encode()), rows)


    def test_worldspawn_first_and_classnames(self):
        for text in (b'\0', b'{ "classname" "info_target" }\0',
                     b'{ "classname" "worldspawn" }{ "classname" "worldspawn" }\0',
                     b'{ "classname" "worldspawn" }{ "targetname" "x" }\0',
                     b'{ "classname" "worldspawn" "classname" "func_brush" }\0'):
            self.write_map(entities=text)
            self.assertTrue(self.check()[0], text)

    def test_missing_entity_nul_is_a_warning_and_partition_nul_an_error(self):
        self.write_map(entities=b'{ "classname" "worldspawn" }')
        issues = self.check()[0]
        self.assertEqual([issue['severity'] for issue in issues], ['warning'])
        self.write_map(declaration=b'01* spawn')
        self.assertIn('not NUL-terminated', str(self.check()[0]))
        self.write_map(declaration=b'01*  spawn\0')
        self.assertEqual([issue['severity'] for issue in self.check()[0]], ['warning'])


if __name__ == '__main__':
    unittest.main()
