"""运行时安全回归测试：monitor ckpt 缓存门槛（RA-001）与推理背压（RA-016）。"""
import threading
import time

import pytest


def test_monitor_ckpt_cache_mtime_gate(tmp_path, monkeypatch):
    """TTL 到期但文件 mtime/size 未变化时不得重复 torch.load（缓存必须命中）。"""
    from src.training import monitor as M

    f = tmp_path / "best.pt"
    f.write_bytes(b"not-a-real-ckpt")  # torch.load 会失败，meta 仅含 mtime/size
    monkeypatch.setattr(M, "_CKPT_CACHE", None)
    monkeypatch.setattr(M, "_CKPT_CACHE_AT", 0.0)

    m1 = M._load_ckpt_meta(f)
    assert m1 and m1["mtime"] == f.stat().st_mtime

    # 模拟 TTL 早已到期：缓存时间设为远古
    monkeypatch.setattr(M, "_CKPT_CACHE_AT", 0.0)
    cache_obj = M._CKPT_CACHE
    m2 = M._load_ckpt_meta(f)
    assert m2 is cache_obj, "文件未变化时必须命中缓存而不是重新 torch.load"


def test_backpressure_overload_raises(tmp_path):
    """并发许可耗尽且排队超时 → OverloadedError（HTTP 429 的来源）。"""
    from src.recognize import service as S

    engine = S.RecognitionEngine()
    engine.cascade = object()  # 跳过模型加载，直达信号量
    monkey_timeout = S._QUEUE_TIMEOUT
    # 占满全部并发许可
    held = []
    for _ in range(S._MAX_CONCURRENCY):
        assert S._INFER_SEM.acquire(timeout=2)
        held.append(1)
    try:
        S._QUEUE_TIMEOUT = 0.1  # 缩短等待，快速触发
        with pytest.raises(S.OverloadedError):
            engine.recognize(b"fake-image-bytes")
    finally:
        S._QUEUE_TIMEOUT = monkey_timeout
        for _ in held:
            S._INFER_SEM.release()


def test_backpressure_recovers_after_release():
    """许可释放后应立即恢复服务（信号量无泄漏）。"""
    from src.recognize import service as S

    class FakeCascade:
        def recognize(self, image_bytes, conf=0.25):
            return []

    engine = S.RecognitionEngine()
    engine.cascade = FakeCascade()
    assert S._INFER_SEM.acquire(timeout=2)
    S._INFER_SEM.release()
    out = engine.recognize(b"x")
    assert out == []
