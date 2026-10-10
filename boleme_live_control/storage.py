"""Per-user settings; no cookies or profile data are shipped with the app."""

import json
import os
import re
import secrets
import shutil
from pathlib import Path


_PLATFORM = re.compile(r"^[a-z][a-z0-9_]*$")
_ACCOUNT_ID = re.compile(r"^[0-9a-f]{32}$")


def data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return root / "Boleme" / "LiveControl"


def load_settings() -> dict:
    path = data_dir() / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_settings(data: dict) -> None:
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "settings.json"
    temp = root / f".settings-{os.getpid()}-{secrets.token_hex(4)}.tmp"
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        if json.loads(path.read_text(encoding="utf-8")) != data:
            raise OSError("Saved settings do not match the current configuration")
    finally:
        temp.unlink(missing_ok=True)


def _valid_platform(platform: str) -> bool:
    return isinstance(platform, str) and bool(_PLATFORM.fullmatch(platform))


def accounts_for(settings: dict, platform: str) -> list[dict]:
    if not _valid_platform(platform):
        raise ValueError("Invalid platform")
    accounts = settings.setdefault("accounts", {})
    if not isinstance(accounts, dict):
        accounts = settings["accounts"] = {}
    existing = accounts.get(platform)
    rows = [{"id": "default", "name": "默认账号"}]
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            account_id = item.get("id")
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            if account_id == "default":
                rows[0] = {"id": "default", "name": name.strip()[:30]}
            elif (isinstance(account_id, str) and _ACCOUNT_ID.fullmatch(account_id)
                  and all(row["id"] != account_id for row in rows)):
                rows.append({"id": account_id, "name": name.strip()[:30]})
    accounts[platform] = rows
    return rows


def selected_account(settings: dict, platform: str) -> str:
    rows = accounts_for(settings, platform)
    selected = settings.setdefault("selected_accounts", {})
    if not isinstance(selected, dict):
        selected = settings["selected_accounts"] = {}
    account_id = selected.get(platform)
    if not any(row["id"] == account_id for row in rows):
        account_id = selected[platform] = "default"
    return account_id


def account_profile_path(platform: str, account_id: str, root: Path | None = None) -> Path:
    if not _valid_platform(platform):
        raise ValueError("Invalid platform")
    base = root or data_dir()
    if account_id == "default":
        return base / "profiles" / platform
    if not isinstance(account_id, str) or not _ACCOUNT_ID.fullmatch(account_id):
        raise ValueError("Invalid account ID")
    return base / "profiles" / "accounts" / platform / account_id


def _label(settings: dict, platform: str, name: str, account_id: str = "") -> str:
    label = name.strip() if isinstance(name, str) else ""
    if not label or len(label) > 30 or any(ord(char) < 32 for char in label):
        raise ValueError("账号备注需为 1 到 30 个可读字符")
    if any(row["id"] != account_id and row["name"].casefold() == label.casefold()
           for row in accounts_for(settings, platform)):
        raise ValueError("该平台已有同名账号")
    return label


def add_account(settings: dict, platform: str, name: str) -> str:
    label = _label(settings, platform, name)
    account_id = secrets.token_hex(16)
    accounts_for(settings, platform).append({"id": account_id, "name": label})
    settings.setdefault("selected_accounts", {})[platform] = account_id
    return account_id


def rename_account(settings: dict, platform: str, account_id: str, name: str) -> None:
    label = _label(settings, platform, name, account_id)
    for row in accounts_for(settings, platform):
        if row["id"] == account_id:
            row["name"] = label
            return
    raise ValueError("账号不存在")


def account_profile_for_deletion(platform: str, account_id: str, root: Path | None = None) -> Path:
    if account_id == "default":
        raise ValueError("默认账号保存了旧版登录资料，不能删除")
    base = root or data_dir()
    managed = (base / "profiles" / "accounts").resolve()
    profile = account_profile_path(platform, account_id, base)
    resolved = profile.resolve()
    if resolved.relative_to(managed).parts != (platform, account_id):
        raise ValueError("账号目录超出受管理范围")
    return profile


def delete_account_profile(platform: str, account_id: str, root: Path | None = None) -> None:
    profile = account_profile_for_deletion(platform, account_id, root)
    if profile.exists():
        shutil.rmtree(profile)


def remove_account(settings: dict, platform: str, account_id: str, root: Path | None = None,
                   *, delete_profile: bool = True) -> None:
    account_profile_for_deletion(platform, account_id, root)
    rows = accounts_for(settings, platform)
    if not any(row["id"] == account_id for row in rows):
        raise ValueError("账号不存在")
    was_selected = selected_account(settings, platform) == account_id
    if delete_profile:
        delete_account_profile(platform, account_id, root)
    rows[:] = [row for row in rows if row["id"] != account_id]
    if was_selected:
        settings["selected_accounts"][platform] = "default"


def bridge_token(settings: dict) -> str:
    token = settings.get("bridge_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        settings["bridge_token"] = token
        save_settings(settings)
    return token
