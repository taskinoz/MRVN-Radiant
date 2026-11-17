"""Original synthetic navigation-CRC fixtures; no native or retail assets."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from inspect_bsp import HEADER_SIZE, FormatError
from tf1_navigation_crc import calculate, graph_copy, navigation_spans, raw_crc


class NavigationCrcTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bsp = self.root / 'mp_crc.bsp'
        self.graph = self.root / 'native.ain'
        self.graph.write_bytes(struct.pack('<4I', 54, 6, 0, 1) + bytes(68) + bytes(8))

    def write_bsp(self, entities=b'{ "classname" "worldspawn" }', declaration=b'', payloads=None):
        # Physical order deliberately differs from directory index order.
        chunks = [(3, b'1234'), (1, b'56789'), (0, entities), (24, declaration)]
        if payloads is not None:
            chunks = payloads + [(0, entities), (24, declaration)]
        header = bytearray(HEADER_SIZE)
        struct.pack_into('<4s3I', header, 0, b'rBSP', 29, 6, 127)
        body = bytearray()
        for index, data in chunks:
            while len(body) % 4:
                body.append(0x7e)
            struct.pack_into('<4I', header, 16 + index * 16, HEADER_SIZE + len(body), len(data), 0, 0)
            body.extend(data)
        self.bsp.write_bytes(header + body)
        return calculate(self.bsp)

    def test_native_raw_crc_known_vector(self):
        self.assertEqual(raw_crc(b'123456789'), 0x340bc6d9)
        self.assertEqual(raw_crc(b'56789', raw_crc(b'1234')), 0x340bc6d9)

    def test_file_order_skips_entities_table_and_padding(self):
        report = self.write_bsp()
        self.assertEqual(report['map_crc'], 0x340bc6d9)
        self.assertEqual(report['entity_crc'], report['map_crc'])
        self.assertEqual(report['navigation_entities'], {})

    def test_raw_navigation_span_and_ignored_suffix_whitespace(self):
        data = b'  {\n"classname" "info_node" "origin" "1 2 3"  \n}  '
        spans = navigation_spans(data)
        self.assertEqual(spans, [('info_node', b'\n"classname" "info_node" "origin" "1 2 3"')])
        report = self.write_bsp(entities=data)
        self.assertEqual(report['entity_crc'], raw_crc(spans[0][1], 0x340bc6d9))

    def test_node_changes_invalidate_but_irrelevant_entity_changes_do_not(self):
        first = self.write_bsp(entities=b'{ "classname" "info_target" "origin" "0 0 0" }')
        second = self.write_bsp(entities=b'{ "classname" "info_target" "origin" "9 9 9" }')
        self.assertEqual(first['entity_crc'], second['entity_crc'])
        a = self.write_bsp(entities=b'{ "classname" "info_node" "origin" "0 0 0" }')
        b = self.write_bsp(entities=b'{ "classname" "info_node" "origin" "9 9 9" }')
        self.assertEqual(a['map_crc'], b['map_crc'])
        self.assertNotEqual(a['entity_crc'], b['entity_crc'])

    def test_selected_classes_and_case_sensitive_class_filter(self):
        for cls in ('info_node', 'info_node_hint', 'info_hint', 'traverse', 'trigger_indoor_area'):
            self.assertEqual(len(navigation_spans(('{ "classname" "' + cls + '" }').encode())), 1)
        for cls in ('Info_node', 'info_hint_extra', 'info_target', 'traverse_extra'):
            self.assertEqual(navigation_spans(('{ "classname" "' + cls + '" }').encode()), [])

    def test_partition_order_and_header(self):
        self.root.joinpath('mp_crc_a.ent').write_bytes(b'ENTITIES01\n{ "classname" "info_node" "origin" "1 0 0" }')
        self.root.joinpath('mp_crc_b.ent').write_bytes(b'ENTITIES01\r\n{ "classname" "info_node" "origin" "2 0 0" }')
        a = self.write_bsp(declaration=b'01* a b\0')
        b = self.write_bsp(declaration=b'01* b a\0')
        self.assertEqual(a['navigation_entities'], {'info_node': 2})
        self.assertNotEqual(a['entity_crc'], b['entity_crc'])
        self.assertEqual(a['map_crc'], b['map_crc'])

    def test_unsafe_missing_and_invalid_partitions(self):
        for declaration in (b'01* ../a', b'01* a a', b'01* a A', b'02* a', b'01* \xff', b'   '):
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                self.write_bsp(declaration=declaration)
        with self.assertRaises(FileNotFoundError):
            self.write_bsp(declaration=b'01* missing')
        self.root.joinpath('mp_crc_a.ent').write_bytes(b'ENTITIES02\n{}')
        with self.assertRaises(ValueError):
            self.write_bsp(declaration=b'01* a')

    def test_ambiguous_escaped_and_oversized_selected_tokens_rejected(self):
        cases = [b'{ "classname" "info_node" "classname" "info_node" }',
                 b'{ "Classname" "info_node" }',
                 b'{ "classname" "info_node" "model" "a\\b" }',
                 b'{ "classname" "info_node" "value" "' + b'x' * 2048 + b'" }']
        for data in cases:
            with self.subTest(data=data[:80]), self.assertRaises(ValueError):
                navigation_spans(data)

    def test_corrupt_directory_wrong_version_and_external_overrides(self):
        self.write_bsp()
        original = self.bsp.read_bytes()
        for offset, value in ((4, 37), (16 + 16, len(original) + 100), (16 + 3 * 16 + 12, 1)):
            data = bytearray(original);struct.pack_into('<I', data, offset, value);self.bsp.write_bytes(data)
            with self.assertRaises(ValueError):
                calculate(self.bsp)
        self.bsp.write_bytes(original)
        self.bsp.with_name(self.bsp.name + '.0001.bsp_lump').write_bytes(b'x')
        with self.assertRaises(ValueError):
            calculate(self.bsp)

    def test_exclusive_graph_copy_preserves_all_other_bytes(self):
        report = self.write_bsp()
        original = self.graph.read_bytes()
        out = self.root / 'new.ain'
        patched = graph_copy(self.bsp, self.graph, out)
        self.assertFalse(patched['graph']['crc_matches'])
        self.assertEqual(self.graph.read_bytes(), original)
        self.assertEqual(out.read_bytes(), original[:8] + struct.pack('<I', report['entity_crc']) + original[12:])
        self.assertTrue(graph_copy(self.bsp, out)['graph']['crc_matches'])
        with self.assertRaises(FileExistsError):
            graph_copy(self.bsp, self.graph, out)
        with self.assertRaises(FileExistsError):
            graph_copy(self.bsp, self.graph, self.graph)

    def test_graph_revision_version_and_node_framing_rejected(self):
        self.write_bsp()
        original = self.graph.read_bytes()
        for offset, value in ((0, 53), (4, 7), (12, 0), (12, 32768)):
            data = bytearray(original);struct.pack_into('<I', data, offset, value);self.graph.write_bytes(data)
            with self.assertRaises(ValueError):
                graph_copy(self.bsp, self.graph)
        self.graph.write_bytes(original[:20])
        with self.assertRaises(ValueError):
            graph_copy(self.bsp, self.graph)

    def test_source_geometry_changes_affect_base_crc(self):
        a = self.write_bsp(payloads=[(3, b'1234'), (1, b'56789')])
        b = self.write_bsp(payloads=[(3, b'0234'), (1, b'56789')])
        self.assertNotEqual(a['map_crc'], b['map_crc'])


if __name__ == '__main__':
    unittest.main()
