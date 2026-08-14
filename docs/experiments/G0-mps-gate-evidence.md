# G0 MPS 硬门禁证据（2026-08-01 训练执行前）

- 手册依据：docs/superpowers/plans/2026-08-04-final-training-execution-gate.md §2.3
- 执行 Terminal：Qoder agent shell（实际训练将使用同一 Python 与同一机器环境）

## 命令输出

```text
$ file python3
python3: Mach-O 64-bit executable arm64

$ python -c '...G0 断言...'
arch arm64
torch 2.13.0
mps_built True
mps_available True
mps_tensor_ok torch.Size([1024, 1024]) mps:0

$ pmset -g batt
Now drawing from 'AC Power'
 -InternalBattery-0 (id=22806627)       100%; charged; 0:00 remaining present: true

$ pmset -g custom   # AC Power 段
powermode            2
```

## 通过判定

| 检查项 | 结果 |
|---|---|
| Python 为 arm64 | PASS（Mach-O arm64，platform.machine()=arm64） |
| torch.backends.mps.is_built() | PASS（True） |
| torch.backends.mps.is_available() | PASS（True） |
| MPS 张量计算 | PASS（1024×1024 矩阵乘，device=mps:0） |
| 已接电源 | PASS（AC Power，电池 100% charged） |
| High Power Mode | 命令行证据：AC Power 段 powermode=2（2=高电量模式，0=默认，1=低电量）。按手册以系统设置可视状态为准，用户如与设置界面不符请立即叫停 |

## 结论

G0 全部自动检查项通过。训练策略：显式 --device mps，不设置
PYTORCH_ENABLE_MPS_FALLBACK，不回退 CPU；训练日志必须出现 device=mps，
否则立即停训。
