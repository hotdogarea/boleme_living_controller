import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from boleme_live_control.browser_worker import BrowserWorker
from boleme_live_control.platforms import PLATFORMS


def comment(text, msg_id="m1", **extra):
    return {"platform": "buyin", "type": "comment", "content": text,
            "nickname": "viewer", "user_id": "", "msg_id": msg_id, **extra}


class OutgoingEchoTests(unittest.TestCase):
    def worker(self, platform="buyin"):
        worker = BrowserWorker(platform, Path(tempfile.gettempdir()))
        received = []
        worker.event_received.connect(received.append)
        return worker, received

    def test_delayed_uidless_echo_is_not_forwarded_on_any_platform(self):
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                worker, received = self.worker(platform)
                with patch("boleme_live_control.browser_worker.time.monotonic", return_value=100):
                    worker._remember_outgoing("thanks for your support")
                with patch("boleme_live_control.browser_worker.time.monotonic", return_value=3700):
                    worker._publish([comment("thanks for your support", platform=platform)])
                self.assertEqual(received, [])

    def test_repeated_echoes_from_different_sources_remain_filtered(self):
        worker, received = self.worker()
        worker._remember_outgoing("hello")
        worker._publish([comment("hello", "control"), comment("hello", "compass")])
        worker._publish([comment("hello", "later")])
        self.assertEqual(received, [])

    def test_line_endings_and_outer_whitespace_are_normalized(self):
        worker, received = self.worker()
        worker._remember_outgoing("  first\r\nsecond  ")
        worker._publish([comment("first\nsecond")])
        self.assertEqual(received, [])

    def test_different_viewer_comments_and_non_comment_events_are_kept(self):
        worker, received = self.worker()
        worker._remember_outgoing("hello")
        worker._publish([comment("hello?"), comment("hello", "order", type="live_order"),
                         comment("hello", "enter", type="enter"), comment("hel lo", "spaces")])
        self.assertEqual([event["msg_id"] for event in received], ["m1", "order", "enter", "spaces"])

    def test_history_is_bounded_and_reused_text_is_retained(self):
        worker, received = self.worker()
        worker.OUTGOING_HISTORY_LIMIT = 3
        for text in ("old", "keep", "third", "keep", "new"):
            worker._remember_outgoing(text)
        self.assertEqual(len(worker._outgoing), 3)
        self.assertTrue(all(isinstance(key, bytes) and len(key) == 32 for key in worker._outgoing))
        worker._publish([comment("keep"), comment("old", "old")])
        self.assertEqual([event["msg_id"] for event in received], ["old"])

    def test_different_account_or_connection_has_independent_history(self):
        first, _ = self.worker()
        second, received = self.worker()
        first._remember_outgoing("hello")
        second._publish([comment("hello")])
        self.assertEqual(len(received), 1)


if __name__ == "__main__":
    unittest.main()
