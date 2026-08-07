"""diagnostic_v1_truebox_v2 正式导出器（任务书§十三）。

gold_region_v1 → diagnostic_v1_truebox_v2 → run_truebox_eval 的正式出口：
- 只有 human_final / gold_verified 终态区域可进入导出；prediction/
  unreviewed/submitted/conflict/superseded/失效队列区域一律禁止进入；
- 严格模式（默认，fail-closed）：出现 submitted/conflict 区域或失效
  队列区域 → 拒绝整次导出；strict=False 时仅排除（仍绝不进入导出）；
- 不可变：目标路径已存在 → FileExistsError，绝不覆盖；
- 0 gold 不写文件（无真值不得产出空真值文件）；
- 可审计：export_version/export_hash/protocol_hash/git_commit/
  source_queue_versions 全量留痕。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.platform.annotate.review import (
    DOUBLE_REVIEW_IOU_THRESHOLD,
    _iou,
    gold_region_report,
)

EXPORT_VERSION = "diagnostic_v1_truebox_v2"
TERMINAL_STATUSES = ("human_final", "gold_verified")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_git_commit(repo_root: Path | str | None = None) -> str:
    """当前 HEAD commit（审计字段）；无法解析时返回空串，不伪造。"""
    cmd = ["git", "rev-parse", "HEAD"]
    if repo_root is not None:
        cmd += ["--git-dir", str(Path(repo_root) / ".git")]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             cwd=str(repo_root) if repo_root else None,
                             check=False)
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def load_manifest(path: Path | str) -> dict[str, dict]:
    """尺寸权威源 clean_manifest.json：photo_id → {sha256,width,height,...}"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest 必须是 photo_id 索引的 dict: {path}")
    return data


def _label_source(final_status: str, n_agree: int) -> str:
    if final_status == "gold_verified":
        return "arbitration"
    return "double_review_agreement" if n_agree >= 2 else "single_review"


def _partner_actor(region: dict, siblings: list[dict]) -> str | None:
    """双审一致区域的另一位审核人：同任务内不同 actor、几何匹配
    （IoU>=阈值）的区域；确定性取 IoU 最高者。"""
    best, best_iou = None, DOUBLE_REVIEW_IOU_THRESHOLD
    for r in siblings:
        if r["actor"] == region["actor"] or r["role"] == "arbiter":
            continue
        v = _iou(r["box"], region["box"])
        if v >= DOUBLE_REVIEW_IOU_THRESHOLD and v > best_iou:
            best, best_iou = r["actor"], v
    return best


