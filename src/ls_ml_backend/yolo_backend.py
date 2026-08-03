"""Label Studio ML 后端：YOLO SKU 检测自动标注。

直接实现现代 LS ML backend HTTP 协议（规避 label-studio-ml 1.0.9 旧协议兼容问题）。
LS 在项目设置中连接本后端 URL（http://127.0.0.1:8301），开启自动预标注后，
打开任务即得 YOLO 预测框 + SKU。

端点：
  GET  /health     健康检查
  POST /setup      接收项目配置，加载模型
  POST /predict    对 tasks 预测，返回 LS 格式 result
  GET  /versions   模型版本

用法：python -m src.ls_ml_backend.yolo_backend --port 8301"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from ..common.config import PROJECT_ROOT, get_settings

get_settings()  # 加载 .env

REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"


def _engine_status() -> dict:
    """RA-022：模型版本必须动态取自识别引擎实际加载状态，禁止硬编码。

    返回 {loaded, version, load_error}：未加载时 version=not_loaded 且 health 报 DOWN。"""
    try:
        from ..recognize.service import get_engine
        eng = get_engine()
        info = eng.info or {}
        version = info.get("bundle") or info.get("detector")
        return {"loaded": eng.cascade is not None,
                "version": str(version) if version else "not_loaded",
                "load_error": eng.load_error}
    except Exception as e:
        return {"loaded": False, "version": "not_loaded", "load_error": str(e)}


# ISSUE-012：SSRF 防护 —— 仅允许配置的 Label Studio 域名 / 受控对象存储域名 / data: URI
MAX_IMAGE_BYTES = 50 * 1024 * 1024      # 下载字节上限 50MB
MAX_REDIRECTS = 3                        # 重定向跳数上限
MAX_IMAGE_PIXELS = 80_000_000            # 解码像素上限（防 decompression bomb）


class ImageFetchError(Exception):
    """图片获取失败（与“真实无检测结果”严格区分）。"""


def _load_registry():
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return reg


def _allowed_hosts() -> set[str]:
    """URL 白名单：LABEL_STUDIO_URL 主机 + ML_BACKEND_ALLOWED_HOSTS（逗号分隔）。"""
    hosts = set()
    ls_url = os.environ.get("LABEL_STUDIO_URL", "http://127.0.0.1:8300")
    for raw in (ls_url, os.environ.get("ML_BACKEND_ALLOWED_HOSTS", "")):
        raw = (raw or "").strip()
        if not raw:
            continue
        if "://" not in raw:
            raw = f"http://{raw}"
        netloc = urlparse(raw).netloc.lower()
        if netloc:
            hosts.add(netloc)
    return hosts


def _fetch_url(url: str, token: str, redirects_left: int = MAX_REDIRECTS) -> bytes:
    """下载单个 URL：白名单校验 + 禁任意重定向 + 字节上限。失败抛 ImageFetchError。"""
    import requests

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ImageFetchError(f"非法协议: {parsed.scheme}")
    if parsed.netloc.lower() not in _allowed_hosts():
        raise ImageFetchError(f"URL 主机不在白名单: {parsed.netloc}")
    headers = {"Authorization": f"Token {token}"} if token else {}
    r = requests.get(url, headers=headers, timeout=120, stream=True,
                     allow_redirects=False)
    if r.status_code in (301, 302, 303, 307, 308):
        if redirects_left <= 0:
            raise ImageFetchError("重定向次数超限")
        location = r.headers.get("Location", "")
        if not location:
            raise ImageFetchError("重定向缺少 Location")
        # 相对重定向补全为同主机；目标必须仍在白名单内（重定向后重复校验）
        if location.startswith("/"):
            location = f"{parsed.scheme}://{parsed.netloc}{location}"
        return _fetch_url(location, token, redirects_left - 1)
    if r.status_code != 200:
        raise ImageFetchError(f"HTTP {r.status_code}")
    chunks, total = [], 0
    for chunk in r.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise ImageFetchError(f"响应超过 {MAX_IMAGE_BYTES} 字节上限")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ImageFetchError("响应体为空")
    return data


def _fetch_image(image_url: str) -> bytes:
    """从 LS 下载图片（相对路径补全为 LS URL，带 token 鉴权）。

    ISSUE-012：只允许白名单域名与 data: URI；任何失败抛 ImageFetchError，
    由调用方写入错误字段，绝不静默返回空成功。"""
    if image_url.startswith("data:"):
        try:
            _head, b64 = image_url.split(",", 1)
            data = base64.b64decode(b64, validate=True)
        except Exception as e:
            raise ImageFetchError(f"data URI 解码失败: {e}")
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ImageFetchError("data URI 为空或超限")
        return data
    token = os.environ.get("LABEL_STUDIO_API_KEY", "")
    if image_url.startswith("http"):
        return _fetch_url(image_url, token)
    ls_url = os.environ.get("LABEL_STUDIO_URL", "http://127.0.0.1:8300").rstrip("/")
    return _fetch_url(f"{ls_url}{image_url}", token)


def _safe_open_image(img_bytes: bytes) -> Image.Image:
    """解码图片，限制像素数（防 decompression bomb）。"""
    with Image.open(io.BytesIO(img_bytes)) as im:
        w, h = im.size
        if w * h > MAX_IMAGE_PIXELS:
            raise ImageFetchError(f"图片像素超限: {w}x{h}")
        return im.convert("RGB")


def _predict_one(image_bytes: bytes, conf: float, reg: dict) -> tuple[list[dict], float]:
    """对单张图运行识别，返回 (LS result 列表, 平均 score)。"""
    from ..recognize.service import detect_and_recognize

    img = _safe_open_image(image_bytes)
    W, H = img.size
    products = detect_and_recognize(image_bytes, conf=conf)

    result = []
    scores = []
    for pr in products:
        x1, y1, x2, y2 = pr["box"]
        # 像素 → 百分比
        box = {
            "x": x1 / W * 100,
            "y": y1 / H * 100,
            "width": (x2 - x1) / W * 100,
            "height": (y2 - y1) / H * 100,
            "rotation": 0,
        }
        rid = f"yolo_{uuid.uuid4().hex[:8]}"
        result.append({
            "id": rid, "from_name": "box", "to_name": "image",
            "type": "rectanglelabels", "value": {**box, "rectanglelabels": ["product"]},
        })
        name = pr.get("name", "")
        # RA-004：状态由级联裁决决定，ML backend 不得把所有结果硬编码为 matched。
        # 拒识（needs_review）输出 unknown 进入人工审核，且不附 taxonomy 预判。
        accepted = (not pr.get("needs_review")) and name in reg
        if accepted:
            result.append({
                "id": rid, "from_name": "sku", "to_name": "image",
                "type": "taxonomy", "value": {**box, "taxonomy": [[name]]},
            })
        result.append({
            "id": rid, "from_name": "status", "to_name": "image",
            "type": "choices", "value": {**box, "choices": ["matched" if accepted else "unknown"]},
        })
        scores.append(pr.get("confidence", 0.5))
    avg = sum(scores) / len(scores) if scores else 0.0
    return result, avg


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        d = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def _json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self):
        if self.path.startswith("/liveness"):
            # RA-022：liveness 仅证明进程存活，与模型状态解耦
            return self._send(200, {"status": "alive"})
        if self.path.startswith("/health"):
            # RA-022：readiness 反映引擎真实加载状态，未加载必须 503 DOWN，
            # 绝不恒返回 UP（此前 _model_version 硬编码 sku_v1 掩盖了加载失败）。
            st = _engine_status()
            if st["loaded"]:
                return self._send(200, {"status": "UP", "model_version": st["version"]})
            return self._send(503, {"status": "DOWN", "model_version": st["version"],
                                    "error": st["load_error"]})
        if self.path.startswith("/versions"):
            return self._send(200, {"versions": [_engine_status()["version"]]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/setup"):
            body = self._json()
            # LS 发来项目配置；这里仅确认就绪
            return self._send(200, {"model_version": _engine_status()["version"]})

        if self.path.startswith("/predict"):
            body = self._json()
            tasks = body.get("tasks", [])
            params = body.get("params", {}) or {}
            conf = 0.25
            reg = _load_registry()
            results = []
            for t in tasks:
                data = t.get("data", {})
                image_url = data.get("image") or data.get("url") or ""
                tid = t.get("id")
                # ISSUE-012：区分“真实无检测结果”与“下载/解码/推理失败”
                try:
                    if not image_url:
                        raise ImageFetchError("任务未提供 image URL")
                    img_bytes = _fetch_image(image_url)
                    result, score = _predict_one(img_bytes, conf, reg)
                except ImageFetchError as e:
                    print(f"[ml_backend] task={tid} 图片获取失败: {e}", file=sys.stderr)
                    results.append({"model_version": _engine_status()["version"], "score": 0.0,
                                    "result": [], "error": f"fetch_failed: {e}"})
                    continue
                except Exception as e:
                    print(f"[ml_backend] task={tid} 推理失败: {type(e).__name__}: {e}", file=sys.stderr)
                    results.append({"model_version": _engine_status()["version"], "score": 0.0,
                                    "result": [], "error": f"inference_failed: {type(e).__name__}: {e}"})
                    continue
                results.append({"model_version": _engine_status()["version"], "score": round(score, 4), "result": result})
            return self._send(200, {"results": results})

        self._send(404, {"error": "not found"})


def serve(host="127.0.0.1", port=8301):
    # 预加载模型；RA-022：失败不是警告了事 —— 错误必须记入引擎 load_error，
    # 使 /health 如实报 DOWN，而不是继续假装 UP。
    try:
        from ..recognize.service import _load_detector, get_engine
        _load_detector()
    except Exception as e:
        try:
            get_engine().load_error = f"{type(e).__name__}: {e}"
        except Exception:
            pass
        print(f"[ml_backend][FATAL] 模型预加载失败（health 将报 DOWN）: {e}", file=sys.stderr)
    s = ThreadingHTTPServer((host, port), H)
    st = _engine_status()
    print(f"YOLO ML 后端 http://{host}:{port}")
    print(f"  模型版本: {st['version']} ({'已加载' if st['loaded'] else '未加载'})")
    s.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8301)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    serve(a.host, a.port)
