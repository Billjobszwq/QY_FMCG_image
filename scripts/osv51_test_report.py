#!/usr/bin/env python3
"""OSV51 C-6/C-8：hermetic 测试报告机器生成器（手写 JSON 废止）。

运行 hermetic pytest（marker not host_mps），解析结果并写
.eval/scope_v5/test_report.json —— 带 binding 块（source_commit/
code_tree_hash/migration_hash/database_fingerprint/
suite_config_hash/command_hash/result_hash/started_at/finished_at）。
Gate 只消费本脚本生成的报告；failed>0 时 Gate 必须非 READY。

用法：python3 scripts/osv51_test_report.py [--quick]
    --quick 只解析已存在的最近 pytest 输出（不重跑），用于演示绑定；
    默认真跑全量。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / ".eval" / "scope_v5" / "test_report.json"
PY = "/Users/zhangweiqi/miniconda3/bin/python"

from src.platform import binding_core as _bc  # noqa: E402


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_summary(text: str) -> dict:
    """解析 pytest -q 末行摘要。全绿时 pytest 不输出 “0 failed”，
    此时 failed=0；若连 passed 行都没有（进程异常）则 failed=-1，
    Gate 必须阻断（诚实失败，不得猜测）。"""
    m = re.search(r"(\d+) passed", text)
    passed = int(m.group(1)) if m else -1
    m = re.search(r"(\d+) failed", text)
    failed = int(m.group(1)) if m else (0 if passed >= 0 else -1)
    m = re.search(r"(\d+) skipped", text)
    skipped = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) deselected", text)
    deselected = int(m.group(1)) if m else 0
    return {"failed": failed, "passed": passed, "skipped": skipped,
            "deselected": deselected}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    from src.platform.data.store import PlatformStore
    from src.platform.gate_evaluator import db_fingerprint
    store = PlatformStore(ROOT / ".platform" / "platform.sqlite")
    started = _utcnow()
    # OSV52：测试质量门禁——测试函数返回非 None 视为错误（不得以
    # 过滤/降级 warning 的方式绕过）。
    argv = [PY, "-m", "pytest", "tests", "-q", "-p",
            "no:cacheprovider",
            "-W", "error::pytest.PytestReturnNotNoneWarning"]
    if args.quick:
        print("--quick：不重跑；binding 按当前状态生成（仅演示/兜底）")
        text = ""
        counts = {"failed": -1, "passed": -1, "skipped": 0,
                  "deselected": 0}
    else:
        proc = subprocess.run(argv, cwd=str(ROOT),
                              capture_output=True, text=True,
                              timeout=3600)
        text = proc.stdout + "\n" + proc.stderr
        counts = parse_summary(text)
    finished = _utcnow()
    payload = {"suite": "hermetic", **counts,
               "marker": "not host_mps",
               "generated_by": "scripts/osv51_test_report.py"}
    binding = _bc.make_binding(
        root=ROOT, conn=store._conn, argv=argv,
        result_payload=payload, started_at=started,
        finished_at=finished,
        database_fingerprint=db_fingerprint(store))
    payload["binding"] = binding
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps({k: payload[k] for k in
                      ("suite", "failed", "passed", "skipped",
                       "deselected")}, ensure_ascii=False))
    print(f"binding.source_commit={binding['source_commit']}")
    print(f"binding.code_tree_hash={binding['code_tree_hash']}")
    if counts["failed"] != 0 and not args.quick:
        print("存在失败测试：Gate tests_all_passed 必须阻断")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
