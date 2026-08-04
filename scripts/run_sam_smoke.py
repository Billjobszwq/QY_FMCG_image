"""Gate S0 smoke（手册§五）：5 张真实照片的 SAM 2.1 实跑。

- 只读 `.field/manifest.json` + `.field/blobs`（内容寻址原图，不改动）；
- 提示：真实坐标点=positive，最近邻点=negative，通用比例粗 ROI（coarse_only）；
- 隔离 venv worker 执行 MPS 门禁（fail-closed），主环境只读报告；
- 输出 `.sam_runs/smoke_<model>_<ts>/`：request/report/masks，全部证据留档。

用法：
  python -m scripts.run_sam_smoke --model sam2.1_hiera_small --n 5
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from src.sam_assist.contracts import InstanceInput
from src.sam_assist.prompts import PromptConfig, build_prompts
from src.sam_assist.runtime import CHECKPOINTS
from src.sam_assist.service import SAMWorkerClient

CKPT_DIR = PROJECT_ROOT / ".sam_checkpoints"


def _load_photos(n: int):
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
        if len(photos) >= n:
            break
    return photos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sam2.1_hiera_small",
                    choices=sorted(CHECKPOINTS))
    ap.add_argument("--n", type=int, default=5)
    a = ap.parse_args()

    ckpt_meta = CHECKPOINTS[a.model]
    ckpt_path = CKPT_DIR / f"{a.model}.pt"
    ckpt_manifest = json.loads((CKPT_DIR / "manifest.json").read_text())
    sha = next(e["sha256"] for e in ckpt_manifest["entries"]
               if e["model"] == a.model)

    photos = _load_photos(a.n)
    if not photos:
        raise SystemExit("无可用照片（.field/blobs 与 warehouse 不匹配）")

    cfg = PromptConfig()
    images_req = []
    n_points = 0
    for ph in photos:
        instances = []
        inst_inputs = []
        for i, ann in enumerate(ph["annotations"]):
            inst_inputs.append(InstanceInput(
                asset_id=ph["photo_id"], photo_id=ph["photo_id"],
                image_sha256=ph["sha256"], width=ph["width"],
                height=ph["height"], instance_id=f"{ph['photo_id']}_{i:03d}",
                x=float(ann["x"]), y=float(ann["y"]),
                sku_raw_name=ann.get("name", ""),
                sku_canonical=ann.get("canonical"),
                quality_version="diagnostic_v1"))
        for inst in inst_inputs:
            ps = build_prompts(inst, inst_inputs,
                               box_frac_fn=lambda _name: None, cfg=cfg)
            instances.append({
                "instance_id": inst.instance_id,
                "positive": list(ps.positive_point),
                "negatives": [list(p) for p in ps.negative_points],
                "coarse_box": list(ps.coarse_box),
                "prompt_config_version": ps.config_version,
                "coarse_only": ps.coarse_only,
            })
            n_points += 1
        images_req.append({"image_path": str(ph["blob"]),
                           "image_sha": ph["sha256"],
                           "photo_id": ph["photo_id"],
                           "instances": instances})

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / ".sam_runs" / f"smoke_{a.model}_{ts}"
    request = {
        "_request_path": str(out_dir / "request.json"),
        "model": a.model,
        "checkpoint": str(ckpt_path),
        "checkpoint_sha256": sha,
        "config": ckpt_meta["config"],
        "out_dir": str(out_dir),
        "images": images_req,
    }

    print(f"[smoke] model={a.model} photos={len(images_req)} points={n_points}")
    client = SAMWorkerClient()
    resp = client.invoke(request)

    report = {
        "gate": "S0_smoke",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": a.model,
        "checkpoint_sha256": sha,
        "prompt_config_version": cfg.config_version,
        "n_photos": len(images_req),
        "n_points": n_points,
        "env": resp["env"],
        "wall_time_sec": resp["wall_time_sec"],
        "results": resp["results"],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    env = resp["env"]
    assert env["device"] == "mps", f"设备门禁异常: {env['device']}"
    print(f"[smoke] ok device={env['device']} torch={env['torch']} "
          f"load={env['load_sec']}s rss={env['peak_rss_mb']}MB "
          f"wall={resp['wall_time_sec']}s")
    for r in resp["results"]:
        dec = sum(i["decoder_sec"] for i in r["instances"])
        print(f"  photo {r['image_sha'][:8]}: encoder={r['encoder_sec']}s "
              f"decoder_total={round(dec, 3)}s pts={len(r['instances'])} "
              f"mps_peak={r['mps_peak_mem_bytes']/1e6:.0f}MB")
    print(f"[smoke] report: {out_dir/'report.json'}")


if __name__ == "__main__":
    main()
