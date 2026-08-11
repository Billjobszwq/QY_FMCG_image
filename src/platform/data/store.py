"""PlatformStore — SQLite 开发适配器（M1–M3 专用，M6 一次性迁移 PostgreSQL）。

设计约束：
- 只暴露类型化方法；不存在任意 SQL / shell / 文件系统逃逸口。
- migration 只追加；已应用 migration 的 sha256 校验，防篡改。
- 时间戳 UTC ISO-8601。
- WAL + busy timeout，与旧 warehouse 同款并发策略（ISSUE-007 教训）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RUN_STATUSES = ("pending", "running", "waiting_human", "completed", "failed", "cancelled")
NODE_STATUSES = ("pending", "running", "completed", "failed", "skipped")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "expired")


class StoreError(Exception):
    """PlatformStore 域错误（非法状态、缺失记录、重复主键、migration 篡改）。"""


_M001 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_run (
    run_id TEXT PRIMARY KEY,
    graph_name TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','waiting_human','completed','failed','cancelled')),
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT,
    error TEXT,
    request_id TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS node_execution (
    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES graph_run(run_id),
    node_name TEXT NOT NULL,
    seq INTEGER NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('pending','running','completed','failed','skipped')),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    output_json TEXT,
    error TEXT,
    UNIQUE (run_id, node_name, seq, attempt)
);

CREATE TABLE IF NOT EXISTS checkpoint (
    run_id TEXT NOT NULL REFERENCES graph_run(run_id),
    node_name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, node_name)
);

CREATE TABLE IF NOT EXISTS job (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_attempt (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES job(job_id),
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS audit_event (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_subject ON audit_event(subject_type, subject_id);

CREATE TABLE IF NOT EXISTS usage_event (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    capability TEXT NOT NULL,
    run_id TEXT,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_usage_run ON usage_event(run_id);

CREATE TABLE IF NOT EXISTS evidence_bundle (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph_run(run_id),
    kind TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset (
    asset_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    kind TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    media_type TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (sha256, kind)
);
"""

_M002 = """
CREATE TABLE IF NOT EXISTS labeling_batch (
    batch_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    assisted_project_id INTEGER,
    blind_project_id INTEGER,
    task_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'created'
        CHECK (status IN ('created','imported','annotating','reconciled','closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    event_id TEXT NOT NULL,
    action TEXT NOT NULL,
    project_id INTEGER,
    task_id INTEGER,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE (source, event_id)
);
"""

_M003 = """
CREATE TABLE IF NOT EXISTS dataset_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    mode TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    guard_json TEXT NOT NULL,
    source_actor TEXT NOT NULL,
    source_conclusion TEXT NOT NULL,
    quality_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'registered'
        CHECK (status IN ('registered','rejected','superseded')),
    created_at TEXT NOT NULL,
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS training_run (
    run_id TEXT PRIMARY KEY,
    snapshot_id TEXT REFERENCES dataset_snapshot(snapshot_id),
    kind TEXT NOT NULL DEFAULT 'dry_run'
        CHECK (kind IN ('dry_run','authorized','started','completed_candidate','cancelled')),
    plan_json TEXT NOT NULL,
    command_json TEXT NOT NULL,
    budget_json TEXT NOT NULL,
    stop_lines_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'dry_run',
    publish_status TEXT NOT NULL DEFAULT 'none'
        CHECK (publish_status IN ('none','requested','approved','rejected','published')),
    requested_by TEXT,
    approved_by TEXT,
    publish_requested_by TEXT,
    publish_approved_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_flag (
    flag TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);

INSERT OR IGNORE INTO platform_flag (flag, value, updated_at, updated_by)
VALUES ('training_authorized', 'false', '1970-01-01T00:00:00+00:00', 'system');
"""

_M004 = """
ALTER TABLE job ADD COLUMN lease_until TEXT;
ALTER TABLE job ADD COLUMN worker_id TEXT;
ALTER TABLE job ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE job ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3;
CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);

CREATE TABLE IF NOT EXISTS share_token (
    token TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    subject_id TEXT,
    expires_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
"""

_M005 = """
ALTER TABLE dataset_snapshot ADD COLUMN trainable INTEGER NOT NULL DEFAULT 1;
ALTER TABLE dataset_snapshot ADD COLUMN status_note TEXT NOT NULL DEFAULT '';
"""

_M006 = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""

_M007 = """
ALTER TABLE training_run ADD COLUMN job_id TEXT NOT NULL DEFAULT '';
"""

_M008 = """
CREATE TABLE IF NOT EXISTS recognition_task (
    task_id TEXT PRIMARY KEY,
    entry TEXT NOT NULL,
    status TEXT NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    sku_count INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);
"""

_M009 = """
ALTER TABLE recognition_task
    ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_recognition_task_idem
    ON recognition_task(idempotency_key);
"""

# U3-2：不可变 source_asset_inventory_v1（追加式；原图不动，只登记引用）。
# 触发器禁止 DELETE/UPDATE；唯一键为 (source_id, source_uri)，同 SHA 不同来源各自保留。
_M010 = """
CREATE TABLE IF NOT EXISTS source_asset_inventory_v1 (
    asset_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    photo_id TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL,
    UNIQUE(source_id, source_uri)
);
CREATE INDEX IF NOT EXISTS idx_inventory_v1_sha
    ON source_asset_inventory_v1(sha256);
CREATE INDEX IF NOT EXISTS idx_inventory_v1_source
    ON source_asset_inventory_v1(source_id);
CREATE TRIGGER inventory_v1_no_delete
    BEFORE DELETE ON source_asset_inventory_v1
BEGIN
    SELECT RAISE(ABORT, 'source_asset_inventory_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER inventory_v1_no_update
    BEFORE UPDATE ON source_asset_inventory_v1
BEGIN
    SELECT RAISE(ABORT, 'source_asset_inventory_v1 不可变：禁止 UPDATE');
END;
"""

# U3-5：质量结论台账 quality_decision_v1（追加式不可变）。
# 全字段：原图 SHA、策略版本、分数、阈值、自动结论、人工结论、模型版本、证据。
_M011 = """
CREATE TABLE IF NOT EXISTS quality_decision_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    score_json TEXT NOT NULL,
    threshold_json TEXT NOT NULL,
    auto_decision TEXT NOT NULL,
    human_decision TEXT,
    model_version TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_decision_sha
    ON quality_decision_v1(sha256);
CREATE TRIGGER quality_decision_v1_no_delete
    BEFORE DELETE ON quality_decision_v1
BEGIN
    SELECT RAISE(ABORT, 'quality_decision_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER quality_decision_v1_no_update
    BEFORE UPDATE ON quality_decision_v1
BEGIN
    SELECT RAISE(ABORT, 'quality_decision_v1 不可变：禁止 UPDATE');
END;
"""

# U3-6：人工质量金标准队列 quality_gold_v1 + 人工结论 quality_human_v1
#（均追加式不可变；人工未完成时状态只能推导为 waiting_human）。
_M012 = """
CREATE TABLE IF NOT EXISTS quality_gold_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    source_uri TEXT NOT NULL DEFAULT '',
    stratum TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER quality_gold_v1_no_delete
    BEFORE DELETE ON quality_gold_v1
BEGIN
    SELECT RAISE(ABORT, 'quality_gold_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER quality_gold_v1_no_update
    BEFORE UPDATE ON quality_gold_v1
BEGIN
    SELECT RAISE(ABORT, 'quality_gold_v1 不可变：禁止 UPDATE');
END;
CREATE TABLE IF NOT EXISTS quality_human_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    verdict TEXT NOT NULL,
    dims_json TEXT NOT NULL DEFAULT '{}',
    reviewer TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_human_sha
    ON quality_human_v1(sha256);
CREATE TRIGGER quality_human_v1_no_delete
    BEFORE DELETE ON quality_human_v1
BEGIN
    SELECT RAISE(ABORT, 'quality_human_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER quality_human_v1_no_update
    BEFORE UPDATE ON quality_human_v1
BEGIN
    SELECT RAISE(ABORT, 'quality_human_v1 不可变：禁止 UPDATE');
END;
"""

# U4-1：SAM 辅助标注 lineage sam_lineage_v1（point→prompt→mask→box
# 全链路，追加式不可变；manual_required 时 tight_box 恒为 NULL）。
_M013 = """
CREATE TABLE IF NOT EXISTS sam_lineage_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    photo_id TEXT NOT NULL DEFAULT '',
    image_sha256 TEXT NOT NULL,
    point_x REAL NOT NULL,
    point_y REAL NOT NULL,
    prompt_config_version TEXT NOT NULL,
    positive_point_json TEXT NOT NULL,
    negative_points_json TEXT NOT NULL DEFAULT '[]',
    coarse_box_json TEXT,
    model TEXT NOT NULL,
    checkpoint_sha256 TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL,
    escalated_to TEXT,
    tight_box_json TEXT,
    mask_sha256 TEXT,
    mask_path TEXT,
    selection_reason TEXT NOT NULL DEFAULT '',
    rules_version TEXT NOT NULL DEFAULT '',
    reject_reasons_json TEXT NOT NULL DEFAULT '[]',
    run_dir TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sam_lineage_sha
    ON sam_lineage_v1(image_sha256);
CREATE INDEX IF NOT EXISTS idx_sam_lineage_instance
    ON sam_lineage_v1(instance_id);
CREATE TRIGGER sam_lineage_v1_no_delete
    BEFORE DELETE ON sam_lineage_v1
BEGIN
    SELECT RAISE(ABORT, 'sam_lineage_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER sam_lineage_v1_no_update
    BEFORE UPDATE ON sam_lineage_v1
BEGIN
    SELECT RAISE(ABORT, 'sam_lineage_v1 不可变：禁止 UPDATE');
END;
"""

_M014 = """
CREATE TABLE IF NOT EXISTS review_task_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    claim_token TEXT NOT NULL UNIQUE,
    photo_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    review_mode TEXT NOT NULL,
    requires_second_review INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    claimed_by TEXT,
    queue_version TEXT NOT NULL DEFAULT 'rq_v1',
    protocol TEXT NOT NULL DEFAULT '',
    import_seed INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(photo_id, sha256, review_mode)
);
CREATE TABLE IF NOT EXISTS review_event_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'annotator',
    verdict TEXT,
    box_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_event_task
    ON review_event_v1(task_id);
CREATE TRIGGER review_task_v1_no_delete
    BEFORE DELETE ON review_task_v1
BEGIN
    SELECT RAISE(ABORT, 'review_task_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER review_task_v1_no_update
    BEFORE UPDATE ON review_task_v1
BEGIN
    SELECT RAISE(ABORT, 'review_task_v1 不可变：禁止 UPDATE');
END;
CREATE TRIGGER review_event_v1_no_delete
    BEFORE DELETE ON review_event_v1
BEGIN
    SELECT RAISE(ABORT, 'review_event_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER review_event_v1_no_update
    BEFORE UPDATE ON review_event_v1
BEGIN
    SELECT RAISE(ABORT, 'review_event_v1 不可变：禁止 UPDATE');
END;
"""

_M015 = """
CREATE TABLE IF NOT EXISTS model_residency (
    model_id TEXT PRIMARY KEY,
    residency TEXT NOT NULL CHECK (residency IN ('hot','warm','cold')),
    state TEXT NOT NULL DEFAULT 'cold'
        CHECK (state IN ('cold','loading','hot','unloading','failed')),
    max_concurrency INTEGER NOT NULL DEFAULT 1,
    idle_ttl_s INTEGER NOT NULL DEFAULT 300,
    last_used_at TEXT,
    registered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_lease (
    lease_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL REFERENCES model_residency(model_id),
    run_id TEXT NOT NULL,
    attempt_id TEXT,
    deadline TEXT,
    created_at TEXT NOT NULL,
    released_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_model_lease_model ON model_lease(model_id);
"""

_M016 = """
-- 队列 SLA 与计费账本（追加式：只增列/表/索引，保留 usage_event，不 rename 历史表名）。
-- job 表重建以扩展 status CHECK（新增 expired）并增加 attempt_timeout_at/queue_deadline_at。
-- attempt_timeout_at = 单次尝试超时（超时仅影响当次 attempt，重试/降级）；
-- queue_deadline_at = 队列业务 SLA（12h/48h），到期必须 expired/转人工并写审计。
PRAGMA foreign_keys=OFF;
CREATE TABLE IF NOT EXISTS job_m016 (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed','cancelled','expired')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    lease_until TEXT,
    worker_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    attempt_timeout_at TEXT,
    queue_deadline_at TEXT
);
INSERT INTO job_m016 (job_id, kind, status, payload_json, result_json, error,
        created_at, updated_at, lease_until, worker_id, attempt_count, max_attempts)
    SELECT job_id, kind, status, payload_json, result_json, error,
        created_at, updated_at, lease_until, worker_id,
        COALESCE(attempt_count, 0), COALESCE(max_attempts, 3)
    FROM job;
DROP TABLE job;
ALTER TABLE job_m016 RENAME TO job;
PRAGMA foreign_keys=ON;
CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);
CREATE INDEX IF NOT EXISTS idx_job_queue_deadline ON job(queue_deadline_at);

CREATE TABLE IF NOT EXISTS cascade_usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES graph_run(run_id),
    billing_key TEXT NOT NULL,
    capability TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    model_version TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL,
    photos INTEGER NOT NULL DEFAULT 0,
    regions INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    compute_ms REAL NOT NULL DEFAULT 0,
    cold_start INTEGER NOT NULL DEFAULT 0,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    rate_card_version TEXT NOT NULL,
    resource_cost REAL NOT NULL DEFAULT 0,
    billed_cost REAL NOT NULL DEFAULT 0,
    detail_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, billing_key)
);
CREATE INDEX IF NOT EXISTS idx_cascade_usage_run ON cascade_usage(run_id);
"""

