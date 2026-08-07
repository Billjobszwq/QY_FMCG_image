"""PLC3-001 红测试：protocol photo_id ↔ sha256 canonical identity。

背景（P0，2026-08-07 现场复现）：diagnostic_v1.json 把 photo_ids 与 sha256
各自独立排序保存，build_review_queue.py 按数组位置 zip 配对，造成
2/500、队列 0/250 的 ID/SHA 错配。本测试锁定：

1. 独立排序数组按位置 zip 必须被检测为错配；
2. canonical 映射必须按 photo_id 从权威 manifest 查询；
3. 队列导入前逐条 actual_sha(photo_id)==declared_sha256，错一条 fail-closed；
4. 同 SHA 不同 photo_id 按 canonical asset 规则处理并保留别名证据；
5. 队列文件已存在不得覆盖。
"""
import hashlib
import json

import pytest

from src.data import photo_identity as PI


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _manifest(pairs: dict[str, str]) -> dict:
    """photo_id -> sha256 的 clean_manifest 形状。"""
    return {pid: {"status": "clean", "sha256": sha, "width": 100,
                  "height": 200, "filename": f"{pid}.jpg"}
            for pid, sha in pairs.items()}


# ---------- 1. 位置 zip 错配检测 ----------

def test_positional_zip_of_sorted_arrays_detected(tmp_path):
    """两个独立排序数组按位置 zip，绝大多数配对必须被 validate 判错。"""
    pids = [f"{i:04d}" for i in range(20)]
    shas = [_sha(p) for p in pids]
    manifest = _manifest(dict(zip(pids, shas)))
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")

    bad_pairs = list(zip(sorted(pids), sorted(shas)))  # 独立排序后位置 zip
    report = PI.validate_pairing(bad_pairs, manifest_path=mp)
    assert report["ok"] is False
    assert report["mismatches"] > 0


def test_correct_mapping_passes(tmp_path):
    pids = [f"{i:04d}" for i in range(20)]
    shas = [_sha(p) for p in pids]
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(_manifest(dict(zip(pids, shas)))), encoding="utf-8")
    pairs = [(p, _sha(p)) for p in pids]  # 按 ID 查询的正确配对
    report = PI.validate_pairing(pairs, manifest_path=mp)
    assert report["ok"] is True
    assert report["mismatches"] == 0


# ---------- 2. canonical mapping 按 ID 查询 ----------

def test_canonical_mapping_by_photo_id(tmp_path):
    pairs = {"111": _sha("111"), "222": _sha("222")}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(_manifest(pairs)), encoding="utf-8")
    got = PI.canonical_mapping(["222", "111"], manifest_path=mp)
    assert got == pairs


def test_canonical_mapping_missing_id_fail_closed(tmp_path):
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(_manifest({"111": _sha("111")})), encoding="utf-8")
    with pytest.raises(PI.IdentityError):
        PI.canonical_mapping(["111", "999"], manifest_path=mp)


# ---------- 3. 队列导入逐条校验，错一条 fail-closed ----------

def test_queue_validation_rejects_single_mismatch(tmp_path):
    pairs = {"111": _sha("111"), "222": _sha("222")}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(_manifest(pairs)), encoding="utf-8")
    items = [
        {"photo_id": "111", "sha256": _sha("111")},
        {"photo_id": "222", "sha256": _sha("WRONG")},  # 仅一条错
    ]
    report = PI.validate_queue_items(items, manifest_path=mp)
    assert report["ok"] is False
    assert report["checked"] == 2
    assert report["correct"] == 1
    # fail-closed：不允许部分导入
    assert report["allow_partial_import"] is False


def test_queue_validation_all_correct(tmp_path):
    pairs = {"111": _sha("111"), "222": _sha("222")}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(_manifest(pairs)), encoding="utf-8")
    items = [{"photo_id": k, "sha256": v} for k, v in pairs.items()]
    report = PI.validate_queue_items(items, manifest_path=mp)
    assert report["ok"] is True and report["correct"] == 2


# ---------- 4. 同 SHA 不同 photo_id：canonical asset + 别名证据 ----------

def test_same_sha_multiple_ids_canonical_with_alias_evidence(tmp_path):
    shared = _sha("shared-content")
    manifest = {
        "111": {"status": "clean", "sha256": shared, "width": 100,
                "height": 200, "filename": "a.jpg"},
        "222": {"status": "clean", "sha256": shared, "width": 100,
                "height": 200, "filename": "b.jpg"},
    }
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    assets = PI.canonical_assets(manifest_path=mp)
    group = assets["by_sha"][shared]
    assert group["canonical_photo_id"] in ("111", "222")  # 确定性选择
    assert set(group["alias_photo_ids"]) == {"111", "222"}
    assert group["evidence"]  # 别名证据必须保留
    # 确定性：重复调用结果一致
    assert PI.canonical_assets(manifest_path=mp)["by_sha"][shared] == group


# ---------- 5. 队列文件已存在拒绝覆盖 ----------

def test_queue_file_refuses_overwrite(tmp_path):
    from src.review.human_review_queue import write_queue
    out = tmp_path / "rq.json"
    write_queue({"items": []}, out)
    with pytest.raises(FileExistsError):
        write_queue({"items": []}, out)


# ---------- 现场证据测试（真实制品，只读） ----------

@pytest.mark.slow
def test_real_protocol_positional_zip_is_broken():
    """现场复现：diagnostic_v1 位置 zip 配对几乎全错，canonical 映射可全恢复。"""
    diag = PI.PROTOCOL_DIR / "diagnostic_v1.json"
    if not diag.exists():
        pytest.skip("diagnostic_v1.json 不在本机")
    d = json.loads(diag.read_text(encoding="utf-8"))
    zip_report = PI.validate_pairing(
        list(zip(d["photo_ids"], d["sha256"])),
        manifest_path=PI.CLEAN_MANIFEST)
    assert zip_report["ok"] is False  # 位置 zip 就是错的
    # canonical 映射 500/500 可恢复
    mapping = PI.canonical_mapping(d["photo_ids"], manifest_path=PI.CLEAN_MANIFEST)
    assert len(mapping) == len(d["photo_ids"]) == 500
    assert set(mapping.values()) == set(d["sha256"])  # SHA 集合本身有效
