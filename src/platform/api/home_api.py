"""ABOSV3 T2：首页总控 API（日历/日程/进度/活动/容量/便签/提醒）。

所有数据来自真实 Domain Service 投影；写操作需 session + CSRF。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..home_center import HomeCenterError, HomeCenterService


class CalendarEventBody(BaseModel):
    title: str
    starts_at: str
    ends_at: str = ""
    all_day: bool = False
    location: str = ""
    kind: str = "user"
    ref_type: str = ""
    ref_id: str = ""
    customer_id: str = ""
    project_id: str = ""


class NoteBody(BaseModel):
    content: str
    pinned: bool = False


class NoteUpdateBody(BaseModel):
    content: str | None = None
    pinned: bool | None = None


def create_home_router(store: Any, auth: AuthService | None,
                       probe: Any = None) -> APIRouter:
    router = APIRouter(tags=["home"])
    svc = HomeCenterService(store)

    @router.get("/api/v1/calendar/events")
    def calendar(request: Request, start: str = "", end: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        events = svc.calendar_events(start=start, end=end, actor=p["actor"])
        return {"count": len(events), "events": events}

    @router.post("/api/v1/calendar/events")
    def add_event(body: CalendarEventBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            ev = svc.add_event(actor=p["actor"], **body.model_dump())
        except HomeCenterError as e:
            raise HTTPException(409, str(e))
        return {"event": ev}

    @router.delete("/api/v1/calendar/events/{event_id}")
    def delete_event(event_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            svc.delete_event(event_id, actor=p["actor"])
        except HomeCenterError as e:
            raise HTTPException(409, str(e))
        return {"deleted": event_id}

    @router.get("/api/v1/activity")
    def activity(request: Request, limit: int = 60) -> dict:
        require_principal(auth, request, csrf=False)
        rows = svc.activity(limit=min(limit, 200))
        return {"count": len(rows), "events": rows}

    @router.get("/api/v1/progress")
    def progress(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        return svc.progress()

    @router.get("/api/v1/capacity")
    def capacity(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        cap = svc.capacity()
        if probe is not None:
            try:
                cap["services"] = probe()
            except Exception:
                cap["services"] = None
        return cap

    @router.get("/api/v1/notes")
    def list_notes(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        rows = svc.list_notes(actor=p["actor"])
        return {"count": len(rows), "notes": rows}

    @router.post("/api/v1/notes")
    def add_note(body: NoteBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"note": svc.add_note(actor=p["actor"],
                                         content=body.content,
                                         pinned=body.pinned)}
        except HomeCenterError as e:
            raise HTTPException(409, str(e))

    @router.put("/api/v1/notes/{note_id}")
    def update_note(note_id: str, body: NoteUpdateBody,
                    request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        try:
            return {"note": svc.update_note(note_id, content=body.content,
                                            pinned=body.pinned)}
        except HomeCenterError as e:
            raise HTTPException(409, str(e))

    @router.delete("/api/v1/notes/{note_id}")
    def delete_note(note_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        try:
            svc.delete_note(note_id)
        except HomeCenterError as e:
            raise HTTPException(409, str(e))
        return {"deleted": note_id}

    @router.get("/api/v1/home/agent-alerts")
    def agent_alerts(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        alerts = svc.agent_alerts()
        return {"count": len(alerts), "alerts": alerts}

    @router.get("/api/v1/home/recent")
    def recent(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        return svc.recent_objects()

    @router.get("/api/v1/home/dashboard")
    def dashboard(request: Request) -> dict:
        """首页聚合：待办/日历/进度/活动/容量/提醒/最近对象（全部真实）。"""
        p = require_principal(auth, request, csrf=False)
        proj = store.rebuild_work_projection()
        items = proj["items"]
        todos = {"todo": 0, "running": 0, "waiting": 0,
                 "blocked": 0, "done": 0, "cancelled": 0}
        for it in items:
            todos[it["status"]] = todos.get(it["status"], 0) + 1
        return {
            "actor": p["actor"],
            "todos": todos,
            "work_items": items[:50],
            "calendar": svc.calendar_events(actor=p["actor"])[:20],
            "progress": svc.progress(),
            "activity": svc.activity(limit=20),
            "capacity": svc.capacity(),
            "agent_alerts": svc.agent_alerts(),
            "recent": svc.recent_objects(),
            "notes": svc.list_notes(actor=p["actor"]),
        }

    return router
