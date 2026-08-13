# FINAL-REPORT — Operational Scope V5.2 Correction

> 数字单一事实源：`.eval/scope_v5/machine_facts.json`（
> scripts/osv51_machine_facts.py 机器生成）。本报告不手工复录会随
> 证据再生成变化的数字。

## 1. HEAD / branch / worktree

见 machine_facts → git.*。基线 8cb51dcf（V5.1 收尾）；本轮提交链见
§2。主仓工作；.claude/worktrees/upbeat-archimedes-158fe1 为过期
docs worktree，全程未作为项目状态读写。

## 2. commit 链

`git log --oneline 8cb51dcf..HEAD`：2268aa02（红测试+治理目录）→
d9fe9657（哈希重校验+Active Gate Registry+负例27）→ 0a574772（URL
同步）→ abb241da（测试质量+首页H1）→ 28589e90（CAS 红）→ 1d6cf060
（CAS 绿）→ 1a3994f2（激活端点修复+Web面板+API测试）→ 本文档提交。

## 3. before 复现

QA ISSUE-001 现场复现：gate.json 记录 negative 哈希
3dd868a16e585276，QA 重跑负例脚本后当前文件 52da2afd4f9579f4，实时
/api/v1/control/gate 仍 READY_FOR_REAL_DATA_UAT（freshness 从未重算
evidence_hashes）。快照见 before-snapshots/。修复开工后实时 Gate 即
改为 fail-closed（先 BLOCKED_BY_GATE_EVIDENCE：无 active run；篡改
语义由 BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT 承接）。

## 4. evidence hash 断链修复

- gate.json 写入 evidence_manifest：五份证据（uat/test/browser/
  negative/issue ledger）× {根相对路径, SHA256, 大小, 生成时间}。
- 实时 freshness 复评每次重读重算：整文件哈希/尺寸不符 →
  BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT；缺失/路径越界/符号链接逃逸/
  JSON 不可解析 → STALE_GATE_EVIDENCE。
- 分层校验：evidence_file_hashes_fresh（整文件）、
  evidence_binding_fresh_live（binding 块 vs 当前 HEAD/树/迁移）、
  evidence_result_hash_fresh（按 kind 重建载荷 hash）分别报告。
- 评估器 3.4.0；osv5_gate_evaluate.py 生成时登记 candidate。

## 5. Active Gate Registry

- 迁移 061 gate_run_v1（append-only，禁 DELETE）；字段含 gate_run_id/
  protocol/gate_path/gate_file_sha256/source_commit/
  evaluator_version/evidence_manifest_hash/status/requested_by/
  activated_by/activated_at/supersedes。
- 实时端点只读 status=active 的 scope_v5 run；无 active/文件缺失/
  文件哈希与 registry 不一致 → BLOCKED_BY_GATE_EVIDENCE（fail-closed）。
- 激活：POST /api/v1/control/gate/activate（平台角色 + approved=true
  + CAS candidate→active；旧 active→superseded；expected_protocol
  不匹配拒绝——旧 scope 重跑不得接管）。mtime 选择已废除。
- Web 状态页展示 active gate_run_id/协议/激活时间/manifest hash。

## 6. 所有新增负例（21→27，ALL_BLOCKED）

22 tamper_rewrite_negative_report_after_gate → HASH_DRIFT；
23 tamper_rewrite_test_report_after_gate → HASH_DRIFT；
24 tamper_replace_browser_evidence_after_gate → HASH_DRIFT；
25 tamper_delete_uat_report_after_gate → STALE；
26 tamper_body_keep_binding_after_gate → HASH_DRIFT；
27 tamper_symlink_escape_evidence_path → STALE。
全部经与实时端点相同的 freshness 复评路径执行；收尾另做端到端
实时篡改演练（§12）。

## 7. URL 状态修复

