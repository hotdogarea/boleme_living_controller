"""Opt-in routing for completed voice replies; never generates new content."""

from collections import deque
import time

VOICE_REPLY_TYPES = {"comment": "评论回复", "live_order": "订单感谢"}
ORDER_TEXT_INTERVAL = 30


def selected_voice_reply_types(settings):
    value = settings.get("voice_reply_types")
    if not isinstance(value, list):
        return ("comment",)
    return tuple(kind for kind in VOICE_REPLY_TYPES if kind in value)


class VoiceReplyPolicy:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last_activity = None
        self.seen_orders = set()
        self.order_history = deque(maxlen=2000)

    @staticmethod
    def order_key(command, account_id):
        order_id, separator, _status = str(command.get("event_id") or "").rpartition("#")
        return (command.get("platform"), account_id, order_id) if separator and order_id else None

    def check(self, command, enabled, account_id):
        kind = command.get("event_type", "comment")
        if kind not in enabled:
            return "该类型未开启文字同步"
        if kind != "live_order":
            return ""
        key = self.order_key(command, account_id)
        if not key:
            return "缺少可靠订单标识"
        if key in self.seen_orders:
            return "同一订单已同步，跳过重复感谢"
        if self.last_activity is not None and self.clock() - self.last_activity < ORDER_TEXT_INTERVAL:
            return "文字发送间隔不足30秒，订单感谢已跳过，不积压发送"
        return ""

    def record(self, command, account_id):
        self.touch_activity()
        if command.get("event_type") == "live_order":
            key = self.order_key(command, account_id)
            if key and key not in self.seen_orders:
                if len(self.order_history) == self.order_history.maxlen:
                    self.seen_orders.discard(self.order_history[0])
                self.order_history.append(key)
                self.seen_orders.add(key)

    def touch_activity(self):
        self.last_activity = self.clock()
