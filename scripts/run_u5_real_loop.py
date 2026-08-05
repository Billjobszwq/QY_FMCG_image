"""U5-2 真实 E2E：在生产库上跑通第一条真实 Loop（只追加，不删改）。

- Run A（bad_samples）：启发式无 fail → clean 分支 → 人工门暂停 +
  全新引擎实例恢复续跑 → 组装/真实识别完成；
- Run B（photo1106，max_rounds=2）：真实货架照大量质量 fail →
  feedback 误差回流每轮发生 → 预算停止（stop_reason=budget_rounds）。

首跑实测（20260805_142546）：photo1106 三轮均含 fail（26 条 quality.fail
审计）达轮次预算；bad_samples 启发式未判 fail（反光样本需人工确认，
诚实 waiting_human）——故本脚本按真实数据分工。

全部结论真实：质量=qpol_v2 落库、识别=8091 legacy.recognition.v2；
执行前备份生产库；证据写 .eval/u5/。

用法：
  /Users/zhangweiqi/miniconda3/bin/python3 -m scripts.run_u5_real_loop
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from src.platform.data.store import PlatformStore
    from src.platform.kernel.loop import LoopEngine
    from src.platform.loops.pipeline_v2 import (build_graph, build_handlers,
                                                build_routers)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / ".eval" / "u5"
    out_dir.mkdir(parents=True, exist_ok=True)

    store = PlatformStore(ROOT / ".platform" / "platform.sqlite")
    bak = store.backup(out_dir / f"platform_backup_before_u52_{ts}.sqlite")
    print("backup:", bak)

    evidence: dict = {"ts": ts, "runs": []}

    # ---------- Run A：bad_samples 全链路（clean → 人工门 → 完成） ----------
    eng = LoopEngine(store)
    run = eng.start_run(
        build_graph(max_rounds=3),
        {"origin": "script-u52", "source_id": "bad_samples"})
    rid = run["run_id"]
    handlers = build_handlers(store, root=ROOT, source_id="bad_samples",
                              batch_size=8)
    out = eng.execute(rid, handlers, build_routers())
    rec_a = {"run_id": rid, "graph": "photo_pipeline_v2",
             "source_id": "bad_samples", "max_rounds": 3,
             "status_before_gate": out["status"]}
    if out["status"] == "waiting_human":
        trail = eng.decision_trail(rid)
        rec_a["feedback_decisions"] = [
            d for d in trail if d["decision"] == "feedback"]
        rec_a["human_gate"] = [
            d for d in trail if d["decision"] == "human_gate"]
        # 模拟进程重启：全新引擎实例批准并续跑
        eng2 = LoopEngine(store)
        eng2.approve_human_gate(rid, approved=True, actor="admin")
        out2 = eng2.execute(rid, handlers, build_routers())
        rec_a["status_final"] = out2["status"]
        rec_a["error"] = out2.get("error")
        rec_a["outputs"] = (json.loads(out2["output_json"])
                            if out2.get("output_json") else None)
        rec_a["trail"] = eng2.decision_trail(rid)
    else:
        rec_a["status_final"] = out["status"]
        rec_a["stop_reason"] = out.get("stop_reason")
        rec_a["trail"] = eng.decision_trail(rid)
    fails = [a for a in store.list_audit(limit=2000)
             if a["action"] == "quality.fail"]
    rec_a["quality_fail_audit_entries"] = len(fails)
    evidence["runs"].append(rec_a)
    print("RunA:", rec_a["status_before_gate"], "->",
          rec_a["status_final"],
          "| feedback:", len(rec_a.get("feedback_decisions", [])),
          "| fails审计:", rec_a["quality_fail_audit_entries"])

    # ---------- Run B：photo1106 质量失败回流 → 预算停止 ----------
    eng_b = LoopEngine(store)
    run_b = eng_b.start_run(
        build_graph(max_rounds=2),
        {"origin": "script-u52-budget", "source_id": "photo1106"})
    rid_b = run_b["run_id"]
    handlers_b = build_handlers(store, root=ROOT, source_id="photo1106",
                                batch_size=16)
    out_b = eng_b.execute(rid_b, handlers_b, build_routers())
    rec_b = {"run_id": rid_b, "source_id": "photo1106",
             "max_rounds": 2, "status": out_b["status"],
             "stop_reason": out_b.get("stop_reason"),
             "error": out_b.get("error"),
             "trail": eng_b.decision_trail(rid_b)}
    evidence["runs"].append(rec_b)
    print("RunB:", rec_b["status"], "| stop_reason:", rec_b["stop_reason"])

    path = out_dir / f"u52_real_loop_evidence_{ts}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print("evidence:", path)
    store.close()


if __name__ == "__main__":
    main()
