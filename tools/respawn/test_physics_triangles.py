"""PHYSICS_TRIANGLES layout and hull generator tests, without proprietary assets."""
import math
import struct
import unittest

import physics_triangles as pt

# A retail-shaped blob (layout as Colony header 30): one hull, a flat quad
# as a double-sided 4-face, 6-edge sliver.
RETAIL_QUAD = bytes.fromhex("01000000 04 04 06 04 00"
                            "00010203 04050202 00050301 01030400"
                            "0001 0103 0300 0201 0302 0200".replace(" ", ""))
CUBE = [(x, y, z) for x in (0.0, 64.0) for y in (0.0, 64.0) for z in (0.0, 64.0)]
CUBE_TRIS = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]


def outward(vertices, tris):
    cx = [sum(v[k] for v in vertices) / len(vertices) for k in range(3)]
    for a, b, c in tris:
        n = pt._cross(pt._sub(vertices[b], vertices[a]), pt._sub(vertices[c], vertices[a]))
        centre = [(vertices[a][k] + vertices[b][k] + vertices[c][k]) / 3 - cx[k] for k in range(3)]
        if pt._dot(n, centre) <= 0:
            return False
    return True


class LayoutTests(unittest.TestCase):
    def test_retail_quad_parses_and_unpacks_like_the_engine(self):
        parsed = pt.parse_blob(RETAIL_QUAD)
        hull = parsed["hulls"][0]
        self.assertEqual((len(hull["faces"]), hull["virtual_faces"], len(hull["edges"]),
                          hull["virtual_edges"], hull["base"]), (4, 4, 6, 4, 0))
        self.assertEqual(pt.hull_triangles(hull), [(0, 1, 3), (3, 2, 0), (1, 0, 2), (3, 1, 2)])
        self.assertEqual(pt.check_blob(RETAIL_QUAD, 4), [])
        self.assertEqual(pt.pack_blob(parsed["hulls"]), RETAIL_QUAD)

    def test_lump_table_and_null_sizes(self):
        lump = pt.build_lump([RETAIL_QUAD, None, RETAIL_QUAD])
        count, *sizes = struct.unpack_from("<4H", lump)
        self.assertEqual((count, sizes), (3, [len(RETAIL_QUAD), 0xffff, len(RETAIL_QUAD)]))
        self.assertEqual(pt.split_lump(lump), [RETAIL_QUAD, None, RETAIL_QUAD])
        # The engine also treats size 0 as null (but 0xfffe as a real size).
        self.assertEqual(pt.split_lump(struct.pack("<HH", 1, 0)), [None])
        self.assertEqual(pt.split_lump(b""), [])
        with self.assertRaises(pt.FormatError):
            pt.split_lump(lump + b"\0")

    def test_validator_rejects_broken_hulls(self):
        bad = bytearray(RETAIL_QUAD)
        bad[9] = 5  # face 0 now uses edge 5 three times
        self.assertTrue(pt.check_blob(bytes(bad)))
        self.assertTrue(pt.check_blob(RETAIL_QUAD, 3))  # vertex 3 outside a 3-vertex header
        self.assertTrue(pt.check_blob(RETAIL_QUAD[:-1]))


class GeneratorTests(unittest.TestCase):
    def test_cube_hull(self):
        hull = pt.build_hull(CUBE, CUBE_TRIS)
        self.assertEqual((len(hull["faces"]), len(hull["edges"]), hull["base"]), (12, 18, 0))
        blob = pt.pack_blob([hull])
        self.assertEqual(pt.check_blob(blob, len(CUBE)), [])
        tris = pt.hull_triangles(pt.parse_blob(blob)["hulls"][0])
        self.assertTrue(outward(CUBE, tris))
        self.assertEqual(len(blob), 9 + 4 * 12 + 2 * 18)
        # Pierce points at a face with the opposite normal.
        for f, face in enumerate(hull["faces"]):
            a, b, c = tris[f]
            n = pt._cross(pt._sub(CUBE[b], CUBE[a]), pt._sub(CUBE[c], CUBE[a]))
            a, b, c = tris[face[3]]
            m = pt._cross(pt._sub(CUBE[b], CUBE[a]), pt._sub(CUBE[c], CUBE[a]))
            self.assertLess(pt._dot(pt._unit(n), pt._unit(m)), -0.999)

    def test_interior_duplicate_and_coplanar_points_are_not_vertices(self):
        vertices = CUBE + [(32.0, 32.0, 32.0), (32.0, 0.0, 32.0), (0.0, 0.0, 0.0)]
        tris = CUBE_TRIS + [(8, 9, 10)]
        hull = pt.build_hull(vertices, tris)
        used = {v + hull["base"] for e in hull["edges"] for v in e}
        self.assertEqual(used, set(range(8)))  # duplicate 10 maps to vertex 0

    def test_flat_polygon_is_double_sided(self):
        hexagon = [(64 * math.cos(k * math.pi / 3), 64 * math.sin(k * math.pi / 3), 16.0) for k in range(6)]
        hull = pt.build_hull(hexagon, [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 5)])
        self.assertTrue(hull["flat"])
        self.assertEqual((len(hull["faces"]), len(hull["edges"])), (8, 12))
        self.assertEqual(pt.check_blob(pt.pack_blob([hull]), 6), [])
        triangle = pt.build_hull([(0, 0, 0), (64, 0, 0), (0, 64, 0)], [(0, 1, 2)])
        self.assertEqual(len(triangle["faces"]), 2)  # retail also has 2-face hulls

    def test_degenerate_and_base_vertex(self):
        self.assertIsNone(pt.build_hull([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2)]))
        shifted = [(999.0, 999.0, 999.0)] * 300 + CUBE
        hull = pt.build_hull(shifted, [tuple(v + 300 for v in t) for t in CUBE_TRIS])
        self.assertEqual(hull["base"], 255)
        self.assertEqual(max(v for e in hull["edges"] for v in e), 307 - 255)

    def test_build_writes_hulls_only_for_solid_window_grate(self):
        lump = pt.build([(CUBE, CUBE_TRIS, 0x1), (CUBE, CUBE_TRIS, 0x10000), (CUBE, CUBE_TRIS, 0x8)])
        blobs = pt.split_lump(lump)
        self.assertEqual([b is not None for b in blobs], [True, False, True])

    def test_too_wide_vertex_range_splits_into_two_hulls(self):
        far = [(999.0, 999.0, 999.0)] * 300
        vertices = CUBE + far + [(x + 512, y, z) for x, y, z in CUBE]
        tris = CUBE_TRIS + [tuple(v + 308 for v in t) for t in CUBE_TRIS]
        blob = pt.build_blob(vertices, tris)
        hulls = pt.parse_blob(blob)["hulls"]
        self.assertEqual(len(hulls), 2)
        self.assertEqual(pt.check_blob(blob, len(vertices)), [])
        self.assertEqual(hulls[1]["base"], 255)


if __name__ == "__main__":
    unittest.main()