_M017 = """
-- 新包装工作流（VLM-015）：受审包装演进台账。
-- 决定行一经终结（same_sku_new_package/new_sku/unknown/rejected）即不可变；
-- 历史修正只追加 package_supersede 关系，不改写旧行；禁止 DELETE。
CREATE TABLE IF NOT EXISTS package_decision (
    decision_id TEXT PRIMARY KEY,
    sku_id TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL,
    package_version_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate','reviewing','same_sku_new_package',
                          'new_sku','unknown','rejected')),
    source TEXT NOT NULL CHECK (source IN ('qwen','human','customer_policy')),
    run_id TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    name_choice TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_package_decision_sku ON package_decision(sku_id);
CREATE TABLE IF NOT EXISTS package_supersede (
    supersede_id INTEGER PRIMARY KEY AUTOINCREMENT,
    older_decision_id TEXT NOT NULL REFERENCES package_decision(decision_id),
    newer_decision_id TEXT NOT NULL REFERENCES package_decision(decision_id),
    reason TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (older_decision_id, newer_decision_id)
);
CREATE TRIGGER package_decision_no_delete
    BEFORE DELETE ON package_decision
BEGIN
    SELECT RAISE(ABORT, 'package_decision 不可变：禁止 DELETE');
END;
CREATE TRIGGER package_decision_no_update_final
    BEFORE UPDATE ON package_decision
    WHEN OLD.status IN ('same_sku_new_package','new_sku','unknown','rejected')
BEGIN
    SELECT RAISE(ABORT, '已终结包装决定不可变：禁止 UPDATE');
END;
"""

_M018 = """
CREATE TABLE IF NOT EXISTS gold_region_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    region_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    box_json TEXT NOT NULL,
    sku_id TEXT NOT NULL DEFAULT '',
    sku_name TEXT NOT NULL DEFAULT '',
    package_version_id TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT 'submitted',
    actor TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'annotator',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    group_store TEXT NOT NULL DEFAULT '',
    group_session TEXT NOT NULL DEFAULT '',
    near_dup_group TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(task_id, region_id, actor)
);
CREATE INDEX IF NOT EXISTS idx_gold_region_task ON gold_region_v1(task_id);
CREATE TRIGGER gold_region_v1_no_delete
    BEFORE DELETE ON gold_region_v1
BEGIN
    SELECT RAISE(ABORT, 'gold_region_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER gold_region_v1_no_update
    BEFORE UPDATE ON gold_region_v1
BEGIN
    SELECT RAISE(ABORT, 'gold_region_v1 不可变：禁止 UPDATE');
END;
"""


# PLC3-002：审核队列版本账本 + 追加式失效记录。
# 两表均不可变（触发器禁 DELETE/UPDATE）；状态由 join 推导，不改写历史行。
_M019 = """
CREATE TABLE IF NOT EXISTS review_queue_ledger_v1 (
    queue_version TEXT PRIMARY KEY,
    protocol TEXT NOT NULL DEFAULT '',
    n_tasks INTEGER NOT NULL DEFAULT 0,
    source_path TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL
);
CREATE TRIGGER review_queue_ledger_v1_no_delete
    BEFORE DELETE ON review_queue_ledger_v1
BEGIN
    SELECT RAISE(ABORT, 'review_queue_ledger_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER review_queue_ledger_v1_no_update
    BEFORE UPDATE ON review_queue_ledger_v1
BEGIN
    SELECT RAISE(ABORT, 'review_queue_ledger_v1 不可变：禁止 UPDATE');
END;
CREATE TABLE IF NOT EXISTS review_queue_invalidation_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_version TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    root_cause TEXT NOT NULL DEFAULT '',
    impact_summary TEXT NOT NULL DEFAULT '',
    git_commit TEXT NOT NULL DEFAULT '',
    evidence_path TEXT NOT NULL DEFAULT '',
    superseded_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TRIGGER review_queue_invalidation_v1_no_delete
    BEFORE DELETE ON review_queue_invalidation_v1
BEGIN
    SELECT RAISE(ABORT, 'review_queue_invalidation_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER review_queue_invalidation_v1_no_update
    BEFORE UPDATE ON review_queue_invalidation_v1
BEGIN
    SELECT RAISE(ABORT, 'review_queue_invalidation_v1 不可变：禁止 UPDATE');
END;
"""

_M020 = """
CREATE TABLE IF NOT EXISTS training_run_supersession_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    superseded_by TEXT NOT NULL DEFAULT '',
    git_commit TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TRIGGER training_run_supersession_v1_no_delete
    BEFORE DELETE ON training_run_supersession_v1
BEGIN
    SELECT RAISE(ABORT, 'training_run_supersession_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER training_run_supersession_v1_no_update
    BEFORE UPDATE ON training_run_supersession_v1
BEGIN
    SELECT RAISE(ABORT, 'training_run_supersession_v1 不可变：禁止 UPDATE');
END;
"""

_M021 = """
CREATE TABLE IF NOT EXISTS training_plan_v2 (
    plan_id TEXT PRIMARY KEY,
    lane TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    lineage_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_run_v2 (
    run_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    worker TEXT NOT NULL DEFAULT '',
    pid INTEGER,
    attempt INTEGER NOT NULL DEFAULT 0,
    job_id TEXT NOT NULL DEFAULT '',
    lease_json TEXT NOT NULL DEFAULT '[]',
    heartbeat_at TEXT,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS training_event_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, seq)
);
CREATE TRIGGER training_event_v1_no_delete
    BEFORE DELETE ON training_event_v1
BEGIN
    SELECT RAISE(ABORT, 'training_event_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER training_event_v1_no_update
    BEFORE UPDATE ON training_event_v1
BEGIN
    SELECT RAISE(ABORT, 'training_event_v1 不可变：禁止 UPDATE');
END;
CREATE TABLE IF NOT EXISTS training_artifact_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    lineage_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TRIGGER training_artifact_v1_no_delete
    BEFORE DELETE ON training_artifact_v1
BEGIN
    SELECT RAISE(ABORT, 'training_artifact_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER training_artifact_v1_no_update
    BEFORE UPDATE ON training_artifact_v1
BEGIN
    SELECT RAISE(ABORT, 'training_artifact_v1 不可变：禁止 UPDATE');
END;
CREATE TABLE IF NOT EXISTS resource_lease_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    resource TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'exclusive',
    acquired_at TEXT NOT NULL,
    released_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_resource_lease_active
    ON resource_lease_v1(resource, released_at);
"""

_M022 = """
CREATE TABLE IF NOT EXISTS legacy_model_registry_v1 (
    model_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    status TEXT NOT NULL,
    weights_json TEXT NOT NULL DEFAULT '[]',
    git_commit TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL
);
CREATE TRIGGER legacy_model_registry_v1_no_delete
    BEFORE DELETE ON legacy_model_registry_v1
BEGIN
    SELECT RAISE(ABORT, 'legacy_model_registry_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER legacy_model_registry_v1_no_update
    BEFORE UPDATE ON legacy_model_registry_v1
BEGIN
    SELECT RAISE(ABORT, 'legacy_model_registry_v1 不可变：禁止 UPDATE');
END;
"""

_M023 = """
CREATE TABLE IF NOT EXISTS training_cycle_v1 (
    cycle_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    version INTEGER NOT NULL DEFAULT 1,
    waiting_for TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_cycle_event_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(cycle_id, seq)
);
CREATE TRIGGER training_cycle_event_v1_no_delete
    BEFORE DELETE ON training_cycle_event_v1
BEGIN
    SELECT RAISE(ABORT, 'training_cycle_event_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER training_cycle_event_v1_no_update
    BEFORE UPDATE ON training_cycle_event_v1
BEGIN
    SELECT RAISE(ABORT, 'training_cycle_event_v1 不可变：禁止 UPDATE');
END;
CREATE TABLE IF NOT EXISTS training_cycle_node_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    node TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nextgen_plan_v1 (
    plan_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    hypothesis TEXT NOT NULL DEFAULT '',
    base_revision TEXT NOT NULL DEFAULT '',
    dataset_hash TEXT NOT NULL DEFAULT '',
    budget_json TEXT NOT NULL DEFAULT '{}',
    stop_lines_json TEXT NOT NULL DEFAULT '[]',
    eval_set_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    approved_by TEXT NOT NULL DEFAULT '',
    approved_count INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nextgen_plan_approval_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    approval_key TEXT NOT NULL UNIQUE,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER nextgen_plan_approval_v1_no_delete
    BEFORE DELETE ON nextgen_plan_approval_v1
BEGIN
    SELECT RAISE(ABORT, 'nextgen_plan_approval_v1 不可变：禁止 DELETE');
END;
CREATE TABLE IF NOT EXISTS nextgen_run_attempt_v1 (
    run_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    command_hash TEXT NOT NULL DEFAULT '',
    env_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'REGISTERED',
    pid INTEGER,
    lease_json TEXT NOT NULL DEFAULT '[]',
    heartbeat_at TEXT,
    output_dir TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_artifact_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    lineage_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TRIGGER training_artifact_v2_no_delete
    BEFORE DELETE ON training_artifact_v2
BEGIN
    SELECT RAISE(ABORT, 'training_artifact_v2 不可变：禁止 DELETE');
END;
CREATE TRIGGER training_artifact_v2_no_update
    BEFORE UPDATE ON training_artifact_v2
BEGIN
    SELECT RAISE(ABORT, 'training_artifact_v2 不可变：禁止 UPDATE');
END;
CREATE TABLE IF NOT EXISTS resource_benchmark_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario TEXT NOT NULL,
    lane_combo TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    verdict TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recognition_profile_v1 (
    profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    components_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'disabled',
    blockers_json TEXT NOT NULL DEFAULT '[]',
    policy_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_M024 = """
