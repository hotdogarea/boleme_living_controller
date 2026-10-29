"""Events sent to the voice engine use its existing barrage field names."""

VOICE_PLATFORMS = {
    "douyin": "douyin",
    "buyin": "douyin",
    "douyin_eos": "douyin",
    "xiaohongshu": "xiaohongshu",
    "xiaohongshu_pgy": "xiaohongshu",
    "wechat": "wechat_channels",
    "kuaishou": "kuaishou",
    "taobao": "taobao",
}
VOICE_TYPES = {"comment", "enter", "like", "follow", "gift",
               "subscribe_merchant_brand_vip", "ecom_fansclub_participate", "live_order"}


def to_voice_event(event: dict) -> dict | None:
    if not isinstance(event, dict):
        return None
    source = event.get("platform")
    platform = VOICE_PLATFORMS.get(source)
    kind = event.get("type")
    if kind == "comment" and event.get("is_self_comment") is True:
        return None
    if not platform or kind not in VOICE_TYPES:
        return None
    content = str(event.get("content") or "")[:500]
    if kind == "comment" and not content.strip():
        return None
    nickname = str(event.get("nickname") or "")[:100]
    user_id = str(event.get("user_id") or "")[:150]
    result = {
        "schema_version": 1,
        "platform": platform,
        "source_platform": source,
        "type": kind,
        "nickname": nickname,
        "content": content,
        "display_text": f"[{kind}] {nickname}: {content}",
        "user_id": user_id,
        "msg_id": str(event.get("msg_id") or "")[:200],
        "session_id": str(event.get("session_id") or ""),
        "account_id": str(event.get("account_id") or ""),
        "full_inner_data": {"User": {"Id": user_id}},
    }
    if kind == "gift":
        result["gift_name"] = content
    if kind == "live_order" and isinstance(event.get("order"), dict):
        order = event["order"]
        result["order"] = {key: order.get(key) for key in (
            "status", "status_code", "product_id", "product_title", "order_ts")}
    return result
