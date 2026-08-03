"""平台编排 API（:8304）：统一管理数据集、照片导入、识别/训练任务、结果下载、模型切换。

端点：
  数据集（LS 项目）
    GET    /datasets                      列出数据集
    POST   /datasets                      创建数据集 {title}
    DELETE /datasets/{id}                 删除数据集
    POST   /datasets/{id}/import          导入照片 {limit, with_predictions}
    GET    /datasets/{id}/export?format=  导出标注 yolo|json
  任务
    POST   /jobs/recognize                发起识别 {asset_ids?, conf?, limit?}
    POST   /jobs/train                    发起训练 {dataset_yaml?, epochs, batch, model}
    GET    /jobs                          任务列表 {kind?}
    GET    /jobs/{id}                     任务状态
    GET    /jobs/{id}/result?format=      下载结果 json|xlsx
  模型
    GET    /models                        模型列表
    POST   /models/switch                 切换生产模型 {model_version_id}
  健康
    GET    /health

用法：python -m src.ls_platform.orchestrator --port 8304"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from . import jobs, task_runners, webhook
from .exporter import export_yolo
from .importer import import_photos
from .ls_client import LSClient

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "label-studio" / "label_config.xml"
DASHBOARD_HTML = Path(__file__).resolve().parents[2] / "src" / "recognize" / "dashboard.html"
TRAINING_DATA = Path(__file__).resolve().parents[2] / ".training_data"

# ISSUE-011：写接口需要管理 token；未设置时仅本机回环可用（服务默认监听 127.0.0.1）
WRITE_PATHS_EXACT = {"/retrain", "/webhook/ls", "/models/switch", "/datasets"}
WRITE_PREFIXES = ("/jobs/", "/datasets/")  # /datasets/{id}/import|accept-predictions|export, /jobs/*
# CORS 白名单：只允许本机监控/工作台前端（ISSUE-011）
ALLOWED_ORIGINS = {
    "http://127.0.0.1:8090", "http://localhost:8090",
    "http://127.0.0.1:8092", "http://localhost:8092",
    "http://127.0.0.1:8304", "http://localhost:8304",
}


def _list_photos(limit=200):
    man = json.loads((TRAINING_DATA / "manifest.json").read_text(encoding="utf-8"))
    photos = man["photos"]
    out = []
    for k, p in list(photos.items())[:limit]:
        meta = p.get("meta", {})
        out.append({"id": k, "sname": meta.get("sname", ""), "typename": meta.get("typename", "")})
    return out


def _photo_bytes(asset_id):
    man = json.loads((TRAINING_DATA / "manifest.json").read_text(encoding="utf-8"))
    p = man["photos"].get(asset_id)
    if not p:
        return None
    sha = (p.get("image") or {}).get("sha256")
    if not sha:
        return None
    bp = TRAINING_DATA / "blobs" / sha[:2] / sha
    return bp.read_bytes() if bp.exists() else None


def _models_list():
    from ..data import warehouse as wh
    conn = wh.connect()
    wh.migrate(conn)
    rows = conn.execute(
        "SELECT mv_id, task, status, metrics_json, weight_uri, created_at FROM model_version ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [{"mv_id": r[0], "task": r[1], "status": r[2],
             "metrics": json.loads(r[3]) if r[3] else {}, "weight": r[4], "created_at": r[5]} for r in rows]


def _model_switch(mv_id: str):
    """ISSUE-005：单事务切换 production（旧版本下线），委托识别服务的实现。"""
    from ..recognize.service import switch_production
    try:
        return switch_production(mv_id)["switched_to"]
    except ValueError:
        return None


def _notify_recognize_reload() -> dict:
    """切换后通知识别进程重载模型包，保证 DB 状态与实际加载一致（ISSUE-005）。"""
    import urllib.request
    try:
        req = urllib.request.Request("http://127.0.0.1:8091/v2/admin/reload", method="POST",
                                     data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class H(BaseHTTPRequestHandler):
    MAX_BODY = 32 * 1024 * 1024

    def log_message(self, *a):
        pass

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        # ISSUE-011：通配 CORS → 白名单
        if origin in ALLOWED_ORIGINS:
            return origin
        return None

    def _send(self, code, body, ct="application/json; charset=utf-8"):
        d = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(d)))
        origin = self._cors_headers()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(d)

    def _raw_body(self) -> bytes:
        n = int(self.headers.get("Content-Length", 0))
        if n > self.MAX_BODY:
            raise ValueError("payload too large")
        return self.rfile.read(n) if n else b""

    def _json(self):
        raw = self._raw_body()
        self._last_raw_body = raw
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _write_authorized(self, path: str) -> bool:
        """ISSUE-011：写接口鉴权。设置 ORCHESTRATOR_ADMIN_TOKEN 时强制 Bearer；
        未设置时仅允许本机回环连接（服务默认绑定 127.0.0.1）。"""
        token = os.environ.get("ORCHESTRATOR_ADMIN_TOKEN", "")
        if token:
            auth = self.headers.get("Authorization", "")
            return auth == f"Bearer {token}"
        client = self.client_address[0] if self.client_address else ""
        return client in ("127.0.0.1", "::1", "localhost")

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        if origin not in ALLOWED_ORIGINS:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)
        try:
            if path == "/health":
                return self._send(200, json.dumps({"ok": True, "service": "orchestrator"}))

            if path in ("/dashboard", "/"):
                return self._send(200, DASHBOARD_HTML.read_text(encoding="utf-8"), "text/html; charset=utf-8")

            if path == "/recognize/health":
                from ..data import warehouse as wh
                conn = wh.connect(); wh.migrate(conn)
                row = conn.execute("SELECT mv_id FROM model_version WHERE status IN ('production','trained') ORDER BY created_at DESC LIMIT 1").fetchone()
                conn.close()
                return self._send(200, json.dumps({"ok": True, "model": row[0] if row else "sku_v1"}))

            if path == "/recognize/photos":
                return self._send(200, json.dumps({"photos": _list_photos()}, ensure_ascii=False))

            if path.startswith("/recognize/photo/"):
                asset_id = path.split("/")[-1]
                b = _photo_bytes(asset_id)
                if not b:
                    return self._send(404, '{"error":"photo not found"}')
                ct = "image/jpeg" if b[:3] == b"\xff\xd8\xff" else "image/png"
                return self._send(200, b, ct)

            if path == "/datasets":
                client = LSClient()
                projects = client.list_projects()
                out = [{"id": p["id"], "title": p.get("title"), "task_number": p.get("task_number"),
                        "description": p.get("description", "")} for p in projects]
                return self._send(200, json.dumps({"datasets": out}, ensure_ascii=False))

            if path == "/jobs":
                kind = qs.get("kind", [None])[0]
                return self._send(200, json.dumps({"jobs": jobs.list_jobs(kind)}, ensure_ascii=False))

            if path.startswith("/jobs/") and path.endswith("/result"):
                job_id = path.split("/")[2]
                fmt = qs.get("format", ["json"])[0]
                if fmt == "xlsx":
                    xp = jobs.RESULTS_DIR / f"{job_id}.xlsx"
                    if not xp.exists():
                        return self._send(404, '{"error":"xlsx not ready"}')
                    data = xp.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    self.send_header("Content-Disposition", f'attachment; filename="{job_id}.xlsx"')
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                result = jobs.load_result(job_id)
                if result is None:
                    return self._send(404, '{"error":"result not found"}')
                return self._send(200, json.dumps(result, ensure_ascii=False))

            if path.startswith("/jobs/"):
                job_id = path.split("/")[2]
                job = jobs.get_job(job_id)
                if not job:
                    return self._send(404, '{"error":"job not found"}')
                return self._send(200, json.dumps(job, ensure_ascii=False))

            if path == "/models":
                return self._send(200, json.dumps({"models": _models_list()}, ensure_ascii=False))

            if path.startswith("/datasets/") and path.endswith("/export"):
                pid = int(path.split("/")[2])
                fmt = qs.get("format", ["json"])[0]
                if fmt == "yolo":
                    out_name = qs.get("out", [f"ls_{pid}"])[0]
                    summary = export_yolo(project_id=pid, out_name=out_name)
                    return self._send(200, json.dumps(summary, ensure_ascii=False))
                client = LSClient()
                data = client.export(pid, "JSON")
                return self._send(200, json.dumps({"tasks": data}, ensure_ascii=False))

            self._send(404, '{"error":"not found"}')
        except Exception as e:
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            # ISSUE-011：写接口鉴权（dashboard 识别入口 /recognize/run 为只读推理，同样要求本机/token）
            is_write = path in WRITE_PATHS_EXACT or path.startswith(WRITE_PREFIXES) or path == "/recognize/run"
            if is_write and not self._write_authorized(path):
                return self._send(401, '{"error":"unauthorized: need Bearer token or loopback"}')
            body = self._json()

            if path == "/recognize/run":
                import base64 as _b64
                import time as _t
                from ..recognize.service import detect_and_recognize, OverloadedError
                conf = body.get("conf", 0.25)
                if "image_base64" in body:
                    img = _b64.b64decode(body["image_base64"])
                elif "asset_id" in body:
                    img = _photo_bytes(body["asset_id"])
                    if not img:
                        return self._send(404, '{"error":"asset not found"}')
                else:
                    return self._send(400, '{"error":"need image_base64 or asset_id"}')
                t0 = _t.time()
                try:
                    products = detect_and_recognize(img, conf=conf)
                except OverloadedError as e:
                    # RA-016：背压拒绝 → 429，客户端可重试
                    return self._send(429, json.dumps({"error": "OVERLOADED", "detail": str(e)}, ensure_ascii=False))
                elapsed = _t.time() - t0
                # ISSUE-007：dashboard 入口也必须写审计
                import uuid as _uuid
                from ..recognize.service import _write_audit
                _write_audit(str(_uuid.uuid4()), body.get("asset_id"),
                             {"source": "orchestrator_dashboard"}, products)
                return self._send(200, json.dumps({"products": products, "count": len(products), "elapsed_ms": round(elapsed*1000)}, ensure_ascii=False))

            if path == "/datasets":
                client = LSClient()
                title = body.get("title", "未命名数据集")
                cfg = CONFIG_PATH.read_text(encoding="utf-8")
                proj = client.create_project(title, cfg, body.get("description", ""))
                return self._send(201, json.dumps({"id": proj["id"], "title": proj.get("title")}, ensure_ascii=False))

            if path.startswith("/datasets/") and path.endswith("/import"):
                pid = int(path.split("/")[2])
                limit = body.get("limit", 0)
                with_pred = body.get("with_predictions", True)
                summary = import_photos(limit=limit, with_predictions=with_pred, project_id=pid)
                return self._send(200, json.dumps(summary, ensure_ascii=False))

            if path == "/jobs/recognize":
                job_id = jobs.create_job("recognize", body)
                jobs.run_in_thread(
                    lambda jid, upd: task_runners.recognize_job(
                        jid, upd, asset_ids=body.get("asset_ids"),
                        conf=body.get("conf", 0.25), limit=body.get("limit")),
                    job_id)
                return self._send(202, json.dumps({"job_id": job_id, "status": "pending"}))

            if path == "/jobs/train":
                # ISSUE-001：训练任务必须显式指定数据集
                if not body.get("dataset_yaml"):
                    return self._send(400, '{"error":"dataset_yaml 必填（禁止隐式默认数据集）"}')
                job_id = jobs.create_job("train", body)
                jobs.run_in_thread(
                    lambda jid, upd: task_runners.train_job(
                        jid, upd, dataset_yaml=body.get("dataset_yaml"),
                        epochs=body.get("epochs", 80), batch=body.get("batch", 8),
                        imgsz=body.get("imgsz", 640), model=body.get("model", "yolo26m.pt")),
                    job_id)
                return self._send(202, json.dumps({"job_id": job_id, "status": "pending"}))

            if path == "/retrain":
                # 再训练闭环：导出LS审核标注 → 训练 → 热切换
                pid = body.get("project_id") or int(__import__("os").environ.get("LABEL_STUDIO_PROJECT_ID", "1"))
                job_id = jobs.create_job("retrain", body)
                jobs.run_in_thread(
                    lambda jid, upd: task_runners.retrain_job(
                        jid, upd, project_id=pid, out_name=body.get("out_name", "ls_retrain"),
                        epochs=body.get("epochs", 80), batch=body.get("batch", 8),
                        imgsz=body.get("imgsz", 640), model=body.get("model", "yolo26m.pt"),
                        auto_switch=body.get("auto_switch", True)),
                    job_id)
                return self._send(202, json.dumps({"job_id": job_id, "status": "pending", "project_id": pid}))

            if path == "/webhook/ls":
                # LS 审核/标注事件 → warehouse 审计双写
                # ISSUE-014：传递原始 body + HMAC 签名头，支持验签与幂等
                status_code, result = webhook.handle_event(
                    body,
                    signature=self.headers.get("X-Label-Studio-HMAC-SHA256"),
                    raw_body=getattr(self, "_last_raw_body", b""),
                )
                return self._send(status_code, json.dumps(result, ensure_ascii=False))

            if path.startswith("/datasets/") and path.endswith("/accept-predictions"):
                # ISSUE-004：移除“未提供 task_ids 就全量接受”行为；
                # 必须显式任务列表 + confirm 确认参数，逐 task 记录审计
                pid = int(path.split("/")[2])
                task_ids = body.get("task_ids")
                if not task_ids or not isinstance(task_ids, list):
                    return self._send(400, '{"error":"必须显式提供 task_ids 列表（禁止全量盲接受）"}')
                if not body.get("confirm"):
                    return self._send(400, '{"error":"需 confirm=true 确认接受预测为标注（人工门动作）"}')
                reviewer = body.get("reviewer") or body.get("user") or ""
                if not reviewer:
                    return self._send(400, '{"error":"需 reviewer 字段记录真实接受人"}')
                client = LSClient()
                accepted = 0
                for tid in task_ids:
                    rt = client.s.get(f"{client.url}/api/tasks/{tid}", params={"include": "predictions"}, timeout=60).json()
                    preds = rt.get("predictions", [])
                    if not preds:
                        continue
                    pred = sorted(preds, key=lambda p: p.get("score", 0), reverse=True)[0]
                    ra = client.s.post(f"{client.url}/api/tasks/{tid}/annotations/",
                                       json={"result": pred["result"], "was_cancelled": False}, timeout=60)
                    if ra.status_code < 400:
                        accepted += 1
                        # 审计：记录接受动作、原 prediction、接受人（ISSUE-004）
                        try:
                            from ..data import warehouse as wh
                            conn = wh.connect()
                            wh.migrate(conn)
                            wh.add_review_event(
                                conn, asset_id=f"ls_task_{tid}", reviewer=str(reviewer),
                                status="prediction_accepted",
                                before={"prediction_id": pred.get("id"), "model_version": pred.get("model_version")},
                                after={"project": pid, "accepted_by": reviewer})
                            conn.close()
                        except Exception:
                            pass
                return self._send(200, json.dumps({"accepted": accepted, "tasks": len(task_ids)}, ensure_ascii=False))

            if path == "/models/switch":
                mv_id = body.get("model_version_id")
                if not mv_id:
                    return self._send(400, '{"error":"need model_version_id"}')
                r = _model_switch(mv_id)
                if not r:
                    return self._send(404, '{"error":"model not found or weight missing"}')
                # ISSUE-005：切换后刷新识别进程缓存的模型
                reload_r = _notify_recognize_reload()
                return self._send(200, json.dumps({"ok": True, "switched_to": mv_id, "reload": reload_r}, ensure_ascii=False))

            self._send(404, '{"error":"not found"}')
        except Exception as e:
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            if not self._write_authorized(path):
                return self._send(401, '{"error":"unauthorized"}')
            if path.startswith("/datasets/"):
                # ISSUE-011：删除需二次确认参数 + 审计
                qs = parse_qs(urlparse(self.path).query)
                if qs.get("confirm", [""])[0] != "DELETE":
                    return self._send(400, '{"error":"需要 ?confirm=DELETE 二次确认"}')
                pid = int(path.split("/")[2])
                client = LSClient()
                client.delete_project(pid)
                try:
                    from ..data import warehouse as wh
                    conn = wh.connect()
                    wh.migrate(conn)
                    wh.add_review_event(conn, asset_id=f"ls_project_{pid}",
                                        reviewer="orchestrator", status="project_deleted",
                                        after={"action": "delete_dataset"})
                    conn.close()
                except Exception:
                    pass
                return self._send(200, json.dumps({"ok": True, "deleted": pid}))
            self._send(404, '{"error":"not found"}')
        except Exception as e:
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


def serve(host="127.0.0.1", port=8304):
    s = ThreadingHTTPServer((host, port), H)
    print(f"平台编排 API http://{host}:{port}")
    print(f"  数据集/任务/识别/训练/模型 统一入口")
    s.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8304)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    serve(a.host, a.port)