CREATE TABLE IF NOT EXISTS flow_supersession_v1 (
    flow_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    superseded_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TRIGGER flow_supersession_v1_no_delete
    BEFORE DELETE ON flow_supersession_v1
BEGIN
    SELECT RAISE(ABORT, 'flow_supersession_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER flow_supersession_v1_no_update
    BEFORE UPDATE ON flow_supersession_v1
BEGIN
    SELECT RAISE(ABORT, 'flow_supersession_v1 不可变：禁止 UPDATE');
END;
"""

_M025 = """
CREATE TABLE IF NOT EXISTS agent_manifest_v1 (
    agent_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blackboard_event_v1 (
    id TEXT PRIMARY KEY,
    by TEXT NOT NULL,
    by_kind TEXT NOT NULL DEFAULT 'agent',
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    supersedes TEXT,
    created_at TEXT NOT NULL
);
CREATE TRIGGER blackboard_event_v1_no_delete
    BEFORE DELETE ON blackboard_event_v1
BEGIN
    SELECT RAISE(ABORT, 'blackboard_event_v1 不可变：禁止 DELETE');
END;
CREATE TRIGGER blackboard_event_v1_no_update
    BEFORE UPDATE ON blackboard_event_v1
BEGIN
    SELECT RAISE(ABORT, 'blackboard_event_v1 不可变：禁止 UPDATE');
END;
CREATE TABLE IF NOT EXISTS memory_entry_v1 (
    id TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    text TEXT NOT NULL,
    scope TEXT NOT NULL,
    acl_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    retention TEXT NOT NULL DEFAULT 'project_lifetime',
    supersedes TEXT,
    version INTEGER NOT NULL DEFAULT 1
);
"""

_M026 = """
CREATE TABLE IF NOT EXISTS model_artifact_registry_v1 (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    dataset_manifest_sha TEXT NOT NULL DEFAULT '',
    source_commit TEXT NOT NULL DEFAULT '',
    dirty_diff_hash TEXT NOT NULL DEFAULT '',
    model_base TEXT NOT NULL DEFAULT '',
    label_source TEXT NOT NULL DEFAULT '',
    evidence_level TEXT NOT NULL DEFAULT '',
    candidate_status TEXT NOT NULL DEFAULT '',
    blocker TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    reconciled_by TEXT NOT NULL DEFAULT '',
    reconciliation_run_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dataset_snapshot_registry_v1 (
    snapshot_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    manifest_sha TEXT NOT NULL,
    label_source TEXT NOT NULL DEFAULT '',
    evidence_level TEXT NOT NULL DEFAULT '',
    leakage_policy TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    reconciled_by TEXT NOT NULL DEFAULT '',
    reconciliation_run_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS evaluation_registry_v1 (
    eval_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    report_path TEXT NOT NULL,
    report_sha TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL DEFAULT '{}',
    evidence_level TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    reconciled_by TEXT NOT NULL DEFAULT '',
    reconciliation_run_id TEXT NOT NULL DEFAULT ''
);
"""

_M027 = """
CREATE TABLE IF NOT EXISTS agent_session_v1 (
    session_id TEXT PRIMARY KEY,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_session_msg_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_command_v1 (
    command_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending_approval',
    created_by TEXT NOT NULL DEFAULT '',
    decided_by TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
"""

_M028 = """
CREATE TABLE IF NOT EXISTS training_cycle_node_state_v2 (
    cycle_id TEXT NOT NULL,
    logical_node TEXT NOT NULL,
    current_status TEXT NOT NULL,
    latest_event_id TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(cycle_id, logical_node)
);
CREATE TABLE IF NOT EXISTS task_state_projection_v1 (
    project TEXT NOT NULL DEFAULT 'llm-image',
    cycle_id TEXT NOT NULL DEFAULT '',
    logical_task_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    current_status TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    blocker TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    acceptance TEXT NOT NULL DEFAULT 'pending',
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(project, cycle_id, logical_task_key)
);
"""

_M029 = """
CREATE TABLE IF NOT EXISTS recognition_profile_def_v1 (
    profile_id TEXT PRIMARY KEY,
    components_json TEXT NOT NULL DEFAULT '[]',
    scopes_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    legacy INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

# ABOS T7：识别任务冻结 Profile 契约（profile/tier/source/project/trace）
_M030 = """
ALTER TABLE recognition_task
    ADD COLUMN recognition_profile_id TEXT NOT NULL DEFAULT '';
ALTER TABLE recognition_task
    ADD COLUMN service_tier TEXT NOT NULL DEFAULT '';
ALTER TABLE recognition_task
    ADD COLUMN source TEXT NOT NULL DEFAULT '';
ALTER TABLE recognition_task
    ADD COLUMN project_id TEXT NOT NULL DEFAULT '';
ALTER TABLE recognition_task
    ADD COLUMN trace_id TEXT NOT NULL DEFAULT '';
"""

# ABOSV2-P0-001：统一 current task projection 的 supersession 账本。
# 被取代的工作族（如旧审核队列）只移出当前待办，历史行永不删除。
_M031 = """
CREATE TABLE IF NOT EXISTS work_item_supersession_v1 (
    supersession_id INTEGER PRIMARY KEY AUTOINCREMENT,
    family TEXT NOT NULL,
    match_json TEXT NOT NULL,
    superseded_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(family, match_json, superseded_by)
);
CREATE TRIGGER IF NOT EXISTS work_item_supersession_v1_no_delete
    BEFORE DELETE ON work_item_supersession_v1
    BEGIN
        SELECT RAISE(ABORT, 'work_item_supersession_v1 不可变：禁止 DELETE');
    END;
CREATE TRIGGER IF NOT EXISTS work_item_supersession_v1_no_update
    BEFORE UPDATE ON work_item_supersession_v1
    BEGIN
        SELECT RAISE(ABORT, 'work_item_supersession_v1 不可变：禁止 UPDATE');
    END;
"""

# ABOSV2-P0-002：快速目标服务端 goal draft（刷新可恢复；确认后形成
# 计划/命令留痕，不只存 URL/前端状态）。
_M032 = """
CREATE TABLE IF NOT EXISTS goal_draft_v1 (
    goal_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    result_json TEXT NOT NULL DEFAULT '{}'
);
"""

# ABOSV2 Phase B：统一 Work/Event/Usage 控制平面（01 文档契约）。
# BusinessRunV1/WorkItemV2/EventEnvelopeV1/UsageEventV2/EvidenceBundleV1
# + Transactional Outbox；事件/用量/证据 append-only。
_M033 = """
ALTER TABLE recognition_task
    ADD COLUMN run_id TEXT NOT NULL DEFAULT '';
ALTER TABLE recognition_task
    ADD COLUMN work_id TEXT NOT NULL DEFAULT '';
ALTER TABLE recognition_task
    ADD COLUMN correlation_id TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS business_run_v1 (
    run_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL DEFAULT '',
    tenant_id TEXT NOT NULL DEFAULT 'local',
    customer_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    workflow_definition_id TEXT NOT NULL DEFAULT '',
    workflow_version TEXT NOT NULL DEFAULT '',
    trigger_type TEXT NOT NULL DEFAULT 'command',
    parent_run_id TEXT,
    correlation_id TEXT NOT NULL DEFAULT '',
    causation_id TEXT,
    subject_type TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL DEFAULT '',
    initiator_type TEXT NOT NULL DEFAULT 'human',
    initiator_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    current_node TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    ended_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    evidence_bundle_id TEXT,
    usage_account_id TEXT NOT NULL DEFAULT '',
    policy_snapshot_id TEXT,
    error TEXT NOT NULL DEFAULT '',
    command_kind TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT UNIQUE,
    goal_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_item_v2 (
    work_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'local',
    customer_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',
    owner_type TEXT NOT NULL DEFAULT 'human',
    owner_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    business_summary TEXT NOT NULL DEFAULT '',
    next_actions_json TEXT NOT NULL DEFAULT '[]',
    due_at TEXT,
    sla_policy TEXT NOT NULL DEFAULT '',
    subject_type TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL DEFAULT '',
    parent_work_id TEXT,
    dependencies_json TEXT NOT NULL DEFAULT '[]',
    blockers_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    usage_refs_json TEXT NOT NULL DEFAULT '[]',
    result_ref TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_envelope_v1 (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1,
    occurred_at TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'local',
    customer_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    actor_type TEXT NOT NULL DEFAULT 'human',
    actor_id TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL DEFAULT '',
    causation_id TEXT,
    run_id TEXT NOT NULL DEFAULT '',
    work_id TEXT NOT NULL DEFAULT '',
    subject_type TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL DEFAULT '',
    payload_schema TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    idempotency_key TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS outbox_v1 (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    dispatched_at TEXT
);
CREATE TABLE IF NOT EXISTS usage_event_v2 (
    usage_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'local',
    customer_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    contract_id TEXT NOT NULL DEFAULT '',
    rate_card_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    work_id TEXT NOT NULL DEFAULT '',
    node TEXT NOT NULL DEFAULT '',
    capability TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    profile_id TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL,
    quantity REAL NOT NULL,
    resource_cost REAL NOT NULL DEFAULT 0,
    internal_cost REAL NOT NULL DEFAULT 0,
    customer_price REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CNY',
    source_evidence TEXT NOT NULL DEFAULT '',
    meter_version TEXT NOT NULL DEFAULT 'v1',
    price_version TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_bundle_v1 (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL DEFAULT '',
    work_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    source_uri TEXT NOT NULL DEFAULT '',
    cas_hash TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    producer TEXT NOT NULL DEFAULT '',
    input_hash TEXT NOT NULL DEFAULT '',
    config_version TEXT NOT NULL DEFAULT '',
    permission_label TEXT NOT NULL DEFAULT 'internal',
    retention TEXT NOT NULL DEFAULT '',
    parent_evidence_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS event_envelope_v1_no_delete
    BEFORE DELETE ON event_envelope_v1
    BEGIN
        SELECT RAISE(ABORT, 'event_envelope_v1 不可变：禁止 DELETE');
    END;
CREATE TRIGGER IF NOT EXISTS event_envelope_v1_no_update
    BEFORE UPDATE ON event_envelope_v1
    BEGIN
        SELECT RAISE(ABORT, 'event_envelope_v1 不可变：禁止 UPDATE');
    END;
CREATE TRIGGER IF NOT EXISTS usage_event_v2_no_delete
    BEFORE DELETE ON usage_event_v2
    BEGIN
        SELECT RAISE(ABORT, 'usage_event_v2 不可变：禁止 DELETE');
    END;
CREATE TRIGGER IF NOT EXISTS usage_event_v2_no_update
    BEFORE UPDATE ON usage_event_v2
    BEGIN
        SELECT RAISE(ABORT, 'usage_event_v2 不可变：禁止 UPDATE');
    END;
CREATE TRIGGER IF NOT EXISTS evidence_bundle_v1_no_delete
    BEFORE DELETE ON evidence_bundle_v1
    BEGIN
        SELECT RAISE(ABORT, 'evidence_bundle_v1 不可变：禁止 DELETE');
    END;
CREATE TRIGGER IF NOT EXISTS evidence_bundle_v1_no_update
    BEFORE UPDATE ON evidence_bundle_v1
    BEGIN
        SELECT RAISE(ABORT, 'evidence_bundle_v1 不可变：禁止 UPDATE');
    END;
"""

# ABOSV2 Phase C：Workflow Studio MVP（02 文档契约）。
# 定义发布后不可原地修改（新版本）；节点执行 checkpoint；死信诚实留痕。
_M034 = """
CREATE TABLE IF NOT EXISTS workflow_definition_v1 (
    definition_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    tenant_id TEXT NOT NULL DEFAULT 'local',
    owner TEXT NOT NULL DEFAULT '',
    spec_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL DEFAULT '',
    lint_report_json TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    PRIMARY KEY (definition_id, version)
);
CREATE TABLE IF NOT EXISTS workflow_node_execution_v1 (
    exec_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    ended_at TEXT,
    UNIQUE(run_id, node_id)
);
CREATE TABLE IF NOT EXISTS workflow_dead_letter_v1 (
    dead_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS workflow_dead_letter_v1_no_delete
    BEFORE DELETE ON workflow_dead_letter_v1
    BEGIN
        SELECT RAISE(ABORT, 'workflow_dead_letter_v1 不可变：禁止 DELETE');
    END;
CREATE TRIGGER IF NOT EXISTS workflow_dead_letter_v1_no_update
    BEFORE UPDATE ON workflow_dead_letter_v1
    BEGIN
        SELECT RAISE(ABORT, 'workflow_dead_letter_v1 不可变：禁止 UPDATE');
    END;
"""

# ABOSV2 Phase D：IAM（账号/角色/permission bundle/成员/审计/批准矩阵）
# + 主数据（客户/项目/SKU 库，含别名与新旧包装）。
_M035 = """
CREATE TABLE IF NOT EXISTS iam_principal_v1 (
    principal_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    tenant_id TEXT NOT NULL DEFAULT 'local',
    status TEXT NOT NULL DEFAULT 'active',
    password_hash TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS iam_role_v1 (
    role_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    builtin INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS iam_permission_bundle_v1 (
    bundle_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT 'v1',
    UNIQUE(scope, version)
);
CREATE TABLE IF NOT EXISTS iam_role_permission_v1 (
    role_id TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    PRIMARY KEY (role_id, bundle_id)
);
CREATE TABLE IF NOT EXISTS iam_membership_v1 (
    principal_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'local',
    customer_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    granted_by TEXT NOT NULL DEFAULT '',
    granted_at TEXT NOT NULL,
    PRIMARY KEY (principal_id, role_id, customer_id, project_id)
);
CREATE TABLE IF NOT EXISTS iam_audit_event_v1 (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    tenant_id TEXT NOT NULL DEFAULT 'local',
    customer_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS iam_approval_matrix_v1 (
    matrix_id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    approver_role TEXT NOT NULL,
    min_approvers INTEGER NOT NULL DEFAULT 1,
    UNIQUE(action, approver_role)
);
CREATE TABLE IF NOT EXISTS md_customer_v1 (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'local',
    is_test_fixture INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    retention_policy TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS md_project_v1 (
    project_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT,
    ended_at TEXT,
    sku_scope_json TEXT NOT NULL DEFAULT '[]',
    budget_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS md_sku_v1 (
    sku_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    volume TEXT NOT NULL DEFAULT '',
    barcode TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    valid_from TEXT,
    valid_to TEXT,
    package_version TEXT NOT NULL DEFAULT 'v1',
    superseded_by TEXT,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS md_sku_alias_v1 (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'alias',
    customer_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(alias, customer_id, kind)
);
CREATE TRIGGER IF NOT EXISTS iam_audit_event_v1_no_delete
    BEFORE DELETE ON iam_audit_event_v1
    BEGIN
        SELECT RAISE(ABORT, 'iam_audit_event_v1 不可变：禁止 DELETE');
    END;
CREATE TRIGGER IF NOT EXISTS iam_audit_event_v1_no_update
    BEFORE UPDATE ON iam_audit_event_v1
    BEGIN
        SELECT RAISE(ABORT, 'iam_audit_event_v1 不可变：禁止 UPDATE');
    END;
"""

# ABOSV2 Phase E：问卷域（定义版本/分配/响应/修正事件/拍照媒体）。
# 发布后不可原地改；后台修正只追加 correction 事件并重算评分版本。
_M036 = """
CREATE TABLE IF NOT EXISTS survey_definition_v1 (
    survey_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    spec_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL DEFAULT '',
    lint_report_json TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    PRIMARY KEY (survey_id, version)
);
CREATE TABLE IF NOT EXISTS survey_assignment_v1 (
    assignment_id TEXT PRIMARY KEY,
    survey_id TEXT NOT NULL,
    survey_version INTEGER NOT NULL,
    customer_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    assignee TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'assigned',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS survey_response_v1 (
    response_id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL,
    survey_id TEXT NOT NULL,
    survey_version INTEGER NOT NULL,
    customer_id TEXT NOT NULL DEFAULT '',
    respondent TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    answers_json TEXT NOT NULL DEFAULT '{}',
    scores_json TEXT NOT NULL DEFAULT '{}',
    score_version INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS survey_answer_correction_v1 (
    correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    old_value_json TEXT NOT NULL,
    new_value_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    approver TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS survey_media_v1 (
    media_id TEXT PRIMARY KEY,
    response_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'photo',
    evidence_ref TEXT NOT NULL DEFAULT '',
    location_json TEXT NOT NULL DEFAULT '{}',
    taken_at TEXT,
    device TEXT NOT NULL DEFAULT '',
    quality_json TEXT NOT NULL DEFAULT '{}',
    recognition_run_id TEXT NOT NULL DEFAULT '',
    suggestion_json TEXT NOT NULL DEFAULT '{}',
    suggestion_status TEXT NOT NULL DEFAULT 'none',
    final_value_json TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS survey_answer_correction_v1_no_delete
    BEFORE DELETE ON survey_answer_correction_v1
    BEGIN
        SELECT RAISE(ABORT,
            'survey_answer_correction_v1 不可变：禁止 DELETE');
    END;
CREATE TRIGGER IF NOT EXISTS survey_answer_correction_v1_no_update
    BEFORE UPDATE ON survey_answer_correction_v1
    BEGIN
        SELECT RAISE(ABORT,
            'survey_answer_correction_v1 不可变：禁止 UPDATE');
    END;
"""

# ABOSV2 Phase F：BI 语义层（指标/维度/报表规格/异常/追问）。
# Agent 只能映射到已注册指标，不得任意 SQL；报表版本化。
_M037 = """
CREATE TABLE IF NOT EXISTS bi_metric_v1 (
    metric_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    definition_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'customer',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bi_report_spec_v1 (
    spec_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    customer_id TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '[]',
    dimensions_json TEXT NOT NULL DEFAULT '[]',
    filters_json TEXT NOT NULL DEFAULT '{}',
    nl_query TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    PRIMARY KEY (spec_id, version)
);
CREATE TABLE IF NOT EXISTS bi_anomaly_v1 (
    anomaly_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL,
    customer_id TEXT NOT NULL DEFAULT '',
    rule_json TEXT NOT NULL,
    observed REAL NOT NULL,
    threshold REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    follow_up_work_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS bi_followup_answer_v1 (
    answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_id TEXT NOT NULL,
    answer TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# ABOSV2 Phase F：位置与外勤（地址/地理编码/任务/路线/围栏/到店证据/差旅费）。
_M038 = """
CREATE TABLE IF NOT EXISTS geo_address_v1 (
    address_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL DEFAULT '',
    raw TEXT NOT NULL,
    candidates_json TEXT NOT NULL DEFAULT '[]',
    chosen_json TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    verified_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geo_employee_v1 (
    employee_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    skills_json TEXT NOT NULL DEFAULT '[]',
    vehicle TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_task_v1 (
    task_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    address_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'visit',
    survey_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    route_plan_id TEXT NOT NULL DEFAULT '',
    assignee TEXT NOT NULL DEFAULT '',
    require_storefront INTEGER NOT NULL DEFAULT 1,
    selfie_required INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS route_plan_v1 (
    plan_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    task_ids_json TEXT NOT NULL DEFAULT '[]',
    constraints_json TEXT NOT NULL DEFAULT '{}',
    stops_json TEXT NOT NULL DEFAULT '[]',
    cost_json TEXT NOT NULL DEFAULT '{}',
    unassigned_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geofence_v1 (
    fence_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    radius_m REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geofence_event_v1 (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fence_id TEXT NOT NULL,
    task_id TEXT NOT NULL DEFAULT '',
    employee_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    accuracy REAL NOT NULL DEFAULT 0,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_visit_evidence_v1 (
    evidence_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    media_ref TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL,
    location_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS travel_cost_v1 (
    cost_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    route_plan_id TEXT NOT NULL DEFAULT '',
    km REAL NOT NULL,
    unit_price REAL NOT NULL,
    amount REAL NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""

# ABOSV2 Phase F：财务与计费（contract/rate card/invoice/adjustment）。
# 账单只能从 immutable usage_event_v2 生成并下钻到 run/node/证据；
# 调整用 reversal/adjustment，不删除 Usage；已开票金额不随新价格变动。
_M039 = """
CREATE TABLE IF NOT EXISTS fin_rate_card_v1 (
    rate_card_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    lines_json TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    PRIMARY KEY (rate_card_id, version)
);
CREATE TABLE IF NOT EXISTS fin_contract_v1 (
    contract_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'usage',
    rate_card_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fin_invoice_v1 (
    invoice_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    contract_id TEXT NOT NULL DEFAULT '',
    period TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    total REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CNY',
    rate_card_id TEXT NOT NULL DEFAULT '',
    rate_card_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    issued_at TEXT
);
CREATE TABLE IF NOT EXISTS fin_invoice_line_v1 (
    line_id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    amount REAL NOT NULL,
    usage_ids_json TEXT NOT NULL DEFAULT '[]',
    drilldown_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS fin_adjustment_v1 (
    adjustment_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS fin_adjustment_v1_no_delete
    BEFORE DELETE ON fin_adjustment_v1
    BEGIN
        SELECT RAISE(ABORT, 'fin_adjustment_v1 不可变：禁止 DELETE');
    END;
CREATE TRIGGER IF NOT EXISTS fin_adjustment_v1_no_update
    BEFORE UPDATE ON fin_adjustment_v1
    BEGIN
        SELECT RAISE(ABORT, 'fin_adjustment_v1 不可变：禁止 UPDATE');
    END;
"""

# 登录凭据锁定：一旦写入 auth_locked_credential_v1，任何 UPDATE/DELETE
# 都被触发器拒绝；环境变量也不能覆盖（auth 层忽略）。
_M040 = """
CREATE TRIGGER IF NOT EXISTS platform_flag_auth_lock_no_update
    BEFORE UPDATE ON platform_flag
    WHEN old.flag = 'auth_locked_credential_v1'
    BEGIN
        SELECT RAISE(ABORT, '登录凭据已锁定，不可变更（UPDATE 拒绝）');
    END;
CREATE TRIGGER IF NOT EXISTS platform_flag_auth_lock_no_delete
    BEFORE DELETE ON platform_flag
    WHEN old.flag = 'auth_locked_credential_v1'
    BEGIN
        SELECT RAISE(ABORT, '登录凭据已锁定，不可变更（DELETE 拒绝）');
    END;
"""

MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("001_platform_init", _M001),
    ("002_labeling_inbox", _M002),
    ("003_training_gov", _M003),
    ("004_recoverable_worker", _M004),
    ("005_snapshot_trainable", _M005),
    ("006_auth_sessions", _M006),
    ("007_training_run_job_id", _M007),
    ("008_recognition_task", _M008),
    ("009_recognition_task_idem", _M009),
    ("010_source_asset_inventory_v1", _M010),
    ("011_quality_decision_v1", _M011),
    ("012_quality_gold_v1", _M012),
    ("013_sam_lineage_v1", _M013),
    ("014_review_task_v1", _M014),
    ("015_model_residency", _M015),
    ("016_job_sla_and_cascade_usage", _M016),
    ("017_package_decision_v1", _M017),
    ("018_gold_region_v1", _M018),
    ("019_review_queue_ledger_v1", _M019),
    ("020_training_run_supersession_v1", _M020),
    ("021_training_control_v2", _M021),
    ("022_legacy_model_registry_v1", _M022),
    ("023_nextgen_training_cycle_v1", _M023),
    ("024_flow_supersession_v1", _M024),
    ("025_agent_blackboard_memory_v1", _M025),
    ("026_reconciliation_registry_v1", _M026),
    ("027_agent_runtime_v1", _M027),
    ("028_state_projections_v2", _M028),
    ("029_profile_def_v1", _M029),
    ("030_recognition_task_profile_contract", _M030),
    ("031_work_item_supersession_v1", _M031),
    ("032_goal_draft_v1", _M032),
    ("033_work_event_usage_control_plane", _M033),
    ("034_workflow_studio_v1", _M034),
    ("035_iam_master_data_v1", _M035),
    ("036_survey_v1", _M036),
    ("037_bi_semantic_v1", _M037),
    ("038_geo_field_v1", _M038),
    ("039_finance_v1", _M039),
    ("040_auth_credential_lock", _M040),
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class PlatformStore:
    """SQLite 开发适配器。生产（M6）将一次性迁移到 PostgreSQL，不做双写。"""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # 首连接设置 WAL（持久化于库文件）
        self._conn.execute("PRAGMA journal_mode=WAL")
        self.apply_migrations()

    def _make_conn(self) -> sqlite3.Connection:
        # autocommit 模式：避免隐式长读事务在 WAL 下阻塞其他连接的写者；
        # 写路径每条语句自提交（本库写操作均为单语句）。
        c = sqlite3.connect(str(self._path), timeout=15, autocommit=True)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA journal_mode=WAL")
        return c

    @property
    def _conn(self) -> sqlite3.Connection:
        """每线程独立连接（WAL 并发），避免跨线程共享 sqlite 对象。"""
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._make_conn()
            self._local.conn = c
        return c

    # ---------- migrations ----------

    def apply_migrations(self) -> None:
        conn = self._conn
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,"
            "sha256 TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {
            r["name"]: r["sha256"]
            for r in conn.execute("SELECT name, sha256 FROM schema_migrations").fetchall()
        }
        for name, sql in MIGRATIONS:
            digest = _sha(sql)
            if name in applied:
                if applied[name] != digest:
                    raise StoreError(
                        f"migration '{name}' 已被篡改（记录 sha256 与当前内容不一致），拒绝启动"
                    )
                continue
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations(name, sha256, applied_at) VALUES (?,?,?)",
                (name, digest, _utcnow()),
            )
        conn.commit()

    # ---------- graph_run ----------

    def create_run(
        self,
        *,
        run_id: str,
        graph_name: str,
        graph_version: str,
        input_payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        now = _utcnow()
        try:
            self._conn.execute(
                "INSERT INTO graph_run(run_id, graph_name, graph_version, status,"
                " input_json, request_id, idempotency_key, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    graph_name,
                    graph_version,
                    "pending",
                    json.dumps(input_payload or {}, ensure_ascii=False),
                    request_id,
                    idempotency_key,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"run 已存在或 idempotency_key 冲突: {run_id}") from e
        self._conn.commit()
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM graph_run WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"run 不存在: {run_id}")
        return dict(row)

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM graph_run ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_run_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM graph_run WHERE idempotency_key=?", (key,)
        ).fetchone()
        return _row_to_dict(row)

    def set_run_status(
        self,
        run_id: str,
        status: str,
        *,
        output_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in RUN_STATUSES:
            raise StoreError(f"非法 run 状态: {status}")
        cur = self._conn.execute(
            "UPDATE graph_run SET status=?, updated_at=?, error=?"
            + (", output_json=?" if output_payload is not None else "")
            + " WHERE run_id=?",
            (
                status,
                _utcnow(),
                error,
                *(
                    [json.dumps(output_payload, ensure_ascii=False)]
                    if output_payload is not None
                    else []
                ),
                run_id,
            ),
        )
        if cur.rowcount == 0:
            raise StoreError(f"run 不存在: {run_id}")
        self._conn.commit()

    # ---------- node_execution ----------

    def start_node(self, run_id: str, *, node_name: str, seq: int, attempt: int = 1) -> None:
        try:
            self._conn.execute(
                "INSERT INTO node_execution(run_id, node_name, seq, attempt, status, started_at)"
                " VALUES (?,?,?,?,?,?)",
                (run_id, node_name, seq, attempt, "running", _utcnow()),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"node 执行记录已存在: {run_id}/{node_name}/seq{seq}/a{attempt}") from e
        self._conn.commit()

    def finish_node(
        self,
        run_id: str,
        *,
        node_name: str,
        seq: int,
        status: str,
        attempt: int = 1,
        output_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in NODE_STATUSES:
            raise StoreError(f"非法 node 状态: {status}")
        cur = self._conn.execute(
            "UPDATE node_execution SET status=?, ended_at=?, output_json=?, error=?"
            " WHERE run_id=? AND node_name=? AND seq=? AND attempt=?",
            (
                status,
                _utcnow(),
                json.dumps(output_payload, ensure_ascii=False) if output_payload is not None else None,
                error,
                run_id,
                node_name,
                seq,
                attempt,
            ),
        )
        if cur.rowcount == 0:
            raise StoreError(f"node 执行记录不存在: {run_id}/{node_name}/seq{seq}/a{attempt}")
        self._conn.commit()

    def list_nodes(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM node_execution WHERE run_id=? ORDER BY seq, attempt",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- checkpoint ----------

    def save_checkpoint(self, run_id: str, *, node_name: str, payload: dict[str, Any]) -> None:
        try:
            self._conn.execute(
                "INSERT INTO checkpoint(run_id, node_name, payload_json, created_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(run_id, node_name) DO UPDATE SET"
                " payload_json=excluded.payload_json, created_at=excluded.created_at",
                (run_id, node_name, json.dumps(payload, ensure_ascii=False), _utcnow()),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"checkpoint 写入失败: {run_id}/{node_name}") from e
        self._conn.commit()

    def load_checkpoint(self, run_id: str, node_name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload_json FROM checkpoint WHERE run_id=? AND node_name=?",
            (run_id, node_name),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    # ---------- job / attempt ----------

    def create_job(
        self,
        *,
        job_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        attempt_timeout_at: str | None = None,
        queue_deadline_at: str | None = None,
    ) -> dict[str, Any]:
        now = _utcnow()
        try:
            self._conn.execute(
                "INSERT INTO job(job_id, kind, status, payload_json, max_attempts,"
                " attempt_timeout_at, queue_deadline_at, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    job_id, kind, "queued",
                    json.dumps(payload or {}, ensure_ascii=False),
                    max_attempts, attempt_timeout_at, queue_deadline_at, now, now,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"job 已存在: {job_id}") from e
        self._conn.commit()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM job WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise StoreError(f"job 不存在: {job_id}")
        return dict(row)

    def set_job_status(
        self,
        job_id: str,
        status: str,
        *,
        result_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in JOB_STATUSES:
            raise StoreError(f"非法 job 状态: {status}")
        cur = self._conn.execute(
            "UPDATE job SET status=?, updated_at=?, error=?"
            + (", result_json=?" if result_payload is not None else "")
            + " WHERE job_id=?",
            (
                status,
                _utcnow(),
                error,
                *(
                    [json.dumps(result_payload, ensure_ascii=False)]
                    if result_payload is not None
                    else []
                ),
                job_id,
            ),
        )
        if cur.rowcount == 0:
            raise StoreError(f"job 不存在: {job_id}")
        self._conn.commit()

    def record_attempt(
        self,
        job_id: str,
        *,
        attempt_no: int,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO job_attempt(job_id, attempt_no, status, started_at, ended_at, detail_json)"
            " VALUES (?,?,?,?,?,?)",
            (job_id, attempt_no, status, _utcnow(), _utcnow(), json.dumps(detail or {}, ensure_ascii=False)),
        )
        self._conn.commit()

    def list_attempts(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM job_attempt WHERE job_id=? ORDER BY attempt_no", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        exclude_job_ids: set[str] | None = None,
    ) -> dict[str, Any] | None:
        """原子认领最老 queued job 为 running（单语句 UPDATE，崩溃可恢复）。

        lease_until 到期而 worker 未续期/完成 → 视为崩溃，可被重新排队。
        exclude_job_ids：本轮刚 requeue 的 job 不重复认领（退让语义）。
        """
        now = datetime.now(timezone.utc)
        lease = (now + timedelta(seconds=lease_seconds)).isoformat()
        excluded = sorted(exclude_job_ids or ())
        params: list[Any] = [worker_id, lease, now.isoformat()]
        excl_sql = ""
        if excluded:
            excl_sql = f" AND job_id NOT IN ({', '.join('?' * len(excluded))})"
            params.extend(excluded)
        params.extend(excluded)  # 子查询同名排除
        row = self._conn.execute(
            "UPDATE job SET status='running', worker_id=?, lease_until=?, updated_at=?"
            " WHERE job_id=(SELECT job_id FROM job WHERE status='queued'"
            f"{excl_sql} ORDER BY created_at, job_id LIMIT 1){excl_sql} RETURNING *",
            params,
        ).fetchone()
        self._conn.commit()
        return dict(row) if row is not None else None

    def increment_attempt(self, job_id: str) -> int:
        self._conn.execute(
            "UPDATE job SET attempt_count=attempt_count+1, updated_at=? WHERE job_id=?",
            (_utcnow(), job_id),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT attempt_count FROM job WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"job 不存在: {job_id}")
        return int(row["attempt_count"])

    def clear_lease(self, job_id: str) -> None:
        self._conn.execute(
            "UPDATE job SET lease_until=NULL, worker_id=NULL, updated_at=? WHERE job_id=?",
            (_utcnow(), job_id),
        )
        self._conn.commit()

    def list_jobs(
        self, *, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        if status is not None:
            rows = self._conn.execute(
                "SELECT * FROM job WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM job ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_jobs_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM job GROUP BY status"
        ).fetchall()
        out = {s: 0 for s in JOB_STATUSES}
        for r in rows:
            out[r["status"]] = int(r["n"])
        return out

    def expired_running_leases(self, *, before_ts: str) -> list[dict[str, Any]]:
        """lease 过期仍 running 的 job（worker 崩溃候选）。"""
        rows = self._conn.execute(
            "SELECT * FROM job WHERE status='running' AND lease_until IS NOT NULL"
            " AND lease_until < ?",
            (before_ts,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- share token（scope + 有效期，fail-closed） ----------

    def create_share_token(
        self,
        *,
        scope: str,
        subject_id: str | None = None,
        ttl_seconds: int,
        created_by: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        import secrets

        tok = token or secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        self._conn.execute(
            "INSERT INTO share_token(token, scope, subject_id, expires_at,"
            " created_by, created_at, revoked) VALUES (?,?,?,?,?,?,0)",
            (tok, scope, subject_id, expires, created_by, now.isoformat()),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM share_token WHERE token=?", (tok,)
        ).fetchone()
        return dict(row)

    def validate_share_token(
        self, token: str, *, scope: str
    ) -> dict[str, Any] | None:
        """校验 token：存在 + 未吊销 + 未过期 + scope 匹配；任一不满足返回 None。"""
        row = self._conn.execute(
            "SELECT * FROM share_token WHERE token=?", (token,)
        ).fetchone()
        if row is None:
            return None
        r = dict(row)
        if r["revoked"]:
            return None
        if r["scope"] != scope:
            return None
        if r["expires_at"] <= _utcnow():
            return None
        return r

    def revoke_share_token(self, token: str) -> bool:
        cur = self._conn.execute(
            "UPDATE share_token SET revoked=1 WHERE token=?", (token,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def flag_orphaned_jobs(self, *, before_ts: str) -> list[str]:
        """将超时仍处于 running 的 job 标记为 failed（可恢复语义，M2 要求）。"""
        rows = self._conn.execute(
            "SELECT job_id FROM job WHERE status='running' AND updated_at < ?",
            (before_ts,),
        ).fetchall()
        ids = [r["job_id"] for r in rows]
        for jid in ids:
            self._conn.execute(
                "UPDATE job SET status='failed', error='orphaned', updated_at=? WHERE job_id=?",
                (_utcnow(), jid),
            )
        if ids:
            self._conn.commit()
        return ids

    # ---------- audit / usage ----------

    def append_audit(
        self,
        *,
        actor: str,
        action: str,
        subject_type: str,
        subject_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_event(ts, actor, action, subject_type, subject_id, detail_json)"
            " VALUES (?,?,?,?,?,?)",
            (_utcnow(), actor, action, subject_type, subject_id, json.dumps(detail or {}, ensure_ascii=False)),
        )
        self._conn.commit()

    def list_audit(self, *, subject_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if subject_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM audit_event WHERE subject_id=? ORDER BY audit_id LIMIT ?",
                (subject_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM audit_event ORDER BY audit_id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def append_usage(
        self,
        *,
        capability: str,
        run_id: str | None,
        quantity: float,
        unit: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO usage_event(ts, capability, run_id, quantity, unit, detail_json)"
            " VALUES (?,?,?,?,?,?)",
            (_utcnow(), capability, run_id, quantity, unit, json.dumps(detail or {}, ensure_ascii=False)),
        )
        self._conn.commit()

    def list_usage(self, *, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if run_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM usage_event WHERE run_id=? ORDER BY usage_id LIMIT ?",
                (run_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM usage_event ORDER BY usage_id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- package_decision / supersede（VLM-015） ----------

    def create_package_decision(
        self,
        *,
        decision_id: str,
        sku_id: str,
        display_name: str,
        package_version_id: str,
        status: str,
        source: str,
        run_id: str | None = None,
        evidence: list[Any] | None = None,
        name_choice: str | None = None,
        created_by: str,
    ) -> dict[str, Any]:
        now = _utcnow()
        try:
            self._conn.execute(
                "INSERT INTO package_decision(decision_id, sku_id, display_name,"
                " package_version_id, status, source, run_id, evidence_json,"
                " name_choice, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (decision_id, sku_id, display_name, package_version_id,
                 status, source, run_id,
                 json.dumps(evidence or [], ensure_ascii=False),
                 name_choice, created_by, now, now),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"package_decision 已存在或字段非法: {decision_id}") from e
        self._conn.commit()
        return self.get_package_decision(decision_id)

    def get_package_decision(self, decision_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM package_decision WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"package_decision 不存在: {decision_id}")
        return dict(row)

    def update_package_decision(
        self, decision_id: str, *, fields: dict[str, Any]
    ) -> dict[str, Any]:
        allowed = {"sku_id", "display_name", "package_version_id",
                   "status", "name_choice"}
        bad = set(fields) - allowed
        if bad:
            raise StoreError(f"非法更新字段: {sorted(bad)}")
        if not fields:
            return self.get_package_decision(decision_id)
        sets = ", ".join(f"{k}=?" for k in fields)
        params = list(fields.values()) + [_utcnow(), decision_id]
        try:
            cur = self._conn.execute(
                f"UPDATE package_decision SET {sets}, updated_at=?"
                " WHERE decision_id=?",
                params,
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"package_decision 更新被拒绝: {decision_id}") from e
        if cur.rowcount == 0:
            raise StoreError(f"package_decision 不存在: {decision_id}")
        self._conn.commit()
        return self.get_package_decision(decision_id)

    def list_package_decisions(
        self, *, sku_id: str | None = None, status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM package_decision"
        conds, params = [], []
        if sku_id is not None:
            conds.append("sku_id=?"); params.append(sku_id)
        if status is not None:
            conds.append("status=?"); params.append(status)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def add_package_supersede(
        self, *, older_decision_id: str, newer_decision_id: str,
        reason: str, created_by: str,
    ) -> None:
        try:
            self._conn.execute(
                "INSERT INTO package_supersede(older_decision_id,"
                " newer_decision_id, reason, created_by, created_at)"
                " VALUES (?,?,?,?,?)",
                (older_decision_id, newer_decision_id, reason,
                 created_by, _utcnow()),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(
                f"supersede 重复或引用缺失: {older_decision_id} -> {newer_decision_id}"
            ) from e
        self._conn.commit()

    def list_package_supersedes(self, decision_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM package_supersede WHERE older_decision_id=?"
            " ORDER BY supersede_id",
            (decision_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- evidence / asset ----------

    def create_evidence_bundle(
        self,
        *,
        evidence_id: str,
        run_id: str,
        kind: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            self._conn.execute(
                "INSERT INTO evidence_bundle(evidence_id, run_id, kind, manifest_json, created_at)"
                " VALUES (?,?,?,?,?)",
                (evidence_id, run_id, kind, json.dumps(manifest, ensure_ascii=False), _utcnow()),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"evidence 已存在或 run 缺失: {evidence_id}") from e
        self._conn.commit()
        return self.get_evidence(evidence_id)

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM evidence_bundle WHERE evidence_id=?", (evidence_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"evidence 不存在: {evidence_id}")
        return dict(row)

    def list_evidence(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM evidence_bundle WHERE run_id=? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- labeling batch / webhook inbox (M4) ----------

    def create_labeling_batch(
        self,
        *,
        batch_id: str,
        name: str,
        assisted_project_id: int | None,
        blind_project_id: int | None,
        task_count: int = 0,
    ) -> dict[str, Any]:
        now = _utcnow()
        try:
            self._conn.execute(
                "INSERT INTO labeling_batch(batch_id, name, assisted_project_id,"
                " blind_project_id, task_count, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (batch_id, name, assisted_project_id, blind_project_id,
                 task_count, "created", now, now),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"labeling batch 已存在: {batch_id}") from e
        self._conn.commit()
        return self.get_labeling_batch(batch_id)

    def get_labeling_batch(self, batch_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM labeling_batch WHERE batch_id=?", (batch_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"labeling batch 不存在: {batch_id}")
        return dict(row)

    def list_labeling_batches(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM labeling_batch ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    _BATCH_FIELDS = {"name", "assisted_project_id", "blind_project_id", "task_count", "status"}

    def update_labeling_batch(self, batch_id: str, **fields: Any) -> dict[str, Any]:
        unknown = set(fields) - self._BATCH_FIELDS
        if unknown:
            raise StoreError(f"未知 labeling batch 字段: {sorted(unknown)}")
        if not fields:
            return self.get_labeling_batch(batch_id)
        sets = ", ".join(f"{k}=?" for k in fields)
        cur = self._conn.execute(
            f"UPDATE labeling_batch SET {sets}, updated_at=? WHERE batch_id=?",
            (*fields.values(), _utcnow(), batch_id),
        )
        if cur.rowcount == 0:
            raise StoreError(f"labeling batch 不存在: {batch_id}")
        self._conn.commit()
        return self.get_labeling_batch(batch_id)

    def record_webhook_event(
        self,
        *,
        source: str,
        event_id: str,
        action: str,
        project_id: int | None = None,
        task_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """幂等收件箱：(source, event_id) 重复时返回 False，不重复写入。"""
        try:
            self._conn.execute(
                "INSERT INTO webhook_event(source, event_id, action, project_id,"
                " task_id, payload_json, received_at) VALUES (?,?,?,?,?,?,?)",
                (source, event_id, action, project_id, task_id,
                 json.dumps(payload or {}, ensure_ascii=False), _utcnow()),
            )
        except sqlite3.IntegrityError:
            return False
        self._conn.commit()
        return True

    def list_webhook_events(
        self, *, source: str | None = None, project_id: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM webhook_event"
        cond: list[str] = []
        args: list[Any] = []
        if source is not None:
            cond.append("source=?")
            args.append(source)
        if project_id is not None:
            cond.append("project_id=?")
            args.append(project_id)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY id"
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ---------- dataset snapshot / training gov (M5) ----------

    def create_dataset_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._conn.execute(
            """INSERT INTO dataset_snapshot (snapshot_id, name, version, mode,
               manifest_hash, manifest_json, guard_json, source_actor,
               source_conclusion, quality_json, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (snapshot["snapshot_id"], snapshot["name"], snapshot["version"],
             snapshot["mode"], snapshot["manifest_hash"], snapshot["manifest_json"],
             snapshot["guard_json"], snapshot["source_actor"],
             snapshot["source_conclusion"], snapshot.get("quality_json", "{}"),
             snapshot.get("status", "registered"), snapshot["created_at"]),
        )
        return snapshot

    def get_dataset_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM dataset_snapshot WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone())

    def list_dataset_snapshots(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM dataset_snapshot ORDER BY created_at DESC").fetchall()]

    def mark_dataset_snapshot_trainable(
        self, snapshot_id: str, *, trainable: int, note: str
    ) -> dict[str, Any] | None:
        """审计式标记（U0-2/UMT-004）：不删除行，仅改可训练标志与备注。"""
        self._conn.execute(
            "UPDATE dataset_snapshot SET trainable=?, status_note=?"
            " WHERE snapshot_id=?",
            (1 if trainable else 0, note, snapshot_id),
        )
        self._conn.commit()
        return self.get_dataset_snapshot(snapshot_id)

    def create_training_run(self, run: dict[str, Any]) -> dict[str, Any]:
        self._conn.execute(
            """INSERT INTO training_run (run_id, snapshot_id, kind, plan_json,
               command_json, budget_json, stop_lines_json, status, publish_status,
               requested_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run["run_id"], run.get("snapshot_id"), run.get("kind", "dry_run"),
             run["plan_json"], run["command_json"], run["budget_json"],
             run["stop_lines_json"], run.get("status", "dry_run"),
             run.get("publish_status", "none"), run.get("requested_by"),
             run["created_at"], run["updated_at"]),
        )
        return run

    def get_training_run(self, run_id: str) -> dict[str, Any] | None:
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM training_run WHERE run_id=?", (run_id,)).fetchone())

    def list_training_runs(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM training_run ORDER BY created_at DESC").fetchall()]

    _TRAINING_RUN_FIELDS = (
        "kind", "status", "publish_status", "approved_by", "requested_by",
        "publish_requested_by", "publish_approved_by", "plan_json", "job_id",
    )

    def update_training_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        bad = set(fields) - set(self._TRAINING_RUN_FIELDS)
        if bad:
            raise ValueError(f"不允许的字段: {sorted(bad)}")
        if not fields:
            raise ValueError("无更新字段")
        fields["updated_at"] = _utcnow()
        sets = ", ".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE training_run SET {sets} WHERE run_id=?",
            (*fields.values(), run_id),
        )
        self._conn.commit()
        got = self.get_training_run(run_id)
        if got is None:
            raise KeyError(run_id)
        return got

    def get_flag(self, flag: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM platform_flag WHERE flag=?", (flag,)).fetchone()
        return row["value"] if row else None

    def set_flag(self, flag: str, value: str, actor: str) -> None:
        self._conn.execute(
            """INSERT INTO platform_flag (flag, value, updated_at, updated_by)
               VALUES (?,?,?,?) ON CONFLICT(flag) DO UPDATE SET
               value=excluded.value, updated_at=excluded.updated_at,
               updated_by=excluded.updated_by""",
            (flag, value, _utcnow(), actor),
        )

    # ---------- auth session（UMT-006） ----------

    def create_auth_session(
        self, *, session_id: str, actor: str, role: str,
        csrf_token: str, created_at: str, expires_at: str,
    ) -> None:
        self._conn.execute(
            """INSERT INTO auth_sessions
               (session_id, actor, role, csrf_token, created_at, expires_at)
               VALUES (?,?,?,?,?,?)""",
            (session_id, actor, role, csrf_token, created_at, expires_at),
        )
        self._conn.commit()

    def get_auth_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM auth_sessions WHERE session_id=?",
            (session_id,)).fetchone()
        return dict(row) if row else None

    def delete_auth_session(self, session_id: str) -> None:
        self._conn.execute(
            "DELETE FROM auth_sessions WHERE session_id=?", (session_id,))
        self._conn.commit()

    # ---------- recognition task（U2-3） ----------

    def create_recognition_task(
        self, *, task_id: str, entry: str, status: str,
        file_count: int, sku_count: int, created_by: str,
        result_json: str = "", error: str = "",
        idempotency_key: str | None = None,
        recognition_profile_id: str = "",
        service_tier: str = "", source: str = "",
        project_id: str = "", trace_id: str = "",
        run_id: str = "", work_id: str = "", correlation_id: str = "",
    ) -> dict[str, Any]:
        self._conn.execute(
            """INSERT INTO recognition_task
               (task_id, entry, status, file_count, sku_count,
                created_by, created_at, result_json, error,
                idempotency_key, recognition_profile_id, service_tier,
                source, project_id, trace_id, run_id, work_id,
                correlation_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, entry, status, file_count, sku_count,
             created_by, _utcnow(), result_json, error,
             idempotency_key, recognition_profile_id, service_tier,
             source, project_id, trace_id, run_id, work_id,
             correlation_id),
        )
        self._conn.commit()
        return self.get_recognition_task(task_id)

    def find_recognition_task_by_idempotency_key(
        self, key: str,
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM recognition_task WHERE idempotency_key=?",
            (key,)).fetchone()
        return dict(row) if row else None

    def get_recognition_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM recognition_task WHERE task_id=?",
            (task_id,)).fetchone()
        return dict(row) if row else None

    def list_recognition_tasks(self, *, limit: int = 100,
                               offset: int = 0,
                               status: str | None = None,
                               ) -> list[dict[str, Any]]:
        where, params = "", []
        if status:
            where, params = "WHERE status=?", [status]
        rows = self._conn.execute(
            "SELECT * FROM recognition_task " + where +
            " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            params + [min(limit, 500), max(offset, 0)]).fetchall()
        return [dict(r) for r in rows]

    def count_recognition_tasks(self, *, status: str | None = None) -> int:
        where, params = "", []
        if status:
            where, params = "WHERE status=?", [status]
        row = self._conn.execute(
            "SELECT COUNT(*) FROM recognition_task " + where,
            params).fetchone()
        return int(row[0])

    # ---------- source_asset_inventory_v1（U3-2，不可变台账） ----------

    def register_inventory_asset(
        self,
        *,
        source_id: str,
        source_type: str,
        source_uri: str,
        photo_id: str = "",
        sha256: str = "",
    ) -> dict[str, Any]:
        """追加式登记一条来源引用；(source_id, source_uri) 幂等。

        同 SHA 不同来源各自保留（去重在 U3-3）；禁止 UPDATE/DELETE（触发器）。
        """
        conn = self._conn
        row = conn.execute(
            "SELECT * FROM source_asset_inventory_v1"
            " WHERE source_id=? AND source_uri=?",
            (source_id, source_uri),
        ).fetchone()
        if row is not None:
            return dict(row)
        asset_id = hashlib.sha256(
            f"{source_id}\x00{source_uri}".encode("utf-8")
        ).hexdigest()
        now = _utcnow()
        conn.execute(
            "INSERT INTO source_asset_inventory_v1"
            "(asset_id, source_id, source_type, source_uri, photo_id,"
            " sha256, registered_at) VALUES (?,?,?,?,?,?,?)",
            (asset_id, source_id, source_type, source_uri, photo_id,
             sha256, now),
        )
        return {
            "asset_id": asset_id, "source_id": source_id,
            "source_type": source_type, "source_uri": source_uri,
            "photo_id": photo_id, "sha256": sha256,
            "registered_at": now,
        }

    def count_inventory_assets(self, *, source_id: str | None = None) -> int:
        where, params = "", []
        if source_id:
            where, params = "WHERE source_id=?", [source_id]
        row = self._conn.execute(
            "SELECT COUNT(*) FROM source_asset_inventory_v1 " + where,
            params).fetchone()
        return int(row[0])

    def list_inventory_assets(
        self,
        *,
        source_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, params = "", []
        if source_id:
            where, params = "WHERE source_id=?", [source_id]
        rows = self._conn.execute(
            "SELECT * FROM source_asset_inventory_v1 " + where
            + " ORDER BY asset_id LIMIT ? OFFSET ?",
            [*params, limit, offset]).fetchall()
        return [dict(r) for r in rows]

    # ---------- quality_decision_v1（U3-5，不可变质量结论） ----------

    def record_quality_decision(
        self,
        *,
        sha256: str,
        policy_version: str,
        score: dict[str, Any],
        threshold: dict[str, Any],
        auto_decision: str,
        human_decision: str | None,
        model_version: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utcnow()
        cur = self._conn.execute(
            "INSERT INTO quality_decision_v1"
            "(sha256, policy_version, score_json, threshold_json,"
            " auto_decision, human_decision, model_version, evidence_json,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (sha256, policy_version, json.dumps(score, ensure_ascii=False),
             json.dumps(threshold, ensure_ascii=False), auto_decision,
             human_decision, model_version,
             json.dumps(evidence or {}, ensure_ascii=False), now))
        return {"id": cur.lastrowid, "sha256": sha256,
                "policy_version": policy_version,
                "auto_decision": auto_decision,
                "human_decision": human_decision, "created_at": now}

    def list_quality_decisions(
        self, *, sha256: str | None = None, limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, params = "", []
        if sha256:
            where, params = "WHERE sha256=?", [sha256]
        rows = self._conn.execute(
            "SELECT * FROM quality_decision_v1 " + where
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset]).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["score"] = json.loads(d.pop("score_json"))
            d["threshold"] = json.loads(d.pop("threshold_json"))
            d["evidence"] = json.loads(d.pop("evidence_json"))
            out.append(d)
        return out

    # ---------- quality_gold_v1 / quality_human_v1（U3-6，不可变） ----------

    def add_gold_item(self, *, sha256: str, source_uri: str,
                      stratum: str) -> bool:
        """追加一条金标准队列项；sha256 幂等，返回是否新增。"""
        try:
            self._conn.execute(
                "INSERT INTO quality_gold_v1"
                "(sha256, source_uri, stratum, created_at)"
                " VALUES (?,?,?,?)",
                (sha256, source_uri, stratum, _utcnow()))
            return True
        except sqlite3.IntegrityError:
            return False

    def list_gold_queue(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM quality_gold_v1 ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def add_human_verdict(self, *, sha256: str, verdict: str,
                          reviewer: str,
                          dims: dict[str, Any] | None = None) -> bool:
        """追加一条人工结论；同一 sha256 只允许一次（UNIQUE），
        之后任何 UPDATE/DELETE 由触发器 RAISE。"""
        try:
            self._conn.execute(
                "INSERT INTO quality_human_v1"
                "(sha256, verdict, dims_json, reviewer, created_at)"
                " VALUES (?,?,?,?,?)",
                (sha256, verdict,
                 json.dumps(dims or {}, ensure_ascii=False),
                 reviewer, _utcnow()))
            return True
        except sqlite3.IntegrityError:
            return False

    def find_human_verdict(self, sha256: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM quality_human_v1 WHERE sha256=?",
            (sha256,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["dims"] = json.loads(d.pop("dims_json"))
        return d

    def list_human_verdicts(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM quality_human_v1 ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["dims"] = json.loads(d.pop("dims_json"))
            out.append(d)
        return out

    # ---------- sam_lineage_v1（U4-1，不可变 lineage） ----------

    def record_sam_lineage(self, *, instance_id: str, image_sha256: str,
                           point_x: float, point_y: float,
                           prompt_config_version: str,
                           positive_point: tuple, model: str,
                           decision: str, selection_reason: str = "",
                           rules_version: str = "",
                           photo_id: str = "",
                           negative_points: list | None = None,
                           coarse_box: tuple | None = None,
                           checkpoint_sha256: str = "",
                           escalated_to: str | None = None,
                           tight_box: tuple | None = None,
                           mask_sha256: str | None = None,
                           mask_path: str | None = None,
                           reject_reasons: list | None = None,
                           run_dir: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO sam_lineage_v1"
            "(instance_id, photo_id, image_sha256, point_x, point_y,"
            " prompt_config_version, positive_point_json,"
            " negative_points_json, coarse_box_json, model,"
            " checkpoint_sha256, decision, escalated_to, tight_box_json,"
            " mask_sha256, mask_path, selection_reason, rules_version,"
            " reject_reasons_json, run_dir, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (instance_id, photo_id, image_sha256, float(point_x),
             float(point_y), prompt_config_version,
             json.dumps(list(positive_point)),
             json.dumps([list(p) for p in (negative_points or [])]),
             json.dumps(list(coarse_box)) if coarse_box else None,
             model, checkpoint_sha256, decision, escalated_to,
             json.dumps(list(tight_box)) if tight_box else None,
             mask_sha256, mask_path, selection_reason, rules_version,
             json.dumps(reject_reasons or []), run_dir, _utcnow()))
        return int(cur.lastrowid)

    def list_sam_lineage(self, *, image_sha: str | None = None,
                         limit: int = 500,
                         offset: int = 0) -> list[dict[str, Any]]:
        where, params = "", []
        if image_sha:
            where, params = "WHERE image_sha256=?", [image_sha]
        rows = self._conn.execute(
            "SELECT * FROM sam_lineage_v1 " + where
            + " ORDER BY id LIMIT ? OFFSET ?",
            [*params, min(limit, 2000), max(offset, 0)]).fetchall()
        return [dict(r) for r in rows]

    # ---------- review_task_v1 / review_event_v1（U4-2，不可变+追加式） ----------

    def add_review_task(self, *, task_id: str, claim_token: str,
                        photo_id: str, sha256: str, review_mode: str,
                        requires_second_review: bool,
                        queue_version: str = "rq_v1",
                        protocol: str = "",
                        import_seed: int | None = None) -> bool:
        """幂等写入审核任务；(photo_id, sha256, review_mode) 已存在则跳过
        （真实队列中盲抽项可能与双审项同照片，故幂等键含 review_mode）。"""
        try:
            self._conn.execute(
                "INSERT INTO review_task_v1"
                "(task_id, claim_token, photo_id, sha256, review_mode,"
                " requires_second_review, status, claimed_by,"
                " queue_version, protocol, import_seed, created_at)"
                " VALUES (?,?,?,?,?,?,'pending',NULL,?,?,?,?)",
                (task_id, claim_token, photo_id, sha256, review_mode,
                 1 if requires_second_review else 0, queue_version,
                 protocol, import_seed, _utcnow()))
            return True
        except sqlite3.IntegrityError:
            return False

    def list_review_tasks(self, *, limit: int = 5000,
                          status: str | None = None
                          ) -> list[dict[str, Any]]:
        # 单审任务优先派发（requires_second_review 升序），确定性排序
        rows = self._conn.execute(
            "SELECT * FROM review_task_v1"
            " ORDER BY requires_second_review, id LIMIT ?",
            (min(limit, 20000),)).fetchall()
        return [dict(r) for r in rows]

    def find_review_task(self, *, photo_id: str, sha256: str,
                         review_mode: str = ""
                         ) -> dict[str, Any] | None:
        if review_mode:
            r = self._conn.execute(
                "SELECT * FROM review_task_v1"
                " WHERE photo_id=? AND sha256=? AND review_mode=?",
                (photo_id, sha256, review_mode)).fetchone()
        else:
            r = self._conn.execute(
                "SELECT * FROM review_task_v1"
                " WHERE photo_id=? AND sha256=?",
                (photo_id, sha256)).fetchone()
        return dict(r) if r else None

    def find_review_task_by_token(self,
                                  claim_token: str
                                  ) -> dict[str, Any] | None:
        r = self._conn.execute(
            "SELECT * FROM review_task_v1 WHERE claim_token=?",
            (claim_token,)).fetchone()
        return dict(r) if r else None

    def find_review_task_by_id(self,
                               task_id: str) -> dict[str, Any] | None:
        r = self._conn.execute(
            "SELECT * FROM review_task_v1 WHERE task_id=?",
            (task_id,)).fetchone()
        return dict(r) if r else None

    def add_review_event(self, *, task_id: str, kind: str, actor: str,
                         role: str = "annotator",
                         verdict: str | None = None,
                         box: tuple | list | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO review_event_v1"
            "(task_id, kind, actor, role, verdict, box_json, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (task_id, kind, actor, role, verdict,
             json.dumps([float(v) for v in box]) if box is not None
             else None, _utcnow()))
        return int(cur.lastrowid)

    def list_review_events(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM review_event_v1 WHERE task_id=? ORDER BY id",
            (task_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["box"] = json.loads(d["box_json"]) if d["box_json"] else None
            out.append(d)
        return out

    # ---------- gold regions（区域级人工真值账本，追加式） ----------

    def add_gold_region(self, *, task_id: str, region_id: str,
                        photo_id: str, sha256: str, box: tuple | list,
                        sku_id: str, sku_name: str,
                        package_version_id: str = "",
                        review_status: str = "submitted",
                        actor: str, role: str = "annotator",
                        evidence: dict | None = None,
                        group_store: str = "", group_session: str = "",
                        near_dup_group: str = "") -> bool:
        """追加一条区域级人工真值记录；(task_id, region_id, actor) 幂等。"""
        try:
            self._conn.execute(
                "INSERT INTO gold_region_v1"
                "(task_id, region_id, photo_id, sha256, box_json, sku_id,"
                " sku_name, package_version_id, review_status, actor, role,"
                " evidence_json, group_store, group_session, near_dup_group,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, region_id, photo_id, sha256,
                 json.dumps([float(v) for v in box]), sku_id, sku_name,
                 package_version_id, review_status, actor, role,
                 json.dumps(evidence or {}, ensure_ascii=False),
                 group_store, group_session, near_dup_group, _utcnow()))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # 同一审核员对同一 region 重复提交 → 幂等跳过

    def add_gold_regions_atomic(self, regions: list[dict[str, Any]]) -> bool:
        """单事务批量追加区域级人工真值（任务书§十一.1 原子性）：
        全部成功才 COMMIT；任一条冲突（如 (task_id, region_id, actor)
        重复）→ 整批 ROLLBACK，返回 False，保证整次审核零落账。"""
        if not regions:
            return True
        conn = self._conn
        try:
            conn.execute("BEGIN")
            for rg in regions:
                conn.execute(
                    "INSERT INTO gold_region_v1"
                    "(task_id, region_id, photo_id, sha256, box_json, sku_id,"
                    " sku_name, package_version_id, review_status, actor,"
                    " role, evidence_json, group_store, group_session,"
                    " near_dup_group, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rg["task_id"], rg["region_id"], rg["photo_id"],
                     rg["sha256"],
                     json.dumps([float(v) for v in rg["box"]]),
                     rg["sku_id"], rg["sku_name"],
                     rg.get("package_version_id", ""),
                     rg.get("review_status", "submitted"), rg["actor"],
                     rg.get("role", "annotator"),
                     json.dumps(rg.get("evidence") or {}, ensure_ascii=False),
                     rg.get("group_store", ""), rg.get("group_session", ""),
                     rg.get("near_dup_group", ""), _utcnow()))
            conn.execute("COMMIT")
            return True
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            return False  # 整批回滚 → 半次审核不落账

    def list_gold_regions(self, task_id: str | None = None) -> list[dict[str, Any]]:
        if task_id is None:
            rows = self._conn.execute(
                "SELECT * FROM gold_region_v1 ORDER BY id").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM gold_region_v1 WHERE task_id=? ORDER BY id",
                (task_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["box"] = json.loads(d["box_json"])
            d["evidence"] = json.loads(d["evidence_json"] or "{}")
            out.append(d)
        return out

    # ---------- review queue ledger（PLC3-002，追加式失效账本） ----------

    def register_queue_version(self, *, queue_version: str, protocol: str = "",
                               n_tasks: int = 0,
                               source_path: str = "") -> bool:
        """登记队列版本（幂等：已存在则保留原登记，不覆盖）。"""
        try:
            self._conn.execute(
                "INSERT INTO review_queue_ledger_v1"
                "(queue_version, protocol, n_tasks, source_path, registered_at)"
                " VALUES (?,?,?,?,?)",
                (queue_version, protocol, n_tasks, source_path, _utcnow()))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def invalidate_queue_version(self, *, queue_version: str, reason: str,
                                 root_cause: str = "",
                                 impact_summary: str = "",
                                 git_commit: str = "",
                                 evidence_path: str = "",
                                 superseded_by: str = "") -> bool:
        """追加式失效一个队列版本；不改写 review_task_v1 任务行。

        fail-closed：未登记的队列版本不允许失效；重复失效幂等。"""
        row = self._conn.execute(
            "SELECT queue_version FROM review_queue_ledger_v1"
            " WHERE queue_version=?", (queue_version,)).fetchone()
        if row is None:
            raise StoreError(f"队列版本未登记，不得失效: {queue_version}")
        try:
            self._conn.execute(
                "INSERT INTO review_queue_invalidation_v1"
                "(queue_version, reason, root_cause, impact_summary,"
                " git_commit, evidence_path, superseded_by, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (queue_version, reason, root_cause, impact_summary,
                 git_commit, evidence_path, superseded_by, _utcnow()))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # 已失效，幂等

    def list_queue_ledger(self) -> list[dict[str, Any]]:
        """队列版本账本（join 推导 status：active/invalid）。"""
        rows = self._conn.execute(
            "SELECT l.*, i.reason AS invalid_reason,"
            " i.root_cause, i.impact_summary, i.git_commit AS invalid_commit,"
            " i.evidence_path, i.superseded_by, i.created_at AS invalidated_at"
            " FROM review_queue_ledger_v1 l"
            " LEFT JOIN review_queue_invalidation_v1 i"
            "   ON i.queue_version = l.queue_version"
            " ORDER BY l.registered_at, l.queue_version").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["status"] = "invalid" if d["invalid_reason"] is not None else "active"
            out.append(d)
        return out

    def _invalid_queue_versions(self) -> set[str]:
        rows = self._conn.execute(
            "SELECT queue_version FROM review_queue_invalidation_v1").fetchall()
        return {r["queue_version"] for r in rows}

    # ---------- work_item_supersession_v1（ABOSV2-P0-001） ----------

    def add_work_item_supersession(self, *, family: str,
                                   match: dict[str, Any],
                                   superseded_by: str, reason: str,
                                   decided_by: str) -> bool:
        """追加式登记工作族被取代；幂等（同 family+match+取代者）。

        match 为 detail 字段匹配器：{字段: [允许值...]}，所有字段须命中。
        不改写任何历史行；current 投影消费本账本。"""
        match_json = json.dumps(match, sort_keys=True, ensure_ascii=False)
        try:
            self._conn.execute(
                "INSERT INTO work_item_supersession_v1"
                " (family, match_json, superseded_by, reason, decided_by,"
                " decided_at, created_at) VALUES (?,?,?,?,?,?,?)",
                (family, match_json, superseded_by, reason, decided_by,
                 _utcnow(), _utcnow()))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # 已登记，幂等

    def list_work_item_supersessions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM work_item_supersession_v1"
            " ORDER BY supersession_id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["match"] = json.loads(d.pop("match_json"))
            except (ValueError, KeyError):
                d["match"] = {}
            out.append(d)
        return out

    # ---------- goal_draft_v1（ABOSV2-P0-002） ----------

    def create_goal_draft(self, *, goal_id: str, text: str,
                          created_by: str) -> dict[str, Any]:
        now = _utcnow()
        self._conn.execute(
            "INSERT INTO goal_draft_v1 (goal_id, text, status, created_by,"
            " created_at, updated_at, version, result_json)"
            " VALUES (?,?,?, ?,?,?,1,'{}')",
            (goal_id, text, "open", created_by, now, now))
        self._conn.commit()
        return self.get_goal_draft(goal_id)

    def get_goal_draft(self, goal_id: str) -> dict[str, Any] | None:
        d = _row_to_dict(self._conn.execute(
            "SELECT * FROM goal_draft_v1 WHERE goal_id=?",
            (goal_id,)).fetchone())
        if d is not None:
            try:
                d["result"] = json.loads(d.pop("result_json"))
            except ValueError:
                d["result"] = {}
        return d

    def list_goal_drafts(self, *, status: str | None = None
                         ) -> list[dict[str, Any]]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM goal_draft_v1 WHERE status=?"
                " ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM goal_draft_v1"
                " ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["result"] = json.loads(d.pop("result_json"))
            except ValueError:
                d["result"] = {}
            out.append(d)
        return out

    def resolve_goal_draft(self, goal_id: str, *, status: str,
                           result: dict[str, Any],
                           expected_version: int) -> dict[str, Any]:
        """乐观锁更新 goal 状态（open→confirmed/cancelled）。

        非法跃迁或版本冲突抛 StoreError；历史不删除。"""
        row = self._conn.execute(
            "SELECT status, version FROM goal_draft_v1 WHERE goal_id=?",
            (goal_id,)).fetchone()
        if row is None:
            raise StoreError(f"goal 不存在: {goal_id}")
        if row["status"] != "open":
            raise StoreError(
                f"goal 已终态 {row['status']}，不得重复操作")
        if row["version"] != expected_version:
            raise StoreError("goal 乐观锁版本冲突")
        n = self._conn.execute(
            "UPDATE goal_draft_v1 SET status=?, result_json=?,"
            " updated_at=?, version=version+1"
            " WHERE goal_id=? AND version=?",
            (status, json.dumps(result, ensure_ascii=False), _utcnow(),
             goal_id, expected_version))
        if n.rowcount != 1:
            raise StoreError("goal 乐观锁版本冲突")
        self._conn.commit()
        return self.get_goal_draft(goal_id)

    # ---------- 统一 Work/Event/Usage 控制平面（ABOSV2 Phase B） ----------

    RUN_TRANSITIONS = {
        "queued": {"running", "cancelled"},
        "running": {"running", "succeeded", "failed", "cancelled",
                    "paused", "waiting_human"},
        "failed": {"running"},          # 只能经 retry 重新进入 running
        "paused": {"running", "cancelled"},
        "waiting_human": {"running", "cancelled"},
        "succeeded": set(),
        "cancelled": set(),
    }

    def insert_business_run(self, row: dict[str, Any]) -> dict[str, Any]:
        now = _utcnow()
        self._conn.execute(
            "INSERT INTO business_run_v1 (run_id, work_id, tenant_id,"
            " customer_id, project_id, workflow_definition_id,"
            " workflow_version, trigger_type, parent_run_id,"
            " correlation_id, causation_id, subject_type, subject_id,"
            " initiator_type, initiator_id, status, current_node,"
            " version, usage_account_id, command_kind, params_json,"
            " idempotency_key, goal_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?,1,?,?,?,?,?,?,?)",
            (row["run_id"], row.get("work_id", ""),
             row.get("tenant_id", "local"), row.get("customer_id", ""),
             row.get("project_id", ""),
             row.get("workflow_definition_id", ""),
             row.get("workflow_version", ""),
             row.get("trigger_type", "command"),
             row.get("parent_run_id"), row.get("correlation_id", ""),
             row.get("causation_id"), row.get("subject_type", ""),
             row.get("subject_id", ""), row.get("initiator_type", "human"),
             row.get("initiator_id", ""), row.get("status", "queued"),
             row.get("current_node", ""), row.get("usage_account_id", ""),
             row.get("command_kind", ""),
             json.dumps(row.get("params", {}), ensure_ascii=False),
             row.get("idempotency_key"), row.get("goal_id", ""),
             now, now))
        self._conn.commit()
        return self.get_business_run(row["run_id"])

    def get_business_run(self, run_id: str) -> dict[str, Any] | None:
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM business_run_v1 WHERE run_id=?",
            (run_id,)).fetchone())

    def find_business_run_by_idempotency_key(
            self, key: str) -> dict[str, Any] | None:
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM business_run_v1 WHERE idempotency_key=?",
            (key,)).fetchone())

    def set_business_run_status(self, run_id: str, status: str, *,
                                error: str = "",
                                current_node: str | None = None,
                                subject_type: str | None = None,
                                subject_id: str | None = None,
                                evidence_bundle_id: str | None = None,
                                ) -> dict[str, Any]:
        """状态机：failed 不得直接变成功；终态不可回退。"""
        row = self._conn.execute(
            "SELECT status FROM business_run_v1 WHERE run_id=?",
            (run_id,)).fetchone()
        if row is None:
            raise StoreError(f"run 不存在: {run_id}")
        cur = row["status"]
        if status not in self.RUN_TRANSITIONS.get(cur, set()):
            raise StoreError(f"run {cur}→{status} 非法跃迁")
        sets = ["status=?", "version=version+1", "updated_at=?"]
        vals: list[Any] = [status, _utcnow()]
        if status == "running" and cur == "queued":
            sets.append("started_at=?"); vals.append(_utcnow())
        if status in ("succeeded", "failed", "cancelled"):
            sets.append("ended_at=?"); vals.append(_utcnow())
        if error:
            sets.append("error=?"); vals.append(error)
        if current_node is not None:
            sets.append("current_node=?"); vals.append(current_node)
        if subject_type is not None:
            sets.append("subject_type=?"); vals.append(subject_type)
        if subject_id is not None:
            sets.append("subject_id=?"); vals.append(subject_id)
        if evidence_bundle_id is not None:
            sets.append("evidence_bundle_id=?")
            vals.append(evidence_bundle_id)
        self._conn.execute(
            f"UPDATE business_run_v1 SET {', '.join(sets)}"
            " WHERE run_id=?", (*vals, run_id))
        self._conn.commit()
        return self.get_business_run(run_id)

    def insert_work_item_v2(self, row: dict[str, Any]) -> dict[str, Any]:
        now = _utcnow()
        self._conn.execute(
            "INSERT INTO work_item_v2 (work_id, tenant_id, customer_id,"
            " project_id, run_id, status, owner_type, owner_id, title,"
            " business_summary, subject_type, subject_id, idempotency_key,"
            " created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["work_id"], row.get("tenant_id", "local"),
             row.get("customer_id", ""), row.get("project_id", ""),
             row.get("run_id", ""), row.get("status", "todo"),
             row.get("owner_type", "human"), row.get("owner_id", ""),
             row.get("title", ""), row.get("business_summary", ""),
             row.get("subject_type", ""), row.get("subject_id", ""),
             row.get("idempotency_key"), now, now))
        self._conn.commit()
        return self.get_work_item_v2(row["work_id"])

    def get_work_item_v2(self, work_id: str) -> dict[str, Any] | None:
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM work_item_v2 WHERE work_id=?",
            (work_id,)).fetchone())

    def set_work_item_v2_status(self, work_id: str, status: str, *,
                                subject_type: str | None = None,
                                subject_id: str | None = None,
                                blockers: list[str] | None = None,
                                ) -> None:
        sets = ["status=?", "version=version+1", "updated_at=?"]
        vals: list[Any] = [status, _utcnow()]
        if subject_type is not None:
            sets.append("subject_type=?"); vals.append(subject_type)
        if subject_id is not None:
            sets.append("subject_id=?"); vals.append(subject_id)
        if blockers is not None:
            sets.append("blockers_json=?")
            vals.append(json.dumps(blockers, ensure_ascii=False))
        self._conn.execute(
            f"UPDATE work_item_v2 SET {', '.join(sets)} WHERE work_id=?",
            (*vals, work_id))
        self._conn.commit()

    def list_work_items_v2(self, *, status: str | None = None
                           ) -> list[dict[str, Any]]:
        where, params = "", []
        if status:
            where, params = "WHERE status=?", [status]
        rows = self._conn.execute(
            "SELECT * FROM work_item_v2 " + where +
            " ORDER BY created_at DESC", params).fetchall()
        return [dict(r) for r in rows]

    def emit_event(self, *, event_id: str, event_type: str,
                   run_id: str = "", work_id: str = "",
                   correlation_id: str = "", causation_id: str | None = None,
                   actor_type: str = "human", actor_id: str = "",
                   subject_type: str = "", subject_id: str = "",
                   payload: dict[str, Any] | None = None,
                   idempotency_key: str | None = None) -> dict[str, Any]:
        """事件 + outbox 同一事务提交（Transactional Outbox）。"""
        conn = self._conn
        now = _utcnow()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO event_envelope_v1 (event_id, event_type,"
                " occurred_at, actor_type, actor_id, correlation_id,"
                " causation_id, run_id, work_id, subject_type, subject_id,"
                " payload_json, idempotency_key)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, event_type, now, actor_type, actor_id,
                 correlation_id, causation_id, run_id, work_id,
                 subject_type, subject_id,
                 json.dumps(payload or {}, ensure_ascii=False),
                 idempotency_key))
            conn.execute(
                "INSERT INTO outbox_v1 (event_id, status, attempts,"
                " created_at) VALUES (?,?,0,?)", (event_id, "pending", now))
            conn.execute("COMMIT")
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            raise
        return _row_to_dict(conn.execute(
            "SELECT * FROM event_envelope_v1 WHERE event_id=?",
            (event_id,)).fetchone())

    def list_events(self, *, run_id: str | None = None,
                    work_id: str | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        if run_id:
            where.append("run_id=?"); params.append(run_id)
        if work_id:
            where.append("work_id=?"); params.append(work_id)
        sql = "SELECT * FROM event_envelope_v1"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY seq"
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def dispatch_outbox(self) -> int:
        """至少一次投递：pending → dispatched（本机同进程消费）。"""
        n = self._conn.execute(
            "UPDATE outbox_v1 SET status='dispatched', attempts=attempts+1,"
            " dispatched_at=? WHERE status='pending'", (_utcnow(),))
        self._conn.commit()
        return n.rowcount

    def insert_usage_event_v2(self, *, usage_id: str, unit: str,
                              quantity: float, run_id: str = "",
                              work_id: str = "", node: str = "",
                              capability: str = "", model: str = "",
                              profile_id: str = "", tier: str = "",
                              customer_id: str = "", project_id: str = "",
                              source_evidence: str = "") -> dict[str, Any]:
        self._conn.execute(
            "INSERT INTO usage_event_v2 (usage_id, customer_id, project_id,"
            " run_id, work_id, node, capability, model, profile_id, tier,"
            " unit, quantity, source_evidence, occurred_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (usage_id, customer_id, project_id, run_id, work_id, node,
             capability, model, profile_id, tier, unit, float(quantity),
             source_evidence, _utcnow()))
        self._conn.commit()
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM usage_event_v2 WHERE usage_id=?",
            (usage_id,)).fetchone())

    def list_usage_events_v2(self, *, run_id: str | None = None
                             ) -> list[dict[str, Any]]:
        if run_id:
            rows = self._conn.execute(
                "SELECT * FROM usage_event_v2 WHERE run_id=?"
                " ORDER BY occurred_at", (run_id,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM usage_event_v2"
                " ORDER BY occurred_at").fetchall()
        return [dict(r) for r in rows]

    def insert_evidence_bundle(self, *, evidence_id: str, kind: str,
                               run_id: str = "", work_id: str = "",
                               source_uri: str = "", cas_hash: str = "",
                               content_type: str = "", producer: str = "",
                               input_hash: str = "",
                               config_version: str = "") -> dict[str, Any]:
        self._conn.execute(
            "INSERT INTO evidence_bundle_v1 (evidence_id, run_id, work_id,"
            " kind, source_uri, cas_hash, content_type, producer,"
            " input_hash, config_version, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (evidence_id, run_id, work_id, kind, source_uri, cas_hash,
             content_type, producer, input_hash, config_version, _utcnow()))
        self._conn.commit()
        return self.get_evidence_bundle(evidence_id)

    def get_evidence_bundle(self, evidence_id: str
                            ) -> dict[str, Any] | None:
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM evidence_bundle_v1 WHERE evidence_id=?",
            (evidence_id,)).fetchone())

    def rebuild_work_projection(self) -> dict[str, Any]:
        """从事件重建 current 投影（幂等）；hash/count 可对账。

        规则：command.accepted→running；run.succeeded→done；
        run.failed→blocked；run.cancelled→cancelled；按事件 seq 演进。
        """
        events = self.list_events()
        self.dispatch_outbox()  # 至少一次投递：重建时统一消费 pending
        state: dict[str, dict[str, Any]] = {}
        for e in events:
            wid = e.get("work_id") or ""
            if not wid:
                continue
            st = state.setdefault(wid, {
                "work_id": wid, "status": "todo",
                "subject_type": "", "subject_id": "",
                "run_id": e.get("run_id", "")})
            t = e["event_type"]
            if t == "command.accepted":
                st["status"] = "running"
            elif t == "run.succeeded":
                st["status"] = "done"
                st["subject_type"] = e.get("subject_type") or st["subject_type"]
                st["subject_id"] = e.get("subject_id") or st["subject_id"]
            elif t == "run.failed":
                st["status"] = "blocked"
                st["subject_type"] = e.get("subject_type") or st["subject_type"]
                st["subject_id"] = e.get("subject_id") or st["subject_id"]
            elif t == "run.cancelled":
                st["status"] = "cancelled"
        items = sorted(state.values(), key=lambda x: x["work_id"])
        # 同步到 work_item_v2（重建不丢失原始行，只更新状态/主体）
        for it in items:
            row = self.get_work_item_v2(it["work_id"])
            if row is not None and (row["status"] != it["status"]
                                    or row["subject_id"] != it["subject_id"]):
                self.set_work_item_v2_status(
                    it["work_id"], it["status"],
                    subject_type=it["subject_type"],
                    subject_id=it["subject_id"])
        canonical = json.dumps(
            [{"work_id": i["work_id"], "status": i["status"],
              "subject_id": i["subject_id"]} for i in items],
            sort_keys=True, ensure_ascii=False)
        return {"count": len(items), "items": items,
                "hash": hashlib.sha256(canonical.encode()).hexdigest()}

    # ---------- Workflow Studio（ABOSV2 Phase C） ----------

    def insert_workflow_definition(self, *, definition_id: str,
                                   version: int, name: str,
                                   spec: dict[str, Any], created_by: str,
                                   owner: str = "") -> dict[str, Any]:
        now = _utcnow()
        spec_json = json.dumps(spec, sort_keys=True, ensure_ascii=False)
        self._conn.execute(
            "INSERT INTO workflow_definition_v1 (definition_id, version,"
            " name, status, owner, spec_json, spec_hash, created_by,"
            " created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (definition_id, version, name, "draft", owner, spec_json,
             hashlib.sha256(spec_json.encode()).hexdigest(),
             created_by, now, now))
        self._conn.commit()
        return self.get_workflow_definition(definition_id, version)

    def get_workflow_definition(self, definition_id: str,
                                version: int | None = None
                                ) -> dict[str, Any] | None:
        if version is None:
            row = self._conn.execute(
                "SELECT * FROM workflow_definition_v1 WHERE definition_id=?"
                " ORDER BY version DESC LIMIT 1",
                (definition_id,)).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM workflow_definition_v1"
                " WHERE definition_id=? AND version=?",
                (definition_id, version)).fetchone()
        d = _row_to_dict(row)
        if d is not None:
            d["spec"] = json.loads(d["spec_json"])
            d["lint_report"] = json.loads(d["lint_report_json"] or "[]")
        return d

    def list_workflow_definitions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM workflow_definition_v1"
            " ORDER BY definition_id, version").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["spec"] = json.loads(d["spec_json"])
            d["lint_report"] = json.loads(d["lint_report_json"] or "[]")
            out.append(d)
        return out

    def update_workflow_definition(self, definition_id: str, version: int,
                                   *, spec: dict[str, Any] | None = None,
                                   name: str | None = None,
                                   status: str | None = None,
                                   lint_report: list | None = None,
                                   published: bool = False
                                   ) -> dict[str, Any]:
        sets, vals = [], []
        if spec is not None:
            spec_json = json.dumps(spec, sort_keys=True, ensure_ascii=False)
            sets += ["spec_json=?", "spec_hash=?"]
            vals += [spec_json,
                     hashlib.sha256(spec_json.encode()).hexdigest()]
        if name is not None:
            sets.append("name=?"); vals.append(name)
        if status is not None:
            sets.append("status=?"); vals.append(status)
        if lint_report is not None:
            sets.append("lint_report_json=?")
            vals.append(json.dumps(lint_report, ensure_ascii=False))
        if published:
            sets.append("published_at=?"); vals.append(_utcnow())
        sets.append("updated_at=?"); vals.append(_utcnow())
        n = self._conn.execute(
            f"UPDATE workflow_definition_v1 SET {', '.join(sets)}"
            " WHERE definition_id=? AND version=?",
            (*vals, definition_id, version))
        if n.rowcount != 1:
            raise StoreError(
                f"workflow 定义不存在: {definition_id}@v{version}")
        self._conn.commit()
        return self.get_workflow_definition(definition_id, version)

    def upsert_node_execution(self, run_id: str, node_id: str, *,
                              node_type: str, status: str,
                              input_data: dict | None = None,
                              output_data: dict | None = None,
                              error: str = "",
                              inc_attempt: bool = False) -> None:
        row = self._conn.execute(
            "SELECT exec_id, attempts FROM workflow_node_execution_v1"
            " WHERE run_id=? AND node_id=?",
            (run_id, node_id)).fetchone()
        now = _utcnow()
        if row is None:
            self._conn.execute(
                "INSERT INTO workflow_node_execution_v1 (run_id, node_id,"
                " node_type, status, input_json, output_json, error,"
                " attempts, started_at, ended_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, node_id, node_type, status,
                 json.dumps(input_data or {}, ensure_ascii=False),
                 json.dumps(output_data or {}, ensure_ascii=False),
                 error, 1,
                 now, now if status in ("succeeded", "failed", "skipped")
                 else None))
        else:
            attempts = row["attempts"] + (1 if inc_attempt else 0)
            self._conn.execute(
                "UPDATE workflow_node_execution_v1 SET status=?,"
                " node_type=?, output_json=?, error=?, attempts=?,"
                " ended_at=? WHERE run_id=? AND node_id=?",
                (status, node_type,
                 json.dumps(output_data or {}, ensure_ascii=False),
                 error, attempts,
                 now if status in ("succeeded", "failed", "skipped",
                                   "waiting_approval") else None,
                 run_id, node_id))
        self._conn.commit()

    def list_node_executions(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM workflow_node_execution_v1 WHERE run_id=?"
            " ORDER BY exec_id", (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["input"] = json.loads(d["input_json"] or "{}")
            d["output"] = json.loads(d["output_json"] or "{}")
            out.append(d)
        return out

    def insert_dead_letter(self, run_id: str, node_id: str, *,
                           reason: str,
                           payload: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO workflow_dead_letter_v1 (run_id, node_id, reason,"
            " payload_json, created_at) VALUES (?,?,?,?,?)",
            (run_id, node_id, reason,
             json.dumps(payload or {}, ensure_ascii=False), _utcnow()))
        self._conn.commit()

    def list_dead_letters(self, run_id: str | None = None
                          ) -> list[dict[str, Any]]:
        if run_id:
            rows = self._conn.execute(
                "SELECT * FROM workflow_dead_letter_v1 WHERE run_id=?"
                " ORDER BY dead_id", (run_id,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM workflow_dead_letter_v1"
                " ORDER BY dead_id").fetchall()
        return [dict(r) for r in rows]

    def list_review_tasks_active(self, *, limit: int = 5000
                                 ) -> list[dict[str, Any]]:
        """活动审核任务：排除已失效队列版本（历史行保留，不删除）。"""
        invalid = self._invalid_queue_versions()
        tasks = self.list_review_tasks(limit=limit)
        return [t for t in tasks if t["queue_version"] not in invalid]

    def review_task_stats(self) -> dict[str, int]:
        """active/invalid/total 分开统计（失效 V1 不阻断 V2）。"""
        invalid = self._invalid_queue_versions()
        active = invalid_n = 0
        for t in self.list_review_tasks():
            if t["queue_version"] in invalid:
                invalid_n += 1
            else:
                active += 1
        return {"active": active, "invalid": invalid_n,
                "total": active + invalid_n}

    # ---------- training run supersession（追加式，不改历史行） ----------

    def supersede_training_run(self, run_id: str, *, reason: str,
                                 superseded_by: str = "",
                                 git_commit: str = "") -> None:
        """GLTC D2：追加式标记 legacy/superseded（历史 run 行不改不删）。

        幂等：已标记的 run 重复调用不新增（UNIQUE(run_id) 兼做保护）。
        """
        if self.is_training_run_superseded(run_id):
            return
        self._conn.execute(
            "INSERT INTO training_run_supersession_v1"
            " (run_id, reason, superseded_by, git_commit, created_at)"
            " VALUES (?,?,?,?,?)",
            (run_id, reason, superseded_by, git_commit, _utcnow()))
        self._conn.commit()

    def is_training_run_superseded(self, run_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM training_run_supersession_v1 WHERE run_id=?",
            (run_id,)).fetchone()
        return row is not None

    def list_training_run_supersessions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM training_run_supersession_v1"
            " ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # ---------- 资源租约（GLTC Task 1/7：heavy 并发 1，MPS/MLX 互斥） ----------

    _HEAVY_RESOURCES = ("mps", "mlx")

    def acquire_resource_lease(self, *, run_id: str, resource: str,
                               mode: str = "exclusive") -> None:
        """获取租约：heavy 资源全局并发上限 1；mps/mlx 互斥（含同 run）。"""
        if resource in self._HEAVY_RESOURCES:
            active = self._conn.execute(
                "SELECT run_id, resource FROM resource_lease_v1"
                " WHERE released_at IS NULL").fetchall()
            for row in active:
                if row["resource"] == resource:
                    raise StoreError(
                        f"heavy 租约冲突：{resource} 已被 "
                        f"{row['run_id']} 持有（并发上限 1）")
                if row["resource"] in self._HEAVY_RESOURCES:
                    raise StoreError(
                        f"MPS/MLX 互斥：{row['resource']} 已被 "
                        f"{row['run_id']} 持有，不得再持有 {resource}")
        self._conn.execute(
            "INSERT INTO resource_lease_v1"
            " (run_id, resource, mode, acquired_at) VALUES (?,?,?,?)",
            (run_id, resource, mode, _utcnow()))
        self._conn.commit()

    def release_resource_lease(self, *, run_id: str,
                               resource: str) -> None:
        """释放租约（safe-stop 证据链之一：确认退出后才释放）。"""
        cur = self._conn.execute(
            "UPDATE resource_lease_v1 SET released_at=?"
            " WHERE run_id=? AND resource=? AND released_at IS NULL",
            (_utcnow(), run_id, resource))
        self._conn.commit()
        if cur.rowcount == 0:
            raise StoreError(f"无活动租约可释放: {run_id}/{resource}")

    def list_active_leases(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM resource_lease_v1"
            " WHERE released_at IS NULL ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # ---------- 旧模型登记（GLTC Task 2：追加式不可变账本） ----------

    def register_legacy_model(self, *, model_id: str, path: str,
                              status: str, weights_json: str = "[]",
                              git_commit: str = "") -> None:
        self._conn.execute(
            "INSERT INTO legacy_model_registry_v1"
            " (model_id, path, status, weights_json, git_commit,"
            " registered_at) VALUES (?,?,?,?,?,?)",
            (model_id, path, status, weights_json, git_commit, _utcnow()))
        self._conn.commit()

    def list_legacy_models(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM legacy_model_registry_v1"
            " ORDER BY model_id").fetchall()
        return [dict(r) for r in rows]

    # ---------- training_run_v2 / 结构化事件（GLTC Task 7） ----------

    def create_training_run_v2(self, run_id: str, *, lane: str,
                               plan_id: str = "", status: str = "QUEUED",
                               lease_json: str = "[]",
                               attempt: int = 1) -> None:
        self._conn.execute(
            "INSERT INTO training_run_v2 (run_id, plan_id, lane, status,"
            " lease_json, attempt, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (run_id, plan_id, lane, status, lease_json, attempt,
             _utcnow(), _utcnow()))
        self._conn.commit()

    def update_training_run_v2(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "pid", "heartbeat_at", "attempt",
                   "lease_json", "worker", "job_id"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sets = ", ".join(f"{c}=?" for c in cols)
        self._conn.execute(
            f"UPDATE training_run_v2 SET {sets}, updated_at=?"
            " WHERE run_id=?",
            (*[fields[c] for c in cols], _utcnow(), run_id))
        self._conn.commit()

    def get_training_run_v2(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM training_run_v2 WHERE run_id=?",
            (run_id,)).fetchone()
        return dict(row) if row else None

    def list_training_runs_v2(self, *, statuses: tuple[str, ...] | None = None
                              ) -> list[dict[str, Any]]:
        if statuses:
            marks = ",".join("?" * len(statuses))
            rows = self._conn.execute(
                f"SELECT * FROM training_run_v2 WHERE status IN ({marks})"
                " ORDER BY created_at", statuses).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM training_run_v2 ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def append_training_event(self, run_id: str, kind: str,
                              payload: dict[str, Any] | None = None
                              ) -> None:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM training_event_v1"
            " WHERE run_id=?", (run_id,)).fetchone()
        self._conn.execute(
            "INSERT INTO training_event_v1"
            " (run_id, seq, kind, payload_json, created_at)"
            " VALUES (?,?,?,?,?)",
            (run_id, row["next"], kind,
             json.dumps(payload or {}, ensure_ascii=False), _utcnow()))
        self._conn.commit()

    def list_training_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM training_event_v1 WHERE run_id=?"
            " ORDER BY seq", (run_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- backup ----------

    def backup(self, dest: Path | str) -> dict[str, Any]:
        """使用 sqlite3 backup API 生成一致性备份，并对备份做 integrity_check。"""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest))
        try:
            self._conn.backup(target)
            ok = target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            target.close()
        return {"ok": bool(ok), "path": str(dest), "created_at": _utcnow()}

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
