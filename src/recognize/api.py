"""识别模块+接口：通用检测器定位瓶身 + 知识库+VLM 识别 SKU（Mode A 裁决）+ 审计留痕。

检测用通用瓶身检测器（yolo11n / smoke 权重，COCO 瓶类），识别靠知识库+VLM——
即"老师"的知识下沉到识别热路径。训练好的饮料专用检测器日后替换 detect_bottles 即可。
stdlib HTTP，无额外依赖。用法：python -m src.recognize.api --port 8091"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from ..catalog.alias_registry import build_registry
from ..catalog.store import LocalStore
from ..common import paths
from ..common.config import PROJECT_ROOT
from ..labeling import assign as A

REF = PROJECT_ROOT / "搭建初期P1"
KB = PROJECT_ROOT / ".kb"
FIELD = PROJECT_ROOT / ".field"

_det = None


def _detector():
    global _det
    if _det is not None:
        return _det
    from ultralytics import YOLO

    w = Path(".models/smoke/weights/best.pt")
    _det = YOLO(str(w) if w.exists() else "yolo11n.pt")
    return _det


def _bottle_cls(model):
    return [i for i, n in model.names.items() if n == "bottle"]


def detect_bottles(image_bytes, conf=0.25):
    import numpy as np
    model = _detector()
    bcls = _bottle_cls(model)
    arr = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
    r = model.predict(arr, conf=conf, classes=bcls, verbose=False, device="cpu")
    out = []
    for bi in r:
        if bi.boxes is None:
            continue
        for xyxy in bi.boxes.xyxy.tolist():
            out.append(xyxy)
    return out


_store = _ids = _vec = _reg = None


def _load_kb():
    global _store, _ids, _vec, _reg
    if _store is None:
        _store = LocalStore(KB)
        _ids, _vec = _store.load_vectors()
        _reg = build_registry(sorted(p.name for p in REF.iterdir() if p.is_dir()), PROJECT_ROOT / "data" / "sku_aliases.json")
    return _store, _ids, _vec, _reg


def recognize(image_bytes, boxes=None, topk=5):
    store, ids, vec, reg = _load_kb()
    if boxes is None:
        boxes = detect_bottles(image_bytes)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H = img.size
    products = []
    for b in boxes:
        x1, y1, x2, y2 = (int(v) for v in b)
        crop = img.crop((max(0, x1), max(0, y1), min(W, x2), min(H, y2)))
        if crop.width < 8 or crop.height < 8:
            continue
        r = A.assign(crop, store, ids, vec, reg, prior_name=None, topk=topk)
        products.append({"box": b, "decision": r["decision"], "confidence": r["confidence"], "score": r["score"], "evidence": r["evidence"]})
    return products


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
        if self.path == "/v1/health":
            return self._send(200, '{"ok":true}')
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/v1/recognize":
            return self._send(404, '{"error":"not found"}')
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n).decode("utf-8"))
        if "image_base64" in req:
            img = base64.b64decode(req["image_base64"])
        elif "asset_id" in req:
            m = json.load(open(FIELD / "manifest.json", encoding="utf-8"))
            idx = {p["id"]: p for p in m["photos"]}
            sha = idx[req["asset_id"]]["image"].get("sha256") or idx[req["asset_id"]]["image"].get("sha")
            img = (FIELD / "blobs" / sha[:2] / sha).read_bytes()
        else:
            return self._send(400, '{"error":"need image_base64 or asset_id"}')
        products = recognize(img, boxes=req.get("boxes"))
        rid = "run-" + str(int(time.time() * 1000))
        try:
            from ..data import warehouse as wh

            conn = wh.connect()
            wh.migrate(conn)
            conn.execute("INSERT INTO recognition_run VALUES(?,?,?,?,?,?,?)",
                         (rid, req.get("asset_id"), json.dumps({"detector": "yolo11n/smoke"}), "kb-v1", "prompt-v1", json.dumps(products, ensure_ascii=False), time.time()))
            conn.commit()
            conn.close()
        except Exception:
            rid = "run-err"
        self._send(200, json.dumps({"run_id": rid, "products": products}, ensure_ascii=False))


def serve(host="127.0.0.1", port=8091):
    s = ThreadingHTTPServer((host, port), H)
    print(f"recognition api http://{host}:{port}")
    s.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8091)
    a = ap.parse_args()
    serve(port=a.port)
