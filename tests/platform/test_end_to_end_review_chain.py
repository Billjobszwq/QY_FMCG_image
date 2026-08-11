"""端到端审核链路验证（commit 11）：rq_v2 队列构建 → U5 式导入 →
review_progress 状态推导 → 区域级 gold → 失效队列隔离 → truebox 导出 →
WorkItems API 对照。

全部使用已实现的公开 API，临时 DB（tmp_path），不碰生产库；测试按文件
顺序链式推进同一 fixture，一条链走通：
build_v2/write_v2 → validate_queue_items(fail-closed)+import_review_queue →
pending→claim→awaiting_second→finalized / awaiting_arbitration→仲裁 →
区域 gold（双审一致 human_final / 分歧仲裁 gold_verified）→ 失效队列隔离 →
export_truebox_gold 严格模式 + load_truebox_v2 / gt_images_from_export →
WorkItems API 与 review_progress 同库对照。
"""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from src.data.photo_identity import validate_queue_items
from src.platform.annotate.review import (
    claim_task,
    final_box,
    gold_region_report,
    import_review_queue,
    review_progress,
    submit_review,
    task_view,
)
from src.platform.api.workitems import collect_workitems, create_workitems_router
from src.platform.data.store import PlatformStore
from src.review.review_queue_v2 import build_v2, write_v2
from src.review.truebox_export import (
    export_truebox_gold,
    gt_images_from_export,
    load_truebox_v2,
)

PHOTOS = [f"p{i}" for i in range(1, 9)]  # p1..p8
REG = {
    "可口可乐500ml": {"sku_id": "QY_KK_000001", "name": "可口可乐500ml"},
    "百事可乐330ml": {"sku_id": "QY_BS_000002", "name": "百事可乐330ml"},
}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """临时环境：合成 blobs + 权威 manifest + 协议 + tmp DB（不碰生产库）。"""
    root = tmp_path_factory.mktemp("e2e_review_chain")
    blobs = root / "blobs"
    manifest: dict[str, dict] = {}
    for pid in PHOTOS:
        data = f"photo-bytes-{pid}".encode("utf-8")
        sha = hashlib.sha256(data).hexdigest()
        bdir = blobs / sha[:2]
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / sha).write_bytes(data)
        manifest[pid] = {"sha256": sha, "width": 1600, "height": 1200,
                         "filename": f"{pid}.jpg"}
    manifest_path = root / "clean_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    protocol_path = root / "diagnostic_v1.json"
    protocol_path.write_text(json.dumps(
        {"frozen": True, "role": "diagnostic_v1", "photo_ids": PHOTOS},
        ensure_ascii=False), encoding="utf-8")
    store = PlatformStore(root / "platform.sqlite")
    ctx = {"root": root, "store": store, "manifest": manifest,
           "manifest_path": manifest_path, "protocol_path": protocol_path,
           "blobs": blobs}
    yield ctx
    store.close()


def _sha(env, pid: str) -> str:
    return env["manifest"][pid]["sha256"]


def _task(env, pid: str, mode: str) -> dict:
    row = env["store"].find_review_task(photo_id=pid, sha256=_sha(env, pid),
                                        review_mode=mode)
    assert row is not None, f"任务不存在: {pid}/{mode}"
    return row


# ---- 阶段 1：rq_v2 队列文件构建（build_v2 → write_v2）----

def test_1_build_v2_gates_and_immutable_write(env):
    queue, audit, gates = build_v2(
        protocol_path=env["protocol_path"], manifest_path=env["manifest_path"],
        blobs_dir=env["blobs"], seed=20260807, n_double=6, n_blind=3,
        git_commit="e2e-test")
    env["queue"], env["audit"] = queue, audit
    assert gates["ok"] is True  # 发布门禁全绿（blob 存在 + 现场 SHA 全对）
    assert gates["files_present"] == gates["n_unique_photos"]
    assert gates["sha_verified"] == gates["n_unique_photos"]
    assert queue["queue_version"] == "rq_v2"
    assert audit["n_tasks"] == len(queue["items"]) == 6 + 3
    assert audit["sha_verification"]["mismatches"] == 0
    out = write_v2(queue, audit, env["root"] / "review_queue_e2e.json")
    env["queue_path"] = out
    # 不可变证据链：已存在拒绝覆盖
    with pytest.raises(FileExistsError):
        write_v2(queue, audit, out)


