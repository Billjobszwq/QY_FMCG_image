"""补充拦截指令：从现有 clean 指标筛出"中等质量灰名单"（不重跑拦截器）。

收紧阈值（不重跑、直接读已存指标）：
  - 反光   [0.10, 0.18) → 灰名单 _light_reflection
  - 摩尔纹 [1.45, 1.65) → 灰名单 _light_moire
  - 模糊   保持 <40 不变（保护微距小罐）

灰名单不删除：symlink 独立存放到 batch3_gray/（文件名加后缀），
并写灰名单清单 batch3_gray/gray_manifest.json（供 sku_v6 数据加载器降采样 50%）。

用法：python -m src.data.graylist_batch3"""
from __future__ import annotations

import json
from pathlib import Path

from ..common.config import PROJECT_ROOT

CLEAN_MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"
CLEAN_BLOBS = PROJECT_ROOT / ".batch3_clean" / "blobs"
GRAY_DIR = PROJECT_ROOT / "batch3_gray"

REFL_LO, REFL_HI = 0.10, 0.18
MOIRE_LO, MOIRE_HI = 1.45, 1.65


def build():
    clean = json.loads(CLEAN_MANIFEST.read_text(encoding="utf-8"))
    GRAY_DIR.mkdir(parents=True, exist_ok=True)

    gray = {}
    for pid, rec in clean.items():
        mt = rec.get("metrics", {})
        refl = mt.get("reflect_ratio", 0.0)
        moire = mt.get("moire_ratio", 0.0)
        reasons = []
        if REFL_LO <= refl < REFL_HI:
            reasons.append("light_reflection")
        if MOIRE_LO <= moire < MOIRE_HI:
            reasons.append("light_moire")
        if not reasons:
            continue
        suffix = "_" + reasons[0]
        sha = rec.get("sha256")
        gray[pid] = {
            "reasons": reasons,
            "suffix": suffix,
            "sha256": sha,
            "filename": rec.get("filename"),
            "metrics": mt,
        }
        # symlink 独立存放（不复制数据）
        if sha:
            src = CLEAN_BLOBS / sha[:2] / sha
            if src.exists():
                link = GRAY_DIR / f"{pid}{suffix}.jpg"
                if not link.exists():
                    try:
                        link.symlink_to(src.resolve())
                    except Exception:
                        pass

    (GRAY_DIR / "gray_manifest.json").write_text(json.dumps(gray, ensure_ascii=False, indent=2), encoding="utf-8")

    n_refl = sum(1 for g in gray.values() if "light_reflection" in g["reasons"])
    n_moire = sum(1 for g in gray.values() if "light_moire" in g["reasons"])
    print("=== 灰名单构建完成（未重跑拦截器，读现有指标）===")
    print(f"  反光灰名单 _light_reflection: {n_refl}")
    print(f"  摩尔纹灰名单 _light_moire: {n_moire}")
    print(f"  灰名单合计(去重): {len(gray)}")
    print(f"  保持全权重 clean: {len(clean) - len(gray)}")
    print(f"  独立目录: {GRAY_DIR}/ (symlink + gray_manifest.json)")
    return gray


if __name__ == "__main__":
    build()
