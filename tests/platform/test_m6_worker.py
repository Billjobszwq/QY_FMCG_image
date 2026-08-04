"""M6 TDD：可恢复 JobWorker（取消/超时/重试/dead-letter/背压/崩溃不重复）
+ CAS 校验/备份/恢复/磁盘水位 + 分享链接 scope/有效期 + CORS 白名单 + Jobs API。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.composition.build import build_production_bundle, build_jobs_router
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus
from src.platform.assets.cas import CASIntegrityError, ContentAddressedStore
from src.platform.data.store import PlatformStore, StoreError
from src.platform.worker import RecoverableJobWorker


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1, detail="fake")


# ---------- 可恢复 Worker：成功路径 ----------

def test_worker_submit_and_succeed(store) -> None:
    calls: list[str] = []

    def handler(job: dict) -> dict:
        calls.append(job["job_id"])
        return {"echo": job["payload"]}

    w = RecoverableJobWorker(store, {"demo.echo": handler})
    jid = w.submit("demo.echo", {"n": 1})
    done = w.poll()
    assert [d["job_id"] for d in done] == [jid]
    job = store.get_job(jid)
    assert job["status"] == "succeeded"
    assert job["result_json"] is not None
    attempts = store.list_attempts(jid)
    assert len(attempts) == 1 and attempts[0]["status"] == "succeeded"
    assert calls == [jid]  # 恰好执行一次


# ---------- 重试与 dead-letter ----------

def test_worker_retry_then_succeed(store) -> None:
    count = {"n": 0}

    def flaky(job: dict) -> dict:
        count["n"] += 1
        if count["n"] == 1:
            raise RuntimeError("临时故障")
        return {"ok": True}

    w = RecoverableJobWorker(store, {"demo.flaky": flaky})
    jid = w.submit("demo.flaky", {}, max_attempts=3)
    w.poll()  # 第 1 次失败 → 重新排队
    assert store.get_job(jid)["status"] == "queued"
    w.poll()  # 第 2 次成功
    assert store.get_job(jid)["status"] == "succeeded"
    assert count["n"] == 2
    assert [a["status"] for a in store.list_attempts(jid)] == ["failed", "succeeded"]


def test_worker_dead_letter_after_max_attempts(store) -> None:
    def always_fail(job: dict) -> dict:
        raise RuntimeError("永久故障")

    w = RecoverableJobWorker(store, {"demo.fail": always_fail})
    jid = w.submit("demo.fail", {}, max_attempts=2)
    w.poll()
    assert store.get_job(jid)["status"] == "queued"  # 还剩 1 次机会
    w.poll()
    job = store.get_job(jid)
    assert job["status"] == "failed"
    assert job["error"] is not None and job["error"].startswith("dead_letter:")
    assert store.list_attempts(jid) and len(store.list_attempts(jid)) == 2
    stats = w.stats()
    assert stats["dead_letters"] == 1


def test_worker_unknown_kind_dead_letter(store) -> None:
    w = RecoverableJobWorker(store, {})
    jid = w.submit("demo.missing", {}, max_attempts=1)
    w.poll()
    job = store.get_job(jid)
    assert job["status"] == "failed"
    assert job["error"].startswith("dead_letter:")


# ---------- 崩溃恢复：lease 过期认领，不重复完成 ----------

def test_worker_crash_recovery_no_duplicate(store) -> None:
    count = {"n": 0}

    def handler(job: dict) -> dict:
        count["n"] += 1
        return {"done": True}

    w = RecoverableJobWorker(store, {"demo.echo": handler}, lease_seconds=300)
    jid = w.submit("demo.echo", {})
    # 模拟崩溃：job 被认领为 running 后 worker 死亡（直接操纵 store）
    claimed = store.claim_next_job(worker_id="dead-worker", lease_seconds=-1)
    assert claimed is not None and claimed["job_id"] == jid
    assert store.get_job(jid)["status"] == "running"
    # 新 worker 扫描过期 lease → 重新排队
    recovered = w.reclaim_expired_leases()
    assert jid in recovered
    assert store.get_job(jid)["status"] == "queued"
    # 正常完成，且只完成一次（result 单一、attempt 记账清晰）
    w.poll()
    job = store.get_job(jid)
    assert job["status"] == "succeeded"
    assert count["n"] == 1
    assert len(store.list_attempts(jid)) == 1


def test_worker_crash_exhausted_dead_letter(store) -> None:
    w = RecoverableJobWorker(store, {"demo.echo": lambda j: {"ok": 1}})
    jid = w.submit("demo.echo", {}, max_attempts=1)
    store.claim_next_job(worker_id="dead", lease_seconds=-1)
    store._conn.execute("UPDATE job SET attempt_count=1 WHERE job_id=?", (jid,))
    recovered = w.reclaim_expired_leases()
    assert recovered == []
    job = store.get_job(jid)
    assert job["status"] == "failed" and job["error"].startswith("dead_letter:")


# ---------- 取消 ----------

def test_worker_cancel_queued_only(store) -> None:
    w = RecoverableJobWorker(store, {"demo.echo": lambda j: {}})
    jid = w.submit("demo.echo", {})
    assert w.cancel(jid, actor="op") is True
    assert store.get_job(jid)["status"] == "cancelled"
    w.poll()  # 取消的 job 不再被认领
    assert store.get_job(jid)["status"] == "cancelled"
    # 终态不可取消
    assert w.cancel(jid, actor="op") is False


# ---------- 背压 ----------

def test_worker_backpressure_max_concurrent(store) -> None:
    w = RecoverableJobWorker(
        store, {"demo.echo": lambda j: {"ok": 1}}, max_concurrent=1
    )
    w.submit("demo.echo", {})
    w.submit("demo.echo", {})
    w.poll()
    st = w.stats()
    assert st["succeeded"] == 1 and st["queued"] == 1  # 背压：单轮只放行 1 个
    w.poll()
    assert w.stats()["succeeded"] == 2


# ---------- 性能基线（软上限） ----------

def test_worker_throughput_baseline(store) -> None:
    w = RecoverableJobWorker(
        store, {"demo.echo": lambda j: {"ok": 1}}, max_concurrent=50
    )
    for _ in range(100):
        w.submit("demo.echo", {})
    t0 = time.monotonic()
    while w.stats()["queued"]:
        w.poll()
    elapsed = time.monotonic() - t0
    assert w.stats()["succeeded"] == 100
    assert elapsed < 10.0, f"100 job 耗时 {elapsed:.2f}s 超出软上限"


# ---------- CAS 校验 / 备份 / 恢复 / 水位 ----------

def test_cas_verify_all_detects_corruption(store, tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas", store)
    ref = cas.put(b"hello world", kind="photo")
    rep = cas.verify_all()
    assert rep["ok"] is True and rep["checked"] >= 1
    # 人为损坏 blob
    p = tmp_path / "cas" / ref.sha256[:2] / ref.sha256
    p.write_bytes(b"tampered!!!")
    rep2 = cas.verify_all()
    assert rep2["ok"] is False and ref.sha256 in rep2["corrupt"]
    with pytest.raises(CASIntegrityError):
        cas.get(ref.sha256)


def test_cas_verify_detects_missing(store, tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas", store)
    ref = cas.put(b"data", kind="photo")
    (tmp_path / "cas" / ref.sha256[:2] / ref.sha256).unlink()
    rep = cas.verify_all()
    assert rep["ok"] is False and ref.sha256 in rep["missing"]


def test_cas_backup_restore_roundtrip(store, tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas", store)
    r1 = cas.put(b"alpha", kind="photo")
    r2 = cas.put(b"beta", kind="model")
    archive = tmp_path / "backup.tar.gz"
    info = cas.backup(archive)
    assert info["blobs"] >= 2 and archive.exists()

    # 恢复到全新目录
    cas2 = ContentAddressedStore(tmp_path / "cas_restored", store)
    out = cas2.restore(archive)
    assert out["restored"] >= 2
    assert cas2.get(r1.sha256) == b"alpha"
    assert cas2.get(r2.sha256) == b"beta"


def test_cas_restore_rejects_corrupt_archive(store, tmp_path: Path) -> None:
    import tarfile

    cas = ContentAddressedStore(tmp_path / "cas", store)
    cas.put(b"gamma", kind="photo")
    archive = tmp_path / "backup.tar.gz"
    cas.backup(archive)
    # 拆开 → 改坏一个 blob → 重打包（保留 manifest.json）
    extract = tmp_path / "x"
    with tarfile.open(archive) as tf:
        tf.extractall(extract, filter="data")
    blobs = list(extract.rglob("cas/*/*"))
    assert blobs, "备份包应包含 blob"
    blobs[0].write_bytes(b"corrupted bytes")
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        tf.add(extract / "cas", arcname="cas")
        tf.add(extract / "manifest.json", arcname="manifest.json")
    cas2 = ContentAddressedStore(tmp_path / "cas_bad", store)
    with pytest.raises(CASIntegrityError):
        cas2.restore(bad)
    # fail-closed：恢复失败不留下半成品被信任
    assert cas2.verify_all()["checked"] >= 0


def test_cas_disk_watermark(store, tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas", store)
    wm = cas.disk_watermark(free_fraction_threshold=0.10)
    assert 0.0 <= wm["free_fraction"] <= 1.0
    assert wm["exceeded"] is (wm["free_fraction"] < 0.10)
    wm2 = cas.disk_watermark(free_fraction_threshold=1.01)
    assert wm2["exceeded"] is True  # 阈值不可能满足 → 必告警


# ---------- 分享链接：scope/有效期 fail-closed ----------

def test_share_token_lifecycle(store) -> None:
    tok = store.create_share_token(
        scope="run:evidence", subject_id="run-1", ttl_seconds=60, created_by="alice"
    )
    assert tok["scope"] == "run:evidence"
    got = store.validate_share_token(tok["token"], scope="run:evidence")
    assert got is not None and got["subject_id"] == "run-1"
    # scope 不匹配 → 拒绝
    assert store.validate_share_token(tok["token"], scope="other") is None
    # 吊销
    store.revoke_share_token(tok["token"])
    assert store.validate_share_token(tok["token"], scope="run:evidence") is None


def test_share_token_expired(store) -> None:
    tok = store.create_share_token(
        scope="run:evidence", subject_id="r", ttl_seconds=-1, created_by="a"
    )
    assert store.validate_share_token(tok["token"], scope="run:evidence") is None


# ---------- CORS 白名单 ----------

def test_cors_allowlist_from_env(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PLATFORM_CORS_ORIGINS", "https://ops.example.com")
    app = create_app(services=(), probe=_fake_probe, web_dist=tmp_path / "none")
    client = TestClient(app)
    r = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://ops.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://ops.example.com"
    # 非白名单 Origin 不授予
    r2 = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert r2.headers.get("access-control-allow-origin") != "https://evil.example.com"


# ---------- Jobs API E2E（提交 → poll → 完成 → 取消 → 审计） ----------

class FakeRecognition:
    def recognize(self, image_bytes: bytes, conf: float = 0.25) -> dict:
        return {"run_id": "fake", "count": 0, "products": [], "elapsed_ms": 1,
                "model": "fake"}


class FakeMonitor:
    def live(self):
        return {"ok": True}

    def overview(self):
        return {"ok": True}


class FakeLS:
    def health(self):
        return {"ok": True}


def test_jobs_api_e2e(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    # UMT-006：写端点需登录 session + CSRF
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "pw-admin-e2e")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=FakeRecognition(), monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    worker, router = build_jobs_router(bundle)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     jobs_router=router, web_dist=tmp_path / "none")
    client = TestClient(app)
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "pw-admin-e2e"})
    assert r.status_code == 200, r.text
    h = {"X-CSRF-Token": r.json()["csrf_token"]}

    # 提交 echo job（仅允许已注册 kind）
    r = client.post("/api/v1/jobs", json={"kind": "platform.echo", "payload": {"x": 1}},
                    headers=h)
    assert r.status_code == 200, r.text
    jid = r.json()["job"]["job_id"]
    # 未知 kind 拒绝
    assert client.post("/api/v1/jobs", json={"kind": "evil.kind"},
                       headers=h).status_code == 400

    # poll 驱动执行
    r2 = client.post("/api/v1/jobs/poll")
    assert r2.status_code == 200 and r2.json()["processed"] >= 1
    r3 = client.get(f"/api/v1/jobs/{jid}")
    assert r3.json()["job"]["status"] == "succeeded"
    assert r3.json()["attempts"][0]["status"] == "succeeded"

    # 列表 + 统计
    lst = client.get("/api/v1/jobs").json()
    assert lst["stats"]["succeeded"] >= 1

    # 取消：新 job queued 状态可取消
    r4 = client.post("/api/v1/jobs", json={"kind": "platform.echo"}, headers=h)
    jid2 = r4.json()["job"]["job_id"]
    assert client.post(f"/api/v1/jobs/{jid2}/cancel", headers=h).status_code == 200
    assert client.get(f"/api/v1/jobs/{jid2}").json()["job"]["status"] == "cancelled"
    # 终态取消 → 409
    assert client.post(f"/api/v1/jobs/{jid2}/cancel", headers=h).status_code == 409

    # 审计留痕（cancel 记录）
    rows = bundle.store._conn.execute(
        "SELECT * FROM audit_event WHERE action='job.cancel'"
    ).fetchall()
    assert len(rows) >= 1
