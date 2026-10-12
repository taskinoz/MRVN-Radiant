"""Synthetic format tests; no game assets required or redistributed."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

from inspect_bsp import FormatError, HEADER_SIZE, inspect, main


class InspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "test.bsp"

    def make_bsp(self, version=29, lumps=None, payload=b"", endian="<", max_lump=127):
        header = bytearray(struct.pack(endian + "4s3I",
            b"rBSP" if endian == "<" else b"PSBr", version, 12, max_lump))
        for index in range(128):
            header.extend(struct.pack(endian + "4I", *(lumps or {}).get(index, (0, 0, 0, 0))))
        self.path.write_bytes(header + payload)
        return self.path

    def test_profiles(self):
        for version in (29, 37, 47):
            with self.subTest(version=version):
                report = inspect(self.make_bsp(version))
                self.assertEqual(report["version"], [version, 0])
                self.assertEqual(len(report["lumps"]), 128)
                self.assertEqual(report["lumps"][0]["name"], "ENTITIES")
                self.assertIsNotNone(report["compiler_profile_hint"])
                self.assertFalse(report["issues"])

    def test_unknown_version_has_no_inferred_schema(self):
        report = inspect(self.make_bsp(52))
        self.assertIsNone(report["compiler_profile_hint"])
        self.assertIsNone(report["lumps"][0]["name"])
        self.assertEqual(report["issues"][0]["severity"], "warning")

    def test_big_endian(self):
        report = inspect(self.make_bsp(endian=">", lumps={0: (HEADER_SIZE, 4, 2, 0)}, payload=b"data"))
        self.assertEqual(report["byte_order"], "big")
        self.assertEqual(report["lumps"][0]["storage"], "internal")
        self.assertEqual(report["lumps"][0]["version"], 2)

    def test_short_header_and_bad_magic(self):
        for data in (b"rBSP", b"nope" + bytes(HEADER_SIZE - 4)):
            self.path.write_bytes(data)
            with self.assertRaises(FormatError):
                inspect(self.path)

    def test_bad_max_lump(self):
        with self.assertRaises(FormatError):
            inspect(self.make_bsp(max_lump=128))

    def test_internal_digest_and_metadata(self):
        self.make_bsp(lumps={127: (HEADER_SIZE, 4, 9, 123)}, payload=b"data")
        report = inspect(self.path, hashes=True)
        lump = report["lumps"][127]
        self.assertEqual(lump["sha256"], hashlib.sha256(b"data").hexdigest())
        self.assertEqual(lump["fourcc"], 123)
        self.assertEqual(report["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_invalid_ranges(self):
        for offset, length in ((0, 4), (HEADER_SIZE - 1, 4), (HEADER_SIZE, 1), (0xFFFFFFFE, 8)):
            with self.subTest(offset=offset, length=length):
                report = inspect(self.make_bsp(lumps={0: (offset, length, 0, 0)}))
                self.assertEqual(report["lumps"][0]["storage"], "invalid")
                self.assertEqual(report["issues"][0]["severity"], "error")

    def test_empty_lump_offset_does_not_require_payload(self):
        report = inspect(self.make_bsp(lumps={0: (0xFFFFFFFF, 0, 0, 0)}))
        self.assertFalse(report["issues"])

    def test_nested_overlaps_and_adjacent_ranges(self):
        report = inspect(self.make_bsp(lumps={
            0: (HEADER_SIZE, 16, 0, 0), 1: (HEADER_SIZE + 4, 4, 0, 0),
            2: (HEADER_SIZE + 8, 4, 0, 0), 3: (HEADER_SIZE + 16, 4, 0, 0)}, payload=bytes(20)))
        errors = [i for i in report["issues"] if i["severity"] == "error"]
        self.assertEqual(len(errors), 2)
        self.assertEqual({i["lump"] for i in errors}, {1, 2})

    def test_external_override_and_client(self):
        self.make_bsp(lumps={0: (HEADER_SIZE, 4, 0, 0)}, payload=b"base")
        for suffix in ("", ".client"):
            self.path.with_name(self.path.name + ".0000.bsp_lump" + suffix).write_bytes(b"extra")
        report = inspect(self.path, True)
        self.assertEqual(report["lumps"][0]["storage"], "internal_with_override")
        self.assertEqual(len(report["lumps"][0]["external_files"]), 2)
        self.assertFalse(report["issues"])

    def test_streamed_external_uses_entire_sidecar(self):
        self.make_bsp(version=49 | (1 << 16), lumps={0: (0x1000000, 4, 0, 0)})
        extra = self.path.with_name(self.path.name + ".0000.bsp_lump")
        extra.write_bytes(b"external-data")
        report = inspect(self.path, True)
        self.assertEqual(report["version"], [49, 1])
        self.assertEqual(report["lumps"][0]["storage"], "external")
        self.assertEqual(report["lumps"][0]["external_files"][0]["sha256"],
                         hashlib.sha256(b"external-data").hexdigest())
        self.assertFalse(any(i["severity"] == "error" for i in report["issues"]))

    def test_missing_and_empty_external(self):
        self.make_bsp(version=50 | (1 << 16), lumps={0: (0, 4, 0, 0)})
        self.assertEqual(inspect(self.path)["lumps"][0]["storage"], "missing_external")
        self.path.with_name(self.path.name + ".0000.bsp_lump").write_bytes(b"")
        self.assertTrue(any(i["severity"] == "error" for i in inspect(self.path)["issues"]))

    def test_unknown_flags_do_not_infer_streamed_layout(self):
        self.make_bsp(version=49 | (2 << 16), lumps={0: (0, 4, 0, 0)})
        report = inspect(self.path)
        self.assertEqual(report["lumps"][0]["storage"], "unresolved_version_layout")
        self.assertFalse(any(i["severity"] == "error" for i in report["issues"]))

    def test_uppercase_external_lump_id(self):
        self.make_bsp(version=50 | (1 << 16), lumps={42: (0, 4, 0, 0)})
        self.path.with_name(self.path.name + ".002A.bsp_lump").write_bytes(b"data")
        self.assertEqual(inspect(self.path)["lumps"][42]["storage"], "external")

    def test_zero_length_entry_can_have_external_payload(self):
        self.make_bsp(version=50 | (1 << 16))
        self.path.with_name(self.path.name + ".0000.bsp_lump").write_bytes(b"data")
        self.assertEqual(inspect(self.path)["lumps"][0]["storage"], "external")

    def test_entity_headers(self):
        self.make_bsp()
        for version in (b"ENTITIES01\n", b"ENTITIES02 num_models=0\r\n"):
            self.path.with_name("test_spawn.ent").write_bytes(version + b"{}\0")
            report = inspect(self.path, True)
            self.assertEqual(report["entity_files"][0]["header"], version.decode().rstrip())
            self.assertFalse(report["issues"])

    def test_malformed_entity_header(self):
        self.make_bsp()
        self.path.with_name("test_env.ent").write_bytes(b"ENTITIES01")
        self.assertEqual(inspect(self.path)["issues"][0]["severity"], "warning")

    def test_cli_keeps_good_maps_on_bad_input(self):
        self.make_bsp()
        bad = self.root / "bad.bsp"
        bad.write_bytes(b"bad")
        output = self.root / "report.json"
        self.assertEqual(main([str(self.root), "--output", str(output)]), 1)
        report = json.loads(output.read_text())
        self.assertEqual(len(report["maps"]), 1)
        self.assertEqual(len(report["errors"]), 1)

    def test_cli_empty_directory_and_deduplication(self):
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(main([str(self.root)]), 1)
        self.assertTrue(json.loads(captured.getvalue())["errors"])
        self.make_bsp()
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(main([str(self.root), str(self.path)]), 0)
        self.assertEqual(len(json.loads(captured.getvalue())["maps"]), 1)


if __name__ == "__main__":
    unittest.main()
