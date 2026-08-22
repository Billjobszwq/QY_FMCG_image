#!/usr/bin/env python3
"""M7 调试：测量 gold 正/负样本的 dense 相似度分布，为冻结下限提供依据。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.eval_research_rag import _setup_managed_omlx  # noqa: E402
from src.platform.cognition.composition import build_cognition_services  # noqa: E402
from src.platform.cognition.evaluation.dataset import load_gold  # noqa: E402
from src.platform.cognition.evaluation.harness import build_corpus  # noqa: E402
from src.platform.cognition.index.vector import cosine  # noqa: E402
from src.platform.data.store import PlatformStore  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp(prefix="mm-floor-"))
    store = PlatformStore(tmp / "f.sqlite")
    provider = _setup_managed_omlx(store)
    stack = build_cognition_services(store, cas_root=tmp / "cas",
                                     index_root=tmp / "index",
                                     vector_provider=provider)
    snapshot = build_corpus(stack, store)
    id_map = snapshot.get("id_map", {})
    gold = load_gold(str(REPO_ROOT / "tests" / "fixtures" / "cognition"
                         / "gold_queries.jsonl"))

    # 取激活索引的向量
    build = stack.catalog.active("knowledge")
    assert build is not None, "no active knowledge index"
    artifact = stack.catalog.load_artifact(build)
    vectors = artifact.get("vectors") or {}
    units = artifact.get("units") or {}
    print("chunk vectors:", len(vectors))

    pos_top1 = []
    neg_top = []
    for g in gold:
        qvec = provider.encode_queries([g.query])[0]
        sims = sorted((cosine(qvec, v) for v in vectors.values()),
                      reverse=True)
        tag = f"{g.id} ({g.cls}/{g.polarity})"
        if g.polarity == "positive":
            pos_top1.append((sims[0] if sims else None, tag))
        else:
            neg_top.append((sims[0] if sims else None,
                            sims[7] if len(sims) > 7 else None, tag))
    print("\n-- positives（全库最高相似度）--")
    for v, t in sorted(pos_top1, key=lambda x: x[0] or 0):
        print(f"  {v:.4f}  {t}")
    print("\n-- negatives/abstain（全库 top1 / top8 相似度）--")
    for a, b, t in sorted(neg_top, key=lambda x: -(x[0] or 0)):
        bs = "None" if b is None else f"{b:.4f}"
        print(f"  top1={a:.4f} top8={bs}  {t}")
    store.close()


if __name__ == "__main__":
    main()
