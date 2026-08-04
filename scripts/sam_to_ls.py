"""SAM → Label Studio prediction 导入驱动（手册§一.9 / §七）。

流程：
1. 读取 .field 照片与真实坐标点（诊断集，只读）；
2. 隔离 venv worker 跑 SAM 2.1 hiera_small（Gate S0 选定）；
3. 主环境硬约束筛选/评分 → prediction（绝不写 annotation）+ 证据链；
4. LS 在线：建独立项目 `sam_reannotation_diag_v1` 导入 task 与 prediction；
   LS 离线：落盘 `ls_payload.json`（tasks+predictions）待 LS 恢复后导入，
   状态写 awaiting_human_review（手册§七/§26）。

用法：
  python -m scripts.sam_to_ls --limit 9
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from src.sam_assist.candidates import PhysicalLimits
from src.sam_assist.evidence import EvidenceStore
from src.sam_assist.ls_import import import_to_ls, process_image, record_evidence
from src.sam_assist.prompts import PromptConfig, build_prompts
from src.sam_assist.runtime import CHECKPOINTS
from src.sam_assist.contracts import InstanceInput
from src.sam_assist.service import SAMWorkerClient

CKPT_DIR = PROJECT_ROOT / ".sam_checkpoints"
MODEL = "sam2.1_hiera_small"
LABEL_CONFIG = (PROJECT_ROOT / "configs/label-studio/label_config.xml")


def _git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True,
                          cwd=PROJECT_ROOT).stdout.strip()


def _load_photos(limit: int):
    manifest = json.loads((PROJECT_ROOT / ".field/manifest.json")
                          .read_text(encoding="utf-8"))
    con = sqlite3.connect(PROJECT_ROOT / ".warehouse/db.sqlite")
    assets = {str(r[0]): {"sha256": r[1], "width": r[2], "height": r[3]}
              for r in con.execute(
                  "select asset_id, sha256, width, height from asset")}
    photos = []
    for p in manifest["photos"]:
        pid = str(p["id"])
        if pid not in assets:
            continue
        a = assets[pid]
        blob = PROJECT_ROOT / ".field/blobs" / a["sha256"][:2] / a["sha256"]
        if not blob.exists():
            continue
        photos.append({"photo_id": pid, "blob": blob, **a,
                       "annotations": p.get("annotations", [])})
        if len(photos) >= limit:
            break
    return photos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=9)
    a = ap.parse_args()

    photos = _load_photos(a.limit)
    cfg = PromptConfig()
    ckpt_manifest = json.loads((CKPT_DIR / "manifest.json").read_text())
    ckpt_sha = next(e["sha256"] for e in ckpt_manifest["entries"]
                    if e["model"] == MODEL)
    commit = _git_commit()

    images_req = []
    for ph in photos:
        inst_inputs = [InstanceInput(
            asset_id=ph["photo_id"], photo_id=ph["photo_id"],
            image_sha256=ph["sha256"], width=ph["width"], height=ph["height"],
            instance_id=f"{ph['photo_id']}_{i:03d}",
            x=float(ann["x"]), y=float(ann["y"]),
            sku_raw_name=ann.get("name", ""),
            sku_canonical=ann.get("canonical"),
            quality_version="diagnostic_v1")
            for i, ann in enumerate(ph["annotations"])]
        instances = []
        for inst in inst_inputs:
            ps = build_prompts(inst, inst_inputs,
                               box_frac_fn=lambda _n: None, cfg=cfg)
            instances.append({
                "instance_id": inst.instance_id,
                "positive": list(ps.positive_point),
                "negatives": [list(p) for p in ps.negative_points],
                "coarse_box": list(ps.coarse_box),
                "prompt_config_version": ps.config_version,
            })
        images_req.append({"image_path": str(ph["blob"]),
                           "image_sha": ph["sha256"],
                           "photo_id": ph["photo_id"],
                           "width": ph["width"], "height": ph["height"],
                           "instances": instances})

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / ".sam_runs" / f"ls_import_{ts}"
    request = {"_request_path": str(out_dir / "request.json"),
               "model": MODEL,
               "checkpoint": str(CKPT_DIR / f"{MODEL}.pt"),
               "checkpoint_sha256": ckpt_sha,
               "config": CHECKPOINTS[MODEL]["config"],
               "out_dir": str(out_dir),
               "images": images_req}

    print(f"[sam_to_ls] photos={len(images_req)} model={MODEL}")
    resp = SAMWorkerClient().invoke(request)

    limits = {}
    outcomes = []
    for img_req, img_res in zip(images_req, resp["results"]):
        w, h = img_req["width"], img_req["height"]
        lim = PhysicalLimits(min_area_px=400.0, max_area_px=0.6 * w * h,
                             min_aspect=0.05, max_aspect=8.0)
        limits[img_req["image_sha"]] = lim
        outcomes.append(process_image(
            img_res, img_req, model_id=MODEL, checkpoint_sha256=ckpt_sha,
            code_commit=commit, limits=lim))

    store = EvidenceStore(out_dir / "evidence.jsonl")
    for oc in outcomes:
        record_evidence(store, oc)

    n_pred = sum(len(o.predictions) for o in outcomes)
    n_manual = sum(len(o.manual_required) for o in outcomes)
    model_version = f"{MODEL}@{ckpt_sha[:12]}"

    # ---- LS 在线导入 / 离线落盘 ----
    ls_state = "offline"
    project_id = None
    try:
        from src.ls_platform.ls_client import LSClient
        client = LSClient()
        client.whoami()
        projects = [p for p in client.list_projects()
                    if p.get("title") == "sam_reannotation_diag_v1"]
        if projects:
            project_id = projects[0]["id"]
        else:
            project_id = client.create_project(
                "sam_reannotation_diag_v1",
                LABEL_CONFIG.read_text(encoding="utf-8"),
                description="SAM 辅助重标注诊断项目：仅 prediction，人工双审后出真值")["id"]
        index = client.index_task_images(project_id)
        for ph, oc in zip(photos, outcomes):
            fn = ph["blob"].name
            task = index.get(fn)
            if task is None:
                client.import_files(project_id,
                                    [(fn, ph["blob"].read_bytes())])
                index = client.index_task_images(project_id)
                task = index.get(fn)
            if task is not None:
                import_to_ls(client, task_id=task["id"], outcome=oc,
                             model_version=model_version)
        ls_state = "online"
    except Exception as e:  # LS 不可达：离线落盘，不伪造
        print(f"[sam_to_ls] LS 离线（{type(e).__name__}: {e}），落盘待导入")
        payload = []
        for ph, oc in zip(photos, outcomes):
            payload.append({
                "data": {"image": f"/data/local-files/?d={ph['blob']}"},
                "meta": {"photo_id": ph["photo_id"],
                         "image_sha256": ph["sha256"]},
                "predictions": [{
                    "score": p["score"], "model_version": model_version,
                    "result": p["result"],
                } for p in oc.predictions],
                "manual_required": oc.manual_required,
            })
        (out_dir / "ls_payload.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8")

    summary = {
        "timestamp": ts, "model": MODEL, "checkpoint_sha256": ckpt_sha,
        "code_commit": commit, "ls_state": ls_state,
        "project_id": project_id,
        "n_photos": len(photos), "n_predictions": n_pred,
        "n_manual_required": n_manual,
        "manual_required_ids": [m for o in outcomes for m in o.manual_required],
        "status": "awaiting_human_review",
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[sam_to_ls] ls_state={ls_state} predictions={n_pred} "
          f"manual_required={n_manual} → awaiting_human_review")
    print(f"[sam_to_ls] out: {out_dir}")


if __name__ == "__main__":
    main()
