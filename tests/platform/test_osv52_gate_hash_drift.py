"""OSV52 红测试：Gate 证据文件哈希实时重校验 + Active Gate Registry。

契约（docs/implementation/operational-scope-v5-correction-v2）：
- gate.json 必须保存每份证据的 manifest（根相对路径/SHA256/大小/
  生成时间）；实时 freshness 复评必须重读重算 UAT/test/browser/
  negative/issue ledger 五份证据；
- 内容/大小/哈希改变 → BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT；
  文件缺失/路径异常/JSON 不可解析 → STALE_GATE_EVIDENCE；
- result_hash、binding、整文件哈希分层校验；
- Active Gate 显式 Registry（gate_run_v1，append-only，禁 mtime
  选择）：激活 CAS + 人工批准；实时端点只读 active；缺失/哈希/
  registry 不一致 fail-closed。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


PW = "osv52-pw"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_OkRecognition(), probe=lambda spec: None)
    build_profiles_service(bundle)
    return {"store": bundle.store, "tmp": tmp_path, "bundle": bundle}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _mk_evidence(tmp: Path, name: str, payload: dict, kind: str,
                 head: str = "h0") -> Path:
    from src.platform import binding_core as _bc
    from src.platform.gate_evaluator import _result_payload_for
    d = dict(payload)
    rp = _result_payload_for(kind, payload)
    d["binding"] = {"source_commit": head, "code_tree_hash": "",
                    "migration_hash": "",
                    "result_hash": _bc.result_hash(rp)
                    if rp is not None else ""}
    p = tmp / name
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def _mk_recorded_gate(tmp: Path, manifest: dict, store,
                      head: str = "h0") -> Path:
    from src.platform.gate_evaluator import db_fingerprint
    g = {"gate": "READY_FOR_REAL_DATA_UAT", "reasons": [], "checks": [],
         "evidence_hashes": {}, "evaluator_version": "3.4.0",
         "source_commit": head, "code_tree_hash": "",
         "migration_hash": "", "db_fingerprint": db_fingerprint(store),
         "evidence_manifest": manifest}
    p = tmp / "gate.json"
    p.write_text(json.dumps(g), encoding="utf-8")
    return p


def _manifest_of(files: dict) -> dict:
    man = {}
    for kind, p in files.items():
        man[kind] = {"path": str(p), "sha256": _sha(p),
                     "size": p.stat().st_size,
                     "generated_at": "2026-08-13T00:00:00+00:00"}
    return man


def _fresh(store, gate_path: Path, head: str = "h0"):
    from src.platform.gate_evaluator import evaluate_gate_from_evidence
    return evaluate_gate_from_evidence(
        store=store, recorded_gate_path=gate_path, current_head=head,
        current_tree_hash="", current_migration_hash="",
        evidence_root=gate_path.parent)


class TestEvidenceHashRecheck:
    def _five(self, env):
        tmp = env["tmp"]
        uat = _mk_evidence(tmp, "uat.json",
                           {"protocol": "uatv7", "total": 23,
                            "failed": 0, "namespace": "ns",
                            "ids": {}}, "uat_report")
        tst = _mk_evidence(tmp, "test.json",
                           {"suite": "hermetic", "failed": 0,
                            "passed": 1, "skipped": 0,
                            "deselected": 0, "marker": "not host_mps",
                            "generated_by": "scripts/x"}, "test_report")
        brw = _mk_evidence(tmp, "browser.json",
                           {"pages": [], "status": "ok",
                            "browser_test_run": "ns_b"},
                           "browser_report")
        neg = _mk_evidence(tmp, "negative.json",
                           {"gate_negative_tests": [],
                            "all_blocked": True}, "negative_report")
        led = tmp / "ISSUES.md"
        led.write_text("# issues\nnone\n", encoding="utf-8")
        return {"uat_report": uat, "test_report": tst,
                "browser_report": brw, "negative_report": neg,
                "issue_ledger": led}

    def test_clean_manifest_passes(self, env):
        files = self._five(env)
        gate = _mk_recorded_gate(env["tmp"], _manifest_of(files),
                                 env["store"])
        res = _fresh(env["store"], gate)
        assert res["gate"] == "READY_FOR_REAL_DATA_UAT", res

    def test_rewritten_negative_report_is_hash_drift(self, env):
        files = self._five(env)
        gate = _mk_recorded_gate(env["tmp"], _manifest_of(files),
                                 env["store"])
        files["negative_report"].write_text(
            json.dumps({"gate_negative_tests": [],
                        "all_blocked": True, "x": 1}),
            encoding="utf-8")
        res = _fresh(env["store"], gate)
        assert res["gate"] == "BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT", res

    def test_rewritten_test_report_is_hash_drift(self, env):
        files = self._five(env)
        gate = _mk_recorded_gate(env["tmp"], _manifest_of(files),
                                 env["store"])
        files["test_report"].write_text(
            json.dumps({"suite": "hermetic", "failed": 0,
                        "passed": 9999}), encoding="utf-8")
        res = _fresh(env["store"], gate)
        assert res["gate"] == "BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT", res

    def test_replaced_browser_evidence_is_hash_drift(self, env):
        files = self._five(env)
        gate = _mk_recorded_gate(env["tmp"], _manifest_of(files),
                                 env["store"])
        files["browser_report"].write_bytes(b'{"pages": [1,2,3]}')
        res = _fresh(env["store"], gate)
        assert res["gate"] == "BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT", res

    def test_deleted_uat_report_is_stale(self, env):
        files = self._five(env)
        gate = _mk_recorded_gate(env["tmp"], _manifest_of(files),
                                 env["store"])
        files["uat_report"].unlink()
        res = _fresh(env["store"], gate)
        assert res["gate"] == "STALE_GATE_EVIDENCE", res

    def test_unparseable_json_is_stale(self, env):
        files = self._five(env)
        gate = _mk_recorded_gate(env["tmp"], _manifest_of(files),
                                 env["store"])
        p = files["test_report"]
        blob = bytearray(p.read_bytes())
        # 同尺寸破坏中段字节 → JSON 不可解析且哈希变化：fail-closed
        blob[len(blob) // 2] = 0x07
        p.write_bytes(bytes(blob))
        res = _fresh(env["store"], gate)
        assert res["gate"] in ("STALE_GATE_EVIDENCE",
                               "BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT"), res

    def test_size_mismatch_is_hash_drift(self, env):
        files = self._five(env)
        man = _manifest_of(files)
        man["negative_report"]["size"] += 5  # 记录尺寸被篡改
        gate = _mk_recorded_gate(env["tmp"], man, env["store"])
        res = _fresh(env["store"], gate)
        assert res["gate"] == "BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT", res

    def test_missing_manifest_fails_closed(self, env):
        files = self._five(env)
        g = {"gate": "READY_FOR_REAL_DATA_UAT", "reasons": [],
             "checks": [], "evidence_hashes": {},
             "evaluator_version": "3.4.0", "source_commit": "h0",
             "db_fingerprint": {}}
        gate = env["tmp"] / "gate.json"
        gate.write_text(json.dumps(g), encoding="utf-8")
        res = _fresh(env["store"], gate)
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT", res

    def test_path_traversal_rejected(self, env):
        files = self._five(env)
        man = _manifest_of(files)
        evil = env["tmp"].parent / "evil.json"
        evil.write_text("{}", encoding="utf-8")
        man["negative_report"]["path"] = "../evil.json"
        gate = _mk_recorded_gate(env["tmp"], man, env["store"])
        res = _fresh(env["store"], gate)
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT", res

    def test_symlink_escape_rejected(self, env):
        files = self._five(env)
        man = _manifest_of(files)
        outside = env["tmp"].parent / "outside_neg.json"
        outside.write_text(files["negative_report"].read_text(),
                           encoding="utf-8")
        link = env["tmp"] / "neg_link.json"
        try:
            os.symlink(outside, link)
        except OSError:
            pytest.skip("symlink 不可用")
        man["negative_report"]["path"] = str(link)
        man["negative_report"]["sha256"] = _sha(link)
        man["negative_report"]["size"] = link.stat().st_size
        gate = _mk_recorded_gate(env["tmp"], man, env["store"])
        res = _fresh(env["store"], gate)
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT", res

    def test_binding_kept_body_tampered_still_drift(self, env):
        """保持 binding 块字节不变、篡改正文其余字段——整文件哈希与
        result_hash 层必须拦下。"""
        files = self._five(env)
        gate = _mk_recorded_gate(env["tmp"], _manifest_of(files),
                                 env["store"])
        p = files["negative_report"]
        d = json.loads(p.read_text(encoding="utf-8"))
        d["all_blocked"] = False  # 篡改语义正文，binding 不动
        p.write_text(json.dumps(d, ensure_ascii=False),
                     encoding="utf-8")
        res = _fresh(env["store"], gate)
        assert res["gate"] == "BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT", res


class TestActiveGateRegistry:
    def _record(self, env, scope="scope_v5", head="h0"):
        from src.platform.gate_registry import record_gate_run
        gp = env["tmp"] / f"gate_{scope}.json"
        gp.write_text(json.dumps({"gate": "READY_FOR_REAL_DATA_UAT",
                                  "source_commit": head}),
                      encoding="utf-8")
        return record_gate_run(
            env["store"], protocol=scope, gate_path=gp,
            source_commit=head, evaluator_version="3.4.0",
            evidence_manifest_hash="m" * 16,
            gate_file_sha256=_sha(gp), requested_by="generator")

    def test_record_creates_candidate(self, env):
        gid = self._record(env)
        from src.platform.gate_registry import get_gate_run
        row = get_gate_run(env["store"], gid)
        assert row["status"] == "candidate"

    def test_activate_requires_approval_and_platform(self, env):
        from src.platform.gate_registry import (activate_gate_run,
                                                GateRegistryError)
        gid = self._record(env)
        with pytest.raises(GateRegistryError):
            activate_gate_run(env["store"], gate_run_id=gid,
                              actor="admin", approved=False)
        with pytest.raises(GateRegistryError):
            activate_gate_run(env["store"], gate_run_id=gid,
                              actor="u_reader", approved=True,
                              session_role="read_only")

    def test_activate_cas_single_active(self, env):
        from src.platform.gate_registry import (activate_gate_run,
                                                get_active_gate_run)
        gid = self._record(env)
        row = activate_gate_run(env["store"], gate_run_id=gid,
                                actor="admin", approved=True)
        assert row["status"] == "active"
        act = get_active_gate_run(env["store"])
        assert act["gate_run_id"] == gid
        # 第二次激活同一 run 幂等；旧 scope 重跑不得接管
        gid2 = self._record(env, scope="scope_v4_old", head="hOld")
        from src.platform.gate_registry import GateRegistryError
        with pytest.raises(GateRegistryError):
            activate_gate_run(env["store"], gate_run_id=gid2,
                              actor="admin", approved=True,
                              expected_protocol="scope_v5")
        act2 = get_active_gate_run(env["store"])
        assert act2["gate_run_id"] == gid

    def test_supersede_chain(self, env):
        from src.platform.gate_registry import (activate_gate_run,
                                                get_gate_run)
        gid1 = self._record(env, head="h1")
        activate_gate_run(env["store"], gate_run_id=gid1,
                          actor="admin", approved=True)
        gid2 = self._record(env, head="h2")
        row2 = activate_gate_run(env["store"], gate_run_id=gid2,
                                 actor="admin", approved=True,
                                 expected_protocol="scope_v5")
        assert row2["supersedes"] == gid1
        assert get_gate_run(env["store"], gid1)["status"] == \
            "superseded"

    def test_registry_rows_immutable_no_delete(self, env):
        import sqlite3
        gid = self._record(env)
        with pytest.raises(sqlite3.IntegrityError):
            env["store"]._conn.execute(
                "DELETE FROM gate_run_v1 WHERE gate_run_id=?", (gid,))
