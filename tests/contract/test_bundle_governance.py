"""bundle 治理回归测试（RA-006 复核修订）。

覆盖：哈希校验失败拒绝上线、篡改检测、重复 publish 保留 previous 链、
resolve_weights 默认先 verify（fail-closed）、thresholds margin 来源如实标记。"""
import json
import pytest

from src.models import bundle as B


class FakeConn:
    def __init__(self):
        self.sql = []

    def execute(self, q, p=()):
        self.sql.append((q, p))

        class _R:
            def fetchone(self):
                return None
        return _R()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """把 bundle 的物理目录/指针/DB 全部重定向到 tmp。"""
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    monkeypatch.setattr(B, "BUNDLES_DIR", bundles)
    monkeypatch.setattr(B, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(B, "CURRENT_FILE", bundles / "CURRENT.json")
    conn = FakeConn()
    monkeypatch.setattr(B.wh, "connect", lambda: conn)
    monkeypatch.setattr(B.wh, "migrate", lambda c: None)
    return tmp_path, conn


def _assets(tmp_path):
    det = tmp_path / "det.pt"; det.write_bytes(b"detector-bytes")
    clf = tmp_path / "clf.pt"; clf.write_bytes(b"classifier-bytes")
    reg = tmp_path / "reg.json"; reg.write_text("{}")
    thr = tmp_path / "thr.json"; thr.write_text(json.dumps({"conf": 0.6}))  # 故意缺 margin
    return det, clf, reg, thr


def test_create_verify_ok(fake_env):
    tmp_path, _ = fake_env
    det, clf, reg, thr = _assets(tmp_path)
    B.create_bundle("b1", det, clf, reg, thresholds=thr, note="test")
    r = B.verify_bundle("b1")
    assert r["ok"] and r["n_files"] == 4


def test_tamper_detected(fake_env):
    tmp_path, _ = fake_env
    det, clf, reg, thr = _assets(tmp_path)
    B.create_bundle("b1", det, clf, reg, note="test")
    f = B.bundle_dir("b1") / "detector.pt"
    f.chmod(0o644)
    f.write_bytes(b"tampered")
    with pytest.raises(B.BundleError):
        B.verify_bundle("b1")


def test_publish_keeps_previous_on_republish(fake_env):
    """重复 publish 当前 bundle 不得清零 previous 回滚链。"""
    tmp_path, _ = fake_env
    det, clf, reg, thr = _assets(tmp_path)
    B.create_bundle("b1", det, clf, reg, note="test")
    B.create_bundle("b2", det, clf, reg, note="test2")
    B.publish("b1")
    B.publish("b2")
    assert B.current_bundle()["previous"] == "b1"
    B.publish("b2")  # 重复发布
    assert B.current_bundle()["previous"] == "b1", "重复 publish 丢失 previous 链"


def test_publish_refuses_tampered_bundle(fake_env):
    tmp_path, _ = fake_env
    det, clf, reg, thr = _assets(tmp_path)
    B.create_bundle("b1", det, clf, reg, note="test")
    f = B.bundle_dir("b1") / "classifier.pt"
    f.chmod(0o644)
    f.write_bytes(b"bad")
    with pytest.raises(B.BundleError):
        B.publish("b1")
    assert B.current_bundle() is None


def test_resolve_weights_verifies_and_reports_threshold_source(fake_env):
    tmp_path, _ = fake_env
    det, clf, reg, thr = _assets(tmp_path)
    B.create_bundle("b1", det, clf, reg, thresholds=thr, note="test")
    B.publish("b1")
    r = B.resolve_weights()
    assert r["bundle_id"] == "b1"
    assert r["threshold_values"]["conf"] == 0.6
    assert "margin" not in r["threshold_values"]
    # margin 缺失必须如实标记为代码默认，不得假装来自 bundle
    assert r["threshold_source"]["conf"] == "bundle"
    assert r["threshold_source"]["margin"] == "code_default"
    # 篡改后 resolve 必须 fail-closed（默认 verify=True）
    f = B.bundle_dir("b1") / "detector.pt"
    f.chmod(0o644)
    f.write_bytes(b"tampered-again")
    with pytest.raises(B.BundleError):
        B.resolve_weights()
