"""Recover only the known Douyin/Buyin inactivity dialog, not arbitrary prompts."""

import re
import time
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary


BACKEND_HOSTS = {"buyin.jinritemai.com", "fxg.jinritemai.com", "compass.jinritemai.com"}
IDLE_MARKERS = ("检测到您长时间未操作", "为保障您的账号安全", "系统已自动唤起保护机制")


def is_idle_protection_text(text):
    compact = re.sub(r"\s+", "", text)
    return (all(marker in compact for marker in IDLE_MARKERS)
            and not any(word in compact for word in ("验证码", "重新登录", "人机验证", "同意协议")))


class IdleProtectionGuard:
    def __init__(self, notice, clock=time.monotonic):
        self.notice = notice
        self.clock = clock
        self._attempts = WeakKeyDictionary()

    @staticmethod
    def supported(page):
        return urlsplit(page.url).hostname in BACKEND_HOSTS

    @staticmethod
    def dialogs(page):
        return page.locator('[role="dialog"]:visible').all()

    def restore(self, page):
        if not self.supported(page) or page.is_closed():
            return False
        try:
            matches = [dialog for dialog in self.dialogs(page)
                       if is_idle_protection_text(dialog.inner_text(timeout=1000))]
            if len(matches) > 1:
                matches = [dialog for dialog in matches if not dialog.locator('[role="dialog"]:visible').count()]
            if len(matches) != 1:
                self._attempts.pop(page, None)
                return False
            dialog = matches[0]
            count, retry_after = self._attempts.get(page, (0, 0))
            if count >= 3 or self.clock() < retry_after:
                return False
            self._attempts[page] = (count + 1, self.clock() + 10)
            buttons = dialog.get_by_role("button", name=re.compile(r"^恢\s*复$")).all()
            if not buttons:
                buttons = dialog.locator('.auxo-btn').filter(has_text=re.compile(r"^恢\s*复$")).all()
            if len(buttons) != 1:
                raise RuntimeError("恢复按钮未找到或不唯一")
            self.notice(f"检测到后台闲置保护弹窗，正在自动点击“恢复”（{count + 1}/3）")
            buttons[0].click(timeout=2000)
            dialog.wait_for(state="hidden", timeout=3000)
            self._attempts.pop(page, None)
            self.notice("后台闲置保护已恢复，继续弹幕采集和中控操作")
            return True
        except Exception as exc:
            if page.is_closed():
                return False
            count, _retry_after = self._attempts.get(page, (0, 0))
            if count:
                self.notice(f"闲置保护恢复未完成（{type(exc).__name__}）；" +
                            ("已尝试3次，请在浏览器手动处理" if count >= 3 else "至少10秒后再次尝试，当前不强制发布"))
            return False

    def ensure_clear(self, page):
        if not self.supported(page):
            return
        self.restore(page)
        if self.dialogs(page):
            raise RuntimeError("后台弹窗仍遮挡页面，本次操作未执行；仅自动恢复已识别的闲置保护，其他弹窗请手动处理")
