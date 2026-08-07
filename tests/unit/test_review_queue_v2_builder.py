"""PLC3-003 红测试：review_queue_diag_v2 构建器（correct ID→SHA by lookup）。

设计保留（任务书§七）：前 200 ID double、seed=20260804 盲抽 50 blind、
250 任务、226 唯一照片、24 同图对照；但 SHA 必须按 photo_id 从权威
manifest 查询，禁止位置 zip；发布前门禁任一失败即不发布。
"""
import hashlib
import json

import pytest

from src.review import review_queue_v2 as RQ2


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture()
def env(tmp_path):
    """合成协议（50 ID）+ manifest + blobs。"""
    n = 50
    pids = [f"{i:05d}" for i in range(n)]
    manifest = {}
    blobs = tmp_path / "blobs"
    for pid in pids:
        sha = _sha(pid)
        manifest[pid] = {"status": "clean", "sha256": sha, "width": 100,
                         "height": 200, "filename": f"{pid}.jpg"}
        b = blobs / sha[:2] / sha
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_bytes(pid.encode())  # 内容即 pid → 现场 SHA 一致
    mp = tmp_path / "clean_manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    protocol = {"frozen": True, "role": "diagnostic_v1", "seed": 20260804,
                "photo_ids": sorted(pids),
                "sha256": sorted(_sha(p) for p in pids)}
    pp = tmp_path / "diagnostic_v1.json"
    pp.write_text(json.dumps(protocol), encoding="utf-8")
    return {"tmp": tmp_path, "manifest": mp, "blobs": blobs,
            "protocol": pp, "pids": pids}


def _build(env, n_double=20, n_blind=5, verify_blobs=True):
    return RQ2.build_v2(
        protocol_path=env["protocol"], manifest_path=env["manifest"],
        blobs_dir=env["blobs"], seed=20260804,
        n_double=n_double, n_blind=n_blind,
        verify_blobs=verify_blobs, git_commit="test123")


def test_v2_pairs_all_correct(env):
    q, audit, gates = _build(env)
    assert gates["ok"] is True
    assert audit["pairing_correct"] == 25
    items = q["items"]
    manifest = json.loads(env["manifest"].read_text())
    for it in items:
        assert manifest[it["photo_id"]]["sha256"] == it["sha256"]


def test_v2_design_counts_and_overlap(env):
    q, audit, gates = _build(env)
    items = q["items"]
    assert len(items) == 25  # n_double + n_blind
    pids = [it["photo_id"] for it in items]
    unique = set(pids)
    assert audit["n_tasks"] == 25
    assert audit["n_unique_photos"] == len(unique)
    assert audit["n_overlap_photos"] == len(pids) - len(unique)
    modes = [it["review_mode"] for it in items]
    assert modes.count("double_review") == 20
    assert modes.count("blind_manual") == 5


def test_v2_double_uses_first_n_ids(env):
    q, audit, gates = _build(env)
    double_ids = [it["photo_id"] for it in q["items"]
                  if it["review_mode"] == "double_review"]
    proto = json.loads(env["protocol"].read_text())
    assert double_ids == proto["photo_ids"][:20]  # 协议顺序前 20


def test_v2_seed_deterministic(env):
    q1, _, _ = _build(env)
    q2, _, _ = _build(env)
    assert q1["items"] == q2["items"]  # 固定 seed 可复现


def test_v2_gate_fails_when_blob_missing(env):
    """发布门禁：任一原图缺失 → fail-closed 不发布。"""
    manifest = json.loads(env["manifest"].read_text())
    victim = env["pids"][0]
    sha = manifest[victim]["sha256"]
    (env["blobs"] / sha[:2] / sha).unlink()
    q, audit, gates = _build(env)
    assert gates["ok"] is False
    assert gates["files_present"] < gates["n_unique_photos"]


def test_v2_gate_fails_when_sha_mismatch(env):
    """现场 SHA 与 manifest 不一致 → fail-closed。"""
    manifest = json.loads(env["manifest"].read_text())
    victim = env["pids"][1]
    sha = manifest[victim]["sha256"]
    (env["blobs"] / sha[:2] / sha).write_bytes(b"tampered")
    q, audit, gates = _build(env)
    assert gates["ok"] is False
    assert gates["sha_verified"] < gates["n_unique_photos"]


def test_v2_mapping_gate_500_of_500(env):
    q, audit, gates = _build(env)
    assert gates["mapping_recovered"] == len(env["pids"])
    assert gates["mapping_total"] == len(env["pids"])


def test_v2_audit_fields_complete(env):
    q, audit, gates = _build(env)
    for key in ("builder_version", "builder_hash", "git_commit",
                "protocol_hash", "manifest_hash", "seed", "mapping_hash",
                "tasks_hash", "n_tasks", "n_unique_photos",
                "n_overlap_photos", "sha_verification", "distribution",
                "errors", "supersedes"):
        assert key in audit, f"审计缺字段: {key}"
    assert audit["errors"] == []
    assert audit["supersedes"] == "rq_v1"


def test_v2_write_refuses_overwrite(env, tmp_path):
    q, audit, gates = _build(env)
    out = tmp_path / "rq_v2.json"
    RQ2.write_v2(q, audit, out)
    with pytest.raises(FileExistsError):
        RQ2.write_v2(q, audit, out)


def test_v2_rejects_positional_zip_protocol_shape(env):
    """构建器不得依赖位置 zip：把协议 sha256 数组打乱后构建结果仍正确。"""
    proto = json.loads(env["protocol"].read_text())
    import random as _r
    shas = proto["sha256"][:]
    _r.Random(7).shuffle(shas)
    proto["sha256"] = shas
    env["protocol"].write_text(json.dumps(proto), encoding="utf-8")
    q, audit, gates = _build(env)
    assert gates["ok"] is True  # 只按 ID 查询，不受数组顺序影响