Import Center 视图 = URL ?view= 单一事实源；首次渲染从 query 初始化；
页签点击 PUSH 更新 URL（前进/后退一致）；未知 view REPLACE 规范化为
operational；浏览器断言 import_url_view_api_consistent（四视图×四视口：
页签 aria-selected 文本 == 视图标签、DOM 行数 == API 行数、URL 含
view=X）+ import_unknown_view_normalized。

## 8. 测试 warning 修复

唯一违规 test_first_commit_delivers_once 改纯断言（复用提升为模块级
helper _commit_users）；AST 扫描确认测试函数零非 None 返回；
osv51_test_report.py 强制 -W error::pytest.PytestReturnNotNoneWarning
（不得过滤/降级）。全量结果见 machine_facts → tests.*。

## 9. 首页无障碍修复

Home 加载中分支也渲染 page-header H1（此前仅数据加载后出现）；
ScrollManager 焦点落点 + aria-live 覆盖首页；浏览器断言
home_unique_h1_focus（唯一 H1 且导航进入后 activeElement=H1）；
Supervisor 抽屉为独立组件未受影响。

## 10. OSV51-013 结论

调用方普查：set_business_run_status 全部调用方位于 control_plane/
workflow/agents runtime（均为执行域），无非 workflow 域调用方。
但函数是公共 store 方法且竞态已实证（旧实现 1500 轮并发 1301 轮
双写覆盖终态），故按条件 UPDATE/CAS 结构性关闭（不走“文档声明不
可达”路线）：UPDATE … WHERE run_id=? AND status=<读取时 cur>；
CAS 失败 → 幂等（当前态==目标态）或冲突拒绝；succeeded/cancelled
绝对终态（RUN_TRANSITIONS 无出边）；failed/partial_failed 仅
retry→running。复测 1500/1500 恰一赢家 0 覆盖；套件内 300 轮竞争
+ 60 轮同目标 + 终态不可回退/迟到写/重复写 7 测试全绿。

## 11. 全量测试与浏览器结果

machine_facts → tests/browser.*：hermetic 全量（-W error 门禁）、
host MPS、浏览器 pages/assertions/console。

## 12. 静态/实时 Gate 对账

- 收尾流程：证据链再生（UAT→browser→test→negative）→
  osv5_gate_evaluate.py（写 manifest + 登记 candidate）→ 平台角色
  人工批准激活 → 实时 /api/v1/control/gate 复核（active 元数据 +
  freshness_verified_at）。
- 篡改演练：激活后重写 gate_negative_tests.json → 实时端点立即
  BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT；恢复只走重跑（negative→gate
  →重新激活），不手工改 hash。
- machine_facts → gate.* 记录收尾静态值；实时值以复评为准。

## 13. production / 训练声明

本轮未 publish/rollback/switch bundle（production 保持
prod_v4_best_r1，见 machine_facts → production）；未启动训练
（training_processes=0）；未 merge/push/deploy；未修改真实业务数据；
全部历史证据保留（含 V5.1 before-snapshots 与本轮快照）。

## 14. 未关闭问题

- OSV52-007（P2）：vendor-maplibre 约 949KB（gzip 248KB）性能债务，
  本轮按任务书只登记不重构。
- 隔离区三批次的最终业务处置（绑定/软作废/转正式）仍待用户从 UI
  裁决（当前 retained_for_evidence）。

## 15. 用户下一步

1. 真实数据 UAT：Import Center 运营视图导入真实客户/门店/问卷并贯穿
   dry-run→提交→BI/工作台（Gate 已 READY 后方可开始）。
2. 隔离区裁决：Import Center → 隔离待处理 → 三个批次执行
   绑定 Test Run / 软作废 / 申请转正式（双人审批）。
3. 人工走查：系统状态页 Active Gate 面板、四视图 URL 直连/刷新、
   首页焦点。
4. 真实 UAT + 人工验收通过前不得宣称 ACCEPTED / PRODUCTION_READY。
