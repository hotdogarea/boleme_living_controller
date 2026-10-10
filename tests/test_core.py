import unittest

from boleme_live_control.platforms import PLATFORMS, parse_response
from boleme_live_control.scheduler import Product, SequenceScheduler
from boleme_live_control.voice_protocol import to_voice_event


class CoreTests(unittest.TestCase):
    def test_platform_catalog(self):
        self.assertEqual(len(PLATFORMS), 8)

    def test_comment_is_normalized_for_voice_engine(self):
        event = to_voice_event({
            "platform": "buyin", "type": "comment", "nickname": "Alice",
            "content": "How much?", "user_id": "u1", "msg_id": "m1",
            "session_id": "s1", "account_id": "a1", "raw": {"cookie": "never forward"},
        })
        self.assertEqual(event["platform"], "douyin")
        self.assertEqual(event["source_platform"], "buyin")
        self.assertEqual(event["msg_id"], "m1")
        self.assertNotIn("raw", event)
        self.assertNotIn("cookie", str(event))

    def test_empty_comment_is_dropped(self):
        self.assertIsNone(to_voice_event({"platform": "douyin", "type": "comment", "content": " "}))

    def test_buyin_comment_parser_ignores_unrelated_response(self):
        body = {"data": {"comment_infos": [{"comment_id": "m1", "content": "hello"}]}}
        self.assertEqual(parse_response("buyin", "https://other.example/message?", body), [])
        events = parse_response("buyin", "https://compass.jinritemai.com/comment/info?x=1", body)
        self.assertEqual(events[0]["msg_id"], "m1")

    def test_product_schedule_respects_repeat_count(self):
        now = [0]
        schedule = SequenceScheduler(
            [Product(1, repeats=2, interval=10), Product(2, interval=10)],
            clock=lambda: now[0],
        )
        self.assertEqual(schedule.due().number, 1)
        now[0] = 10
        self.assertEqual(schedule.due().number, 1)
        now[0] = 20
        self.assertEqual(schedule.due().number, 2)


if __name__ == "__main__":
    unittest.main()
