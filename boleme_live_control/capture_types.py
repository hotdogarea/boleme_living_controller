"""Supported event selection, shared by the console display and local bridge."""

TYPE_LABELS = {"comment": "评论", "enter": "进房", "like": "点赞", "follow": "关注"}


def available_capture_types(capture):
    if capture == "douyin":
        return tuple(TYPE_LABELS)
    return ("comment",) if capture != "none" else ()


def selected_capture_types(settings, capture):
    available = available_capture_types(capture)
    configured = settings.get("capture_types", {})
    value = configured.get(capture) if isinstance(configured, dict) else None
    if not isinstance(value, list):
        return available
    return tuple(kind for kind in available if kind in value)
