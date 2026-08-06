"""Task 13（VLM-013）：级联计费账本 + 队列 SLA。

覆盖：
- 每个 node attempt 账本字段完整（capability/model/version/photo/region/token/
  compute_ms/tier/cold_start/cache_hit/rate_card_version/resource_cost/billed_cost）；
- 相同幂等键重试不得重复计费；
- Job 双时间戳：attempt_timeout_at（单次尝试超时）与 queue_deadline_at（业务 SLA）分离；
- 单次 attempt timeout ≠ 任务过期；queue deadline 到期 → expired + 审计；
- 追加式迁移可重复执行、旧 usage_event 保留、不 drop/rename 历史表。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.modules.fmcg.cascade.billing import (
    RATE_CARD_VERSION,
    CascadeBillingError,
    bill_attempt,
    billing_total,
    list_billing,
)
from src.platform.data.store import JOB_STATUSES, PlatformStore, StoreError
from src.platform.jobs import allowed_transitions, transition


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _ts(dt: datetime) -> str:
    return dt.isoformat()


# ---------- 账本字段完整性 ----------

def test_bill_attempt_records_full_ledger_fields(store) -> None:
    store.create_run(run_id="run-b1", graph_name="fmcg_cascade_s0_s5", graph_version="1")
    entry = bill_attempt(
        store,
        run_id="run-b1",
        billing_key="classify_fast#r1",
        capability="cap.classify.resnet50",
        model="resnet50",
        model_version="v7.1",
        tier="standard",
        photos=1,
        regions=3,
        tokens=0,
        compute_ms=42.5,
        cold_start=False,
        cache_hit=True,
    )
    for field in (
        "capability", "model", "model_version", "photos", "regions", "tokens",
        "compute_ms", "tier", "cold_start", "cache_hit", "rate_card_version",
        "resource_cost", "billed_cost",
    ):
        assert field in entry, f"账本缺少字段 {field}"
    assert entry["rate_card_version"] == RATE_CARD_VERSION
    assert entry["capability"] == "cap.classify.resnet50"
    assert entry["billed_cost"] >= 0
    rows = list_billing(store, run_id="run-b1")
    assert len(rows) == 1 and rows[0]["capability"] == "cap.classify.resnet50"


def test_bill_requires_existing_run(store) -> None:
    with pytest.raises(CascadeBillingError):
        bill_attempt(store, run_id="run-missing", billing_key="q#r1",
                     capability="cap.quality.v1", tier="fast")


# ---------- 幂等：相同 key 重试不得重复计费 ----------

def test_same_billing_key_not_billed_twice(store) -> None:
    store.create_run(run_id="run-b2", graph_name="g", graph_version="1")
    first = bill_attempt(store, run_id="run-b2", billing_key="segment#r1",
                         capability="cap.segment.sam", tier="deep", tokens=0)
    again = bill_attempt(store, run_id="run-b2", billing_key="segment#r1",
                         capability="cap.segment.sam", tier="deep", tokens=0)
    assert len(list_billing(store, run_id="run-b2")) == 1
    assert again["billed_cost"] == first["billed_cost"]
    # 不同 key 正常追加
    bill_attempt(store, run_id="run-b2", billing_key="segment#r2",
                 capability="cap.segment.sam", tier="deep", tokens=0)
    assert len(list_billing(store, run_id="run-b2")) == 2
    assert billing_total(store, run_id="run-b2")["entries"] == 2


# ---------- Job SLA 双时间戳 ----------

def test_job_has_attempt_timeout_and_queue_deadline(store) -> None:
    now = datetime.now(timezone.utc)
    job = store.create_job(
        job_id="job-sla-1", kind="cascade.recognize", payload={},
        attempt_timeout_at=_ts(now + timedelta(minutes=10)),
        queue_deadline_at=_ts(now + timedelta(hours=12)),
    )
    assert job["attempt_timeout_at"] is not None
    assert job["queue_deadline_at"] is not None
    # 单次 VLM/attempt timeout ≠ 任务过期：job 仍是可调度状态
    assert job["status"] == "queued"


def test_attempt_timeout_does_not_expire_task(store) -> None:
    past = _ts(datetime.now(timezone.utc) - timedelta(minutes=5))
    future = _ts(datetime.now(timezone.utc) + timedelta(hours=12))
    job = store.create_job(job_id="job-sla-2", kind="cascade.vlm",
                           attempt_timeout_at=past, queue_deadline_at=future)
    # attempt 超时只影响当次尝试，任务本身未过期
    assert job["status"] == "queued"
    assert job["queue_deadline_at"] == future


# ---------- queue deadline：到期转 expired + 审计 ----------

def test_expire_job_at_queue_deadline_writes_audit(store) -> None:
    past = _ts(datetime.now(timezone.utc) - timedelta(seconds=1))
    store.create_job(job_id="job-sla-3", kind="cascade.recognize",
                     queue_deadline_at=past)
    store.set_job_status("job-sla-3", "running")
    from src.platform.jobs import expire_job_at_deadline
    result = expire_job_at_deadline(store, "job-sla-3", actor="scheduler")
    assert result == "expired"
    job = store.get_job("job-sla-3")
    assert job["status"] == "expired"
    audit = [a for a in store.list_audit(subject_id="job-sla-3")
             if a["action"] == "job.queue_deadline_expired"]
    assert len(audit) == 1


def test_expire_job_before_deadline_is_noop(store) -> None:
    future = _ts(datetime.now(timezone.utc) + timedelta(hours=12))
    store.create_job(job_id="job-sla-4", kind="cascade.recognize",
                     queue_deadline_at=future)
    store.set_job_status("job-sla-4", "running")
    from src.platform.jobs import expire_job_at_deadline
    assert expire_job_at_deadline(store, "job-sla-4", actor="scheduler") is None
    assert store.get_job("job-sla-4")["status"] == "running"


def test_terminal_jobs_not_expired(store) -> None:
    past = _ts(datetime.now(timezone.utc) - timedelta(seconds=1))
    store.create_job(job_id="job-sla-5", kind="cascade.recognize",
                     queue_deadline_at=past)
    store.set_job_status("job-sla-5", "running")
    store.set_job_status("job-sla-5", "succeeded")
    from src.platform.jobs import expire_job_at_deadline
    assert expire_job_at_deadline(store, "job-sla-5", actor="scheduler") is None
    assert store.get_job("job-sla-5")["status"] == "succeeded"


def test_job_state_machine_allows_expired() -> None:
    assert "expired" in JOB_STATUSES
    assert "expired" in allowed_transitions("running")
    assert transition("running", "expired") == "expired"


# ---------- 追加式迁移：可重复执行、保留旧数据 ----------

def test_migration_is_repeatable_and_preserves_usage_event(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    s1 = PlatformStore(db)
    s1.create_run(run_id="run-old", graph_name="g", graph_version="1")
    s1.append_usage(capability="cap.legacy", run_id="run-old",
                    quantity=1.0, unit="call")
    s1.close()
    # 重复执行迁移（第二次打开）不应丢数据、不报错
    s2 = PlatformStore(db)
    rows = s2._conn.execute("SELECT * FROM usage_event").fetchall()
    assert len(rows) == 1  # 旧 usage_event 保留
    cols = {r[1] for r in s2._conn.execute("PRAGMA table_info(job)").fetchall()}
    assert "attempt_timeout_at" in cols and "queue_deadline_at" in cols
    # 历史表未被 drop/rename：graph_run/audit_event/evidence_bundle 仍在
    for t in ("graph_run", "audit_event", "evidence_bundle", "usage_event", "job"):
        assert s2._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone() is not None
    s2.close()
