# FINAL-REPORT — Operational Scope V5.1 Correction（operational-scope-v5-correction-v1）

> 单一事实源约定：本报告所有会随证据再生成而变化的数字（Gate checks
> 数、Registry 数、UAT namespace/批次 ID、测试计数、服务状态、bundle、
> 训练进程）一律引用 `.eval/scope_v5/machine_facts.json`（由
> `scripts/osv51_machine_facts.py` 机器生成），正文不再手工录入
> （OSV51-007 修复；V5 轮 42vs52/125vs126/namespace 漂移已附更正附录）。

## 1. HEAD / branch / worktree

- 基线：`feat/nextgen-training-cycle-v2` @ `8e31708d584459fb38fedefe21b070bede36db57`
- 收尾 HEAD：见 `machine_facts.json → git.head`（branch 同；tracked
  worktree clean；worktree list 含主仓与一个过期 docs worktree，后者
  全程未被读写为项目状态）。

## 2. commit 链（8e31708d 之后）

`git log --oneline 8e31708d..HEAD`：docs 基线 → W1-c ScrollManager
（红/绿）→ W1-a parallel 竞态（红×2/绿）→ W1-b kb flake（红/绿）→
W2-a quarantine 守卫（红×2/绿/归因检查）→ W2-b 密码零持久化（红/绿）→
W3 裁决状态机 → W4 血缘回填 → W5 证据新鲜度 → W6 machine_facts +
更正附录 → C-7 滚动 QA 断言 → CSS token 修复 → test_report 解析器修复
→ 本报告与 handbook。逐条 SHA 以 git 为准（机器可列）。

## 3. 完整阅读清单

GLOBAL_AGENT_ROUTING.md（~/.local/share/ai-workflow/routing/）；
CODEX-PROJECT-HANDBOOK.md；docs/USER-HANDBOOK.md；
docs/OPERATOR-RUNBOOK.md；V3/V4/V5 治理文档全套；.eval/scope_v5
gate/uatv7/test_report/browser/negative/before 全部证据；import、
scope、gate_evaluator、workflow、IAM、前端 Import Center 源码与测试；
8e31708d 之前全部 14 个 commits。**AGENTS.md 不存在于仓库**
（find maxdepth 3 为空）——记录为 OSV51-012（WONTFIX），以 handbook +
本轮文档为连续性入口。

## 4. before 状态

见 BEFORE-STATE.md：四服务 UP、production=prod_v4_best_r1、训练 0、
DB 备份 platform_pre_osv51_correction_20260813T162315.sqlite
（备份/原库 integrity ok）、静态 Gate READY（52 checks）与实时
STALE 并存、全量实测 1 failed（静态报告声称 0）。

## 5. P0/P1/P2 问题台账

见 ISSUES.md：OSV51-001..012 全部 CLOSED（各附证据），
OSV51-013 OPEN（低风险，下轮）：store.py set_business_run_status
残留 SELECT-then-UPDATE（当前无 workflow 终态写经此路径）。

## 6. 每个问题的复现/根因/修复/测试

00-LIVE-AUDIT.md（复现与活体证据）+ 01-ROOT-CAUSES-AND-CONTRACTS.md
（根因 RC-1..RC-9 与契约 C-1..C-8）+ EXECUTION-LOG（红→绿逐项记录）。

## 7. quarantine 逃逸修复证据

- 守卫：`ImportCenter._assert_batch_writable`（dry_run/commit 唯一强制
  点；quarantine/archived/history → `IMPORT_BATCH_WRITE_BLOCKED` 409）。
- 测试：test_osv51_quarantine_guard.py 52 项（14 模板参数化、并发、
  伪造参数、重启、直接 service、committed 重放现场向量）全绿。
- Gate：`quarantine_execution_escape` + `quarantine_no_operational_writes`
  （BLOCKED_BY_IMPORT_SECURITY）；负例 13/14/16 全部阻断。
- live API 复核：三个隔离批次 commit/dry-run 均 409+稳定码（见
  EXECUTION-LOG 验收链）。
- QA 重放对账：QA_REPLAY_DETECTED evidence + audit 已入账（幂等脚本
  scripts/osv51_record_qa_replay.py；历史行零回写）。

## 8. 首次密码零持久化证据

- 交付面收敛为 POST /commit 当次响应；commit_json/dry_run/error 落库
  前 redact_secrets 递归脱敏；batch_dto 出口递归扫描兜底；熵 32→128bit。
- 测试：test_osv51_password_zeropersist.py 10 项全绿（含
  upload→dry-run→commit→GET→restart→GET 契约：除当次响应外一切表面
  零明文且哈希仍可登录）。
- 存量清洗：scripts/osv51_scrub_secrets.py；live DB dry-run 0 命中
  （含递归键路径扫描）。
- Gate：`recursive_secret_scan`（负例 15 阻断）。

## 9. 隔离区裁决状态机与三个批次状态

- 迁移 060（quarantine_adjudication_v1 + 追加式证据表，触发器防删改）；
  API GET/POST `/api/v1/import/batches/{id}/adjudication`；CAS 版本号 +
  幂等；release_to_operational 双人审批（申请人≠审批人，409
  ADJUDICATION_SAME_ACTOR）→ 新批次 revision（不原地改）；
  revision 提交成功 → superseded_by_new_batch；UI 裁决面板。
