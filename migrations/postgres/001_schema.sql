-- ISSUE-016：PostgreSQL 业务 schema（与 migrations/sqlite/001_schema.sql 语义同构）
-- 八张业务表 + append-only 触发器 + 索引 + schema_version

CREATE TABLE IF NOT EXISTS schema_version(
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sku_catalog(
    canonical_id TEXT PRIMARY KEY,
    display TEXT,
    brand TEXT,
    flavor TEXT,
    sugar TEXT,
    volume_ml INTEGER,
    packaging_version TEXT,
    barcode TEXT,
    aliases TEXT,
    attrs_json JSONB,
    kb_missing INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS asset(
    asset_id TEXT PRIMARY KEY,
    sha256 TEXT,
    kind TEXT,
    uri TEXT,
    bucket TEXT,
    width INTEGER,
    height INTEGER,
    source TEXT,
    ingested_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS asset_sha_idx ON asset(sha256);

CREATE TABLE IF NOT EXISTS annotation(
    ann_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES asset(asset_id),
    x DOUBLE PRECISION,
    y DOUBLE PRECISION,
    box JSONB,
    canonical_id TEXT REFERENCES sku_catalog(canonical_id),
    source TEXT,
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    provenance_json JSONB,
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now())
);
CREATE INDEX IF NOT EXISTS annotation_asset_idx ON annotation(asset_id);

CREATE TABLE IF NOT EXISTS auto_label(
    label_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES asset(asset_id),
    box JSONB,
    canonical_id TEXT,
    method TEXT,
    confidence TEXT,
    evidence_json JSONB,
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now())
);
CREATE INDEX IF NOT EXISTS auto_label_asset_idx ON auto_label(asset_id);

CREATE TABLE IF NOT EXISTS review_event(
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    status TEXT NOT NULL,
    before_json JSONB,
    after_json JSONB,
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now())
);
CREATE INDEX IF NOT EXISTS review_event_asset_idx ON review_event(asset_id);

CREATE TABLE IF NOT EXISTS dataset_version(
    dv_id TEXT PRIMARY KEY,
    split_info TEXT,
    filter_query TEXT,
    n_images INTEGER,
    n_labels INTEGER,
    source_label_ids TEXT,
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now())
);

CREATE TABLE IF NOT EXISTS model_version(
    mv_id TEXT PRIMARY KEY,
    task TEXT,
    code_hash TEXT,
    data_version TEXT,
    hyperparams JSONB,
    seed INTEGER,
    metrics_json JSONB,
    weight_uri TEXT,
    weight_sha TEXT,
    status TEXT NOT NULL CHECK (status IN ('candidate','trained','production','retired')),
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now())
);
CREATE INDEX IF NOT EXISTS model_version_status_idx ON model_version(status);

CREATE TABLE IF NOT EXISTS recognition_run(
    run_id TEXT PRIMARY KEY,
    asset_id TEXT,
    model_versions TEXT,
    knowledge_version TEXT,
    prompt_version TEXT,
    decisions_json JSONB,
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now())
);

-- RA-006：不可变模型 bundle 治理（detector+classifier+类别映射+阈值作为一个发布/回滚单元）
CREATE TABLE IF NOT EXISTS model_bundle(
    bundle_id TEXT PRIMARY KEY,
    manifest_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'created' CHECK(status IN ('created','production','retired')),
    previous_bundle_id TEXT,
    published_at DOUBLE PRECISION,
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now())
);

-- RA-018：webhook 事件幂等去重表（唯一事件键 + 业务写入同事务）
CREATE TABLE IF NOT EXISTS webhook_event(
    event_key TEXT PRIMARY KEY,
    action TEXT,
    payload_sha TEXT,
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now())
);

-- RA-017：审计 outbox —— recognition_run 写失败时完整事件落此表，后台重放幂等补写，绝不静默丢审计
CREATE TABLE IF NOT EXISTS audit_outbox(
    run_id TEXT PRIMARY KEY,
    asset_id TEXT,
    payload_json JSONB NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL DEFAULT extract(epoch from now()),
    last_try DOUBLE PRECISION
);

-- append-only 红线：annotation / auto_label / review_event 禁止 UPDATE/DELETE
CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ann_no_upd ON annotation;
CREATE TRIGGER ann_no_upd BEFORE UPDATE ON annotation FOR EACH ROW EXECUTE FUNCTION reject_mutation();
DROP TRIGGER IF EXISTS ann_no_del ON annotation;
CREATE TRIGGER ann_no_del BEFORE DELETE ON annotation FOR EACH ROW EXECUTE FUNCTION reject_mutation();
DROP TRIGGER IF EXISTS al_no_upd ON auto_label;
CREATE TRIGGER al_no_upd BEFORE UPDATE ON auto_label FOR EACH ROW EXECUTE FUNCTION reject_mutation();
DROP TRIGGER IF EXISTS al_no_del ON auto_label;
CREATE TRIGGER al_no_del BEFORE DELETE ON auto_label FOR EACH ROW EXECUTE FUNCTION reject_mutation();
DROP TRIGGER IF EXISTS re_no_upd ON review_event;
CREATE TRIGGER re_no_upd BEFORE UPDATE ON review_event FOR EACH ROW EXECUTE FUNCTION reject_mutation();
DROP TRIGGER IF EXISTS re_no_del ON review_event;
CREATE TRIGGER re_no_del BEFORE DELETE ON review_event FOR EACH ROW EXECUTE FUNCTION reject_mutation();
DROP TRIGGER IF EXISTS wh_no_upd ON webhook_event;
CREATE TRIGGER wh_no_upd BEFORE UPDATE ON webhook_event FOR EACH ROW EXECUTE FUNCTION reject_mutation();
DROP TRIGGER IF EXISTS wh_no_del ON webhook_event;
CREATE TRIGGER wh_no_del BEFORE DELETE ON webhook_event FOR EACH ROW EXECUTE FUNCTION reject_mutation();

INSERT INTO schema_version(version) VALUES (1) ON CONFLICT DO NOTHING;
