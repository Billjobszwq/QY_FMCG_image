"""RA-006：不可变模型 bundle 治理。

将 detector + classifier + 类别映射 + 阈值 + 数据指纹作为一个不可变发布单元：
- create_bundle：复制资产到 .models/bundles/<id>/，逐文件 sha256 写入 MANIFEST.json，整体只读
- verify_bundle：发布/加载前重算哈希，任何篡改拒绝上线
- publish：校验 → 原子切换 CURRENT 指针 → DB 登记（previous_bundle_id 记录回滚链）
- rollback：只回滚到明确记录的上一生产 bundle，绝不猜测
- resolve_weights：在线服务解析当前生产 bundle 的权重路径

CLI：python -m src.models.bundle {create|publish|rollback|verify|list|current} [...]"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.config import PROJECT_ROOT
from src.data import warehouse as wh

MODELS_DIR = PROJECT_ROOT / ".models"
BUNDLES_DIR = MODELS_DIR / "bundles"
ARCHIVE_DIR = MODELS_DIR / "archive"  # 止损归档目录同样可作为 bundle 源
CURRENT_FILE = BUNDLES_DIR / "CURRENT.json"
MANIFEST_NAME = "MANIFEST.json"


class BundleError(RuntimeError):
    """bundle 完整性/状态错误 —— 拒绝上线，fail-closed。"""


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _chmod_readonly_recursive(d: Path) -> None:
    for f in d.rglob("*"):
        try:
            f.chmod(0o444 if f.is_file() else 0o555)
        except Exception:
            pass
    try:
        d.chmod(0o555)
    except Exception:
        pass


def bundle_dir(bundle_id: str) -> Path | None:
    """解析 bundle 物理目录：优先 bundles/，其次 archive/（止损归档可直接发布）。"""
    for base in (BUNDLES_DIR, ARCHIVE_DIR):
        d = base / bundle_id
        if (d / MANIFEST_NAME).exists():
            return d
    return None


def list_bundles() -> list[dict]:
    out = []
    for base in (BUNDLES_DIR, ARCHIVE_DIR):
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            mp = d / MANIFEST_NAME
            if not mp.exists():
                continue
            try:
                m = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({"bundle_id": d.name, "location": str(base.name),
                        "created_at": m.get("created_at"), "reason": m.get("reason", ""),
                        "n_files": len(m.get("files", []))})
    return out


def verify_bundle(bundle_id: str) -> dict:
    """重算所有文件 sha256 与 MANIFEST 比对；任何不一致抛 BundleError。"""
    d = bundle_dir(bundle_id)
    if d is None:
        raise BundleError(f"bundle 不存在: {bundle_id}")
    m = json.loads((d / MANIFEST_NAME).read_text(encoding="utf-8"))
    files = m.get("files", [])
    if not files:
        raise BundleError(f"bundle manifest 无文件清单: {bundle_id}")
    for item in files:
        rel = Path(item["file"])
        # manifest 中 file 形如 "<bundle_id>/<name>"（兼容归档格式，可含子目录）
        parts = rel.parts
        if parts and parts[0] == bundle_id:
            parts = parts[1:]
        fp = d.joinpath(*parts) if parts else d / rel.name
        if not fp.exists():
            fp = d / rel.name
        if not fp.exists():
            raise BundleError(f"bundle 文件缺失: {bundle_id}/{rel}")
        if fp.stat().st_size != int(item.get("size", -1)):
            raise BundleError(f"bundle 文件大小不符: {rel}")
        if _sha256(fp) != item["sha256"]:
            raise BundleError(f"bundle 哈希不一致（被篡改？）: {rel}")
    combo = m.get("production_combo", {})
    if not combo.get("detector") or not combo.get("classifier"):
        raise BundleError(f"bundle 缺少 production_combo 定义: {bundle_id}")
    return {"bundle_id": bundle_id, "ok": True, "n_files": len(files)}


def current_bundle() -> dict | None:
    """读取 CURRENT 指针（原子文件），返回 {'bundle_id', 'published_at', 'previous'}。"""
    if not CURRENT_FILE.exists():
        return None
    try:
        return json.loads(CURRENT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_current_atomic(bundle_id: str, previous: str | None) -> None:
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"bundle_id": bundle_id, "previous": previous, "published_at": time.time()}
    tmp = CURRENT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CURRENT_FILE)  # 原子替换：任何时刻 CURRENT 都是完整 JSON


def create_bundle(bundle_id: str, detector: str | Path, classifier: str | Path,
                  registry: str | Path, classes: str | Path | None = None,
                  thresholds: str | Path | None = None,
                  dataset_hash: str = "", metrics: dict | None = None,
                  note: str = "") -> dict:
    """创建不可变 bundle：复制资产 → 写 MANIFEST（逐文件 sha256）→ 整体只读 → DB 登记 created。"""
    if bundle_dir(bundle_id) is not None:
        raise BundleError(f"bundle 已存在，禁止覆盖: {bundle_id}")
    d = BUNDLES_DIR / bundle_id
    d.mkdir(parents=True)
    files = []
    try:
        assets = {"detector.pt": Path(detector), "classifier.pt": Path(classifier),
                  "sku_registry.json": Path(registry)}
        if classes:
            assets["classifier_classes.json"] = Path(classes)
        if thresholds:
            assets["thresholds.json"] = Path(thresholds)
        for name, src in assets.items():
            if not src.exists():
                raise BundleError(f"源资产缺失: {src}")
            dst = d / name
            shutil.copy2(src, dst)
            files.append({"file": f"{bundle_id}/{name}", "source": str(src),
                          "size": dst.stat().st_size, "sha256": _sha256(dst)})
        manifest = {
            "bundle_id": bundle_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "production_combo": {"detector": "detector.pt", "classifier": "classifier.pt"},
            "dataset_hash": dataset_hash,
            "metrics": metrics or {},
            "reason": note,
            "files": files,
        }
        (d / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        _chmod_readonly_recursive(d)
    except Exception:
        # 创建失败：清理半成品（只读化前仍可删）
        for f in d.rglob("*"):
            try:
                f.chmod(0o644)
            except Exception:
                pass
        shutil.rmtree(d, ignore_errors=True)
        raise
    conn = wh.connect()
    wh.migrate(conn)
    conn.execute(
        "INSERT INTO model_bundle(bundle_id, manifest_json, status, created_at) VALUES(?,?,?,?)",
        (bundle_id, json.dumps(manifest, ensure_ascii=False), "created", time.time()))
    conn.commit()
    conn.close()
    return {"bundle_id": bundle_id, "dir": str(d), "n_files": len(files)}


def publish(bundle_id: str) -> dict:
    """上线 = 只切 CURRENT 指针。发布前强制 verify；DB 记录回滚链。"""
    verify_bundle(bundle_id)
    cur = current_bundle()
    previous = cur["bundle_id"] if cur and cur.get("bundle_id") != bundle_id else None
    d = bundle_dir(bundle_id)
    manifest = json.loads((d / MANIFEST_NAME).read_text(encoding="utf-8"))
    conn = wh.connect()
    wh.migrate(conn)
    try:
        row = conn.execute("SELECT bundle_id FROM model_bundle WHERE bundle_id=?",
                           (bundle_id,)).fetchone()
        if not row:
            # 归档 bundle 直接发布时也补登记
            conn.execute(
                "INSERT INTO model_bundle(bundle_id, manifest_json, status, created_at) VALUES(?,?,?,?)",
                (bundle_id, json.dumps(manifest, ensure_ascii=False), "created", time.time()))
        if previous:
            conn.execute("UPDATE model_bundle SET status='retired' WHERE bundle_id=?", (previous,))
        conn.execute(
            "UPDATE model_bundle SET status='production', previous_bundle_id=?, published_at=? "
            "WHERE bundle_id=?", (previous, time.time(), bundle_id))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    _write_current_atomic(bundle_id, previous)
    return {"ok": True, "published": bundle_id, "previous": previous}


def rollback() -> dict:
    """回滚到明确记录的上一生产 bundle；无记录则拒绝（绝不猜测）。"""
    cur = current_bundle()
    target = None
    if cur and cur.get("previous"):
        target = cur["previous"]
    else:
        conn = wh.connect()
        wh.migrate(conn)
        row = conn.execute(
            "SELECT previous_bundle_id FROM model_bundle WHERE status='production' "
            "AND previous_bundle_id IS NOT NULL ORDER BY published_at DESC LIMIT 1").fetchone()
        conn.close()
        if row and row[0]:
            target = row[0]
    if not target:
        raise BundleError("无可回滚目标：当前 bundle 没有记录 previous_bundle_id")
    return publish(target)


def resolve_weights() -> dict | None:
    """在线服务解析当前生产 bundle 的资产路径；无 CURRENT 指针返回 None（调用方走默认路径）。"""
    cur = current_bundle()
    if not cur:
        return None
    bid = cur["bundle_id"]
    d = bundle_dir(bid)
    if d is None:
        return None
    try:
        m = json.loads((d / MANIFEST_NAME).read_text(encoding="utf-8"))
    except Exception:
        return None
    combo = m.get("production_combo", {})
    det, clf = combo.get("detector"), combo.get("classifier")
    if not det or not clf:
        return None
    out = {"bundle_id": bid,
           "detector": str(d / det), "classifier": str(d / clf),
           "registry": str(d / "sku_registry.json") if (d / "sku_registry.json").exists() else None,
           "classes": str(d / "classifier_classes.json") if (d / "classifier_classes.json").exists() else None,
           "thresholds": str(d / "thresholds.json") if (d / "thresholds.json").exists() else None,
           "dataset_hash": m.get("dataset_hash", "")}
    # 阈值可选注入（拒识门禁 conf/margin），兼容多种键名
    if out["thresholds"]:
        try:
            raw = json.loads(Path(out["thresholds"]).read_text(encoding="utf-8"))
            norm = {}
            for k in ("conf", "conf_threshold", "cascade_conf_threshold"):
                if isinstance(raw.get(k), (int, float)):
                    norm["conf"] = float(raw[k])
                    break
            for k in ("margin", "margin_threshold", "cascade_margin_threshold"):
                if isinstance(raw.get(k), (int, float)):
                    norm["margin"] = float(raw[k])
                    break
            if norm:
                out["threshold_values"] = norm
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser(description="model bundle 治理（RA-006）")
    ap.add_argument("action", choices=["create", "publish", "rollback", "verify", "list", "current"])
    ap.add_argument("--bundle-id", default=None)
    ap.add_argument("--detector", default=None)
    ap.add_argument("--classifier", default=None)
    ap.add_argument("--registry", default=None)
    ap.add_argument("--classes", default=None)
    ap.add_argument("--thresholds", default=None)
    ap.add_argument("--dataset-hash", default="")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    if a.action == "list":
        for b in list_bundles():
            print(f"{b['bundle_id']:40s} [{b['location']}] {b['created_at']}  files={b['n_files']}  {b['reason']}")
        cur = current_bundle()
        print(f"\nCURRENT: {cur['bundle_id'] if cur else '（未发布任何 bundle）'}")
    elif a.action == "create":
        if not (a.bundle_id and a.detector and a.classifier and a.registry):
            raise SystemExit("create 需要 --bundle-id --detector --classifier --registry")
        r = create_bundle(a.bundle_id, a.detector, a.classifier, a.registry,
                          classes=a.classes, thresholds=a.thresholds,
                          dataset_hash=a.dataset_hash, note=a.note)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif a.action == "verify":
        print(json.dumps(verify_bundle(a.bundle_id), ensure_ascii=False))
    elif a.action == "publish":
        print(json.dumps(publish(a.bundle_id), ensure_ascii=False))
    elif a.action == "rollback":
        print(json.dumps(rollback(), ensure_ascii=False))
    elif a.action == "current":
        print(json.dumps(current_bundle() or {"bundle_id": None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
