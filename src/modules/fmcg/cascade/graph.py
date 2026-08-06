"""VLM-012：S0–S5 级联 GraphV2 定义（14 节点，typed edges）。

节点与阶段映射：
- S0：quality、scene；
- S1：detect、classify_fast、risk_s1；
- S2：segment、reclassify、risk_s2；
- S3：retrieve、risk_s3；
- S4：vlm_rerank、risk_s4；
- S5：human_review；finalize 为终点。

红线：
- 多条件节点全部带 router 标签；未匹配 edge 由内核 fail-closed；
- 本图不含 feedback 边：重裁剪/补数据循环须显式扩展并受
  max_rounds 限制（当前 max_rounds=5 仅作内核兜底）；
- human_review 是等待人工门的唯一节点；finalize 为终点。
"""

from __future__ import annotations

from src.platform.kernel.loop import EdgeSpec, GraphV2

CASCADE_NODES = (
    "quality", "scene", "detect", "classify_fast", "risk_s1",
    "segment", "reclassify", "risk_s2", "retrieve", "risk_s3",
    "vlm_rerank", "risk_s4", "human_review", "finalize",
)

CASCADE_GRAPH_NAME = "fmcg_cascade_s0_s5"
CASCADE_GRAPH_VERSION = "1"

CASCADE_GRAPH = GraphV2(
    name=CASCADE_GRAPH_NAME,
    version=CASCADE_GRAPH_VERSION,
    entry="quality",
    nodes=CASCADE_NODES,
    edges=(
        # S0
        EdgeSpec("quality", "scene", when="scene"),
        EdgeSpec("quality", "finalize", when="blocked"),
        EdgeSpec("scene", "detect"),
        # S1
        EdgeSpec("detect", "classify_fast", when="classify"),
        EdgeSpec("detect", "finalize", when="no_product"),
        EdgeSpec("classify_fast", "risk_s1"),
        EdgeSpec("risk_s1", "finalize", when="accept"),
        EdgeSpec("risk_s1", "segment", when="escalate"),
        EdgeSpec("risk_s1", "human_review", when="human"),
        EdgeSpec("risk_s1", "human_review", when="budget_exhausted"),
        # S2
        EdgeSpec("segment", "reclassify"),
        EdgeSpec("reclassify", "risk_s2"),
        EdgeSpec("risk_s2", "finalize", when="accept"),
        EdgeSpec("risk_s2", "retrieve", when="escalate"),
        EdgeSpec("risk_s2", "human_review", when="human"),
        EdgeSpec("risk_s2", "human_review", when="budget_exhausted"),
        # S3
        EdgeSpec("retrieve", "risk_s3"),
        EdgeSpec("risk_s3", "finalize", when="accept"),
        EdgeSpec("risk_s3", "vlm_rerank", when="escalate"),
        EdgeSpec("risk_s3", "human_review", when="human"),
        EdgeSpec("risk_s3", "human_review", when="budget_exhausted"),
        # S4
        EdgeSpec("vlm_rerank", "risk_s4", when="accepted"),
        EdgeSpec("vlm_rerank", "risk_s4", when="new_package"),
        EdgeSpec("vlm_rerank", "human_review", when="unknown"),
        EdgeSpec("vlm_rerank", "human_review", when="vlm_unavailable"),
        EdgeSpec("vlm_rerank", "human_review", when="budget_exhausted"),
        EdgeSpec("risk_s4", "finalize", when="accept"),
        EdgeSpec("risk_s4", "human_review", when="human"),
        EdgeSpec("risk_s4", "human_review", when="escalate"),
        EdgeSpec("risk_s4", "human_review", when="budget_exhausted"),
        # S5 与终点
        EdgeSpec("human_review", "finalize"),
    ),
    max_rounds=5,
)
