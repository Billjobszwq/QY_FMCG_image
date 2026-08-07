"""commit 8（任务书§十）：把已发布 rq_v2 审核队列接入 Label Studio，使人工真正可标注。

创建两个新项目（multipart 上传图片；/data/local-files/ 403 不可用，不得重启 LS）：
- diag_v2_assisted：double_review 双审（200 任务）
- diag_v2_blind：blind_manual 盲审（50 任务，零模型信息）

实测 LS 1.23 行为（驱动设计的依据）：
- 单次 multipart 请求含多个 files 字段时只落 1 个 FileUpload → 必须逐张导入；
- 上传后存储文件名带随机前缀（原名仅保留尾段）→ 无法事后按文件名反查，
  改为逐张导入后用“新增 task id”定位（导入前快照 task id 集合）。

守护约束：
- 项目 10~13 与 1 绝不删除/覆盖/改动：创建前后校验存在性与标题不变
- 幂等：目标项目名已存在即中止（不重复创建）
- 证据文件已存在即拒绝覆盖

用法：python -m scripts.create_ls_v2_projects
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUEUE = PROJECT_ROOT / ".review_queue" / "review_queue_diag_v2.json"
BLOBS = PROJECT_ROOT / ".batch3_clean" / "blobs"
LABEL_CONFIG = PROJECT_ROOT / "configs" / "label-studio" / "label_config.xml"
EVIDENCE = PROJECT_ROOT / ".review_queue" / "ls_v2_evidence.json"
GUARD_IDS = (10, 11, 12, 13)  # 绝不删除/覆盖/改动的项目

PROJECT_SPECS = {
    "assisted": (
        "diag_v2_assisted",
        "rq_v2 诊断队列 assisted 侧：double_review 双审（200 任务）。"
        "来源 review_queue_diag_v2.json（queue_version=rq_v2）。人工标注：绘制/修正商品框 + SKU + 裁决状态。"),
    "blind": (
        "diag_v2_blind",
        "rq_v2 诊断队列 blind 侧：blind_manual 盲审（50 任务）。"
        "零模型信息（no prediction），标注者不得见任何模型输出。"),
}


def _guard_check(ls, phase: str) -> dict[int, str]:
    """校验 10~13 项目存在，返回 {id: title}。"""
    projects = ls.list_projects()
    by_id = {p["id"]: p["title"] for p in projects}
    result = {}
    for pid in GUARD_IDS:
        if pid not in by_id:
            raise SystemExit(f"[守护失败-{phase}] 项目 {pid} 不存在")
        result[pid] = by_id[pid]
    return result


def _task_ids(ls, pid: int) -> set[int]:
    # LS 1.23：空项目 GET /api/projects/{pid}/tasks 返回 404，视为空集
    r = ls.s.get(f"{ls.url}/api/projects/{pid}/tasks",
                 params={"page": 1, "page_size": 1000}, timeout=60)
    if r.status_code == 404:
        return set()
    if r.status_code >= 400:
        raise RuntimeError(f"list tasks 失败: {r.status_code} {r.text[:200]}")
    d = r.json()
    tasks = d if isinstance(d, list) else d.get("tasks", d.get("results", []))
    return {t["id"] for t in tasks}


def main() -> None:
    from src.ls_platform.ls_client import LSClient
    from src.review.ls_v2_payload import build_ls_v2_payloads

    if EVIDENCE.exists():
        raise SystemExit(f"[幂等中止] 证据文件已存在，拒绝覆盖: {EVIDENCE}")

    ls = LSClient()
    print(f"[info] whoami: {ls.whoami().get('email')} @ {ls.url}")

    # 创建前守护：10~13 存在，记录标题快照
    guard_before = _guard_check(ls, "before")
    print(f"[guard-before] 10~13 标题快照: {guard_before}")

    # 幂等：目标项目名已存在即中止
    names = {p["title"]: p["id"] for p in ls.list_projects()}
    for title, _ in PROJECT_SPECS.values():
        if title in names:
            raise SystemExit(f"[幂等中止] 项目已存在: {title} (id={names[title]})")

    # label config：优先复用，缺失则生成（不改生成器逻辑）
    if LABEL_CONFIG.exists():
        xml = LABEL_CONFIG.read_text(encoding="utf-8")
        print(f"[info] 复用 label config: {LABEL_CONFIG}")
    else:
        from src.ls_platform.gen_label_config import REGISTRY, build_config
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        xml = build_config(registry)
        LABEL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        LABEL_CONFIG.write_text(xml, encoding="utf-8")
        print(f"[info] 已生成 label config: {LABEL_CONFIG}")

    # 队列 → payload（fail-closed：blob 缺失即抛错）
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    if queue.get("queue_version") != "rq_v2":
        raise SystemExit(f"queue_version 非 rq_v2: {queue.get('queue_version')}")
    payloads = build_ls_v2_payloads(queue, BLOBS)
    ev0 = payloads["evidence"]
    print(f"[payload] assisted={ev0['n_assisted']} blind={ev0['n_blind']} "
          f"唯一照片={ev0['n_unique_photos']} 重叠={len(ev0['overlap_photo_ids'])}")
    if ev0["n_assisted"] != 200 or ev0["n_blind"] != 50:
        raise SystemExit(f"任务数不符预期（200/50）: {ev0}")

    created: dict[str, int] = {}
    report: dict[str, dict] = {}
    for side, (title, desc) in PROJECT_SPECS.items():
        proj = ls.create_project(title, xml, description=desc)
        pid = proj["id"]
        created[side] = pid
        print(f"[create] {title} -> project id={pid}  人工入口: {ls.url}/projects/{pid}")

        tasks = payloads[side]
        uploaded, patched, failures = 0, 0, []
        known_ids = _task_ids(ls, pid)  # 新项目应为空集
        for n, t in enumerate(tasks, 1):
            resp = ls.import_files(pid, files=[(t["filename"], Path(t["blob_path"]).read_bytes())])
            if resp.get("task_count") != 1:
                raise SystemExit(f"[fail-closed] {title} 第 {n} 张导入异常: {resp}")
            uploaded += 1
            # 定位新建 task（id 集合差分），回填 meta（LSClient 无 PATCH 方法，
            # 直接用其鉴权会话调用 PATCH /api/tasks/{id}/，于此记录）
            new_ids = _task_ids(ls, pid) - known_ids
            if len(new_ids) != 1:
                raise SystemExit(f"[fail-closed] {title} 第 {n} 张未定位到唯一新 task: {new_ids}")
            ls_task_id = new_ids.pop()
            known_ids.add(ls_task_id)
            meta = dict(t["meta"])
            meta["ls_task_id"] = ls_task_id
            r = ls.s.patch(f"{ls.url}/api/tasks/{ls_task_id}/",
                           json={"meta": meta}, timeout=60)
            if r.status_code >= 400:
                raise RuntimeError(f"PATCH task {ls_task_id} meta 失败: {r.status_code} {r.text[:200]}")
            patched += 1
            if n % 25 == 0 or n == len(tasks):
                print(f"  [upload+meta] {n}/{len(tasks)}")
        report[side] = {"project_id": pid, "expected": len(tasks),
                        "uploaded": uploaded, "meta_patched": patched, "failures": failures}

    # 创建后守护：10~13 仍存在且标题未变
    guard_after = _guard_check(ls, "after")
    for pid in GUARD_IDS:
        if guard_after[pid] != guard_before[pid]:
            raise SystemExit(f"[守护失败-after] 项目 {pid} 标题被改动: "
                             f"{guard_before[pid]!r} -> {guard_after[pid]!r}")
    print(f"[guard-after] 10~13 校验通过，标题未变: {guard_after}")

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT).decode().strip()
    evidence = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "queue_file": str(QUEUE),
        "queue_version": "rq_v2",
        "projects": created,
        "project_titles": {side: PROJECT_SPECS[side][0] for side in created},
        "task_counts": {side: report[side]["expected"] for side in created},
        "uploads": report,
        "n_unique_photos": ev0["n_unique_photos"],
        "overlap_photo_ids": ev0["overlap_photo_ids"],
        "guard_projects_10_13": {"before": guard_before, "after": guard_after,
                                 "unchanged": guard_before == guard_after},
        "human_entry_examples": [f"{ls.url}/projects/{pid}" for pid in created.values()],
    }
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[evidence] 已写入: {EVIDENCE}")
    for side, pid in created.items():
        print(f"[入口] {side}: {ls.url}/projects/{pid}")


if __name__ == "__main__":
    main()
