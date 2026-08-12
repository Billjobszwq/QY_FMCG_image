# 01 · 根因与契约

## RC-1 门头必拍可绕过（照片契约）

根因：`survey.py` 照片题契约只有 `min_count`；`submit` 用
`min_count>0` 才计数 media；`attach_media` 无 `capture_role` 参数，
media 表无角色列；`require_storefront` 字段仅存在于模板文案，
lint/submit 均不校验。
契约修复：
- 题目新增 `max_count / capture_role(storefront|shelf|employee_selfie|
  product|other) / quality_gate / recognition_enabled /
  recognition_profile_id / manual_confirmation_required`；
- `survey_media_v1` 增加 `capture_role / status`（migration 047）；
- lint：`require_storefront=true` 必须存在至少一道
  `capture_role=storefront` 的照片题配置；`required=true` 与
  `min_count=0` 冲突拒绝；
- submit：只校验可见题；门头必拍题必须至少 1 张
  `capture_role=storefront` 且归属本 response/question、状态有效
  的 media；`min_count/max_count` 双向校验；错误指明题目与缺失类型；
  原子提交，任一失败整份不得 submitted。

## RC-2 Agent Usage 无统一链

根因：`agents/runtime.py invoke` 只写 `agent_run_v1` + usage
（`run_id=''`），未创建 BusinessRun/WorkItem/Evidence；
`except Exception: pass` 吞错。
契约修复（身份模型）：每次 invoke 创建
`business_run_v1`（command_kind=`agent.invoke`，含
agent_id/definition_version/provider/correlation/parent_run_id/
customer/project/tenant）+ WorkItem + EvidenceBundle；usage 挂
run_id/work_id；失败也写失败 run + 已消耗 usage；Usage/Evidence 写失败
fail-closed（不静默）。历史 12 条：追加式 attribution 账本
（migration 047 `usage_attribution_v1`），UI 显示“历史未归属”。

## RC-3 Workflow parallel 伪并行

根因：parallel 仅串行扇出；join 靠 frontier 重排。
契约修复：真实有界并行——分支独立身份（branch_id）、独立 ctx 副本、
`max_concurrency` 信号量、durable 分支状态（migration 047
`workflow_branch_v1`）、分支级失败/超时、join all/any/quorum、
any/quorum 达成后取消剩余分支、进程重启恢复、合并冲突规则
（分支输出写入 `branch:<id>` 命名空间再合并）、Evidence/Usage 带
branch_id。wall-time 证明：2×2s wait，串行≈4s、并行≈2s。

## RC-4 shadow 证据口径

根因：脚本读 `name` 键（实际 `sku_name`）；无 hash/负样本/延迟口径。
契约修复：`extract_products` 读 sku_id/sku_name/confidence/margin/box/
status；记录 detector/classifier/registry/threshold hash；区分
load smoke / detection comparison / latency regression（无 GT 不写
准确率结论）；V4 状态改 `USER_SELECTED_UAT_MODEL`。

## RC-5 rate limit 缺失

契约：`rate_limit_v1`（migration 047）窗口计数（主体+能力+IP），
窗口/burst/retry-after；429 结构化；审计事件；重启后窗口不完全丢失
（SQLite 持久化）；默认额度不影响正常 UAT；管理端点（管理员）。

## RC-6 UAT 预演与 Gate 判定

契约：`scripts/uat_report_validator.py`（必填 ID/实体清单，缺一失败；
inserted=0 不得记成功）；`src/platform/gate_evaluator.py`
（P0/P1/场景/限流/并行任一不满足即拒绝 READY）。
UAT V2：每次运行唯一 namespace `uatv2_<ts>_<rand>`，全部实体新建。
