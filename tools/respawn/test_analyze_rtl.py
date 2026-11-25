"""Unit tests for the RTL analysis helpers (synthetic data, no retail maps)."""
import struct
import unittest

import numpy as np

from analyze_rtl import Occluders, hardware_indices, light_reach, world_lights


def light_record(type_, flags, origin=(0, 0, 0), normal=(0, 0, -1), radius=100.0,
                 stopdot=0.9, stopdot2=0.5, tail=None):
    values = (*origin, 1, 1, 1, *normal, 0, 0, 0, 0, type_, 0, stopdot, stopdot2, 1.0,
              radius, 1.0, -0.01, 0.0, flags, 0, 0)
    data = struct.pack("<12f3i7f3i", *values)
    return data + (struct.pack("<3f", *tail) if tail is not None else b"")


class WorldLightTests(unittest.TestCase):
    def test_v29_and_v37_records_and_hardware_indices(self):
        v29 = light_record(5, 0) + light_record(3, 0) + light_record(1, 30)
        lights = world_lights(v29, 29)
        self.assertEqual([l["type"] for l in lights], [5, 3, 1])
        self.assertEqual(lights[2]["flags"], 30)
        # Ambients are not counted: TF1 RTL byte b names WORLD_LIGHTS[b + 1].
        self.assertEqual(hardware_indices(lights), {1: 0, 2: 1})
        v37 = light_record(2, 56, tail=(60.0, 0.0, 0.25))
        light = world_lights(v37, 37)[0]
        self.assertEqual(light["tail"], (60.0, 0.0, 0.25))  # _emitter_radius, 0, _specular_intensity
        with self.assertRaises(ValueError):
            world_lights(v37, 29)


class ReachTests(unittest.TestCase):
    def test_radius_facing_and_cone(self):
        spot = world_lights(light_record(2, 14, origin=(0, 0, 50), radius=100, stopdot=0.95, stopdot2=0.8), 29)[0]
        pos = np.array([[0, 0, 0], [0, 0, 0], [200, 0, 0], [80, 0, 0]], float)
        normal = np.array([[0, 0, 1], [0, 0, -1], [0, 0, 1], [0, 0, 1]], float)
        reach, ratio = light_reach(spot, pos, normal)
        # In front and in cone; facing away; out of radius; outside the outer cone.
        self.assertEqual(reach.tolist(), [True, False, False, False])
        self.assertAlmostEqual(ratio[0], 0.5)


class OccluderTests(unittest.TestCase):
    def test_wall_blocks_segment(self):
        wall = np.array([[[50, -100, -100], [50, 100, -100], [50, 0, 100]]], float)
        occ = Occluders(wall, cell=32.0)
        self.assertTrue(occ.blocked(np.array([0.0, 0, 0]), np.array([100.0, 0, 0])))
        self.assertFalse(occ.blocked(np.array([0.0, 0, 0]), np.array([0.0, 100, 0])))
        hits = occ.hits(np.array([0.0, 0, 0]), np.array([100.0, 0, 0]))
        self.assertAlmostEqual(float(hits[0]), 0.5)


if __name__ == "__main__":
    unittest.main()