# ---- 阶段 2：U5 式导入（fail-closed 门禁 + 幂等）----

def test_2_u5_style_import_fail_closed_then_import(env):
    store = env["store"]
    # fail-closed：ID→SHA 错配一条即不得通过门禁
    bad_items = copy.deepcopy(env["queue"]["items"])
    bad_items[0]["sha256"] = "0" * 64
    pairing_bad = validate_queue_items(bad_items,
                                       manifest_path=env["manifest_path"])
    assert pairing_bad["ok"] is False
    assert pairing_bad["allow_partial_import"] is False
    # 合法配对全绿后才允许导入
    pairing = validate_queue_items(env["queue"]["items"],
                                   manifest_path=env["manifest_path"])
    assert pairing["ok"] is True and pairing["correct"] == 9
    res = import_review_queue(store, env["queue_path"], seed=20260807)
    assert res["imported"] == 9
    # 幂等：重复导入不新增
    assert import_review_queue(store, env["queue_path"])["imported"] == 0
    prog = review_progress(store)
    assert prog["source"] == "db_events"
    assert prog["active"]["total"] == 9
    assert prog["active"]["by_status"] == {"pending": 9}
    assert prog["active"]["queue_versions"] == ["rq_v2"]


# ---- 阶段 3：状态推导（pending→claim→awaiting_second→双审一致 finalized）----

def test_3_claim_and_double_agreement_finalized(env):
    store = env["store"]
    row = _task(env, "p1", "double_review")
    env["task_p1"] = row["task_id"]
    token = row["claim_token"]
    assert task_view(store, token)["status"] == "pending"
    assert claim_task(store, token, actor="alice")["claimed"] is True
    # 已认领不得二次认领
    assert claim_task(store, token, actor="bob")["claimed"] is False
    assert task_view(store, token)["status"] == "claimed"
    box = [10.0, 10.0, 200.0, 200.0]
    out1 = submit_review(store, task_id=row["task_id"], actor="alice",
                         verdict="accepted", box=box, registry=REG)
    assert out1["status"] == "awaiting_second" and out1["needs_second"] is True
    # 双审框一致 → finalized
    out2 = submit_review(store, task_id=row["task_id"], actor="bob",
                         verdict="accepted", box=box, registry=REG)
    assert out2["finalized"] is True and out2["final_box"] == box
    assert final_box(store, row["task_id"]) == box


# ---- 阶段 4：分歧 → awaiting_arbitration → 仲裁一锤定音 ----

def test_4_disagreement_then_arbitration_finalizes(env):
    store = env["store"]
    row = _task(env, "p2", "double_review")
    tid = row["task_id"]
    env["task_p2"] = tid
    claim_task(store, row["claim_token"], actor="alice")
    # 原子性：批内一个非法区域 → 整次零落账，review 事件也不记录
    with pytest.raises(ValueError):
        submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                      box=[0, 0, 400, 300], registry=REG,
                      regions=[{"region_id": "R1", "box": [0, 0, 100, 100],
                                "sku_label": "可口可乐500ml"},
                               {"region_id": "BAD", "box": [-5, 0, 10, 10],
                                "sku_label": "可口可乐500ml"}])
    assert store.list_gold_regions(tid) == []
    assert not any(e["kind"] == "review"
                   for e in store.list_review_events(tid))
    # 合法多区域原子提交：x1/y1=0 是合法框（图片左上角）
    alice_regions = [
        {"region_id": "R1", "box": [0, 0, 100, 100],
         "sku_label": "可口可乐500ml", "package_version_id": "pkg_v1",
         "evidence": {"zoom": 2}},
        {"region_id": "R2", "box": [200, 0, 300, 100],
         "sku_label": "可口可乐500ml"},
    ]
    out1 = submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                         box=[0, 0, 400, 300], regions=alice_regions,
                         registry=REG)
    assert out1["regions_submitted"] == 2
    assert out1["status"] == "awaiting_second"
    bob_regions = [
        # 与 R1 one-to-one 几何匹配（IoU>=0.75）且 SKU 结论相同 → 一致
        {"region_id": "R1", "box": [2, 2, 102, 102],
         "sku_label": "可口可乐500ml"},
        # 与 R2 几何匹配但 SKU 结论不同 → 分歧
        {"region_id": "R2", "box": [200, 0, 300, 100],
         "sku_label": "百事可乐330ml"},
    ]
    out2 = submit_review(store, task_id=tid, actor="bob", verdict="accepted",
                         box=[0, 0, 400, 299], regions=bob_regions,
                         registry=REG)
    assert out2["status"] == "awaiting_arbitration"
    assert out2["needs_arbitration"] is True
    rep = gold_region_report(store)
    by_id: dict[str, list[dict]] = {}
    for r in rep["regions"]:
        if r["task_id"] == tid:
            by_id.setdefault(r["region_id"], []).append(r)
    assert all(r["final_status"] == "human_final" for r in by_id["R1"])
    assert all(r["final_status"] == "conflict" for r in by_id["R2"])
    # 仲裁一锤定音：任务级 finalized + 分歧区域 gold_verified
    out3 = submit_review(store, task_id=tid, actor="admin",
                         verdict="adjudicated", box=[0, 0, 400, 300],
                         role="arbiter", registry=REG,
                         regions=[{"region_id": "R2",
                                   "box": [200, 0, 300, 100],
                                   "sku_label": "可口可乐500ml"}])
    assert out3["finalized"] is True


