"""Loopback startup stays independent of the machine's DNS configuration."""
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.loopback_http import LoopbackHTTPServer, ThreadingLoopbackHTTPServer


class LoopbackTests(unittest.TestCase):
    def test_startup_binds_without_reverse_dns(self):
        for server_type in (LoopbackHTTPServer, ThreadingLoopbackHTTPServer):
            with self.subTest(server=server_type.__name__), patch("socket.getfqdn", side_effect=AssertionError("DNS must not run")):
                with server_type(("127.0.0.1", 0), BaseHTTPRequestHandler) as server:
                    self.assertEqual(server.server_name, "localhost")
                    self.assertEqual(server.server_address[0], "127.0.0.1")
                    self.assertGreater(server.server_port, 0)

    def test_rejects_exposing_the_server_on_other_interfaces(self):
        for server_type in (LoopbackHTTPServer, ThreadingLoopbackHTTPServer):
            with self.subTest(server=server_type.__name__), self.assertRaises(ValueError):
                server_type(("0.0.0.0", 0), BaseHTTPRequestHandler)
