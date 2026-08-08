"""纠偏 Task 2/3/5：追加式 reconciliation + 真实 Cycle + 黑板/记忆/任务板。

幂等：重复运行不重复插入；hash 冲突 fail-closed。
历史节点经 reconciliation event 标记，不伪造重新执行。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.platform.data.store import PlatformStore
from src.platform.reconciliation import (CORRECT_STATUS,
                                         ReconciliationService)
from src.platform.agents.blackboard import BlackboardService, MemoryService

RUN_ID = "recon-" + uuid.uuid4().hex[:8]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    store = PlatformStore(ROOT / ".platform/platform.sqlite")
    svc = ReconciliationService(store)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "diff", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True).stdout
    dirty_hash = hashlib.sha256(dirty.encode()).hexdigest()

    # ---- 7 model artifacts ----
    models = [
        ("nextgen_detector_smoke_v1", ".models/nextgen_detector_smoke_v1/weights/best.pt",
         "d1_detector_smoke_v1", "yolo11n.pt(public)", "sam_verified_pseudo",
         "smoke_pseudo_interim", CORRECT_STATUS["m1"], "1 epoch smoke"),
        ("nextgen_segmenter_smoke_v1", ".models/nextgen_segmenter_smoke_v1/weights/best.pt",
         "d2_segmenter_smoke_v1", "yolo11n-seg.pt(public)", "sam_verified_pseudo",
         "smoke_pseudo_interim", CORRECT_STATUS["m2"], "1 epoch smoke"),
        ("nextgen_classifier_cropped_v1", ".models/nextgen_classifier_cropped_v1/weights/best.pt",
         "d3_cropped_classifier_v1", "resnet18-imagenet(public)",
         "user_provided_cropped", "user_labeled_leaked_split",
         CORRECT_STATUS["m3_random"], "random split leaked"),
        ("nextgen_classifier_grouped_v1", ".models/nextgen_classifier_grouped_v1/weights/best.pt",
         "d3_cropped_classifier_v2_grouped", "resnet18-imagenet(public)",
         "user_provided_cropped", "user_labeled",
         CORRECT_STATUS["m3_grouped"], "grouped baseline not candidate"),
        ("nextgen_vlm_cropped_v1", ".models/nextgen_vlm_cropped_v1/adapters/adapters.safetensors",
         "d4_cropped_vlm_v1", "mlx-community/Qwen3-VL-4B-Instruct-4bit",
         "user_provided_cropped", "pseudo_mask_interim",
         CORRECT_STATUS["m4_old"], "KB coverage zero"),
        ("nextgen_sam_decoder_v1", ".models/nextgen_sam_decoder_v1/mask_decoder_ft.pt",
         "sam_crop_masks", "sam2.1_hiera_small(frozen)", "sam_pseudo",
         "pseudo_mask_interim", CORRECT_STATUS["sam_v1"], "self-consistency only"),
        ("nextgen_sam_decoder_v2", ".models/nextgen_sam_decoder_v2/mask_decoder_ft.pt",
         "sam_crop_masks", "sam2.1_hiera_small(frozen)", "sam_pseudo",
         "pseudo_mask_interim", CORRECT_STATUS["sam_v2"], "self-consistency only"),
    ]
    snaps4 = json.loads((ROOT / "reports/nextgen_v2/four_snapshots_v3.json").read_text())
    reg = {"artifacts": [], "snapshots": [], "evals": []}
    for aid, rel, ds, base, lsrc, evl, status, blocker in models:
        p = ROOT / rel
        ds_sha = snaps4.get(ds.replace("d1_detector_smoke_v1", "detector_snapshot_v3")
                           .replace("d2_segmenter_smoke_v1", "segmenter_snapshot_v3")
                           .replace("d3_cropped_classifier_v1", "classifier_snapshot_v3")
                           .replace("d3_cropped_classifier_v2_grouped", "classifier_snapshot_v3")
                           .replace("d4_cropped_vlm_v1", "vlm_snapshot_v3"), "")
        r = svc.register_artifact(
            artifact_id=aid, kind="model", path=str(p), sha256=sha(p),
            dataset_manifest_sha=ds_sha, source_commit=head,
            dirty_diff_hash=dirty_hash, model_base=base, label_source=lsrc,
            evidence_level=evl, candidate_status=status, blocker=blocker,
            actor="reconciliation", run_id=RUN_ID)
        reg["artifacts"].append((aid, r["duplicate"]))

    # ---- 4 snapshots ----
    for sid, msha in snaps4.items():
        r = svc.register_snapshot(
            snapshot_id=sid, path=str(ROOT / ".datasets_nextgen" / sid),
            manifest_sha=msha,
            label_source="user_provided_cropped" if "classifier" in sid
            or "vlm" in sid else "sam_verified_pseudo",
            evidence_level="user_labeled" if "classifier" in sid or "vlm" in sid
            else "pseudo_mask_interim",
            leakage_policy="grouped", actor="reconciliation", run_id=RUN_ID)
        reg["snapshots"].append((sid, r["duplicate"]))

    # ---- 7 evaluations ----
    evals = [
        ("grouped_split_comparison", "reports/nextgen_v2/classifier_split_compare.json",
         "user_labeled"),
        ("sku_readiness_policy", "reports/nextgen_v2/sku_data_readiness_policy_v1.json",
         "user_labeled"),
        ("qwen_candidate_recall", "reports/nextgen_v2/qwen_candidate_recall_real.json",
         "pseudo_mask_interim"),
        ("sam_segmentation", "reports/nextgen_v2/sam_crop_segmentation_report.json",
         "pseudo_mask_interim"),
        ("m1_smoke", ".models/nextgen_detector_smoke_v1/smoke_report.json"
         if (ROOT / ".models/nextgen_detector_smoke_v1/smoke_report.json").exists()
         else "reports/nextgen_v2/m1_detector_smoke_report.json", "smoke"),
        ("m3_random", "reports/nextgen_v2/m3_classifier_cropped_report.json", "user_labeled"),
        ("m4_qlora_pilot", "reports/nextgen_v2/m4_vlm_cropped_report.json",
         "pseudo_mask_interim"),
    ]
    for eid, rel, evl in evals:
        p = ROOT / rel
        if not p.exists():
            continue
        summary = json.loads(p.read_text())
        r = svc.register_evaluation(eval_id=eid, kind="evaluation",
                                    report_path=str(p), summary=summary,
                                    evidence_level=evl,
                                    actor="reconciliation", run_id=RUN_ID)
        reg["evals"].append((eid, r["duplicate"]))

    # ---- Cycle：19 节点，历史节点 reconciliation 标记 ----
    cid = "sku_long_tail_nextgen_cycle_v1"
    if not store._conn.execute("SELECT 1 FROM training_cycle_v1 WHERE cycle_id=?",
                               (cid,)).fetchone():
        store._conn.execute(
            "INSERT INTO training_cycle_v1 (cycle_id, name, status, version,"
            " waiting_for, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,datetime('now'),datetime('now'))",
            (cid, cid, "TRAINING_CYCLE_ACTIVE", 1, "", "reconciliation"))
        store._conn.commit()
    HIST_NODES = [
        ("BaselineReconciled", "done"), ("SamPseudoMasksGenerated", "done"),
        ("SamDecoderExperimentRecorded", "done"), ("SnapshotsV3Frozen", "done"),
        ("M1SmokeRecorded", "done"), ("M2SmokeRecorded", "done"),
        ("M3LeakageDetected", "done"), ("M3GroupedBaselineRecorded", "done"),
        ("M4PilotRecorded", "done"), ("PlatformFactsReconciled", "done"),
        ("Canonical38DatasetBuild", "pending"), ("M1Pilot", "pending"),
        ("M2Pilot", "pending"), ("M3LongTailExperiments", "pending"),
        ("KBCoverageBuild", "pending"), ("M4RealCandidatePilot", "pending"),
        ("DemoEvaluation", "pending"), ("AwaitingIndependentEvaluation", "pending"),
        ("AwaitingProductionDecision", "pending")]
    for node, st in HIST_NODES:
        key = f"{cid}:{node}:recon"
        if not store._conn.execute(
                "SELECT 1 FROM training_cycle_node_v1 WHERE idempotency_key=?",
                (key,)).fetchone():
            store._conn.execute(
                "INSERT INTO training_cycle_node_v1 (cycle_id, node, status,"
                " idempotency_key, evidence_json, created_at, updated_at)"
                " VALUES (?,?,?,?,?,datetime('now'),datetime('now'))",
                (cid, node, st, key,
                 json.dumps({"via": "reconciliation", "run_id": RUN_ID,
                            "note": "历史已完成节点，非重新执行"
                            if st == "done" else ""})))
            store._conn.commit()

    # ---- 黑板真实事件 ----
    bb = BlackboardService(store)
    findings = [
        ("Finding", "发现 47.7pp 数据泄漏：random split top1 82.4% vs grouped 34.7%",
         ["reports/nextgen_v2/classifier_split_compare.json"]),
        ("Finding", "SAM decoder v1/v2 为自一致性实验，不可作为候选",
         ["reports/nextgen_v2/sam_decoder_finetune_report.json"]),
        ("Finding", "M1/M2 仅 1 epoch smoke，candidate=false",
         ["reports/nextgen_v2/m1_detector_smoke_report.json"]),
        ("Finding", "M3 grouped baseline top1 30.7%",
         ["reports/nextgen_v2/m3_classifier_cropped_report.json"]),
        ("Finding", "M4 KB 覆盖 0（canonical38 未建），candidate recall=null",
         ["reports/nextgen_v2/qwen_candidate_recall_real.json"]),
        ("Finding", "45 个 pending SKU 待业务裁决",
         ["reports/nextgen_v2/sku_data_readiness_policy_v1.json"]),
        ("Finding", "D1/D2 仅含 894 张全场景原图",
         ["reports/nextgen_v2/four_snapshots_v3.json"]),
        ("Decision", "production 保持 prod_20260805_v5_r1，未切换", []),
        ("Blocker", "KB canonical38 未建 → M4 禁训", []),
        ("PendingCommand", "创建 M3 长尾消融计划（E1-E5）待批准", []),
        ("ModelRunRef", "nextgen_classifier_grouped_v1 val 30.7%",
         [".models/nextgen_classifier_grouped_v1/weights/best.pt"]),
        ("Task", "M3 长尾消融 E1-E5", {"state": "todo", "owner": "modelops"}),
        ("Task", "M1 5 epoch pilot", {"state": "todo", "owner": "modelops"}),
        ("Task", "M2 5 epoch pilot", {"state": "todo", "owner": "modelops"}),
        ("Task", "KB canonical38 建设", {"state": "running", "owner": "data_steward"}),
        ("Task", "pending SKU 裁决包人工裁决", {"state": "waiting", "owner": "human"}),
        ("Task", "平台事实对账", {"state": "done", "owner": "supervisor"}),
        ("Resolution", "Gate 纠正为 PIPELINE_SMOKES_READY_PLATFORM_NOT_CONNECTED", []),
    ]
    for et, text, refs in findings:
        payload = {"text": text}
        if et == "Task":
            payload = {**text, "title": text["title"]} if isinstance(text, dict) else {"text": text}
        bb.append("reconciliation", et, payload, evidence_refs=refs,
                  by_kind="agent")

    # ---- 记忆 ----
    ms = MemoryService(store)
    if not store._conn.execute(
            "SELECT 1 FROM memory_entry_v1 WHERE level='l2'").fetchone():
        ms.put("l1", f"cycle checkpoint: {cid} 10/19 done",
               scope="project", acl=["project:llm-image"], confidence=1.0,
               evidence=["platform.sqlite:training_cycle_v1"])
        ms.put("l2", "grouped split 后分类器真实泛化 30.7%；random 82.4% 为泄漏",
               scope="project", acl=["project:llm-image"], confidence=1.0,
               evidence=["reports/nextgen_v2/classifier_split_compare.json"])
        ms.put("l2", "四 snapshot v3 冻结；7 artifact 已对账注册",
               scope="project", acl=["project:llm-image"], confidence=1.0,
               evidence=["reports/nextgen_v2/four_snapshots_v3.json"])
        ms.put("l4", "泄漏 split 的 top1 不可用于方案排名；grouped 为唯一基线",
               scope="global", acl=["project:llm-image", "tenant:*"],
               confidence=1.0, evidence=["reports/nextgen_v2/classifier_split_compare.json"])

    print(json.dumps(reg, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
