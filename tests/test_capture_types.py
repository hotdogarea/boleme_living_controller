import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from boleme_live_control.app import Console
from boleme_live_control.capture_types import available_capture_types, selected_capture_types
from boleme_live_control.storage import load_settings


class CaptureTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {"LOCALAPPDATA": directory.name})
        env.start()
        self.addCleanup(env.stop)
        bridge = patch("boleme_live_control.app.Bridge")
        self.bridge = bridge.start().return_value
        self.addCleanup(bridge.stop)
        self.window = Console()
        self.addCleanup(self.window.close)

    def event(self, kind, **values):
        return {"platform": "douyin", "type": kind, "content": "多少钱" if kind == "comment" else "",
                "nickname": "观众", "msg_id": kind, **values}

    def test_defaults_match_actual_platform_capabilities(self):
        self.assertEqual(available_capture_types("douyin"), ("comment", "enter", "like", "follow"))
        self.assertEqual(available_capture_types("wechat"), ("comment",))
        self.assertEqual(available_capture_types("none"), ())
        self.assertEqual(selected_capture_types({"capture_types": "old invalid value"}, "douyin"), available_capture_types("douyin"))
        self.assertEqual(set(self.window._capture_type_actions), set(available_capture_types("douyin")))

    def test_unchecked_types_are_not_displayed_or_forwarded(self):
        self.window._capture_type_actions["enter"].setChecked(False)
        self.window._event(self.event("enter"))
        self.window._event(self.event("comment"))
        self.window._flush_barrage()
        self.assertEqual(self.window.barrage.rowCount(), 1)
        self.bridge.broadcast.assert_called_once()
        self.assertEqual(self.bridge.broadcast.call_args.args[0]["type"], "comment")

    def test_changes_are_saved_and_shared_by_douyin_backends(self):
        self.window._capture_type_actions["like"].setChecked(False)
        self.assertNotIn("like", load_settings()["capture_types"]["douyin"])
        self.window.platform.setCurrentIndex(self.window.platform.findData("buyin"))
        self.assertFalse(self.window._capture_type_actions["like"].isChecked())
        restarted = Console()
        self.addCleanup(restarted.close)
        self.assertFalse(restarted._capture_type_actions["like"].isChecked())

    def test_an_empty_selection_is_preserved_and_stops_forwarding(self):
        for action in self.window._capture_type_actions.values():
            action.setChecked(False)
        self.assertEqual(load_settings()["capture_types"]["douyin"], [])
        for kind in available_capture_types("douyin"):
            self.window._event(self.event(kind))
        self.window._flush_barrage()
        self.assertEqual(self.window.barrage.rowCount(), 0)
        self.bridge.broadcast.assert_not_called()
        self.assertIn("未选择", self.window.capability.text())

    def test_failed_save_restores_selection_without_changing_behavior(self):
        with patch("boleme_live_control.app.save_settings", side_effect=OSError("read only")):
            self.window._capture_type_actions["enter"].setChecked(False)
        self.assertTrue(self.window._capture_type_actions["enter"].isChecked())
        self.window._event(self.event("enter"))
        self.bridge.broadcast.assert_called_once()

    def test_pending_rows_and_existing_history_follow_the_selection(self):
        self.window._event(self.event("enter"))
        self.window._capture_type_actions["enter"].setChecked(False)
        self.window._flush_barrage()
        self.assertEqual(self.window.barrage.rowCount(), 0)
        self.window._capture_type_actions["enter"].setChecked(True)
        self.window._event(self.event("enter"))
        self.window._flush_barrage()
        self.window._capture_type_actions["enter"].setChecked(False)
        self.assertTrue(self.window.barrage.isRowHidden(0))
        self.window.only_pending.setChecked(True)
        self.window.only_pending.setChecked(False)
        self.assertTrue(self.window.barrage.isRowHidden(0))
        self.window._capture_type_actions["enter"].setChecked(True)
        self.assertFalse(self.window.barrage.isRowHidden(0))

    def test_other_platforms_only_offer_currently_supported_types(self):
        self.window.platform.setCurrentIndex(self.window.platform.findData("wechat"))
        self.assertEqual(set(self.window._capture_type_actions), {"comment"})
        self.window.platform.setCurrentIndex(self.window.platform.findData("douyin_eos"))
        self.assertFalse(self.window.capability.isEnabled())
        self.assertEqual(self.window._capture_type_actions, {})


if __name__ == "__main__":
    unittest.main()
