import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from playwright.sync_api import sync_playwright, Locator, TimeoutError as PlaywrightTimeout
from PyQt6.QtWidgets import QApplication
from boleme_live_control.browser_worker import BrowserWorker
from boleme_live_control.idle_protection import IdleProtectionGuard, is_idle_protection_text


IDLE_TEXT = '检测到您长时间未操作 为保障您的账号安全，系统已自动唤起保护机制'
FIXTURE = '''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<style>.shade {position:fixed;inset:0;background:#7778;display:flex;align-items:center;justify-content:center;z-index:99}
.modal {background:white;padding:24px} textarea {width:300px;height:80px}</style>
<div id="input-comment-block-id"><textarea></textarea>
<div class="inputSuffix-test" onclick="window.sent++;window.lastText=document.querySelector('textarea').value">发布</div></div>
<div class="shade" id="shield" role="dialog"><div class="modal"><h3 id="title">检测到您长时间未操作</h3>
<p id="description">为保障您的账号安全，系统已自动唤起保护机制</p>
<button onclick="window.restored++;document.querySelector('#shield').style.display='none'">恢 复</button></div></div>
<script>window.sent=0;window.restored=0;window.lastText='';</script></body></html>'''


class IdleProtectionBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=FIXTURE))
        self.page = self.context.new_page()
        self.page.goto('https://buyin.jinritemai.com/dashboard/live/control')
        self.worker = BrowserWorker('buyin', Path(tempfile.gettempdir()))
        self.worker.page = self.page
        self.notices = []
        self.worker.capture_notice.connect(self.notices.append)

    def test_known_idle_dialog_is_restored_before_single_publish(self):
        self.worker._send('already generated reply')
        self.assertEqual(self.page.evaluate('window.restored'), 1)
        self.assertEqual(self.page.evaluate('window.sent'), 1)
        self.assertEqual(self.page.evaluate('window.lastText'), 'already generated reply')
        self.assertTrue(any('已恢复' in notice for notice in self.notices))

    def test_periodic_maintenance_restores_without_sending_any_message(self):
        self.worker._maintain_douyin_pages([self.page])
        self.assertEqual(self.page.evaluate('window.restored'), 1)
        self.assertEqual(self.page.evaluate('window.sent'), 0)
        self.assertFalse(self.worker._stopping)

    def test_nested_dialog_roles_are_treated_as_one_idle_popup(self):
        self.page.locator('.modal').evaluate("el => el.setAttribute('role','dialog')")
        self.worker._send('one reply')
        self.assertEqual(self.page.evaluate('window.restored'), 1)
        self.assertEqual(self.page.evaluate('window.sent'), 1)

    def test_capture_response_listener_survives_recovery(self):
        received = []
        self.worker.event_received.connect(received.append)
        self.context.route('**/comment/info?*', lambda route: route.fulfill(json={'data': {'comment_infos': [
            {'comment_id': 'fixture-comment', 'content': 'hello', 'nick_name': 'viewer'}]}}))
        self.page.on('response', self.worker._response)
        self.worker._maintain_douyin_pages([self.page])
        self.page.evaluate("async () => await (await fetch('/comment/info?fixture=1')).json()")
        self.page.wait_for_timeout(50)
        self.app.processEvents()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['content'], 'hello')
        self.assertEqual(received[0]['session_id'], self.worker.session_id)

    def test_unknown_dialog_is_not_confirmed_or_force_clicked(self):
        self.page.locator('#title').evaluate("el => el.textContent='账号安全确认'")
        with self.assertRaisesRegex(RuntimeError, '请手动处理'):
            self.worker._send('do not send')
        self.assertEqual(self.page.evaluate('window.restored'), 0)
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_similarly_named_dialog_on_unrelated_origin_is_not_touched(self):
        self.page.goto('https://unrelated.example/')
        self.assertFalse(self.worker._idle_protection.restore(self.page))
        self.assertEqual(self.page.evaluate('window.restored'), 0)

    def test_product_action_restores_dialog_before_finding_product(self):
        found = []
        def find_product(page, number):
            found.append(number)
            self.assertEqual(page.evaluate('window.restored'), 1)
            raise RuntimeError('fixture ends after preflight')
        with patch.object(self.worker, '_find_product', side_effect=find_product):
            with self.assertRaisesRegex(RuntimeError, 'fixture ends'):
                self.worker._popup(1)
        self.assertEqual(found, [1])

    def test_idle_dialog_appearing_during_trial_is_recovered_without_duplicate_post(self):
        self.page.locator('#shield').evaluate("el => el.style.display='none'")
        original = Locator.click
        injected = []
        def click(locator, **kwargs):
            if kwargs.get('trial') and not injected:
                injected.append(True)
                self.page.locator('#shield').evaluate("el => el.style.display='flex'")
                raise PlaywrightTimeout('fixture: dialog appeared before click')
            return original(locator, **kwargs)
        with patch.object(Locator, 'click', click):
            self.worker._send('one reply')
        self.assertEqual(self.page.evaluate('window.restored'), 1)
        self.assertEqual(self.page.evaluate('window.sent'), 1)

    def test_timeout_after_real_publish_does_not_retry_and_duplicate(self):
        self.page.locator('#shield').evaluate("el => el.style.display='none'")
        original = Locator.click
        def click(locator, **kwargs):
            result = original(locator, **kwargs)
            if not kwargs.get('trial'):
                raise PlaywrightTimeout('fixture: timeout after click')
            return result
        with patch.object(Locator, 'click', click):
            with self.assertRaisesRegex(RuntimeError, '未自动重发'):
                self.worker._send('only one publish')
        self.assertEqual(self.page.evaluate('window.sent'), 1)
        received = []
        self.worker.event_received.connect(received.append)
        self.worker._publish([{'platform': 'buyin', 'type': 'comment', 'content': 'only one publish',
                               'nickname': 'viewer', 'msg_id': 'fixture-viewer-comment'}])
        self.app.processEvents()
        self.assertEqual([event['msg_id'] for event in received], ['fixture-viewer-comment'])

    def test_viewer_same_text_during_publish_is_not_filtered(self):
        self.page.locator('#shield').evaluate("el => el.style.display='none'")
        received = []
        self.worker.event_received.connect(received.append)
        original = Locator.click

        def click(locator, **kwargs):
            result = original(locator, **kwargs)
            if not kwargs.get('trial'):
                self.worker._publish([{'platform': 'buyin', 'type': 'comment',
                                      'content': 'one outgoing reply', 'nickname': 'viewer',
                                      'user_id': '', 'msg_id': 'viewer-same-text'}])
            return result

        with patch.object(Locator, 'click', click):
            self.worker._send('one outgoing reply')
        self.app.processEvents()
        self.assertEqual(self.page.evaluate('window.sent'), 1)
        self.assertEqual([event['msg_id'] for event in received], ['viewer-same-text'])

    def test_preflight_failure_does_not_filter_unsent_draft(self):
        self.page.locator('#shield').evaluate("el => el.style.display='none'")
        with patch.object(Locator, 'fill', side_effect=RuntimeError('fixture fill failed')):
            with self.assertRaisesRegex(RuntimeError, 'fixture fill failed'):
                self.worker._send('unsent draft')
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_changed_comment_after_recovery_is_not_published(self):
        self.page.locator('#shield').evaluate("el => el.style.display='none'")
        self.page.locator('#shield button').evaluate("""el => el.onclick=() => {
            window.restored++;
            document.querySelector('#shield').style.display='none';
            document.querySelector('textarea').value='another draft';
        }""")
        original = Locator.click
        injected = []
        def click(locator, **kwargs):
            if kwargs.get('trial') and not injected:
                injected.append(True)
                self.page.locator('#shield').evaluate("el => el.style.display='flex'")
                raise PlaywrightTimeout('fixture: dialog appeared')
            return original(locator, **kwargs)
        with patch.object(Locator, 'click', click):
            with self.assertRaisesRegex(RuntimeError, '内容已变化'):
                self.worker._send('original draft')
        self.assertEqual(self.page.evaluate('window.restored'), 1)
        self.assertEqual(self.page.evaluate('window.sent'), 0)

    def test_maintenance_click_error_is_contained(self):
        self.page.locator('#shield').evaluate("el => el.style.display='none'")
        self.page.locator('body').evaluate("el => el.insertAdjacentHTML('beforeend','<div class=newCommentLabel-test>新评论</div>')")
        with patch.object(Locator, 'click', side_effect=PlaywrightTimeout('blocked')):
            self.worker._maintain_douyin_pages([self.page])
        self.assertFalse(self.worker._stopping)
        self.assertTrue(any('采集进程继续运行' in notice for notice in self.notices))


