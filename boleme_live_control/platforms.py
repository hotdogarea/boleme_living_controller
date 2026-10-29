"""Platform selectors and event decoding, adapted from oba-live-tool (MIT)."""

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    url: str
    ready: str
    capture: str
    input: str
    submit: str
    goods: str
    goods_id: str
    popup: str
    popup_page: str = ""
    popup_start: str = "讲解"
    popup_stop: str = "结束讲解"
    iframe: str = ""


PLATFORMS = {
    p.key: p for p in (
        Platform("douyin", "抖音小店", "https://fxg.jinritemai.com/ffa/buyin/dashboard/live/control", '[class^="goodsPanel"]', "douyin", "#input-comment-block-id textarea", '#input-comment-block-id div[class^="inputSuffix"]', 'div[class^="goodsItem"]', 'div[class^="indexWrapper"] input', 'div[class^="goodsAction"] button', popup_stop="取消讲解"),
        Platform("buyin", "巨量百应", "https://buyin.jinritemai.com/dashboard/live/control", '[class^="goodsPanel"]', "douyin", "#input-comment-block-id textarea", '#input-comment-block-id div[class^="inputSuffix"]', 'div[class^="goodsItem"]', 'div[class^="indexWrapper"] input', 'div[class^="goodsAction"] button', popup_stop="取消讲解"),
        Platform("douyin_eos", "抖音团购", "https://eos.douyin.com/livesite/live/current", '[class^="layout-container"]', "none", 'textarea[class^="input"]', 'div[class^="comment-wrap"] div[class^="button"]', '#live-card-list div[class^="render-item"]', 'input', '[class^="talking-btn"]', popup_stop="取消讲解"),
        Platform("xiaohongshu", "小红书方舟", "https://ark.xiaohongshu.com/live_center_control", ".app-root-topbar-wrapper", "xiaohongshu", ".comment-input textarea", ".comment-input button", ".goods-list .table-wrap > div > div > table tbody tr", "td:first-child input", ".more-operation .operation-item", popup_stop="结束讲解"),
        Platform("xiaohongshu_pgy", "小红书蒲公英", "https://pgy.xiaohongshu.com/commerce/redlive/live_center_control", "#redlive-pgy-app .control-container", "xiaohongshu", ".comment-input textarea", ".comment-input button", ".goods-list .table-wrap > div > div > table tbody tr", "td:first-child input", ".more-operation .operation-item", popup_stop="结束讲解"),
        Platform("wechat", "微信视频号", "https://channels.weixin.qq.com/platform/live/liveBuild", ".live-message-input-container", "wechat", ".live-message-input-container textarea", ".live-message-input-container button", ".commodity-list-wrap .table-body-wrap > div > span div.table-row-wrap", "input + span", ".promoting-wrap .action-link span[class*='promoting']", popup_page="https://channels.weixin.qq.com/platform/live/commodity/onsale/index", iframe=".wujie_iframe"),
        Platform("kuaishou", "快手小店", "https://zs.kwaixiaodian.com/page/helper", "div[class^=live-panel]", "kuaishou", 'div[class^=reply-content] input[type=text]', 'div[class^=reply-content] button', '[class^=list-container] [class^=list-item]', 'input', '[class^=cardBtn] > button:last-child', popup_start="开始讲解"),
        Platform("taobao", "淘宝直播", "https://liveplatform.taobao.com/restful/index/live/list", "div.tblalm-lm-content", "taobao", "#comment-page div.tc-comment-reply textarea", "#comment-page div.tc-comment-reply div.tc-comment-reply-footer div.tc-comment-reply-publish-button button", "#livePushed-tcl-unique-scroll-list .list-item", "div.list-item-img-index", 'button[data-tblalog-id="tanPin"]'),
    )
}


# Same current-account selectors as OBA; never use the editable local account remark.
PUBLISHER_NAME_SELECTORS = {
    "douyin": ("fxg.jinritemai.com", '[class^="index_userName"]'),
    "buyin": ("buyin.jinritemai.com", "span.btn-item-role-exchange-name__title"),
}


def _event(platform: str, kind: str, msg: dict, *, text="", nick="", user_id="", msg_id="") -> dict:
    return {
        "platform": platform,
        "type": kind,
        "content": str(text or ""),
        "nickname": str(nick or ""),
        "user_id": str(user_id or ""),
        "msg_id": str(msg_id or ""),
        "time": int(msg.get("time") or time.time() * 1000),
        "raw": msg,
    }


