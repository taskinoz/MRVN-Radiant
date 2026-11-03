"""Structural tests for the experimental Apex collision writer.

These checks do not certify the native engine's interpretation of triangle leaves.
"""
import struct
import unittest

from inspect_bsp import FormatError
from port_tf2_to_apex import collision_bvh, mesh_bounds


class CollisionWriterTests(unittest.TestCase):
    def test_baked_mesh_visibility_sphere_encloses_geometry(self):
        # A camera can be inside a dome while its centre lies outside the
        # frustum. A zero sphere radius incorrectly discards the entire mesh.
        points=[(-1024.,0.,0.),(1024.,0.,0.),(0.,-1024.,960.),(0.,1024.,960.)]
        b=mesh_bounds(points)
        self.assertGreater(b[3],1024)
        for p in points:
            self.assertLessEqual(sum((p[a]-b[a])**2 for a in range(3)),b[3]**2+1e-6)
            for a in range(3):self.assertLessEqual(abs(p[a]-b[a]),b[4+a])

    def test_mixed_contents_geometry_and_hierarchy(self):
        source = [(128 if i % 2 else 16384,
                   ((i * 10., 0., 0.), (i * 10. + 3., 0., 0.), (i * 10., 4., 0.)))
                  for i in range(401)]
        positions, nodes, leaves, contents = collision_bvh(source)
        xyz = list(struct.iter_unpack('<3f', positions))
        records = list(struct.iter_unpack('<24h4I', nodes))
        palette = [r[0] for r in struct.iter_unpack('<I', contents)]
        recovered, visited = [], set()

        def walk(index):
            self.assertLess(index, len(records))
            self.assertNotIn(index, visited)
            visited.add(index)
            row = records[index]
            words = row[24:]
            mask = palette[words[0] & 255]
            types = (words[2] & 15, (words[2] >> 4) & 15,
                     words[3] & 15, (words[3] >> 4) & 15)
            descendants = []
            for child, kind in enumerate(types):
                reference = words[child] >> 8
                if kind == 1:
                    continue
                if kind == 0:
                    triangles = walk(reference)
                else:
                    self.assertEqual(kind, 4)
                    header, triangle = struct.unpack_from('<2I', leaves, reference * 4)
                    self.assertEqual(((header >> 12) & 15) + 1, 1)
                    self.assertEqual(header & 4095, 0)
                    base = (header >> 16) * 1024
                    a = base + (triangle & 2047)
                    b = a + ((triangle >> 11) & 511) + 1
                    c = a + ((triangle >> 20) & 511) + 1
                    self.assertLess(max(a, b, c), len(xyz))
                    triangles = [(mask, (xyz[a], xyz[b], xyz[c]))]
                    recovered.extend(triangles)
                for _, t in triangles:
                    for p in t:
                        for axis in range(3):
                            self.assertLessEqual(row[axis * 8 + child], p[axis])
                            self.assertGreaterEqual(row[axis * 8 + 4 + child], p[axis])
                descendants.extend(triangles)
            for child_mask, _ in descendants:
                self.assertEqual(mask & child_mask, child_mask)
            return descendants

        walk(0)
        self.assertCountEqual(source, recovered)
        self.assertEqual(len(visited), len(records))

    def test_refuses_unrepresentable_bounds(self):
        with self.assertRaisesRegex(FormatError, 'bounds'):
            collision_bvh([(128, ((40000., 0., 0.), (40001., 0., 0.), (40000., 1., 0.)))])

    def test_refuses_empty_collision(self):
        with self.assertRaisesRegex(FormatError, 'No collision'):
            collision_bvh([])


if __name__ == '__main__':
    unittest.main()