# ---- 阶段 5：区域级 gold 终态推导（仲裁只覆盖分歧区域）----

def test_5_region_gold_states_and_arbitration_scope(env):
    store = env["store"]
    tid = env["task_p2"]
    rep = gold_region_report(store)
    mine = [r for r in rep["regions"] if r["task_id"] == tid]
    states = {(r["region_id"], r["final_status"]) for r in mine}
    # 未分歧区域 R1 保持 human_final，不被仲裁覆盖
    assert ("R1", "human_final") in states
    # 分歧区域 R2 由仲裁产出 gold_verified
    assert ("R2", "gold_verified") in states
    # 原分歧提交仅留痕（superseded），且不再残留 conflict
    assert sum(1 for r in mine if r["final_status"] == "superseded") == 2
    assert not any(r["final_status"] == "conflict" for r in mine)
    r1 = next(r for r in mine if r["region_id"] == "R1"
              and r["final_status"] == "human_final")
    assert r1["n_agree"] == 2 and r1["actor"] == "alice"
    r2 = next(r for r in mine if r["region_id"] == "R2"
              and r["final_status"] == "gold_verified")
    assert r2["role"] == "arbiter" and r2["actor"] == "admin"


# ---- 阶段 6：另一双审任务多区域一致 → human_final ----

def test_6_second_task_region_agreement_human_final(env):
    store = env["store"]
    row = _task(env, "p3", "double_review")
    tid = row["task_id"]
    env["task_p3"] = tid
    claim_task(store, row["claim_token"], actor="carol")
    regs = [{"region_id": "X", "box": [0, 0, 50, 60],
             "sku_label": "可口可乐500ml"},
            {"region_id": "Y", "box": [100, 100, 180, 200],
             "sku_label": "百事可乐330ml"}]
    out1 = submit_review(store, task_id=tid, actor="carol", verdict="accepted",
                         box=[0, 0, 200, 220], regions=regs, registry=REG)
    assert out1["status"] == "awaiting_second"
    sub = [r for r in gold_region_report(store)["regions"] if r["task_id"] == tid]
    assert {r["final_status"] for r in sub} == {"submitted"}  # 等二审
    out2 = submit_review(store, task_id=tid, actor="dave", verdict="accepted",
                         box=[0, 0, 200, 220], regions=regs, registry=REG)
    assert out2["finalized"] is True
    sub = [r for r in gold_region_report(store)["regions"] if r["task_id"] == tid]
    assert all(r["final_status"] == "human_final" and r["n_agree"] == 2
               for r in sub)


# ---- 阶段 7：失效队列隔离（不进 review_progress / WorkItems 默认视图）----

