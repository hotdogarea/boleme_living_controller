import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from boleme_live_control.app import Console


class LegacyWarningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        bridge = patch("boleme_live_control.app.Bridge")
        bridge.start()
        self.addCleanup(bridge.stop)
        self.window = Console()
        self.addCleanup(self.window.close)

    def test_connection_warns_once_without_blocking_or_stopping_other_processes(self):
        with patch("boleme_live_control.app.legacy_douyin_grabber_pids", return_value=[123]) as detect, \
                patch("boleme_live_control.app.BrowserWorker") as worker_type:
            worker = worker_type.return_value
            worker.isRunning.return_value = False
            worker.session_id = "isolated-test-session"
            self.window._start_connection()
            box = self.window._legacy_warning_box
            self.assertIsNotNone(box)
            self.assertIn("先关闭旧插件", box.text())
            self.assertEqual(box.windowModality(), Qt.WindowModality.NonModal)
            worker.start.assert_called_once()
            self.window._warn_legacy_grabber()
            self.assertIs(self.window._legacy_warning_box, box)
            detect.assert_called_once()
            box.close()

    def test_no_old_collector_does_not_show_a_warning(self):
        with patch("boleme_live_control.app.legacy_douyin_grabber_pids", return_value=[]):
            self.window._warn_legacy_grabber()
        self.assertIsNone(self.window._legacy_warning_box)

    def test_process_inspection_failure_does_not_block_connection(self):
        with patch("boleme_live_control.app.legacy_douyin_grabber_pids", side_effect=OSError("test inspection failure")), \
                patch("boleme_live_control.app.BrowserWorker") as worker_type:
            worker = worker_type.return_value
            worker.isRunning.return_value = False
            worker.session_id = "isolated-test-session"
            self.window._start_connection()
            worker.start.assert_called_once()
        self.assertIsNone(self.window._legacy_warning_box)


if __name__ == "__main__":
    unittest.main()
