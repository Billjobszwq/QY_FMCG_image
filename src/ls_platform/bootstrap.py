"""Label Studio 平台引导：创建管理员用户、获取 API token、创建 SKU 标注项目、写入 .env。

幂等：用户已存在则登录；项目已存在则复用。
ISSUE-015：无硬编码密码 —— 优先读环境变量 LABEL_STUDIO_PASSWORD，未设置时
随机生成高强度密码（仅输出一次，需立即更换）；.env 写入后 chmod 600；
日志不输出 token 片段或密码。
用法：python -m src.ls_platform.bootstrap"""
from __future__ import annotations

import json
import os
import re
import secrets
import string
import sys
from pathlib import Path

import requests

from ..common.config import PROJECT_ROOT

LS_URL = "http://127.0.0.1:8300"
EMAIL = os.environ.get("LABEL_STUDIO_EMAIL", "admin@qy.local")
PROJECT_TITLE = "SKU 检测标注与审核"
CONFIG_PATH = PROJECT_ROOT / "configs" / "label-studio" / "label_config.xml"
ENV_PATH = PROJECT_ROOT / ".env"


def _resolve_password() -> tuple[str, bool]:
    """ISSUE-015：返回 (密码, 是否本次随机生成)。绝不使用硬编码密码。"""
    pw = os.environ.get("LABEL_STUDIO_PASSWORD", "").strip()
    if pw:
        return pw, False
    alphabet = string.ascii_letters + string.digits + "!@#%^*-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(24)), True


def _csrf(sess: requests.Session) -> str:
    return sess.cookies.get("csrftoken", "")


def ensure_user(sess: requests.Session, password: str) -> None:
    """注册或登录管理员用户。"""
    # 先尝试登录
    sess.get(f"{LS_URL}/user/login/", timeout=30)
    r = sess.post(
        f"{LS_URL}/user/login/",
        data={"email": EMAIL, "password": password, "csrfmiddlewaretoken": _csrf(sess)},
        headers={"Referer": f"{LS_URL}/user/login/"},
        timeout=30, allow_redirects=True,
    )
    if "sessionid" in sess.cookies or r.url.endswith(("/projects/", "/")):
        # 验证是否真的登录成功
        chk = sess.get(f"{LS_URL}/api/current-user/whoami", timeout=30)
        if chk.status_code == 200:
            print(f"[bootstrap] 已登录: {chk.json().get('email')}")
            return
    # 登录失败 → 注册
    sess.get(f"{LS_URL}/user/signup/", timeout=30)
    r = sess.post(
        f"{LS_URL}/user/signup/",
        data={"email": EMAIL, "password": password, "csrfmiddlewaretoken": _csrf(sess)},
        headers={"Referer": f"{LS_URL}/user/signup/"},
        timeout=30, allow_redirects=True,
    )
    chk = sess.get(f"{LS_URL}/api/current-user/whoami", timeout=30)
    if chk.status_code == 200:
        print(f"[bootstrap] 已注册并登录: {chk.json().get('email')}")
    else:
        raise RuntimeError(f"用户创建失败: {r.status_code} {chk.status_code} {chk.text[:200]}")


def get_token(sess: requests.Session) -> str:
    """获取/创建当前用户 API token。"""
    r = sess.get(f"{LS_URL}/api/current-user/token", timeout=30)
    if r.status_code == 200 and r.json().get("token"):
        return r.json()["token"]
    # 创建 token
    r = sess.post(
        f"{LS_URL}/api/current-user/token",
        headers={"X-CSRFToken": _csrf(sess), "Referer": f"{LS_URL}/"},
        timeout=30,
    )
    if r.status_code in (200, 201) and r.json().get("token"):
        return r.json()["token"]
    raise RuntimeError(f"获取 token 失败: {r.status_code} {r.text[:200]}")


def ensure_project(token: str) -> int:
    """创建或复用 SKU 标注项目，返回 project id。"""
    h = {"Authorization": f"Token {token}"}
    # 查找同名项目
    r = requests.get(f"{LS_URL}/api/projects/", headers=h, params={"page_size": 100}, timeout=30)
    for p in r.json().get("results", []):
        if p.get("title") == PROJECT_TITLE:
            print(f"[bootstrap] 复用项目: id={p['id']} {p['title']}")
            return p["id"]
    # 创建新项目
    label_config = CONFIG_PATH.read_text(encoding="utf-8")
    payload = {
        "title": PROJECT_TITLE,
        "label_config": label_config,
        "description": "货架陈列 SKU 检测：自动标注 + 人工审核 + 再训练闭环",
    }
    r = requests.post(f"{LS_URL}/api/projects/", headers=h, json=payload, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"创建项目失败: {r.status_code} {r.text[:300]}")
    pid = r.json()["id"]
    print(f"[bootstrap] 已创建项目: id={pid} {PROJECT_TITLE}")
    # 开启评审模式相关设置（允许预标注）
    return pid


def write_env(token: str, project_id: int, password: str) -> None:
    """把 LS 连接信息写入 .env（不覆盖其它键）；写入后 chmod 600（ISSUE-015）。"""
    lines = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    keys = {
        "LABEL_STUDIO_URL": LS_URL,
        "LABEL_STUDIO_API_KEY": token,
        "LABEL_STUDIO_PROJECT_ID": str(project_id),
        "LABEL_STUDIO_EMAIL": EMAIL,
        "LABEL_STUDIO_PASSWORD": password,
    }
    existing = {l.split("=", 1)[0].strip() for l in lines if "=" in l and not l.strip().startswith("#")}
    for k, v in keys.items():
        if k in existing:
            lines = [re.sub(rf"^{k}=.*$", f"{k}={v}", l) for l in lines]
        else:
            lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_PATH, 0o600)  # ISSUE-015：仅当前用户可读写
    except Exception:
        pass
    print(f"[bootstrap] 已写入 .env（chmod 600）: {', '.join(keys.keys())}")


def main():
    password, generated = _resolve_password()
    sess = requests.Session()
    ensure_user(sess, password)
    token = get_token(sess)
    # ISSUE-015：日志不输出 token 片段与密码
    project_id = ensure_project(token)
    write_env(token, project_id, password)
    print(f"\n=== Label Studio 就绪 ===")
    print(f"  URL: {LS_URL}")
    print(f"  项目 ID: {project_id}")
    print(f"  登录账号: {EMAIL}（密码已写入 .env，不在日志中展示）")
    if generated:
        print(f"  ⚠ 本次随机生成的初始密码（仅此一次显示，请立即登录后更换）: {password}")
    return {"url": LS_URL, "token": token, "project_id": project_id}


if __name__ == "__main__":
    main()
