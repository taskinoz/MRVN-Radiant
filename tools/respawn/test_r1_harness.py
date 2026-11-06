import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r1_harness


class R1HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'Titanfall'
        self.r1 = self.game / 'r1'
        self.app = self.root / 'R1Delta/app-3.0.4'
        self.maps = self.root / 'build'
        (self.game / 'vpk').mkdir(parents=True)
        self.r1.mkdir(parents=True)
        self.app.mkdir(parents=True)
        (self.app / 'Titanfall.exe').write_bytes(b'')
        (self.r1 / 'GameInfo.txt').write_text('"GameInfo" {}')
        self.maps.mkdir()
        (self.maps / 'mp_test.bsp').write_bytes(b'BSP')
        (self.maps / 'mp_test_spawn.ent').write_text('ENT')
        (self.maps / 'mp_test.bsp.0000.bsp_lump').write_bytes(b'LUMP')
        (self.maps / 'mp_test.map').write_text('SOURCE')
        (self.maps / 'other.bsp').write_bytes(b'OTHER')
        (self.r1 / 'addonlist.txt').write_text('"AddonList"\n{\n"UserMod" "1"\n}\n')

    def prepare(self, maps=True):
        return r1_harness.prepare(self.app, self.game, self.maps if maps else None, 'mp_test',
                                  ['models/containers/barrel.mdl'] if maps else None, run_id='a' * 32)

    def test_staging_copies_only_the_level_and_cleanup_preserves_other_addons(self):
        session = self.prepare()
        addon = Path(session['addon'])
        staged = sorted(p.name for p in (addon / 'maps').iterdir())
        self.assertEqual(staged, ['mp_test.bsp', 'mp_test.bsp.0000.bsp_lump', 'mp_test_spawn.ent'])
        self.assertIn('"addonContent_Map" "1"', (addon / 'addoninfo.txt').read_text())
        hook = (addon / 'scripts/vscripts/test/myscript.nut').read_text()
        self.assertIn('PrecacheModel( "models/containers/barrel.mdl" )', hook)
        self.assertIn('"MRVN.TF1Harness.' + 'a' * 32 + '" "1"', (self.r1 / 'addonlist.txt').read_text())
        r1_harness.cleanup(session)
        self.assertFalse(addon.exists())
        listing = (self.r1 / 'addonlist.txt').read_text()
        self.assertIn('"UserMod" "1"', listing)
        self.assertNotIn('MRVN.TF1Harness', listing)

    def test_drop_model_files_are_staged_from_a_loose_tree(self):
        dump = self.root / 'assets_dump/models/containers'
        dump.mkdir(parents=True)
        for name in ('barrel.mdl', 'barrel.vvd', 'barrel.dx11.vtx', 'barrel.phy', 'barrel.txt', 'barrel_lid.mdl'):
            (dump / name).write_bytes(b'x')
        session = r1_harness.prepare(self.app, self.game, self.maps, 'mp_test', [], run_id='a' * 32,
                                     model_source=self.root / 'assets_dump')
        addon = Path(session['addon'])
        staged = sorted(p.name for p in (addon / 'models/containers').iterdir())
        self.assertEqual(staged, ['barrel.dx11.vtx', 'barrel.mdl', 'barrel.phy', 'barrel.vvd'])
        r1_harness.cleanup(session)
        self.assertFalse(addon.exists())
        with self.assertRaisesRegex(ValueError, 'crate.mdl is not in'):
            r1_harness.prepare(self.app, self.game, self.maps, 'mp_test', ['models/containers/crate.mdl'],
                               run_id='b' * 32, model_source=self.root / 'assets_dump')
        self.assertFalse((self.r1 / 'addons' / ('MRVN.TF1Harness.' + 'b' * 32)).exists())

    def test_cleanup_accepts_the_games_tab_indented_listing(self):
        session = self.prepare()
        name = Path(session['addon']).name
        (self.r1 / 'addonlist.txt').write_text(f'"AddonList"\n{{\n\t"UserMod"\t\t"1"\n\t"{name}"\t\t"1"\n}}\n')
        r1_harness.cleanup(session)
        self.assertEqual((self.r1 / 'addonlist.txt').read_text(), '"AddonList"\n{\n\t"UserMod"\t\t"1"\n}\n')

    def test_existing_precache_hook_is_not_shadowed(self):
        other = self.r1 / 'addons/UserMod/scripts/vscripts/test/myscript.nut'
        other.parent.mkdir(parents=True)
        other.write_text('// user script')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.r1 / 'addons' / ('MRVN.TF1Harness.' + 'a' * 32)).exists())

    def test_retail_map_with_drops_stages_only_the_precache_hook(self):
        session = r1_harness.prepare(self.app, self.game, None, 'mp_test', [], run_id='b' * 32)
        addon = Path(session['addon'])
        self.assertFalse((addon / 'maps').exists())
        self.assertIn(r1_harness.DEFAULT_MODEL, (addon / 'scripts/vscripts/test/myscript.nut').read_text())
        self.assertIn('"addonContent_Map" "0"', (addon / 'addoninfo.txt').read_text())
        r1_harness.cleanup(session)
        self.assertFalse(addon.exists())

    def test_retail_map_stages_nothing(self):
        session = self.prepare(maps=False)
        self.assertIsNone(session['addon'])
        self.assertFalse((self.r1 / 'addons').exists())
        r1_harness.cleanup(session)
        self.assertEqual((self.r1 / 'addonlist.txt').read_text(), '"AddonList"\n{\n"UserMod" "1"\n}\n')

    def test_changed_addon_prevents_cleanup(self):
        session = self.prepare()
        (Path(session['addon']) / 'addoninfo.txt').write_text('user changes')
        with self.assertRaises(ValueError):
            r1_harness.cleanup(session)
        self.assertTrue(Path(session['addon']).exists())

    def test_unsupported_addon_list_is_not_rewritten(self):
        (self.r1 / 'addonlist.txt').write_text('"AddonList" { "Nested" { } }')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.r1 / 'addons').exists())

    def test_check_validation_matches_tfo_schema(self):
        checks = r1_harness.validate_checks({
            'traces': [[0, 0, 10, 0, 0, 0]], 'hulls': [[0, 0, 10, 0, 0, 0, -8, -8, 0, 8, 8, 72]],
            'drops': [[0, 0, 10]], 'drop_models': ['models/containers/barrel.mdl'], 'drop_wait': 2,
            'drop_samples': True, 'expect': {'trace_z': [[0, -1, 1]]}})
        self.assertTrue(checks['drop_samples'])
        for bad in ({'hulls': [[0, 0, 0, 0, 0, 0, 8, 0, 0, -8, 0, 0]]},
                    {'drops': [[0, 0, 0]], 'drop_models': ['../x.mdl']},
                    {'drop_wait': 0}, {'traces': [[0, 0, float('nan'), 0, 0, 0]]},
                    {'expect': {'trace_z': [[0, 2, 1]]}}):
            with self.assertRaises(ValueError):
                r1_harness.validate_checks(bad)

    def test_trace_script_matches_tfo_event_format(self):
        script = r1_harness.trace_script([[1, 2, 3, 4, 5, 6, -1, -1, -1, 1, 1, 1]], 7, True)
        self.assertIn('TraceHull( Vector( 1.0000, 2.0000, 3.0000 )', script)
        self.assertIn('"[MRVN] HULL 7 fraction=" + r.fraction + " end=" + r.endPos.z', script)
        self.assertIn('TRACE_COLLISION_GROUP_NONE );', script)


if __name__ == '__main__':
    unittest.main()
