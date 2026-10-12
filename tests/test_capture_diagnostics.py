import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from boleme_live_control.browser_worker import BrowserWorker


class CaptureDiagnosticsTests(unittest.TestCase):
    def test_optional_comment_error_does_not_mark_capture_failed(self):
        worker = BrowserWorker("buyin", Path(tempfile.gettempdir()))
        notices, failures, events = [], [], []
        worker.capture_notice.connect(notices.append)
        worker.action_result.connect(lambda *args: failures.append(args))
        worker.event_received.connect(events.append)
        bad = Mock(
            url="https://buyin.jinritemai.com/comment/info?room_id=private",
            status=200,
            headers={"content-type": "application/json"},
        )
        bad.json.side_effect = ValueError("private response content")
        worker._response(bad)
        worker._response(bad)

        good = Mock(url="https://compass.jinritemai.com/api/message?room=1")
        good.json.return_value = {"data": {"messages": {"comment": [
            {"msg_id": "m1", "nick_name": "A", "content": "hello"},
        ]}}}
        worker._response(good)

        self.assertEqual(len(notices), 1)
        self.assertIn("HTTP 200", notices[0])
        self.assertIn("ValueError", notices[0])
        self.assertNotIn("private", notices[0])
        self.assertEqual(failures, [])
        self.assertEqual(events[0]["msg_id"], "m1")

    def test_primary_compass_error_is_still_reported(self):
        worker = BrowserWorker("buyin", Path(tempfile.gettempdir()))
        failures = []
        worker.action_result.connect(lambda *args: failures.append(args))
        bad = Mock(
            url="https://compass.jinritemai.com/api/message?room=1",
            status=200,
            headers={"content-type": "application/json"},
        )
        bad.json.side_effect = ValueError("private response content")
        worker._response(bad)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][:2], ("capture", False))
        self.assertIn("罗盘消息", failures[0][2])
        self.assertNotIn("private", failures[0][2])


if __name__ == "__main__":
    unittest.main()
