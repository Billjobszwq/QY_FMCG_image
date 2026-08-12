"""ABOSV3 T2：首页总控服务（01 文档 §2：首页八类真实卡片）。

- 日历：统一读取模型（D-004）= 用户日程 + WorkItem 截止 + 外勤任务
  + 问卷分配窗口；私人日程专表且产生审计，不得只存 localStorage；
- 活动日志：EventEnvelope + IAM Audit 的业务友好投影（不展示噪声）；
- 进度：按客户/项目聚合 WorkItem/Run 状态（同一 current projection）；
- 系统容量：数据库/磁盘/队列/服务真实读数；
- Agent 提醒：待批准/阻断/异常（来自统一事实，不硬编码）；
- 便签：服务端持久化（关闭 ABOSV2-P2-001）。
- SI2 T4：首页全部卡片默认 scope=operational；fixture 只在测试与
  证据中心可见（统一 ScopedQuery 口径，不散落临时 SQL）。
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any

from .scope import OPERATIONAL_FILTER


class HomeCenterError(Exception):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# 业务友好事件文案（活动日志只投影业务事件，过滤内部噪声）
_EVENT_TEXT = {
    "command.accepted": "命令已受理",
    "run.succeeded": "运行成功",
    "run.failed": "运行失败",
    "run.cancelled": "运行已取消",
    "run.retried": "运行重试",
    "run.waiting_human": "等待人工处理",
    "workflow.started": "工作流启动",
    "workflow.succeeded": "工作流完成",
    "workflow.failed": "工作流失败",
    "workflow.retried": "工作流重试",
    "human_approval.decided": "人工批准已决定",
    "survey.suggestion.reviewed": "识别建议已人工复核",
}


class HomeCenterService:
    def __init__(self, store: Any) -> None:
        self.store = store

    # ---------- 日历（统一读取模型） ----------

    def calendar_events(self, *, start: str = "", end: str = "",
                        actor: str = "") -> list[dict]:
        conn = self.store._conn
        out: list[dict] = []
        # 1) 用户日程（专表，服务端持久化；SI2：默认只看 operational）
        rows = conn.execute(
            "SELECT * FROM user_calendar_v1 WHERE " + OPERATIONAL_FILTER
            + " ORDER BY starts_at").fetchall()
        for r in rows:
            d = dict(r)
            d["all_day"] = bool(d.get("all_day"))
            out.append({**d, "source": "user",
                        "when": d["starts_at"]})
        # 2) WorkItem 截止（work_item_v2 即 current 投影表，同源）
        self.store.rebuild_work_projection()
        for it in self.store.list_work_items_v2():
            if it.get("due_at") and it["status"] not in (
                    "done", "cancelled"):
                out.append({"event_id": f"due-{it['work_id']}",
                            "title": it.get("title") or it["work_id"],
                            "kind": "work_due", "source": "work",
                            "starts_at": it["due_at"],
                            "when": it["due_at"],
                            "ref_type": "work_item",
                            "ref_id": it["work_id"],
                            "customer_id": it.get("customer_id", ""),
                            "project_id": it.get("project_id", "")})
        # 3) 外勤任务（未完成的派发）
        try:
            tasks = conn.execute(
                "SELECT * FROM field_task_v1 WHERE status NOT IN"
                " ('completed','cancelled') AND " + OPERATIONAL_FILTER
                + " ORDER BY created_at"
                ).fetchall()
            for r in tasks:
                d = dict(r)
                out.append({"event_id": f"field-{d['task_id']}",
                            "title": f"外勤任务：{d['kind']}"
                                     f"（{d['status']}）",
                            "kind": "field_task", "source": "field",
                            "starts_at": d["created_at"],
                            "when": d["created_at"],
                            "ref_type": "field_task",
                            "ref_id": d["task_id"],
                            "customer_id": d.get("customer_id", ""),
                            "project_id": d.get("project_id", "")})
        except Exception:
            pass
        # 4) 问卷分配（进行中的填写窗口）
        try:
            asgs = conn.execute(
                "SELECT * FROM survey_assignment_v1 WHERE status IN"
                " ('assigned','in_progress') AND " + OPERATIONAL_FILTER
                + " ORDER BY created_at"
                ).fetchall()
            for r in asgs:
                d = dict(r)
                out.append({"event_id": f"survey-{d['assignment_id']}",
                            "title": f"问卷填写：{d['survey_id'][:18]}"
                                     f"（{d['status']}）",
                            "kind": "survey_window", "source": "survey",
                            "starts_at": d["created_at"],
                            "when": d["created_at"],
                            "ref_type": "survey_assignment",
                            "ref_id": d["assignment_id"],
                            "customer_id": d.get("customer_id", ""),
                            "project_id": d.get("project_id", "")})
        except Exception:
            pass
        if start:
            out = [e for e in out if (e.get("when") or "") >= start]
        if end:
            out = [e for e in out if (e.get("when") or "") <= end]
        return sorted(out, key=lambda e: e.get("when") or "")

    def add_event(self, *, actor: str, title: str, starts_at: str,
                  ends_at: str = "", all_day: bool = False,
                  location: str = "", kind: str = "user",
                  ref_type: str = "", ref_id: str = "",
                  customer_id: str = "", project_id: str = "") -> dict:
        if not title or not starts_at:
            raise HomeCenterError("title/starts_at 必填")
        if kind not in ("user", "meeting", "reminder"):
            raise HomeCenterError(f"日程类型不支持: {kind}")
        eid = _new_id("cal")
        self.store._conn.execute(
            "INSERT INTO user_calendar_v1 (event_id, actor, title, kind,"
            " starts_at, ends_at, all_day, location, ref_type, ref_id,"
            " customer_id, project_id, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, actor, title, kind, starts_at, ends_at or None,
             1 if all_day else 0, location, ref_type, ref_id,
             customer_id, project_id, actor, _now(), _now()))
        self.store._conn.commit()
        try:  # 日程是业务事实：写审计（D-004）
            self.store._conn.execute(
                "INSERT INTO iam_audit_event_v1 (occurred_at, actor_id,"
                " action, resource, detail_json, customer_id)"
                " VALUES (?,?,?,?,?,?)",
                (_now(), actor, "calendar.event.created",
                 f"calendar:{eid}",
                 json.dumps({"title": title, "starts_at": starts_at},
                            ensure_ascii=False), customer_id))
            self.store._conn.commit()
        except Exception:
            pass
        return self.get_event(eid)

    def get_event(self, event_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM user_calendar_v1 WHERE event_id=?",
            (event_id,)).fetchone()
        return dict(row) if row else None

    def delete_event(self, event_id: str, *, actor: str) -> None:
        e = self.get_event(event_id)
        if e is None:
            raise HomeCenterError(f"日程不存在: {event_id}")
        if e["kind"] not in ("user", "meeting", "reminder"):
            raise HomeCenterError("系统事件（外勤/问卷/截止）不可删除，"
                                  "请在对应模块处理")
        self.store._conn.execute(
            "DELETE FROM user_calendar_v1 WHERE event_id=?", (event_id,))
        self.store._conn.commit()

    # ---------- 活动日志（业务友好投影） ----------

    def activity(self, *, limit: int = 60) -> list[dict]:
        out: list[dict] = []
        # SI2：fixture run 的事件不进运营活动日志（scope 来自 run 行）
        _fixture_runs = {r["run_id"] for r in self.store._conn.execute(
            "SELECT run_id FROM business_run_v1 WHERE data_scope IN"
            " ('uat_fixture','demo_fixture')")}
        events = self.store.list_events()
        for e in reversed(events):  # 最新在前
            t = e.get("event_type", "")
            if t in ("node.started", "node.completed"):
                continue  # 节点级噪声不进业务日志
            if e.get("run_id") in _fixture_runs:
                continue
            text = _EVENT_TEXT.get(t)
            if text is None and not any(
                    t.startswith(p) for p in ("survey.", "geo.",
                                              "finance.", "iam.")):
                continue
            payload = e.get("payload_json") or e.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            out.append({
                "seq": e.get("seq"), "type": t,
                "text": text or t,
                "at": e.get("occurred_at", ""),
                "run_id": e.get("run_id", ""),
                "work_id": e.get("work_id", ""),
                "actor": e.get("actor_id", ""),
                "subject_type": e.get("subject_type", ""),
                "subject_id": e.get("subject_id", ""),
                "error": (payload.get("error") or "")[:200],
            })
            if len(out) >= limit:
                break
        return out

    # ---------- 项目进度（同一 current projection） ----------

    def progress(self) -> dict[str, Any]:
        proj = self.store.rebuild_work_projection()
        by_project: dict[str, dict] = {}
        for it in proj["items"]:
            key = it.get("project_id") or it.get("customer_id") \
                or "（未归属）"
            p = by_project.setdefault(key, {
                "project_id": it.get("project_id", ""),
                "customer_id": it.get("customer_id", ""),
                "total": 0, "done": 0, "running": 0, "blocked": 0,
                "waiting": 0})
            p["total"] += 1
            if it["status"] == "done":
                p["done"] += 1
            elif it["status"] in ("running", "todo"):
                p["running"] += 1
            elif it["status"] == "blocked":
                p["blocked"] += 1
            elif it["status"] == "waiting":
                p["waiting"] += 1
        for p in by_project.values():
            p["completion"] = round(
                p["done"] / p["total"] * 100, 1) if p["total"] else 0.0
        runs = self.store._conn.execute(
            "SELECT status, count(*) c FROM business_run_v1"
            " GROUP BY status").fetchall()
        return {"projects": sorted(by_project.values(),
                                   key=lambda x: -x["total"]),
                "runs_by_status": {r["status"]: r["c"] for r in runs},
                "work_total": len(proj["items"])}

    # ---------- 便签（服务端持久化） ----------

    def list_notes(self, *, actor: str = "") -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM user_note_v1 ORDER BY pinned DESC, updated_at"
            " DESC LIMIT 100").fetchall()
        return [dict(r) for r in rows]

    def add_note(self, *, actor: str, content: str,
                 pinned: bool = False) -> dict:
        if not content.strip():
            raise HomeCenterError("便签内容不得为空")
        nid = _new_id("note")
        self.store._conn.execute(
            "INSERT INTO user_note_v1 (note_id, actor, content, pinned,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (nid, actor, content.strip()[:2000], 1 if pinned else 0,
             _now(), _now()))
        self.store._conn.commit()
        return self.get_note(nid)

    def get_note(self, note_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM user_note_v1 WHERE note_id=?",
            (note_id,)).fetchone()
        return dict(row) if row else None

    def update_note(self, note_id: str, *, content: str | None = None,
                    pinned: bool | None = None) -> dict:
        n = self.get_note(note_id)
        if n is None:
            raise HomeCenterError(f"便签不存在: {note_id}")
        if content is not None:
            if not content.strip():
                raise HomeCenterError("便签内容不得为空")
            self.store._conn.execute(
                "UPDATE user_note_v1 SET content=?, updated_at=?"
                " WHERE note_id=?",
                (content.strip()[:2000], _now(), note_id))
        if pinned is not None:
            self.store._conn.execute(
                "UPDATE user_note_v1 SET pinned=?, updated_at=?"
                " WHERE note_id=?",
                (1 if pinned else 0, _now(), note_id))
        self.store._conn.commit()
        return self.get_note(note_id)

    def delete_note(self, note_id: str) -> None:
        if self.get_note(note_id) is None:
            raise HomeCenterError(f"便签不存在: {note_id}")
        self.store._conn.execute(
            "DELETE FROM user_note_v1 WHERE note_id=?", (note_id,))
        self.store._conn.commit()

    # ---------- Agent 提醒（真实待办，不硬编码） ----------

    def agent_alerts(self) -> list[dict]:
        alerts: list[dict] = []
        proj = self.store.rebuild_work_projection()
        for it in proj["items"]:
            if it["status"] == "waiting":
                alerts.append({"kind": "needs_decision",
                               "title": it.get("title") or it["work_id"],
                               "ref_type": "work_item",
                               "ref_id": it["work_id"]})
            elif it["status"] == "blocked":
                alerts.append({"kind": "blocked",
                               "title": it.get("title") or it["work_id"],
                               "blockers": it.get("blockers", []),
                               "ref_type": "work_item",
                               "ref_id": it["work_id"]})
        try:
            rows = self.store._conn.execute(
                "SELECT anomaly_id, metric_id, observed, threshold"
                " FROM bi_anomaly_v1 WHERE status='open' AND "
                + OPERATIONAL_FILTER).fetchall()
            for r in rows:
                alerts.append({"kind": "anomaly",
                               "title": f"指标异常：{r['metric_id']}"
                                        f"（observed={r['observed']}）",
                               "ref_type": "bi_anomaly",
                               "ref_id": r["anomaly_id"]})
        except Exception:
            pass
        return alerts

    # ---------- 系统容量（真实读数） ----------

    def capacity(self) -> dict[str, Any]:
        db_path = self.store._path
        db_size = db_path.stat().st_size if db_path.exists() else 0
        wal = db_path.with_name(db_path.name + "-wal")
        db_size += wal.stat().st_size if wal.exists() else 0
        tables = self.store._conn.execute(
            "SELECT count(*) c FROM sqlite_master WHERE type='table'"
            ).fetchone()["c"]
        platform_dir = db_path.parent
        dir_size = 0
        try:
            for root, _dirs, files in os.walk(platform_dir):
                for f in files:
                    try:
                        dir_size += os.path.getsize(
                            os.path.join(root, f))
                    except OSError:
                        pass
        except OSError:
            pass
        try:
            disk = shutil.disk_usage(str(db_path))
            disk_info = {"total_gb": round(disk.total / 2**30, 1),
                         "used_gb": round(disk.used / 2**30, 1),
                         "free_gb": round(disk.free / 2**30, 1)}
        except OSError:
            disk_info = {}
        pending_outbox = self.store._conn.execute(
            "SELECT count(*) c FROM outbox_v1 WHERE status='pending'"
            ).fetchone()["c"]
        jobs = {"queued": 0, "running": 0, "failed": 0}
        try:
            for r in self.store._conn.execute(
                    "SELECT status, count(*) c FROM job WHERE status"
                    " IN ('queued','running','failed')"
                    " GROUP BY status").fetchall():
                jobs[r["status"]] = r["c"]
        except Exception:
            pass
        return {"db_bytes": db_size, "tables": tables,
                "platform_dir_bytes": dir_size, "disk": disk_info,
                "outbox_pending": pending_outbox, "jobs": jobs,
                "migrations": self.store._conn.execute(
                    "SELECT count(*) c FROM schema_migrations"
                ).fetchone()["c"]}

    # ---------- 最近对象（点击直达同一对象） ----------

    def recent_objects(self, *, limit: int = 5) -> dict[str, list]:
        conn = self.store._conn
        out: dict[str, list] = {}

        def _q(table: str, id_col: str, extra: str = "") -> list[dict]:
            # SI2：最近对象默认 operational（统一口径，不散落 SQL）
            try:
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE " + OPERATIONAL_FILTER
                    + f" ORDER BY created_at DESC"
                    f" LIMIT ?{extra}", (limit,)).fetchall()
                return [dict(r) for r in rows]
            except Exception:
                return []

        out["customers"] = [
            {"id": r["customer_id"], "name": r["name"]}
            for r in _q("md_customer_v1", "customer_id")]
        out["projects"] = [
            {"id": r["project_id"], "name": r["name"],
             "customer_id": r["customer_id"]}
            for r in _q("md_project_v1", "project_id")]
        out["surveys"] = [
            {"id": r["survey_id"], "name": r["name"],
             "status": r["status"], "version": r["version"]}
            for r in _q("survey_definition_v1", "survey_id")]
        out["workflows"] = [
            {"id": r["definition_id"], "name": r["name"],
             "status": r["status"], "version": r["version"]}
            for r in _q("workflow_definition_v1", "definition_id")]
        out["reports"] = [
            {"id": r["spec_id"], "name": r["name"],
             "status": r["status"], "version": r["version"]}
            for r in _q("bi_report_spec_v1", "spec_id")]
        try:
            rows = conn.execute(
                "SELECT task_id, status, created_at FROM"
                " recognition_task WHERE " + OPERATIONAL_FILTER
                + " ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
            out["recognition_tasks"] = [dict(r) for r in rows]
        except Exception:
            out["recognition_tasks"] = []
        return out
