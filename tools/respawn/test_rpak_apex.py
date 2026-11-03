"""Boundary checks for local Apex RPak inspection, without game assets."""
import struct
import tempfile
from pathlib import Path
import unittest

from rpak_apex import ApexRPak


class ApexRPakTests(unittest.TestCase):
    def read(self, blob):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.rpak'
            path.write_bytes(blob)
            return ApexRPak(path)

    def fixture(self, payload=b'\0name\0'):
        blob=bytearray(140)
        struct.pack_into('<4sH',blob,0,b'RPak',8)
        struct.pack_into('<Q',blob,48,len(blob)+len(payload))
        struct.pack_into('<H',blob,78,1)
        struct.pack_into('<3I',blob,128,0,4,len(payload))
        return blob+payload

    def test_page_string_and_bounds(self):
        pak=self.read(self.fixture())
        self.assertEqual(pak.string((0,1)),'name')
        with self.assertRaisesRegex(ValueError,'outside page'):
            pak.address((0,5),2)
        with self.assertRaisesRegex(ValueError,'Page index'):
            pak.address((1,0))

    def test_refuses_truncated_page(self):
        blob=self.fixture()
        struct.pack_into('<I',blob,136,1000)
        with self.assertRaisesRegex(ValueError,'outside file'):
            self.read(blob)

    def test_refuses_compressed_and_patched(self):
        blob=self.fixture()
        struct.pack_into('<Q',blob,48,1000)
        with self.assertRaisesRegex(ValueError,'decompressed'):
            self.read(blob)
        blob=self.fixture()
        struct.pack_into('<H',blob,80,1)
        with self.assertRaisesRegex(ValueError,'Patched'):
            self.read(blob)


if __name__=='__main__':
    unittest.main()