- 15 项测试全绿（含并发双批准仅一赢、重启持久、审计追加）。
- 三个现存批次当前状态（live API 裁决）：
  imp-8e4f53455eaa / imp-9a8028ec9733 / imp-bf333d101db6 均为
  `retained_for_evidence`（继续隔离留证）。**最终处置（绑定 Test Run /
  软作废 / 转正式）属真实业务裁决，保留给用户从 UI 执行。**

## 10. 17 个历史批次客户血缘结果

- 确定性回填 17/17（8×uat_fixture_v3、6×uatv2、3×uatv3 → 各自 Test Run
  唯一客户，md_customer 交叉印证；零名称猜测）；关联行 12→29；
  0 pending；3 quarantine 批次合法未绑定（UI/API 显示“未绑定/待裁决”，
  不再显示“全局”）；逐批 scope_backfill_audit_v1 审计含 batch_id；
  报告 .eval/scope_v5/lineage_backfill_audit.json；Gate
  `import_batch_association_complete`。

## 11. workflow timeout 100 轮结果

- test_osv51_parallel_stress.py 100 轮（all/any/quorum、外部取消、
  branch/run timeout、重启恢复）零漂移；套件内复跑 3 次全绿；
  独立种子 OSV51_STRESS_SEED=777 通过；150 轮种子 77 通过
  （W1-a 报告）。test_branch_timeout 改有界 drain 确定性断言。

## 12. 全量测试结果

- hermetic 全量（marker not host_mps）：**0 failed，1581 passed，
  1 skipped，6 deselected**（scripts/osv51_test_report.py 机器生成，
  带 binding 块；见 machine_facts → tests.*）。
- host_mps 独立：6 passed。

## 13. Gate 证据绑定和负例

- 四份证据（uatv7/test/browser/negative）各携带 binding 块；Gate 逐项
  比对 recorded（证据文件）vs current（现场）——自比较已消灭；实时
  `/api/v1/control/gate` 复核 HEAD+tree+migration+worktree+DB
  fingerprint。
- 负例账本 21 项 ALL_BLOCKED（旧 12 + OSV51 新增 9：quarantine 逃逸
  族 3、secret 扫描 1、binding 缺失/三类 stale/自比较注入 5）。

## 14. 浏览器四视口结果

- scripts/osv5_browser_evidence.py 于 1440/1280/1024/768 采集：
  对象级断言 + 四视图截影像素互异（browser_import_views_distinct）+
  导航滚动连续性（nav_scroll_continuity：深滚 y≈2124 → 系统管理
  scrollY=0 且焦点 h1）。结果数值见 machine_facts → browser.*。

## 15. Registry / Gate / 报告一致性

- Registry 126 条、validate_registry problems=[]（live DB 复核）。
- Gate checks 总数与负例数见 machine_facts → gate/gate_negatives
  （机器读取，正文不录数字）。
- V5 轮历史报告漂移以更正附录修正（FINAL-REPORT/EXECUTION-LOG 附录
  V5.1）；osv5_gate_evaluate.py 不再覆写 uatv7/report.json。

## 16. SQLite / 服务 / 模型 / 训练进程

- SQLite integrity_check=ok（开工前备份与收尾复核）。
- 四服务（app/recognize/monitor/label_studio）健康（bin/abos restart
  后全 UP；见 machine_facts → services）。
- production bundle 见 machine_facts → production.bundle；训练进程 0。

## 17. production 未切换声明

本轮全程未执行 bundle publish/rollback/switch；CURRENT.json 保持
`prod_v4_best_r1`（previous=prod_20260805_v5_r1）；未启动任何训练；
未 merge/push/deploy；未删除任何历史证据、训练资产或用户未跟踪目录。

## 18. 未关闭问题

- OSV51-013（P2，低风险）：store.py set_business_run_status 残留
  SELECT-then-UPDATE；当前无 workflow 终态写经此路径，列入下轮。
- 三个隔离批次最终处置（保留/绑定/作废/转正式）等待用户业务裁决。
- uat-cust-a/uat-cust-b 的 is_test_fixture=0 与 data_scope=uat_fixture
  分类不一致（00-LIVE-AUDIT §2 记录）——属语义清理，不影响隔离安全。

## 19. 最终机器 Gate

以 `python3 scripts/osv5_gate_evaluate.py` 收尾再生成为准（.eval/
scope_v5/gate.json），实时 `GET /api/v1/control/gate` 必须同值
（freshness_verified_at 戳）。数值见 machine_facts → gate.*。

## 20. 用户真正需要执行的下一步

1. 真实数据 UAT：从 Import Center 运营视图导入真实客户/门店/问卷并
   贯穿 dry-run→提交→BI/工作台。
2. 隔离区业务裁决：Import Center → 隔离待处理 → 对三个批次执行
   绑定 Test Run / 软作废 / 申请转正式（双人审批）。
3. 人工走查四视图/BI/IAM/Gate 区块（USER-HANDBOOK 既有流程）。
4. 在真实 UAT 与人工验收通过之前，任何人（含 AI）不得宣称
   ACCEPTED / COMPLETE / PRODUCTION_READY。