def build_truebox_export(store, *, manifest: dict[str, dict],
                         protocol_path: Path | str,
                         strict: bool = True,
                         git_commit: str | None = None) -> dict[str, Any]:
    """构建 v2 导出文档（纯函数，不落盘）。

    严格模式 fail-closed：submitted/conflict 区域或失效队列区域出现
    即拒绝整个导出；非严格模式仅输出终态区域（被禁类别仍绝不进入）。
    """
    protocol_path = Path(protocol_path)
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))

    tasks = {t["task_id"]: t for t in store.list_review_tasks()}
    active_ids = {t["task_id"] for t in store.list_review_tasks_active()}
    report = gold_region_report(store)

    counts = {"exported": 0, "human_final": 0, "gold_verified": 0,
              "excluded_submitted": 0, "excluded_conflict": 0,
              "excluded_superseded": 0, "rejected_invalid_queue": 0,
              "photos": 0}
    strict_violations: list[str] = []
    kept: list[dict] = []
    for r in report["regions"]:
        t = tasks.get(r["task_id"])
        if t is None:
            continue  # 无任务引用的孤儿区域，fail-closed 不导出
        if r["task_id"] not in active_ids:
            counts["rejected_invalid_queue"] += 1  # 失效队列禁入（绝对）
            if strict:
                strict_violations.append(
                    f"失效队列区域: task={r['task_id']} "
                    f"queue={t.get('queue_version')} region={r['region_id']}")
            continue
        st = r["final_status"]
        if st in TERMINAL_STATUSES:
            kept.append(r)
            counts[st] += 1
            counts["exported"] += 1
        else:
            counts[f"excluded_{st}"] = counts.get(f"excluded_{st}", 0) + 1
            if strict and st in ("submitted", "conflict"):
                strict_violations.append(
                    f"非终态区域({st}): task={r['task_id']} "
                    f"region={r['region_id']}")
    if strict and strict_violations:
        raise ValueError(
            "严格模式拒绝导出（fail-closed），存在禁止进入的区域：\n"
            + "\n".join(strict_violations[:20]))

    # 按 photo 聚合全部最终 boxes；尺寸/sha 一律以 manifest 为准
    by_photo: dict[str, list[dict]] = {}
    for r in kept:
        by_photo.setdefault(r["photo_id"], []).append(r)
    images: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    queue_versions: set[str] = set()
    for photo_id in sorted(by_photo):
        recs = sorted(by_photo[photo_id],
                      key=lambda r: (r["task_id"], r["region_id"]))
        m = manifest.get(photo_id)
        if m is None:
            raise ValueError(
                f"photo 不在 clean_manifest（尺寸权威源缺失，fail-closed）: "
                f"{photo_id}")
        sha = str(recs[0]["sha256"])
        if m.get("sha256") != sha:
            raise ValueError(
                f"photo_sha256 与 manifest 不一致（fail-closed）: {photo_id}")
        width, height = int(m["width"]), int(m["height"])
        image_uri = f".batch3_clean/blobs/{sha[:2]}/{sha}"
        boxes = sorted([float(v) for v in r["box"]] for r in recs)
        images.append({"image_id": photo_id, "photo_id": photo_id,
                       "photo_sha256": sha, "image_uri": image_uri,
                       "width": width, "height": height, "boxes": boxes})
        task_regions = {r["task_id"]: [
            x for x in store.list_gold_regions(r["task_id"])]
            for r in recs}
        for r in recs:
            t = tasks[r["task_id"]]
            siblings = task_regions[r["task_id"]]
            reviewer = r["actor"]
            second = arbiter = None
            if r["final_status"] == "gold_verified":
                arbiter = r["actor"]
                annotators = sorted({x["actor"] for x in siblings
                                     if x["role"] != "arbiter"})
                reviewer = annotators[0] if annotators else None
                second = annotators[1] if len(annotators) > 1 else None
            elif int(r.get("n_agree", 1)) >= 2:
                pair = sorted({r["actor"],
                               _partner_actor(r, siblings) or r["actor"]})
                reviewer, second = pair[0], pair[1]
            records.append({
                "image_id": photo_id, "photo_id": photo_id,
                "photo_sha256": sha, "image_uri": image_uri,
                "width": width, "height": height, "boxes": boxes,
                "box": [float(v) for v in r["box"]],
                "task_id": r["task_id"], "region_id": r["region_id"],
                "sku_id": r["sku_id"], "sku_name": r["sku_name"],
                "package_version_id": r.get("package_version_id", ""),
                "label_source": _label_source(r["final_status"],
                                              int(r.get("n_agree", 1))),
                "reviewer": reviewer, "second_reviewer": second,
                "arbiter": arbiter, "final_status": r["final_status"],
                "evidence": r.get("evidence") or {},
                "evidence_ids": sorted((r.get("evidence") or {}).keys()),
                "group_store": r.get("group_store", ""),
                "group_session": r.get("group_session", ""),
                "near_dup_group": r.get("near_dup_group", ""),
                "queue_version": t.get("queue_version", ""),
            })
            queue_versions.add(str(t.get("queue_version", "")))
    counts["photos"] = len(images)

    if git_commit is None:
        git_commit = resolve_git_commit(_REPO_ROOT)
    body = {
        "export_version": EXPORT_VERSION,
        "created_at": _utcnow(),
        "strict": bool(strict),
        "protocol": protocol.get("role", "diagnostic_v1"),
        "protocol_hash": protocol_hash,
        "git_commit": git_commit,
        "source_queue_versions": sorted(queue_versions),
        "counts": counts,
        "images": images,
        "records": records,
    }
    body["export_hash"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True
                   ).encode("utf-8")).hexdigest()
    return body


def export_truebox_gold(store, *, out_path: Path | str,
                        manifest_path: Path | str,
                        protocol_path: Path | str,
                        strict: bool = True,
                        git_commit: str | None = None) -> dict[str, Any]:
    """正式导出入口（构建 + 不可变落盘）。

    0 gold → 不写文件（fail-closed）；目标已存在 → FileExistsError。
    """
    out_path = Path(out_path)
    doc = build_truebox_export(
        store, manifest=load_manifest(manifest_path),
        protocol_path=protocol_path, strict=strict, git_commit=git_commit)
    counts = doc["counts"]
    if counts["exported"] == 0:
        return {"written": False, "path": None, "counts": counts,
                "export_hash": doc["export_hash"],
                "reason": "无 gold 终态区域，不写空真值文件（fail-closed）"}
    if out_path.exists():
        raise FileExistsError(
            f"导出文件已存在，不可变制品禁止覆盖: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(out_path)  # 原子写
    return {"written": True, "path": str(out_path), "counts": counts,
            "export_hash": doc["export_hash"]}


def load_truebox_v2(path: Path | str) -> dict[str, Any]:
    """解析 v2 导出文档并校验 export_hash 自洽（审计完整性）。"""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("export_version") != EXPORT_VERSION:
        raise ValueError(f"非 {EXPORT_VERSION} 文档: {path}")
    body = {k: v for k, v in doc.items() if k != "export_hash"}
    expect = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True
                   ).encode("utf-8")).hexdigest()
    if doc.get("export_hash") != expect:
        raise ValueError(f"export_hash 校验失败（文档被改动？）: {path}")
    return doc


def gt_images_from_export(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """v2 文档 → run_truebox_eval 的 GT 视图 [{"image_id","boxes"}]。"""
    return [{"image_id": im["image_id"], "boxes": im["boxes"]}
            for im in doc.get("images", [])]
