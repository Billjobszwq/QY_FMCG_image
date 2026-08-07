"""照片导入 Label Studio：从训练数据 manifest / xlsx 读取照片，上传为 task。

支持把现有点标注（name/x/y，假设 100% 准确）转换为 LS 预标注矩形（含 SKU taxonomy + status）。
LS 的矩形坐标用百分比（相对图片宽高）。

RA-015：幂等 + 批量：
- 导入前一次性建立远端 task 文件名索引（O(N)，非每图分页搜索的 O(N²)）
- 以稳定文件名（照片 ID + 内容后缀）作为幂等键：已存在 → skipped，不重复创建
- 批量上传（默认每批 16 张）；导入报告明确 created/skipped/failed

用法：
  python -m src.ls_platform.importer --limit 3            # 导入 3 张（含真值预标注）测试
  python -m src.ls_platform.importer --limit 0            # 导入全部
  python -m src.ls_platform.importer --no-predictions     # 仅导入图片，不带预标注
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..common.config import PROJECT_ROOT
from .ls_client import LSClient

TRAINING_DATA = PROJECT_ROOT / ".training_data"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"

# 点标注 → 框的比例启发式（与训练一致）
BOX_W_FRAC = 0.07
BOX_H_FRAC = 0.18


def _load_registry_names():
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return set(reg.keys())


def _point_to_pct_box(x, y, W, H):
    """像素点 → LS 百分比框 (x, y, width, height, 均为百分比)。"""
    bw = BOX_W_FRAC * W
    bh = BOX_H_FRAC * H
    x1 = max(0, x - bw / 2)
    y1 = max(0, y - bh / 2)
    x2 = min(W, x + bw / 2)
    y2 = min(H, y + bh / 2)
    return {
        "x": x1 / W * 100,
        "y": y1 / H * 100,
        "width": (x2 - x1) / W * 100,
        "height": (y2 - y1) / H * 100,
        "rotation": 0,
    }


def _build_prediction_result(ann, W, H, sku_names):
    """把一个点标注转成 LS prediction result（rectanglelabels + sku taxonomy + status）。"""
    box = _point_to_pct_box(ann["x"], ann["y"], W, H)
    name = ann.get("name", "")
    rid = f"region_{int(ann['x'])}_{int(ann['y'])}"
    result = [{
        "id": rid,
        "from_name": "box",
        "to_name": "image",
        "type": "rectanglelabels",
        "value": {**box, "rectanglelabels": ["product"]},
    }]
    if name in sku_names:
        result.append({
            "id": rid,
            "from_name": "sku",
            "to_name": "image",
            "type": "taxonomy",
            "value": {**box, "taxonomy": [[name]]},
        })
    result.append({
        "id": rid,
        "from_name": "status",
        "to_name": "image",
        "type": "choices",
        "value": {**box, "choices": ["unreviewed"]},
    })
    return result


def import_photos(limit: int = 3, with_predictions: bool = True, project_id: int | None = None,
                  batch_size: int = 16):
    import os
    pid = project_id or int(os.environ.get("LABEL_STUDIO_PROJECT_ID", "1"))
    client = LSClient()
    sku_names = _load_registry_names()

    manifest = json.loads((TRAINING_DATA / "manifest.json").read_text(encoding="utf-8"))
    photos = manifest["photos"]
    keys = list(photos.keys())
    if limit and limit > 0:
        keys = keys[:limit]

    # RA-015：一次性建远端索引（O(N)），同名文件幂等跳过
    print("[import] 建立远端 task 索引 ...")
    index = client.index_task_images(pid)
    print(f"  已有 task: {len(index)}")

    created = skipped = failed = predicted = 0
    pending: list[tuple[str, str, bytes]] = []  # (photo_key, filename, data)

    def flush(batch):
        """批量上传 → 重建索引差集定位新 task → 附预标注。"""
        nonlocal created, failed, predicted
        if not batch:
            return
        files = [(fn, data) for _, fn, data in batch]
        try:
            client.import_files(pid, files)
        except Exception as e:
            failed += len(batch)
            print(f"  [fail] 批量上传 {len(batch)} 张失败: {e}")
            return
        new_index = client.index_task_images(pid)
        for k, fn, _ in batch:
            task = new_index.get(fn)
            if not task:
                failed += 1
                print(f"  [fail] {k}: 上传后未找到 task")
                continue
            created += 1
            task_id = task.get("id")
            if with_predictions and task_id:
                anns = photos[k].get("annotations", [])
                img = photos[k].get("image", {})
                W = img.get("width") or 1500
                H = img.get("height") or 2000
                results = []
                for ann in anns:
                    if ann.get("x") is None or ann.get("y") is None:
                        continue
                    results.extend(_build_prediction_result(ann, W, H, sku_names))
                if results:
                    try:
                        client.create_prediction(task_id, results, score=0.6,
                                                 model_version="external_seed_xlsx")
                        predicted += 1
                    except Exception as e:
                        print(f"  [warn] {k} 预标注失败: {e}")

    for k in keys:
        p = photos[k]
        img = p.get("image", {})
        sha = img.get("sha256")
        if not sha:
            failed += 1
            continue
        blob = TRAINING_DATA / "blobs" / sha[:2] / sha
        if not blob.exists():
            failed += 1
            continue
        data = blob.read_bytes()
        ext = "jpg" if data[:3] == b"\xff\xd8\xff" else "png"
        fn = f"{k}.{ext}"  # 稳定幂等键：照片 ID + 内容类型
        if fn in index:
            skipped += 1
            continue
        pending.append((k, fn, data))
        if len(pending) >= batch_size:
            flush(pending)
            pending = []
    flush(pending)

    report = {"created": created, "skipped": skipped, "failed": failed,
              "predicted": predicted, "project_id": pid}
    print(f"\n=== 导入完成 (RA-015 幂等报告) ===")
    print(f"  created={created} skipped={skipped} failed={failed} predicted={predicted}")
    print(f"  项目: {client.url}/projects/{pid}/data")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3, help="导入照片数，0=全部")
    ap.add_argument("--no-predictions", action="store_true", help="不带真值预标注")
    ap.add_argument("--project-id", type=int, default=None)
    a = ap.parse_args()
    import_photos(a.limit, with_predictions=not a.no_predictions, project_id=a.project_id)
