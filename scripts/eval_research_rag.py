#!/usr/bin/env python3
"""Research RAG 固定评测（Task 12；M7 受管 OMLX dense/hybrid）。

用法：
  python scripts/eval_research_rag.py --gold tests/fixtures/cognition/gold_queries.jsonl
  python scripts/eval_research_rag.py --suite v1 --frozen
  python scripts/eval_research_rag.py --suite v1-release --frozen --managed-omlx \
      --out runtime/platform/evidence/model-management-rag-eval.json

在临时 DB 上构建语料 + 建索引 + 跑金标准，输出分层指标 JSON 报告
（retrieval/citation/generation/safety），不写生产 DB。

--managed-omlx：在评测库内经统一模型管理引导本地 OMLX
（connection draft→secret→test→approve→catalog probe→binding active），
以受管 Binding Identity 构建并查询真实 dense/hybrid 索引；凭据来自
进程环境 TAAS_OMLX_API_KEY 或用户本机 OMLX 配置，绝不回显。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.platform.cognition.composition import build_cognition_services  # noqa: E402
from src.platform.cognition.evaluation.dataset import load_gold  # noqa: E402
from src.platform.cognition.evaluation.harness import (  # noqa: E402
    build_corpus, run_gold_evaluation)
from src.platform.data.store import PlatformStore  # noqa: E402


def _setup_managed_omlx(store) -> object:
    """在评测库上引导受管 OMLX embedding；返回 provider（失败 → None）。"""
    from src.platform.models.bootstrap import bootstrap_local_omlx
    from src.platform.models.integrations import resolve_embedding_provider
    from src.platform.models.secrets import EncryptedSQLiteSecretStore
    from src.platform.models.service import ModelManagementServices
    import os as _os
    import secrets as _secrets

    key_env = (_os.environ.get("TAAS_OMLX_API_KEY") or "").strip()
    key: bytes | None = key_env.encode("utf-8") if key_env else None
    if key is None:
        settings = Path.home() / ".omlx" / "settings.json"
        try:
            cfg = json.loads(settings.read_text())
            raw = (cfg.get("auth") or {}).get("api_key") or ""
            key = raw.encode("utf-8") if raw else None
        except (OSError, json.JSONDecodeError):
            key = None
    if key is None:
        print("[eval] BLOCKED_BY_PROVIDER_AUTH：无受控凭据，"
              "退回词法基线（诚实报告）", file=sys.stderr)
        return None

    kek = _secrets.token_bytes(32)  # 演练进程内 KEK：不落盘、不回显
    services = ModelManagementServices(
        store, secret_store=EncryptedSQLiteSecretStore(store, kek=kek))
    report = bootstrap_local_omlx(services, get_key=lambda: key)
    if not report.get("ok"):
        print(f"[eval] OMLX 引导失败：{report.get('stage')} /"
              f" {report.get('detail')}", file=sys.stderr)
        return None
    identity = {k: report.get(k) for k in (
        "connection_id", "connection_version", "model_id",
        "embedding_dimension", "normalization_version", "identity")}
    print(f"[eval] 受管 OMLX 就绪：{json.dumps(identity, ensure_ascii=False)}")
    return resolve_embedding_provider(services,
                                      principal_id="eval-harness")


def main() -> None:
    ap = argparse.ArgumentParser(description="Research RAG evaluation")
    ap.add_argument("--gold",
                    default=str(REPO_ROOT / "tests" / "fixtures" /
                                "cognition" / "gold_queries.jsonl"))
    ap.add_argument("--suite", default="v1")
    ap.add_argument("--frozen", action="store_true",
                    help="固定语料/索引快照（可复现模式）")
    ap.add_argument("--out", default=None,
                    help="报告输出路径（缺省打印到 stdout）")
    ap.add_argument("--managed-omlx", action="store_true",
                    help="经统一模型管理引导本地 OMLX 真实 dense/hybrid")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="cognition-eval-"))
    store = PlatformStore(tmp / "eval.sqlite")
    vector_provider = None
    if args.managed_omlx:
        vector_provider = _setup_managed_omlx(store)
    stack = build_cognition_services(store, cas_root=tmp / "cas",
                                     index_root=tmp / "index",
                                     vector_provider=vector_provider)
    snapshot = build_corpus(stack, store)
    gold = load_gold(args.gold)
    report = run_gold_evaluation(stack, store, gold, snapshot,
                                 gold_path=args.gold)
    # suite/frozen 在哈希之前并入，保证 report_hash 覆盖最终产物
    # （评审 #T12-5）；用统一的 report_content_hash（剔除易变字段）。
    from src.platform.cognition.evaluation.report import (  # noqa: E402
        report_content_hash)
    report["suite"] = args.suite
    report["frozen"] = bool(args.frozen)
    report["report_hash"] = report_content_hash(report)

    out = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"report written to {args.out}")
    else:
        print(out)
    # gate 判定（评审 #T12-1）：未达标项如实报告并以非零码退出
    gates = report.get("gates", {})
    failed = {k: v for k, v in gates.items() if not v.get("pass", False)}
    if failed:
        print("\n[GATES] 以下 gate 未通过（如实报告，非假绿）：",
              file=sys.stderr)
        for k, v in failed.items():
            print(f"  - {k}: {v}", file=sys.stderr)
        store.close()
        raise SystemExit(1)
    store.close()


if __name__ == "__main__":
    main()
