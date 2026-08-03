"""零依赖人工审核服务（每张图一个人工门）。

只读 .field/blobs + .labels/proposals；只写 .labels/{reviews,approved,review_events.jsonl,review_queue.json}，
经 paths 护栏，绝不碰原始资产。approved 是训练唯一来源。
Label Studio 就绪后可以同一 review_event/approved 契约接管协作审核。
用法：python -m src.labeling.review_server --port 8090"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..catalog.alias_registry import build_registry
from ..common.config import PROJECT_ROOT
from . import emit as E

REF = PROJECT_ROOT / "搭建初期P1"
FIELD = PROJECT_ROOT / ".field"
LABEL = PROJECT_ROOT / ".labels"
HTML = Path(__file__).parent / "review.html"

_M = _I = _CM = _CI = None


def _load():
    global _M, _I, _CM, _CI
    _M = json.load(open(FIELD / "manifest.json", encoding="utf-8"))
    _I = {}
    for p in _M["photos"]:
        sha = p["image"].get("sha256") or p["image"].get("sha")
        # ISSUE-008：AssetId 统一规范为字符串（历史 manifest 可能为整数）
        _I[str(p["id"])] = {"sha": sha, "w": p["image"].get("width"), "h": p["image"].get("height"), "meta": p.get("meta", {})}
    cp = LABEL / "classes.json"
    if cp.exists():
        _CI = json.loads(cp.read_text(encoding="utf-8"))
    else:
        reg = build_registry(sorted(p.name for p in REF.iterdir() if p.is_dir()), PROJECT_ROOT / "data" / "sku_aliases.json")
        _CM, _CI = E.build_classmap(reg)
    if _CM is None:
        _CM = {c: i for i, c in enumerate(_CI)}


def _rev(rid):
    rid = str(rid)
    rp = LABEL / "reviews" / f"{rid}.json"
    return json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None


def _qstat():
    qp = LABEL / "review_queue.json"
    if not qp.exists():
        return {}
    # ISSUE-008：队列状态键同样规范化为字符串
    return {str(q["asset_id"]): q.get("status", "pending") for q in json.loads(qp.read_text(encoding="utf-8"))}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ct="application/json; charset=utf-8"):
        d = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        _load()
        if self.path in ("/", "/index.html"):
            return self._send(200, HTML.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if self.path == "/api/photos":
            st = _qstat()
            out = [{"id": str(p["id"]), "status": (_rev(p["id"]) or {}).get("status") or st.get(str(p["id"]), "pending"), "meta": _I[str(p["id"])]["meta"]} for p in _M["photos"]]
            return self._send(200, json.dumps(out, ensure_ascii=False))
        if self.path.startswith("/api/photo/"):
            rid = str(self.path.split("/")[-1])
            info = _I.get(rid)
            if not info:
                return self._send(404, '{"error":"not found"}')
            sp = LABEL / "proposals" / f"{rid}.json"
            props = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else []
            return self._send(200, json.dumps({"id": rid, "w": info["w"], "h": info["h"], "proposals": props, "review": _rev(rid), "classes": _CI}, ensure_ascii=False))
        if self.path.startswith("/img/"):
            rid = str(self.path.split("/")[-1])
            info = _I.get(rid)
            if not info or not info["sha"]:
                return self._send(404, b"nf", "text/plain")
            bp = FIELD / "blobs" / info["sha"][:2] / info["sha"]
            b = bp.read_bytes()
            return self._send(200, b, "image/jpeg" if b[:3] == b"\xff\xd8\xff" else "image/png")
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        _load()
        if self.path != "/api/review":
            return self._send(404, '{"error":"not found"}')
        n = int(self.headers.get("Content-Length", 0))
        rev = json.loads(self.rfile.read(n).decode("utf-8"))
        # ISSUE-008：输入边界立即规范化 ID
        rid = str(rev.get("asset_id", "")).strip()
        rev["asset_id"] = rid
        info = _I.get(rid)
        if not info:
            return self._send(404, '{"error":"bad id"}')
        if rev.get("status") not in ("approved", "rework", "rejected"):
            return self._send(400, '{"error":"bad status"}')
        for r in rev.get("regions", []):
            c = r.get("canonical_id")
            if c is not None and c not in _CM:
                return self._send(400, json.dumps({"error": "bad canonical", "value": c}, ensure_ascii=False))
        prev = _rev(rid)
        rev["ts"] = time.time()
        E.write_review(rid, rev)
        E.append_review_event({"ts": rev["ts"], "asset_id": rid, "reviewer": rev.get("reviewer", ""), "status": rev["status"], "before": (prev or {}).get("regions"), "after": rev.get("regions")})
        E.apply_review_to_approved(rid, rev, info["w"], info["h"], _CM)
        self._send(200, json.dumps({"ok": True, "approved_written": rev["status"] == "approved"}, ensure_ascii=False))


def serve(host="127.0.0.1", port=8090):
    _load()
    s = ThreadingHTTPServer((host, port), H)
    print(f"review server http://{host}:{port} photos={len(_M['photos'])} classes={len(_CI)}")
    s.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    serve(a.host, a.port)
