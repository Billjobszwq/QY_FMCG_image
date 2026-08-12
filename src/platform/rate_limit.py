"""UATCC T6：真实限流（固定窗口 + burst + Retry-After + 审计）。

- SQLite 持久化（rate_limit_v1 / rate_limit_rule_v1）：重启后窗口计数
  不完全丢失；
- 主体 + 能力 + IP 组合键；不得通过伪造 header 绕过身份（subject
  一律取服务端认证身份，IP 取 request.client）；
- 429 结构化 + Retry-After；拒绝写审计事件；
- 默认额度足够正常 UAT；规则仅管理员可改且留审计。
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException


def enforce(request: Any, capability: str, subject: str) -> None:
    """端点级限流守卫：429 结构化 + Retry-After。

    subject 必须来自服务端认证身份（不得信任客户端 header）。
    limiter 未装配时放行（测试/降级场景）。"""
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    ip = request.client.host if request.client else ""
    ok, retry_after, count = limiter.check(capability, subject, ip)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited",
                    "capability": capability,
                    "subject": subject,
                    "count": count,
                    "retry_after": round(retry_after, 2)},
            headers={"Retry-After": str(max(1, int(retry_after)))})

# capability -> (max_per_window, window_seconds, burst)
DEFAULT_RULES: dict[str, tuple[int, int, int]] = {
    "auth.login": (10, 60, 0),
    "agent.invoke": (60, 60, 10),
    "import.upload": (30, 60, 5),
    "import.commit": (20, 60, 5),
    "recognition.create": (60, 60, 10),
    "bi.query": (120, 60, 20),
    "workflow.run.start": (60, 60, 10),
    "model.switch": (10, 60, 0),
    "url.download": (60, 60, 10),
}


class RateLimiter:
    def __init__(self, store: Any) -> None:
        self.store = store
        conn = store._conn
        for cap, (mx, win, burst) in DEFAULT_RULES.items():
            conn.execute(
                "INSERT OR IGNORE INTO rate_limit_rule_v1 (capability,"
                " max_per_window, window_seconds, burst, enabled,"
                " updated_by, updated_at) VALUES (?,?,?,?,1,'system',"
                " datetime('now'))", (cap, mx, win, burst))
        conn.commit()

    # ---------- 规则 ----------

    def get_rule(self, capability: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM rate_limit_rule_v1 WHERE capability=?",
            (capability,)).fetchone()
        return dict(row) if row else None

    def list_rules(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM rate_limit_rule_v1 ORDER BY capability"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["hits_total"] = self._hits(d["capability"])
            out.append(d)
        return out

    def set_rule(self, capability: str, *, max_per_window: int,
                 window_seconds: int, burst: int = 0,
                 enabled: bool = True, actor: str) -> dict:
        if max_per_window < 1 or window_seconds < 1:
            raise ValueError("max_per_window/window_seconds 必须 ≥1")
        self.store._conn.execute(
            "INSERT INTO rate_limit_rule_v1 (capability, max_per_window,"
            " window_seconds, burst, enabled, updated_by, updated_at)"
            " VALUES (?,?,?,?,?,?,datetime('now'))"
            " ON CONFLICT(capability) DO UPDATE SET"
            " max_per_window=excluded.max_per_window,"
            " window_seconds=excluded.window_seconds,"
            " burst=excluded.burst, enabled=excluded.enabled,"
            " updated_by=excluded.updated_by,"
            " updated_at=excluded.updated_at",
            (capability, max_per_window, window_seconds, burst,
             1 if enabled else 0, actor))
        self.store._conn.commit()
        try:
            self.store._conn.execute(
                "INSERT INTO iam_audit_event_v1 (occurred_at, actor_id,"
                " action, resource, detail_json, customer_id)"
                " VALUES (datetime('now'),?,?,?,?,'')",
                (actor, "rate_limit.rule.updated", capability,
                 f'{{"max":{max_per_window},"window":{window_seconds},'
                 f'"burst":{burst},"enabled":{enabled}}}'))
            self.store._conn.commit()
        except Exception:
            pass  # 审计表缺失不阻断规则更新
        return self.get_rule(capability) or {}

    def _hits(self, capability: str) -> int:
        row = self.store._conn.execute(
            "SELECT sum(count) s FROM rate_limit_v1 WHERE key LIKE ?",
            (capability + "|%",)).fetchone()
        return int(row["s"] or 0) if row else 0

    # ---------- 判定 ----------

    def check(self, capability: str, subject: str,
              ip: str = "") -> tuple[bool, float, int]:
        """返回 (allowed, retry_after_seconds, current_count)。"""
        rule = self.get_rule(capability)
        if rule is None or not rule["enabled"]:
            return True, 0.0, 0
        win = int(rule["window_seconds"])
        limit = int(rule["max_per_window"]) + int(rule["burst"])
        now = time.time()
        bucket = int(now // win)
        key = f"{capability}|{subject or 'anon'}|{ip or '-'}"
        conn = self.store._conn
        conn.execute(
            "INSERT INTO rate_limit_v1 (key, window_start, count)"
            " VALUES (?,?,1) ON CONFLICT(key, window_start) DO UPDATE"
            " SET count=count+1", (key, str(bucket)))
        conn.commit()
        row = conn.execute(
            "SELECT count FROM rate_limit_v1 WHERE key=? AND"
            " window_start=?", (key, str(bucket))).fetchone()
        count = int(row["count"]) if row else 1
        if count > limit:
            retry_after = max(0.5, (bucket + 1) * win - now)
            self._audit_deny(capability, subject, ip, retry_after)
            return False, retry_after, count
        return True, 0.0, count

    def _audit_deny(self, capability: str, subject: str, ip: str,
                    retry_after: float) -> None:
        try:
            self.store.emit_event(
                event_id="evt-rl-" + str(time.time_ns()),
                event_type="rate_limit.denied",
                actor_type="human", actor_id=subject or "anon",
                subject_type="capability", subject_id=capability,
                payload={"ip": ip, "retry_after": round(retry_after, 2)})
        except Exception:
            pass  # 审计事件失败不阻断限流本身
