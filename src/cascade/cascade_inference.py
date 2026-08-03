"""级联推理：YOLO 画框（冻结 v4）→ 裁剪 224x224 → 分类器精识别 → 拒识门禁。

流程：
  输入图像 → YOLO 检测画框 → 逐框裁剪等比缩放 224x224 → 分类器输出 SKU + 置信度
  RA-004：置信度 < 阈值或 top1-top2 margin 过小 → 输出 unknown/needs_review，
  绝不回退 detector 类别充当最终 SKU 决策。

用法：
  python -m src.cascade.cascade_inference --test [--limit 20]   # 一对一匹配评估（RA-005）
  python -m src.cascade.cascade_inference --image <path>        # 单图推理
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torchvision import transforms

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from .classifier import build_model

CROP_DIR = PROJECT_ROOT / "crop_dataset"
CLF_WEIGHT = PROJECT_ROOT / ".models" / "classifier" / "best.pt"
CLF_CLASSES = PROJECT_ROOT / ".models" / "classifier" / "classes.json"
YOLO_WEIGHT = PROJECT_ROOT / ".models" / "sku_v4" / "weights" / "best.pt"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]
CONF_THRESHOLD = 0.6  # 接受阈值（可在 bundle thresholds 中校准）
MARGIN_THRESHOLD = 0.05  # top1-top2 最小间隔，低于此值视为不确定（RA-004）
UNKNOWN_CLASS = "__unknown__"  # unknown 契约：该类永远不得 accepted，一律 needs_review


def gate_decision(clf_sku_id: str, conf_val: float, margin: float,
                  conf_thr: float = CONF_THRESHOLD,
                  margin_thr: float = MARGIN_THRESHOLD) -> tuple[str, str]:
    """拒识门禁纯函数（RA-004 + unknown 契约），返回 (status, source)。

    规则：top1 为 __unknown__ → 永远 needs_review（无论置信度）；
    conf 达阈且 margin 达阈 → accepted；其余一律 needs_review。"""
    if clf_sku_id == UNKNOWN_CLASS:
        return "needs_review", "unknown_class"
    if conf_val >= conf_thr and margin >= margin_thr:
        return "accepted", "classifier"
    if conf_val < conf_thr:
        return "needs_review", "needs_review_lowconf"
    return "needs_review", "needs_review_lowmargin"


class CascadeRecognizer:
    """级联识别器：YOLO 画框 + 分类器精识别。

    复核修订（RA-006）：registry 可由调用方传入（bundle 自带），不再强制读取
    项目根全局 data/sku_registry.json；构造时校验 classifier classes / detector names
    与 registry 完全一致，不一致即失败关闭。"""

    def __init__(self, yolo_weight=None, clf_weight=None, conf_thr=CONF_THRESHOLD,
                 margin_thr=MARGIN_THRESHOLD, device=None, registry=None):
        from ultralytics import YOLO
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.conf_thr = conf_thr
        self.margin_thr = margin_thr
        # YOLO 画框器（冻结）
        self.yolo = YOLO(str(yolo_weight or YOLO_WEIGHT))
        # 分类器
        ckpt = torch.load(str(clf_weight or CLF_WEIGHT), map_location=self.device, weights_only=False)
        self.classes = ckpt["classes"]
        self.n_classes = ckpt["n_classes"]
        self.backbone = ckpt.get("backbone", "resnet18")
        self.clf = build_model(self.backbone, self.n_classes).to(self.device)
        self.clf.load_state_dict(ckpt["model"])
        self.clf.eval()
        # registry：优先使用调用方传入（bundle 自包含），无则退回全局（兼容旧路径）
        if registry is not None:
            reg = registry
        else:
            reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.id_to_name = {v["sku_id"]: k for k, v in reg.items()}
        self.clsid_to_name = {v["class_id"]: k for k, v in reg.items()}
        self.clsid_to_id = {v["class_id"]: v["sku_id"] for k, v in reg.items()}
        self._validate_class_alignment(reg)
        self.tf = transforms.Compose([
            transforms.Resize(int(224 * 1.14)), transforms.CenterCrop(224),
            transforms.ToTensor(), transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ])

    def _validate_class_alignment(self, reg: dict) -> None:
        """RA-006：类别一致性校验 —— classifier classes / detector names 必须与 registry 对齐。

        允许 classifier 在 208 类基础上额外携带 __unknown__（209 类方案）；
        任何超出集合的类别或顺序错乱都拒绝上线（fail-closed）。"""
        reg_sku_ids = {v["sku_id"] for v in reg.values()}
        cls_set = set(self.classes)
        extra = cls_set - reg_sku_ids - {UNKNOWN_CLASS}
        if extra:
            raise ValueError(f"分类器类别超出 registry: {sorted(extra)[:5]}（共 {len(extra)} 个）")
        missing = reg_sku_ids - cls_set
        if missing:
            raise ValueError(f"分类器缺少 registry 类别: {sorted(missing)[:5]}（共 {len(missing)} 个）")
        if len(set(self.classes)) != len(self.classes):
            raise ValueError("分类器类别列表存在重复")
        if hasattr(self.yolo, "names") and self.yolo.names:
            yolo_names = set(self.yolo.names.values()) if isinstance(self.yolo.names, dict) \
                else set(self.yolo.names)
            yolo_extra = yolo_names - set(reg.values() if isinstance(reg, list) else
                                          [k for k in reg.keys()])
            if yolo_extra:
                raise ValueError(f"检测器 names 超出 registry: {sorted(yolo_extra)[:5]}")

    def _crop_resize(self, img, box):
        W, H = img.size
        x1, y1, x2, y2 = [max(0, min(int(v), W if i % 2 else W)) for i, v in enumerate(box)]
        x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
        x2, y2 = min(W, int(box[2])), min(H, int(box[3]))
        if x2 - x1 < 4 or y2 - y1 < 4:
            return None
        crop = img.crop((x1, y1, x2, y2))
        # 等比缩放至 224x224（与训练一致的填充方式）
        w, h = crop.size
        scale = 224 / max(w, h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        crop = crop.resize((nw, nh), Image.BILINEAR)
        canvas = Image.new("RGB", (224, 224), (114, 114, 114))
        canvas.paste(crop, ((224 - nw) // 2, (224 - nh) // 2))
        return canvas

    def recognize(self, image_bytes, conf=0.25):
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        # YOLO 画框
        rs = self.yolo.predict(arr, conf=conf, imgsz=960, verbose=False, device=self.device)
        results = []
        for r in rs:
            if r.boxes is None:
                continue
            for box, cls, sc in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                cls_id = int(cls)
                yolo_name = self.clsid_to_name.get(cls_id, f"unknown_{cls_id}")
                yolo_sku_id = self.clsid_to_id.get(cls_id, "")
                crop = self._crop_resize(img, box)
                if crop is None:
                    continue
                # 分类器精识别
                inp = self.tf(crop).unsqueeze(0).to(self.device)
                with torch.no_grad():
                    logits = self.clf(inp)
                    probs = torch.softmax(logits, dim=1)[0]
                    conf_val, pred_idx = probs.max(0)
                    conf_val = float(conf_val)
                    top2 = float(probs.topk(2).values[-1]) if self.n_classes > 1 else 0.0
                    margin = conf_val - top2
                    clf_sku_id = self.classes[pred_idx.item()]
                    clf_name = self.id_to_name.get(clf_sku_id, clf_sku_id)
                # RA-004：拒识门禁。detector 只提框，不拥有最终 SKU 决策权；
                # unknown 契约：top1 为 __unknown__ 时无论置信度多高都不得 accepted。
                status, source = gate_decision(clf_sku_id, conf_val, margin,
                                               self.conf_thr, self.margin_thr)
                if status == "accepted":
                    final_id, final_name = clf_sku_id, clf_name
                else:
                    final_id, final_name = "", "unknown"
                results.append({
                    "box": [round(v, 1) for v in box],
                    "status": status,
                    "sku_id": final_id, "sku_name": final_name,
                    "classifier_conf": round(conf_val, 4),
                    "margin": round(margin, 4),
                    "classifier_sku": clf_name,
                    "yolo_sku": yolo_name, "yolo_conf": round(float(sc), 4),
                    "source": source,
                })
        return results


def _match_one_to_one(preds: list, gts: list) -> dict:
    """RA-005：一对一匹配。预测框按 classifier_conf 降序贪心，每框最多消费一个 GT 点，
    每 GT 点只被一个预测框匹配；未匹配预测计 FP，未被消费 GT 计 FN。"""
    gts_left = list(range(len(gts)))
    matches: list = []  # (pred_idx, gt_idx)
    fp: list = []
    for pi, pr in sorted(enumerate(preds), key=lambda kv: -kv[1].get("classifier_conf", 0.0)):
        b = pr["box"]
        cands = [gi for gi in gts_left
                 if b[0] <= gts[gi][0] <= b[2] and b[1] <= gts[gi][1] <= b[3]]
        if not cands:
            fp.append(pi)
            continue
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        gi = min(cands, key=lambda g: (gts[g][0] - cx) ** 2 + (gts[g][1] - cy) ** 2)
        matches.append((pi, gi))
        gts_left.remove(gi)
    return {"matches": matches, "fp": fp, "fn": gts_left}


def integration_test(limit: int = 20, conf: float = 0.18):
    """RA-005 评估协议：一对一匹配，同时报告漏检/误检/错分/拒识/计数误差。

    指标：TP（accepted 且 SKU 正确）、misclassified、review（匹配但拒识）、
    FP（无匹配预测）、FN（未覆盖 GT）、precision、count MAE、每照片全对率。
    逐图明细存 .eval/cascade_eval_details.json，支持从明细重算所有汇总。"""
    from collections import Counter
    manifest = json.loads((PROJECT_ROOT / ".eval" / "batch2" / "manifest.json").read_text(encoding="utf-8"))
    photos = manifest["photos"]
    blobs = PROJECT_ROOT / ".training_data" / "blobs"

    recog = CascadeRecognizer()
    keys = list(photos.keys())[:limit]
    tot_tp = tot_mis = tot_review = tot_fp = tot_fn = tot_gt = 0
    count_abs_err = 0
    photo_exact = 0
    confusion = Counter()
    per_sku: dict = {}
    details: list = []
    for k in keys:
        p = photos[k]
        sha = (p.get("image") or {}).get("sha256")
        if not sha:
            continue
        bp = blobs / sha[:2] / sha
        if not bp.exists():
            continue
        img_bytes = bp.read_bytes()
        preds = recog.recognize(img_bytes, conf=conf)
        gts = [(ann.get("x"), ann.get("y"), ann.get("name")) for ann in p.get("annotations", [])
               if ann.get("x") is not None and ann.get("name")]
        tot_gt += len(gts)
        m = _match_one_to_one(preds, gts)
        tp = mis = review = 0
        matched_detail = []
        for pi, gi in m["matches"]:
            gname = gts[gi][2]
            pr = preds[pi]
            ps = per_sku.setdefault(gname, {"gt": 0, "covered": 0, "correct": 0, "review": 0})
            ps["gt"] += 1
            ps["covered"] += 1
            if pr["status"] != "accepted":
                review += 1
                ps["review"] += 1
                matched_detail.append({"gt": gname, "pred": None, "verdict": "review"})
            elif pr["sku_name"] == gname:
                tp += 1
                ps["correct"] += 1
                matched_detail.append({"gt": gname, "pred": pr["sku_name"], "verdict": "correct"})
            else:
                mis += 1
                confusion[(gname, pr["sku_name"])] += 1
                matched_detail.append({"gt": gname, "pred": pr["sku_name"], "verdict": "misclassified"})
        # GT 未被覆盖统计
        for gi in m["fn"]:
            per_sku.setdefault(gts[gi][2], {"gt": 0, "covered": 0, "correct": 0, "review": 0})["gt"] += 1
        n_accepted = sum(1 for pr in preds if pr["status"] == "accepted")
        count_abs_err += abs(n_accepted - len(gts))
        exact = (not m["fp"]) and (not m["fn"]) and mis == 0 and review == 0 and tp == len(gts)
        if exact:
            photo_exact += 1
        tot_tp += tp; tot_mis += mis; tot_review += review
        tot_fp += len(m["fp"]); tot_fn += len(m["fn"])
        details.append({"photo": k, "n_gt": len(gts), "n_pred": len(preds),
                        "tp": tp, "misclassified": mis, "review": review,
                        "fp": len(m["fp"]), "fn": len(m["fn"]), "exact": exact,
                        "matches": matched_detail})

    n_photos = len(details)
    det_recall = (tot_tp + tot_mis + tot_review) / tot_gt if tot_gt else 0
    accepted_acc = tot_tp / (tot_tp + tot_mis) if (tot_tp + tot_mis) else 0
    e2e_acc = tot_tp / tot_gt if tot_gt else 0
    precision = tot_tp / (tot_tp + tot_mis + tot_fp) if (tot_tp + tot_mis + tot_fp) else 0
    review_rate = tot_review / tot_gt if tot_gt else 0
    count_mae = count_abs_err / n_photos if n_photos else 0

    (PROJECT_ROOT / ".eval").mkdir(exist_ok=True)
    detail_path = PROJECT_ROOT / ".eval" / "cascade_eval_details.json"
    detail_path.write_text(json.dumps({"conf": conf, "photos": details}, ensure_ascii=False, indent=1),
                           encoding="utf-8")

    print("=" * 58)
    print(f"级联一对一匹配评估（RA-005） conf={conf}")
    print("=" * 58)
    print(f"  照片: {n_photos} | GT: {tot_gt} | 预测框: {sum(d['n_pred'] for d in details)}")
    print(f"  TP(接受且正确): {tot_tp} | 错分: {tot_mis} | 拒识(review): {tot_review} | FP: {tot_fp} | FN: {tot_fn}")
    print(f"  【检测召回】 {det_recall * 100:.1f}% | 【precision】 {precision * 100:.1f}%")
    print(f"  【已接受准确率】 {accepted_acc * 100:.1f}% | 【拒识率】 {review_rate * 100:.1f}%")
    print(f"  【端到端准确】 {e2e_acc * 100:.1f}% ({tot_tp}/{tot_gt})")
    print(f"  计数 MAE: {count_mae:.2f}/图 | 照片全对率: {photo_exact}/{n_photos}")
    print(f"\n  Top 混淆（GT→误判）:")
    for (g, pr), c in confusion.most_common(10):
        print(f"    {g} → {pr} ({c}次)")
    worst = sorted(per_sku.items(), key=lambda kv: kv[1]["gt"] - kv[1]["correct"], reverse=True)[:10]
    print(f"\n  最差 SKU:")
    for name, v in worst:
        print(f"    {name}: GT{v['gt']} 覆盖{v['covered']} 正确{v['correct']} 拒识{v['review']}")
    print(f"\n  逐图明细已存: {detail_path}")
    return {"photos": n_photos, "gt": tot_gt, "tp": tot_tp, "misclassified": tot_mis,
            "review": tot_review, "fp": tot_fp, "fn": tot_fn,
            "det_recall": det_recall, "precision": precision, "accepted_acc": accepted_acc,
            "e2e_acc": e2e_acc, "review_rate": review_rate, "count_mae": count_mae,
            "photo_exact": photo_exact}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="集成测试模式")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--conf", type=float, default=0.18, help="YOLO 检测置信度阈值")
    ap.add_argument("--image", default=None, help="单图推理路径")
    a = ap.parse_args()
    if a.test:
        integration_test(a.limit, a.conf)
    elif a.image:
        recog = CascadeRecognizer()
        img_bytes = Path(a.image).read_bytes()
        results = recog.recognize(img_bytes)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