def parse_response(platform: str, url: str, body: Any) -> list[dict]:
    """Only return messages from the platform-specific response path."""
    result = []
    if platform in ("douyin", "buyin"):
        if "comment/info?" in url:
            for msg in (body.get("data") or {}).get("comment_infos") or []:
                result.append(_event(platform, "comment", msg, text=msg.get("content"), nick=msg.get("nick_name"), user_id=msg.get("user_id"), msg_id=msg.get("comment_id")))
        elif "message?" in url and "compass.jinritemai.com" in url:
            for kind, messages in ((body.get("data") or {}).get("messages") or {}).items():
                for msg in messages or []:
                    source_kind = msg.get("msg_type") or kind
                    mapped = {"room_enter": "enter", "room_like": "like", "room_follow": "follow"}.get(source_kind, source_kind)
                    result.append(_event(platform, mapped, msg, text=msg.get("content"), nick=msg.get("nick_name"), user_id=msg.get("user_id"), msg_id=msg.get("msg_id")))
        elif "live_order_stream?" in url and "compass.jinritemai.com" in url:
            for msg in body.get("data") or []:
                code = msg.get("order_status")
                status = "未知状态"
                if isinstance(code, (int, float)) and not isinstance(code, bool):
                    if code <= 1:
                        status = "已下单"
                    elif code == 3:
                        status = "已付款"
                title = str(msg.get("product_title") or "")
                event = _event(platform, "live_order", msg,
                               text=f"{status}：{title}" if title else status,
                               nick=msg.get("nick_name"), user_id=msg.get("user_id"),
                               msg_id=f"{msg['order_id']}#{code}" if msg.get("order_id") else "")
                event["order"] = {
                    "status": status, "status_code": code,
                    "product_id": str(msg.get("product_id") or ""),
                    "product_title": title, "order_ts": msg.get("order_ts"),
                }
                result.append(event)
    elif platform == "wechat" and "micro/live/cgi-bin/mmfinderassistant-bin/live/msg?" in url:
        if body.get("errCode") == 0:
            for msg in (body.get("data") or {}).get("msgList") or []:
                if msg.get("type") == 1:
                    result.append(_event(platform, "comment", msg, text=msg.get("content"), nick=msg.get("nickname"), user_id=msg.get("username"), msg_id=msg.get("clientMsgId")))
            for msg in (body.get("data") or {}).get("appMsgList") or []:
                if msg.get("msgType") == 20002:
                    try:
                        payload = json.loads(base64.b64decode(msg["payload"]))
                        contact = ((msg.get("fromUserContact") or {}).get("contact") or {})
                        result.append(_event(platform, "comment", msg, text=payload.get("content"), nick=contact.get("nickname"), user_id=contact.get("username") or contact.get("usename"), msg_id=msg.get("clientMsgId")))
                    except (ValueError, KeyError):
                        continue
    elif platform == "taobao" and "mtop.taobao.iliad.comment.query.anchorlatest/3.0" in url:
        if isinstance(body, str):
            match = re.match(r"^[^(]+\((.*)\)\s*;?$", body, re.S)
            body = json.loads(match.group(1)) if match else {}
        for msg in (body.get("data") or {}).get("comments") or []:
            result.append(_event(platform, "comment", msg, text=msg.get("content"), nick=msg.get("tbNick"), user_id=msg.get("publisherId"), msg_id=msg.get("commentId")))
    return result


def parse_xiaohongshu_frame(platform: str, payload: str) -> list[dict]:
    result = []
    try:
        frame = json.loads(payload)
        if frame.get("t") != 4:
            return result
        for item in frame["b"]["d"]["b"]:
            parsed = json.loads(base64.b64decode(item["d"]))
            if parsed.get("command") != 1:
                continue
            msg = json.loads(parsed["customData"])
            if msg.get("type") != "text":
                continue
            profile = msg.get("profile") or {}
            result.append(_event(platform, "comment", msg, text=msg.get("desc"), nick=profile.get("nickname"), user_id=profile.get("user_id"), msg_id=msg.get("commentId")))
    except (ValueError, KeyError, TypeError):
        pass
    return result


def parse_kuaishou_message(body: dict) -> list[dict]:
    return [_event("kuaishou", "comment", msg, text=msg.get("commentContent"), nick=msg.get("fromUserName"), user_id=msg.get("fromUserId"), msg_id=msg.get("commentId")) for msg in body.get("commentList") or []]
