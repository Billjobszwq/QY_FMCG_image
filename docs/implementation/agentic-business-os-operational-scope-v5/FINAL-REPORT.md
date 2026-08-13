# FINAL-REPORT · Operational Scope V5（指令第十六节 · 53 项）

诚实边界：机器 Gate 只能输出 READY_FOR_REAL_DATA_UAT 或具体
BLOCKED；真实数据 UAT 与人工验收由用户执行，此前不写
ACCEPTED/COMPLETE/PRODUCTION_READY。

## 1. HEAD / branch / worktree
- branch：feat/nextgen-training-cycle-v2
- HEAD：见收尾提交（`git log --oneline -1`；Gate 以该 HEAD 绑定）
- tracked worktree：干净（`git status --porcelain --untracked-files=no` 为空；
  Gate tracked_worktree_clean 检查消费）

## 2. commit 链
6ec99985(V4 收尾) → osv5(T0,T1) 审计+治理+32 红测试 → osv5(T2,T3)
批次执行上下文+IAM/DTO → osv5(T4,T6,T9) 可执行 Registry+Gate 3.2+
session → osv5(T5,T6) 纠偏+负例 → osv5(T7) UAT V7 → osv5(T8) 浏览器
29/29 → osv5(T10) 收口。全部小步、显式文件清单、无 add -A。

## 3. 完整阅读清单
READING-LIST.md 29 项全部 READ（含 GLOBAL_AGENT_ROUTING、V3/V4 全
目录、50 commits、scope/import/gate/iam 源码、数据库 schema 对账）。

## 4. 开工现场
00-LIVE-AUDIT.md：基线 11 项与指令全一致（HEAD/服务/production/
integrity/20 条批次/BI 污染/Gate 错误 READY/3.0.0）。

## 5. 数据库备份与 hash
`.platform/backups/platform_pre_scope_v5_20260813T124408.sqlite`；
备份库 sha256 `f1f92091f1b2001b0cd6f338f7a74d988b63e4ecce3fec66f03f98ea8c53b284`；
源库 sha256 `694ce1d71a88c00503ee22ac934730ccfb6aed8173a0951730016ce2aba29a01`；
双向 integrity_check=ok。

## 6. Before 红测试
tests/platform/test_osv5_import_scope.py 32 项；首跑 27 failed /
5 诚实绿（r06 现状恰好满足；r12/r13 恰被状态机 409 拦下；r24/r28
现状恰好可解析/可捕获），EXECUTION-LOG T1 段登记。

## 7. 发现问题清单
ISSUES.md：OSV5-001…012（P0×6 / P1×4 / P2×2）全部 CLOSED（附证据）。

## 8. 20 条 import 污染证据
before：`.eval/scope_v5/before/before_audit_v5.json`（SQL 20/20/20；
/import/batches count=20；data-products import.batches_v1=20；详情
returns_mapping_json=true）。after：operational=0（见 16/17）。

## 9. 跨角色越权复现
before 静态事实（import_api.py 仅 require_principal）+ 红测试 r09–r14
（临时库 TestClient）：read_only list/detail/dry-run/commit/errors.csv
全部复现可越权 → 修复后全 403（r10–r14 绿；UAT V7 检查 4/12/13；
负例 3/4/5 阻断）。

## 10. 原始数据泄漏复现
before_audit_v5.json p0004_detail_leak_surface（4 类原始 JSON 全返回）
→ batch_dto 白名单 + preview 授权脱敏（r15/r16 绿；浏览器 14/14b；
负例 6）。

## 11. Scope Registry/23/18 平行清单根因
before_audit_v5.json p0005（125/23/18 + import_batch_v1 未进
scanner/archiver）。修复：`_SCOPED_TABLES=leak_scan_tables()`、
`_SCOPED_DOMAIN_TABLES=archivable_tables()`、ARCHIVE_HANDLERS、
Gate 覆盖派生（scope_audit_v5.py 第 3/4 维验证相等）。

## 12. Registry 无效字段统计
before：35 假 pk / 5 假 customer_col（含 import_batch_v1.customer_id）
/ 115 幻影 tenant_col。after：全部修正（真实列/composite:/留空=
not_applicable）；validate_registry 零错误（r22；负例 7 验证可检出）。

## 13. 修复后的导入作用域模型
01-IMPORT-SCOPE-CONTRACT.md + 迁移 059：批次冻结 data_scope/
test_run_id/visibility/archived_at/source/correlation_id +
import_batch_customer_scope_v1（batch/customer/project/decision）。

