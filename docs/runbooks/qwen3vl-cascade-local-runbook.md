# Qwen3-VL 级联本机运行手册（runbook）

> 适用分支：`feat/unified-workbench-training-readiness`
> 状态语义（只写事实，不混用）：
> - `implemented` = 代码已实现；`tested` = 有单元/契约/mock 集成测试通过；
> - `benchmarked/trained/shadow_passed/publish_approved/production_active`
>   均需真实机器证据，当前**全部未达到**。
> - 当前所有真实 Qwen/MLX 重任务状态：**BLOCKED_BY_ACTIVE_TRAINING**
>   或 **G-APPLE 未通过（未安装/未下载）**。

## 0. 前置约束（红线）

1. `sku_v7_sam` 训练运行期间：不得启动任何第二个 MPS/MLX 重任务；
   不得 kill/renice/重启训练进程；不得修改其参数、数据集、输出目录。
2. 下载 `mlx-community/Qwen3-VL-4B-Instruct-4bit` 权重、安装
   mlx/mlx-vlm 必须获得用户明确授权（G-APPLE），且仅在无活跃训练时执行。
3. 业务模型名固定 `qwen3-vl:4b`；Ollama Q4_K_M 推理制品不得作为
   MLX LoRA 训练输入；禁止 `--use-mps`、`--num-epochs` 假设参数。
4. production bundle `prod_20260804_v4_r2` 不切换；
   `production_switch=false` 冻结；8091/8092 保持原状。

## 1. 环境

```bash
# 主环境（测试/纯计算，不安装任何大型依赖）
/Users/zhangweiqi/miniconda3/bin/python3 -m pytest tests -q -p no:cacheprovider

# MLX-VLM 独立环境（本轮未创建；真实执行前需用户授权）
# python3 -m venv .venv_mlx_vlm && .venv_mlx_vlm/bin/pip install mlx-vlm
```

## 2. Preflight（G-CURRENT + G-APPLE）

```bash
# 未授权时 download_authorization_required；训练存在时 active_training_conflict
python3 -m scripts.run_qwen3vl_preflight
# 已获得用户对下载/安装的明确授权后：
python3 -m scripts.run_qwen3vl_preflight --authorized
```

- 12 维 probe（arm64/apple_silicon/mlx_metal_device/model_loadable/
  processor_image/bounded_forward/ac_power/disk_space/memory/swap/
  thermal/service_health）任一失败 → fail-closed，不回 CPU。
- 证据写入 `.eval/vlm_preflight/<run_id>/`（目录已存在即拒绝，防覆盖）。
- swap 停止线 8192MB：超过必须处置后复测。
- 后续所有真实命令都必须引用一份 `ok=true` 的 preflight 报告路径。

## 3. 数据集构建（G-DATA）

```bash
python3 -m scripts.build_qwen3vl_dataset \
    --input <candidates.jsonl> \
    --output <dataset_dir_must_not_exist> \
    --registry-version <registry_hash>
```

- 八维 fail-closed 隔离（customer/store/session/time/package_version/
  SHA/near-duplicate/active protocol）；禁止随机 9:1 划分。
- 输出目录必须不存在；发布为 os.replace 原子动作；泄漏在发布前阻断并清理。
- JSONL 是不可变审计清单；MLX-VLM 实际输入是 images + messages。

## 4. Zero-shot 评估（G-ZERO）

```bash
python3 -m scripts.run_qwen3vl_zero_shot \
    --preflight-report .eval/vlm_preflight/<run_id>/report.json \
    --records <eval_records.jsonl>
```

- 无 `ok=true` preflight 报告直接拒绝执行；逐实例 error_ledger 必须完整。
- 零 coverage → accepted_precision=None，gate_pass=False。

## 5. Benchmark（G-BENCH）

```bash
python3 -m scripts.run_qwen3vl_benchmark \
    --preflight-report .eval/vlm_preflight/<run_id>/report.json
```

- 冻结矩阵 batch 1/2/4 × low/high tokens × qlora/bf16；
  实测字段缺失即 BenchmarkError，禁止照片数估时。
