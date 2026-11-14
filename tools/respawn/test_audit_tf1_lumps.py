"""Audit coverage must preserve unknown layouts and missing reference payloads."""
import tempfile
from pathlib import Path
import struct
import unittest

from audit_tf1_lumps import audit, writer_lumps
from inspect_bsp import HEADER_SIZE, FormatError


def bsp(path, version=29, payload=b'', lump=54, lump_version=1):
    data = bytearray(HEADER_SIZE)
    struct.pack_into('<4s3I', data, 0, b'rBSP', version, 1, 127)
    if payload:
        struct.pack_into('<4I', data, 16 + lump * 16, HEADER_SIZE, len(payload), lump_version, 0)
    path.write_bytes(data + payload)


class AuditTests(unittest.TestCase):
    def test_conditional_and_duplicate_writes_are_one_coverage_entry(self):
        source = '\n'.join(['AddLump(file, header.lumps[R1_LUMP_WORLD_LIGHTS], x);'] * 2)
        self.assertEqual(writer_lumps(source), {'WORLD_LIGHTS', 'GAME_LUMP'})

    def test_unschematized_payload_does_not_become_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reference.bsp'
            bsp(path, payload=b'\0' * 100, lump=40)
            result = audit([path], 'AddLump(file, header.lumps[R1_LUMP_PAKFILE], x);')
            row = next(row for row in result['lumps'] if row['index'] == 40)
            self.assertTrue(row['writer'])
            self.assertFalse(row['record_schema'])
            self.assertEqual(row['semantic_parity'], 'unverified')
            self.assertEqual(row['observations'][0]['bytes'], 100)

    def test_reject_wrong_game(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wrong.bsp'
            bsp(path, version=37)
            with self.assertRaises(FormatError):
                audit([path], '')

    def test_external_payload_and_bad_record_version_remain_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'external.bsp'
            bsp(path, payload=b'\0' * 12, lump=3, lump_version=99)
            path.with_name(path.name + '.0003.bsp_lump').write_bytes(b'\0' * 25)
            result = audit([path], 'AddLump(file, header.lumps[R1_LUMP_VERTICES], x);')
            row = next(row for row in result['lumps'] if row['index'] == 3)
            observation = row['observations'][0]
            self.assertEqual(observation['bytes'], 25)
            self.assertEqual(observation['remainder'], 1)
            self.assertFalse(observation['schema_version_matches'])
            self.assertTrue(result['maps'][0]['record_issues'])


if __name__ == '__main__':
    unittest.main()
