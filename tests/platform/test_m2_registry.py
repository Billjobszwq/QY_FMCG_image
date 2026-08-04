"""W6/M2：Capability Registry、Job/Attempt 状态机、RequestContext、依赖方向守卫 TDD。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.platform.api.app import create_app
from src.platform.api.context import new_request_context
from src.platform.jobs import JobTransitionError, allowed_transitions, transition
from src.platform.registry import (
    CapabilityRegistry,
    CapabilitySpec,
    ModuleManifest,
    RegistryError,
    bootstrap_default_registry,
)


# ---------- Capability Registry ----------

def _manifest(module_id: str = "mod.a") -> ModuleManifest:
    return ModuleManifest(
        module_id=module_id,
        name="Module A",
        version="1.0.0",
        capabilities=[CapabilitySpec(capability_id="a.cap1", kind="compute", description="cap")],
    )


def test_register_and_lookup() -> None:
    reg = CapabilityRegistry()
    adapter = object()
    reg.register(_manifest(), adapters={"a.cap1": adapter})
    assert reg.get("a.cap1") is adapter
    infos = reg.capabilities()
    assert len(infos) == 1
    assert infos[0]["module_id"] == "mod.a"


def test_duplicate_capability_rejected() -> None:
    reg = CapabilityRegistry()
    reg.register(_manifest(), adapters={"a.cap1": object()})
    with pytest.raises(RegistryError):
        reg.register(_manifest(module_id="mod.b"), adapters={"a.cap1": object()})


def test_duplicate_module_rejected() -> None:
    reg = CapabilityRegistry()
    reg.register(_manifest(), adapters={"a.cap1": object()})
    with pytest.raises(RegistryError):
        reg.register(
            ModuleManifest(
                module_id="mod.a",
                name="dup",
                version="2.0.0",
                capabilities=[CapabilitySpec(capability_id="a.cap2", kind="k", description="d")],
            ),
            adapters={"a.cap2": object()},
        )


def test_missing_adapter_rejected() -> None:
    reg = CapabilityRegistry()
    with pytest.raises(RegistryError):
        reg.register(_manifest(), adapters={})


def test_unknown_capability_raises() -> None:
    reg = CapabilityRegistry()
    with pytest.raises(RegistryError):
        reg.get("does.not.exist")


def test_legacy_adapters_registered() -> None:
    reg = bootstrap_default_registry()
    ids = {c["capability_id"] for c in reg.capabilities()}
    assert ids == {"legacy.recognition.v2", "legacy.training.monitor", "legacy.label_studio"}


# ---------- Job/Attempt 状态机 ----------

def test_job_transitions() -> None:
    assert allowed_transitions("queued") == {"running", "cancelled"}
    assert "succeeded" in allowed_transitions("running")
    assert transition("queued", "running") == "running"
    assert transition("running", "failed") == "failed"
    # 失败可重新排队（重试语义），成功/取消为终态
    assert transition("failed", "queued") == "queued"
    assert allowed_transitions("succeeded") == set()
    assert allowed_transitions("cancelled") == set()


def test_illegal_transition_raises() -> None:
    with pytest.raises(JobTransitionError):
        transition("queued", "succeeded")
    with pytest.raises(JobTransitionError):
        transition("succeeded", "running")
    with pytest.raises(JobTransitionError):
        transition("bogus", "running")


# ---------- RequestContext ----------

def test_request_context_utc_and_ids() -> None:
    ctx = new_request_context(idempotency_key="k1")
    assert ctx.request_id
    assert ctx.idempotency_key == "k1"
    assert ctx.created_at.endswith("+00:00") or ctx.created_at.endswith("Z")
    ctx2 = new_request_context()
    assert ctx2.request_id != ctx.request_id


def test_request_id_middleware_header() -> None:
    app = create_app(services=(), probe=lambda spec, **kw: None)
    client = TestClient(app)
    r = client.get("/api/v1/version")
    assert r.headers.get("x-request-id")
    # 客户端指定则沿用
    r2 = client.get("/api/v1/version", headers={"x-request-id": "fixed-id"})
    assert r2.headers["x-request-id"] == "fixed-id"


# ---------- /api/v1/capabilities ----------

def test_capabilities_endpoint() -> None:
    app = create_app(services=(), probe=lambda spec, **kw: None)
    client = TestClient(app)
    r = client.get("/api/v1/capabilities")
    assert r.status_code == 200
    body = r.json()
    ids = {c["capability_id"] for c in body["capabilities"]}
    assert ids == {"legacy.recognition.v2", "legacy.training.monitor", "legacy.label_studio"}
    assert body["count"] == 3


# ---------- 依赖方向守卫 ----------

def test_platform_does_not_import_domain_modules() -> None:
    """红线：src/platform 不得 import src/modules 或任何领域包（只能经 Capability 注册）。"""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "platform"
    forbidden_roots = {"src.modules", "src.catalog", "src.recognize", "src.labeling",
                       "src.training", "src.field", "src.eval", "src.pipeline",
                       "src.data", "src.common"}
    violations = []
    for py in root.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        pkg_parts = py.parent.relative_to(root.parent.parent).parts  # ('src','platform',...)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    names = [node.module or ""]
                else:
                    base = pkg_parts[: len(pkg_parts) - node.level + 1] if node.level <= len(pkg_parts) else ()
                    names = [".".join([*base, node.module] if node.module else list(base))]
            else:
                continue
            for n in names:
                if any(n == f or n.startswith(f + ".") for f in forbidden_roots):
                    violations.append(f"{py}: {n}")
    assert violations == [], violations
