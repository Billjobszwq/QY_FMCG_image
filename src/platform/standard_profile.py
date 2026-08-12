"""ABOSV3 T8：standard profile 受控切换与回滚服务。

- 切换前校验目标 bundle MANIFEST 与全部文件 hash（fail-closed）；
- CURRENT.json 原子写入（tmp+rename），切换前备份 CURRENT.previous.json
  与时间戳副本；
- 切换/回滚写审计与证据；失败不得造成半切换状态；
- shadow 报告只读呈现（不修改）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any


class StandardProfileError(Exception):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class StandardProfileService:
    def __init__(self, store: Any,
                 bundles_dir: Path | str | None = None) -> None:
        import os
        self.store = store
        if bundles_dir is not None:
            self.bundles_dir = Path(bundles_dir)
        elif os.environ.get("STANDARD_BUNDLES_DIR", "").strip():
            self.bundles_dir = Path(
                os.environ["STANDARD_BUNDLES_DIR"])
        else:
            self.bundles_dir = (Path(__file__).resolve().parents[2]
                                / ".models" / "bundles")

    # ---------- 只读 ----------

    @property
    def current_path(self) -> Path:
        return self.bundles_dir / "CURRENT.json"

    def current(self) -> dict:
        try:
            return json.loads(self.current_path.read_text(
                encoding="utf-8"))
        except Exception:
            return {"bundle_id": None, "found": False}

    def list_bundles(self) -> list[dict]:
        out = []
        for d in sorted(self.bundles_dir.iterdir()):
            mf = d / "MANIFEST.json"
            if not d.is_dir() or not mf.exists():
                continue
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({"bundle_id": m.get("bundle_id", d.name),
                        "dir": d.name,
                        "created_at": m.get("created_at"),
                        "reason": (m.get("reason") or "")[:200],
                        "files": len(m.get("files", []))})
        return out

    def verify_bundle(self, bundle_id: str) -> dict:
        """校验 MANIFEST 与磁盘文件 hash 一致（fail-closed）。"""
        d = self.bundles_dir / bundle_id
        mf = d / "MANIFEST.json"
        if not mf.exists():
            raise StandardProfileError(f"bundle 不存在: {bundle_id}")
        m = json.loads(mf.read_text(encoding="utf-8"))
        problems = []
        for f in m.get("files", []):
            p = self.bundles_dir / f["file"]
            if not p.exists():
                problems.append(f"文件缺失: {f['file']}")
                continue
            if p.stat().st_size != f.get("size"):
                problems.append(f"大小不一致: {f['file']}")
            if _sha(p) != f.get("sha256"):
                problems.append(f"hash 不一致: {f['file']}")
        return {"bundle_id": bundle_id, "consistent": not problems,
                "problems": problems}

    def shadow_report(self) -> dict | None:
        p = (Path(__file__).resolve().parents[2] / ".eval"
             / "shadow_v4_best_report.json")
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    # ---------- 切换 / 回滚 ----------

    def switch(self, *, bundle_id: str, actor: str,
               reason: str = "") -> dict:
        verify = self.verify_bundle(bundle_id)
        if not verify["consistent"]:
            raise StandardProfileError(
                "bundle 校验失败（fail-closed）："
                + "；".join(verify["problems"]))
        cur = self.current()
        if cur.get("bundle_id") == bundle_id:
            raise StandardProfileError(
                f"当前已是 {bundle_id}（无需切换）")
        # 备份当前指针（可回滚）
        if self.current_path.exists():
            shutil.copy2(self.current_path,
                         self.bundles_dir / "CURRENT.previous.json")
            shutil.copy2(self.current_path,
                         self.bundles_dir
                         / f"CURRENT.bak.{int(time.time())}.json")
        payload = {"bundle_id": bundle_id,
                   "previous": cur.get("bundle_id"),
                   "published_at": time.time(),
                   "switched_by": actor,
                   "reason": (reason or "ABOSV3 T8 受控切换")[:300]}
        tmp = self.current_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False,
                                  indent=2), encoding="utf-8")
        tmp.replace(self.current_path)  # 原子替换
        self._sync_profiles(bundle_id, enabled=True)
        self._record("recognition.standard.switched", actor, payload)
        return self.current()

    def rollback(self, *, actor: str) -> dict:
        prev = self.bundles_dir / "CURRENT.previous.json"
        if not prev.exists():
            raise StandardProfileError("无可回滚的备份"
                                       "（CURRENT.previous.json 不存在）")
        target = json.loads(prev.read_text(encoding="utf-8"))
        verify = self.verify_bundle(target["bundle_id"])
        if not verify["consistent"]:
            raise StandardProfileError(
                "回滚目标校验失败（fail-closed）："
                + "；".join(verify["problems"]))
        cur = self.current()
        shutil.copy2(prev, self.current_path.with_suffix(".json.tmp"))
        self.current_path.with_suffix(".json.tmp").replace(
            self.current_path)
        # 备份指针回退后交换（允许多次往返）
        backup = self.bundles_dir / "CURRENT.swap.json"
        backup.write_text(json.dumps(cur, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        shutil.copy2(backup, prev)
        backup.unlink()
        # 回滚：被回退的 bundle 同步禁用；恢复的 bundle 若是 V4 则启用
        self._sync_profiles(cur.get("bundle_id") or "", enabled=False)
        self._sync_profiles(target["bundle_id"], enabled=True)
        self._record("recognition.standard.rollback", actor,
                     {"restored": target["bundle_id"],
                      "from": cur.get("bundle_id")})
        return self.current()

    def _sync_profiles(self, bundle_id: str, *, enabled: bool) -> None:
        """切换/回滚同步制品状态：artifact registry 的 candidate_status
        决定 v4_best_standard profile 的启用（derive_profiles 派生，
        不伪造状态）。"""
        if bundle_id != "prod_v4_best_r1":
            return
        try:
            self.store._conn.execute(
                "UPDATE model_artifact_registry_v1 SET candidate_status=?"
                " WHERE artifact_id='prod_v4_best_r1_bundle'",
                ("CANDIDATE" if enabled else "SHADOW_PENDING_SWITCH",))
            self.store._conn.commit()
        except Exception:
            pass

    def _record(self, action: str, actor: str, detail: dict) -> None:
        try:
            self.store._conn.execute(
                "INSERT INTO iam_audit_event_v1 (occurred_at, actor_id,"
                " action, resource, detail_json, customer_id)"
                " VALUES (?,?,?,?,?,?)",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 actor, action, "recognition_standard",
                 json.dumps(detail, ensure_ascii=False), ""))
            self.store._conn.commit()
        except Exception:
            pass
        try:
            self.store.emit_event(
                event_id="evt-" + hashlib.sha256(
                    (action + str(time.time())).encode()).hexdigest()[:16],
                event_type=action, actor_type="human", actor_id=actor,
                payload=detail)
        except Exception:
            pass
