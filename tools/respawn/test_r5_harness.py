"""Wire and isolation checks for the R5 map harness; no game install required."""
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest

from r5_harness import (Harness, MAX_FRAME, Netconsole, decode_message,
                        encode_request, identifier, make_playlist, receive_frame)


class HarnessTests(unittest.TestCase):
    def test_legacy_command_name_and_complete_value(self):
        packet = encode_request(0, 'mp_gamemode', 'mp_gamemode fs_dm')
        self.assertEqual(struct.unpack('>I', packet[:4])[0], len(packet)-4)
        fields = decode_message(packet[4:])
        self.assertEqual(fields[1], (1 << 64)-1)
        self.assertEqual(fields[3], 0)
        self.assertEqual(fields[4], 'mp_gamemode')
        self.assertEqual(fields[5], 'mp_gamemode fs_dm')

    def test_fragmented_frame_and_oversized_frame(self):
        sender, receiver = socket.socketpair()
        sender.settimeout(3)
        receiver.settimeout(3)
        packet = encode_request(1, 'test-only-password')
        def send():
            for byte in packet:
                sender.sendall(bytes([byte]))
        thread = threading.Thread(target=send)
        thread.start()
        try:
            self.assertEqual(receive_frame(receiver)[4], 'test-only-password')
            thread.join()
            sender.sendall(struct.pack('>I', MAX_FRAME+1))
            with self.assertRaisesRegex(ValueError, 'bounded'):
                receive_frame(receiver)
        finally:
            sender.close()
            receiver.close()

    def test_rejects_malformed_wire_data(self):
        for data in (b'\x00', b'\x22\x10x', b'\x08'+b'\xff'*10+b'\x01', b'\x0d\x00'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                decode_message(data)

    def test_fake_server_authentication_and_command_roundtrip(self):
        listener = socket.socket(socket.AF_INET6)
        listener.settimeout(3)
        listener.bind(('::1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        received, done = [], threading.Event()
        def server():
            conn, _ = listener.accept()
            with conn:
                received.append(receive_frame(conn))
                conn.sendall(encode_request(0, 'Authentication successful.'))
                received.append(receive_frame(conn))
                received.append(receive_frame(conn))
                conn.sendall(encode_request(1, 'native test output'))
                done.wait(2)
        thread = threading.Thread(target=server)
        thread.start()
        event = threading.Event()
        console = Netconsole(port, 'test-only-password', lambda _: event.set())
        try:
            console.command('status')
            self.assertTrue(event.wait(2))
            self.assertEqual(received[0][3], 1)
            self.assertEqual(received[0][4], 'test-only-password')
            self.assertEqual(received[1][3], 2)
            self.assertEqual(received[1][5], '1')
            self.assertEqual(received[2][5], 'status')
            with self.assertRaises(ValueError):
                console.command('status\nquit')
        finally:
            done.set()
            console.close()
            thread.join()
            listener.close()

    def test_owned_playlist_and_identifier_validation(self):
        original = 'playlists { Gamemodes { fs_dm { inherit defaults } } Playlists { fs_dm { inherit defaults } } }'
        result = make_playlist(original, 'mp_test', 'fs_dm', 'tdm')
        self.assertIn('gamemodes { tdm { maps { mp_test 1 } } }', result)
        self.assertEqual(result.count('mrvn_harness_run'), 1)
        self.assertIn('Playlists { fs_dm { inherit defaults } }', original)
        for value in ('../mp_test', 'mp_test;quit', 'map\nquit', '', 'x'*65):
            with self.assertRaises(ValueError):
                identifier(value)
        with self.assertRaises(ValueError):
            make_playlist('invalid', 'mp_test', 'fs_dm', 'tdm')

    def test_filtered_events_do_not_expose_engine_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = Harness(Path(directory), Path(directory)/'state', 37025)
            harness.event('Installed NetKey: sensitive')
            harness.event('Password hash: sensitive')
            harness.event('normal native event')
            harness.event('value '+harness.password)
            events = list(harness.events)
            self.assertEqual(len(events), 2)
            self.assertNotIn(harness.password, json.dumps(events))
            self.assertEqual(events[-1]['text'], 'value [redacted]')


if __name__ == '__main__':
    unittest.main()
