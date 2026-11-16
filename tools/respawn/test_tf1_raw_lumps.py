"""Original synthetic v29 raw-lump framing and texture name tests."""
import struct
import unittest

from validate_records import check_tf1_physics, check_tf1_texture_strings

TERMINAL = struct.pack('<4i', -1, -1, 0, 0)


def model(index=0, solid=b'VPHYoriginal', keys=b'solid { }\0'):
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
