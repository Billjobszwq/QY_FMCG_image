"""reference.echo manifest + adapter。

只经组合根装配（src/platform 不 import 本模块）。注册后即可被
/api/v1/modules 发现、/api/v1/reference/echo 调用；不依赖任何
识别/训练领域代码，用于验证 Module Manifest V2 的通用性。
"""
from __future__ import annotations

from typing import Any

CAPABILITY_ID = "reference.echo"


class EchoAdapter:
    """最小 capability adapter：原样回显输入（含幂等示例）。"""

    @property
    def capability_id(self) -> str:
        return CAPABILITY_ID

    def echo(self, text: str) -> dict[str, Any]:
        return {"module_id": "reference.echo", "echo": text,
                "capability": CAPABILITY_ID, "status": "ok"}


def register_reference_echo(cap_registry: Any) -> None:
    """把 echo capability 注册进平台 CapabilityRegistry（fail-closed）。"""
    from src.platform.registry import CapabilitySpec, ModuleManifest

    cap_registry.register(
        ModuleManifest(
            module_id="reference.echo",
            name="Reference Echo Module",
            version="1.0.0",
            capabilities=[
                CapabilitySpec(capability_id=CAPABILITY_ID,
                               kind="reference",
                               description="平台通用性参考能力（echo）"),
            ],
        ),
        adapters={CAPABILITY_ID: EchoAdapter()},
    )
