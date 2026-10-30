"""All Playwright objects live on this thread; UI receives Qt signals only."""

import json
import queue
import re
import secrets
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

from PyQt6.QtCore import QThread, pyqtSignal

from .platforms import (
    PLATFORMS, PUBLISHER_NAME_SELECTORS, PUBLISHER_PROFILE_URLS, parse_kuaishou_message,
    parse_response, parse_xiaohongshu_frame,
)
from .idle_protection import IdleProtectionGuard
from .browser_runtime import prepare_browser_runtime


class BrowserWorker(QThread):
    state_changed = pyqtSignal(str)
    event_received = pyqtSignal(dict)
    action_started = pyqtSignal(str)
    action_result = pyqtSignal(str, bool, str)
    capture_notice = pyqtSignal(str)
    reply_result = pyqtSignal(str, bool)

    def __init__(self, platform_key: str, profile_root: Path, parent=None, *,
                 account_id: str = "default", profile_path: Path | None = None):
        super().__init__(parent)
        self.spec = PLATFORMS[platform_key]
        self.session_id = secrets.token_urlsafe(12)
        self.profile_root = profile_root
        self.account_id = account_id
        self.profile_path = profile_path or profile_root / self.spec.key
        self.commands = queue.Queue(maxsize=200)
        self._stopping = False
        self._seen = set()
        self._seen_order = deque()
        self._room_id = None
        self._compass = None
        self._next_compass_attempt = 0.0
        self._products = None
        self._active_control_page = None
        self._browser_closed = False
        self._context_closed = False
        self._xhs_sessions = []
        self._capture_issue_times = {}
        self._comment_response_notice_reported = False
        self._publisher_nickname = ""
        self._next_publisher_check = 0.0
        self._publisher_profile_nickname = ""
        self._next_publisher_profile_attempt = 0.0
        self._checking_publisher = False
        self._publisher_warning_reported = False
        self._idle_protection = IdleProtectionGuard(self.capture_notice.emit)

    def command(self, action: str, value=None):
        try:
            self.commands.put_nowait((action, value))
            return True
        except queue.Full:
            self.action_result.emit(action, False, "操作队列已满")
            return False

    def stop(self):
        self._stopping = True
        self.command("stop")

    def _on_context_closed(self, _context=None):
        self._context_closed = True
        if not self._browser_closed:
            self._browser_closed = True
            if not self._stopping:
                self.state_changed.emit("浏览器已关闭，采集停止")

    def _on_control_page_closed(self, _page=None):
        if not self._browser_closed:
            self._browser_closed = True
            if not self._stopping:
                self.state_changed.emit("中控台页面已关闭，采集停止")

    def _publish(self, events):
        self._refresh_publisher_nickname()
        for event in events:
            if not event["content"] and event["type"] == "comment":
                continue
            key = (event["platform"], event["msg_id"])
            if event["msg_id"] and key in self._seen:
                continue
            if event["msg_id"]:
                self._seen.add(key)
                self._seen_order.append(key)
                if len(self._seen_order) > 4000:
                    self._seen.discard(self._seen_order.popleft())
            event["session_id"] = self.session_id
            event["account_id"] = self.account_id
            event["is_self_comment"] = bool(
                event["type"] == "comment" and self._publisher_nickname
                and str(event.get("nickname") or "").strip() == self._publisher_nickname
            )
            self.event_received.emit(event)

    def _control_ready(self, page):
        if page.locator(self.spec.ready).count():
            return True
        if self.spec.key == "taobao":
            return (urlsplit(page.url).path == "/restful/index/live/control"
                    and page.locator(self.spec.input).count() > 0)
        if self.spec.iframe:
            return page.frame_locator(self.spec.iframe).locator(self.spec.ready).count() > 0
        return False

    def _read_publisher_name(self, page, host, selector):
        if urlsplit(page.url).hostname != host:
            return ""
        field = page.locator(selector)
        if field.count() != 1 or not field.is_visible():
            return ""
        name = field.inner_text(timeout=500).strip()
        if not name or len(name) > 100 or any(char in name for char in ("\n", "\r", "*")):
            return ""
        if self.spec.key == "xiaohongshu" and name.endswith("的店"):
            name = name[:-2].strip()
        return name

    def _lookup_publisher_profile(self, url, host, selector):
        profile = None
        try:
            profile = self.context.new_page()
            profile.goto(url, wait_until="domcontentloaded", timeout=5000)
            if urlsplit(profile.url).hostname != host:
                return ""
            profile.locator(selector).first.wait_for(state="visible", timeout=1500)
            return self._read_publisher_name(profile, host, selector)
        except Exception:
            return ""
        finally:
            if profile is not None:
                try:
                    profile.close()
                except Exception:
                    pass

    def _refresh_publisher_nickname(self, *, allow_profile_lookup=False):
        source = PUBLISHER_NAME_SELECTORS.get(self.spec.key)
        page = getattr(self, "page", None)
        now = time.monotonic()
        if (not source or page is None or self._checking_publisher
                or (now < self._next_publisher_check and not allow_profile_lookup)):
            return
        # Reading a page can dispatch capture callbacks; never navigate from those callbacks.
        self._next_publisher_check = now + 2
        self._checking_publisher = True
        previous = self._publisher_nickname
        name = ""
        try:
            host, selector = source
            if urlsplit(page.url).hostname != host or not self._control_ready(page):
                self._publisher_profile_nickname = ""
                self._publisher_nickname = ""
                return
            name = self._read_publisher_name(page, host, selector)
            profile_url = PUBLISHER_PROFILE_URLS.get(self.spec.key)
            if not name and profile_url:
                if (allow_profile_lookup and not self._publisher_profile_nickname
                        and now >= self._next_publisher_profile_attempt):
                    self._next_publisher_profile_attempt = now + 60
                    self._publisher_profile_nickname = self._lookup_publisher_profile(profile_url, host, selector)
                name = self._publisher_profile_nickname
        except Exception:
            # Unknown or changed account information must not suppress viewer comments.
            name = ""
            self._publisher_profile_nickname = ""
        finally:
            self._checking_publisher = False
        self._publisher_nickname = name
        if name:
            self._publisher_warning_reported = False
            if name != previous:
                self.capture_notice.emit("已识别后台账号昵称；同昵称评论仅在助手显示，不推送语音引擎")
        elif allow_profile_lookup and not self._publisher_warning_reported:
            self._publisher_warning_reported = True
            self.capture_notice.emit("未读取到后台账号昵称；暂不自动排除本人评论，请保留语音引擎的UID或昵称过滤")

    def _response(self, response):
        url = response.url
        if self.spec.capture not in ("douyin", "wechat", "taobao"):
            return
        if self.spec.capture == "douyin" and "promotions_v2?" in url:
            try:
                self._room_id = (response.json().get("data") or {}).get("room_id") or self._room_id
            except Exception:
                pass
            return
        endpoint = None
        if self.spec.capture == "douyin":
            host = urlsplit(url).hostname or ""
            if "comment/info?" in url:
                endpoint = "中控评论"
            elif "message?" in url and host == "compass.jinritemai.com":
                endpoint = "罗盘消息"
            elif "live_order_stream?" in url and host == "compass.jinritemai.com":
                endpoint = "罗盘订单"
        elif self.spec.capture == "wechat" and "micro/live/cgi-bin/mmfinderassistant-bin/live/msg?" in url:
            endpoint = "视频号消息"
        elif self.spec.capture == "taobao" and "mtop.taobao.iliad.comment.query.anchorlatest/3.0" in url:
            endpoint = "淘宝评论"
        if endpoint is None:
            return
        try:
            body = response.text() if self.spec.capture == "taobao" else response.json()
            if self.spec.capture != "taobao" and not isinstance(body, dict):
                raise ValueError("JSON root is not an object")
            self._publish(parse_response(self.spec.key, url, body))
        except Exception as exc:
            status = getattr(response, "status", "未知")
            content_type = (getattr(response, "headers", {}) or {}).get("content-type", "未知")
            if endpoint == "中控评论":
                if not self._comment_response_notice_reported:
                    self._comment_response_notice_reported = True
                    self.capture_notice.emit(
                        f"提示 · 中控评论接口响应未解析 ({type(exc).__name__}, "
                        f"HTTP {status}, {content_type})；这一路异常不代表弹幕采集已停止，"
                        "程序仍会尝试罗盘监听"
                    )
                return
            key = (endpoint, status, content_type, type(exc).__name__)
            now = time.monotonic()
            if now - self._capture_issue_times.get(key, 0) >= 60:
                self._capture_issue_times[key] = now
                self.action_result.emit(
                    "capture", False,
                    f"{endpoint}响应无法解析 ({type(exc).__name__}, "
                    f"HTTP {status}, {content_type})；请确认登录和直播间状态",
                )

    def _kuaishou_hook(self, route):
        response = route.fetch(headers={"Cache-Control": "no-cache"})
        source = response.text()
        if "decodePayload" in source:
            source = re.sub(
                r"([a-zA-Z0-9_$]+)\s*=\s*this\.decodePayload\(([^)]*?[\"']receive[\"']\s*)\)",
                r"\1=(function(res){try{window.__onLiveMessage&&window.__onLiveMessage(res)}catch(e){}return res;})(this.decodePayload(\2))",
                source,
            )
        route.fulfill(response=response, body=source)

    def _on_kuaishou(self, data):
        if isinstance(data, dict):
            self._publish(parse_kuaishou_message(data))

    def _on_xhs_frame(self, params):
        payload = (params.get("response") or {}).get("payloadData", "")
        self._publish(parse_xiaohongshu_frame(self.spec.key, payload))

    def _send(self, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("发送内容不能为空")
        if len(text) > 300:
            raise ValueError("发送内容过长")
        self._ensure_control_clear(self.page)
        target = self.page.frame_locator(self.spec.iframe) if self.spec.iframe else self.page
        field = target.locator(self.spec.input).first
        field.fill(text.strip(), timeout=5000)
        button = self.page.locator(self.spec.submit).first
        has_button = button.count() > 0
        if has_button:
            if not button.is_visible() or "isDisabled" in (button.get_attribute("class") or ""):
                raise RuntimeError("发送按钮不可用，请确认直播间和评论框状态")
            if self.spec.capture == "douyin":
                # A trial is safe to retry: it checks obstruction without publishing.
                try:
                    button.click(trial=True, timeout=2000)
                except Exception:
                    if not self._idle_protection.restore(self.page):
                        raise
                    if field.input_value(timeout=1000) != text.strip():
                        raise RuntimeError("恢复后评论框内容已变化，未自动重复发布，请重新确认内容")
                    button.click(trial=True, timeout=2000)
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        try:
            if has_button:
                button.click(timeout=5000)
            else:
                field.press("Enter", timeout=5000)
        except PlaywrightTimeout as exc:
            raise RuntimeError(f"发布结果未确认，未自动重发；请先核对公屏，避免重复发送。原始错误：{exc}") from exc

    def _ensure_control_clear(self, page):
        if self._stopping or self._browser_closed:
            raise RuntimeError("中控正在停止，操作已取消")
        if self.spec.capture == "douyin":
            self._idle_protection.ensure_clear(page)

    def _maintain_douyin_pages(self, pages):
        if self.spec.capture != "douyin" or self._stopping:
            return
        try:
            for page in pages:
                self._idle_protection.restore(page)
            if self._idle_protection.dialogs(self.page):
                return
            fresh = self.page.locator('[class^="newCommentLabel"]')
            if fresh.count() and fresh.first.is_visible():
                fresh.first.click(timeout=1000)
        except Exception as exc:
            now = time.monotonic()
            if not self._browser_closed and now - self._capture_issue_times.get("page-maintenance", -60) >= 60:
                self._capture_issue_times["page-maintenance"] = now
                self.capture_notice.emit(f"提示 · 中控页面维护暂未完成（{type(exc).__name__}），采集进程继续运行")

    def _goods_page(self):
        if not self.spec.popup_page:
            return self.page
        if self._products is None or self._products.is_closed():
            self._products = self.context.new_page()
            self._products.goto(self.spec.popup_page, wait_until="domcontentloaded", timeout=30000)
        return self._products

    def _find_product(self, page, number):
        for attempt in range(12):
            visible_numbers = []
            for row in page.locator(self.spec.goods).all():
                marker = row.locator(self.spec.goods_id).first
                if not marker.count():
                    continue
                raw = marker.input_value() if self.spec.goods_id == "input" or " input" in self.spec.goods_id else marker.inner_text()
                if raw.strip().lstrip("#") == str(number):
                    return row
                try:
                    visible_numbers.append(int(raw.strip().lstrip("#")))
                except ValueError:
                    continue
            rows = page.locator(self.spec.goods)
            if not rows.count():
                break
            first, last = (visible_numbers[0], visible_numbers[-1]) if visible_numbers else (0, 0)
            reversed_order = first > last
            scroll_up = (number < first and not reversed_order) or (number > first and reversed_order)
            anchor = rows.first if scroll_up else rows.last
            anchor.evaluate("""(el, direction) => {
                let parent = el.parentElement;
                while (parent && parent.scrollHeight <= parent.clientHeight) parent = parent.parentElement;
                if (parent) parent.scrollTop += direction * Math.max(parent.clientHeight * 0.8, 300);
            }""", -1 if scroll_up else 1)
            page.wait_for_timeout(300)
        raise RuntimeError(f"商品序号 {number} 未找到，请确认中控台商品列表")

    def _popup(self, number):
        number = int(number)
        if number < 1:
            raise ValueError("商品序号必须大于 0")
        page = self._goods_page()
        self._ensure_control_clear(page)
        row = self._find_product(page, number)
        if self.spec.key == "taobao":
            button = row.locator(self.spec.popup).first
            if not button.count():
                raise RuntimeError(f"商品 {number} 的弹讲解按钮未找到")
            button.click(timeout=5000)
            return
        if self.spec.key in ("xiaohongshu", "xiaohongshu_pgy"):
            row.hover(timeout=3000)
        buttons = row.locator(self.spec.popup).filter(visible=True)

        def label_pattern(labels):
            return re.compile(r"^\s*(?:" + "|".join(
                r"\s*".join(re.escape(char) for char in label) for label in set(labels)
            ) + r")\s*$")

        start_pattern = label_pattern((self.spec.popup_start, "开始讲解", "讲解"))
        stop_pattern = label_pattern((self.spec.popup_stop, "取消讲解", "结束讲解", "停止讲解"))

        def click_popup(target):
            target.click(timeout=8000)
            if self.spec.key == "kuaishou":
                confirm = page.locator(".ant-modal-root button:last-child")
                if confirm.count():
                    confirm.click(timeout=2000)

        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        active = buttons.filter(has_text=stop_pattern).first
        if active.count():
            self.capture_notice.emit(f"商品 {number} 正在讲解，正在结束本次讲解并等待按钮恢复")
            click_popup(active)
        try:
            # Re-resolve the button after asynchronous updates; never reuse a text snapshot.
            click_popup(buttons.filter(has_text=start_pattern).first)
        except PlaywrightTimeout as exc:
            labels = " / ".join(buttons.all_text_contents())[:120] or "无可见讲解按钮"
            raise RuntimeError(
                f"商品 {number} 的讲解按钮在8秒内未恢复可点击状态（当前：{labels}）；"
                "可能存在加载、禁用或弹窗遮挡；为避免重复操作，本次不自动补点"
            ) from exc
        try:
            buttons.filter(has_text=stop_pattern).first.wait_for(state="visible", timeout=8000)
        except PlaywrightTimeout as exc:
            raise RuntimeError(
                f"商品 {number} 已点击讲解，但8秒内未确认进入讲解状态；"
                "请查看后台是否已生效，本次不自动重复点击"
            ) from exc

    def _enter_taobao_control(self):
        live_id = self.page.locator(
            "#scrollableDiv .tblalm-lm-list-item-live.online "
            ".tblalm-lm-list-item-live-subTitle-id .tui-number-figure"
        ).first
        if not live_id.count():
            return False
        room = live_id.inner_text().strip()
        if not room:
            return False
        self.page.goto(
            f"https://liveplatform.taobao.com/restful/index/live/control?liveId={room}",
            wait_until="domcontentloaded", timeout=30000,
        )
        return True

    def _connect_compass(self):
        if (self.spec.capture != "douyin" or not self._room_id
                or (self._compass and not self._compass.is_closed())
                or time.monotonic() < self._next_compass_attempt):
            return
        self._next_compass_attempt = time.monotonic() + 60
        prefix = "shop" if self.spec.key == "douyin" else "talent"
        page = self.context.new_page()
        self._compass = page
        try:
            page.goto(f"https://compass.jinritemai.com/{prefix}", wait_until="domcontentloaded", timeout=30000)
            page.locator('div[class^="userName"]').first.wait_for(timeout=15000)
            page.goto(f"https://compass.jinritemai.com/screen/anchor/{prefix}?live_room_id={self._room_id}", wait_until="domcontentloaded", timeout=30000)
            page.evaluate("() => { for(const v of document.querySelectorAll('video')) { v.pause(); v.removeAttribute('src'); v.load(); v.remove(); } }")
            self.state_changed.emit("已连接直播间，罗盘弹幕监听中")
        except Exception as exc:
            self._compass = None
            page.close()
            self.action_result.emit("capture", False, f"罗盘监听未就绪，仍可接收中控评论: {exc}")

    def _attach_page(self, page):
        if self.spec.capture == "xiaohongshu":
            session = self.context.new_cdp_session(page)
            session.send("Network.enable")
            session.on("Network.webSocketFrameReceived", self._on_xhs_frame)
            self._xhs_sessions.append(session)

    def _prepare(self):
        self.context.on("response", self._response)
        self.context.on("page", self._attach_page)
        for page in self.context.pages:
            self._attach_page(page)
        if self.spec.capture == "kuaishou":
            self.context.expose_function("__onLiveMessage", self._on_kuaishou)
            self.context.route("**/lib-es-link*.js", self._kuaishou_hook)
        self.page.goto(
            "https://pgy.xiaohongshu.com/microapp/selection/buyer_home"
            if self.spec.key == "xiaohongshu_pgy" else self.spec.url,
            wait_until="domcontentloaded", timeout=30000,
        )
        if self.spec.key == "taobao":
            self.state_changed.emit("请登录并开播，再在浏览器中进入直播中控台")
        else:
            self.state_changed.emit("浏览器已打开，请完成登录并进入直播中控台")

    def run(self):
        stage = "检查浏览器运行组件"
        try:
            prepare_browser_runtime(self.capture_notice.emit)
            from playwright.sync_api import sync_playwright

            self.profile_path.mkdir(parents=True, exist_ok=True)
            stage = "启动Playwright驱动"
            with sync_playwright() as playwright:
                stage = "启动浏览器"
                self.context = None
                errors = []
                for channel in ("msedge", "chrome", None):
                    try:
                        kwargs = {"channel": channel} if channel else {}
                        self.context = playwright.chromium.launch_persistent_context(
                            str(self.profile_path), headless=False, no_viewport=True,
                            args=["--window-size=1600,900", "--disable-background-timer-throttling",
                                  "--disable-renderer-backgrounding"],
                            **kwargs,
                        )
                        break
                    except Exception as exc:
                        errors.append(str(exc).splitlines()[0])
                if self.context is None:
                    raise RuntimeError("浏览器启动失败。请安装 Edge/Chrome 或 Playwright Chromium。" + " | ".join(errors))
                self.context.on("close", self._on_context_closed)
                self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
                stage = "加载中控台"
                self._prepare()
                stage = "运行中控台"
                last_check = 0.0
                ready = False
                comment_ready = False
                douyin_refreshed = False
                taobao_entered = False
                pgy_opened = False
                while not self._stopping and not self._browser_closed:
                    pages = [page for page in self.context.pages if not page.is_closed()]
                    if not pages:
                        self._on_context_closed()
                        break
                    if self._active_control_page and self._active_control_page.is_closed():
                        self._on_control_page_closed()
                        break
                    if self.page.is_closed():
                        self.page = pages[0]
                    now = time.monotonic()
                    if now - last_check >= 2:
                        last_check = now
                        if self.spec.key == "xiaohongshu_pgy" and not pgy_opened:
                            logged_in_page = next((candidate for candidate in pages if candidate.locator(
                                ".top-bar-right-user-item .top-bar-right-user-item-info-name"
                            ).count()), None)
                            if logged_in_page:
                                try:
                                    with self.context.expect_page(timeout=10000) as popup:
                                        logged_in_page.evaluate("""url => {
                                            const link = document.createElement('a');
                                            link.href = url; link.target = '_blank'; link.click();
                                        }""", self.spec.url)
                                    self.page = popup.value
                                    pgy_opened = True
                                except Exception as exc:
                                    self.action_result.emit("connect", False, f"蒲公英中控页未打开: {exc}")
                        if self.spec.key != "taobao":
                            for candidate in pages:
                                if self._control_ready(candidate):
                                    self.page = candidate
                                    break
                        if self.spec.key == "taobao" and not taobao_entered:
                            taobao_entered = any("/live/control?liveId=" in candidate.url for candidate in pages)
                            if taobao_entered:
                                self.page = next(candidate for candidate in pages if "/live/control?liveId=" in candidate.url)
                        if self.spec.key == "taobao" and not taobao_entered:
                            taobao_entered = self._enter_taobao_control()
                        active = taobao_entered if self.spec.key == "taobao" else self._control_ready(self.page)
                        self._maintain_douyin_pages(pages)
                        if active and self.spec.key == "douyin" and not douyin_refreshed:
                            douyin_refreshed = True
                            self.state_changed.emit("登录成功，正在刷新抖店中控台")
                            try:
                                self.page.reload(wait_until="domcontentloaded", timeout=30000)
                            except Exception as exc:
                                self.action_result.emit("connect", False, f"中控台刷新未完成: {exc}")
                            last_check = 0.0
                            continue
                        if active != ready:
                            ready = active
                            comment_ready = False
                            if not ready:
                                self._publisher_nickname = ""
                                self._publisher_profile_nickname = ""
                            self.state_changed.emit("中控台已就绪" if ready else "等待登录或直播中控台")
                        if ready:
                            self._refresh_publisher_nickname(allow_profile_lookup=True)
                            if self._active_control_page is not self.page:
                                self._active_control_page = self.page
                                self.page.on("close", self._on_control_page_closed)
                            if not comment_ready:
                                try:
                                    target = (self.page.frame_locator(self.spec.iframe)
                                              if self.spec.iframe else self.page)
                                    comment_ready = target.locator(self.spec.input).first.count() > 0
                                    if comment_ready:
                                        self.state_changed.emit("中控台已就绪，评论框已定位")
                                except Exception:
                                    pass
                        if ready and self.spec.capture == "douyin" and self._room_id:
                            self._connect_compass()
                    try:
                        action, value = self.commands.get_nowait()
                    except queue.Empty:
                        self.page.wait_for_timeout(100)
                        continue
                    if action == "stop":
                        break
                    self.action_started.emit(action)
                    msg_id = str(value.get("msg_id") or "") if action == "send" and isinstance(value, dict) else ""
                    try:
                        if not ready:
                            raise RuntimeError("请先登录并进入直播中控台")
                        if action == "send":
                            self._send(value.get("text") if isinstance(value, dict) else value)
                        elif action == "popup":
                            self._popup(value)
                        else:
                            raise ValueError(f"未知操作: {action}")
                        detail = "文字已发送" if action == "send" else f"商品 {value} 已弹讲解"
                        self.action_result.emit(action, True, detail)
                        if msg_id:
                            self.reply_result.emit(msg_id, True)
                    except Exception as exc:
                        self.action_result.emit(action, False, str(exc))
                        if msg_id:
                            self.reply_result.emit(msg_id, False)
                if not self._context_closed:
                    self.context.close()
        except Exception as exc:
            if not self._browser_closed and not self._stopping:
                detail = f"{stage}失败（{type(exc).__name__}）：{exc}"
                if isinstance(exc, AttributeError) and "PlaywrightContextManager" in str(exc):
                    detail += (
                        "；Playwright驱动未完成初始化，不代表未安装浏览器。"
                        "请完整解压程序及_internal目录，并检查安全软件隔离记录；不要只复制EXE"
                    )
                self.action_result.emit("connect", False, detail)
        finally:
            self.state_changed.emit("已停止")
