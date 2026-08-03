"""SKU 识别服务 v3：级联引擎（YOLO 画框 + 分类器精识别）+ 模型版本管理。

架构（与 docs/architecture.md 一致）：
- 检测层：sku_v4 YOLO 画框器（冻结）或 DB production 权重
- 识别层：ResNet18 级联分类器精识别，低置信标记 needs_review
- 管理层：只加载 status='production' 模型；失败关闭（fail-closed），不回退通用模型

安全红线（ISSUE-002/003）：
- 业务权重缺失/损坏/类别不匹配 → MODEL_UNAVAILABLE，健康检查非健康
- 绝不加载 COCO 等通用模型并按业务 registry 解释

API：
  GET  /v2/health          健康检查 + 模型包信息
  POST /v2/recognize       识别（image_base64 或 asset_id）
  GET  /v2/models          已注册模型列表
  POST /v2/models/switch   切换生产模型（单事务 + 重载，需管理 token）
  POST /v2/admin/reload    强制重载模型包（编排层切换后调用）

用法：python -m src.recognize.service --port 8091"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from ..data import warehouse as wh

REGISTRY_PATH = PROJECT_ROOT / "data" / "sku_registry.json"
MODELS_DIR = PROJECT_ROOT / ".models"
TRAINING_DATA = PROJECT_ROOT / ".training_data"
FIELD_DIR = PROJECT_ROOT / ".field"
# 文档规定的默认级联资产（冻结画框器 + 分类器）
DEFAULT_YOLO_WEIGHT = MODELS_DIR / "sku_v4" / "weights" / "best.pt"
CLF_WEIGHT = MODELS_DIR / "classifier" / "best.pt"

MAX_BODY_BYTES = 32 * 1024 * 1024  # 请求体上限 32MB

# RA-016：在线推理背压 —— 并发硬上限（默认 2，单进程共享 YOLO/Torch 模型），
# 排队超过等待时限立即拒绝（HTTP 429），绝不无限开线程拖垂尾延迟。
_MAX_CONCURRENCY = max(1, int(os.environ.get("RECOGNIZE_MAX_CONCURRENCY", "2")))
_QUEUE_TIMEOUT = float(os.environ.get("RECOGNIZE_QUEUE_TIMEOUT", "5"))
_INFER_SEM = threading.BoundedSemaphore(_MAX_CONCURRENCY)


class ModelUnavailableError(RuntimeError):
    """模型包缺失或校验失败 —— 服务必须失败关闭，禁止回退通用模型。"""


class OverloadedError(RuntimeError):
    """RA-016：推理队列已满，背压拒绝 —— 调用方应收到 429 而非无限等待。"""


def sha256_file(p: Path, limit_mb: int = 0) -> str:
    h = hashlib.sha256()
    n = 0
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
            if limit_mb and n > limit_mb * (1 << 20):
                break
    return h.hexdigest()


def _load_registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _get_production_model():
    """只允许 status='production' 的模型进入线上加载（ISSUE-005）。

    返回 None 表示 DB 未登记 production，使用文档规定的默认级联资产。"""
    conn = wh.connect()
    wh.migrate(conn)
    row = conn.execute(
        "SELECT mv_id, weight_uri, status, metrics_json, created_at FROM model_version "
        "WHERE task='detect_208sku' AND status='production' "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row:
        return {"mv_id": row[0], "weight_uri": row[1], "status": row[2],
                "metrics": json.loads(row[3]) if row[3] else {}, "created_at": row[4]}
    return None


class RecognitionEngine:
    """统一识别引擎：级联（YOLO 画框 + 分类器精识别），失败关闭。"""

    def __init__(self):
        self.yolo = None
        self.cascade = None
        self.registry = None
        self.info: dict = {}
        self.loaded_at: float = 0
        self.load_error: str | None = None
        self._lock = threading.Lock()

    def load(self, force: bool = False):
        """加载完整模型包。任何校验失败抛 ModelUnavailableError（fail-closed）。"""
        with self._lock:
            if self.cascade is not None and not force:
                return
            from ..cascade.cascade_inference import CascadeRecognizer

            # RA-006：优先从当前生产 bundle 解析全部资产（权重+registry+阈值）；
            # 无 CURRENT 指针时退回默认路径逻辑
            bundle_info = None
            try:
                from ..models import bundle as _bundle
                bundle_info = _bundle.resolve_weights()
            except Exception:
                bundle_info = None
            thr = (bundle_info or {}).get("threshold_values") or {}

            if bundle_info and Path(bundle_info["detector"]).exists() \
                    and Path(bundle_info["classifier"]).exists():
                weight = Path(bundle_info["detector"])
                clf_weight = Path(bundle_info["classifier"])
                mv_id = f"bundle:{bundle_info['bundle_id']}"
                source = "bundle"
                reg_path = Path(bundle_info["registry"]) if bundle_info.get("registry") else REGISTRY_PATH
                registry = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else _load_registry()
            else:
                clf_weight = CLF_WEIGHT
                registry = _load_registry()
                # 1. 画框器权重：production 优先，否则文档默认冻结 sku_v4
                prod = _get_production_model()
                if prod and prod.get("weight_uri"):
                    weight = Path(prod["weight_uri"])
                    mv_id = prod["mv_id"]
                    source = "production"
                else:
                    weight = DEFAULT_YOLO_WEIGHT
                    mv_id = "sku_v4_frozen"
                    source = "default_frozen"
            n_classes_expected = len(registry)
            if not weight.exists():
                raise ModelUnavailableError(
                    f"检测器权重缺失: {weight}（禁止回退通用模型，请先训练或切换有效模型）")

            # 2. 分类器权重必须存在（级联的核心），缺失即失败关闭
            if not clf_weight.exists():
                raise ModelUnavailableError(f"级联分类器权重缺失: {clf_weight}")

            # 3. 加载并校验类别一致性（阈值来自 bundle thresholds.json，缺省用代码默认）
            kwargs = {}
            if isinstance(thr.get("conf"), (int, float)):
                kwargs["conf_thr"] = float(thr["conf"])
            if isinstance(thr.get("margin"), (int, float)):
                kwargs["margin_thr"] = float(thr["margin"])
            cascade = CascadeRecognizer(yolo_weight=str(weight), clf_weight=str(clf_weight), **kwargs)
            n_yolo = len(cascade.yolo.names) if hasattr(cascade.yolo, "names") else 0
            if n_yolo and n_yolo != n_classes_expected:
                raise ModelUnavailableError(
                    f"模型类别数不匹配: 检测器 {n_yolo} vs registry {n_classes_expected}，"
                    "拒绝按业务 SKU 解释输出")

            self.cascade = cascade
            self.registry = registry
            self.loaded_at = time.time()
            self.load_error = None
            self.info = {
                "bundle": bundle_info["bundle_id"] if bundle_info and source == "bundle" else None,
                "detector": mv_id, "detector_source": source,
                "detector_weight": str(weight),
                "detector_sha256": sha256_file(weight)[:16],
                "classifier": f"{cascade.backbone}@ep?/acc?",
                "classifier_weight": str(clf_weight),
                "classifier_sha256": sha256_file(clf_weight)[:16],
                "n_classes": n_classes_expected,
                "conf_threshold": cascade.conf_thr,
                "loaded_at": self.loaded_at,
            }
            # 补充分类器最佳轮信息
            try:
                import torch
                ck = torch.load(str(clf_weight), map_location="cpu", weights_only=False)
                self.info["classifier"] = (
                    f"{ck.get('backbone', 'resnet18')}@ep{ck.get('epoch', '?')}"
                    f"/acc{float(ck.get('val_acc', 0)) * 100:.2f}%")
            except Exception:
                pass
            print(f"[recognize] 级联引擎已加载: 检测器={mv_id} 分类器={self.info['classifier']}")

    def recognize(self, image_bytes: bytes, conf: float = 0.25) -> list[dict]:
        """级联识别。输出兼容旧契约（box/name/sku_id/confidence）+ needs_review 显式标记。

        RA-004：拒识结果 sku_id 为空、name 为 unknown，绝不把 detector 类别包装成已匹配 SKU。"""
        if self.cascade is None:
            self.load()
        # RA-016：所有在线入口（HTTP/ML backend/批任务）都经此信号量背压
        if not _INFER_SEM.acquire(timeout=_QUEUE_TIMEOUT):
            raise OverloadedError(
                f"推理队列已满（并发上限 {_MAX_CONCURRENCY}，等待 {_QUEUE_TIMEOUT}s 超时）")
        try:
            raw = self.cascade.recognize(image_bytes, conf=conf)
        finally:
            _INFER_SEM.release()
        products = []
        for pr in raw:
            needs_review = pr.get("status") != "accepted"
            products.append({
                "box": pr["box"],
                "sku_id": pr.get("sku_id", ""),
                "name": pr.get("sku_name", ""),
                "class_id": None,
                "confidence": pr.get("classifier_conf", 0.0),
                "margin": pr.get("margin"),
                "yolo_name": pr.get("yolo_sku"),
                "yolo_confidence": pr.get("yolo_conf"),
                "source": pr.get("source", "classifier"),
                "needs_review": bool(needs_review),
            })
        products.sort(key=lambda p: -p["confidence"])
        return products


_engine = RecognitionEngine()


def get_engine() -> RecognitionEngine:
    return _engine


def detect_and_recognize(image_bytes: bytes, conf: float = 0.25, imgsz: int | None = None) -> list[dict]:
    """兼容入口：所有在线识别必须经此走级联引擎（ISSUE-002）。"""
    return _engine.recognize(image_bytes, conf=conf)


def _load_detector(force: bool = False):
    """兼容旧接口：预加载引擎（供 ML backend 预热）。"""
    _engine.load(force=force)
    return _engine.cascade.yolo if _engine.cascade else None


def switch_production(mv_id: str) -> dict:
    """切换 production（ISSUE-005）：单事务 —— 校验目标存在且权重可读 → 旧 production 全部 retired
    → 目标设为 production。任何一步失败回滚，旧模型继续服务。"""
    conn = wh.connect()
    wh.migrate(conn)
    try:
        row = conn.execute(
            "SELECT weight_uri FROM model_version WHERE mv_id=?", (mv_id,)).fetchone()
        if not row:
            raise ValueError(f"model not found: {mv_id}")
        wuri = row[0]
        if not wuri or not Path(wuri).exists():
            raise ValueError(f"目标权重缺失，拒绝切换: {wuri}")
        # 单事务：旧 production 全部 retired → 目标设为 production
        conn.execute("UPDATE model_version SET status='retired' "
                     "WHERE task='detect_208sku' AND status='production' AND mv_id<>?", (mv_id,))
        conn.execute("UPDATE model_version SET status='production' WHERE mv_id=?", (mv_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return {"ok": True, "switched_to": mv_id}


def _write_audit(run_id: str, asset_id, model_versions: dict, products: list, extra: dict | None = None) -> bool:
    """识别审计（ISSUE-007）：UUIDv4 run_id；写失败返回 False，调用方必须显式标注 audit_pending。

    RA-017：extra 完整落库（并入 model_versions JSON 的 _extra 键）；主表写失败时
    完整事件进 audit_outbox（transactional outbox），后台重放幂等补写，绝不静默丢审计。"""
    mv = dict(model_versions or {})
    if extra:
        mv["_extra"] = extra
    mv_json = json.dumps(mv, ensure_ascii=False)
    products_json = json.dumps(products, ensure_ascii=False)
    ts = time.time()
    try:
        conn = wh.connect()
        wh.migrate(conn)
        conn.execute(
            "INSERT INTO recognition_run VALUES(?,?,?,?,?,?,?)",
            (run_id, asset_id, mv_json, "registry_v1", "v3_cascade", products_json, ts)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[recognize][AUDIT_FAIL] run_id={run_id} {type(e).__name__}: {e} → 进 outbox 重放",
              file=sys.stderr, flush=True)
        try:
            conn = wh.connect()
            wh.migrate(conn)
            payload = json.dumps({"model_versions": mv_json, "products": products_json,
                                  "created_at": ts}, ensure_ascii=False)
            conn.execute("INSERT OR REPLACE INTO audit_outbox(run_id, asset_id, payload_json, created_at) "
                         "VALUES(?,?,?,?)", (run_id, asset_id, payload, ts))
            conn.commit()
            conn.close()
        except Exception as e2:
            # 连 outbox 都写不进：完整 payload 落日志，作为最后兑底
            print(f"[recognize][AUDIT_DEAD] run_id={run_id} outbox 也失败: {e2}; "
                  f"payload={json.dumps({'asset_id': asset_id, 'mv': mv, 'products': products}, ensure_ascii=False)}",
                  file=sys.stderr, flush=True)
        return False


_OUTBOX_DEAD_ATTEMPTS = 20


def _replay_outbox_once() -> int:
    """RA-017：重放审计 outbox。幂等键=run_id（PK），INSERT OR IGNORE 重复重放安全。

    重试耗尽的事件保留在 outbox 供人工排查，绝不删除。返回本次补写条数。"""
    try:
        conn = wh.connect()
        wh.migrate(conn)
        rows = conn.execute(
            "SELECT run_id, asset_id, payload_json, attempts FROM audit_outbox "
            "ORDER BY created_at LIMIT 50").fetchall()
        done = 0
        for run_id, asset_id, payload_json, attempts in rows:
            try:
                p = json.loads(payload_json)
                conn.execute("INSERT OR IGNORE INTO recognition_run VALUES(?,?,?,?,?,?,?)",
                             (run_id, asset_id, p["model_versions"], "registry_v1", "v3_cascade",
                              p["products"], p["created_at"]))
                conn.execute("DELETE FROM audit_outbox WHERE run_id=?", (run_id,))
                conn.commit()
                done += 1
            except Exception:
                conn.rollback()
                conn.execute("UPDATE audit_outbox SET attempts=?, last_try=? WHERE run_id=?",
                             (attempts + 1, time.time(), run_id))
                conn.commit()
                if attempts + 1 >= _OUTBOX_DEAD_ATTEMPTS:
                    print(f"[recognize][AUDIT_DEAD] run_id={run_id} 重试耗尽，保留 outbox 待人工处理",
                          file=sys.stderr, flush=True)
        conn.close()
        return done
    except Exception as e:
        print(f"[recognize][outbox] 重放异常: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return 0


def _start_outbox_replayer(interval: float = 10.0):
    def loop():
        while True:
            time.sleep(interval)
            try:
                _replay_outbox_once()
            except Exception:
                pass
    t = threading.Thread(target=loop, name="audit-outbox-replayer", daemon=True)
    t.start()
    return t


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors_origin(self) -> str | None:
        """RA-020：CORS 改为显式白名单（RECOGNIZE_CORS_ORIGINS 逗号分隔）。

        未配置白名单或请求 Origin 不在名单内 → 不发送任何 CORS 头，
        绝不无条件 Access-Control-Allow-Origin: *。"""
        allow = [o.strip() for o in os.environ.get("RECOGNIZE_CORS_ORIGINS", "").split(",") if o.strip()]
        if not allow:
            return None
        origin = self.headers.get("Origin", "")
        return origin if origin in allow else None

    def _send(self, code, body, ct="application/json; charset=utf-8"):
        d = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(d)))
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(d)

    def do_OPTIONS(self):
        origin = self._cors_origin()
        code = 200 if origin else 405  # 未授权 Origin 的预检直接拒绝
        self.send_response(code)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _admin_ok(self) -> bool:
        """管理类接口要求 Bearer token（ISSUE-011 / RA-020 收口）。

        非 dev 环境未配置 token 时失败关闭（拒绝管理操作）；
        token 比对使用常量时间比较防时序旁路。"""
        import secrets as _secrets
        token = os.environ.get("RECOGNIZE_ADMIN_TOKEN", "")
        if not token:
            env = os.environ.get("APP_ENV", "dev").strip().lower()
            return env == "dev"  # 仅 dev 允许免 token 本机管理
        auth = self.headers.get("Authorization", "")
        return _secrets.compare_digest(auth, f"Bearer {token}")

    def do_GET(self):
        if self.path == "/v2/health":
            info = _engine.info or {}
            healthy = _engine.cascade is not None and _engine.load_error is None
            return self._send(200 if healthy else 503, json.dumps({
                "ok": healthy,
                "engine": "cascade_v3",
                "model": info.get("detector"),
                "detector": info.get("detector"), "detector_sha256": info.get("detector_sha256"),
                "classifier": info.get("classifier"), "classifier_sha256": info.get("classifier_sha256"),
                "n_classes": info.get("n_classes"),
                "registry_size": len(_engine.registry or _load_registry()),
                "loaded_at": info.get("loaded_at"),
                "error": _engine.load_error,
            }, ensure_ascii=False))

        if self.path == "/v2/models":
            conn = wh.connect()
            wh.migrate(conn)
            rows = conn.execute(
                "SELECT mv_id, task, status, metrics_json, weight_uri, created_at FROM model_version ORDER BY created_at DESC"
            ).fetchall()
            conn.close()
            models = [{"mv_id": r[0], "task": r[1], "status": r[2],
                       "metrics": json.loads(r[3]) if r[3] else {},
                       # RA-020：只暴露文件名，不泄露服务器绝对路径
                       "weight": Path(r[4]).name if r[4] else None,
                       "created_at": r[5]} for r in rows]
            return self._send(200, json.dumps({"models": models, "current": (_engine.info or {}).get("detector")}, ensure_ascii=False))

        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_BODY_BYTES:
            return self._send(413, '{"error":"payload too large"}')

        if self.path == "/v2/recognize":
            req = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            if "image_base64" in req:
                try:
                    img_bytes = base64.b64decode(req["image_base64"])
                except Exception:
                    return self._send(400, '{"error":"bad base64"}')
            elif "asset_id" in req:
                img_bytes = self._load_asset(req["asset_id"])
                if img_bytes is None:
                    return self._send(404, '{"error":"asset not found"}')
            else:
                return self._send(400, '{"error":"need image_base64 or asset_id"}')

            conf = float(req.get("conf", 0.25))
            run_id = str(uuid.uuid4())  # ISSUE-007：UUIDv4 防并发冲突
            t0 = time.time()
            try:
                products = _engine.recognize(img_bytes, conf=conf)
            except ModelUnavailableError as e:
                return self._send(503, json.dumps({"error": "MODEL_UNAVAILABLE", "detail": str(e)}, ensure_ascii=False))
            except OverloadedError as e:
                # RA-016：背压拒绝 → 429，客户端可重试
                self.send_response(429)
                self.send_header("Retry-After", "5")
                msg = json.dumps({"error": "OVERLOADED", "detail": str(e)}, ensure_ascii=False).encode()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
            elapsed = time.time() - t0

            audit_ok = _write_audit(
                run_id, req.get("asset_id"),
                {"detector": (_engine.info or {}).get("detector"),
                 "classifier": (_engine.info or {}).get("classifier")},
                products)

            return self._send(200, json.dumps({
                "run_id": run_id, "products": products,
                "count": len(products), "elapsed_ms": round(elapsed * 1000),
                "model": (_engine.info or {}).get("detector"),
                "audit_written": audit_ok,
                **({"audit_pending": True} if not audit_ok else {}),
            }, ensure_ascii=False))

        if self.path == "/v2/models/switch":
            if not self._admin_ok():
                return self._send(401, '{"error":"unauthorized"}')
            req = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            mv_id = req.get("model_version_id")
            if not mv_id:
                return self._send(400, '{"error":"need model_version_id"}')
            try:
                result = switch_production(mv_id)
            except ValueError as e:
                return self._send(404 if "not found" in str(e) else 400,
                                  json.dumps({"error": str(e)}, ensure_ascii=False))
            # 事务成功后热重载；重载失败回滚状态，旧模型继续服务
            try:
                _engine.load(force=True)
            except ModelUnavailableError as e:
                old = _get_previous_production(mv_id)
                if old:
                    try:
                        switch_production(old)
                        _engine.load(force=True)
                    except Exception:
                        pass
                return self._send(500, json.dumps(
                    {"error": "load_failed_rolled_back", "detail": str(e)}, ensure_ascii=False))
            return self._send(200, json.dumps({**result, "loaded": _engine.info.get("detector"),
                                               "sha256": _engine.info.get("detector_sha256")}, ensure_ascii=False))

        if self.path == "/v2/admin/reload":
            if not self._admin_ok():
                return self._send(401, '{"error":"unauthorized"}')
            try:
                _engine.load(force=True)
            except ModelUnavailableError as e:
                return self._send(503, json.dumps({"error": str(e)}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True, "loaded": _engine.info.get("detector")}))

        self._send(404, '{"error":"not found"}')

    def _load_asset(self, asset_id):
        """从 .training_data 或 .field 加载图片。"""
        asset_id = str(asset_id)
        for base in [TRAINING_DATA, FIELD_DIR]:
            manifest_path = base / "manifest.json"
            if not manifest_path.exists():
                continue
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            photos = m.get("photos", {})
            if isinstance(photos, dict):
                p = photos.get(asset_id) or photos.get(asset_id.strip())
            else:
                p = next((x for x in photos if str(x.get("id")) == asset_id), None)
            if p:
                img = p.get("image", {})
                sha = img.get("sha256")
                if sha:
                    bp = base / "blobs" / sha[:2] / sha
                    if bp.exists():
                        return bp.read_bytes()
        return None


def _get_previous_production(exclude_mv_id: str) -> str | None:
    conn = wh.connect()
    wh.migrate(conn)
    row = conn.execute(
        "SELECT mv_id FROM model_version WHERE task='detect_208sku' AND mv_id<>? "
        "AND status IN ('retired','trained') ORDER BY created_at DESC LIMIT 1",
        (exclude_mv_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def serve(host="127.0.0.1", port=8091):
    try:
        _engine.load()
    except ModelUnavailableError as e:
        _engine.load_error = str(e)
        print(f"[recognize][FATAL] 模型包不可用（失败关闭，服务以非健康状态启动）: {e}")
    s = ThreadingHTTPServer((host, port), Handler)
    _start_outbox_replayer()  # RA-017：审计 outbox 后台重放
    print(f"识别服务（级联引擎 v3） http://{host}:{port}")
    print(f"  检测器: {(_engine.info or {}).get('detector', '不可用')}")
    print(f"  分类器: {(_engine.info or {}).get('classifier', '不可用')}")
    print(f"  推理并发上限: {_MAX_CONCURRENCY}（排队超时 {_QUEUE_TIMEOUT}s → 429）")
    s.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    serve(a.host, a.port)
