# 本地资产布局

仓库只版本化源码和说明文件。数据、模型和运行状态必须放在标准本地区域，实际内容不进入 Git；克隆代码不会下载或切换模型，也不会恢复任何用户数据。

## 三个标准区域

| 区域 | 用途 | 版本控制边界 |
|---|---|---|
| `training-data/` | 原始输入、加工数据集、训练集和评估集 | 仅跟踪区域 README；照片、标注、表格和生成数据不进入 Git |
| `recognition-models/` | 生产、候选、基础模型、checkpoint 和本地 registry | 仅跟踪区域 README；权重和 bundle 不进入 Git |
| `runtime/` | 数据库、日志、缓存、导入、审核队列和服务状态 | 仅跟踪区域 README；所有运行记录不进入 Git |

这些目录由 `.gitignore` 保护。不要用 `git add -f` 绕过边界；需要共享的最小测试 fixture 应脱敏后放入明确的测试目录，并通过发布树审计。

## 初始化与检查

从仓库根目录先运行无修改预检：

```bash
python3 scripts/bootstrap_local_assets.py --dry-run
```

确认没有 conflict 后再创建缺失目录和相对兼容链接：

```bash
python3 scripts/bootstrap_local_assets.py
python3 scripts/bootstrap_local_assets.py --dry-run
```

脚本不覆盖现有文件、目录或指向其他目标的链接。第二次 dry-run 中的 `unchanged` 表示链接已指向标准本地区域；`conflict` 必须人工核对，不能直接删除原内容。

## 兼容链接

旧入口均为仓库内相对链接，方便现有代码继续工作；真实资产仍只存在于三个标准区域。

| 兼容入口 | 标准相对目标 |
|---|---|
| `.models` | `recognition-models/registry` |
| `.sam_checkpoints` | `recognition-models/foundation/sam` |
| `.datasets` | `training-data/processed/datasets` |
| `.datasets_nextgen` | `training-data/processed/datasets-nextgen` |
| `.training_data` | `training-data/processed/training-data` |
| `.batch3_clean` | `training-data/processed/batch3-clean` |
| `.kb` | `training-data/processed/knowledge-base` |
| `.micro_gold_v1` | `training-data/evaluation/micro-gold-v1` |
| `.micro_gold_v2` | `training-data/evaluation/micro-gold-v2` |
| `.data_protocol` | `training-data/evaluation/data-protocol` |
| `.eval` | `training-data/evaluation/legacy-eval` |
| `.platform` | `runtime/platform` |
| `.label-studio` | `runtime/label-studio` |

## 本机恢复原则

- 从受控备份或原始数据源恢复资产，不从 Git 历史寻找数据或模型。
- 不在文档、提交信息或测试输出中记录用户文件名、绝对路径、凭据或客户标识。
- 生产与候选模型的选择由本地 registry 管理；bootstrap 只建目录和链接，不改变选择。
- 数据导入、训练和服务运行只写本地区域；形成新版本前运行发布树审计并确认 finding 为零。
