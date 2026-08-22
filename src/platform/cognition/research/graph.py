"""Research Graph 定义（Task 9 / 03 §5；R2-06 显式节点语义）。

确定性管线：classify → plan → retrieve → read → sufficiency →
claim → finalize。sufficiency（Critic）输出 typed 动作：
- accept → claim；
- gap_query → retrieve（缺口改写，novelty 停止：连续两轮无新高价值
  span 即止）；
- counterevidence → retrieve（独立反证检索，中性查询不预设结论）；
- ask_human → waiting_human（仅真实冲突：互斥规范化数值/命题矛盾，
  多来源等值只是 diversity）。
deep_research 必须经 typed planner（有界子问题/依赖/停止条件/反证）；
planner 不可用 → degraded/abstain。节点执行结果持久化到
research_step_v1（checkpoint），resume 从断点续跑。
"""
from __future__ import annotations

PIPELINE: tuple[str, ...] = ("classify", "plan", "retrieve", "read",
                             "sufficiency", "claim", "finalize")

NODE_SCHEMAS: dict[str, dict[str, str]] = {
    "classify": {"in": "question,mode", "out": "answerability"},
    "plan": {"in": "brief,budget",
             "out": "subquestions,depends,stop_conditions"},
    "retrieve": {"in": "subquestions,pending_action(primary|gap_query|"
                       "counterevidence)",
                 "out": "hits,queries(strategy typed)"},
    "read": {"in": "hits", "out": "evidence,seen_spans,rounds_without_new"},
    "sufficiency": {"in": "evidence",
                    "out": "covered,gaps,conflicts,action,next"},
    "claim": {"in": "evidence,gaps", "out": "claims"},
    "finalize": {"in": "claims", "out": "report,stop_reason"},
}
