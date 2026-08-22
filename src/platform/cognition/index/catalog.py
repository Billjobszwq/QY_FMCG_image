"""索引目录（Task 8）：build 记录 + 显式 active registry + CAS 激活。

索引是可重建派生物（02 §1/§8.3）。每次 build 记录 corpus/input hash、
后端、分析器、chunk 策略、参数、条目数与质量报告；激活必须显式且
hash 匹配（CAS），不按 mtime/“最新目录”选择。

V1 词法基线索引 artifact 以 JSON 存于 index_root 下（本地优先）；
向量 leg 仅当提供可用 VectorProvider 时构建，否则检索面 degraded。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..context import CognitiveContext
from ..errors import CognitionIntegrityError, CognitionValidationError
from ..repository import CognitionRepository, UnitOfWork
from .lexical import LEX_ANALYZER_VERSION, build_postings
from .vector import encode_documents, identity_string, provider_identity

CHUNK_POLICY_VERSION = "chunk@1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IndexCatalog:
    def __init__(self, store: Any, *, index_root: Path | str,
                 vector_provider: Any = None) -> None:
        self.store = store
        self.repo = CognitionRepository(store)
        self.index_root = Path(index_root)
        # R2-05：组合根注入的默认 provider；API build 不接受调用方
        # 自带 endpoint/key（provider 只能来自受控配置）。
        self.vector_provider = vector_provider

    # ---------- build ----------

    def _collect_knowledge_units(self) -> list[dict[str, Any]]:
        """published 知识条目 → 可检索 chunk 单元（携带 ACL/effective
        元数据）。ACL 过滤在查询时做（pre-retrieval），build 只收集。"""
        units: list[dict[str, Any]] = []
        for item in self.repo.list_knowledge_by_status("published"):
            span_ids = json.loads(item["source_span_ids_json"] or "[]")
            chunks = {c["chunk_id"]: c
                      for c in self.repo.get_chunks_by_ids(span_ids)}
            for sid in span_ids:
                c = chunks.get(sid)
                if c is None:
                    continue
                units.append({
                    "chunk_id": c["chunk_id"],
                    "document_id": c["document_id"],
                    "document_version": c["document_version"],
                    "knowledge_id": item["knowledge_id"],
                    "knowledge_version": item["version"],
                    "text": c["text"],
                    "char_start": c["char_start"],
                    "char_end": c["char_end"],
                    "tenant_id": item["tenant_id"],
                    "customer_id": item["customer_id"],
                    "project_id": item["project_id"],
                    "data_scope": item["data_scope"],
                    "test_run_id": item["test_run_id"],
                    "permission_tags": json.loads(
                        item["permission_tags_json"] or "[]"),
                    "effective_from": item["effective_from"],
                    "effective_to": item["effective_to"],
                    "status": item["status"],
                    "title": item["title"],
                    "summary": item["summary"],
                })
        return units

    def build(self, ctx: CognitiveContext, *, target_kind: str,
              corpus_snapshot_id: str,
              vector_provider: Any = None,
              backend: str = "sqlite_lexical",
              parameters: dict | None = None) -> dict[str, Any]:
        if ctx is None:
            raise CognitionValidationError("缺 CognitiveContext")
        if target_kind != "knowledge":
            raise CognitionValidationError(
                f"V1 索引构建仅支持 knowledge（收到 {target_kind}）")
        if vector_provider is None:
            vector_provider = self.vector_provider
        params = dict(parameters or {})
        # R2-05：索引身份覆盖 target kind、corpus、backend、provider/
        # model/revision/dimension、normalization、analyzer、chunk
        # policy、canonical parameters。不同 dense model/参数必须产生
        # 不同 snapshot；lexical 与 dense 不得互相复用。
        ident = provider_identity(vector_provider
                                  if vector_provider is not None
                                  and vector_provider.available()
                                  else None)
        canonical_params = json.dumps(params, ensure_ascii=False,
                                      sort_keys=True)
        snapshot_id = "idx-" + hashlib.sha256(
            f"{target_kind}|{corpus_snapshot_id}|{backend}|"
            f"{ident['provider_id']}|{ident['model_name']}|"
            f"{ident['model_revision']}|{ident['dimension']}|"
            f"{ident['normalization_version']}|"
            f"{LEX_ANALYZER_VERSION}|{CHUNK_POLICY_VERSION}|"
            f"{canonical_params}".encode("utf-8")).hexdigest()[:20]
        existing = self.repo.get_build(snapshot_id)
        if existing is not None:
            return existing

        units = self._collect_knowledge_units()
        postings, _df = build_postings(
            [{"chunk_id": u["chunk_id"], "text": u["text"]}
             for u in units])
        vectors: dict[str, list[float]] = {}
        embedding_model = None
        if vector_provider is not None and vector_provider.available():
            embedding_model = identity_string(vector_provider)
            texts = [u["text"] for u in units]
            vecs = encode_documents(vector_provider, texts)
            for u, v in zip(units, vecs):
                vectors[u["chunk_id"]] = list(v)

        artifact = {
            "index_snapshot_id": snapshot_id,
            "target_kind": target_kind,
            "corpus_snapshot_id": corpus_snapshot_id,
            "units": {u["chunk_id"]: u for u in units},
            "postings": postings,
            "vectors": vectors,
            "embedding_model": embedding_model,
            # 查询侧 mismatch 判定依据（不含任何凭据）
            "vector_identity": ident,
            "parameters": params,
        }
        artifact_json = json.dumps(artifact, ensure_ascii=False,
                                   sort_keys=True)
        manifest_hash = hashlib.sha256(
            artifact_json.encode("utf-8")).hexdigest()
        # 写 artifact 文件（本地优先 CAS 风格）
        self.index_root.mkdir(parents=True, exist_ok=True)
        artifact_path = self.index_root / f"{snapshot_id}.json"
        artifact_path.write_text(artifact_json, encoding="utf-8")

        quality = {
            "unit_count": len(units),
            "vocab_size": len(postings),
            "has_vectors": bool(vectors),
            "vector_count": len(vectors),
            "unique_knowledge": len({u["knowledge_id"] for u in units}),
        }
        with UnitOfWork(self.store) as tx:
            self.repo.insert_build(
                tx, index_snapshot_id=snapshot_id,
                target_kind=target_kind,
                corpus_snapshot_id=corpus_snapshot_id, backend=backend,
                embedding_model=embedding_model,
                analyzer_version=LEX_ANALYZER_VERSION,
                chunk_policy_version=CHUNK_POLICY_VERSION,
                parameters=params, item_count=len(units),
                source_manifest_hash=manifest_hash,
                quality_report=quality, artifact_ref=str(artifact_path),
                created_by=ctx.principal_id, created_at=_now())
        return self.repo.get_build(snapshot_id)

    def load_artifact(self, build: dict[str, Any]) -> dict[str, Any]:
        path = Path(build["artifact_ref"])
        if not path.exists():
            raise CognitionIntegrityError(
                f"索引 artifact 缺失: {build['index_snapshot_id']}")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        # 完整性校验：artifact 哈希必须与 build 记录一致
        actual = hashlib.sha256(json.dumps(
            artifact, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")).hexdigest()
        if actual != build["source_manifest_hash"]:
            raise CognitionIntegrityError(
                f"索引 artifact 哈希漂移: {build['index_snapshot_id']}")
        return artifact

    # ---------- 激活（显式 registry + CAS） ----------

    def activate(self, ctx: CognitiveContext, *, target_kind: str,
                 index_snapshot_id: str,
                 expected_hash: str | None = None) -> dict[str, Any]:
        build = self.repo.get_build(index_snapshot_id)
        if build is None:
            raise CognitionValidationError(
                f"索引 build 不存在: {index_snapshot_id}")
        if build["target_kind"] != target_kind:
            raise CognitionValidationError(
                f"build target_kind 不匹配: {build['target_kind']}")
        if expected_hash is not None and \
                expected_hash != build["source_manifest_hash"]:
            raise CognitionIntegrityError(
                "激活 hash 校验失败（expected != build manifest hash）")
        activation_id = "act-" + uuid.uuid4().hex[:16]
        with UnitOfWork(self.store) as tx:
            self.repo.retire_activations(tx, target_kind)
            self.repo.insert_activation(
                tx, activation_id=activation_id, target_kind=target_kind,
                index_snapshot_id=index_snapshot_id,
                expected_hash=build["source_manifest_hash"],
                activated_by=ctx.principal_id, activated_at=_now())
        return build

    def active(self, target_kind: str) -> dict[str, Any] | None:
        act = self.repo.get_active_activation(target_kind)
        if act is None:
            return None
        return self.repo.get_build(act["index_snapshot_id"])

    def count_builds(self, target_kind: str) -> int:
        return self.repo.count_builds(target_kind)
