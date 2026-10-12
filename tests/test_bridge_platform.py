"""Platform selection commands stay on the authenticated local bridge."""

import json
import socket
import time
import unittest

from PyQt6.QtCore import QCoreApplication
from websockets.sync.client import connect

from boleme_live_control.bridge import Bridge


class BridgePlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_authenticated_platform_selection_and_status(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        bridge = Bridge("test-token", port=port)
        bridge.platform = "douyin"
        selected = []
        bridge.platform_requested.connect(selected.append)
        try:
            bridge.start()
            with connect(f"ws://127.0.0.1:{port}") as client:
                client.send(json.dumps({"token": "test-token"}))
                self.assertEqual(json.loads(client.recv(timeout=2))["type"], "ready")
                self.assertEqual(json.loads(client.recv(timeout=2))["platform"], "douyin")
                client.send(json.dumps({"type": "select_platform", "platform": "buyin"}))
                end = time.monotonic() + 2
                while not selected and time.monotonic() < end:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.assertEqual(selected, ["buyin"])
                client.send(json.dumps({"type": "select_platform", "platform": "invalid"}))
                self.assertEqual(json.loads(client.recv(timeout=2))["type"], "error")
                self.assertEqual(selected, ["buyin"])
        finally:
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
