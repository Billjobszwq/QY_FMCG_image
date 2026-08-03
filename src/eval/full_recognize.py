"""全量识别：对全部训练照片运行 YOLO 识别，输出与训练数据同构的 xlsx + 对比用 JSON。

输出：
  .eval/full_recognize.json   每张照片的预测框 + 真值（供 compare.py 对比）
  .eval/full_recognize.xlsx   与训练数据同构的识别结果（ID/SName/TypeName/name/x/y/...）

用法：
  python -m src.eval.full_recognize                # 全部照片
  python -m src.eval.full_recognize --limit 100    # 前 100 张
  python -m src.eval.full_recognize --conf 0.25
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

TRAINING_DATA = PROJECT_ROOT / ".training_data"
EVAL_DIR = PROJECT_ROOT / ".eval"


def run(conf: float = 0.25, limit: int | None = None, imgsz: int = 640, weight: str | None = None):
    if weight:
        # 用指定权重加载独立检测器（评估特定训练轮次，不影响生产模型）
        import io as _io
        import numpy as _np
        from PIL import Image as _Image
        from ultralytics import YOLO as _YOLO
        from ..common.config import PROJECT_ROOT as _PR
        reg = json.loads((_PR / "data" / "sku_registry.json").read_text(encoding="utf-8"))
        id_to_name = {v["class_id"]: k for k, v in reg.items()}
        id_to_sku = {v["class_id"]: v["sku_id"] for k, v in reg.items()}
        _m = _YOLO(weight)
        def detect_and_recognize(image_bytes, conf=0.25, imgsz=640):
            arr = _np.array(_Image.open(_io.BytesIO(image_bytes)).convert("RGB"))
            rs = _m.predict(arr, conf=conf, imgsz=imgsz, verbose=False, device="cpu")
            out = []
            for r in rs:
                if r.boxes is None:
                    continue
                for box, cls, sc in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                    cid = int(cls)
                    out.append({"box": [round(v, 1) for v in box], "sku_id": id_to_sku.get(cid, ""),
                                "name": id_to_name.get(cid, f"unknown_{cid}"), "class_id": cid, "confidence": round(float(sc), 4)})
            out.sort(key=lambda p: -p["confidence"])
            return out
        print(f"[评估权重] {weight}")
    else:
        from ..recognize.service import detect_and_recognize

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    man = json.loads((TRAINING_DATA / "manifest.json").read_text(encoding="utf-8"))
    photos = man["photos"]
    keys = list(photos.keys())
    if limit:
        keys = keys[:limit]

    records = []  # 对比用：每张含 predictions + ground_truth
    xlsx_rows = []  # 同构 xlsx 行
    n = len(keys)
    t0 = time.time()
    for i, k in enumerate(keys):
        p = photos[k]
        img = p.get("image", {})
        sha = img.get("sha256")
        W = img.get("width") or 1500
        H = img.get("height") or 2000
        if not sha:
            continue
        blob = TRAINING_DATA / "blobs" / sha[:2] / sha
        if not blob.exists():
            continue
        img_bytes = blob.read_bytes()
        try:
            products = detect_and_recognize(img_bytes, conf=conf, imgsz=imgsz)
        except Exception:
            products = []
        meta = p.get("meta", {})
        gt = p.get("annotations", [])

        pred_boxes = []
        for pr in products:
            x1, y1, x2, y2 = pr["box"]
            pred_boxes.append({"box": [x1, y1, x2, y2], "name": pr["name"], "sku_id": pr["sku_id"], "conf": pr["confidence"]})
            xlsx_rows.append({
                "ID": k, "SName": meta.get("sname", ""), "TypeName": meta.get("typename", ""),
                "TypeValue": p.get("filename", ""), "name": pr["name"], "sku_id": pr["sku_id"],
                "x": round((x1 + x2) / 2), "y": round((y1 + y2) / 2),
                "box": json.dumps([round(v) for v in pr["box"]]), "confidence": pr["confidence"],
            })
        records.append({
            "id": k, "W": W, "H": H, "meta": meta,
            "predictions": pred_boxes,
            "ground_truth": [{"name": a.get("name"), "x": a.get("x"), "y": a.get("y")} for a in gt],
        })
        if (i + 1) % 50 == 0 or i == n - 1:
            elapsed = time.time() - t0
            print(f"  进度 {i+1}/{n} ({(i+1)/n*100:.0f}%) 已用 {elapsed:.0f}s", flush=True)

    # 保存 JSON
    out_json = EVAL_DIR / "full_recognize.json"
    out_json.write_text(json.dumps({"conf": conf, "records": records}, ensure_ascii=False), encoding="utf-8")
    # 保存 xlsx
    _write_xlsx(records, xlsx_rows)
    total_pred = sum(len(r["predictions"]) for r in records)
    total_gt = sum(len(r["ground_truth"]) for r in records)
    print(f"\n=== 全量识别完成 ===")
    print(f"  照片: {len(records)}, 预测框: {total_pred}, 真值标注: {total_gt}")
    print(f"  JSON: {out_json}")
    print(f"  xlsx: {EVAL_DIR / 'full_recognize.xlsx'}")
    return {"photos": len(records), "predictions": total_pred, "ground_truth": total_gt}


def _write_xlsx(records, rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "识别结果"
    cols = ["ID", "SName", "TypeName", "TypeValue", "name", "sku_id", "x", "y", "box", "confidence"]
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    wb.save(str(EVAL_DIR / "full_recognize.xlsx"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--weight", default=None, help="指定 YOLO 权重路径（评估特定训练轮次）")
    a = ap.parse_args()
    run(a.conf, a.limit, a.imgsz, a.weight)
