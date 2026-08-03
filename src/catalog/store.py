"""本地知识库存储：内容寻址 blob + JSON 元数据 + numpy 向量 + 余弦检索。

存储抽象的本地实现；后续可平替为 MinIO(blob) + pgvector(向量) + Postgres(元数据)，接口不变。
RA-019：以版本目录为发布单元 —— skus/vectors/ids/manifest 完整写入
root/versions/<vN>/ 并逐文件校验哈希后，只原子切换一个 CURRENT 指针；
任何时刻读者看到的都是某个完整版本，不会出现新旧混合；
loader 打开前先校验 bundle manifest 哈希，再读内容。"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np


class StoreIntegrityError(Exception):
    """KB 资产不一致（向量行数 vs ID 数 / manifest 校验失败）。"""


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.versions = self.root / "versions"
        self.current_ptr = self.root / "CURRENT.json"
        for d in (self.root, self.blobs, self.versions):
            d.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, h: str) -> Path:
        return self.blobs / h[:2] / h

    def _active_dir(self) -> Path:
        """RA-019：读 CURRENT 指针解析当前版本目录；无指针时回退旧式根目录布局。"""
        if self.current_ptr.exists():
            try:
                vname = json.loads(self.current_ptr.read_text(encoding="utf-8"))["version"]
                d = self.versions / vname
                if (d / "manifest.json").exists():
                    return d
            except Exception:
                pass
            raise StoreIntegrityError(f"CURRENT 指针指向的版本不可用: {self.current_ptr}")
        return self.root  # 旧式布局兼容

    @staticmethod
    def _verify_dir(d: Path) -> None:
        """RA-019：打开前逐文件校验 manifest 哈希，任何篡改/损坏拒绝加载。"""
        mp = d / "manifest.json"
        if not mp.exists():
            raise StoreIntegrityError(f"版本目录缺 manifest: {d}")
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        for name, info in manifest.get("files", {}).items():
            fp = d / name
            if not fp.exists():
                raise StoreIntegrityError(f"KB 版本文件缺失: {fp}")
            b = fp.read_bytes()
            if len(b) != info["size"] or hashlib.sha256(b).hexdigest() != info["sha256"]:
                raise StoreIntegrityError(f"KB 版本文件哈希不匹配: {fp}")

    def put_blob(self, data: bytes, h: str) -> tuple[str, bool]:
        p = self._blob_path(h)
        existed = p.exists()
        if not existed:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return h, existed

    def save(self, skus: list[dict], vector_ids: list[str], vectors) -> None:
        """RA-019：版本目录完整构建 → 自校验 → 原子切换 CURRENT 指针。

        任何阶段中断都不会影响线上版本（旧指针仍指向完整版本）。"""
        vec = np.asarray(vectors, dtype="float32")
        if vec.ndim != 2 or vec.shape[0] != len(vector_ids):
            raise StoreIntegrityError(
                f"向量行数 {0 if vec.ndim != 2 else vec.shape[0]} != ID 数 {len(vector_ids)}，拒绝写入")
        vname = f"v_{int(time.time() * 1000)}_{os.getpid()}"
        vdir = self.versions / vname
        vdir.mkdir(parents=True, exist_ok=False)
        try:
            # 1) 版本目录内完整写好三件套
            np.save(vdir / "vectors.npy", vec)
            (vdir / "vector_ids.json").write_text(
                json.dumps(vector_ids, ensure_ascii=False), encoding="utf-8")
            (vdir / "skus.json").write_text(
                json.dumps(skus, ensure_ascii=False, indent=2), encoding="utf-8")
            # 2) manifest：文件名/大小/哈希/计数/时间
            manifest = {"schema_version": 2, "ts": time.time(), "version": vname,
                        "n_skus": len(skus), "n_vectors": int(vec.shape[0]),
                        "files": {}}
            for name in ("vectors.npy", "vector_ids.json", "skus.json"):
                b = (vdir / name).read_bytes()
                manifest["files"][name] = {
                    "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
            (vdir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            # 3) 发布前自校验（哈希/行数/ID 数）——失败则不切指针
            self._verify_dir(vdir)
            ids_chk = json.loads((vdir / "vector_ids.json").read_text(encoding="utf-8"))
            vec_chk = np.load(vdir / "vectors.npy")
            if vec_chk.shape[0] != len(ids_chk):
                raise StoreIntegrityError("版本自校验失败：向量行数 != ID 数")
            # 4) 原子切换 CURRENT 指针（单文件 os.replace）——发布完成
            tmp = self.current_ptr.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": vname, "ts": time.time()}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self.current_ptr)
            # 5) 清理旧版本（保留最近 3 个供回滚）
            known = {vname}
            try:
                cur = json.loads(self.current_ptr.read_text(encoding="utf-8"))
                known.add(cur.get("version", ""))
            except Exception:
                pass
            old = sorted([d for d in self.versions.iterdir() if d.is_dir()
                          and d.name not in known], reverse=True)
            for d in old[3:]:
                for f in d.iterdir():
                    try:
                        f.unlink()
                    except Exception:
                        pass
                try:
                    d.rmdir()
                except Exception:
                    pass
        except Exception:
            # 发布失败：清理半成品版本目录，旧版本继续服务
            for f in vdir.iterdir():
                try:
                    f.unlink()
                except Exception:
                    pass
            try:
                vdir.rmdir()
            except Exception:
                pass
            raise

    def load_vectors(self) -> tuple[list[str], np.ndarray]:
        d = self._active_dir()
        if (d / "manifest.json").exists():
            self._verify_dir(d)  # RA-019：先校验 manifest 哈希，再打开内容
        ids = json.loads((d / "vector_ids.json").read_text(encoding="utf-8"))
        vec = np.load(d / "vectors.npy")
        # ISSUE-019：一致性闸门 —— 行数与 ID 数不一致时明确拒绝
        if vec.ndim != 2 or vec.shape[0] != len(ids):
            raise StoreIntegrityError(
                f"KB 不一致：向量行数 {0 if vec.ndim != 2 else vec.shape[0]} != ID 数 {len(ids)}，拒绝加载")
        return ids, vec

    def load_skus(self) -> list[dict]:
        d = self._active_dir()
        if (d / "manifest.json").exists():
            self._verify_dir(d)
        return json.loads((d / "skus.json").read_text(encoding="utf-8"))

    @staticmethod
    def search(qvec, ids: list[str], vec: np.ndarray, topk: int = 5) -> list[tuple[str, float]]:
        q = np.asarray(qvec, dtype="float32")
        q = q / (np.linalg.norm(q) + 1e-9)
        nv = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-9)
        sims = nv @ q
        order = np.argsort(-sims)[:topk]
        return [(ids[i], float(sims[i])) for i in order]
