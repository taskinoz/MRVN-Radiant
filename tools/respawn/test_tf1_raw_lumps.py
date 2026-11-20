"""Original synthetic v29 raw-lump framing and texture name tests."""
import struct
import unittest

from validate_records import check_tf1_physics, check_tf1_texture_strings

TERMINAL = struct.pack('<4i', -1, -1, 0, 0)
TETRA = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3))


def solid(client=0, triangles=TETRA, points=((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)), root=None):
    """One synthetic VPHY compact surface holding a single ledge."""
    at = {(t[k], t[(k + 1) % 3]): 4 * i + 1 + k for i, t in enumerate(triangles) for k in range(3)}
    words = []
    for i, t in enumerate(triangles):
        words.append(i)
        for k in range(3):
            here = 4 * i + 1 + k
            twin = at.get((t[(k + 1) % 3], t[k]), here + 64)
            words.append(t[k] | ((twin - here) & 0x7fff) << 16)
    ledge_size = 16 + 16 * len(triangles) + 16 * len(points)
    ledge = struct.pack('<iIIhh', 16 + 16 * len(triangles), client, 4 | (ledge_size // 16) << 8, len(triangles), 0)
    ledge += struct.pack(f'<{len(words)}I', *words)
    ledge += b''.join(struct.pack('<4f', *p, 0) for p in points)
    node = struct.pack('<2i4f3Bx', 0, -ledge_size, 0, 0, 0, 1, 250, 250, 250)
    size = 48 + ledge_size + len(node)
    surface = struct.pack('<7fIi2i', 0, 0, 0, 1, 1, 1, 1, 0xe3 | size << 8,
                          48 + ledge_size if root is None else root, 0, 0) + b'IVPS'
    return b'VPHY' + struct.pack('<hhi3fi', 0x100, 0, size, 1, 1, 1, 0) + surface + ledge + node


def model(index=0, solid=solid(), keys=b'solid { }\0'):
    body = struct.pack('<i', len(solid)) + solid
    return struct.pack('<4i', index, len(body), len(keys), 1) + body + keys


class Tf1RawLumpTests(unittest.TestCase):
    def test_multiple_models_and_empty_physics(self):
        self.assertEqual(check_tf1_physics(model() + model(1) + TERMINAL, 2), [])
        self.assertEqual(check_tf1_physics(b'', 0), [])

    def test_missing_truncated_or_invalid_terminal(self):
        for data in (model(), b'abc', model() + TERMINAL + b'x',
                     struct.pack('<4i', -1, 0, 0, 0)):
            self.assertTrue(check_tf1_physics(data, 1))

    def test_model_ranges_indices_and_duplicate_models(self):
        for data in (model(1) + TERMINAL, model() * 2 + TERMINAL,
                     struct.pack('<4i', 0, -1, 0, 0),
                     struct.pack('<4i', 0, 999, 0, 1)):
            self.assertTrue(check_tf1_physics(data, 1))

    def test_solid_lengths_counts_and_signatures(self):
        for data in (struct.pack('<4i', 0, 4, 0, 2) + bytes(4),
                     struct.pack('<5i', 0, 4, 0, 1, -1),
                     struct.pack('<5i', 0, 4, 0, 1, 100),
                     model(solid=b'nope') + TERMINAL):
            self.assertTrue(check_tf1_physics(data, 1))
        # Extra bytes in a model are not mistaken for its keydata or next header.
        self.assertIn('do not consume', str(check_tf1_physics(
            struct.pack('<4i', 0, 4, 0, 0) + bytes(4) + TERMINAL, 1)))

    def test_compact_surface_trees_ledges_and_edges(self):
        def problem(data, brushes=0):
            return str(check_tf1_physics(model(solid=data) + TERMINAL, 1, brushes))
        self.assertEqual(problem(solid(client=3), 4), '[]')
        self.assertIn('client data', problem(solid(client=4), 4))
        self.assertIn('shorter', problem(b'VPHYoriginal'))
        broken = bytearray(solid())
        broken[76 + 16 + 4] ^= 1  # the first edge now starts at the wrong point
        self.assertIn('twinned', problem(bytes(broken)))
        self.assertIn('twin outside', problem(solid(triangles=TETRA[:3])))
        self.assertIn('tree node', problem(solid(root=4)))
        nan = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, float('nan')))
        self.assertIn('nonfinite ledge point', problem(solid(points=nan)))
        size = bytearray(solid())
        size[28 + 28] ^= 1  # max_deviation varies in retail and is not checked
        self.assertEqual(problem(bytes(size)), '[]')
        size[28 + 29] ^= 1
        self.assertIn('byte size', problem(bytes(size)))

    def test_keydata_requires_one_terminated_string(self):
        for keys in (b'unterminated', b'a\0b\0'):
            self.assertIn('keydata', str(check_tf1_physics(model(keys=keys) + TERMINAL, 1)))

    def test_texture_name_offsets_and_indices(self):
        textures = [(0, 0, 0, 0), (0, 0, 0, 1)]
        self.assertEqual(check_tf1_texture_strings(b'test/a\0test/b\0', [(0,), (7,)], textures), [])
        for data, offsets, message in ((b'a\0', [(2,)], 'outside'),
                                       (b'abc\0', [(1,)], 'inside another'),
                                       (b'abc', [(0,)], 'unterminated'),
                                       (b'\0', [(0,)], 'empty')):
            self.assertIn(message, str(check_tf1_texture_strings(data, offsets, [])))
        self.assertIn('name index outside', str(check_tf1_texture_strings(b'a\0', [(0,)], textures)))
        self.assertIn('name index outside', str(check_tf1_texture_strings(b'a\0', [(0,)], [(0,0,0,-1)])))


if __name__ == '__main__':
    unittest.main()