## 14. 多客户批次模型
UAT V7 客户批次含 2 客户 → 关联表 2 行（assoc 总计 4）；
r07 断言 granted 决定；不再压单列。

## 15. 各模板权限矩阵
TEMPLATE_SCOPE（DEC-OSV5-003）：客户域=master.manage；users/roles/
memberships=iam.manage；rate card=finance.manage；问卷=survey.manage；
知识库=master.manage。新 scope：finance.manage、data.import.audit；
新角色 auditor。负例：read_only 上传 users_v1 → 403（UAT V7 检查 4）。

## 16. 历史 20 条逐批归属结果
`scripts/scope_reconcile_imports_v5.py --apply`：17 bind（uat_fixture
_v3 ×8、uatv2 ×6、uatv3 ×3，逐批 mapping/回执客户 ↔ test_run 客户集
唯一匹配）+ 3 quarantine；20 行 scope_backfill_audit_v1；
before_hash=349447c7…/after_hash=43113b46…；operational=0。

## 17. quarantine 结果
3 条（imp-8e4f53455eaa / imp-9a8028ec9733 / imp-bf333d101db6）：
客户 uat-cust-a/b 与 uatv2…l16gw2 未登记任何 Test Run 客户集 →
fail-closed 隔离；仅管理员/auditor 在隔离区视图可见（浏览器对象级
对账 n=3）。

## 18. migration 与幂等
059_import_scope_lineage_v1：live 重启自动应用（PRAGMA 验证列+表）；
hermetic 每用例从 001 重放至 059（1479 用例）；纠偏脚本二次执行
skipped（幂等）。

## 19. Import API 修复
import_api.py 全端点：模板矩阵 + 逐客户整批 fail-closed（403）+
test_run fail-closed（409）+ 批次作用域授权 + 归档守卫 409；
view=operational|mine|history|quarantine；include_fixture 授权。

## 20. DTO 与脱敏修复
batch_dto 白名单 16 字段 + customer_scopes + 结构化摘要；
/preview 端点（创建者/data.import.audit；redacted=true；≤50 行）。

## 21. 列表作用域修复
默认 effective operational（data_scope=operational ∧ test_run='' ∧
visibility=current）∩ 调用者客户作用域；低权限不可见越权批次
（r10/r17；UAT V7 检查 9；浏览器 read_only rows=0）。

## 22. 错误报告权限修复
errors.csv 走 authorize_batch（跨客户/低权限 403；r14；负例 4/5）。

## 23. BI effective 修复
bi_effective_counts(import_batch_v1) 只计 effective operational；
data_products_all_effective_consistent 8 产品逐项对账（禁弱条件）；
UAT V7 检查 11（bi=0 == db operational=0）。

## 24. Test Center 修复
center_summary count_tables 增 import_batches（test_run 维度）；
UAT V7 检查 10（=3）；r20 绿。

## 25. archive 修复
ARCHIVE_HANDLERS['import_batch_v1']（data_scope=uat_fixture +
visibility=history + archived_at）；archive_namespace 由 handler
派生执行；UAT V7 检查 16/19（归档 3/3，重启不回退）；r21 幂等。

## 26. Registry 类型化结果
125 表类型化声明；_e() 不再默认 tenant_id；pk 支持 composite:/none；
archive_handler 与 ARCHIVE_HANDLERS 双向绑定。

## 27. Registry schema validator 结果
validate_registry(conn)：live=0 错误；r22 绿；负例 7（假字段）检出。

## 28. scanner 派生结果
_SCOPED_TABLES == leak_scan_tables()（scope_audit_v5.py 第 3 维）；
import 泄漏注入被 operational_leakage 捕获（r26）。

## 29. archiver 派生结果
_SCOPED_DOMAIN_TABLES == archivable_tables()（第 4 维）；缺 handler
即 Gate 阻断（负例 8）。

## 30. Gate 3.2 版本
EVALUATOR_VERSION="3.2.0" 单点；gate.json/API/审计器/负例/文档一致；
evaluator_version_consistent 检查常绿。

## 31. Gate 新增 checks
18 项（import_batch_* ×9、registry_* ×5、data_products_all_effective、
browser_import_current_history_separated、uat_import_lineage_complete、
evaluator_version_consistent）+ 新阻断态 BLOCKED_BY_IMPORT_SCOPE_LINEAGE；
总检查数 42。

## 32. Gate 负例
`.eval/scope_v5/gate_negative_tests.json`：12 项全阻断
（ALL_BLOCKED=True；scripts/osv5_gate_negative.py）。

