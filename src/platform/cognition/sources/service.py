"""Source 摄取服务（Task 5 / G3）。

流水线（03 §2）：policy/上下文校验 → 不可变 CAS 捕获 → 注入扫描 →
parser → 版本化 document → 结构化 chunk。全部写路径经 Repository/UoW
（本模块不接触底层连接句柄）。

幂等契约：
- 同 (source_type, original_uri, sha256) 重复摄取返回同一 source；
- 同 document 的内容哈希不变则不产生新版本；
- corpus snapshot 按 manifest_hash 幂等。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..context import CognitiveContext
from ..errors import (
    CognitionConflictError,
    CognitionPolicyError,
    CognitionValidationError,
)
from ..repository import CognitionRepository, UnitOfWork
from . import chunking, parsers

NORMALIZATION_VERSION = "norm@1"
_SOURCE_TYPES = ("file", "url", "api", "database", "manual")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SourceService:
    def __init__(self, store: Any, *, cas_root: Path | str) -> None:
        self.store = store
        self.repo = CognitionRepository(store)
        self.cas_root = Path(cas_root)

    # ---------- CAS ----------

    def cas_path(self, sha256: str) -> Path:
        return self.cas_root / sha256[:2] / sha256

    def _write_cas(self, data: bytes, sha256: str) -> str:
        dest = self.cas_path(sha256)
        if dest.exists():
            return f"cas:{sha256}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)  # 原子发布
        return f"cas:{sha256}"

    # ---------- 摄取 ----------

    def ingest(self, ctx: CognitiveContext, *, source_type: str,
               original_uri: str, media_type: str, content: bytes,
               permission_tags: tuple[str, ...] | list[str],
               trust_tier: str, effective_from: str | None = None,
               effective_to: str | None = None) -> dict[str, Any]:
        # ---- fail-closed 校验 ----
        if ctx is None:
            raise CognitionValidationError("缺 CognitiveContext")
        if source_type not in _SOURCE_TYPES:
            raise CognitionValidationError(
                f"非法 source_type: {source_type}")
        if not original_uri or not str(original_uri).strip():
            raise CognitionValidationError(
                "original_uri 必填（空 uri 会让无关来源共享版本链）")
        tags = list(permission_tags or [])
        if not tags or any(not isinstance(t, str) or not t for t in tags):
            raise CognitionValidationError(
                "permission_tags 必填且为非空字符串序列（fail-closed）")
        if not isinstance(content, bytes) or not content.strip():
            raise CognitionValidationError("内容为空（拒绝摄取）")
        if not parsers.supports(media_type):
            from ..errors import CognitionProviderError
            raise CognitionProviderError(
                f"V1 不支持的 media_type: {media_type}（诚实失败，"
                "不伪装成功）")
        # trust_tier 策略：外部来源不得自报 authoritative（冲突裁决
        # 依赖权威层级；自报会污染优先级，评审 #20）
        if source_type in ("url", "api") and trust_tier == "authoritative":
            raise CognitionValidationError(
                f"source_type={source_type} 不得自报 authoritative"
                "（外部来源最高 external_primary）")

        # ---- parser 先行：解析失败（非法 UTF-8 等）必须在任何写入
        # 之前失败，杜绝 source 行落库而 document 为空的半提交 ----
        parsed = parsers.parse(media_type, content)

        sha = _sha256(content)
        document_id = "doc-" + hashlib.sha256(
            f"{source_type}|{original_uri}".encode("utf-8")
        ).hexdigest()[:20]
        # ---- 幂等：同一来源同一内容直接返回 ----
        existing = self.repo.find_source_by_origin(source_type,
                                                   original_uri, sha)
        if existing is not None:
            doc = self.repo.latest_document_version(document_id)
            chunks = (self.repo.list_chunks(doc["document_id"],
                                            version=doc["version"])
                      if doc else [])
            return {"source": existing, "document": doc,
                    "chunks": chunks,
                    "quarantine_reason": existing["quarantine_reason"]}

        # ---- 不可变 CAS 捕获 ----
        artifact_ref = self._write_cas(content, sha)

        # ---- 注入扫描（外部内容不可信） ----
        text = content.decode("utf-8", errors="replace")
        injection_hit = parsers.scan_for_injection(text)
        status = "quarantined" if injection_hit else "active"
        reason = (f"prompt_injection_pattern:{injection_hit}"
                  if injection_hit else "")

        # source_id 必须按来源唯一（同内容不同 uri 是两个 source，
        # 评审 #2）：origin + 内容哈希派生。
        source_id = "src-" + hashlib.sha256(
            f"{source_type}|{original_uri}|{sha}".encode("utf-8")
        ).hexdigest()[:20]

        with UnitOfWork(self.store) as tx:
            # 同一 origin 的旧 source（内容已变）→ superseded（评审 #8）
            self.repo.supersede_previous_sources(
                tx, source_type=source_type, original_uri=original_uri,
                except_sha256=sha)
            self.repo.insert_source(
                tx, source_id=source_id, artifact_ref=artifact_ref,
                source_type=source_type, original_uri=original_uri,
                media_type=media_type, sha256=sha,
                tenant_id=ctx.tenant_id,
                customer_id=ctx.customer_id,
                project_id=ctx.project_id,
                permission_tags=tuple(tags), trust_tier=trust_tier,
                captured_at=_now(), created_by=ctx.principal_id,
                effective_from=effective_from,
                effective_to=effective_to, status=status,
                quarantine_reason=reason)

        # ---- 注入 → 治理告警（02 §8.1；评审 #7） ----
        if injection_hit:
            self._alert_quarantine(source_id, injection_hit)

        # ---- 版本化 document + chunk + span ----
        content_hash = hashlib.sha256(
            parsed.content.encode("utf-8")).hexdigest()
        latest = self.repo.latest_document_version(document_id)
        if latest is not None and latest["content_hash"] == content_hash:
            doc, chunks = latest, self.repo.list_chunks(
                document_id, version=latest["version"])
        else:
            version = (latest["version"] + 1) if latest else 1
            specs = (chunking.chunk_markdown(parsed.content)
                     if media_type == "text/markdown"
                     else chunking.chunk_plain_text(parsed.content))
            with UnitOfWork(self.store) as tx:
                self.repo.insert_document_version(
                    tx, document_id=document_id, version=version,
                    source_id=source_id, title=parsed.title,
                    content_hash=content_hash,
                    parser_version=parsed.parser_version,
                    normalization_version=NORMALIZATION_VERSION,
                    language=parsed.language, created_at=_now())
                for spec in specs:
                    chunk_id = (f"chk-{document_id}-v{version}-"
                                f"{spec['ordinal']}")
                    self.repo.insert_chunk(
                        tx,
                        chunk_id=chunk_id,
                        document_id=document_id,
                        document_version=version,
                        ordinal=spec["ordinal"],
                        heading_path=spec["heading_path"],
                        text=spec["text"],
                        token_count=spec["token_count"],
                        char_start=spec["char_start"],
                        char_end=spec["char_end"],
                        content_hash=spec["content_hash"])
                    # chunk 级 evidence span（全 chunk 引用；span_id ==
                    # chunk_id，保证 knowledge 发布门的 source span 可
                    # 回查，评审 #1/#16）
                    self.repo.insert_span(
                        tx, span_id=chunk_id, chunk_id=chunk_id,
                        quote_start=spec["char_start"],
                        quote_end=spec["char_end"],
                        quote_hash=spec["content_hash"],
                        normalized_quote=spec["text"][:200],
                        locator={"document_id": document_id,
                                 "document_version": version,
                                 "chunk_id": chunk_id,
                                 "heading_path": spec["heading_path"],
                                 "char_start": spec["char_start"],
                                 "char_end": spec["char_end"]},
                        created_at=_now())
            doc = self.repo.get_document_version(document_id, version)
            chunks = self.repo.list_chunks(document_id, version=version)
        return {"source": self.repo.find_source(source_id),
                "document": doc, "chunks": chunks,
                "quarantine_reason": reason}

    def _alert_quarantine(self, source_id: str, pattern: str) -> None:
        from ...governance.alert_service import AlertService
        AlertService(self.store).raise_alert(
            actor="cognition_source_service", role="system",
            severity="critical",
            content=f"摄取内容命中注入模式被隔离: source={source_id}",
            rule_id="injection_quarantine",
            evidence_refs=[f"cognition_source:{source_id}"],
            recommended_action="人工复核后决定保留隔离或放行",
            pause_requested=False)

    # ---------- 发布门 ----------

    APPROVAL_KIND_PUBLISH = "cognition.document.publish"

    def publish(self, document_id: str, version: int, *,
                ctx: CognitiveContext, approver: str, owner: str,
                approval_id: str) -> dict[str, Any]:
        """03 §2.2 发布门：owner/approver 必填 + governance approval
        账本（maker≠checker，评审 #12）；quarantined/revoked source
        不得发布；CAS draft/reviewed → published，旧 published 版本同
        事务 superseded。"""
        if not approver or not owner:
            raise CognitionValidationError(
                "发布必须提供人类 approver 与 owner")
        doc = self.repo.get_document_version(document_id, version)
        if doc is None:
            raise CognitionValidationError(
                f"document 不存在: {document_id}@v{version}")
        source = self.repo.find_source(doc["source_id"])
        if source is not None and source["status"] in (
                "quarantined", "revoked", "superseded"):
            raise CognitionPolicyError(
                f"source {doc['source_id']} 处于"
                f" {source['status']}，禁止进入 published corpus"
                f"（reason={source['quarantine_reason']}）")
        from ...governance.policy_service import PolicyService
        PolicyService(self.store).verify_approved(
            approval_id, kind=self.APPROVAL_KIND_PUBLISH,
            subject_ref=f"doc:{document_id}@v{version}",
            approver=approver,
            created_by=(source or {}).get("created_by", ""))
        with UnitOfWork(self.store) as tx:
            rc = self.repo.publish_document_version(
                tx, document_id, version, owner=owner,
                approved_by=approver, published_at=_now())
        if rc == 0:
            raise CognitionConflictError(
                f"document {document_id}@v{version} 不在可发布状态"
                "（CAS 拒绝）")
        return self.repo.get_document_version(document_id, version)

    # ---------- corpus snapshot ----------

    def build_corpus_snapshot(self, ctx: CognitiveContext
                              ) -> dict[str, Any]:
        published = self.repo.list_published_versions()
        items = [{"document_id": d["document_id"],
                  "version": d["version"],
                  "content_hash": d["content_hash"],
                  "source_id": d["source_id"],
                  "title": d["title"]} for d in published]
        items.sort(key=lambda x: (x["document_id"], x["version"]))
        manifest_json = json.dumps(items, sort_keys=True,
                                   ensure_ascii=False)
        manifest_hash = hashlib.sha256(
            manifest_json.encode("utf-8")).hexdigest()
        existing = self.repo.find_snapshot_by_hash(manifest_hash)
        if existing is not None:
            return existing
        snapshot_id = "corpus-" + manifest_hash[:16]
        with UnitOfWork(self.store) as tx:
            self.repo.insert_snapshot(
                tx, corpus_snapshot_id=snapshot_id,
                manifest_hash=manifest_hash, manifest_json=manifest_json,
                item_count=len(items), created_by=ctx.principal_id,
                created_at=_now())
        row = self.repo.find_snapshot_by_hash(manifest_hash)
        return row
