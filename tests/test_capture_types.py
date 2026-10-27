import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
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
        self.assertEqual(available_capture_types("douyin"), (
            "comment", "enter", "like", "follow", "subscribe_merchant_brand_vip",
            "ecom_fansclub_participate", "live_order"))
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
        self.assertEqual(self.window.capability.text(), "采集类型：已选 6 类")
        self.assertIn("加入品牌会员", self.window.capability.toolTip())
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
        self.assertFalse(self.window.voice_reply_checks['live_order'].isEnabled())
        self.window.platform.setCurrentIndex(self.window.platform.findData("douyin_eos"))
        self.assertFalse(self.window.capability.isEnabled())
        self.assertEqual(self.window._capture_type_actions, {})

    def test_oba_extra_types_are_displayed_and_forwarded(self):
        for kind, label in (("subscribe_merchant_brand_vip", "加入品牌会员"),
                            ("ecom_fansclub_participate", "加入粉丝团"), ("live_order", "订单")):
            self.window._event(self.event(kind))
            self.window._flush_barrage()
            row = self.window.barrage.rowCount() - 1
            self.assertEqual(self.window.barrage.item(row, 3).text(), label)
            self.assertEqual(self.bridge.broadcast.call_args.args[0]["type"], kind)
            self.window._capture_type_actions[kind].setChecked(False)
            self.bridge.broadcast.reset_mock()
            self.window._event(self.event(kind))
            self.bridge.broadcast.assert_not_called()

    def test_browser_completion_reports_stop_but_account_switch_does_not(self):
        self.window._worker_state("浏览器已关闭，采集停止")
        self.assertEqual(self.bridge.broadcast_status.call_args.kwargs["capture_state"], "stopped")
        self.window._pending_account_id = "next-account"
        self.window._worker_state("已停止")
        self.assertEqual(self.bridge.broadcast_status.call_args.kwargs["capture_state"], "switching")
        self.window._pending_account_id = None
        self.window._worker_finished()
        self.assertEqual(self.bridge.broadcast_status.call_args.kwargs["capture_state"], "stopped")

    def test_voice_text_defaults_to_comments_and_selected_types_persist(self):
        self.assertTrue(self.window.voice_reply_checks['comment'].isChecked())
        self.assertFalse(self.window.voice_reply_checks['live_order'].isChecked())
        self.window.voice_reply_checks['live_order'].setChecked(True)
        self.window.voice_reply_checks['comment'].setChecked(False)
        restarted = Console()
        self.addCleanup(restarted.close)
        self.assertFalse(restarted.voice_reply_checks['comment'].isChecked())
        self.assertTrue(restarted.voice_reply_checks['live_order'].isChecked())

    def test_voice_reply_selection_failure_restores_previous_checkbox(self):
        with patch('boleme_live_control.app.save_settings', side_effect=OSError('read only')):
            self.window.voice_reply_checks['live_order'].setChecked(True)
        self.assertFalse(self.window.voice_reply_checks['live_order'].isChecked())

    def test_order_text_is_opt_in_deduplicated_and_does_not_block_comments(self):
        sent = []
        self.window.worker = SimpleNamespace(session_id='s1', isRunning=lambda: False,
            command=lambda *args: sent.append(args) or True)
        self.window.connected = True
        now = [0]
        self.window.voice_reply_policy.clock = lambda: now[0]
        command = {'type': 'send_public_text', 'platform': self.window.platform.currentData(),
                   'session_id': 's1', 'event_type': 'live_order', 'event_id': 'o1#0', 'text': '谢谢支持'}
        self.window._bridge_send(command)
        self.assertEqual(sent, [])
        self.window.voice_reply_checks['live_order'].setChecked(True)
        self.window._bridge_send(command)
        self.assertEqual(sent, [('send', '谢谢支持')])
        now[0] = 100
        self.window._bridge_send({**command, 'event_id': 'o1#3'})
        self.assertEqual(len(sent), 1)
        self.window._bridge_send({**command, 'event_type': 'comment', 'text': '知识库的原答案'})
        self.assertEqual(sent[-1], ('send', '知识库的原答案'))
        self.window._bridge_send({**command, 'event_id': 'o2#3'})
        self.assertEqual(len(sent), 2)

    def test_busy_worker_does_not_accumulate_order_thanks(self):
        sent = []
        self.window.worker = SimpleNamespace(session_id='s1', isRunning=lambda: False,
            command=lambda *args: sent.append(args) or True)
        self.window.connected = True
        self.window._worker_busy = True
        self.window.voice_reply_checks['live_order'].setChecked(True)
        self.window._bridge_send({'type': 'send_public_text', 'platform': self.window.platform.currentData(),
                   'session_id': 's1', 'event_type': 'live_order', 'event_id': 'o1#3', 'text': '谢谢'})
        self.assertEqual(sent, [])

    def test_simplified_controls_and_independent_capture_and_reply_types(self):
        self.assertNotIn('查看字段', [button.text() for button in self.window.findChildren(QPushButton)])
        self.assertEqual(sum(label.text() == '公开发言' for label in self.window.findChildren(QLabel)), 1)
        self.assertIn('文字回复类型', [label.text() for label in self.window.findChildren(QLabel)])
        self.window.voice_reply_checks['comment'].setChecked(False)
        self.assertTrue(self.window._capture_type_actions['comment'].isChecked())
        self.window._capture_type_actions['enter'].setChecked(False)
        self.assertFalse(self.window.voice_reply_checks['comment'].isChecked())
        self.assertTrue(self.window._capture_type_actions['comment'].isChecked())


if __name__ == "__main__":
    unittest.main()
