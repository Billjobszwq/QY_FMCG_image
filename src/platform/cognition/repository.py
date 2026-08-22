"""Cognition Repository + UnitOfWork（Task 5）。

边界规则：cognition/governance 业务服务不得直接访问 PlatformStore._conn；
所有持久化经 CognitionRepository 的类型化方法，写路径包在 UnitOfWork
事务中（失败整体回滚，不留半提交状态）。Repository 本身是唯一允许
接触底层连接的模块。
"""
from __future__ import annotations

import json
from typing import Any


class UnitOfWork:
    """SQLite 显式事务包装（PlatformStore 连接为 autocommit 模式）。"""

    def __init__(self, store: Any) -> None:
        self._conn = store._conn

    def __enter__(self) -> "UnitOfWork":
        self._conn.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            self._conn.execute("ROLLBACK")
        return False

    def execute(self, sql: str, params: tuple = ()) -> Any:
        return self._conn.execute(sql, params)


class CognitionRepository:
    """cognition_* 表的类型化访问（读路径 autocommit，写路径收 tx）。"""

    def __init__(self, store: Any) -> None:
        self.store = store

    # ---------- sources ----------

    def insert_source(self, tx: UnitOfWork, *, source_id: str,
                      artifact_ref: str, source_type: str,
                      original_uri: str, media_type: str, sha256: str,
                      tenant_id: str, permission_tags: tuple[str, ...],
                      trust_tier: str, captured_at: str, created_by: str,
                      customer_id: str = "", project_id: str = "",
                      effective_from: str | None = None,
                      effective_to: str | None = None,
                      status: str = "active",
                      quarantine_reason: str = "") -> None:
        tx.execute(
            "INSERT INTO cognition_source_artifact_v1 (source_id,"
            " artifact_ref, source_type, original_uri, media_type,"
            " sha256, tenant_id, customer_id, project_id,"
            " permission_tags_json, trust_tier, captured_at,"
            " effective_from, effective_to, status, quarantine_reason,"
            " created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (source_id, artifact_ref, source_type, original_uri,
             media_type, sha256, tenant_id, customer_id, project_id,
             json.dumps(list(permission_tags), ensure_ascii=False),
             trust_tier, captured_at, effective_from, effective_to,
             status, quarantine_reason, created_by))

    def find_source(self, source_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_source_artifact_v1 WHERE"
            " source_id=?", (source_id,)).fetchone()
        return dict(row) if row else None

    def find_source_by_origin(self, source_type: str, original_uri: str,
                              sha256: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_source_artifact_v1 WHERE"
            " source_type=? AND original_uri=? AND sha256=?",
            (source_type, original_uri, sha256)).fetchone()
        return dict(row) if row else None

    def set_source_status(self, tx: UnitOfWork, source_id: str,
                          status: str, *, reason: str = "") -> int:
        cur = tx.execute(
            "UPDATE cognition_source_artifact_v1 SET status=?,"
            " quarantine_reason=? WHERE source_id=?",
            (status, reason, source_id))
        return cur.rowcount

    def supersede_previous_sources(self, tx: UnitOfWork, *,
                                   source_type: str, original_uri: str,
                                   except_sha256: str) -> int:
        """同一 origin 内容已变：旧 source 行 → superseded（可回查但
        默认不检索；02 §8.3）。"""
        cur = tx.execute(
            "UPDATE cognition_source_artifact_v1 SET status='superseded'"
            " WHERE source_type=? AND original_uri=? AND sha256!=? AND"
            " status='active'",
            (source_type, original_uri, except_sha256))
        return cur.rowcount

    def count_sources(self) -> int:
        return self.store._conn.execute(
            "SELECT count(*) c FROM cognition_source_artifact_v1"
        ).fetchone()["c"]

    # ---------- document versions ----------

    def insert_document_version(self, tx: UnitOfWork, *, document_id: str,
                                version: int, source_id: str, title: str,
                                content_hash: str, parser_version: str,
                                normalization_version: str, language: str,
                                created_at: str) -> None:
        tx.execute(
            "INSERT INTO cognition_document_version_v1 (document_id,"
            " version, source_id, title, content_hash, parser_version,"
            " normalization_version, language, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?, 'draft', ?)",
            (document_id, version, source_id, title, content_hash,
             parser_version, normalization_version, language,
             created_at))

    def get_document_version(self, document_id: str,
                             version: int) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_document_version_v1 WHERE"
            " document_id=? AND version=?",
            (document_id, version)).fetchone()
        return dict(row) if row else None

    def latest_document_version(self, document_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_document_version_v1 WHERE"
            " document_id=? ORDER BY version DESC LIMIT 1",
            (document_id,)).fetchone()
        return dict(row) if row else None

    def list_version_statuses(self, document_id: str
                              ) -> list[tuple[int, str]]:
        rows = self.store._conn.execute(
            "SELECT version, status FROM cognition_document_version_v1"
            " WHERE document_id=? ORDER BY version",
            (document_id,)).fetchall()
        return [(r["version"], r["status"]) for r in rows]

    def publish_document_version(self, tx: UnitOfWork, document_id: str,
                                 version: int, *, owner: str,
                                 approved_by: str,
                                 published_at: str) -> int:
        """CAS：只有 draft/reviewed 可发布；同 document 旧 published
        版本同事务降为 superseded。"""
        cur = tx.execute(
            "UPDATE cognition_document_version_v1 SET status='published',"
            " owner=?, approved_by=?, published_at=? WHERE document_id=?"
            " AND version=? AND status IN ('draft','reviewed')",
            (owner, approved_by, published_at, document_id, version))
        tx.execute(
            "UPDATE cognition_document_version_v1 SET status='superseded'"
            " WHERE document_id=? AND status='published' AND version!=?",
            (document_id, version))
        return cur.rowcount

    def list_published_versions(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM cognition_document_version_v1 WHERE"
            " status='published' ORDER BY document_id, version"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- chunks ----------

    def insert_chunk(self, tx: UnitOfWork, *, chunk_id: str,
                     document_id: str, document_version: int,
                     ordinal: int, heading_path: list[str], text: str,
                     token_count: int, char_start: int, char_end: int,
                     content_hash: str,
                     parent_chunk_id: str | None = None) -> None:
        tx.execute(
            "INSERT INTO cognition_chunk_v1 (chunk_id, document_id,"
            " document_version, parent_chunk_id, ordinal,"
            " heading_path_json, text, token_count, char_start,"
            " char_end, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (chunk_id, document_id, document_version, parent_chunk_id,
             ordinal, json.dumps(heading_path, ensure_ascii=False),
             text, token_count, char_start, char_end, content_hash))

    def list_chunks(self, document_id: str, *,
                    version: int | None = None) -> list[dict]:
        if version is None:
            rows = self.store._conn.execute(
                "SELECT * FROM cognition_chunk_v1 WHERE document_id=?"
                " ORDER BY document_version DESC, ordinal",
                (document_id,)).fetchall()
        else:
            rows = self.store._conn.execute(
                "SELECT * FROM cognition_chunk_v1 WHERE document_id=?"
                " AND document_version=? ORDER BY ordinal",
                (document_id, version)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["heading_path"] = json.loads(d["heading_path_json"] or "[]")
            out.append(d)
        return out

    # ---------- spans ----------

    def insert_span(self, tx: UnitOfWork, *, span_id: str, chunk_id: str,
                    quote_start: int, quote_end: int, quote_hash: str,
                    normalized_quote: str, locator: dict,
                    created_at: str) -> None:
        tx.execute(
            "INSERT INTO cognition_evidence_span_v1 (span_id, chunk_id,"
            " quote_start, quote_end, quote_hash, normalized_quote,"
            " locator_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (span_id, chunk_id, quote_start, quote_end, quote_hash,
             normalized_quote,
             json.dumps(locator, ensure_ascii=False), created_at))

    def count_existing_spans(self, span_ids: list[str]) -> int:
        """发布门用：source_span_ids 必须真实存在（防伪 span id）。"""
        if not span_ids:
            return 0
        marks = ",".join("?" * len(span_ids))
        row = self.store._conn.execute(
            f"SELECT count(DISTINCT span_id) c FROM"
            f" cognition_evidence_span_v1 WHERE span_id IN ({marks})",
            tuple(span_ids)).fetchone()
        return int(row["c"])

    def get_span(self, span_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_evidence_span_v1 WHERE span_id=?",
            (span_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["locator"] = json.loads(d["locator_json"] or "{}")
        return d

    # ---------- corpus snapshots ----------

    def find_snapshot_by_hash(self, manifest_hash: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_corpus_snapshot_v1 WHERE"
            " manifest_hash=?", (manifest_hash,)).fetchone()
        return dict(row) if row else None

    def insert_snapshot(self, tx: UnitOfWork, *, corpus_snapshot_id: str,
                        manifest_hash: str, manifest_json: str,
                        item_count: int, created_by: str,
                        created_at: str) -> None:
        tx.execute(
            "INSERT INTO cognition_corpus_snapshot_v1"
            " (corpus_snapshot_id, manifest_hash, manifest_json,"
            " item_count, status, created_by, created_at)"
            " VALUES (?,?,?,?, 'ready', ?,?)",
            (corpus_snapshot_id, manifest_hash, manifest_json,
             item_count, created_by, created_at))

    def count_snapshots(self) -> int:
        return self.store._conn.execute(
            "SELECT count(*) c FROM cognition_corpus_snapshot_v1"
        ).fetchone()["c"]

    # ---------- knowledge_item_version ----------

    def insert_knowledge_version(self, tx: UnitOfWork, *,
                                 knowledge_id: str, version: int,
                                 type_: str, title: str, body: str,
                                 summary: str, owner: str,
                                 effective_from: str,
                                 effective_to: str | None,
                                 permission_tags: tuple[str, ...],
                                 source_span_ids: list[str],
                                 related_knowledge: list[str],
                                 extracted_entities: dict,
                                 created_by: str, created_at: str,
                                 tenant_id: str, customer_id: str,
                                 project_id: str, data_scope: str,
                                 test_run_id: str) -> None:
        tx.execute(
            "INSERT INTO knowledge_item_version (knowledge_id,"
            " version, type, title, body, summary, owner,"
            " effective_from, effective_to, status,"
            " permission_tags_json, source_span_ids_json,"
            " related_knowledge_json, extracted_entities_json,"
            " created_by, created_at, tenant_id, customer_id,"
            " project_id, data_scope, test_run_id) VALUES"
            " (?,?,?,?,?,?,?,?,?, 'draft',?,?,?,?,?,?,?,?,?,?,?)",
            (knowledge_id, version, type_, title, body, summary, owner,
             effective_from, effective_to,
             json.dumps(list(permission_tags), ensure_ascii=False),
             json.dumps(list(source_span_ids), ensure_ascii=False),
             json.dumps(related_knowledge, ensure_ascii=False),
             json.dumps(extracted_entities, ensure_ascii=False),
             created_by, created_at, tenant_id, customer_id, project_id,
             data_scope, test_run_id))

    def get_knowledge_version(self, knowledge_id: str,
                              version: int) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM knowledge_item_version WHERE knowledge_id=?"
            " AND version=?", (knowledge_id, version)).fetchone()
        return dict(row) if row else None

    def max_knowledge_version(self, knowledge_id: str) -> int:
        row = self.store._conn.execute(
            "SELECT max(version) v FROM knowledge_item_version WHERE"
            " knowledge_id=?", (knowledge_id,)).fetchone()
        return row["v"] or 0

    def cas_knowledge(self, tx: UnitOfWork, knowledge_id: str,
                      version: int, *, to_status: str,
                      from_statuses: tuple[str, ...],
                      extra_sets: str = "",
                      extra_params: tuple = ()) -> int:
        sql = ("UPDATE knowledge_item_version SET status=?"
               + extra_sets + " WHERE knowledge_id=? AND version=? AND"
               " status IN (" + ",".join(
                   "?" * len(from_statuses)) + ")")
        cur = tx.execute(sql, (to_status, *extra_params, knowledge_id,
                               version, *from_statuses))
        return cur.rowcount

    def list_knowledge_by_status(self, status: str, *,
                                 type_: str | None = None
                                 ) -> list[dict]:
        if type_:
            rows = self.store._conn.execute(
                "SELECT * FROM knowledge_item_version WHERE status=?"
                " AND type=?", (status, type_)).fetchall()
        else:
            rows = self.store._conn.execute(
                "SELECT * FROM knowledge_item_version WHERE status=?",
                (status,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- skill_definition_version ----------

    def insert_skill_version(self, tx: UnitOfWork, *, skill_id: str,
                             version: int, name: str, description: str,
                             skill_type: str, input_schema: dict,
                             output_schema: dict, execution_ref: str,
                             tool_scopes: list[str],
                             dependency_versions: dict,
                             applicable_scenarios: list[str],
                             forbidden_scenarios: list[str],
                             risk_level: str, approval_policy_id: str,
                             permission_tags: tuple[str, ...],
                             source_refs: list[str], evaluation_ref: str,
                             created_by: str, created_at: str,
                             tenant_id: str, customer_id: str,
                             project_id: str, data_scope: str,
                             test_run_id: str) -> None:
        tx.execute(
            "INSERT INTO skill_definition_version (skill_id, version,"
            " name, description, skill_type, input_schema_json,"
            " output_schema_json, execution_ref, tool_scopes_json,"
            " dependency_versions_json, applicable_scenarios_json,"
            " forbidden_scenarios_json, risk_level, approval_policy_id,"
            " permission_tags_json, source_refs_json, evaluation_ref,"
            " status, created_by, created_at, tenant_id, customer_id,"
            " project_id, data_scope, test_run_id) VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'draft',?,?,?,?,?,?,?)",
            (skill_id, version, name, description, skill_type,
             json.dumps(input_schema, ensure_ascii=False),
             json.dumps(output_schema, ensure_ascii=False),
             execution_ref,
             json.dumps(tool_scopes, ensure_ascii=False),
             json.dumps(dependency_versions, ensure_ascii=False),
             json.dumps(applicable_scenarios, ensure_ascii=False),
             json.dumps(forbidden_scenarios, ensure_ascii=False),
             risk_level, approval_policy_id,
             json.dumps(list(permission_tags), ensure_ascii=False),
             json.dumps(source_refs, ensure_ascii=False), evaluation_ref,
             created_by, created_at, tenant_id, customer_id, project_id,
             data_scope, test_run_id))

    def get_skill_version(self, skill_id: str,
                          version: int) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM skill_definition_version WHERE skill_id=? AND"
            " version=?", (skill_id, version)).fetchone()
        return dict(row) if row else None

    def max_skill_version(self, skill_id: str) -> int:
        row = self.store._conn.execute(
            "SELECT max(version) v FROM skill_definition_version WHERE"
            " skill_id=?", (skill_id,)).fetchone()
        return row["v"] or 0

    def cas_skill(self, tx: UnitOfWork, skill_id: str, version: int, *,
                  to_status: str, from_statuses: tuple[str, ...],
                  extra_sets: str = "",
                  extra_params: tuple = ()) -> int:
        sql = ("UPDATE skill_definition_version SET status=?"
               + extra_sets + " WHERE skill_id=? AND version=? AND"
               " status IN (" + ",".join(
                   "?" * len(from_statuses)) + ")")
        cur = tx.execute(sql, (to_status, *extra_params, skill_id,
                               version, *from_statuses))
        return cur.rowcount

    def list_skill_versions(self, skill_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM skill_definition_version WHERE skill_id=?"
            " ORDER BY version DESC", (skill_id,)).fetchall()
        return [dict(r) for r in rows]

    def list_skills_by_status(self, status: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM skill_definition_version WHERE status=? AND"
            " status!='revoked' ORDER BY skill_id, version",
            (status,)).fetchall()
        return [dict(r) for r in rows]

    def list_skills_not_revoked(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM skill_definition_version WHERE status!="
            " 'revoked' ORDER BY skill_id, version").fetchall()
        return [dict(r) for r in rows]

    # ---------- memory L1/L2/L3 ----------

    def insert_l1(self, tx: UnitOfWork, *, event_id: str, task_id: str,
                  run_id: str, node_id: str, actor_id: str,
                  actor_kind: str, event_type: str, payload: dict,
                  context_meaning: str | None,
                  evidence_refs: list[str], occurred_at: str,
                  ingested_at: str, permission_tags: tuple[str, ...],
                  retention_class: str, supersedes: str | None,
                  tenant_id: str, customer_id: str, project_id: str,
                  data_scope: str, test_run_id: str) -> None:
        tx.execute(
            "INSERT INTO memory_l1_event (event_id, task_id, run_id,"
            " node_id, actor_id, actor_kind, event_type, payload_json,"
            " context_meaning, evidence_refs_json, occurred_at,"
            " ingested_at, permission_tags_json, retention_class,"
            " supersedes, tenant_id, customer_id, project_id,"
            " data_scope, test_run_id) VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, task_id, run_id, node_id, actor_id, actor_kind,
             event_type, json.dumps(payload, ensure_ascii=False),
             context_meaning,
             json.dumps(evidence_refs, ensure_ascii=False), occurred_at,
             ingested_at,
             json.dumps(list(permission_tags), ensure_ascii=False),
             retention_class, supersedes, tenant_id, customer_id,
             project_id, data_scope, test_run_id))

    def get_l1(self, event_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM memory_l1_event WHERE event_id=?",
            (event_id,)).fetchone()
        return dict(row) if row else None

    def list_l1(self, *, task_id: str = "", limit: int = 500
                ) -> list[dict]:
        if task_id:
            rows = self.store._conn.execute(
                "SELECT * FROM memory_l1_event WHERE task_id=?"
                " ORDER BY occurred_at, rowid LIMIT ?",
                (task_id, limit)).fetchall()
        else:
            rows = self.store._conn.execute(
                "SELECT * FROM memory_l1_event ORDER BY occurred_at,"
                " rowid LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def insert_l2(self, tx: UnitOfWork, *, episode_id: str, task_id: str,
                  period_start: str, period_end: str, entities: list,
                  solution: str, result: str, issues: list,
                  conflicts: list, source_l1_ids: list[str],
                  source_hash: str, consolidator_version: str,
                  confidence: float, permission_tags: tuple[str, ...],
                  created_by: str, created_at: str, tenant_id: str,
                  customer_id: str, project_id: str, data_scope: str,
                  test_run_id: str) -> None:
        tx.execute(
            "INSERT INTO memory_l2_episode (episode_id, task_id,"
            " period_start, period_end, entities_json, solution,"
            " result, issues_json, conflicts_json, source_l1_ids_json,"
            " source_hash, consolidator_version, confidence, status,"
            " permission_tags_json, created_by, created_at, tenant_id,"
            " customer_id, project_id, data_scope, test_run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'candidate',?,?,?,?,?"
            ",?,?,?)",
            (episode_id, task_id, period_start, period_end,
             json.dumps(entities, ensure_ascii=False), solution, result,
             json.dumps(issues, ensure_ascii=False),
             json.dumps(conflicts, ensure_ascii=False),
             json.dumps(sorted(source_l1_ids), ensure_ascii=False),
             source_hash, consolidator_version, float(confidence),
             json.dumps(list(permission_tags), ensure_ascii=False),
             created_by, created_at, tenant_id, customer_id, project_id,
             data_scope, test_run_id))

    def get_l2(self, episode_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM memory_l2_episode WHERE episode_id=?",
            (episode_id,)).fetchone()
        return dict(row) if row else None

    def find_l2_by_source_hash(self, source_hash: str,
                               consolidator_version: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM memory_l2_episode WHERE source_hash=? AND"
            " consolidator_version=?",
            (source_hash, consolidator_version)).fetchone()
        return dict(row) if row else None

    def cas_l2(self, tx: UnitOfWork, episode_id: str, *, to_status: str,
               from_statuses: tuple[str, ...], extra_sets: str = "",
               extra_params: tuple = ()) -> int:
        sql = ("UPDATE memory_l2_episode SET status=?" + extra_sets +
               " WHERE episode_id=? AND status IN (" + ",".join(
                   "?" * len(from_statuses)) + ")")
        cur = tx.execute(sql, (to_status, *extra_params, episode_id,
                               *from_statuses))
        return cur.rowcount

    def list_l2(self, *, status: str, task_id: str = "") -> list[dict]:
        if task_id:
            rows = self.store._conn.execute(
                "SELECT * FROM memory_l2_episode WHERE status=? AND"
                " task_id=? ORDER BY created_at",
                (status, task_id)).fetchall()
        else:
            rows = self.store._conn.execute(
                "SELECT * FROM memory_l2_episode WHERE status=?"
                " ORDER BY created_at", (status,)).fetchall()
        return [dict(r) for r in rows]

    def insert_l3(self, tx: UnitOfWork, *, methodology_id: str,
                  version: int, statement: str,
                  trigger_conditions: list, scope: dict,
                  confidence: float, source_l2_ids: list[str],
                  supporting_event_count: int,
                  counterexample_ids: list[str], created_by: str,
                  created_at: str, tenant_id: str, customer_id: str,
                  project_id: str, data_scope: str,
                  test_run_id: str) -> None:
        tx.execute(
            "INSERT INTO memory_l3_methodology_version"
            " (methodology_id, version, statement,"
            " trigger_conditions_json, scope_json, confidence,"
            " source_l2_ids_json, supporting_event_count,"
            " counterexample_ids_json, status, created_by, created_at,"
            " tenant_id, customer_id, project_id, data_scope,"
            " test_run_id) VALUES"
            " (?,1,?,?,?,?,?,?,?, 'candidate',?,?,?,?,?,?,?)",
            (methodology_id, statement,
             json.dumps(trigger_conditions, ensure_ascii=False),
             json.dumps(scope, ensure_ascii=False), float(confidence),
             json.dumps(sorted(source_l2_ids), ensure_ascii=False),
             supporting_event_count,
             json.dumps(counterexample_ids, ensure_ascii=False),
             created_by, created_at, tenant_id, customer_id, project_id,
             data_scope, test_run_id))

    def get_l3(self, methodology_id: str, version: int) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM memory_l3_methodology_version WHERE"
            " methodology_id=? AND version=?",
            (methodology_id, version)).fetchone()
        return dict(row) if row else None

    def max_l3_version(self, methodology_id: str) -> int:
        row = self.store._conn.execute(
            "SELECT max(version) v FROM memory_l3_methodology_version"
            " WHERE methodology_id=?", (methodology_id,)).fetchone()
        return row["v"] or 0

    def cas_l3(self, tx: UnitOfWork, methodology_id: str, version: int,
               *, to_status: str, from_statuses: tuple[str, ...],
               extra_sets: str = "", extra_params: tuple = ()) -> int:
        sql = ("UPDATE memory_l3_methodology_version SET status=?"
               + extra_sets + " WHERE methodology_id=? AND version=? AND"
               " status IN (" + ",".join(
                   "?" * len(from_statuses)) + ")")
        cur = tx.execute(sql, (to_status, *extra_params, methodology_id,
                               version, *from_statuses))
        return cur.rowcount

    def append_l3_counterexamples(self, tx: UnitOfWork,
                                  methodology_id: str, version: int,
                                  counterexample_ids: list[str]) -> int:
        cur = tx.execute(
            "UPDATE memory_l3_methodology_version SET"
            " counterexample_ids_json=? WHERE methodology_id=? AND"
            " version=?",
            (json.dumps(sorted(set(counterexample_ids)),
                        ensure_ascii=False), methodology_id, version))
        return cur.rowcount

    def list_l3(self, *, status: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM memory_l3_methodology_version WHERE status=?"
            " ORDER BY methodology_id, version", (status,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 旧表只读兼容（迁移期；禁写） ----------

    def list_legacy_knowledge_documents(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM knowledge_document_v1 ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_legacy_skill_assets(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM agent_asset_v1 WHERE kind='skill'"
            " ORDER BY asset_id, version").fetchall()
        return [dict(r) for r in rows]

    # ---------- 索引构建 / 激活注册表（Task 8） ----------

    def get_snapshot_by_id(self, corpus_snapshot_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_corpus_snapshot_v1 WHERE"
            " corpus_snapshot_id=?", (corpus_snapshot_id,)).fetchone()
        return dict(row) if row else None

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[dict]:
        if not chunk_ids:
            return []
        marks = ",".join("?" * len(chunk_ids))
        rows = self.store._conn.execute(
            f"SELECT * FROM cognition_chunk_v1 WHERE chunk_id IN"
            f" ({marks})", tuple(chunk_ids)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["heading_path"] = json.loads(d["heading_path_json"] or "[]")
            out.append(d)
        return out

    def insert_build(self, tx: UnitOfWork, *, index_snapshot_id: str,
                     target_kind: str, corpus_snapshot_id: str,
                     backend: str, embedding_model: str | None,
                     analyzer_version: str, chunk_policy_version: str,
                     parameters: dict, item_count: int,
                     source_manifest_hash: str, quality_report: dict,
                     artifact_ref: str, created_by: str,
                     created_at: str) -> None:
        tx.execute(
            "INSERT INTO cognition_index_build_v1 (index_snapshot_id,"
            " target_kind, corpus_snapshot_id, backend, embedding_model,"
            " reranker_model, analyzer_version, chunk_policy_version,"
            " parameters_json, item_count, source_manifest_hash,"
            " build_status, quality_report_json, artifact_ref,"
            " created_by, created_at) VALUES"
            " (?,?,?,?,?,NULL,?,?,?,?,?, 'ready',?,?,?,?)",
            (index_snapshot_id, target_kind, corpus_snapshot_id, backend,
             embedding_model, analyzer_version, chunk_policy_version,
             json.dumps(parameters, ensure_ascii=False), item_count,
             source_manifest_hash,
             json.dumps(quality_report, ensure_ascii=False), artifact_ref,
             created_by, created_at))

    def get_build(self, index_snapshot_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_index_build_v1 WHERE"
            " index_snapshot_id=?", (index_snapshot_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["quality_report"] = json.loads(d["quality_report_json"] or "{}")
        d["parameters"] = json.loads(d["parameters_json"] or "{}")
        return d

    def count_builds(self, target_kind: str) -> int:
        row = self.store._conn.execute(
            "SELECT count(*) c FROM cognition_index_build_v1 WHERE"
            " target_kind=?", (target_kind,)).fetchone()
        return int(row["c"])

    def retire_activations(self, tx: UnitOfWork, target_kind: str) -> int:
        cur = tx.execute(
            "UPDATE cognition_index_activation_v1 SET status='retired',"
            " retired_at=? WHERE target_kind=? AND status='active'",
            (_now_iso(), target_kind))
        return cur.rowcount

    def insert_activation(self, tx: UnitOfWork, *, activation_id: str,
                          target_kind: str, index_snapshot_id: str,
                          expected_hash: str, activated_by: str,
                          activated_at: str) -> None:
        tx.execute(
            "INSERT INTO cognition_index_activation_v1 (activation_id,"
            " target_kind, index_snapshot_id, expected_hash, status,"
            " activated_by, activated_at) VALUES"
            " (?,?,?,?, 'active',?,?)",
            (activation_id, target_kind, index_snapshot_id, expected_hash,
             activated_by, activated_at))

    def get_active_activation(self, target_kind: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM cognition_index_activation_v1 WHERE"
            " target_kind=? AND status='active' ORDER BY activated_at"
            " DESC, rowid DESC LIMIT 1", (target_kind,)).fetchone()
        return dict(row) if row else None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
