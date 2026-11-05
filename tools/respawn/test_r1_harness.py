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
        (self.r1 / 'cfg').mkdir(parents=True)
        self.app.mkdir(parents=True)
        (self.app / 'Titanfall.exe').write_bytes(b'')
        (self.r1 / 'GameInfo.txt').write_text('"GameInfo" {}')
        self.maps.mkdir()
        (self.maps / 'mp_test.bsp').write_bytes(b'BSP')
        (self.maps / 'mp_test.ent').write_text('ENT')
        (self.maps / 'mp_test.map').write_text('SOURCE')
        (self.r1 / 'addonlist.txt').write_text('"AddonList"\n{\n"UserMod" "1"\n}\n')

    def prepare(self):
        return r1_harness.prepare(self.app, self.game, self.maps, 'mp_test',
                                  {'traces': [[0, 0, 10, 0, 0, 0]], 'drops': [[0, 0, 10]]},
                                  run_id='a' * 32)

    def test_staging_and_cleanup_preserves_other_addons(self):
        session = self.prepare()
        addon = Path(session['addon'])
        self.assertTrue((addon / 'maps/mp_test.bsp').exists())
        self.assertTrue((addon / 'maps/mp_test.ent').exists())
        self.assertFalse((addon / 'maps/mp_test.map').exists())
        self.assertIn('"addonContent_Map" "1"', (addon / 'addoninfo.txt').read_text())
        cfg = Path(session['cfg']).read_text()
        self.assertIn('script IncludeFile("mrvn_harness_' + 'a' * 32 + '")', cfg)
        self.assertIn('"MRVN.TF1Harness.' + 'a' * 32 + '" "1"', (self.r1 / 'addonlist.txt').read_text())
        script = next((addon / 'scripts/vscripts').glob('*.nut')).read_text()
        self.assertIn('[MRVN:' + 'a' * 32 + ']', script)
        self.assertIn('WaittillGameStateOrHigher', script)
        self.assertIn('ServerCommand( "condump" )', script)

        r1_harness.cleanup(session)
        self.assertFalse(addon.exists())
        self.assertFalse(Path(session['cfg']).exists())
        listing = (self.r1 / 'addonlist.txt').read_text()
        self.assertIn('"UserMod" "1"', listing)
        self.assertNotIn('MRVN.TF1Harness', listing)

    def test_foreign_cfg_prevents_cleanup(self):
        session = self.prepare()
        Path(session['cfg']).write_text('user changes')
        with self.assertRaisesRegex(ValueError, 'changed'):
            r1_harness.cleanup(session)
        self.assertTrue(Path(session['addon']).exists())

    def test_cleanup_requires_owned_addon_entry(self):
        session = self.prepare()
        listing = self.r1 / 'addonlist.txt'
        listing.write_text('"AddonList"\n{\n"UserMod" "1"\n}\n')
        with self.assertRaisesRegex(ValueError, 'entry'):
            r1_harness.cleanup(session)
        self.assertTrue(Path(session['addon']).exists())

    def test_collect_reports_pass_and_failure(self):
        session = self.prepare()
        events = ['BEGIN', 'TRACE 0 fraction=1 end=0 solid=false', 'DROP 0 z=8', 'DONE']
        text = '\n'.join('[MRVN:' + 'a' * 32 + '] ' + event for event in events)
        result = r1_harness.collect(session, text)
        self.assertTrue(result['server_passed'])
        self.assertTrue(result['finished'])
        self.assertEqual(result['events'], events)
        bad = r1_harness.collect(session, text.replace('DONE', 'OTHER'))
        self.assertFalse(bad['server_passed'])
        self.assertIn('run did not finish', bad['issues'])
        self.assertFalse(r1_harness.collect(session, text + '\nSCRIPT ERROR')['server_passed'])
        self.assertFalse(r1_harness.collect(session, text.replace('DROP 0 z=8', ''))['server_passed'])

    def test_accepts_nested_map_directory(self):
        nested = self.maps / 'maps'
        nested.mkdir()
        (self.maps / 'mp_test.bsp').replace(nested / 'mp_test.bsp')
        session = self.prepare()
        self.assertTrue((Path(session['addon']) / 'maps/mp_test.bsp').exists())
        r1_harness.cleanup(session)

    def test_rejects_unsafe_listing_and_missing_map(self):
        (self.r1 / 'addonlist.txt').write_text('"AddonList"\n{\n"UserMod" "1"\n}\nextra\n')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            self.prepare()
        (self.r1 / 'addonlist.txt').write_text('"AddonList"\n{\n}\n')
        with self.assertRaisesRegex(ValueError, 'missing compiled map'):
            r1_harness.prepare(self.app, self.game, self.maps, 'mp_missing', {})


if __name__ == '__main__':
    unittest.main()
