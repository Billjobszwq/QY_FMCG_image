#!/usr/bin/env python3
"""M7 调试：复现 dense 评测中的 ACL/forbidden/injection 泄漏样本。

只读诊断：输出泄漏样本的候选与元数据，帮助定位网关过滤缺口。
不回显任何凭据。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.eval_research_rag import _setup_managed_omlx  # noqa: E402
from src.platform.cognition.composition import build_cognition_services  # noqa: E402
from src.platform.cognition.contracts import CognitiveQueryRequest  # noqa: E402
from src.platform.cognition.context import CognitiveContext  # noqa: E402
from src.platform.cognition.evaluation.dataset import load_gold  # noqa: E402
from src.platform.cognition.evaluation.harness import (  # noqa: E402
    _resolve_expected, _resolve_forbidden, build_corpus, compute_sample)
from src.platform.data.store import PlatformStore  # noqa: E402
from datetime import datetime  # noqa: E402


def _parse_as_of(g):
    from src.platform.cognition.evaluation.harness import _parse_as_of as p
    return p(g)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="mm-debug-"))
    store = PlatformStore(tmp / "debug.sqlite")
    provider = _setup_managed_omlx(store)
    assert provider is not None, "managed provider required"
    stack = build_cognition_services(store, cas_root=tmp / "cas",
                                     index_root=tmp / "index",
                                     vector_provider=provider)
    snapshot = build_corpus(stack, store)
    id_map = snapshot.get("id_map", {})
    gold = load_gold(str(REPO_ROOT / "tests" / "fixtures" / "cognition"
                         / "gold_queries.jsonl"))
    conn = store._conn
    for g in gold:
        expected = _resolve_expected(g, id_map)
        forbidden = _resolve_forbidden(g, id_map)
        qc = (g.expect_empty_for_customer or g.scope.get("customer_id")
              or g.extra.get("extra_customer") or "")
        ctx = CognitiveContext(
            principal_id="eval", tenant_id="local", customer_id=qc,
            project_id="", test_run_id="", data_scope="operational",
            action="cognition.knowledge.search",
            permission_tags=("public", "internal"), purpose="debug",
            correlation_id="", parent_run_id=None, as_of=_parse_as_of(g))
        req = CognitiveQueryRequest(query=g.query,
                                    target_kinds=tuple(g.target_kinds),
                                    mode=g.mode, top_k=10)
        result = stack.gateway.search(req, ctx)
        ids = [c.target_id for c in result.candidates]
        s = compute_sample(g, expected, ids, [], not result.candidates)
        fh = forbidden & set(ids)
        if s.leaked or fh:
            print(f"== {g.id} class={getattr(g, 'cls', getattr(g, 'gold_class', '?'))}"
                  f" leaked={s.leaked}"
                  f" forbidden_hits={sorted(fh)}")
            print(f"   query={g.query!r} customer={qc!r}")
            for c in result.candidates[:5]:
                row = conn.execute(
                    "SELECT knowledge_id, title, customer_id, project_id,"
                    " permission_tags_json, status FROM"
                    " knowledge_item_version WHERE knowledge_id=?"
                    " ORDER BY version DESC LIMIT 1",
                    (c.target_id,)).fetchone()
                meta = dict(row) if row else {"raw": c.target_id}
                print(f"   cand={c.target_id} score={getattr(c, 'score', None)}"
                      f" meta={json.dumps(meta, ensure_ascii=False)}")
    # injection 负例
    from src.platform.cognition.evaluation.harness import (
        _run_injection_negative)
    hits = _run_injection_negative(stack, store)
    print("injection_hits:", hits)
    store.close()


if __name__ == "__main__":
    main()
