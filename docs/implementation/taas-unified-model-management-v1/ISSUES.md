# ISSUES — TaaS 统一模型管理 V1

> 状态：OPEN / MITIGATED / CLOSED_WITH_EVIDENCE / SUPERSEDED。
> 只登记 fresh 复核确认的问题；不凭文档猜测。

## ISS-MM-001 会话默认落在陈旧 worktree — MITIGATED（2026-08-21）

- 证据：会话 cwd 为 `.claude/worktrees/serene-chatelet-28a5df`
  （branch `claude/serene-chatelet-28a5df` @ `3f13fa6b`，仅 Initial commit +
  source-only baseline + cascade fix 三个提交，缺 frontend/web/runtime/
  src/platform 绝大部分内容）。主仓库在 `codex/taas-agent-operation-v1` @
  `5bbbf898`，含 Round 2 受保护未提交资产。
- 处置：全部操作使用主仓库绝对路径（DEC-M011）；不写、不删任何 worktree；
  ExitWorktree 验证不可用（非本会话创建），如实记录。

## ISS-MM-002 05 计划命令含 `PYTHONPATH=src` 陷阱 — MITIGATED（2026-08-21）

- 证据：Research RAG 轮 ISS-014 已确认 `PYTHONPATH=src` 使 `src/platform`
  遮蔽 stdlib `platform`，pytest 触发 INTERNALERROR。
- 处置：本轮 pytest 命令不加 `PYTHONPATH=src`（DEC-M012），其余与 05 计划一致。

## ISS-MM-003 VLM/OCR/embedding 独立 CLI 仍走 legacy env 通道 — OPEN（受控遗留）

- 证据：`src/pipeline/recognize.py`、`src/labeling/assign.py` 等独立
  pipeline CLI 经 `src/common/omlx.py` 使用 OMLX_API_KEY（.env）；
  V1 未绑定受管 VLM/OCR 模型，不能伪造迁移完成。
- 处置（M8 已做的最小收口）：omlx.py 标注为迁移期兼容层，
  `provider_source()` 显式暴露来源 + 首次使用一次性告警；
  平台运行态（认知索引/Agent）已改经受管连接与账本。
- 后续：为 VLM/OCR 建立受管连接与目录条目后，把 CLI 调用点切到
  统一解析（保留本通道至停用公告）。
