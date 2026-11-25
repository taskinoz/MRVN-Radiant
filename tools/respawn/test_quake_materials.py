#!/usr/bin/env python3
"""Tests for Quake material conversion helpers and the STBSP writer.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

import build_quake_materials as bqm
import stbsp


def png(width, height, rows, colour=6, palette=None):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    body = b"".join(b"\x00" + row for row in rows)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0))
    if palette:
        out += chunk(b"PLTE", palette)
    return out + chunk(b"IDAT", zlib.compress(body)) + chunk(b"IEND", b"")


class QuakeMaterialTests(unittest.TestCase):
    def test_resolution_order(self):
        library = {"tech04_1": 1, "plus_0slipbot": 1, "plus_0basebtn_fbr": 1, "t_tech01": 1, "z_exit_fbr": 1}
        self.assertEqual(bqm.resolve("TECH04_1", library), ("tech04_1", "exact"))
        self.assertEqual(bqm.resolve("+0BASEBTN", library), ("plus_0basebtn_fbr", "renamed"))
        self.assertEqual(bqm.resolve("Z_EXIT", library), ("z_exit_fbr", "renamed"))
        self.assertEqual(bqm.resolve("TECH01_7", library), ("t_tech01", "substitute"))
        self.assertEqual(bqm.resolve("SLIPBOTSD", library), ("plus_0slipbot", "substitute"))
        self.assertEqual(bqm.resolve("UNKNOWN9", library)[1], "default")

    def test_material_names(self):
        self.assertEqual(bqm.material_name("+0SLIP"), "world/quake/plus0slip")
        self.assertEqual(bqm.material_name("TECH04_1"), "world/quake/tech04_1")

    def test_map_texture_scan(self):
        text = '( 0 0 0 ) ( 1 0 0 ) ( 0 1 0 ) TECH04_1 0 0 0 1.000000 1.000000\n' \
               '( 0 0 0 ) ( 1 0 0 ) ( 0 1 0 ) +0SLIP 16 -8 90 1 1\n'
        self.assertEqual(bqm.map_textures(text), ["+0SLIP", "TECH04_1"])

    def test_png_decoding(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.png"
            path.write_bytes(png(2, 1, [bytes([1, 2, 3, 4, 5, 6, 7, 8])]))
            self.assertEqual(bqm.read_png(path), (2, 1, bytes([1, 2, 3, 4, 5, 6, 7, 8])))
            path.write_bytes(png(2, 1, [bytes([1, 0])], colour=3, palette=bytes([9, 9, 9, 7, 7, 7])))
            self.assertEqual(bqm.read_png(path)[2], bytes([7, 7, 7, 255, 9, 9, 9, 255]))

    def test_mips_and_dds(self):
        levels = bqm.mip_chain(4, 2, bytes([200, 100, 0, 255]) * 8)
        self.assertEqual([(w, h) for w, h, _ in levels], [(4, 2), (2, 1), (1, 1)])
        self.assertEqual(levels[-1][2], bytes([200, 100, 0, 255]))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "t.dds"
            bqm.write_dds(path, levels, srgb=True)
            data = path.read_bytes()
            self.assertEqual(data[:4], b"DDS ")
            self.assertEqual(struct.unpack_from("<3I", data, 12), (2, 4, 16))
            self.assertEqual(struct.unpack_from("<I", data, 28)[0], 3)
            self.assertEqual(data[84:88], b"DX10")
            self.assertEqual(struct.unpack_from("<5I", data, 128), (29, 3, 0, 1, 0))
            self.assertEqual(len(data), 148 + (32 + 8 + 4))

    def test_stbsp_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "m.stbsp"
            stbsp.write(path, [("world/quake/b", 2), ("world/quake/a", 1)], (-700, -100), (900, 300))
            catalogue = stbsp.read(path)
            self.assertEqual(catalogue["materials"], [("world/quake/a", 1), ("world/quake/b", 2)])
            self.assertEqual(catalogue["bounds"], (-8, -4, 7, 3))
            self.assertEqual(len(catalogue["columns"]), 4 * 2)
            self.assertTrue(all(c[1] == 32 and c[2] == stbsp.EMPTY_SCALE for c in catalogue["columns"]))
            data = path.read_bytes()
            self.assertEqual(struct.unpack_from("<Q", data, 168 + 16)[0], stbsp.HEADER_SIZE)


if __name__ == "__main__":
    unittest.main()
