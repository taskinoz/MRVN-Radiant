import tempfile
import unittest
from pathlib import Path

from pack_tf1_shaders import package


class ShaderPackageTests(unittest.TestCase):
    def test_explicit_shader_tree_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            shaders = source / 'shaders/fxc'
            shaders.mkdir(parents=True)
            (shaders / 'water_ps40.vcs').write_bytes(b'original test shader payload')
            manifest = package(source, root / 'output', 'mp_probe')
            self.assertEqual(list(manifest['members']), ['shaders/fxc/water_ps40.vcs'])
            self.assertEqual(len(manifest['archives']), 2)
            with self.assertRaises(FileExistsError):
                package(source, root / 'output', 'mp_probe')

    def test_unrelated_files_and_map_path_injection_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            (source / 'unrelated.txt').write_bytes(b'not a shader')
            for name in ('mp_probe', '../mp_probe', 'mp_a/b'):
                with self.assertRaises(ValueError):
                    package(source, root / 'output', name)
                self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
