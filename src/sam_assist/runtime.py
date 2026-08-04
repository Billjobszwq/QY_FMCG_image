"""SAM 2.1 隔离 runtime：设备门禁、checkpoint 登记、embedding 缓存。

本模块不含 SAM 权重加载；权重加载与推理在隔离 venv（.venv_sam）中由
service.py 子进程执行（手册§一.8）。设备门禁 fail-closed：
MPS 不可用或设置了 PYTORCH_ENABLE_MPS_FALLBACK 一律拒绝运行（手册§一.7）。"""
from __future__ import annotations

import collections
import os
import platform
import sys

# SAM 2.1 候选 checkpoint（手册§五：只比较 Small / Base+，不得下载 Large，
# SAM 3/3.1 官方依赖 CUDA，不进入本机实现）。
CHECKPOINTS = {
    "sam2.1_hiera_small": {
        "url": "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt",
        "config": "configs/sam2.1/sam2.1_hiera_s.yaml",
        "license": "Apache-2.0",
        "repo": "facebookresearch/sam2",
    },
    "sam2.1_hiera_base_plus": {
        "url": "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt",
        "config": "configs/sam2.1/sam2.1_hiera_b+.yaml",
        "license": "Apache-2.0",
        "repo": "facebookresearch/sam2",
    },
}


class DeviceGateError(RuntimeError):
    """MPS 门禁失败：立即停止，禁止静默 CPU fallback。"""


def _mps_built() -> bool:
    import torch
    return bool(torch.backends.mps.is_built())


def _mps_available() -> bool:
    import torch
    return bool(torch.backends.mps.is_available())


def device_report() -> dict:
    """手册§五要求的运行环境事实报告。"""
    import torch
    mps_built = _mps_built()
    mps_avail = _mps_available()
    return {
        "python": platform.python_version(),
        "torch_version": torch.__version__,
        "machine": platform.machine(),
        "platform": platform.platform(),
        "mps_built": mps_built,
        "mps_available": mps_avail,
        "device": "mps" if mps_avail else "cpu",
        "fallback_env_set": "PYTORCH_ENABLE_MPS_FALLBACK" in os.environ,
    }


def check_device_gate(env: dict | None = None) -> dict:
    """MPS 门禁：fail-closed。返回环境报告；任何异常路径抛 DeviceGateError。"""
    env = os.environ if env is None else env
    if env.get("PYTORCH_ENABLE_MPS_FALLBACK"):
        raise DeviceGateError(
            "检测到 PYTORCH_ENABLE_MPS_FALLBACK：禁止静默 CPU fallback（手册§一.7）")
    rep = device_report()
    if not rep["mps_built"]:
        raise DeviceGateError("MPS 未构建（torch.backends.mps.is_built()=False）")
    if not _mps_available():
        raise DeviceGateError("MPS 不可用：拒绝运行，禁止回退 CPU")
    return rep


class EmbeddingCache:
    """按原图 SHA256 缓存 image embedding：每图只算一次（手册§五）。"""

    def __init__(self, max_entries: int = 16):
        self.max_entries = max_entries
        self._d: collections.OrderedDict = collections.OrderedDict()

    def get(self, image_sha: str):
        if image_sha in self._d:
            self._d.move_to_end(image_sha)
            return self._d[image_sha]
        return None

    def put(self, image_sha: str, embedding) -> None:
        self._d[image_sha] = embedding
        self._d.move_to_end(image_sha)
        while len(self._d) > self.max_entries:
            self._d.popitem(last=False)

    def size(self) -> int:
        return len(self._d)
