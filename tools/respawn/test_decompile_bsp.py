"""Synthetic scene export/rebuild regressions; no installed games required."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from decompile_bsp import (collision_owners, decompile, entity_text, parse_entities,
                           payload, rebuild, safe_path, write_mesh)
from inspect_bsp import FormatError, inspect
from repair_tf1_port import append
from test_lighting import triangle_bsp
from test_validate_records import fixture


def scene_bsp(path):
    triangle_bsp(path)
    data = bytearray(path.read_bytes())
    append(data,0,0,b'{\n"classname" "worldspawn"\n"message" "original"\n}\n\0')
    append(data,43,0,b'world/test\0')
    append(data,44,0,struct.pack('<I',0))
    append(data,123,0,struct.pack('<4I3f',1,1,1,0,0,0,-1))
    path.write_bytes(data)


class DecompileTests(unittest.TestCase):
    def test_missing_level_info_is_rejected_with_format_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'test.bsp'; scene_bsp(source)
            data = bytearray(source.read_bytes()); struct.pack_into('<4I',data,16+123*16,0,0,0,0)
            source.write_bytes(data)
            with self.assertRaisesRegex(FormatError,'LEVEL_INFO'):
                decompile(source,root/'project')

    def test_entity_duplicates_comments_and_windows_paths(self):
        text = '// source\n{ "classname" "info_target" "OnTrigger" "a" "OnTrigger" "b" "model" "models\\test.mdl" }\0'
        entities = parse_entities(text)
        self.assertEqual(entities[0][1:3],[['OnTrigger','a'],['OnTrigger','b']])
        self.assertEqual(parse_entities(entity_text(entities[0])),entities)

    def test_entity_delimiters_inside_quotes_are_values(self):
        self.assertEqual(parse_entities('{ "key" "{ // text }" }'),[[['key','{ // text }']]])

    def test_rejects_truncated_or_nested_entities(self):
        for text in ('{ "key"','{ "key" "value"','{ { } }','"unquoted"','{ "key" "unterminated }'):
            with self.subTest(text=text), self.assertRaises(FormatError):
                parse_entities(text)

    def test_world_and_submodel_collision_are_separate(self):
        r = fixture()
        r[14].append(r[14][0])
        r[86] = [(0,1),(0,0),(1,1)]
        r[87].append((0,1,1<<8))
        ownership = collision_owners(r)
        self.assertEqual(set(ownership[0]),{(0,0)})
        self.assertEqual(set(ownership[1]),{(0,1)})

    def test_multi_primitive_geosets_resolve_their_own_masks(self):
        r = fixture()
        r[87] = [(0,2,0)]
        r[89] = [(0,),((1<<8)|1,)]
        r[91] = [(1,),(65536,)]
        self.assertEqual(collision_owners(r)[0],{(0,0):1,(0,1):65536})

    def test_preservation_rebuild_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'original.bsp'; scene_bsp(source)
            original = source.read_bytes()
            report = decompile(source,root/'project')
            self.assertEqual(report['render_triangles'],1)
            result = rebuild(root/'project',root/'rebuilt')
            self.assertTrue(result['preserved_byte_identical'])
            self.assertEqual(Path(result['bsp']).read_bytes(),original)
            self.assertEqual(source.read_bytes(),original)

    def test_entity_edit_does_not_change_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'original.bsp'; scene_bsp(source)
            decompile(source,root/'project')
            path = root/'project/entities.json'; groups = json.loads(path.read_text())
            groups[0]['entities'][0].append(['message','edited'])
            path.write_text(json.dumps(groups))
            result = rebuild(root/'project',root/'rebuilt'); target = Path(result['bsp'])
            self.assertFalse(result['preserved_byte_identical'])
            self.assertEqual(payload(target,inspect(target),3),payload(source,inspect(source),3))
            self.assertIn(b'edited',payload(target,inspect(target),0))

    def test_default_sidecar_is_preserved_and_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'original.bsp'; scene_bsp(source)
            override = source.with_name(source.name+'.0000.bsp_lump')
            override.write_bytes(b'{"classname" "worldspawn" "message" "override"}\0')
            decompile(source,root/'project')
            groups = json.loads((root/'project/entities.json').read_text())
            self.assertIn(['message','override'],groups[0]['entities'][0])
            result = rebuild(root/'project',root/'rebuilt')
            self.assertEqual((root/'rebuilt'/override.name).read_bytes(),override.read_bytes())
            self.assertTrue(result['preserved_byte_identical'])

    def test_raw_edits_and_overwrites_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'original.bsp'; scene_bsp(source)
            decompile(source,root/'project')
            (root/'project/lumps/0003.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(FormatError,'Raw lump edits'):
                rebuild(root/'project',root/'rebuilt')
            with self.assertRaises(FileExistsError):
                decompile(source,root/'project')

    def test_project_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FormatError,'escapes'):
                safe_path(Path(tmp),'../outside.bsp')

    def test_rsm1_keeps_source_normal_uv_and_colour(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'test.rsm'
            v = [1,2,3,0,0,1,.25,.75,255,128,64,255,8,16]
            write_mesh(target,[{'material':'world/test','vertices':[v,v,v],'indices':[0,1,2]}])
            b = target.read_bytes(); size = struct.unpack_from('<I',b,8)[0]
            self.assertEqual(b[:8],b'RSM1'+struct.pack('<I',1))
            self.assertEqual(struct.unpack_from('<8f4B2f',b,12+size+8),tuple(v))


if __name__ == '__main__':
    unittest.main()
