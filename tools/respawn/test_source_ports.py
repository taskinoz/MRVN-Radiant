"""Entity conversion checks for the Source 1 converter (no game content needed)."""
import math
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

from build_source_ports import SURF_SCRIPT, choose_spawns, pushes, teleports, load_surf_config, surf_map_export, light_entities, utopia_jail_threshold_repairs


def bsp(entities, models=()):
    return SimpleNamespace(entities=entities, models=list(models) or [(0, 0, 0, 0, 0, 0)])


class SourcePortTests(unittest.TestCase):
    def test_logic_case_picks_random_teleport_destinations(self):
        # surf_utopia's jail: the triggers name a placeholder target, and a logic_case
        # sets the real one with AddOutput, chosen at random.
        ents = [
            {'classname': 'trigger_teleport', 'model': '*1', 'targetname': 'jail_teleport', 'target': 'asd'},
            {'classname': 'trigger_teleport', 'model': '*1', 'target': 'start'},
            {'classname': 'logic_case', 'targetname': 'case',
             'OnCase01': 'jail_teleport,AddOutput,target cell1,0,-1', 'OnCase02': 'jail_teleport\x1bAddOutput\x1btarget cell2\x1b0\x1b-1',
             'OnCase03': 'jail_teleport,AddOutput,target missing,0,-1'},
            {'classname': 'info_teleport_destination', 'targetname': 'cell1', 'origin': '10 0 0', 'angles': '0 90 0'},
            {'classname': 'info_teleport_destination', 'targetname': 'cell2', 'origin': '20 0 0', 'angles': '0 180 0'},
            {'classname': 'info_teleport_destination', 'targetname': 'start', 'origin': '0 0 5'},
        ]
        out = teleports(bsp(ents, [(0,)*6, (-8, -8, -8, 8, 8, 8)]))
        self.assertEqual([(tuple(d), yaw, n) for _, _, d, yaw, n, _ in out],
                         [((10, 0, 0), 90, 2), ((20, 0, 0), 180, 2), ((0, 0, 5), 0, 1)])
        # Alternatives share their trigger box, consecutively.
        self.assertTrue(np.array_equal(out[0][0], out[1][0]))

    def test_push_velocity_follows_source_angles(self):
        ents = [
            {'classname': 'trigger_push', 'model': '*1', 'origin': '0 0 100', 'pushdir': '-90 0 0', 'speed': '1000', 'spawnflags': '4097'},
            {'classname': 'trigger_push', 'model': '*1', 'pushdir': '0 90 0', 'speed': '500', 'spawnflags': '1'},
            {'classname': 'trigger_push', 'model': '*1', 'pushdir': '0 0 0', 'speed': '500', 'spawnflags': '8'},   # physics only
            {'classname': 'trigger_push', 'model': '*1', 'pushdir': '0 0 0', 'speed': '500', 'spawnflags': '1', 'StartDisabled': '1'},
        ]
        out = pushes(bsp(ents, [(0,)*6, (-4, -4, -4, 4, 4, 4)]))
        self.assertEqual(len(out), 2)
        (lo, hi, up, _), (_, _, side, _) = out
        self.assertEqual(tuple(lo), (-4, -4, 96))
        np.testing.assert_allclose(up, (0, 0, 1000), atol=1e-9)   # pitch -90 is straight up
        np.testing.assert_allclose(side, (0, 500, 0), atol=1e-9)

    def test_trigger_brushes_are_world_planes(self):
        # A slab along a 45 degree slope, stored relative to its entity origin as compiled.
        n = (math.sqrt(.5), 0.0, math.sqrt(.5))
        sides = [SimpleNamespace(normal=n, dist=8.0, bevel=False), SimpleNamespace(normal=tuple(-v for v in n), dist=8.0, bevel=False),
                 SimpleNamespace(normal=(0.0, 0.0, 1.0), dist=100.0, bevel=True)]
        fake = bsp([{'classname': 'trigger_teleport', 'model': '*1', 'origin': '0 0 100', 'target': 'd'},
                    {'classname': 'info_teleport_destination', 'targetname': 'd', 'origin': '0 0 0'}],
                   [(0,)*6, (-8, -8, -8, 8, 8, 8)])
        fake.brushes = [SimpleNamespace(sides=sides)]
        fake.model_brushes = lambda model: [0]
        (*_, brushes), = teleports(fake)
        (planes,) = brushes
        self.assertEqual(len(planes), 3)   # swept hulls need the compiled bevel planes
        self.assertAlmostEqual(planes[0][1], 8 + 100*math.sqrt(.5))

    def test_counter_strike_spawns(self):
        ents = [{'classname': 'info_player_terrorist', 'origin': f'{x} 0 0'} for x in range(0, 2000, 400)]
        ents += [{'classname': 'info_player_counterterrorist', 'origin': f'{x} 5000 0'} for x in range(0, 2000, 400)]
        teams = choose_spawns(bsp(ents), (0, 0))
        self.assertTrue(all(p[1] == 0 for p in teams[2]))
        self.assertTrue(all(p[1] == 5000 for p in teams[3]))
        self.assertEqual(len(teams[2]), 4)

    def test_rotated_trigger_planes_and_bounds_match_source_pose(self):
        from build_source_ports import trigger_bounds, trigger_brushes
        from source_engine import Brush, Side
        fake = SimpleNamespace(models=[(0,)*6, (-10,-100,-2,10,100,2)],
                               brushes=[Brush(1,[Side((1,0,0),10,0,-1,False)])], model_brushes=lambda _: [0])
        e = dict(model='*1', origin='1000 2000 3000', angles='0 90 0')
        lo, hi = trigger_bounds(fake,e)
        np.testing.assert_allclose(lo,(900,1990,2998),atol=1e-8)
        np.testing.assert_allclose(hi,(1100,2010,3002),atol=1e-8)
        plane, = trigger_brushes(fake,e)[0]
        np.testing.assert_allclose(plane[0],(0,1,0),atol=1e-8)
        self.assertAlmostEqual(plane[1],2010)
        # A pitched volume also changes its height, which caused early resets.
        e['angles']='30 0 0'
        lo,hi=trigger_bounds(fake,e)
        self.assertGreater(hi[2]-lo[2],4)

    def test_utopia_threshold_preserves_floor_bands(self):
        from source_engine import BSP, Brush, Side
        def block(lo, hi, material):
            sides = []
            for axis in range(3):
                for sign in (-1, 1):
                    n = [0.0]*3; n[axis] = float(sign)
                    sides.append(Side(tuple(n), hi[axis] if sign > 0 else -lo[axis], material, -1, False))
            return Brush(1, sides)
        original = [block((a, -1680, -10256), (b, 1152, -10240), i)
                    for i, (a, b) in enumerate([(-16, 16), (16, 32), (32, 64), (64, 80), (80, 1552)])]
        original.append(block((0, 1152, -10272), (192, 1216, -10256), 5))
        fake = SimpleNamespace(path=Path('surf_utopia_v3.bsp'), brushes=original,
                               entities=[dict(classname='func_door_rotating', targetname='jail_exit_door', origin='0 1184 -10240')],
                               model_brushes=lambda _: list(range(len(original))), brush_bounds=BSP.brush_bounds)
        repairs = utopia_jail_threshold_repairs(fake)
        self.assertEqual([BSP.brush_bounds(b) for b in repairs],
                         [([a, 1152, -10256], [b, 1216, -10240]) for a, b in [(0,16),(16,32),(32,64),(64,80),(80,192)]])
        self.assertEqual([b.sides[0].texinfo for b in repairs], list(range(5)))
        self.assertEqual(BSP.brush_bounds(original[0]), ([-16, -1680, -10256], [16, 1152, -10240]))
        fake.path = Path('other_map.bsp')
        self.assertEqual(utopia_jail_threshold_repairs(fake), [])

    def test_bevel_plane_rejects_premature_contact_above_trigger_tip(self):
        # Two sloping faces alone admit a standing hull eight units above a
        # trigger's upper tip. Source's axial bevel caps that false positive.
        from build_source_ports import trigger_brushes
        from source_engine import Brush, Side
        q = math.sqrt(.5)
        sides = [Side((q,0,q),0,0,-1,False), Side((-q,0,q),0,0,-1,False),
                 Side((0,0,1),0,0,-1,True)]
        fake = SimpleNamespace(brushes=[Brush(1,sides)], model_brushes=lambda _: [0])
        planes, = trigger_brushes(fake, dict(model='*1'))
        c = np.array((0,0,44)) # feet at z=8; center is 36 above feet
        def inside(ps):
            return all(np.dot(n,c)-d <= np.dot(np.abs(n),(16,16,36))+.25 for n,d in ps)
        self.assertTrue(inside(planes[:2]))
        self.assertFalse(inside(planes))

    def test_source_torch_attenuation_is_not_a_broad_fade(self):
        from source_engine import parse_entities
        entries = [dict(classname='light', origin='1 2 3', _light='249 118 62 10000', _quadratic_attn='1'),
                   dict(classname='light', origin='2 3 4', _light='255 255 255 200', _linear_attn='1', _quadratic_attn='0'),
                   dict(classname='light', origin='3 4 5', _light='255 255 255 200', _zero_percent_distance='300')]
        converted = [e for e in parse_entities(light_entities(bsp(entries))) if e['classname'] == 'light']
        self.assertEqual(converted[0]['_source_attenuation'], '0 0 1')
        self.assertEqual(converted[0]['_light'], '249 118 62 10000')
        self.assertEqual(converted[0]['realtime'], '0')
        self.assertEqual(converted[1]['_source_attenuation'], '0 1 0')
        self.assertNotIn('_source_attenuation', converted[2])
        self.assertEqual(converted[2]['_zero_percent_distance'], '300')

    def test_explicit_teleport_repair(self):
        ents = [
            {'classname': 'trigger_teleport', 'model': '*1', 'target': 'broken-instance-target'},
            {'classname': 'info_teleport_destination', 'targetname': 'stage5', 'origin': '10 20 30'},
        ]
        source = bsp(ents, [(0,)*6, (-8, -8, -8, 8, 8, 8)])
        self.assertEqual(teleports(source), [])
        out = teleports(source, {'broken-instance-target': 'stage5'})
        self.assertEqual(len(out), 1)
        self.assertEqual(tuple(out[0][2]), (10, 20, 30))
        with self.assertRaisesRegex(ValueError, 'destination not found'):
            teleports(source, {'broken-instance-target': 'missing'})

    def test_surf_config_validation_and_numeric_script_export(self):
        config = dict(startMins=[-100, -100, -100], startMaxs=[100, 100, 100],
                      startOrigin=[0, 0, 0], startYaw=180,
                      finishZones=[dict(mins=[200, 200, 0], maxs=[300, 300, 100])],
                      checkpointOrigins=[[500, 0, 0]])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'surf.json'
            path.write_text(json.dumps(config))
            checked = load_surf_config(path)
            script = surf_map_export(checked)
            self.assertIn('startMins = < -100, -100, -100 >', script)
            self.assertIn('checkpointOrigins = [ < 500, 0, 0 > ]', script)
            self.assertIn('startYaw = 180.0', script)
            self.assertNotIn('<-100', script)
            for field, bad in [('startOrigin', [500, 0, 0]), ('startMins', [100, 100, 100]),
                               ('startYaw', '0 ); malicious()'), ('startOrigin', [float('nan'), 0, 0]),
                               ('checkpointOrigins', [[500, 0, 0], [500, 0, 0]]),
                               ('finishZones', [])]:
                with self.subTest(field=field, bad=bad):
                    path.write_text(json.dumps({**config, field: bad}))
                    with self.assertRaises(ValueError):
                        load_surf_config(path)

    def test_surf_script_avoids_slot_operator(self):
        # "<-" opens a Squirrel slot, so a vector literal must not start with a minus sign.
        self.assertNotIn('<-1', SURF_SCRIPT.replace('<- Time()', ''))
        self.assertIn('ForceCrouch', SURF_SCRIPT)


if __name__ == '__main__':
    unittest.main()
