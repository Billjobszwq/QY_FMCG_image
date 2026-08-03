"""后台任务管理：识别任务、训练任务的状态跟踪与结果存储。

任务持久化到 .platform/jobs.json，结果存 .platform/results/{job_id}.json。
ISSUE-014：所有读改写共用进程锁 + 跨进程文件锁；解析失败直接抛异常（绝不返回
空对象覆盖历史）；写盘均用临时文件 + os.replace 原子替换。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from ..common import paths
from ..common.config import PROJECT_ROOT

PLATFORM_DIR = PROJECT_ROOT / ".platform"
JOBS_FILE = PLATFORM_DIR / "jobs.json"
RESULTS_DIR = PLATFORM_DIR / "results"
LOCK_FILE = PLATFORM_DIR / "jobs.lock"

_lock = threading.RLock()


def _ensure():
    PLATFORM_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class _file_lock:
    """跨进程文件锁（fcntl），不可用平台退化为仅进程锁。"""

    def __enter__(self):
        _ensure()
        try:
            import fcntl
            self._fh = open(LOCK_FILE, "a")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            self._fh = None
        return self

    def __exit__(self, *exc):
        if self._fh:
            try:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            self._fh.close()
        return False


def _load() -> dict:
    if JOBS_FILE.exists():
        # ISSUE-014：解析失败必须抛异常，绝不返回空字典（否则下次保存会覆盖全部历史）
        return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    return {}


def _atomic_write(path: Path, data):
    _ensure()
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:6]}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # 原子替换：中断后旧文件仍可解析


def create_job(kind: str, params: dict) -> str:
    job_id = f"{kind}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    with _lock, _file_lock():
        jobs = _load()
        jobs[job_id] = {
            "id": job_id, "kind": kind, "params": params,
            "status": "pending", "progress": 0, "created_at": time.time(),
            "updated_at": time.time(), "error": None, "result_summary": None,
        }
        _atomic_write(JOBS_FILE, jobs)
    return job_id


def update_job(job_id: str, **fields):
    with _lock, _file_lock():
        jobs = _load()
        if job_id in jobs:
            jobs[job_id].update(fields)
            jobs[job_id]["updated_at"] = time.time()
            _atomic_write(JOBS_FILE, jobs)


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _load().get(job_id)


def list_jobs(kind: str | None = None, limit: int = 50) -> list[dict]:
    with _lock:
        jobs = list(_load().values())
    if kind:
        jobs = [j for j in jobs if j["kind"] == kind]
    jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return jobs[:limit]


def save_result(job_id: str, data) -> Path:
    p = RESULTS_DIR / f"{job_id}.json"
    _atomic_write(p, data)
    return p


def load_result(job_id: str):
    p = RESULTS_DIR / f"{job_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def run_in_thread(fn, job_id: str):
    """在后台线程运行 fn(job_id, update_fn)，捕获异常更新任务状态。"""
    def wrapper():
        try:
            update_job(job_id, status="running")
            result = fn(job_id, lambda **kw: update_job(job_id, **kw))
            update_job(job_id, status="done", progress=100, result_summary=result)
        except Exception as e:
            update_job(job_id, status="error", error=f"{type(e).__name__}: {e}")
    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    return t
