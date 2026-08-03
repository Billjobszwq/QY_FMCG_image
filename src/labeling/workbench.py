"""标注工作台 + 人工审核 Web UI（零依赖，stdlib HTTP）。

功能：
- 标注工作台：双模式（A=从零标注 / B=种子辅助），任务分配，照片标注
- 人工审核：逐张审核提案，确认/改SKU/加框/删框，approved/rework/rejected
- 数据看板：进度统计，SKU 分布

用法：python -m src.labeling.workbench --port 8090"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

TRAINING_DATA = PROJECT_ROOT / ".training_data"
LABELS_DIR = PROJECT_ROOT / ".labels"
REGISTRY_PATH = PROJECT_ROOT / "data" / "sku_registry.json"
HTML_PATH = Path(__file__).parent / "workbench.html"

# 全局状态
_state = {}

# ISSUE-008：AssetId 统一为规范字符串；ISSUE-010：禁止路径穿越字符
_SAFE_PID_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,128}$")


def normalize_pid(value) -> str | None:
    """照片 ID 规范化：统一 str，拒绝空值/路径穿越/非法字符（ISSUE-008/010）。"""
    if value is None or isinstance(value, (dict, list)):
        return None
    pid = str(value).strip()
    if not pid or pid in (".", "..") or "/" in pid or "\\" in pid or "\x00" in pid:
        return None
    if not _SAFE_PID_RE.match(pid):
        return None
    return pid


def _validate_regions(regions, W, H, min_side=2) -> tuple[list, list]:
    """ISSUE-010：框坐标校验。返回 (合法 regions, 拒绝原因列表)。

    规则：四值均为有限数字；0<=x1<x2<=W；0<=y1<y2<=H；最小边达标。"""
    ok, rejects = [], []
    for i, r in enumerate(regions or []):
        box = r.get("box") if isinstance(r, dict) else None
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            rejects.append(f"region[{i}]: box 格式非法")
            continue
        x1, y1, x2, y2 = box
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x1, y1, x2, y2)):
            rejects.append(f"region[{i}]: 坐标含非法值(NaN/Infinity/非数字)")
            continue
        if not (0 <= x1 < x2 <= W) or not (0 <= y1 < y2 <= H):
            rejects.append(f"region[{i}]: 框越界或反向 ({x1},{y1},{x2},{y2})")
            continue
        if (x2 - x1) < min_side or (y2 - y1) < min_side:
            rejects.append(f"region[{i}]: 框过小")
            continue
        ok.append(r)
    return ok, rejects


def _load_state():
    global _state
    if _state.get("loaded"):
        return
    # 加载 SKU 注册表
    if REGISTRY_PATH.exists():
        _state["registry"] = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    else:
        _state["registry"] = {}
    # 加载训练数据 manifest
    manifest_path = TRAINING_DATA / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        _state["photos"] = m.get("photos", {})
    else:
        _state["photos"] = {}
    # 加载/初始化标注状态
    status_path = LABELS_DIR / "workbench_status.json"
    if status_path.exists():
        _state["status"] = json.loads(status_path.read_text(encoding="utf-8"))
    else:
        _state["status"] = {"tasks": {}, "reviews": {}}
    _state["loaded"] = True


def _save_status():
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    (LABELS_DIR / "workbench_status.json").write_text(
        json.dumps(_state["status"], ensure_ascii=False, indent=2), encoding="utf-8")


def _get_photo_list(mode=None, status=None, page=1, per_page=50):
    """获取照片列表，支持按模式/状态过滤。"""
    photos = _state.get("photos", {})
    tasks = _state["status"].get("tasks", {})
    result = []
    for pid, p in photos.items():
        img = p.get("image", {})
        if not img.get("ok"):
            continue
        task = tasks.get(pid, {})
        t_mode = task.get("mode")
        t_status = task.get("status", "pending")
        if mode and t_mode != mode:
            continue
        if status and t_status != status:
            continue
        result.append({
            "id": pid,
            "filename": p.get("filename", ""),
            "sname": p.get("meta", {}).get("sname", ""),
            "typename": p.get("meta", {}).get("typename", ""),
            "n_annotations": len(p.get("annotations", [])),
            "mode": t_mode,
            "status": t_status,
            "width": img.get("width"),
            "height": img.get("height"),
        })
    total = len(result)
    start = (page - 1) * per_page
    return {"total": total, "page": page, "per_page": per_page, "items": result[start:start + per_page]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ct="application/json; charset=utf-8"):
        d = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(d)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(d)

    def _json_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        _load_state()
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._send(200, HTML_PATH.read_text(encoding="utf-8"), "text/html; charset=utf-8")

        if path == "/api/stats":
            photos = _state.get("photos", {})
            tasks = _state["status"].get("tasks", {})
            reviews = _state["status"].get("reviews", {})
            ok_photos = sum(1 for p in photos.values() if p.get("image", {}).get("ok"))
            by_status = {}
            for pid in photos:
                s = tasks.get(pid, {}).get("status", "pending")
                by_status[s] = by_status.get(s, 0) + 1
            return self._send(200, json.dumps({
                "total_photos": len(photos),
                "downloaded": ok_photos,
                "registry_size": len(_state.get("registry", {})),
                "tasks_by_status": by_status,
                "reviews_total": len(reviews),
            }, ensure_ascii=False))

        if path == "/api/photos":
            mode = qs.get("mode", [None])[0]
            status = qs.get("status", [None])[0]
            page = int(qs.get("page", ["1"])[0])
            per_page = int(qs.get("per_page", ["50"])[0])
            return self._send(200, json.dumps(_get_photo_list(mode, status, page, per_page), ensure_ascii=False))

        if path.startswith("/api/photo/"):
            pid = path.split("/")[-1]
            photos = _state.get("photos", {})
            p = photos.get(pid)
            if not p:
                return self._send(404, '{"error":"not found"}')
            task = _state["status"].get("tasks", {}).get(pid, {})
            review = _state["status"].get("reviews", {}).get(pid)
            return self._send(200, json.dumps({
                "id": pid, "filename": p.get("filename"), "meta": p.get("meta"),
                "annotations": p.get("annotations", []),
                "image": p.get("image", {}),
                "task": task, "review": review,
                "registry_names": sorted(_state.get("registry", {}).keys()),
            }, ensure_ascii=False))

        if path.startswith("/img/"):
            pid = path.split("/")[-1]
            photos = _state.get("photos", {})
            p = photos.get(pid)
            if not p:
                return self._send(404, b"nf", "text/plain")
            img = p.get("image", {})
            sha = img.get("sha256")
            if not sha:
                return self._send(404, b"no image", "text/plain")
            bp = TRAINING_DATA / "blobs" / sha[:2] / sha
            if not bp.exists():
                # 回退到 .field/blobs
                bp = PROJECT_ROOT / ".field" / "blobs" / sha[:2] / sha
            if not bp.exists():
                return self._send(404, b"blob missing", "text/plain")
            b = bp.read_bytes()
            ct = "image/jpeg" if b[:3] == b"\xff\xd8\xff" else "image/png"
            return self._send(200, b, ct)

        if path == "/api/registry":
            return self._send(200, json.dumps(_state.get("registry", {}), ensure_ascii=False))

        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        _load_state()
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/task/assign":
            """分配标注任务：{photo_ids: [...], mode: "A"|"B", annotator: "..."}"""
            body = self._json_body()
            mode = body.get("mode", "B")
            annotator = body.get("annotator", "default")
            ids = body.get("photo_ids", [])
            tasks = _state["status"].setdefault("tasks", {})
            assigned = 0
            for pid in ids:
                if pid in _state.get("photos", {}):
                    tasks[pid] = {"mode": mode, "annotator": annotator, "status": "assigned", "assigned_at": time.time()}
                    assigned += 1
            _save_status()
            return self._send(200, json.dumps({"ok": True, "assigned": assigned, "mode": mode}))

        if path == "/api/task/auto_assign":
            """自动分配：按状态过滤未分配的照片，批量分配。"""
            body = self._json_body()
            mode = body.get("mode", "B")
            annotator = body.get("annotator", "default")
            count = int(body.get("count", 50))
            tasks = _state["status"].setdefault("tasks", {})
            photos = _state.get("photos", {})
            assigned = 0
            for pid, p in photos.items():
                if assigned >= count:
                    break
                if not p.get("image", {}).get("ok"):
                    continue
                if pid not in tasks or tasks[pid].get("status") == "pending":
                    tasks[pid] = {"mode": mode, "annotator": annotator, "status": "assigned", "assigned_at": time.time()}
                    assigned += 1
            _save_status()
            return self._send(200, json.dumps({"ok": True, "assigned": assigned, "mode": mode}))

        if path == "/api/annotation/save":
            """保存标注结果：{photo_id, regions: [{box, name, sku_id}], mode}"""
            body = self._json_body()
            pid = normalize_pid(body.get("photo_id"))
            regions = body.get("regions", [])
            tasks = _state["status"].setdefault("tasks", {})
            if pid is None or pid not in _state.get("photos", {}):
                return self._send(404, '{"error":"photo not found"}')
            # 保存标注
            LABELS_DIR.mkdir(parents=True, exist_ok=True)
            ann_dir = LABELS_DIR / "annotations"
            ann_dir.mkdir(exist_ok=True)
            ann_data = {"photo_id": pid, "regions": regions, "mode": body.get("mode"), "saved_at": time.time()}
            (ann_dir / f"{pid}.json").write_text(json.dumps(ann_data, ensure_ascii=False, indent=2), encoding="utf-8")
            # 更新任务状态
            if pid in tasks:
                tasks[pid]["status"] = "annotated"
                tasks[pid]["annotated_at"] = time.time()
            else:
                tasks[pid] = {"mode": body.get("mode"), "status": "annotated", "annotated_at": time.time()}
            _save_status()
            return self._send(200, json.dumps({"ok": True, "regions_saved": len(regions)}))

        if path == "/api/review/submit":
            """提交审核：{photo_id, status: approved|rework|rejected, regions, reviewer}"""
            body = self._json_body()
            # ISSUE-010：photo_id 必须存在且合法，禁止目录穿越
            pid = normalize_pid(body.get("photo_id"))
            if pid is None:
                return self._send(400, '{"error":"invalid photo_id"}')
            if pid not in _state.get("photos", {}):
                return self._send(404, '{"error":"photo not found"}')
            # 路径安全二次校验：resolve 后必须仍在 approved/ 目录内
            approved_root = (LABELS_DIR / "approved").resolve()
            target = (approved_root / f"{pid}.txt").resolve()
            if target.parent != approved_root:
                return self._send(400, '{"error":"invalid photo_id"}')
            status = body.get("status")
            if status not in ("approved", "rework", "rejected"):
                return self._send(400, '{"error":"bad status"}')
            # ISSUE-010：框坐标校验（NaN/越界/反向框全部拒绝）
            p = _state.get("photos", {}).get(pid, {})
            img = p.get("image", {})
            W, H = img.get("width", 1125), img.get("height", 2000)
            regions, rejects = _validate_regions(body.get("regions", []), W, H)
            if rejects:
                return self._send(400, json.dumps({"error": "invalid regions", "rejects": rejects[:10]}, ensure_ascii=False))
            reviews = _state["status"].setdefault("reviews", {})
            tasks = _state["status"].setdefault("tasks", {})
            prev = reviews.get(pid)
            reviews[pid] = {
                "photo_id": pid, "status": status,
                "regions": regions,
                "reviewer": body.get("reviewer", ""),
                "ts": time.time(),
            }
            if pid in tasks:
                tasks[pid]["status"] = status
            # 追加事件日志
            events_path = LABELS_DIR / "review_events.jsonl"
            LABELS_DIR.mkdir(parents=True, exist_ok=True)
            event = {"ts": time.time(), "asset_id": pid, "reviewer": body.get("reviewer", ""),
                     "status": status, "before": (prev or {}).get("regions"), "after": regions}
            with open(events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            # 如果 approved，生成 YOLO 标签到 approved/（先写临时文件再原子替换）
            if status == "approved":
                _write_approved_label(pid, regions)
            else:
                # 移除已有 approved 标签
                app_path = LABELS_DIR / "approved" / f"{pid}.txt"
                if app_path.exists():
                    app_path.unlink()
            _save_status()
            return self._send(200, json.dumps({"ok": True, "status": status}))

        self._send(404, '{"error":"not found"}')


def _write_approved_label(pid, regions):
    """将审核通过的标注写入 approved/ 作为训练源（临时文件 + 原子替换）。"""
    registry = _state.get("registry", {})
    app_dir = LABELS_DIR / "approved"
    app_dir.mkdir(parents=True, exist_ok=True)
    photos = _state.get("photos", {})
    p = photos.get(pid, {})
    img = p.get("image", {})
    W, H = img.get("width", 1125), img.get("height", 2000)
    lines = []
    for r in regions:
        name = r.get("name", "")
        reg_entry = registry.get(name)
        if reg_entry is None:
            continue
        cls_id = reg_entry["class_id"]
        box = r.get("box", [0, 0, 0, 0])
        x1, y1, x2, y2 = box
        # 防御：再次校验合法性（ISSUE-010）
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
            continue
        if not (0 <= x1 < x2 <= W) or not (0 <= y1 < y2 <= H):
            continue
        xc = (x1 + x2) / 2 / W
        yc = (y1 + y2) / 2 / H
        w = (x2 - x1) / W
        h = (y2 - y1) / H
        lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
    tmp = app_dir / f"{pid}.txt.tmp"
    tmp.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    tmp.replace(app_dir / f"{pid}.txt")


def serve(host="127.0.0.1", port=8090):
    _load_state()
    n_photos = len(_state.get("photos", {}))
    n_reg = len(_state.get("registry", {}))
    s = ThreadingHTTPServer((host, port), Handler)
    print(f"标注工作台 http://{host}:{port}")
    print(f"  照片: {n_photos}, SKU: {n_reg}")
    s.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    serve(a.host, a.port)
