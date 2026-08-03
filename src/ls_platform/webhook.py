"""Label Studio Webhook 处理：把 LS 的标注/审核事件双写进 warehouse.review_event（审计留痕）。

LS 在项目设置中配置 webhook 指向编排层 /webhook/ls。关注事件：
  ANNOTATION_CREATED / ANNOTATION_UPDATED / ANNOTATIONS_DELETED / REVIEW_*(若启用)
每条事件解析出 task、标注 region 摘要、动作，追加写入 review_event 表（append-only）。

ISSUE-014：
- HMAC-SHA256 验签（LABEL_STUDIO_WEBHOOK_SECRET，LS 头 X-Label-Studio-HMAC-SHA256）
- 事件唯一键幂等（同事件重复到达只处理一次，持久化去重表）
- 从 payload 提取真实用户，不用 ls_webhook:动作 冒充审核人

RA-018：去重与业务写入原子化 ——
- 去重改用 DB 唯一事件表 webhook_event（PRIMARY KEY），与 review_event 写入同一事务；
  INSERT OR IGNORE 命中重复 → 不写业务、返回幂等成功；任何一步失败整体回滚
- 事件键强约束：action+task+annotation+updated_at+payload SHA，弱键碰撞不再是风险
- HMAC 非开发环境（APP_ENV != dev）强制配置，未配置直接拒服务而非静默放行
- 原始 payload SHA 落库留证
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path

from ..common.config import PROJECT_ROOT
from ..data import warehouse as wh

# 关注的审核/标注事件（handle_event 处理）
TRACKED = {
    "ANNOTATION_CREATED", "ANNOTATION_UPDATED", "ANNOTATIONS_DELETED",
    "ANNOTATION_SUBMITTED", "REVIEW_ACCEPTED", "REVIEW_REJECTED", "REVIEW_FIXED_AND_ACCEPTED",
}
# 社区版可注册的动作（REVIEW_* 为企业版，注册时只用标注类）
REGISTER_ACTIONS = ["ANNOTATION_CREATED", "ANNOTATION_UPDATED", "ANNOTATIONS_DELETED", "ANNOTATION_SUBMITTED"]

# RA-018：幂等去重已迁移至 DB webhook_event 表（handle_event 单事务）；
# 旧 seen 文件仅作历史兼容，不再参与去重决策。
SEEN_FILE = PROJECT_ROOT / ".platform" / "webhook_seen.json"


def verify_signature(raw_body: bytes, signature: str | None) -> tuple[bool, str]:
    """ISSUE-014/RA-018：HMAC 验签。返回 (通过?, 原因)。

    配置了 LABEL_STUDIO_WEBHOOK_SECRET 则强制验签（缺签名/伪签名均拒绝）；
    RA-018：非开发环境未配置 secret 直接拒绝（不再静默放行）；
    仅 APP_ENV=dev 时记录警告后放行（本机回环部署）。"""
    secret = os.environ.get("LABEL_STUDIO_WEBHOOK_SECRET", "").strip()
    if not secret:
        if os.environ.get("APP_ENV", "prod").strip().lower() == "dev":
            return True, "secret_not_configured"
        return False, "secret_required_in_non_dev_env"
    if not signature:
        return False, "missing_signature"
    expected = hmac.new(secret.encode("utf-8"), raw_body or b"", hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.strip()):
        return False, "invalid_signature"
    return True, "ok"


def _event_key(payload: dict, raw_body: bytes = b"") -> str:
    """ISSUE-014/RA-018：事件唯一键 = action + task + annotation + 更新时间 + payload SHA。

    加入原始 payload SHA：任何内容差异都是不同事件，弱键碰撞不再可能。"""
    task = payload.get("task", {}) or {}
    ann = payload.get("annotation", {}) or {}
    task_id = task.get("id") if isinstance(task, dict) else task
    ann_id = ann.get("id") if isinstance(ann, dict) else None
    updated = ann.get("updated_at") if isinstance(ann, dict) else None
    psha = hashlib.sha256(raw_body).hexdigest()[:16] if raw_body else ""
    raw = f"{payload.get('action', '')}|{task_id}|{ann_id}|{updated}|{psha}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _extract_user(payload: dict) -> str:
    """ISSUE-014：从 payload 提取真实用户（email/id），不用动作名冒充。"""
    for holder in (payload.get("annotation"), payload.get("task")):
        if not isinstance(holder, dict):
            continue
        cb = holder.get("created_by") or holder.get("completed_by")
        if isinstance(cb, dict):
            if cb.get("email"):
                return f"ls_user:{cb['email']}"
            if cb.get("id"):
                return f"ls_user:{cb['id']}"
        elif isinstance(cb, int):
            return f"ls_user:{cb}"
    return "ls_user:unknown"


def _summarize_annotation(ann: dict) -> dict:
    """从 LS annotation 提取 region 摘要（框数、SKU 列表、状态）。"""
    result = ann.get("result", []) if isinstance(ann, dict) else []
    skus, statuses, n_box = [], set(), 0
    for r in result:
        rtype = r.get("type")
        val = r.get("value", {})
        if rtype == "rectanglelabels":
            n_box += 1
        elif rtype == "taxonomy":
            tax = val.get("taxonomy") or []
            if tax and tax[0]:
                skus.append(tax[0][0])
        elif rtype == "choices":
            for ch in val.get("choices", []):
                statuses.add(ch)
    return {"n_box": n_box, "skus": skus[:20], "statuses": sorted(statuses)}


def handle_event(payload: dict, signature: str | None = None,
               raw_body: bytes = b"") -> tuple[int, dict]:
    """处理单个 LS webhook 事件，写入 review_event。返回 (HTTP 状态码, 处理摘要)。"""
    # ISSUE-014：验签（伪造/缺失签名直接 403）
    ok, reason = verify_signature(raw_body, signature)
    if not ok:
        return 403, {"recorded": False, "error": f"signature_{reason}"}
    if reason == "secret_not_configured":
        print("[webhook] 警告：未配置 LABEL_STUDIO_WEBHOOK_SECRET，本次未验签")

    action = payload.get("action", "")
    if action not in TRACKED:
        return 200, {"ignored": action}

    # ISSUE-014/RA-018：幂等 —— 去重标记与业务写入同一事务（DB 唯一键约束）
    key = _event_key(payload, raw_body)
    payload_sha = hashlib.sha256(raw_body).hexdigest() if raw_body else ""

    task = payload.get("task", {}) or {}
    task_id = task.get("id") if isinstance(task, dict) else task
    ann = payload.get("annotation", {}) or {}
    summary = _summarize_annotation(ann)
    reviewer = _extract_user(payload)

    # 映射 LS 动作 → 审核状态
    status_map = {
        "REVIEW_ACCEPTED": "approved",
        "REVIEW_REJECTED": "rejected",
        "REVIEW_FIXED_AND_ACCEPTED": "approved",
        "ANNOTATION_CREATED": "annotated",
        "ANNOTATION_UPDATED": "revised",
        "ANNOTATION_SUBMITTED": "submitted",
        "ANNOTATIONS_DELETED": "deleted",
    }
    status = status_map.get(action, action.lower())

    try:
        conn = wh.connect()
        wh.migrate(conn)
        # RA-018：单事务 —— 去重标记 + 业务写入同提交；任何一步失败整体回滚。
        # INSERT OR IGNORE 命中已存在事件键 → rowcount=0 → 幂等成功，不写业务。
        cur = conn.execute(
            "INSERT OR IGNORE INTO webhook_event(event_key, action, payload_sha, created_at) "
            "VALUES(?,?,?,?)",
            (key, action, payload_sha, time.time()))
        if cur.rowcount == 0:
            conn.close()
            return 200, {"recorded": False, "duplicate": True, "event_key": key}
        conn.execute(
            "INSERT INTO review_event(asset_id,reviewer,status,before_json,after_json,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (f"ls_task_{task_id}", reviewer, status,
             None, json.dumps({**summary, "ls_action": action, "event_key": key}, ensure_ascii=False),
             time.time()))
        conn.commit()
        conn.close()
        return 200, {"recorded": True, "task": task_id, "action": action,
                     "reviewer": reviewer, "status": status, "event_key": key, "summary": summary}
    except Exception as e:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return 500, {"recorded": False, "error": f"{type(e).__name__}: {e}"}


def register_webhook(ls_client, project_id: int, callback_url: str) -> dict | None:
    """在 LS 项目中注册 webhook（幂等：同 URL 不重复创建）。"""
    r = ls_client.s.get(
        f"{ls_client.url}/api/webhooks/",
        params={"project": project_id}, timeout=30)
    if r.status_code == 200:
        for wh_item in r.json():
            if wh_item.get("url") == callback_url:
                return wh_item  # 已存在
    actions = sorted(REGISTER_ACTIONS)
    r = ls_client.s.post(
        f"{ls_client.url}/api/webhooks/",
        json={
            "project": project_id,
            "url": callback_url,
            "send_payload": True,
            "send_for_all_actions": False,
            "actions": actions,
            "is_active": True,
        }, timeout=30)
    if r.status_code in (200, 201):
        return r.json()
    return None
