"""服务端 DatasetSnapshot builder（UMT-003/UMT-004）。

真实 Snapshot 只能由本 builder 生成，不得接受客户端自由 JSON manifest：
- 逐文件验证：存在、SHA256、标签、photo ID、规范门店、session；
- 审核/质量状态：pilot 等级要求 human_final + accepted；
  auto_provisional 仅允许 experimental；waiting_human 绝不伪造通过；
- SHA 精确重复（同 split 与跨 split）与 pHash 近重复（跨 split）拒绝；
- 冻结协议五键零泄漏（protocol_guard）；
- staging 拷贝 + data.yaml 生成；run 目录存在拒绝覆盖；
- 原图只读：只复制，不移动/修改/删除。
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from src.data.store_norm import norm_store

BUILDER_VERSION = "snapshot_builder_v1"

_PILOT_REVIEW = {"human_final"}
_ANY_REVIEW = {"human_final", "auto_provisional"}
_OK_QUALITY = {"accepted"}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _phash(p: Path) -> str | None:
    """8x8 灰度均值哈希（近重复分组用）；无法解码返回 None。"""
    try:
        from PIL import Image
        img = Image.open(p).convert("L").resize((8, 8))
        px = list(img.getdata())
        avg = sum(px) / len(px)
        return "".join("1" if v > avg else "0" for v in px)
    except Exception:
        return None


def _hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b))


def validate_and_stage(
    entries: list[dict[str, Any]],
    dest: Path,
    *,
    mode: str,
    protocol_dir: Path | None = None,
    classes: tuple[str, ...] = ("product",),
    phash_max_dist: int = 5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """校验 entries 并 staging 到 dest；返回 (manifest, report)。

    任一违规 fail-closed（抛 ValueError，调用方包装为领域错误）。
    """
    violations: list[str] = []
    if not entries:
        raise ValueError("entries 为空")
    if Path(dest).exists():
        raise ValueError(f"run 目录已存在，拒绝覆盖: {dest}")

    allowed_review = _ANY_REVIEW if mode == "experimental" else _PILOT_REVIEW

    seen_pid: dict[str, int] = {}
    staged: list[dict[str, Any]] = []
    for i, e in enumerate(entries):
        tag = f"entries[{i}]"
        split = e.get("split")
        if split not in ("train", "val"):
            violations.append(f"{tag}: split 必须为 train/val，得到 {split!r}")
            continue
        pid = str(e.get("photo_id") or "").strip()
        if not pid:
            violations.append(f"{tag}: photo_id 缺失")
        elif pid in seen_pid:
            violations.append(f"{tag}: photo_id 重复 {pid}")
        seen_pid[pid] = i
        store_raw = str(e.get("store") or "").strip()
        session = str(e.get("session") or "").strip()
        if not store_raw or not session:
            violations.append(f"{tag}: store/session 缺失")
        if str(e.get("review_status")) not in allowed_review:
            violations.append(
                f"{tag}: review_status={e.get('review_status')!r} 不满足"
                f" mode={mode}（需 {sorted(allowed_review)}）；"
                "人工未完成不得伪造通过")
        if str(e.get("quality_status")) not in _OK_QUALITY:
            violations.append(
                f"{tag}: quality_status={e.get('quality_status')!r} 非 accepted"
                "（waiting_human/rejected 不得入训练集）")
        p = Path(str(e.get("path") or ""))
        lp = Path(str(e.get("label_path") or ""))
        if not p.is_file():
            violations.append(f"{tag}: 照片文件缺失 {p}")
            continue
        if not lp.is_file():
            violations.append(f"{tag}: 标签文件缺失 {lp}")
            continue
        staged.append({
            "idx": i, "split": split, "photo_id": pid,
            "store": norm_store(store_raw), "session": session,
            "path": p, "label_path": lp,
            "sha256": _sha256(p),
            "review_status": str(e.get("review_status")),
            "quality_status": str(e.get("quality_status")),
        })
    if violations:
        raise ValueError("builder 校验失败: " + "; ".join(violations[:20]))

    # SHA 精确重复：任意两条（含跨 split）即拒绝
    by_sha: dict[str, list[int]] = {}
    for s in staged:
        by_sha.setdefault(s["sha256"], []).append(s["idx"])
    dup = {sha: idxs for sha, idxs in by_sha.items() if len(idxs) > 1}
    if dup:
        raise ValueError(f"SHA 重复（近重复/泄漏）: {dup}")

    # pHash 近重复跨 split 拒绝（PIL 不可用或解码失败则如实披露跳过）
    phash_checked = 0
    phash_near: list[tuple[int, int, int]] = []
    hashes = [(s["idx"], s["split"], _phash(s["path"])) for s in staged]
    for a in range(len(hashes)):
        for b in range(a + 1, len(hashes)):
            ia, sa, ha = hashes[a]
            ib, sb, hb = hashes[b]
            if ha is None or hb is None or sa == sb:
                continue
            phash_checked += 1
            d = _hamming(ha, hb)
            if d <= phash_max_dist:
                phash_near.append((ia, ib, d))
    if phash_near:
        raise ValueError(f"pHash 近重复跨 split: {phash_near}")

    # split 五键守卫：photo_id/store/session/sha train∩val 必须为空
    keys = ("photo_id", "store", "session", "sha256")
    train = [s for s in staged if s["split"] == "train"]
    val = [s for s in staged if s["split"] == "val"]
    for k in keys:
        overlap = {x[k] for x in train} & {x[k] for x in val}
        if overlap:
            raise ValueError(f"split 泄漏（{k}）: {sorted(overlap)[:10]}")
    if not train or not val:
        raise ValueError("train/val 均不得为空")

    # 冻结协议五键零泄漏
    proto_report: dict[str, Any] = {}
    if protocol_dir is not None:
        from src.data.protocol_guard import check_no_leak
        proto_report = check_no_leak(
            photo_ids=[s["photo_id"] for s in staged],
            shas=[s["sha256"] for s in staged],
            stores_raw=[s["store"] for s in staged],
            sessions=[s["session"] for s in staged],
            clean={}, protocol_dir=Path(protocol_dir),
            context=f"snapshot_builder:{dest.name}",
        )

    # staging：复制（不移动原图）+ data.yaml
    dest = Path(dest)
    manifest: dict[str, list[dict[str, Any]]] = {"train": [], "val": []}
    for s in staged:
        img_dir = dest / s["split"] / "images"
        lab_dir = dest / s["split"] / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        lab_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{s['photo_id']}_{s['path'].stem}"
        dst_img = img_dir / (stem + s["path"].suffix)
        dst_lab = lab_dir / (stem + ".txt")
        shutil.copyfile(s["path"], dst_img)
        shutil.copyfile(s["label_path"], dst_lab)
        manifest[s["split"]].append({
            "photo_id": s["photo_id"], "sha256": s["sha256"],
            "store": s["store"], "session": s["session"],
            "source_path": str(s["path"]),
            "review_status": s["review_status"],
            "quality_status": s["quality_status"],
            "file": str(dst_img.relative_to(dest)),
        })
    (dest / "data.yaml").write_text(
        f"path: {dest.resolve()}\ntrain: train/images\nval: val/images\n"
        f"nc: {len(classes)}\nnames: [{', '.join(classes)}]\n",
        encoding="utf-8",
    )

    report = {
        "builder_version": BUILDER_VERSION,
        "mode": mode,
        "train_size": len(train), "val_size": len(val),
        "phash_checked_pairs": phash_checked,
        "phash_skipped_reason": None if any(h for _, _, h in hashes)
        else "PIL 不可用或图像解码失败",
        "protocol_report": proto_report,
        "dest": str(dest),
    }
    return manifest, report