- 真实 batch/token 上限以本命令实测为准，不得假定 batch 16。

## 6. QLoRA pilot（G-PILOT）

```bash
python3 -m scripts.run_qwen3vl_lora \
    --preflight-report .eval/vlm_preflight/<run_id>/report.json \
    --dataset <dataset_dir> --output-dir <new_dir> \
    [--epochs N] [--batch-size N] [--learning-rate R] \
    [--lora-rank R] [--lora-alpha A] [--gradient-accumulation-steps N] \
    [--model-path mlx-community/Qwen3-VL-4B-Instruct-4bit]
```

- 证据链缺一即拒：snapshot/preflight/zero-shot/benchmark；
  epochs/rank/alpha/instance 数超第一轮上限即拒；batch 超 benchmark 即拒。
- 通过门禁后本脚本也只输出冻结命令（blocked=true），不发起真实训练；
  真实提交由 `POST /api/v1/training/runs/vlm/plan`（dry_run）+
  独立授权流程完成，`train_vision` 需单独授权。

## 7. Cascade shadow 评估（G-SHADOW）

```bash
# 纯计算：从账本 JSON 计算指标与晋级门（可与训练并行）
python3 -m scripts.run_cascade_shadow_eval \
    --mode evaluate --input <ledger.json> --output <report.json>

# 真实运行（当前阻断）：
python3 -m scripts.run_cascade_shadow_eval --mode run
# exit 2 = BLOCKED_BY_ACTIVE_TRAINING；exit 3 = 未获授权；
# exit 4 = G-APPLE 未通过（MLX/Qwen 未安装）
```

- 四臂 E0/E1/C1/C2 共享同一 frozen data/registry/region matching；
- accepted precision 与 coverage 必须同时报告；人工真值不足 →
  `not_evaluable`，绝不造 pass；报告见
  `docs/experiments/qwen3vl-cascade-shadow-report.md`。

## 8. 模型驻留（加载/卸载）

- 驻留管理在 `src/platform/model_runtime.py`（ModelResidencyManager）：
  `register/acquire/release/unload_idle/reap_expired`；
  YOLO/ResNet=hot、SAM/OCR/检索=warm、qwen3-vl:4b=cold（max_concurrency=1、
  空闲 TTL 卸载、失败熔断）。
- 只读视图：`GET /api/v1/models/runtime`（Web「模型驻留」页）。
- Qwen 传输为受控 HTTP adapter（`src/modules/fmcg/adapters/qwen3vl_mlx.py`），
  base_url 必须为受控 http(s)；真实服务未启动前 adapter 调用全部熔断。
- 训练存在时资源门禁拒绝加载 Qwen；不得手工 kill 已加载模型进程，
  一律经 TTL 卸载或 residency API。

## 9. 故障排查

| 现象 | 处置 |
|---|---|
| `BLOCKED_BY_ACTIVE_TRAINING` | 等待训练自然结束并完成状态对账（G-CURRENT），不得绕过 |
| `download_authorization_required` | 获取用户明确授权后加 `--authorized`，否则终止 |
| preflight 任一 probe 失败 | fail-closed，逐项修复后重跑；禁止回退 CPU |
| swap 超 8192MB | 处置无关进程/重启后复测，不得带病训练 |
| 输出目录已存在 | 换新 run 目录；不得覆盖历史证据 |
| adapter 熔断/超时 | 级联自动回落人工审核（S5），不无限重试；查 residency 审计 |
| shadow 报 not_evaluable | 补人工 truebox/SKU 真值后重评；不得造 pass |

## 10. 当前阻断清单（截至本手册写入时）

1. sku_v7_sam 训练运行中 → 全部真实 MLX/Qwen 重任务阻断；
2. MLX/mlx-vlm 未安装、权重未下载 → G-APPLE 未通过；
3. 人工 truebox/SKU 真值不足 → shadow 晋级 not_evaluable；
4. 934 张 tilt reject 人工复核未完成；
5. 生产发布（G-PUBLISH）未申请，`production_switch=false`。
