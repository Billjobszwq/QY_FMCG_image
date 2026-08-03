"""识别与训练任务执行器：供编排层后台调用。

- recognize_job: 对一批照片运行 YOLO 识别，输出与训练数据同构的结果（含 xlsx）。
- train_job: 从 LS 导出数据集或复用现有数据集，触发训练并登记模型。
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

from ..common.config import PROJECT_ROOT
from . import jobs

TRAINING_DATA = PROJECT_ROOT / ".training_data"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
# RA-007：失败率超过此门槛时任务不得标记成功
FAILURE_THRESHOLD = 0.05


def _load_manifest_photos():
    man = json.loads((TRAINING_DATA / "manifest.json").read_text(encoding="utf-8"))
    return man["photos"]


def _blob_bytes(sha):
    p = TRAINING_DATA / "blobs" / sha[:2] / sha
    return p.read_bytes() if p.exists() else None


def recognize_job(job_id: str, update, asset_ids: list[str] | None = None, conf: float = 0.25,
                  limit: int | None = None):
    """对指定照片（或全部）运行识别，结果存 JSON + xlsx。

    RA-007：逐项四态 success/empty/failed（含 retryable 标记）；推理异常绝不静默变空结果；
    失败率超 FAILURE_THRESHOLD 时任务失败。每张照片都写审计（含失败事件，RA-017）。"""
    import uuid
    from ..recognize.service import detect_and_recognize, _write_audit, ModelUnavailableError

    photos = _load_manifest_photos()
    keys = asset_ids if asset_ids else list(photos.keys())
    if limit:
        keys = keys[:limit]

    rows = []  # 与训练数据同构的行
    counts = {"success": 0, "empty": 0, "failed": 0}
    failures: list[dict] = []
    n = len(keys)
    for i, k in enumerate(keys):
        p = photos.get(k)
        if not p:
            counts["failed"] += 1
            failures.append({"asset": k, "error": "asset_not_found", "retryable": False})
            continue
        sha = (p.get("image") or {}).get("sha256")
        img = _blob_bytes(sha) if sha else None
        if not img:
            counts["failed"] += 1
            failures.append({"asset": k, "error": "blob_missing", "retryable": True})
            _write_audit(uuid.uuid4().hex, k, {}, [], {"status": "failed", "error": "blob_missing"})
            continue
        run_id = uuid.uuid4().hex
        try:
            products = detect_and_recognize(img, conf=conf)
            status = "success" if products else "empty"
        except ModelUnavailableError as e:
            counts["failed"] += 1
            failures.append({"asset": k, "error": f"ModelUnavailableError: {e}", "retryable": False})
            _write_audit(run_id, k, {}, [], {"status": "failed",
                                             "error": f"ModelUnavailableError: {e}"})
            continue
        except Exception as e:
            counts["failed"] += 1
            failures.append({"asset": k, "error": f"{type(e).__name__}: {e}", "retryable": True})
            _write_audit(run_id, k, {}, [], {"status": "failed",
                                             "error": f"{type(e).__name__}: {e}"})
            continue
        counts[status] += 1
        # 审计（失败时 _write_audit 返回 False，显式记入 failures 而非静默）
        if not _write_audit(run_id, k, {"job": job_id}, products, {"status": status, "conf": conf}):
            failures.append({"asset": k, "error": "audit_write_failed", "retryable": True,
                             "note": "识别已完成但审计落库失败"})
        meta = p.get("meta", {})
        for pr in products:
            x1, y1, x2, y2 = pr["box"]
            rows.append({
                "ID": k,
                "SName": meta.get("sname", ""),
                "TypeName": meta.get("typename", ""),
                "TypeValue": p.get("filename", ""),
                "name": pr["name"],
                "sku_id": pr["sku_id"],
                "x": round((x1 + x2) / 2),
                "y": round((y1 + y2) / 2),
                "box": json.dumps([round(v) for v in pr["box"]]),
                "confidence": pr["confidence"],
                "needs_review": pr.get("needs_review", False),
            })
        if (i + 1) % 10 == 0 or i == n - 1:
            update(progress=int((i + 1) / n * 100))

    fail_rate = counts["failed"] / n if n else 0.0
    # 保存 JSON 结果（含四态统计与可追踪失败项）
    jobs.save_result(job_id, {"rows": rows, "count": len(rows), "photos": n, "conf": conf,
                              "statuses": counts, "failures": failures, "fail_rate": fail_rate})
    # 生成 xlsx
    xlsx_path = _write_xlsx(job_id, rows)
    # RA-007：失败率超门槛→任务失败，绝不把静默丢数据当成功
    if fail_rate > FAILURE_THRESHOLD:
        raise RuntimeError(
            f"识别失败率 {fail_rate:.1%} 超过门槛 {FAILURE_THRESHOLD:.0%}：{counts}，"
            f"失败项已记录于 job result failures，任务不得视为成功")
    return {"rows": len(rows), "photos": n, "xlsx": str(xlsx_path), "conf": conf,
            "statuses": counts, "fail_rate": fail_rate}


def _write_xlsx(job_id: str, rows: list[dict]) -> Path:
    """输出与训练数据同构的 xlsx。"""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "识别结果"
    cols = ["ID", "SName", "TypeName", "TypeValue", "name", "sku_id", "x", "y", "box",
            "confidence", "needs_review"]
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    out = jobs.RESULTS_DIR / f"{job_id}.xlsx"
    wb.save(str(out))
    return out


def train_job(job_id: str, update, dataset_yaml: str | None = None, epochs: int = 80,
              batch: int = 8, imgsz: int = 640, model: str = "yolo26m.pt"):
    """触发训练。ISSUE-001：必须显式指定 dataset_yaml，禁止隐式默认数据集。"""
    from ..training.train_v1 import train

    update(progress=5)
    if not dataset_yaml:
        raise ValueError("训练任务必须显式传入 dataset_yaml（ISSUE-001），拒绝使用隐式默认数据集")
    yaml = dataset_yaml
    mv_id = train(data_yaml=yaml, epochs=epochs, imgsz=imgsz, batch=batch, device="mps",
                  model_name=model, require_explicit_data=True,
                  dataset_desc=f"platform:{job_id}")
    update(progress=95)
    return {"model_version": mv_id, "dataset": yaml, "epochs": epochs}


def retrain_job(job_id: str, update, project_id: int, out_name: str = "ls_retrain",
                epochs: int = 80, batch: int = 8, imgsz: int = 640, model: str = "yolo26m.pt",
                auto_switch: bool = True):
    """再训练闭环：导出 LS 已审核标注 → 生成 YOLO 数据集 → 训练 → 登记模型 → 热切换。

    这是“审核-修正-再训练”闭环的核心：人工在 LS 修正后的标注成为新训练源。
    """
    from ..data import warehouse as wh
    from ..training.train_v1 import train
    from .exporter import export_yolo

    # 1. 导出已审核标注
    update(progress=10)
    summary = export_yolo(project_id=project_id, out_name=out_name, val_ratio=0.1, only_matched=True)
    if summary["tasks_with_ann"] == 0:
        raise RuntimeError("LS 项目中没有已审核的标注，无法再训练（请先在 LS 中审核/修正并提交标注）")
    update(progress=30)

    # 2. 训练（ISSUE-001：显式传入本次导出的数据集，禁止隐式默认）
    yaml = str(PROJECT_ROOT / ".datasets" / out_name / "data.yaml")
    mv_id = train(data_yaml=yaml, epochs=epochs, imgsz=imgsz, batch=batch, device="mps",
                  model_name=model, require_explicit_data=True,
                  dataset_desc=f"label-studio:{project_id}:{out_name}")
    update(progress=90)

    # 3. 热切换（ISSUE-001：先重新读取登记记录，确认本次 mv 的数据版本就是本次导出数据集）
    switched = False
    if auto_switch and mv_id:
        try:
            from ..training.train_v1 import validate_dataset
            ds_info = validate_dataset(yaml)
            expected_dv = f"dataset:{ds_info['dataset_hash']}"
            conn = wh.connect()
            wh.migrate(conn)
            row = conn.execute("SELECT data_version FROM model_version WHERE mv_id=?", (mv_id,)).fetchone()
            if row and row[0] == expected_dv:
                conn.execute("UPDATE model_version SET status='retired' "
                             "WHERE task='detect_208sku' AND status='production' AND mv_id<>?", (mv_id,))
                conn.execute("UPDATE model_version SET status='production' WHERE mv_id=?", (mv_id,))
                conn.commit()
                switched = True
            conn.close()
        except Exception:
            switched = False
    update(progress=100)
    return {
        "model_version": mv_id, "dataset": yaml, "epochs": epochs,
        "exported": summary, "auto_switched": switched,
    }
