"""登录凭据锁定测试（2026-08-12 用户指令：凭据设定后不允许再改变）。

1. 首次出现 PLATFORM_ADMIN_CREDENTIALS → 哈希写入锁定 flag；
2. 锁定后：环境变量（含改回旧口令/改用户名）一律忽略；
3. DB 层 UPDATE/DELETE 锁定 flag 被触发器拒绝；
4. 登录只认锁定凭据；旧 admin 口令失效。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.platform.auth import (AuthService, LOCK_FLAG, default_users,
                               verify_password)
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path) -> PlatformStore:
    return PlatformStore(tmp_path / "p.sqlite")


def test_bootstrap_locks_credential(store, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_CREDENTIALS", "bill:secret-123")
    AuthService(store)
    locked = store.get_flag(LOCK_FLAG)
    assert locked is not None
    username, _, pw_hash = locked.partition(":")
    assert username == "bill"
    assert verify_password("secret-123", pw_hash)


def test_locked_credential_is_the_only_one(store, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_CREDENTIALS", "bill:secret-123")
    auth = AuthService(store)
    users = default_users(store)
    assert list(users.keys()) == ["bill"], "锁定后只有 bill 一个账号"
    assert auth.login("bill", "secret-123")["actor"] == "bill"
    with pytest.raises(PermissionError):
        auth.login("bill", "wrong-password")
    with pytest.raises(PermissionError):
        auth.login("admin", "whatever")


def test_env_change_ignored_after_lock(store, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_CREDENTIALS", "bill:secret-123")
    AuthService(store)
    # 锁定后改环境变量（新口令/新用户名/旧式变量）全部无效
    monkeypatch.setenv("PLATFORM_ADMIN_CREDENTIALS", "evil:other-pass")
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "evil-admin-pass")
    monkeypatch.setenv("PLATFORM_USERS", "evil:e:admin")
    users = default_users(store)
    assert list(users.keys()) == ["bill"]
    auth = AuthService(store)
    assert auth.login("bill", "secret-123")["actor"] == "bill"
    with pytest.raises(PermissionError):
        auth.login("evil", "other-pass")


def test_db_update_delete_locked_flag_rejected(store, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_CREDENTIALS", "bill:secret-123")
    AuthService(store)
    conn = store._conn
    with pytest.raises(Exception):
        conn.execute(
            "UPDATE platform_flag SET value='hacked' WHERE flag=?",
            (LOCK_FLAG,))
    with pytest.raises(Exception):
        conn.execute("DELETE FROM platform_flag WHERE flag=?", (LOCK_FLAG,))
    # 锁定值完好
    assert default_users(store)["bill"][0].startswith("") is True
    locked = store.get_flag(LOCK_FLAG)
    assert locked.startswith("bill:") and verify_password(
        "secret-123", locked.partition(":")[2])
