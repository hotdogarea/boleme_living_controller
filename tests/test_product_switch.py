import os
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from boleme_live_control.app import Console

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP = QApplication.instance() or QApplication([])


class ProductSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = APP

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": temp.name})
        environment.start()
        self.addCleanup(environment.stop)
        bridge = patch("boleme_live_control.app.Bridge")
        bridge.start()
        self.addCleanup(bridge.stop)
        self.window = Console()
        self.addCleanup(self.window.close)

    def test_start_stop_and_disconnect_update_visible_state(self):
        self.window.connected = True
        self.window.product_enabled.click()
        self.assertTrue(self.window.product_enabled.isChecked())
        self.assertIsNotNone(self.window.product_schedule)
        self.assertEqual(self.window.product_state.text(), "运行中")

        self.window.product_enabled.click()
        self.assertFalse(self.window.product_enabled.isChecked())
        self.assertIsNone(self.window.product_schedule)
        self.assertEqual(self.window.product_state.text(), "已停止")

        self.window.product_enabled.click()
        self.window._worker_finished()
        self.assertFalse(self.window.product_enabled.isChecked())
        self.assertIsNone(self.window.product_schedule)
        self.assertEqual(self.window.product_state.text(), "已停止")

    def test_disconnected_or_invalid_product_does_not_start(self):
        with patch("boleme_live_control.app.QMessageBox.warning") as warning:
            self.window.product_enabled.click()
            self.assertTrue(warning.called)
        self.assertFalse(self.window.product_enabled.isChecked())
        self.assertIsNone(self.window.product_schedule)

        self.window.connected = True
        self.window.products.item(0, 2).setText("0")
        with patch("boleme_live_control.app.QMessageBox.warning") as warning:
            self.window.product_enabled.click()
            self.assertTrue(warning.called)
        self.assertFalse(self.window.product_enabled.isChecked())
        self.assertEqual(self.window.product_state.text(), "已停止")


if __name__ == "__main__":
    unittest.main()
