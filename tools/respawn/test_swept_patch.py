import unittest

from swept_patch_test import scene, cases_for, verify, compare_native


class SweptPatchTests(unittest.TestCase):
    def test_scene_exercises_node_free_and_noded_headers(self):
        patches, triangles = scene()
        self.assertEqual([len(faces) for faces in triangles], [8,8,8,8,8,2])
        cases = cases_for(patches,triangles)
        self.assertEqual(len(cases),156)
        self.assertEqual({case['patch'] for case in cases}, {p['name'] for p in patches})
        self.assertTrue(any(case['fraction'] == 1 for case in cases))
        self.assertTrue(any(case['fraction'] < 1 for case in cases))

    def test_verifier_requires_every_contact_and_completion(self):
        cases = cases_for(*scene())
        for game in ('titanfallonline','titanfall2'):
            lines = []
            for i,case in enumerate(cases):
                prefix = f"[MRVN] {case['kind']} {case['native_index']}" if game == 'titanfallonline' else f'[MRVN.Swept] CASE {i}'
                lines.append(f"{prefix} fraction={case['fraction']} end={case['z']} solid=false")
            done = '[MRVN] DONE' if game == 'titanfallonline' else '[MRVN.Swept] DONE'
            text = '\n'.join([*lines,done])
            self.assertFalse(verify(cases,text,game)['errors'])
            self.assertTrue(verify(cases,'\n'.join(lines),game)['errors'])
            self.assertTrue(verify(cases,'\n'.join([*lines[1:],done]),game)['errors'])
            self.assertTrue(verify(cases,text+'\n'+lines[0],game)['errors'])
            self.assertTrue(verify(cases,text.replace('solid=false','solid=true',1),game)['errors'])
            self.assertTrue(verify(cases,text.replace('fraction=', 'fraction=nan ',1),game)['errors'])
            # Correct end height cannot conceal a contradictory fraction.
            self.assertTrue(verify(cases,text.replace(f"fraction={cases[0]['fraction']}", 'fraction=1',1),game)['errors'])

    def test_native_comparison_rejects_missing_divergent_and_solid_results(self):
        cases = cases_for(*scene())[:1]
        text = f"[MRVN.Swept] CASE 0 fraction={cases[0]['fraction']} end={cases[0]['z']} solid=false\n[MRVN.Swept] DONE"
        reference = text.replace('MRVN.Swept','MRVN.SweptBrush')
        self.assertFalse(compare_native(cases,text,reference,'titanfall2')['errors'])
        for bad in (reference.replace(f"end={cases[0]['z']}",'end=81'), reference.replace(f"fraction={cases[0]['fraction']}",'fraction=0.6'),
                    reference.replace('solid=false','solid=true'), reference.replace('DONE','unfinished'), ''):
            self.assertTrue(compare_native(cases,text,bad,'titanfall2')['errors'])

    def test_two_matching_native_misses_cannot_hide_missing_surfaces(self):
        cases = cases_for(*scene())[:1]
        baseline = '[MRVN.Swept] CASE 0 fraction=1 end=-32 solid=false\n[MRVN.Swept] DONE'
        reference = baseline.replace('MRVN.Swept','MRVN.SweptBrush')
        self.assertTrue(compare_native(cases,baseline,reference,'titanfall2')['errors'])
