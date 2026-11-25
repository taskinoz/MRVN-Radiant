"""Original synthetic v29 raw-lump framing and texture name tests."""
import io
import struct
import unittest
import zipfile

from game_lump import TF1_PROP
from validate_records import (check_tf1_game_lump, check_tf1_pakfile, check_tf1_physics,
                              check_tf1_rtl, check_tf1_texture_strings)

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


BASE = 4096


def placement(model=0, origin=(1., 2., 3.), scale=1.):
    """A retail-shaped v12 placement, keeping its stale u16 pair and lighting origin."""
    return TF1_PROP.pack(*origin, 0., 90., 0., model, 725, 5008, 6, 4, 0, 0, -1., -1.,
                         float('nan'), 0., 0., 1., 0, 0, 0, 0, 255, 255, 255, 255,
                         92959488, scale, 0, 0)


def sprp(props=(), names=(b'models/a.mdl',), header=None, leaves=()):
    body = struct.pack('<I', len(names)) + b''.join(n.ljust(128, b'\0') for n in names)
    body += struct.pack(f'<I{len(leaves)}H', len(leaves), *leaves)
    body += struct.pack('<3I', *(header or (len(props),) * 3))
    return body + b''.join(props)


def game_lump(body, version=12, flags=0, ident=b'prps'):
    return struct.pack('<I4sHHII', 1, ident, flags, version, BASE + 20, len(body)) + body


def records(props=0, probes=()):
    return {123: [(0, 0, 0, props, 0., 0., 0.)], 102: list(probes)}


class Tf1GameLumpTests(unittest.TestCase):
    def test_retail_shape_and_empty_baseline(self):
        lump = game_lump(sprp([placement(), placement()], header=(2, 1, 1)))
        self.assertEqual(check_tf1_game_lump(lump, BASE, records(2, [(0,), (1,)])), ([], 2))
        self.assertEqual(check_tf1_game_lump(game_lump(sprp(names=())), BASE, records()), ([], 0))
        self.assertEqual(check_tf1_game_lump(b'', BASE, {}), ([], 0))

    def test_framing_version_and_directory(self):
        for lump in (game_lump(sprp() + b'x'), game_lump(sprp(), version=13),
                     game_lump(sprp(), flags=1), game_lump(sprp(), ident=b'dprp'),
                     game_lump(sprp(leaves=(1, 2))[:-4]), struct.pack('<I', 9)):
            issues, count = check_tf1_game_lump(lump, BASE, records())
            self.assertTrue(issues)
            self.assertIsNone(count)

    def test_three_word_header_with_trailing_word_is_rejected(self):
        # Same length as v12, but the first origin lands in the header.
        body = struct.pack('<I', 1) + b'models/a.mdl'.ljust(128, b'\0')
        body += struct.pack('<3I', 0, 1, 1) + placement(origin=(64., 0., 0.)) + struct.pack('<I', 0)
        self.assertIn('header counts', str(check_tf1_game_lump(game_lump(body), BASE, records(1))))

    def test_names_models_and_placement_values(self):
        for body, message in ((sprp(names=(b'',)), 'empty or unterminated'),
                              (sprp(names=(b'm' * 128,)), 'empty or unterminated'),
                              (sprp([placement(model=1)]), 'model index'),
                              (sprp([placement(origin=(float('inf'), 0., 0.))]), 'nonfinite'),
                              (sprp([placement(scale=0.)]), 'scale'),
                              (sprp([placement(scale=float('nan'))]), 'scale')):
            self.assertIn(message, str(check_tf1_game_lump(game_lump(body), BASE, {})[0]))

    def test_level_info_and_probe_counts_must_match(self):
        lump = game_lump(sprp([placement()]))
        self.assertEqual(check_tf1_game_lump(lump, BASE, records(1))[0], [])
        self.assertIn('LEVEL_INFO', str(check_tf1_game_lump(lump, BASE, records(2))))
        self.assertIn('probe count', str(check_tf1_game_lump(lump, BASE, records(1, [(0,), (0,)]))))


def stored_zip(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_STORED) as archive:
        for name, data in files:
            archive.writestr(name, data)
        archive.comment = b'XZP1 0'
    return stream.getvalue()


class Tf1PakfileTests(unittest.TestCase):
    def test_stored_zip_and_empty_lump(self):
        self.assertEqual(check_tf1_pakfile(stored_zip([('materials/a.vmt', b'x' * 9), ('b.vtf', b'')])), [])
        self.assertEqual(check_tf1_pakfile(b''), [])

    def test_compressed_unsafe_and_duplicate_entries(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('a.vmt', b'a' * 100)
        self.assertIn('compressed', str(check_tf1_pakfile(stream.getvalue())))
        for names, message in ((['../a'], 'unsafe'), (['/a'], 'unsafe'), (['a', 'A'], 'duplicate')):
            self.assertIn(message, str(check_tf1_pakfile(stored_zip([(name, b'1') for name in names]))))

    def test_truncation_crc_and_directory_ranges(self):
        data = stored_zip([('a.vmt', b'hello')])
        self.assertIn('end-of-central-directory', str(check_tf1_pakfile(data[:-1])))
        self.assertIn('end-of-central-directory', str(check_tf1_pakfile(data + b'pad')))
        corrupt = bytearray(data)
        corrupt[corrupt.index(b'hello')] ^= 1
        self.assertIn('CRC', str(check_tf1_pakfile(bytes(corrupt))))
        moved = bytearray(data)
        struct.pack_into('<I', moved, data.rindex(b'PK\x05\x06') + 16, len(data))
        self.assertIn('central directory outside', str(check_tf1_pakfile(bytes(moved))))
        local = bytearray(data)
        local[0] = 0
        self.assertIn('local header', str(check_tf1_pakfile(bytes(local))))


class Tf1RealtimeLightTests(unittest.TestCase):
    # Retail order: sky ambient, sun, then realtime point (1) and spot (2) lights.
    LIGHTS = [(0.,) * 12 + (0, kind, 0) for kind in (5, 3, 1, 2)]

    def test_ordered_slots_name_point_or_spot_lights(self):
        texels = bytes([1, 2, 255, 255, 255, 255, 255, 255, 2, 1, 2, 1])
        self.assertEqual(check_tf1_rtl(texels, self.LIGHTS), [])
        self.assertEqual(check_tf1_rtl(b'', []), [])
        self.assertEqual(check_tf1_rtl(b'\xff' * 8, []), [])

    def test_slot_gaps_unknown_and_non_realtime_lights(self):
        self.assertIn('after an unused', str(check_tf1_rtl(bytes([255, 1, 255, 255]), self.LIGHTS)))
        self.assertIn('names no WORLD_LIGHTS', str(check_tf1_rtl(bytes([3, 255, 255, 255]), self.LIGHTS)))
        self.assertIn('not point or spot', str(check_tf1_rtl(bytes([0, 255, 255, 255]), self.LIGHTS)))
        # Hardware indices skip ambient records: a map without an ambient or
        # sun numbers its first point light 0.
        self.assertEqual(check_tf1_rtl(bytes([0, 255, 255, 255]), self.LIGHTS[2:]), [])
        self.assertIn('not point or spot', str(check_tf1_rtl(bytes([0, 255, 255, 255]), self.LIGHTS[1:])))


if __name__ == '__main__':
    unittest.main()