## 33. UAT V7 namespace
uatv7_20260813053942_kh463m（首次 23/23；报告 .eval/scope_v5/uatv7/
report.json；validator problems=[]；首次失败运行与遗留 namespace 已
归档）。

## 34. UAT V7 import batch IDs
ids.import_batch_customer=imp-2b0fa9391e30 /
import_batch_project=imp-abd5c30ec408 /
import_batch_address=imp-3ba7292382da。

## 35. UAT V7 作用域一致性
检查 7/8：3 批次 uat_fixture+test_run 一致；关联 4 行；导入对象
（客户/项目/地址）全部 uat_fixture+NS。

## 36. UAT V7 跨客户负例
检查 4（read_only 全局模板 403）、12（customer_admin@custB 读 custA
批次 403）、13（read_only dry-run/commit 403）。

## 37. UAT V7 归档结果
检查 15–20：test_run archived；批次 history 3/3；对象运营残留 0；
服务重启；归档不回退；Gate 对账一致；证据 3 + 审计 3（检查 21）。

## 38. 浏览器角色矩阵
浏览器实驱动：owner/platform_admin、read_only、auditor；API 对象级
矩阵：customer_admin、project_manager（list 拒绝/空 + history 403）；
browser_evidence.json roles_* 字段。

## 39. 四视口截图
28 张 PNG（1440×17 + 1280/1024/768 各 3+）全部 sha256 入账
（.eval/scope_v5/browser/）；四视口 responsive_no_overflow 全真。

## 40. console/network
console_errors_unexplained=0（登录稳定后清空再逐页收集）；
无未解释 4xx/5xx（负例 403/409 为契约内）。

## 41. hermetic 测试
1479 passed, 1 skipped, 6 deselected（基线 1447 + 新增 32；
test_osv5_import_scope.py）；.eval/scope_v5/test_report.json。

## 42. host MPS
6 passed（pytest -m host_mps）。

## 43. typecheck/build
`npx tsc --noEmit` 零错误；`npm run build` 成功（vite）。

## 44. SQLite integrity
live integrity_check=ok；备份库 ok；Gate sqlite_integrity 检查消费。

## 45. migrations
001→059 顺序应用；059 live 已生效（PRAGMA 列+表验证）；hermetic
全量重放；migration_hash 绑定 Gate freshness。

## 46. 服务重启
UAT V7 检查 18（bin/abos restart 后 /api/v1/health 200）；
doctor：四端口在用、训练进程无；重启后归档状态不回退（检查 19）。

## 47. production 未切换声明
production 保持 prod_v4_best_r1（bin/abos status + UAT 报告
current_bundle 字段）；本轮未执行任何 production 切换。

## 48. 未启动训练声明
未启动 YOLO/SAM/Classifier/Qwen/QLoRA 等任何训练（abos status
训练进程=0；UAT training_processes=0）。

## 49. 未 merge/push/deploy 声明
本轮未 merge、未 push、未 deploy；全部为本地小步 commit。

## 50. P0/P1/P2 未关闭项
无：OSV5-001…012 全部 CLOSED（ISSUES.md；Gate no_open_p0_p1 消费）。

## 51. 最终机器 Gate
`.eval/scope_v5/gate.json`（scripts/osv5_gate_evaluate.py 在收尾
HEAD 上生成；42 检查；机器评估，非手写）。live
/api/v1/control/gate 实时 freshness 复评同口径。

## 52. 用户下一步唯一需要做的事
1) 用真实客户/地址/问卷数据执行真实数据 UAT（运营导入走 Import
Center 运营视图）；2) 人工走查：Import Center 四视图 → BI 数据产品
→ IAM → 系统状态 Gate 区块；3) 隔离区 3 条批次由管理员人工裁决
（保持隔离或删除需走审批矩阵 data.delete）；4) 是否 merge/push 由
用户决定（本轮未执行）。

## 53. 文档和证据绝对路径
- 治理目录：/Users/zhangweiqi/Documents/QY/项目/LLM-Image/docs/implementation/agentic-business-os-operational-scope-v5/
- before 证据：…/.eval/scope_v5/before/before_audit_v5.json
- gate：…/.eval/scope_v5/gate.json；负例：…/.eval/scope_v5/gate_negative_tests.json
- UAT V7：…/.eval/scope_v5/uatv7/report.json
- 浏览器：…/.eval/scope_v5/browser/browser_evidence.json + *.png
- 测试报告：…/.eval/scope_v5/test_report.json
- 备份：…/.platform/backups/platform_pre_scope_v5_20260813T124408.sqlite
