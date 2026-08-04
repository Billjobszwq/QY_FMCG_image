"""FMCG Domain Pack：fmcg_photo_inspection_v1 Graph（平台无 FMCG 硬编码，经注册接入）。

节点链：ingest → quality → recognize → human_gate → evidence → finalize
红线：识别只经 Capability（legacy.recognition.v2）调用；Evidence 全量落 CAS+store。
"""

from __future__ import annotations

import json
import uuid

from src.platform.assets.cas import ContentAddressedStore
from src.platform.contracts import AssetRef, EvidenceItem, EvidenceManifest
from src.platform.data.store import PlatformStore
from src.platform.kernel.definition import GraphDefinition, NodeSpec
from src.platform.kernel.engine import NodeContext, NodeFailed
from src.platform.registry import CapabilityRegistry

GRAPH_NAME = "fmcg_photo_inspection_v1"
GRAPH_VERSION = "1"

DEFINITION = GraphDefinition(
    name=GRAPH_NAME,
    version=GRAPH_VERSION,
    nodes=[
        NodeSpec("ingest"),
        NodeSpec("quality"),
        NodeSpec("recognize"),
        NodeSpec("human_gate"),
        NodeSpec("evidence"),
        NodeSpec("finalize"),
    ],
)

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _node_output(store: PlatformStore, run_id: str, node_name: str) -> dict:
    for n in store.list_nodes(run_id):
        if n["node_name"] == node_name and n["status"] == "completed" and n["output_json"]:
            return json.loads(n["output_json"])
    return {}


def build_handlers(
    *,
    capabilities: CapabilityRegistry,
    cas: ContentAddressedStore,
    store: PlatformStore,
) -> dict:
    rec = capabilities.get("legacy.recognition.v2")

    def ingest(ctx: NodeContext) -> dict:
        sha = ctx.run_input["photo_sha256"]
        data = cas.get(sha)
        return {"asset_sha256": sha, "size_bytes": len(data)}

    def quality(ctx: NodeContext) -> dict:
        sha = ctx.run_input["photo_sha256"]
        data = cas.get(sha)
        reasons = []
        if len(data) < 1024:
            reasons.append("too_small")
        if not (data[:3] == _JPEG_MAGIC or data[:8] == _PNG_MAGIC):
            reasons.append("not_image_magic")
        if reasons:
            raise NodeFailed(f"quality_fail: {','.join(reasons)}")
        return {"quality_ok": True, "size_bytes": len(data)}

    def recognize(ctx: NodeContext) -> dict:
        sha = ctx.run_input["photo_sha256"]
        data = cas.get(sha)
        result = rec.recognize(data, conf=float(ctx.run_input.get("conf", 0.25)))
        store.append_usage(
            capability="legacy.recognition.v2", run_id=ctx.run_id, quantity=1.0, unit="call"
        )
        return {
            "upstream_run_id": result.get("run_id"),
            "products": result.get("products", []),
            "count": result.get("count", 0),
            "model": result.get("model"),
        }

    def human_gate(ctx: NodeContext) -> dict:
        if not ctx.checkpoint_get("human_approved"):
            ctx.request_human("确认识别结果（人工门）")
        return {"approved": True}

    def evidence(ctx: NodeContext) -> dict:
        sha = ctx.run_input["photo_sha256"]
        rec_out = _node_output(store, ctx.run_id, "recognize")
        rec_blob = cas.put(
            json.dumps(rec_out, ensure_ascii=False).encode("utf-8"),
            kind="recognition_output",
            media_type="application/json",
        )
        evidence_id = uuid.uuid4().hex
        manifest = EvidenceManifest(
            evidence_id=evidence_id,
            run_id=ctx.run_id,
            kind="recognition",
            items=[
                EvidenceItem(
                    role="input_photo",
                    asset=AssetRef(asset_id=sha, sha256=sha, kind="photo",
                                   size_bytes=len(cas.get(sha)), media_type="image/jpeg"),
                ),
                EvidenceItem(role="recognition_output", asset=rec_blob),
            ],
        )
        store.create_evidence_bundle(
            evidence_id=evidence_id,
            run_id=ctx.run_id,
            kind="recognition",
            manifest=manifest.model_dump(),
        )
        return {"evidence_id": evidence_id}

    def finalize(ctx: NodeContext) -> dict:
        rec_out = _node_output(store, ctx.run_id, "recognize")
        ev_out = _node_output(store, ctx.run_id, "evidence")
        store.append_audit(
            actor="system", action="run.completed", subject_type="run", subject_id=ctx.run_id,
            detail={"graph": GRAPH_NAME, "count": rec_out.get("count", 0)},
        )
        return {
            "recognition_result": {
                "products": rec_out.get("products", []),
                "count": rec_out.get("count", 0),
                "model": rec_out.get("model"),
            },
            "evidence_id": ev_out.get("evidence_id"),
        }

    return {
        "ingest": ingest,
        "quality": quality,
        "recognize": recognize,
        "human_gate": human_gate,
        "evidence": evidence,
        "finalize": finalize,
    }
