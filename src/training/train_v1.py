"""YOLO v1 训练：208 类 SKU 检测模型。

数据集：.training_data/（2653 train / 294 val / 84K labels / 208 classes）
模型：yolo11n（nano，平衡速度与精度）
输出：.models/sku_v1/weights/best.pt + 在仓库登记 model_version

用法：python -m src.training.train_v1 [--epochs 50] [--imgsz 640] [--device mps]"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.config import PROJECT_ROOT
from src.data import warehouse as wh

DATA_YAML = PROJECT_ROOT / ".training_data" / "data.yaml"
MODELS_DIR = PROJECT_ROOT / ".models"
REGISTRY_DIR = MODELS_DIR / "registry"  # ISSUE-006：不可变权重仓库（按 SHA 命名）


def code_hash():
    h = hashlib.sha256()
    for f in sorted(glob.glob(str(PROJECT_ROOT / "src" / "**" / "*.py"), recursive=True)):
        h.update(open(f, "rb").read())
    return h.hexdigest()[:12]


def _content_manifest_hash(base: Path, train_rel: str, val_rel: str) -> tuple[str, int]:
    """RA-013：数据集内容指纹 —— 逐文件 sha256（图片+标签），覆盖实际内容而非仅 YAML。

    返回 (manifest_hash, 文件数)。同一内容必得同一哈希，任何图片/标签/切分变化都会改变哈希。
    复核修订：YOLO 数据集的 labels/<split> 目录与图片目录同等参与哈希（图片不变时改
    label 必须改变哈希）；哈希键用相对路径而非仅文件名，并纳入 split 目录名。"""
    h = hashlib.sha256()
    n = 0
    for split_rel in (train_rel, val_rel):
        targets = [split_rel]
        # 图片目录 images/<split> 对应同层级标签目录 labels/<split>，一并入哈希
        sp = Path(split_rel)
        if not sp.is_absolute() and sp.parts and sp.parts[0] == "images" and len(sp.parts) > 1:
            targets.append(str(Path("labels", *sp.parts[1:])))
        for rel in targets:
            d = (base / rel) if not Path(rel).is_absolute() else Path(rel)
            h.update(f"|{rel}".encode())
            if not d.exists():
                continue
            files = sorted((f for f in d.rglob("*") if f.is_file()),
                           key=lambda f: f.relative_to(d).as_posix())
            for f in files:
                n += 1
                h.update(f.relative_to(d).as_posix().encode())
                fh = hashlib.sha256()
                with f.open("rb") as fp:
                    while True:
                        b = fp.read(1 << 20)
                        if not b:
                            break
                        fh.update(b)
                h.update(fh.digest())
    return h.hexdigest()[:16], n


def validate_dataset(data_yaml: str) -> dict:
    """ISSUE-001：训练前校验 data.yaml —— train/val 路径、类别数、类别表、样本数，并计算数据集哈希。

    任何一项不合法直接抛异常，禁止隐式默认数据集静默训练。"""
    import yaml
    p = Path(data_yaml)
    if not p.exists():
        raise FileNotFoundError(f"data.yaml 不存在: {p}")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError(f"data.yaml 格式非法: {p}")
    for k in ("train", "val", "nc", "names"):
        if k not in cfg:
            raise ValueError(f"data.yaml 缺少必需字段: {k}")
    names = cfg["names"]
    nc = int(cfg["nc"])
    if isinstance(names, dict):
        n_names = len(names)
    elif isinstance(names, list):
        n_names = len(names)
    else:
        raise ValueError(f"names 类型非法: {type(names)}")
    if n_names != nc:
        raise ValueError(f"类别数不一致: nc={nc} vs names={n_names}")
    base = Path(cfg.get("path", p.parent))
    if not base.is_absolute():
        base = (p.parent / base).resolve()

    def _count(rel):
        d = (base / rel) if not Path(rel).is_absolute() else Path(rel)
        if not d.exists():
            raise FileNotFoundError(f"数据集目录不存在: {d}")
        return sum(1 for f in d.iterdir()
                   if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"))

    n_train, n_val = _count(cfg["train"]), _count(cfg["val"])
    if n_train == 0:
        raise ValueError("训练集样本数为 0，拒绝训练")
    # RA-013：数据集哈希 = yaml 内容 + 样本数 + 逐文件内容指纹（覆盖图片/标签/切分实际内容）
    content_hash, n_files = _content_manifest_hash(base, cfg["train"], cfg["val"])
    h = hashlib.sha256(p.read_bytes())
    h.update(f"|train={n_train}|val={n_val}|nc={nc}|content={content_hash}".encode())
    ds_hash = h.hexdigest()[:16]
    info = {"data_yaml": str(p), "nc": nc, "n_train": n_train, "n_val": n_val,
            "dataset_hash": ds_hash, "content_hash": content_hash, "n_files": n_files}
    print(f"  数据集校验通过: nc={nc}, train={n_train}, val={n_val}, "
          f"hash={ds_hash}, content={content_hash}({n_files}文件)")
    return info


def snapshot_weight(wp: Path) -> tuple[str, str]:
    """ISSUE-006：训练完成后将权重复制到按 SHA-256 命名的不可变仓库，返回 (完整哈希, 不可变路径)。"""
    full = hashlib.sha256(wp.read_bytes()).hexdigest()
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    target = REGISTRY_DIR / f"{full[:24]}.pt"
    if not target.exists():
        import shutil
        shutil.copy2(wp, target)
        try:
            target.chmod(0o444)  # 只读，防止被覆盖
        except Exception:
            pass
    return full, str(target)


def train(epochs=80, imgsz=640, batch=8, device="mps", model_name="yolo26m.pt",
          cls_weight=0.5, run_name="sku_v1", data_yaml=None, scale=0.5,
          lr0=0.01, mosaic=1.0, mixup=0.1, copy_paste=0.0,
          cos_lr=False, dropout=0.0, close_mosaic=10, patience=10,
          weight_decay=0.0005, warmup_epochs=3, dataset_desc=None,
          box_weight=7.5, hsv_h=0.015, hsv_s=0.7, hsv_v=0.4, erasing=0.4,
          optimizer="auto", require_explicit_data=False, seed=42):
    from ultralytics import YOLO

    if require_explicit_data and not data_yaml:
        # ISSUE-001：复训/平台训练禁止隐式默认数据集
        raise ValueError("require_explicit_data=True：必须显式传入 data_yaml，禁止使用隐式默认数据集")
    data_yaml = data_yaml or str(DATA_YAML)
    # ISSUE-001：训练前数据集预校验（路径/类别/样本数/哈希）
    ds_info = validate_dataset(data_yaml)
    print(f"=== YOLO 训练 ({run_name}) ===")
    print(f"  模型: {model_name}")
    print(f"  数据: {data_yaml}")
    print(f"  epochs={epochs}, imgsz={imgsz}, batch={batch}, cls={cls_weight}, device={device}")
    print(f"  lr0={lr0}, cos_lr={cos_lr}, dropout={dropout}, close_mosaic={close_mosaic}, patience={patience}, wd={weight_decay}")
    t0 = time.time()

    # G6：run 目录已存在即 fail-closed，禁止覆盖旧实验（Ultralytics
    # exist_ok=True 会允许覆盖，一并禁用）。
    # 注意：不得在训练前预建 run 目录/写 meta，否则 Ultralytics
    # exist_ok=False 发现目录已存在会自动递增命名（run_name-2），
    # 破坏唯一 run-name 约束；meta 改为训练完成后写入。
    run_dir = MODELS_DIR / run_name
    if run_dir.exists():
        raise RuntimeError(
            f"run 目录已存在，拒绝覆盖: {run_dir}（换一个 --run-name，"
            "旧实验与生产制品不得被静默覆盖）")

    # 训练元信息（训练完成后随 run 目录落盘，供监控/审计读取）
    meta = {
        "model": model_name,
        "model_display": model_name.replace(".pt", "").upper(),
        "epochs": epochs, "imgsz": imgsz, "batch": batch, "device": device,
        "cls_weight": cls_weight, "run_name": run_name,
        "lr0": lr0, "cos_lr": cos_lr, "dropout": dropout, "close_mosaic": close_mosaic,
        "patience": patience, "weight_decay": weight_decay, "mosaic": mosaic, "mixup": mixup,
        "erasing": erasing, "hsv_v": hsv_v, "hsv_s": hsv_s,
        "seed": seed,
        "data_yaml": data_yaml,
        "dataset_hash": ds_info["dataset_hash"],
        "content_hash": ds_info.get("content_hash"),
        "n_train": ds_info["n_train"], "n_val": ds_info["n_val"], "nc": ds_info["nc"],
        "dataset": dataset_desc or "训练数据集",
        "code_hash": code_hash(),
        "started_at": time.time(),
    }

    model = YOLO(model_name)
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        seed=seed,
        deterministic=True,
        project=str(MODELS_DIR),
        name=run_name,
        exist_ok=False,
        patience=patience,
        save=True,
        plots=True,
        verbose=True,
        workers=4,
        optimizer=optimizer,
        lr0=lr0,
        cos_lr=cos_lr,
        cls=cls_weight,
        box=box_weight,
        dropout=dropout,
        weight_decay=weight_decay,
        warmup_epochs=warmup_epochs,
        mosaic=mosaic,
        mixup=mixup,
        copy_paste=copy_paste,
        close_mosaic=close_mosaic,
        hsv_h=hsv_h,
        hsv_s=hsv_s,
        hsv_v=hsv_v,
        erasing=erasing,
        degrees=5.0,
        translate=0.1,
        scale=scale,
        fliplr=0.5,
    )

    elapsed = time.time() - t0
    # G6：run 目录由 Ultralytics 创建（exist_ok=False），meta 在训练完成后写入
    meta["elapsed_sec"] = round(elapsed, 1)
    (MODELS_DIR / run_name / "train_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    best = MODELS_DIR / run_name / "weights" / "best.pt"
    last = MODELS_DIR / run_name / "weights" / "last.pt"
    wp = best if best.exists() else last

    # 解析训练指标（RA-013：best.pt 对应最佳轮，登记指标必须取 best epoch 行而非最后一行；
    # 同时保留 last 行供对照）
    metrics = {}
    last_metrics = {}
    rc = MODELS_DIR / run_name / "results.csv"
    if rc.exists():
        lines = rc.read_text().strip().splitlines()
        if len(lines) > 1:
            cols = [c.strip() for c in lines[0].split(",")]
            rows = []
            for ln in lines[1:]:
                vals = [v.strip() for v in ln.split(",")]
                rows.append(dict(zip(cols, vals)))
            last_metrics = rows[-1]
            try:
                best_row = max(rows, key=lambda r: float(r.get("metrics/mAP50(B)", 0)))
            except (TypeError, ValueError):
                best_row = rows[-1]
            metrics = best_row

    # 登记 model_version（ISSUE-006：权重快照进不可变仓库，登记完整 SHA-256 + 数据版本）
    conn = wh.connect()
    wh.migrate(conn)
    mv_id = f"{run_name}_" + time.strftime("%Y%m%d%H%M%S")
    if wp.exists():
        wsha_full, immutable_uri = snapshot_weight(wp)
    else:
        wsha_full, immutable_uri = "", str(wp)
    # 发布前重新校验快照哈希，发现变化拒绝发布
    if immutable_uri != str(wp) and Path(immutable_uri).exists():
        recheck = hashlib.sha256(Path(immutable_uri).read_bytes()).hexdigest()
        if recheck != wsha_full:
            conn.close()
            raise RuntimeError(f"权重快照哈希不一致，拒绝登记: {immutable_uri}")
    conn.execute(
        "INSERT OR REPLACE INTO model_version VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (mv_id, "detect_208sku", meta["code_hash"], f"dataset:{ds_info['dataset_hash']}",
         json.dumps({"epochs": epochs, "imgsz": imgsz, "batch": batch, "model": model_name,
                     "cls_weight": cls_weight, "lr0": lr0, "seed": seed}, ensure_ascii=False),
         seed, json.dumps({"best_epoch": metrics, "last_epoch": last_metrics}, ensure_ascii=False),
         immutable_uri, wsha_full[:16], "trained", time.time())
    )
    conn.commit()
    conn.close()

    print(f"\n=== 训练完成 ({elapsed:.0f}s) ===")
    print(f"  权重: {wp}")
    print(f"  model_version: {mv_id}")
    print(f"  指标: {json.dumps({k: v for k, v in metrics.items() if 'mAP' in k or 'precision' in k or 'recall' in k}, indent=2)}")
    return mv_id


def build_arg_parser() -> argparse.ArgumentParser:
    """train_v1 真实参数集（dry-run 命令预检的单一事实源）。"""
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--model", default="yolo26m.pt")
    ap.add_argument("--cls-weight", type=float, default=0.5)
    ap.add_argument("--run-name", default="sku_v1")
    ap.add_argument("--data-yaml", default=None)
    ap.add_argument("--lr0", type=float, default=0.01)
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--mosaic", type=float, default=1.0)
    ap.add_argument("--mixup", type=float, default=0.1)
    ap.add_argument("--copy-paste", type=float, default=0.0)
    ap.add_argument("--cos-lr", action="store_true", help="余弦退火学习率调度")
    ap.add_argument("--dropout", type=float, default=0.0)
    ap.add_argument("--close-mosaic", type=int, default=10, help="最后N轮关闭mosaic")
    ap.add_argument("--patience", type=int, default=10, help="早停耐心")
    ap.add_argument("--weight-decay", type=float, default=0.0005)
    ap.add_argument("--warmup-epochs", type=int, default=3)
    ap.add_argument("--dataset-desc", default=None)
    ap.add_argument("--box-weight", type=float, default=7.5)
    ap.add_argument("--hsv-h", type=float, default=0.015)
    ap.add_argument("--hsv-s", type=float, default=0.7)
    ap.add_argument("--hsv-v", type=float, default=0.4)
    ap.add_argument("--erasing", type=float, default=0.4)
    ap.add_argument("--optimizer", default="auto")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--parse-check", action="store_true",
                    help="仅解析参数后退出，不执行训练（dry-run 预检）")
    return ap


if __name__ == "__main__":
    a = build_arg_parser().parse_args()
    if a.parse_check:
        print("train_v1 parse-check ok")
        raise SystemExit(0)
    train(a.epochs, a.imgsz, a.batch, a.device, a.model, a.cls_weight, a.run_name,
          a.data_yaml, a.scale, a.lr0, a.mosaic, a.mixup, a.copy_paste,
          a.cos_lr, a.dropout, a.close_mosaic, a.patience, a.weight_decay,
          a.warmup_epochs, a.dataset_desc, a.box_weight, a.hsv_h, a.hsv_s, a.hsv_v, a.erasing,
          a.optimizer, seed=a.seed)
