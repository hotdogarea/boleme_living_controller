import tempfile
import unittest
from pathlib import Path

from boleme_live_control.browser_worker import BrowserWorker
from boleme_live_control.platforms import PLATFORMS


class CommentIdentityTests(unittest.TestCase):
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
