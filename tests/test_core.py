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

    def test_compass_membership_and_fansclub_types_preserve_identity(self):
        for platform in ("douyin", "buyin"):
            for kind in ("subscribe_merchant_brand_vip", "ecom_fansclub_participate"):
                with self.subTest(platform=platform, kind=kind):
                    body = {"data": {"messages": {kind: [{"msg_type": kind, "msg_id": "m1",
                            "nick_name": "观众", "user_id": "u1"}]}}}
                    events = parse_response(platform, "https://compass.jinritemai.com/api/message?x=1", body)
                    event = to_voice_event(events[0])
                    self.assertEqual(event["type"], kind)
                    self.assertEqual(event["user_id"], "u1")
                    self.assertEqual(event["nickname"], "观众")

    def test_order_status_matches_oba_and_distinguishes_payment_event(self):
        url = "https://compass.jinritemai.com/api/live_order_stream?x=1"
        for platform in ("douyin", "buyin"):
            for code, label in ((0, "已下单"), (1, "已下单"), (3, "已付款"), (8, "未知状态")):
                with self.subTest(platform=platform, code=code):
                    body = {"data": [{"order_id": "order-1", "order_status": code,
                            "nick_name": "观众", "product_id": "p1", "product_title": "大米",
                            "order_ts": 100, "cookie": "never forward"}]}
                    event = parse_response(platform, url, body)[0]
                    self.assertEqual(event["msg_id"], f"order-1#{code}")
                    event = to_voice_event(event)
                    self.assertEqual(event["type"], "live_order")
                    self.assertEqual(event["order"]["status"], label)
                    self.assertIn(label, event["content"])
                    self.assertEqual(event["order"]["product_title"], "大米")
                    self.assertNotIn("cookie", str(event))


if __name__ == "__main__":
    unittest.main()
