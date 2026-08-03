# 闭环验证（最小证明）：自动提案 -> 人工通过 -> 可训练标签。全程不碰原始资产。
# 用法：python scripts/label_proof.py   （会调本地 omlx，单张照片，可能耗时几分钟）
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.labeling import emit, runner  # 若标注模块缺失，这里直接 ImportError

ROOT = Path(__file__).resolve().parents[1]


def main():
    # 1) 跑模式 B：用它模种子 -> 产出提案 + classes.json + 复核队列（单张照片）
    runner.run("B", max_photos=1)

    m = json.load(open(ROOT / ".field" / "manifest.json", encoding="utf-8"))
    p = m["photos"][0]
    pid = p["id"]
    W, H = p["image"]["width"], p["image"]["height"]

    prop_path = ROOT / ".labels" / "proposals" / f"{pid}.json"
    if not prop_path.exists():
        print("闭环验证 失败：无提案文件", prop_path)
        return
    props = json.load(open(prop_path, encoding="utf-8"))
    classmap = {c: i for i, c in enumerate(json.load(open(ROOT / ".labels" / "classes.json", encoding="utf-8")))}

    # 2) 模拟人工：把"模型有把握的提案"全部确认通过（真实流程里这一步是人在审核页面点的）
    regions = [{"box": pr["box"], "canonical_id": pr["decision"], "confirmed": True}
               for pr in props if pr["decision"] in classmap]
    review = {"asset_id": pid, "reviewer": "human_sim", "status": "approved",
              "regions": regions, "notes": "closed-loop proof（模拟人工通过）"}
    emit.write_review(pid, review)
    emit.append_review_event({"asset_id": pid, "reviewer": "human_sim", "status": "approved",
                              "before": None, "after": regions})
    emit.apply_review_to_approved(pid, review, W, H, classmap)  # 仅 approved 才写训练源

    # 3) 校验训练源确实生成
    ap = ROOT / ".labels" / "approved" / f"{pid}.txt"
    n = len(ap.read_text(encoding="utf-8").strip().splitlines()) if ap.exists() else 0
    print("闭环验证 photo=", pid, "| 提案数=", len(props), "| 人工通过框=", len(regions),
          "| approved 存在=", ap.exists(), "| 训练标签行数=", n,
          "| 结论=", "通过" if (ap.exists() and n > 0) else "失败")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("闭环验证 异常：", type(e).__name__, str(e)[:300])
