"""UMT-002 红测试：dry-run 必须生成 train_v1.py 真实支持的命令。

手册 §3.1 UMT-002 验收口径：
- 命令参数必须全部落在 train_v1.py 真实 argparse 参数集内
  （支持 --data-yaml/--run-name 等；不支持 --dataset/--budget-minutes）；
- 命令必须通过 CLI parse 预检（no-train：--parse-check 只解析不训练）；
- 未知参数 fail-closed，不得入库。

当前 service.py dry_run 生成 `--dataset`/`--budget-minutes`，本测试必须 RED。
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from src.modules.training_gov.service import TrainingGovError, \
    TrainingGovernanceService
from src.platform.data.store import PlatformStore

from tests.platform.test_m5_training_gov import MANIFEST_OK


def make_svc(tmp_path):
    return TrainingGovernanceService(PlatformStore(tmp_path / "p.sqlite"))


def _parse_train_v1(args: list[str]):
    """用 train_v1 真实 argparse 解析（不训练）；未知参数抛 SystemExit。"""
    code = (
        "import sys; sys.argv=['train_v1']+sys.argv[1:]+['--parse-check'];"
        "import runpy; runpy.run_module('src.training.train_v1',"
        " run_name='__main__')"
    )
    p = subprocess.run([sys.executable, "-c", code, *args],
                       capture_output=True, text=True, timeout=120)
    return p


class TestDryRunCommandTruth:
    def test_command_only_uses_real_train_v1_flags(self, tmp_path):
        svc = make_svc(tmp_path)
        snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                     source_actor="a",
                                     source_conclusion="ok")
        run = svc.dry_run(snap["snapshot_id"], actor="op")
        cmd = json.loads(run["command_json"])
        flags = {t for t in cmd if t.startswith("--")}
        assert "--dataset" not in flags, "train_v1.py 不支持 --dataset"
        assert "--budget-minutes" not in flags, \
            "train_v1.py 不支持 --budget-minutes"
        # 数据入口必须是真实存在的 --data-yaml 与 --run-name
        assert "--data-yaml" in flags and "--run-name" in flags

    def test_command_passes_cli_parse_precheck(self, tmp_path):
        """no-train CLI parse 预检：真实子进程跑 --parse-check 退出码 0。"""
        svc = make_svc(tmp_path)
        snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                     source_actor="a",
                                     source_conclusion="ok")
        run = svc.dry_run(snap["snapshot_id"], actor="op")
        cmd = json.loads(run["command_json"])
        assert "--parse-check" in cmd
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, (
            f"CLI parse 预检失败: {p.stderr[-500:]}")
        assert "训练完成" not in p.stdout, "parse-check 不得执行训练"

    def test_dry_run_default_imgsz_not_1280(self, tmp_path):
        svc = make_svc(tmp_path)
        snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                     source_actor="a",
                                     source_conclusion="ok")
        run = svc.dry_run(snap["snapshot_id"], actor="op")
        cmd = json.loads(run["command_json"])
        i = cmd.index("--imgsz")
        assert cmd[i + 1] != "1280", "手册 T0：不得默认 1280"

    def test_unknown_flag_fails_closed(self, tmp_path):
        svc = make_svc(tmp_path)
        snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                     source_actor="a",
                                     source_conclusion="ok")
        with pytest.raises(TrainingGovError):
            svc.dry_run(snap["snapshot_id"], actor="op",
                        extra_args=["--not-a-real-flag"])

    def test_legacy_bad_command_rejected_by_parser(self):
        """旧的无效命令（--dataset）必须被真实 parser 拒绝。"""
        p = _parse_train_v1(["--dataset", "e2@v1", "--epochs", "3"])
        assert p.returncode != 0, "--dataset 应被 train_v1 parser 拒绝"
