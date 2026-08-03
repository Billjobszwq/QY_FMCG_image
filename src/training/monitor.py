"""统一训练监控后端（v2）：实时监控所有训练（YOLO 检测 + 级联分类器）+ 系统状态。

数据源：
  - YOLO 检测训练：.models/<run>/results.csv（mAP50/P/R/losses）+ train_meta.json
  - 级联分类器：.models/classifier/training_history.json（逐轮 val_acc/train_acc/val_loss）+ best.pt
  - 系统状态：各服务端口探活、训练进程、GPU

端点：
  GET /                监控页面
  GET /api/overview    全部训练概览（YOLO 各轮 + 分类器 + 系统）
  GET /api/yolo        所有 YOLO 检测训练轮次指标
  GET /api/classifier  分类器训练实时指标
  GET /api/status      兼容旧版（当前活跃训练）

用法：python -m src.training.monitor --port 8092"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

MODELS_DIR = PROJECT_ROOT / ".models"
HTML = Path(__file__).parent / "monitor.html"
SERVICES = {
    "Label Studio": 8300, "ML Backend": 8301, "识别服务": 8091,
    "训练监控": 8092, "编排 API": 8304,
}

# RA-001：checkpoint 元数据缓存（仅文件 mtime/size 变化时重新读取，绝不每请求 torch.load）
_CKPT_CACHE: dict = {}
_CKPT_CACHE_TTL = 60.0  # 兜底：即使 mtime 不变，也最多每 60s 复查一次 stat
_CKPT_CACHE_AT = 0.0


def _read_yolo_run(run_dir: Path) -> dict | None:
    rc = run_dir / "results.csv"
    if not rc.exists():
        return None
    lines = rc.read_text().strip().splitlines()
    if len(lines) < 2:
        return None
    cols = [c.strip() for c in lines[0].split(",")]
    epochs = []
    for line in lines[1:]:
        v = line.split(",")
        d = dict(zip(cols, v))
        def g(k):
            try:
                return float(d.get(k, 0))
            except (TypeError, ValueError):
                return 0.0
        if not d.get("epoch", "").strip().lstrip("-").isdigit():
            continue
        epochs.append({
            "epoch": int(g("epoch")),
            "map50": g("metrics/mAP50(B)"), "map50_95": g("metrics/mAP50-95(B)"),
            "precision": g("metrics/precision(B)"), "recall": g("metrics/recall(B)"),
            "box_loss": g("train/box_loss"), "cls_loss": g("train/cls_loss"),
            "val_box": g("val/box_loss"), "val_cls": g("val/cls_loss"),
        })
    if not epochs:
        return None
    best = max(epochs, key=lambda e: e["map50"])
    meta = {}
    mp = run_dir / "train_meta.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"run": run_dir.name, "epochs": epochs, "best": best, "n_epochs": len(epochs), "meta": meta}


def read_all_yolo() -> list[dict]:
    runs = []
    if MODELS_DIR.exists():
        for d in sorted(MODELS_DIR.iterdir()):
            if d.is_dir() and d.name != "classifier":
                r = _read_yolo_run(d)
                if r:
                    runs.append(r)
    return runs


def _load_ckpt_meta(bp: Path) -> dict:
    """读取 checkpoint 元数据，带 mtime 缓存。

    RA-001：监控绝不在每次请求时 torch.load（每 3 秒双请求曾导致 RSS 16GiB）。
    复核修订：缓存命中条件以 mtime/size 是否变化为唯一门槛；TTL 到期但文件
    未变化时不再重复 torch.load（与注释语义一致）。"""
    global _CKPT_CACHE, _CKPT_CACHE_AT
    try:
        st = bp.stat()
    except OSError:
        return {}
    now = time.time()
    if _CKPT_CACHE and _CKPT_CACHE.get("mtime") == st.st_mtime \
            and _CKPT_CACHE.get("size") == st.st_size:
        _CKPT_CACHE_AT = now  # 文件未变化：续期缓存，不重新加载
        return _CKPT_CACHE
    meta: dict = {"mtime": st.st_mtime, "size": st.st_size}
    try:
        import torch
        ck = torch.load(str(bp), map_location="cpu", weights_only=False)
        if isinstance(ck, dict):
            meta["val_acc"] = ck.get("val_acc")
            meta["epoch"] = ck.get("epoch")
            meta["backbone"] = ck.get("backbone")
            meta["n_classes"] = ck.get("n_classes")
        del ck
    except Exception:
        pass
    _CKPT_CACHE = meta
    _CKPT_CACHE_AT = now
    return meta


def read_classifier() -> dict | None:
    clf_dir = MODELS_DIR / "classifier"
    if not clf_dir.exists():
        return None
    result = {"running": False, "epochs": [], "best_acc": 0.0, "best_epoch": 0, "backbone": None}
    # 从 training_history.json 读取（逐轮写入）
    for hf in sorted(clf_dir.glob("training_history*.json")):
        try:
            data = json.loads(hf.read_text(encoding="utf-8"))
        except Exception:
            continue
        # 兼容新旧格式
        if isinstance(data, list):
            eps = data
            running = False
            backbone = None
            best_acc = max((e.get("val_acc", 0) for e in eps), default=0)
            best_epoch = max(eps, key=lambda e: e.get("val_acc", 0)).get("epoch", 0) if eps else 0
        else:
            eps = data.get("epochs", [])
            running = data.get("running", False)
            backbone = data.get("backbone")
            best_acc = data.get("best_acc", max((e.get("val_acc", 0) for e in eps), default=0))
            best_epoch = data.get("best_epoch", 0)
        if eps:
            result = {"running": running, "epochs": eps, "best_acc": best_acc,
                      "best_epoch": best_epoch, "backbone": backbone, "history_file": hf.name}
    # RA-021：展示的 best 必须取自当前 best.pt（实际线上权重）；历史文件里的
    # 最佳值（含旧数据轮的 92.95%）只作为 history_best_acc 参考，绝不两者混展。
    bp = clf_dir / "best.pt"
    if bp.exists():
        ck = _load_ckpt_meta(bp)
        if ck.get("val_acc") is not None:
            if result.get("best_acc"):
                result["history_best_acc"] = result["best_acc"]
            result["best_acc"] = float(ck["val_acc"])
        if ck.get("epoch") is not None:
            result["best_epoch"] = ck["epoch"]
        result["backbone"] = result["backbone"] or ck.get("backbone")
        if ck.get("n_classes"):
            result["n_classes"] = ck["n_classes"]
    return result if (result["epochs"] or result["best_acc"]) else None


def check_services() -> dict:
    status = {}
    for name, port in SERVICES.items():
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="GET")
            urllib.request.urlopen(req, timeout=1.5)
            status[name] = "up"
        except Exception:
            # 有些服务根路径返回 404 但服务是活的，尝试探测端口
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            code = s.connect_ex(("127.0.0.1", port))
            s.close()
            status[name] = "up" if code == 0 else "down"
    return status


def check_processes() -> dict:
    procs = {"yolo_training": False, "classifier_training": False}
    try:
        out = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5).stdout
        procs["yolo_training"] = "train_v1" in out
        procs["classifier_training"] = "cascade.classifier" in out
    except Exception:
        pass
    return procs


def overview() -> dict:
    yolo_runs = read_all_yolo()
    classifier = read_classifier()
    services = check_services()
    procs = check_processes()
    # 当前最佳 YOLO
    best_yolo = max(yolo_runs, key=lambda r: r["best"]["map50"]) if yolo_runs else None
    return {
        "yolo_runs": yolo_runs,
        "best_yolo": {"run": best_yolo["run"], "map50": best_yolo["best"]["map50"],
                      "epoch": best_yolo["best"]["epoch"]} if best_yolo else None,
        "classifier": classifier,
        "services": services,
        "processes": procs,
        "timestamp": time.time(),
    }


def read_live_yolo() -> dict:
    """YOLO 检测训练实时进度（自动检测，无需手动配置）。无活跃则 active=False。"""
    procs = check_processes()
    if not procs.get("yolo_training"):
        return {"type": "yolo", "active": False}
    logs = _find_yolo_logs()
    if not logs:
        return {"type": "yolo", "active": False}
    live = _parse_yolo_log(logs[0])
    if not live:
        return {"type": "yolo", "active": False}
    live["active"] = live["age_sec"] <= 600
    run = live.get("name")
    rd = _read_yolo_run(MODELS_DIR / run) if run else None
    if rd and rd.get("epochs"):
        last = rd["epochs"][-1]
        live["last_map50"] = last["map50"]
        live["last_recall"] = last["recall"]
        live["last_done_epoch"] = last["epoch"]
        live["best_map50"] = rd["best"]["map50"]
        live["best_epoch"] = rd["best"]["epoch"]
    return live


def read_live_classifier() -> dict:
    """级联分类器实时进度（自动检测）。无活跃则 active=False。"""
    lf = MODELS_DIR / "classifier" / "live_progress.json"
    hf = MODELS_DIR / "classifier" / "training_history.json"
    live = {"type": "classifier"}
    if lf.exists():
        try:
            loaded = json.loads(lf.read_text(encoding="utf-8"))
            loaded["type"] = "classifier"
            live = loaded
        except Exception:
            pass
    age = time.time() - live.get("updated_at", 0) if live.get("updated_at") else 999999
    live["age_sec"] = round(age)
    finished = False
    best_acc = best_epoch = None
    n_epochs = 0
    if hf.exists():
        try:
            hd = json.loads(hf.read_text(encoding="utf-8"))
            eps = hd.get("epochs", [])
            n_epochs = len(eps)
            if eps:
                b = max(eps, key=lambda e: e.get("val_acc", 0))
                best_acc = b.get("val_acc")
                best_epoch = b.get("epoch")
            if hd.get("running") is False:
                finished = True
        except Exception:
            pass
    live["finished"] = finished
    live["best_acc"] = best_acc
    live["best_epoch"] = best_epoch
    # RA-021 复核修订：训练已结束（非活跃）时，live 展示的 best 必须取自当前生产
    # best.pt（真实线上权重），旧训练历史降级为 history_best_acc，不得混展。
    if finished:
        meta = _load_ckpt_meta(MODELS_DIR / "classifier" / "best.pt")
        if meta.get("val_acc") is not None:
            live["history_best_acc"] = best_acc
            live["best_acc"] = float(meta["val_acc"])
            live["best_epoch"] = meta.get("epoch")
            live["best_source"] = "current_best_pt"
        else:
            live["best_source"] = "history_file"
        live["final_epochs"] = n_epochs
        live["active"] = False
    else:
        live["best_source"] = "live_history"
        live["active"] = age <= 120
    return live


def read_live() -> dict:
    """返回当前活跃训练的实时进度（概览用）：优先 YOLO，其次分类器。"""
    yl = read_live_yolo()
    if yl.get("active"):
        return yl
    cl = read_live_classifier()
    if cl.get("active"):
        return cl
    # 无活跃：返回最近有数据的（完成态）
    return yl if yl.get("epoch") else cl


# ---- YOLO 训练日志实时解析 ----
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
_YOLO_PROG_RE = re.compile(
    r'(\d+)/(\d+)\s+([\d.]+)G\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+):\s*(\d+)%[^\d]*?(\d+)/(\d+)\s+([\d.]+)s/it'
)


def _find_yolo_logs() -> list:
    """找所有 YOLO 训练日志（.models/*_train.log），按更新时间降序。"""
    logs = []
    for lf in MODELS_DIR.glob("*_train.log"):
        try:
            logs.append((lf.stat().st_mtime, lf))
        except Exception:
            pass
    logs.sort(reverse=True)
    return [lf for _, lf in logs]


def _parse_yolo_log(log_path: Path) -> dict | None:
    """解析带 ANSI 的训练日志，提取最新轮内进度。"""
    try:
        data = log_path.read_bytes().decode('utf-8', 'ignore')
    except Exception:
        return None
    tail = _ANSI_RE.sub('', data[-30000:])
    segs = re.split(r'[\r\n]+', tail)
    last = None
    for s in segs:
        m = _YOLO_PROG_RE.search(s)
        if m:
            last = m
    if not last:
        return None
    try:
        epoch, total_ep = int(last.group(1)), int(last.group(2))
        box_loss, cls_loss = float(last.group(4)), float(last.group(5))
        batch, total_batches = int(last.group(10)), int(last.group(11))
        rate = float(last.group(12))
    except (ValueError, IndexError):
        return None
    eta_sec = int(rate * max(0, total_batches - batch))
    try:
        mtime = log_path.stat().st_mtime
    except Exception:
        mtime = time.time()
    run_name = log_path.stem
    if run_name.endswith("_train"):
        run_name = run_name[:-6]
    return {
        "type": "yolo",
        "name": run_name,
        "epoch": epoch, "total_epochs": total_ep,
        "batch": batch, "total_batches": total_batches,
        "epoch_progress": round(batch / total_batches, 4) if total_batches else 0,
        "box_loss": box_loss, "cls_loss": cls_loss,
        "eta_epoch_sec": eta_sec,
        "age_sec": round(time.time() - mtime),
        "updated_at": mtime,
    }


def read_progress() -> dict:
    """读取项目实施进度（.models/progress.json），并动态补充分类器实时指标。"""
    pf = MODELS_DIR / "progress.json"
    if not pf.exists():
        return {}
    try:
        prog = json.loads(pf.read_text(encoding="utf-8"))
    except Exception:
        return {}
    # 动态补充分类器实时 val_acc 到 models
    clf = read_classifier()
    if clf and clf.get("best_acc"):
        for m in prog.get("models", []):
            if m.get("name") == "级联分类器":
                m["metric"] = f"val_acc={clf['best_acc']*100:.1f}% @ ep{clf.get('best_epoch', 0)}"
                m["status"] = "training" if clf.get("running") else "done"
    return prog


def read_datasets() -> list:
    """汇总各数据集规模（管理端用）。"""
    R = PROJECT_ROOT
    def count_dir(p):
        try:
            return sum(1 for _ in (R / p).iterdir()) if (R / p).exists() else 0
        except Exception:
            return 0
    def count_json(p, key=None):
        try:
            d = json.loads((R / p).read_text(encoding="utf-8"))
            return len(d) if not key else len(d.get(key, {}))
        except Exception:
            return 0
    out = []
    out.append({"name": "第一批训练数据", "kind": "原始 xlsx", "photos": 2947, "note": "208 SKU 基线"})
    out.append({"name": "第二批训练数据", "kind": "原始 xlsx", "photos": 6510, "note": "含第一批交叉"})
    out.append({"name": "第三批训练数据", "kind": "原始 xlsx", "photos": 22664, "note": "本轮清洗源"})
    out.append({"name": "batch3 清洗好图", "kind": "拦截后", "photos": count_json(".batch3_clean/clean_manifest.json"), "note": "过拦截器"})
    out.append({"name": "batch3 灰名单", "kind": "降采样", "photos": count_json("batch3_gray/gray_manifest.json"), "note": "50% 采样"})
    out.append({"name": "crop_dataset (GT框)", "kind": "分类裁剪", "photos": count_dir("crop_dataset/train"), "note": "分类器 v1 训练"})
    out.append({"name": "crop_dataset_yolo (YOLO框)", "kind": "分类裁剪", "photos": count_dir("crop_dataset_yolo/train"), "note": "分类器校准"})
    out.append({"name": "sku_v6 检测集", "kind": "YOLO", "photos": count_dir(".datasets/sku_v6/images/train"), "note": "召回专项"})
    return out


def read_models() -> list:
    """模型注册表（管理端用）：YOLO 各轮 + 分类器，含状态。"""
    out = []
    yl = read_live_yolo()
    active_yolo_run = yl.get("name") if yl.get("active") else None
    for r in read_all_yolo():
        status = "训练中" if r["run"] == active_yolo_run else ("冻结" if r["run"] == "sku_v4" else "历史")
        out.append({"name": r["run"], "type": "YOLO 检测", "metric": f"mAP50={r['best']['map50']:.4f}",
                    "epoch": r["best"]["epoch"], "epochs": r["n_epochs"], "status": status})
    cl = read_classifier()
    if cl:
        cl_active = read_live_classifier().get("active")
        out.append({"name": "ResNet18 分类器", "type": "级联分类", "metric": f"val_acc={cl['best_acc']*100:.2f}%",
                    "epoch": cl.get("best_epoch", 0), "epochs": len(cl.get("epochs", [])),
                    "status": "训练中" if cl_active else "已收敛"})
    return out


def read_intercept() -> dict:
    """第三批拦截报告（质量护栏）。"""
    p = PROJECT_ROOT / ".batch3_clean" / "intercept_report.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_confusion() -> list:
    """分类器 Top 混淆对。"""
    p = PROJECT_ROOT / ".eval" / "batch2" / "confusion_matrix.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("confusion", [])[:10]
    except Exception:
        return []


def read_config() -> dict:
    """当前 YOLO 训练配置。"""
    p = MODELS_DIR / "sku_v6" / "train_meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_hardcase() -> dict:
    """难例 SKU 关注表。"""
    p = MODELS_DIR / "hardcase_watchlist.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


class H(BaseHTTPRequestHandler):
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

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        try:
            if path in ("", "/index.html"):
                return self._send(200, HTML.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            if path == "/api/overview":
                return self._send(200, json.dumps(overview(), ensure_ascii=False))
            if path == "/api/progress":
                return self._send(200, json.dumps(read_progress(), ensure_ascii=False))
            if path == "/api/live":
                return self._send(200, json.dumps(read_live(), ensure_ascii=False))
            if path == "/api/yolo":
                return self._send(200, json.dumps(read_all_yolo(), ensure_ascii=False))
            if path == "/api/classifier":
                return self._send(200, json.dumps(read_classifier() or {}, ensure_ascii=False))
            if path == "/api/live/yolo":
                return self._send(200, json.dumps(read_live_yolo(), ensure_ascii=False))
            if path == "/api/live/classifier":
                return self._send(200, json.dumps(read_live_classifier(), ensure_ascii=False))
            if path == "/api/datasets":
                return self._send(200, json.dumps(read_datasets(), ensure_ascii=False))
            if path == "/api/models":
                return self._send(200, json.dumps(read_models(), ensure_ascii=False))
            if path == "/api/services":
                return self._send(200, json.dumps({"services": check_services(), "processes": check_processes()}, ensure_ascii=False))
            if path == "/api/intercept":
                return self._send(200, json.dumps(read_intercept(), ensure_ascii=False))
            if path == "/api/confusion":
                return self._send(200, json.dumps(read_confusion(), ensure_ascii=False))
            if path == "/api/config":
                return self._send(200, json.dumps(read_config(), ensure_ascii=False))
            if path == "/api/hardcase":
                return self._send(200, json.dumps(read_hardcase(), ensure_ascii=False))
            if path == "/api/status":
                ov = overview()
                # 兼容旧版：返回当前活跃训练
                active = None
                if ov["classifier"] and ov["classifier"].get("running"):
                    active = "classifier"
                return self._send(200, json.dumps({
                    "active": active, "services": ov["services"], "processes": ov["processes"],
                    "best_yolo": ov["best_yolo"],
                    "classifier_best": ov["classifier"]["best_acc"] if ov["classifier"] else None,
                }, ensure_ascii=False))
            self._send(404, '{"error":"not found"}')
        except Exception as e:
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


def serve(host="127.0.0.1", port=8092):
    ThreadingHTTPServer.allow_reuse_address = True
    s = ThreadingHTTPServer((host, port), H)
    print(f"统一训练监控 http://{host}:{port}")
    print(f"  监控: YOLO 检测训练 + 级联分类器 + 系统状态")
    s.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    serve(a.host, a.port)