def test_7_invalidated_queue_isolated_from_default_views(env):
    store = env["store"]
    old_path = env["root"] / "rq_v1_test.json"
    old_path.write_text(json.dumps({
        "queue_version": "rq_v1_test", "protocol": "diagnostic_v1",
        "items": [{"photo_id": "p_old", "sha256": "ab" * 32,
                   "review_mode": "double_review",
                   "requires_second_review": True, "status": "pending"}],
    }), encoding="utf-8")
    assert import_review_queue(store, old_path)["imported"] == 1
    old_tid = store.find_review_task(photo_id="p_old", sha256="ab" * 32,
                                     review_mode="double_review")["task_id"]
    store.register_queue_version(queue_version="rq_v1_test",
                                 protocol="diagnostic_v1", n_tasks=1,
                                 source_path=str(old_path))
    store.register_queue_version(queue_version="rq_v2",
                                 protocol="diagnostic_v1", n_tasks=9,
                                 source_path=str(env["queue_path"]))
    store.invalidate_queue_version(queue_version="rq_v1_test",
                                   reason="invalid_id_sha_mapping",
                                   superseded_by="rq_v2")
    prog = review_progress(store)
    assert prog["invalid"]["total"] == 1
    assert prog["invalid"]["queue_versions"] == ["rq_v1_test"]
    assert prog["active"]["total"] == 9
    assert old_tid not in {t["task_id"] for t in prog["active"]["tasks"]}
    # 历史行仍在（追加式失效，不删除）
    assert len(store.list_review_tasks()) == 10
    # WorkItems 投影同样隔离失效队列任务；另（ABOSV2-P0-001/D-010）
    # rq_v2 族已被 supersession 账本取代：current 不含，all 保留历史。
    current = collect_workitems(store)
    review_items = [w for w in current["items"]
                    if w["kind"] == "human_review"]
    assert review_items == []
    assert all(w["id"] != f"review:{old_tid}" for w in current["items"])
    all_items = [w for w in collect_workitems(
        store, projection="all")["items"] if w["kind"] == "human_review"]
    assert len(all_items) == 9
    assert all(w["id"] != f"review:{old_tid}" for w in all_items)
    assert all(w["superseded"] for w in all_items)


# ---- 阶段 8：truebox 导出（严格模式只含终态 + 解析自洽 + GT 非空）----

def test_8_truebox_export_strict_and_self_consistent(env):
    store = env["store"]
    out_path = env["root"] / "diagnostic_v1_truebox_v2.json"
    res = export_truebox_gold(store, out_path=out_path,
                              manifest_path=env["manifest_path"],
                              protocol_path=env["protocol_path"],
                              git_commit="e2e-test")
    assert res["written"] is True
    c = res["counts"]
    assert c["human_final"] == 3      # R1 + X + Y
    assert c["gold_verified"] == 1    # R2 仲裁
    assert c["exported"] == 4 and c["photos"] == 2
    assert c["excluded_superseded"] == 2  # superseded 留痕绝不进导出
    doc = load_truebox_v2(out_path)   # export_hash 自洽校验
    assert {r["final_status"] for r in doc["records"]} == {
        "human_final", "gold_verified"}  # 严格模式只含终态
    gt = gt_images_from_export(doc)
    assert gt and all(im["boxes"] for im in gt)
    assert {im["image_id"] for im in gt} == {"p2", "p3"}
    # 不可变制品：同路径重复导出拒绝
    with pytest.raises(FileExistsError):
        export_truebox_gold(store, out_path=out_path,
                            manifest_path=env["manifest_path"],
                            protocol_path=env["protocol_path"],
                            git_commit="e2e-test")


# ---- 阶段 9：WorkItems API 与 review_progress 数量一致（同库对照）----

def test_9_workitems_api_matches_review_progress(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    store = env["store"]
    prog = review_progress(store)
    # ABOSV2-P0-001/D-010：rq_v2 族已被 supersession 取代；口径一致性
    # 在 projection=all 上对照，current 必须为 0。
    wi = collect_workitems(store, projection="all")
    review_items = [w for w in wi["items"] if w["kind"] == "human_review"]
    assert len(review_items) == prog["active"]["total"] == 9
    assert wi["summary"]["pending_review"] == \
        prog["active"]["by_status"].get("pending", 0)
    derived = {t["task_id"]: t["status"] for t in prog["active"]["tasks"]}
    for w in review_items:
        tid = w["id"].split(":", 1)[1]
        assert derived[tid] == w["status"]
    # API 层（同库）：默认 current=0；projection=all 计数一致
    app = FastAPI()
    app.include_router(create_workitems_router(store))
    tc = TestClient(app)
    r = tc.get("/api/v1/workitems",
               params={"kind": "human_review", "limit": 500})
    assert r.status_code == 200
    assert r.json()["count"] == 0
    r = tc.get("/api/v1/workitems",
               params={"kind": "human_review", "limit": 500,
                       "projection": "all"})
    assert r.status_code == 200
    assert r.json()["count"] == prog["active"]["total"]
