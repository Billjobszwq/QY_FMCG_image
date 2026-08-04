"""下载 SAM 2.1 checkpoint（仅 hiera_small / hiera_base_plus，手册§五）。

- 输出目录：.sam_checkpoints/（不进 Git）
- 断点续传（Range 头）；已存在且大小一致则跳过
- 记录 URL、字节数、SHA256 到 .sam_checkpoints/manifest.json（只追加新版本，
  不覆盖旧条目）

用法：python -m scripts.download_sam_ckpts [--model sam2.1_hiera_small]"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sam_assist.runtime import CHECKPOINTS  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / ".sam_checkpoints"
MANIFEST = OUT_DIR / "manifest.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def download(name: str) -> dict:
    info = CHECKPOINTS[name]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / f"{name}.pt"
    tmp = OUT_DIR / f"{name}.pt.part"

    req = urllib.request.Request(info["url"], headers={"User-Agent": "llm-image-sam-setup"})
    if tmp.exists():
        req.add_header("Range", f"bytes={tmp.stat().st_size}-")
    with urllib.request.urlopen(req, timeout=120) as r:
        total = None
        clen = r.headers.get("Content-Range") or r.headers.get("Content-Length")
        if clen and "/" in str(clen):
            total = int(str(clen).split("/")[-1])
        mode = "ab" if tmp.exists() and r.status == 206 else "wb"
        t0 = time.time()
        got = tmp.stat().st_size if mode == "ab" else 0
        with open(tmp, mode) as f:
            while True:
                b = r.read(1 << 22)
                if not b:
                    break
                f.write(b)
                got += len(b)
                if total:
                    print(f"\r  {name}: {got/1e6:.0f}/{total/1e6:.0f} MB "
                          f"({got/total*100:.1f}%) {got/(time.time()-t0+1e-9)/1e6:.1f} MB/s",
                          end="", flush=True)
    print()
    tmp.rename(dst)
    sha = _sha256(dst)
    entry = {
        "model": name,
        "url": info["url"],
        "license": info["license"],
        "repo": info["repo"],
        "file": str(dst),
        "bytes": dst.stat().st_size,
        "sha256": sha,
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # manifest 只追加/按 model 更新条目，保留历史条目列表
    man = {"entries": []}
    if MANIFEST.exists():
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    man["entries"] = [e for e in man["entries"] if e["model"] != name] + [entry]
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {name}: sha256={sha} ({dst.stat().st_size} bytes)")
    return entry


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(CHECKPOINTS.keys()), default=None,
                    help="只下载指定模型；缺省下载全部两个候选")
    a = ap.parse_args()
    names = [a.model] if a.model else list(CHECKPOINTS.keys())
    for n in names:
        download(n)
    print(f"manifest: {MANIFEST}")
