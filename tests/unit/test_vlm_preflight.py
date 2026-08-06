"""VLM-009：Apple/MLX preflight 硬门禁（G-CURRENT / G-APPLE）TDD。

全部使用 fake probes，不下载模型、不运行真实前向。

红线：
- 进程表存在 src.training.train_v1 / mlx_vlm.lora 或存在 active training
  lease → active_training_conflict，ok=false，不得继续；
- 未获得权重下载授权 → download_authorization_required（G-APPLE）；
- 任一必需 probe 缺失或失败 → fail-closed；
- 输出目录已存在 → 拒绝（防覆盖）。
"""

from __future__ import annotations

import pytest

from src.training.vlm.preflight import (
    REQUIRED_PROBES,
    PreflightError,
    run_preflight,
)


def _all_ok_probes() -> dict:
    return {name: (lambda n=name: (True, f"{n} ok")) for name in REQUIRED_PROBES}


def test_all_green_passes() -> None:
    report = run_preflight(probes=_all_ok_probes(), processes=[],
                           active_training_leases=0,
                           download_authorized=True)
    assert report["ok"] is True
    assert report["blockers"] == []


def test_required_probe_names_frozen() -> None:
    # 门禁维度冻结：arm64/Apple Silicon/Metal/模型/processor/有限前向/
    # AC 电源/磁盘/内存/swap/热状态/服务健康
    for name in ("arm64", "apple_silicon", "mlx_metal_device",
                 "model_loadable", "processor_image", "bounded_forward",
                 "ac_power", "disk_space", "memory", "swap", "thermal",
                 "service_health"):
        assert name in REQUIRED_PROBES


@pytest.mark.parametrize("cmd", [
    "python3 -m src.training.train_v1 --run-name sku_v7_sam",
    "python -m mlx_vlm.lora --model mlx-community/Qwen3-VL-4B-Instruct-4bit",
])
def test_active_training_process_conflict_blocks(cmd) -> None:
    report = run_preflight(probes=_all_ok_probes(), processes=[cmd],
                           active_training_leases=0, download_authorized=True)
    assert report["ok"] is False
    assert "active_training_conflict" in report["blockers"]


def test_active_training_lease_conflict_blocks() -> None:
    report = run_preflight(probes=_all_ok_probes(), processes=[],
                           active_training_leases=1, download_authorized=True)
    assert report["ok"] is False
    assert "active_training_conflict" in report["blockers"]


def test_download_not_authorized_blocks() -> None:
    report = run_preflight(probes=_all_ok_probes(), processes=[],
                           active_training_leases=0, download_authorized=False)
    assert report["ok"] is False
    assert "download_authorization_required" in report["blockers"]


def test_missing_probe_fail_closed() -> None:
    probes = _all_ok_probes()
    del probes["disk_space"]
    with pytest.raises(PreflightError):
        run_preflight(probes=probes, processes=[],
                      active_training_leases=0, download_authorized=True)


def test_failed_probe_blocks_with_detail() -> None:
    probes = _all_ok_probes()
    probes["swap"] = lambda: (False, "swap 8192MB 超过停止线")
    report = run_preflight(probes=probes, processes=[],
                           active_training_leases=0, download_authorized=True)
    assert report["ok"] is False
    check = next(c for c in report["checks"] if c["name"] == "swap")
    assert check["ok"] is False and "停止线" in check["detail"]
    assert "swap" in report["blockers"]


def test_probe_exception_is_fail_closed() -> None:
    probes = _all_ok_probes()
    probes["thermal"] = lambda: (_ for _ in ()).throw(RuntimeError("探针崩溃"))
    report = run_preflight(probes=probes, processes=[],
                           active_training_leases=0, download_authorized=True)
    assert report["ok"] is False
    assert "thermal" in report["blockers"]


def test_output_dir_exists_rejected(tmp_path) -> None:
    out = tmp_path / "preflight_run"
    out.mkdir()
    report = run_preflight(probes=_all_ok_probes(), processes=[],
                           active_training_leases=0,
                           download_authorized=True, output_dir=out)
    assert report["ok"] is False
    assert "output_dir_exists" in report["blockers"]


def test_report_keeps_probe_evidence() -> None:
    report = run_preflight(probes=_all_ok_probes(), processes=[],
                           active_training_leases=0, download_authorized=True)
    names = {c["name"] for c in report["checks"]}
    assert set(REQUIRED_PROBES) <= names
    assert all("detail" in c for c in report["checks"])
