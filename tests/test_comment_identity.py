import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from boleme_live_control.browser_worker import BrowserWorker
from boleme_live_control.platforms import PLATFORMS, PUBLISHER_NAME_SELECTORS, PUBLISHER_PROFILE_URLS
from boleme_live_control.voice_protocol import to_voice_event


class CommentIdentityTests(unittest.TestCase):
    def test_publisher_nickname_not_comment_text_controls_forwarding(self):
        worker = BrowserWorker("buyin", Path(tempfile.gettempdir()), account_id="local-remark")
        worker._publisher_nickname = "主播昵称"
        received = []
        worker.event_received.connect(received.append)
        worker._publish([
            {"platform": "buyin", "type": "comment", "content": "hello",
             "nickname": "主播昵称", "msg_id": "own1"},
            {"platform": "buyin", "type": "comment", "content": "anything else",
             "nickname": "主播昵称", "msg_id": "own2"},
            {"platform": "buyin", "type": "comment", "content": "hello",
             "nickname": "观众", "msg_id": "viewer"},
            {"platform": "buyin", "type": "comment", "content": "hello",
             "nickname": "主播昵称2", "msg_id": "similar-name"},
            {"platform": "buyin", "type": "enter", "content": "",
             "nickname": "主播昵称", "msg_id": "enter"},
        ])
        self.assertEqual(len(received), 5)
        self.assertEqual([e["is_self_comment"] for e in received], [True, True, False, False, False])
        self.assertEqual([e["msg_id"] for e in received if to_voice_event(e)],
                         ["viewer", "similar-name", "enter"])

    def test_unknown_account_never_filters_by_local_account_id(self):
        worker = BrowserWorker("buyin", Path(tempfile.gettempdir()), account_id="主播昵称")
        received = []
        worker.event_received.connect(received.append)
        worker._publish([{"platform": "buyin", "type": "comment", "content": "hello",
                          "nickname": "主播昵称", "msg_id": "m1"}])
        self.assertFalse(received[0]["is_self_comment"])
        self.assertIsNotNone(to_voice_event(received[0]))

    def test_account_name_comes_only_from_unique_visible_trusted_page_field(self):
        self.assertEqual(set(PUBLISHER_NAME_SELECTORS), set(PLATFORMS))
        for platform, (host, selector) in PUBLISHER_NAME_SELECTORS.items():
            with self.subTest(platform=platform):
                worker = BrowserWorker(platform, Path(tempfile.gettempdir()))
                page = Mock(url=f"https://{host}/dashboard/live/control")
                field = Mock()
                field.count.return_value = 1
                field.is_visible.return_value = True
                field.inner_text.return_value = " 主播昵称 "
                ready = Mock()
                ready.count.return_value = 1
                page.locator.side_effect = lambda value: field if value == selector else ready
                worker.page = page
                worker._refresh_publisher_nickname()
                self.assertEqual(worker._publisher_nickname, "主播昵称")
                for count, visible, name in ((0, True, "old"), (2, True, "old"),
                                              (1, False, "old"), (1, True, "主***"),
                                              (1, True, ""), (1, True, "A\nB")):
                    worker._next_publisher_check = 0
                    field.count.return_value = count
                    field.is_visible.return_value = visible
                    field.inner_text.return_value = name
                    worker._refresh_publisher_nickname()
                    self.assertEqual(worker._publisher_nickname, "")
                worker._publisher_nickname = "old"
                worker._next_publisher_check = 0
                page.url = "https://other.example/dashboard/live/control"
                worker._refresh_publisher_nickname()
                self.assertEqual(worker._publisher_nickname, "")

    def test_same_nickname_rule_applies_on_every_platform(self):
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                worker = BrowserWorker(platform, Path(tempfile.gettempdir()))
                worker._publisher_nickname = "主播昵称"
                received = []
                worker.event_received.connect(received.append)
                worker._publish([
                    {"platform": platform, "type": "comment", "content": "same text",
                     "nickname": name, "msg_id": str(index)}
                    for index, name in enumerate(("主播昵称", "观众", "主播昵称2"))
                ])
                self.assertEqual([e["is_self_comment"] for e in received], [True, False, False])
                self.assertEqual([e["msg_id"] for e in received if to_voice_event(e)], ["1", "2"])

    def test_store_suffix_is_removed_only_for_xiaohongshu_storefront(self):
        page = Mock(url="https://ark.xiaohongshu.com/live_center_control")
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.is_visible.return_value = True
        page.locator.return_value.inner_text.return_value = " 主播的店 "
        worker = BrowserWorker("xiaohongshu", Path(tempfile.gettempdir()))
        self.assertEqual(worker._read_publisher_name(page, "ark.xiaohongshu.com", "name"), "主播")
        worker = BrowserWorker("xiaohongshu_pgy", Path(tempfile.gettempdir()))
        self.assertEqual(worker._read_publisher_name(page, "ark.xiaohongshu.com", "name"), "主播的店")

    def test_profile_lookup_is_maintenance_only_cached_and_cleared_on_logout(self):
        for platform, url in PUBLISHER_PROFILE_URLS.items():
            with self.subTest(platform=platform):
                host, selector = PUBLISHER_NAME_SELECTORS[platform]
                worker = BrowserWorker(platform, Path(tempfile.gettempdir()))
                worker.page = Mock(url=f"https://{host}/control")
                worker.page.locator.return_value.count.return_value = 0
                worker.context = Mock()
                profile = worker.context.new_page.return_value
                profile.url = url
                profile.locator.return_value.count.return_value = 1
                profile.locator.return_value.is_visible.return_value = True
                profile.locator.return_value.inner_text.return_value = "主播昵称"
                with patch.object(worker, "_control_ready", return_value=True) as ready:
                    worker._refresh_publisher_nickname()
                    worker.context.new_page.assert_not_called()
                    worker._refresh_publisher_nickname(allow_profile_lookup=True)
                    self.assertEqual(worker._publisher_nickname, "主播昵称")
                    profile.goto.assert_called_once_with(url, wait_until="domcontentloaded", timeout=5000)
                    profile.close.assert_called_once()
                    worker._refresh_publisher_nickname(allow_profile_lookup=True)
                    worker.context.new_page.assert_called_once()
                    ready.return_value = False
                    worker._refresh_publisher_nickname(allow_profile_lookup=True)
                    self.assertEqual(worker._publisher_nickname, "")
                    self.assertEqual(worker._publisher_profile_nickname, "")

    def test_profile_failure_closes_page_throttles_retry_and_does_not_stop_capture(self):
        worker = BrowserWorker("wechat", Path(tempfile.gettempdir()))
        worker.page = Mock(url="https://channels.weixin.qq.com/platform/live/liveBuild")
        worker.page.locator.return_value.count.return_value = 0
        worker.context = Mock()
        profile = worker.context.new_page.return_value
        profile.goto.side_effect = RuntimeError("fixture network failure")
        with patch.object(worker, "_control_ready", return_value=True):
            worker._refresh_publisher_nickname(allow_profile_lookup=True)
            worker._refresh_publisher_nickname(allow_profile_lookup=True)
        profile.close.assert_called_once()
        worker.context.new_page.assert_called_once()
        self.assertEqual(worker._publisher_nickname, "")
        self.assertFalse(worker._stopping)

    def test_same_text_from_different_viewers_is_not_filtered_on_any_platform(self):
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                worker = BrowserWorker(platform, Path(tempfile.gettempdir()))
                received = []
                worker.event_received.connect(received.append)
                worker._publish([
                    {"platform": platform, "type": "comment", "content": "same words",
                     "nickname": "A", "user_id": "", "msg_id": "m1"},
                    {"platform": platform, "type": "comment", "content": "same words",
                     "nickname": "B", "user_id": "", "msg_id": "m2"},
                ])
                self.assertEqual([event["msg_id"] for event in received], ["m1", "m2"])

    def test_actual_duplicate_message_is_still_dropped_by_message_id(self):
        worker = BrowserWorker("buyin", Path(tempfile.gettempdir()))
        received = []
        worker.event_received.connect(received.append)
        event = {"platform": "buyin", "type": "comment", "content": "hello",
                 "nickname": "viewer", "user_id": "", "msg_id": "m1"}
        worker._publish([dict(event), dict(event)])
        self.assertEqual(len(received), 1)


if __name__ == "__main__":
    unittest.main()
