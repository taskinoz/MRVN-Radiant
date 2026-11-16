"""Original synthetic material dependencies; no retail assets required."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_tf1_water import audit, parse_water, resource_name


class WaterDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'assets'
        self.shaders = self.root / 'caches'
        self.write(self.source, 'materials/test/top.vmt', b'''Water {
            $normalmap "test/normal"
            $bottommaterial "test/bottom"
            $envmap "test/sky"
            $refracttexture "_rt_WaterRefraction"
            $forceenvmap 1
            $lightmap 1
            // $basetexture "test/absent_comment"
            /* $flowmap "test/absent_block_comment" */
            $foghalfdists "[ 70 80 80 ]"
        }''')
        self.write(self.source, 'materials/test/bottom.vmt', b'''Water {
            $normalmap "test/normal"
            Proxies { TextureScroll { texturescrollvar "$bumptransform" } }
        }''')
        self.write(self.source, 'materials/test/normal.vtf', b'VTF\0original test bytes')
        self.write(self.source, 'materials/test/sky.hdr.vtf', b'VTF\0original HDR test bytes')
        for name in ('water_ps40.vcs', 'water_vs40.vcs'):
            self.write(self.shaders, 'shaders/fxc/' + name, b'original synthetic cache')

    def write(self, root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def run_audit(self):
        return audit(self.source, self.shaders, ['test/top'])

    def test_bottom_material_hdr_cubemap_runtime_target_and_hashes(self):
        report = self.run_audit()
        self.assertEqual(report['issues'], [])
        self.assertEqual(report['materials'], ['test/bottom', 'test/top'])
        self.assertEqual(len(report['files']), 6)
        self.assertIn('materials/test/sky.hdr.vtf', report['files'])
        self.assertEqual(len(report['runtime_resources']), 1)
        self.assertTrue(all(len(item['sha256']) == 64 for item in report['files'].values()))

    def test_missing_texture_bottom_and_shader_are_failures(self):
        for root, relative in ((self.source, 'materials/test/normal.vtf'),
                               (self.source, 'materials/test/bottom.vmt'),
                               (self.shaders, 'shaders/fxc/water_ps40.vcs')):
            with self.subTest(relative=relative):
                path = root / relative
                before = path.read_bytes()
                path.unlink()
                self.assertIn('missing ', str(self.run_audit()['issues']))
                path.write_bytes(before)

    def test_invalid_header_and_empty_cache_fail(self):
        self.write(self.source, 'materials/test/normal.vtf', b'bad texture')
        self.write(self.shaders, 'shaders/fxc/water_vs40.vcs', b'')
        issues = str(self.run_audit()['issues'])
        self.assertIn('invalid VTF header', issues)
        self.assertIn('empty or oversized shader cache', issues)

    def test_path_escape_and_linked_resources_fail(self):
        for name in ('../outside', '/absolute', 'C:/absolute', 'test//normal', 'test/./normal'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                resource_name(name)
        with patch('audit_tf1_water.linked', side_effect=lambda p: p.name == 'normal.vtf'):
            self.assertIn('linked resource', str(self.run_audit()['issues']))
        self.write(self.source, 'materials/test/top.vmt', b'Water { $normalmap "../outside" }')
        self.assertIn('unsupported resource path', str(self.run_audit()['issues']))

    def test_unsupported_syntax_and_shader_fail_explicitly(self):
        for text in ('Patch { include "test/base" }', 'Water { $a 1 [PC] }',
                     'Water { $a "unfinished }', 'Water { $a 1', 'Water { include "file" }', 'Water { #include "file" }'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_water(text)

    def test_unknown_texture_and_nested_dependency_blocks_fail(self):
        self.write(self.source, 'materials/test/top.vmt',
                   b'Water { $unknowntexture "test/missing" DX90 { $normalmap "test/other" } }')
        issues = str(self.run_audit()['issues'])
        self.assertIn('unknown dependency parameter', issues)
        self.assertIn('unsupported dependency/block', issues)

    def test_unknown_proxy_cannot_hide_a_texture_dependency(self):
        self.write(self.source, 'materials/test/top.vmt',
                   b'Water { Proxies { TextureReplace { filename "test/missing" } } }')
        self.assertIn('unsupported proxy', str(self.run_audit()['issues']))

    def test_repeated_dependencies_and_cycles_terminate(self):
        self.write(self.source, 'materials/test/bottom.vmt', b'Water { $bottommaterial "test/top" }')
        report = audit(self.source, self.shaders, ['test/top', 'test/top.vmt'])
        self.assertEqual(report['issues'], [])
        self.assertEqual(report['materials'], ['test/bottom', 'test/top'])


if __name__ == '__main__':
    unittest.main()
