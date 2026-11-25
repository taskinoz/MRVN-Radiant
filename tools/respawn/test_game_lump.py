"""Synthetic malformed-input, lossless payload and absolute-offset regressions."""
from pathlib import Path
import struct
import json
import tempfile
import unittest

from game_lump import (decode_sprp_v13, inspect_blob, inspect_game_lump, parse_directory,
                       relocate_blob, relocate_bsp, PROP)
from inspect_bsp import FormatError, HEADER_SIZE


def placement(model=0, x=12.0):
    return PROP.pack(x, 24, 48, 10, 20, 30, 1.5, model, 6, 84, 2, 65535,
                     -1, 12, 24, 48, -1, -1, -1, -1, 255, 128, 64, 255, 1, 2)


def sprp(prop=None, extra=b""):
    name = b"models/test.mdl\0".ljust(128, b"\0")
    return (struct.pack("<I", 1) + name + struct.pack("<3I", 1, 1, 0) +
            (placement() if prop is None else prop) + struct.pack("<I", len(extra) // 64) + extra)


def container(body=None, base=4096, version=13, flags=0):
    body = sprp() if body is None else body
    # Nonzero padding bytes must survive, too.
    return struct.pack("<I4sHHII", 1, b"prps", flags, version, base + 32, len(body)) + b"paddingbytes" + body


def bsp(path, blob=None):
    base = HEADER_SIZE + 64
    blob = container(base=base) if blob is None else blob
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<4s3I", header, 0, b"rBSP", 37, 30, 127)
    struct.pack_into("<4I", header, 16 + 35 * 16, base, len(blob), 0, 0)
    # An unrelated raw lump must retain its original location and bytes.
    struct.pack_into("<4I", header, 16 + 8 * 16, HEADER_SIZE, 64, 0, 0)
    path.write_bytes(header + b"Z" * 64 + blob)


class GameLumpTests(unittest.TestCase):
    def test_v13_layout_unsigned_sentinels_and_raw_angles(self):
        self.assertEqual(PROP.size, 64)
        result = inspect_blob(container(), 4096, True)[0]
        prop = result["placements"][0]
        self.assertEqual(prop["origin"], (12, 24, 48))
        self.assertEqual(prop["angles_raw"], (10, 20, 30))
        self.assertEqual(prop["cubemap_raw"], 65535)
        self.assertEqual(prop["scale"], 1.5)
        self.assertEqual(prop["model"], "models/test.mdl")
        self.assertEqual(prop["collision_flags"], (1, 2))
        self.assertEqual(result["unknown_header_counts"], [1, 0])

    def test_relocation_changes_only_absolute_directory_offset(self):
        original = container()
        moved = relocate_blob(original, 4096, 8192)
        self.assertEqual(moved[:12], original[:12])
        self.assertEqual(moved[16:], original[16:])
        self.assertEqual(struct.unpack_from("<I", moved, 12)[0], 8192 + 32)
        self.assertEqual(inspect_blob(moved, 8192)[0]["sha256"], inspect_blob(original, 4096)[0]["sha256"])

    def test_unknown_version_or_flags_stays_opaque_and_refuses_relocation(self):
        for version, flags in ((50, 0), (13, 1), (99, 8)):
            data = container(b"unknown layout", version=version, flags=flags)
            self.assertFalse(inspect_blob(data, 4096)[0]["decoded"])
            with self.assertRaises(FormatError):
                relocate_blob(data, 4096, 8192)

    def test_absolute_directory_ranges_are_bounded(self):
        for offset in (0, 4096, 4096 + 4, 0xffffffff):
            data = bytearray(container())
            struct.pack_into("<I", data, 12, offset)
            with self.assertRaises(FormatError):
                parse_directory(data, 4096)
        with self.assertRaises(FormatError):
            parse_directory(struct.pack("<I", 0xffffffff), 4096)

    def test_overlapping_entries_rejected(self):
        descriptor = struct.pack("<4sHHII", b"prps", 0, 13, 4096 + 36, 4)
        with self.assertRaises(FormatError):
            parse_directory(struct.pack("<I", 2) + descriptor * 2 + bytes(4), 4096)

    def test_huge_counts_and_missing_name_terminator_rejected(self):
        for body in (b"", struct.pack("<I", 0xffffffff),
                     struct.pack("<I", 1) + b"X" * 128 + bytes(12)):
            with self.assertRaises(FormatError):
                decode_sprp_v13(body)
        body = bytearray(sprp())
        struct.pack_into("<I", body, 132, 0xffffffff)
        with self.assertRaises(FormatError):
            decode_sprp_v13(body)

    def test_invalid_prop_reference_and_nonfinite_transform_rejected(self):
        for prop in (placement(model=1), placement(x=float("nan")), placement(x=float("inf"))):
            with self.assertRaises(FormatError):
                decode_sprp_v13(sprp(prop))

    def test_partial_prop_trailer_and_opaque_extra_records(self):
        for body in (sprp()[:-1], sprp() + b"x"):
            with self.assertRaises(FormatError):
                decode_sprp_v13(body)
        data = container(sprp(extra=b"X" * 64))
        self.assertEqual(inspect_blob(data, 4096)[0]["unknown_record_count"], 1)
        with self.assertRaises(FormatError):
            relocate_blob(data, 4096, 8192)

    def test_unused_lighting_origin_bytes_are_opaque_not_invalid_floats(self):
        prop = bytearray(placement())
        struct.pack_into("<I", prop, 40, 0xffffffff)
        report = inspect_blob(container(sprp(prop)), 4096, True)[0]
        self.assertEqual(report["inactive_nonfinite_lighting_origins"], 1)
        self.assertIsNone(report["placements"][0]["lighting_origin"])
        self.assertTrue(report["placements"][0]["lighting_origin_raw_hex"].startswith("ffffffff"))
        json.dumps(report, allow_nan=False)
        prop[31] |= 2
        with self.assertRaises(FormatError):
            decode_sprp_v13(sprp(prop))

    def test_enabled_lighting_origin_is_decoded(self):
        prop = bytearray(placement())
        prop[31] |= 2
        report = decode_sprp_v13(sprp(prop), True)
        self.assertEqual(report["placements"][0]["lighting_origin"], (12, 24, 48))

    def test_external_absolute_offsets_use_virtual_bsp_base(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.bsp"
            bsp(path)
            external = container(sprp(placement(x=96)), base=HEADER_SIZE + 64)
            path.with_name(path.name + ".0023.bsp_lump").write_bytes(external)
            result = inspect_game_lump(path, True)
            self.assertEqual(result["storage"], "default_external")
            self.assertEqual(result["entries"][0]["placements"][0]["origin"][0], 96)
            with self.assertRaises(FormatError):
                relocate_bsp(path, Path(folder) / "relocated.bsp")

    def test_append_relocation_preserves_source_and_other_lumps(self):
        with tempfile.TemporaryDirectory() as folder:
            path, output = Path(folder) / "test.bsp", Path(folder) / "moved.bsp"
            bsp(path)
            original = path.read_bytes()
            report = relocate_bsp(path, output)
            self.assertEqual(path.read_bytes(), original)
            moved = output.read_bytes()
            self.assertEqual(report["new_base"] % 16, 0)
            self.assertEqual(moved[HEADER_SIZE:len(original)], original[HEADER_SIZE:])
            for i in range(128):
                if i != 35:
                    self.assertEqual(moved[16 + i * 16:32 + i * 16], original[16 + i * 16:32 + i * 16])
            self.assertEqual(inspect_game_lump(path)["entries"][0]["sha256"],
                             inspect_game_lump(output)["entries"][0]["sha256"])
            with self.assertRaises(FileExistsError):
                relocate_bsp(path, output)

    def test_version_gate_and_unknown_empty_entry(self):
        data = struct.pack("<I4sHHII", 1, b"????", 0, 50, 0, 0)
        self.assertFalse(inspect_blob(data, 4096)[0]["decoded"])
        with self.assertRaises(FormatError):
            relocate_blob(container(), 4096, 0xffffffff)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "apex.bsp"
            bsp(path)
            data = bytearray(path.read_bytes())
            struct.pack_into("<I", data, 4, 47)
            path.write_bytes(data)
            with self.assertRaises(FormatError):
                inspect_game_lump(path)


if __name__ == "__main__":
    unittest.main()
