"""Entity conversion checks for the Source 1 converter (no game content needed)."""
import math
import unittest
from types import SimpleNamespace

import numpy as np

from build_source_ports import SURF_SCRIPT, choose_spawns, pushes, teleports


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
        self.assertEqual([(tuple(d), yaw, n) for _, _, d, yaw, n in out],
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
        (lo, hi, up), (_, _, side) = out
        self.assertEqual(tuple(lo), (-4, -4, 96))
        np.testing.assert_allclose(up, (0, 0, 1000), atol=1e-9)   # pitch -90 is straight up
        np.testing.assert_allclose(side, (0, 500, 0), atol=1e-9)

    def test_counter_strike_spawns(self):
        ents = [{'classname': 'info_player_terrorist', 'origin': f'{x} 0 0'} for x in range(0, 2000, 400)]
        ents += [{'classname': 'info_player_counterterrorist', 'origin': f'{x} 5000 0'} for x in range(0, 2000, 400)]
        teams = choose_spawns(bsp(ents), (0, 0))
        self.assertTrue(all(p[1] == 0 for p in teams[2]))
        self.assertTrue(all(p[1] == 5000 for p in teams[3]))
        self.assertEqual(len(teams[2]), 4)

    def test_surf_script_avoids_slot_operator(self):
        # "<-" opens a Squirrel slot, so a vector literal must not start with a minus sign.
        self.assertNotIn('<-1', SURF_SCRIPT.replace('<- Time()', ''))
        self.assertIn('ForceCrouch', SURF_SCRIPT)


if __name__ == '__main__':
    unittest.main()
