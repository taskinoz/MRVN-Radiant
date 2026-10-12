import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from extract_maps import extract, map_path


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tool = self.root / "tool.exe"
        self.archive = self.root / "archive_dir.vpk"
        self.destination = self.root / "out"
        self.tool.write_bytes(b"fake tool")
        self.archive.write_bytes(b"fake archive")

    def test_map_filter(self):
        for name in ("maps/a.bsp", "maps/a_env.ent", "maps/a.bsp.002a.bsp_lump.client"):
            self.assertTrue(map_path(name))
        self.assertFalse(map_path("models/a.mdl"))
        self.assertFalse(map_path("maps/a.txt"))

    def test_reject_unsafe_paths(self):
        for name in ("../maps/a.bsp", "/maps/a.bsp", "maps/../a.bsp", "maps//a.bsp",
                     "maps/./a.bsp", "maps/a.bsp:stream", "C:/maps/a.bsp", "maps\\a.bsp"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                map_path(name)

    def test_manifest_and_binary_output(self):
        def run(command, **kwargs):
            if command[1] == "list":
                self.assertNotIn("TF2VPKDEBUG", kwargs["env"])
                return subprocess.CompletedProcess(command, 0, "maps/a.bsp\nmaps/a_spawn.ent\n", "")
            kwargs["stdout"].write(b"\x00\xff\r\n")
            return subprocess.CompletedProcess(command, 0, stderr=b"")
        with patch.dict(os.environ, {"TF2VPKDEBUG": "nocrccheck"}), patch("extract_maps.subprocess.run", side_effect=run):
            result = extract(self.tool, self.archive, self.destination)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual((self.destination / "maps/a.bsp").read_bytes(), b"\x00\xff\r\n")
        self.assertEqual(json.loads((self.destination / "extraction.json").read_text()), result)

    def test_relaxed_checks_explicitly_recorded(self):
        def run(command, **kwargs):
            self.assertEqual(kwargs["env"]["TF2VPKDEBUG"], "nosanitycheck")
            if command[1] == "list":
                return subprocess.CompletedProcess(command, 0, "maps/a.bsp\n", "")
            kwargs["stdout"].write(b"test")
            return subprocess.CompletedProcess(command, 0, stderr=b"")
        with patch("extract_maps.subprocess.run", side_effect=run):
            self.assertTrue(extract(self.tool, self.archive, self.destination, True)["relaxed_flags"])

    def test_no_overwrite(self):
        self.destination.mkdir()
        (self.destination / "keep").write_text("existing")
        with patch("extract_maps.subprocess.run") as run, self.assertRaises(ValueError):
            extract(self.tool, self.archive, self.destination)
        run.assert_not_called()
        self.assertEqual((self.destination / "keep").read_text(), "existing")

    def test_failed_extraction_manifest_is_incomplete(self):
        def run(command, **kwargs):
            if command[1] == "list":
                return subprocess.CompletedProcess(command, 0, "maps/a.bsp\n", "")
            kwargs["stdout"].write(b"partial")
            return subprocess.CompletedProcess(command, 1, stderr=b"CRC mismatch")
        with patch("extract_maps.subprocess.run", side_effect=run), self.assertRaises(RuntimeError):
            extract(self.tool, self.archive, self.destination)
        result = json.loads((self.destination / "extraction.json").read_text())
        self.assertFalse(result["complete"])
        self.assertEqual(result["failed_file"], "maps/a.bsp")
        self.assertEqual(result["files"], [])

    def test_archive_without_bsp(self):
        with patch("extract_maps.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            with self.assertRaises(ValueError):
                extract(self.tool, self.archive, self.destination)
        self.assertFalse(self.destination.exists())
