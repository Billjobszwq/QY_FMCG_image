"""真实框统一评估驱动（手册§十 / 用户要求#19/#23）。

在 diagnostic 真实框（diagnostic_v1_truebox_v1）完成后，用同一 evaluator、
同一 GT、同一配置重评 E0/P0/P1：IoU=0.50/0.75、recall@FP/image=1/3/5、
precision、重复框、背景误检与逐实例错误账本（10 类）。

输入（由真实框导出与模型推理先行产出，本脚本不做推理）：
  --gt     真实框 JSON：[{"image_id","boxes":[[x1,y1,x2,y2]...]}]
  --preds  预测 JSON：[{"image_id","boxes":[{"box":[x1,y1,x2,y2],"conf":f}]}]
  --out    报告输出路径（原子写，已存在拒绝覆盖）

用法：
  python -m scripts.run_truebox_eval --gt ... --preds ... --out ...
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.eval.truebox_eval import evaluate_truebox


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--preds", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    gt = {g["image_id"]: [{"box": b} for b in g["boxes"]]
          for g in json.loads(Path(a.gt).read_text(encoding="utf-8"))}
    preds = {p["image_id"]: p["boxes"]
             for p in json.loads(Path(a.preds).read_text(encoding="utf-8"))}
    images = [{"gt": gt.get(k, []), "preds": preds.get(k, [])}
              for k in sorted(gt)]

    rep = evaluate_truebox(images)
    out = Path(a.out)
    if out.exists():
        raise FileExistsError(f"报告已存在，禁止覆盖: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"[truebox_eval] images={rep['n_images']} gt={rep['n_gt']} "
          f"proposals={rep['n_proposals']}")
    for t, rr in rep["recall_at_fp"].items():
        print(f"[truebox_eval] {t} recall@FP1/3/5 = "
              + " / ".join(f"{rr[b]:.3f}" for b in (1, 3, 5)))
    print(f"[truebox_eval] ledger={ {k: v for k, v in rep['error_ledger'].items() if v} }")


if __name__ == "__main__":
    main()
