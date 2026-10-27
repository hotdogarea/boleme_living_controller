import unittest

from boleme_live_control.voice_reply_policy import VoiceReplyPolicy, selected_voice_reply_types


class VoiceReplyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.policy = VoiceReplyPolicy(clock=lambda: self.now)
        self.order = {'platform': 'buyin', 'event_type': 'live_order', 'event_id': 'order-1#0'}
        self.enabled = ('comment', 'live_order')

    def test_only_comments_are_enabled_by_default_and_empty_selection_is_preserved(self):
        self.assertEqual(selected_voice_reply_types({}), ('comment',))
        self.assertEqual(selected_voice_reply_types({'voice_reply_types': []}), ())
        self.assertTrue(self.policy.check(self.order, ('comment',), 'a1'))
        self.assertEqual(self.policy.check({}, ('comment',), 'a1'), '')

    def test_same_order_is_not_repeated_for_payment_notification(self):
        self.assertEqual(self.policy.check(self.order, self.enabled, 'a1'), '')
        self.policy.record(self.order, 'a1')
        self.now = 100
        self.assertIn('同一订单', self.policy.check({**self.order, 'event_id': 'order-1#3'}, self.enabled, 'a1'))
        self.assertEqual(self.policy.check(self.order, self.enabled, 'another-account'), '')

    def test_recent_comment_takes_priority_and_order_is_not_queued(self):
        self.policy.record({}, 'a1')
        self.now = 29
        self.assertIn('30秒', self.policy.check(self.order, self.enabled, 'a1'))
        self.now = 30
        self.assertEqual(self.policy.check(self.order, self.enabled, 'a1'), '')
        self.policy.record(self.order, 'a1')
        self.now = 31
        self.assertIn('30秒', self.policy.check({**self.order, 'event_id': 'order-2#3'}, self.enabled, 'a1'))
        self.assertEqual(self.policy.check({}, self.enabled, 'a1'), '')

    def test_order_without_identifier_is_not_sent(self):
        self.assertIn('标识', self.policy.check({**self.order, 'event_id': ''}, self.enabled, 'a1'))

    def test_order_history_is_bounded(self):
        for index in range(2100):
            self.policy.record({**self.order, 'event_id': f'{index}#3'}, 'a1')
        self.assertEqual(len(self.policy.seen_orders), 2000)
        self.assertEqual(len(self.policy.order_history), 2000)


if __name__ == '__main__':
    unittest.main()
