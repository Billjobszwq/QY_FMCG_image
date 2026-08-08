"""SAM2 mask decoder 微调（用户切分图 + SAM 伪 mask）。

红线诚实标注：训练标签来自 SAM 自推理（pseudo），本实验为
self-consistency fine-tune，**不是 human gold 微调**，不宣称真实
SAM 微调完成；业务有效性需后续人工 mask 抽检。

冻结：image_encoder + sam_prompt_encoder；可训：sam_mask_decoder。
prompt：GT mask 随机前景点 + 背景点；loss = BCE + Dice（best iou mask）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MASKS_JSONL = ROOT / "reports/nextgen_v2/sam_crop_masks.jsonl"
TARGET = 1024


def _load_records(limit, seed):
    recs = []
    with MASKS_JSONL.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("mask_rle") and r.get("tight_box"):
                recs.append(r)
            if limit and len(recs) >= limit * 2:
                break
    rng = random.Random(seed)
    rng.shuffle(recs)
    return recs


def sam_loss_manifest() -> dict:
    from src.modules.nextgen_data.sam_losses import sam_mask_loss
    return sam_mask_loss.manifest_defaults()


def _rle_to_mask(rle, h, w):
    import numpy as np
    mask = np.zeros(h * w, dtype=bool)
    for seg in rle.split(","):
        if not seg:
            continue
        s, ln = seg.split(":")
        mask[int(s):int(s) + int(ln)] = True
    return mask.reshape((h, w), order="F")


def _transform_mask_to_1024(mask, h, w):
    """与 SAM ResizeLongestSide+pad 同几何：scale→resize→pad 到 1024。"""
    import cv2
    import numpy as np
    scale = TARGET / max(h, w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    m = cv2.resize(mask.astype(np.uint8), (nw, nh),
                   interpolation=cv2.INTER_NEAREST)
    pad = np.zeros((TARGET, TARGET), dtype=np.uint8)
    pad[:nh, :nw] = m
    return pad.astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3000)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--run-name", default="nextgen_sam_decoder_v1")
    a = ap.parse_args()

    out_dir = ROOT / ".models" / a.run_name
    if out_dir.exists():
        raise SystemExit(f"run 目录已存在，拒绝覆盖: {out_dir}")
    out_dir.mkdir(parents=True)

    import cv2
    import numpy as np
    import torch
    import torch.nn.functional as TF
    from sam2.build_sam import build_sam2

    man = json.loads((ROOT / ".sam_checkpoints/manifest.json")
                     .read_text(encoding="utf-8"))
    e = next(x for x in man["entries"]
             if x["model"] == "sam2.1_hiera_small")
    model = build_sam2("configs/sam2.1/sam2.1_hiera_s.yaml", e["file"],
                       device=torch.device("mps"))
    for p in model.image_encoder.parameters():
        p.requires_grad = False
    for p in model.sam_prompt_encoder.parameters():
        p.requires_grad = False
    for p in model.sam_mask_decoder.parameters():
        p.requires_grad = True
    opt = torch.optim.AdamW(
        [p for p in model.sam_mask_decoder.parameters()
         if p.requires_grad], lr=a.lr)

    recs = _load_records(a.samples, 42)
    n_val = max(50, len(recs) // 10)
    train_recs, val_recs = recs[n_val:], recs[:n_val]
    print(f"train={len(train_recs)} val={len(val_recs)}", flush=True)

    mean = torch.tensor([123.675, 116.28, 103.53]).view(3, 1, 1)
    std = torch.tensor([58.395, 57.12, 57.375]).view(3, 1, 1)

    def embed(img_bgr):
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
        h, w = img.shape[:2]
        scale = TARGET / max(h, w)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        img_r = cv2.resize(img, (nw, nh))
        pad = np.zeros((TARGET, TARGET, 3), dtype=np.float32)
        pad[:nh, :nw] = img_r
        t = torch.from_numpy(pad.transpose(2, 0, 1)).float()
        t = (t - mean.flatten().view(3, 1, 1)) / std.flatten().view(3, 1, 1)
        with torch.no_grad():
            backbone_out = model.forward_image(t[None].to("mps"))
            _, vf, _, _ = model._prepare_backbone_features(backbone_out)
        return backbone_out, vf, (h, w)

    from sam2.sam2_image_predictor import SAM2ImagePredictor
    probe = SAM2ImagePredictor(model)
    bb_sizes = probe._bb_feat_sizes

    def forward_loss(rec, rng):
        img = cv2.imread(rec["path"])
        if img is None:
            return None
        h, w = img.shape[:2]
        gt = _rle_to_mask(rec["mask_rle"], h, w)
        gt1024 = _transform_mask_to_1024(gt, h, w)
        backbone_out, vf, _ = embed(img)
        feats = [f.permute(1, 2, 0).view(1, -1, *sz)
                 for f, sz in zip(vf[::-1], bb_sizes[::-1])][::-1]
        high_res, backbone_features = feats[:-1], feats[-1]
        # prompt：GT mask 随机前景点 + 1 背景点
        ys, xs = np.nonzero(gt1024)
        if len(xs) < 4:
            return None
        i = rng.randint(0, len(xs) - 1)
        fg = [float(xs[i]), float(ys[i])]
        bg = [8.0, 8.0]
        coords = torch.tensor([[fg, bg]], device="mps")
        labels = torch.tensor([[1, 0]], dtype=torch.int32, device="mps")
        se, de = model.sam_prompt_encoder(points=(coords, labels),
                                          boxes=None, masks=None)
        low, ious, _, _ = model.sam_mask_decoder(
            image_embeddings=backbone_features,
            image_pe=model.sam_prompt_encoder.get_dense_pe(),
            sparse_prompt_embeddings=se, dense_prompt_embeddings=de,
            multimask_output=True, repeat_image=False,
            high_res_features=high_res)
        idx = int(ious[0].argmax())
        m = low[0, idx]  # (256,256)
        m_up = TF.interpolate(m[None, None], size=(TARGET, TARGET),
                              mode="bilinear", align_corners=False)[0, 0]
        gt_t = torch.from_numpy(gt1024).to("mps")
        # SLTF P0-1：可导 soft Dice（sam_losses）；二值 Dice 仅 metric
        from src.modules.nextgen_data.sam_losses import (
            binary_dice_metric, sam_mask_loss)
        return sam_mask_loss(m_up[None, None], gt_t[None, None])

    rng = random.Random(7)
    curve = []
    t0 = time.time()
    for ep in range(a.epochs):
        tot = 0.0
        n = 0
        for rec in train_recs:
            loss = forward_loss(rec, rng)
            if loss is None:
                continue
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss)
            n += 1
        val_tot, vn = 0.0, 0
        with torch.no_grad():
            for rec in val_recs[:100]:
                lv = forward_loss(rec, rng)
                if lv is not None:
                    val_tot += float(lv)
                    vn += 1
        curve.append({"epoch": ep + 1,
                      "train_loss": round(tot / max(n, 1), 4),
                      "val_loss": round(val_tot / max(vn, 1), 4)})
        print(json.dumps(curve[-1]), flush=True)

    torch.save(model.sam_mask_decoder.state_dict(),
               out_dir / "mask_decoder_ft.pt")
    sha = hashlib.sha256(
        (out_dir / "mask_decoder_ft.pt").read_bytes()).hexdigest()
    rep = {"run": a.run_name, "kind": "sam_mask_decoder_finetune",
           "teacher": "sam2.1_hiera_small(frozen encoder)",
           "label_source": "sam_pseudo_masks（自推理伪标签，非 human gold）",
           "evidence_level": "pseudo_mask_interim",
           "status": "EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE",
           "loss": sam_loss_manifest(),
           "samples": len(train_recs), "epochs": a.epochs,
           "curve": curve, "duration_s": round(time.time() - t0, 1),
           "artifact_sha256": sha, "candidate": False,
           "note": "SAM 伪 mask 自洽微调；业务有效性需人工 mask 抽检"}
    (out_dir / "train_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"done": True, "sha": sha[:16]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
