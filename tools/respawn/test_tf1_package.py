"""Original synthetic TF1 packaging fixtures; no native or retail assets."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from inspect_bsp import HEADER_SIZE
from build_tf1_package import package, prop_models, texture_names
from inspect_bsp import inspect

PASS = lambda bsp: {'issues': []}


def game_lump(base, models):
    names = b''.join(m.encode().ljust(128, b'\0') for m in models)
    sprp = struct.pack('<I', len(models)) + names
    directory = struct.pack('<I', 1) + struct.pack('<4sIII', b'prps', 786432, base + 20, len(sprp))
    return directory + sprp


def write_bsp(path, textures=(b'world/a', b'world/b'), models=('models/x/prop.mdl',), version=29):
    strings = b'\0'.join(textures) + b'\0'
    header = bytearray(HEADER_SIZE)
    struct.pack_into('<4s3I', header, 0, b'rBSP', version, 6, 127)
    body = bytearray()
    def add(index, data):
        while len(body) % 4:
            body.append(0)
        struct.pack_into('<4I', header, 16 + index * 16, HEADER_SIZE + len(body), len(data), 0, 0)
        body.extend(data)
    add(43, strings)
    while len(body) % 4:
        body.append(0)
    add(35, game_lump(HEADER_SIZE + len(body), list(models)))
    path.write_bytes(header + body)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.maps = self.root / 'maps'
        self.maps.mkdir()
        write_bsp(self.maps / 'mp_test.bsp')
        (self.maps / 'mp_test_spawn.ent').write_text('ENTITIES01\n')
        (self.maps / 'mp_test.bsp.0018.bsp_lump').write_bytes(b'x')
        (self.maps / 'mp_other.bsp').write_bytes(b'not ours')
        (self.maps / 'mp_test.log').write_text('build log')

    def build(self, **kwargs):
        kwargs.setdefault('validator', PASS)
        return package(self.maps, 'mp_test', 'Author.Test', '1.2.3', self.root / 'out', **kwargs)

    def test_readers(self):
        bsp = self.maps / 'mp_test.bsp'
        inv = inspect(bsp)
        self.assertEqual(texture_names(bsp, inv), ['world/a', 'world/b'])
        self.assertEqual(prop_models(bsp, inv), ['models/x/prop.mdl'])

    def test_layouts_manifest_and_zips(self):
        manifest = self.build()
        out = self.root / 'out'
        for level in (out / 'tfo/Author.Test/mod/maps', out / 'r1delta/Author.Test/maps'):
            self.assertEqual(sorted(p.name for p in level.iterdir()),
                             ['mp_test.bsp', 'mp_test.bsp.0018.bsp_lump', 'mp_test_spawn.ent'])
        mod = json.loads((out / 'tfo/Author.Test/mod.json').read_text())
        self.assertEqual((mod['Name'], mod['Version'], mod['RequiredOnClient']), ('Author.Test', '1.2.3', True))
        self.assertEqual(manifest['unverified'], ['models/x/prop.mdl', 'world/a', 'world/b'])
        self.assertEqual(manifest['missing'], [])
        self.assertIn('r1delta/Author.Test/maps/mp_test.bsp', manifest['files'])
        with zipfile.ZipFile(out / 'Author.Test-1.2.3-tfo.zip') as z:
            self.assertIn('Author.Test/mod/maps/mp_test.bsp', z.namelist())
        self.assertIn('addonlist.txt', (out / 'INSTALL.md').read_text())

    def test_assets_graph_and_strict(self):
        assets = self.root / 'assets'
        (assets / 'materials/world').mkdir(parents=True)
        (assets / 'materials/world/a.vmt').write_text('"LightmappedGeneric" {}')
        (assets / 'materials/world/b.vmt').write_text('"LightmappedGeneric" {}')
        (assets / 'models/x').mkdir(parents=True)
        (assets / 'models/x/prop.mdl').write_bytes(b'IDST')
        (self.maps / 'graphs').mkdir()
        (self.maps / 'graphs/mp_test.ain').write_bytes(b'graph')
        manifest = self.build(assets=assets, strict=True)
        out = self.root / 'out'
        self.assertEqual(manifest['missing'] + manifest['unverified'], [])
        self.assertTrue(manifest['navigation_graph'])
        self.assertTrue((out / 'r1delta/Author.Test/models/x/prop.mdl').is_file())
        self.assertTrue((out / 'tfo/Author.Test/mod/materials/world/a.vmt').is_file())
        self.assertTrue((out / 'tfo/Author.Test/mod/maps/graphs/mp_test.ain').is_file())

    def test_base_vpk_and_asset_source(self):
        from pack_vpk import pack_files
        vpk = self.root / 'vpk'
        pack_files({'materials/world/a.vmt': b'"LightmappedGeneric" {}'}, vpk, 'client_mp_common.bsp.pak000')
        source = self.root / 'dump/materials/world'
        source.mkdir(parents=True)
        (source / 'b.vmt').write_text('"LightmappedGeneric"\n{\n"$basetexture" "world\\b_col"\n}\n')
        (source / 'b_col.vtf').write_bytes(b'VTF\0')
        manifest = self.build(base_vpk=vpk, asset_source=self.root / 'dump')
        deps = manifest['dependencies']
        self.assertEqual(deps['materials'], {'world/a': 'base game', 'world/b': 'shipped'})
        self.assertEqual(manifest['missing'], ['models/x/prop.mdl'])
        self.assertEqual(manifest['collected_from_asset_source'],
                         ['materials/world/b.vmt', 'materials/world/b_col.vtf'])
        self.assertTrue((self.root / 'out/r1delta/Author.Test/materials/world/b_col.vtf').is_file())

    def test_shader_vpk_naming_from_pack_tf1_shaders(self):
        from pack_vpk import pack_files
        folder = self.root / 'shader-vpk'
        pack_files({'shaders/fxc/water_ps40.vcs': b'VCS\0'}, folder,
                   'client_mp_test.bsp.pak000')
        manifest = self.build(shader_vpk=folder)
        expected = {
            'vpk/client_mp_test.bsp.pak000_000.vpk',
            'vpk/englishclient_mp_test.bsp.pak000_dir.vpk',
        }
        self.assertEqual({p for p in manifest['files'] if p.startswith('vpk/')}, expected)

    def test_rejections(self):
        with self.assertRaisesRegex(ValueError, 'strict'):
            self.build(strict=True)
        with self.assertRaisesRegex(ValueError, 'record validation'):
            self.build(validator=lambda bsp: {'issues': [{'message': 'bad'}]})
        with self.assertRaisesRegex(ValueError, 'x.y.z'):
            package(self.maps, 'mp_test', 'Author.Test', 'one', self.root / 'o2', validator=PASS)
        bad = self.root / 'bad'
        (bad / 'docs').mkdir(parents=True)
        (bad / 'docs/readme.txt').write_text('x')
        with self.assertRaisesRegex(ValueError, 'asset outside'):
            self.build(assets=bad)
        vpk = self.root / 'vpk'
        vpk.mkdir()
        (vpk / 'client_mp_test.bsp.pak000_000.vpk').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, '_dir.vpk'):
            self.build(shader_vpk=vpk)
        other = self.root / 'bad-shader-vpk'
        other.mkdir()
        (other / 'englishclient_mp_other.bsp.pak000_dir.vpk').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'expected only'):
            self.build(shader_vpk=other)
        write_bsp(self.maps / 'mp_test.bsp', version=37)
        with self.assertRaisesRegex(ValueError, 'v29'):
            self.build()
        self.assertFalse((self.root / 'out').exists())

    def test_existing_output_is_not_overwritten(self):
        (self.root / 'out').mkdir()
        with self.assertRaises(FileExistsError):
            self.build()


if __name__ == '__main__':
    unittest.main()
