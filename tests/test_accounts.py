"""Account labels stay local and survive a new process reading settings."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from boleme_live_control.app import Console
from boleme_live_control.storage import (
    accounts_for, add_account, load_settings, rename_account, save_settings,
    selected_account,
)


class AccountPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_renamed_default_and_extra_account_survive_reload(self):
        settings = {"platform": "buyin"}
        rename_account(settings, "buyin", "default", "商家直播号")
        extra_id = add_account(settings, "buyin", "第二个直播号")
        rename_account(settings, "buyin", extra_id, "备用直播号")
        save_settings(settings)

        reloaded = load_settings()
        self.assertEqual(selected_account(reloaded, "buyin"), extra_id)
        self.assertEqual([row["name"] for row in accounts_for(reloaded, "buyin")],
                         ["商家直播号", "备用直播号"])
        self.assertEqual(accounts_for(reloaded, "douyin")[0]["name"], "默认账号")

    def test_ui_save_confirms_renamed_label_is_on_disk(self):
        settings = {"accounts": {"buyin": [{"id": "default", "name": "商家直播号"}]}}
        saved_messages = []
        fake = SimpleNamespace(
            platform=SimpleNamespace(currentData=lambda: "buyin"),
            account=SimpleNamespace(currentData=lambda: "default"),
            phrases=object(), products=object(), settings=settings,
            _rows=lambda _table: [], _log=saved_messages.append,
        )
        self.assertTrue(Console._save(fake, expected_account=("buyin", "default", "商家直播号")))
        self.assertEqual(accounts_for(load_settings(), "buyin")[0]["name"], "商家直播号")
        self.assertTrue(any("账号备注已保存到本机" in message for message in saved_messages))

        with patch("boleme_live_control.app.QMessageBox.warning"):
            self.assertFalse(Console._save(fake, expected_account=("buyin", "default", "其他名称")))
        self.assertIn("设置保存失败", saved_messages[-1])

    def test_icon_assets_are_present(self):
        assets = Path(__file__).resolve().parents[1] / "assets"
        self.assertTrue((assets / "boleme.svg").is_file())
        self.assertEqual((assets / "boleme.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((assets / "boleme.ico").read_bytes()[:4], b"\x00\x00\x01\x00")


if __name__ == "__main__":
    unittest.main()