class IdleProtectionPolicyTests(unittest.TestCase):
    def test_text_requires_the_known_title_and_explanation(self):
        self.assertTrue(is_idle_protection_text(IDLE_TEXT))
        self.assertFalse(is_idle_protection_text('检测到您长时间未操作，请重新登录并输入验证码'))
        self.assertFalse(is_idle_protection_text('恢复账号权限'))
        self.assertFalse(is_idle_protection_text(IDLE_TEXT + '请同意协议'))

    def test_failed_restore_is_rate_limited_and_bounded_to_three_attempts(self):
        class Button:
            calls = 0
            def click(self, **kwargs):
                self.calls += 1
                raise RuntimeError('blocked')
        class Dialog:
            def inner_text(self, **kwargs):
                return IDLE_TEXT
            def get_by_role(self, *args, **kwargs):
                return self
            def all(self):
                return [button]
        class Page:
            url = 'https://buyin.jinritemai.com/dashboard/live/control'
            def is_closed(self):
                return False
            def locator(self, _selector):
                return self
            def all(self):
                return [dialog]
        button, dialog, page = Button(), Dialog(), Page()
        now, notices = [0], []
        guard = IdleProtectionGuard(notices.append, clock=lambda: now[0])
        for moment in (0, 1, 10, 11, 20, 21, 100):
            now[0] = moment
            self.assertFalse(guard.restore(page))
        self.assertEqual(button.calls, 3)
        self.assertTrue(any('已尝试3次' in notice for notice in notices))


if __name__ == '__main__':
    unittest.main()
