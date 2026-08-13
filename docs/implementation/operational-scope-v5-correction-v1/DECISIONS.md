# DECISIONS — operational-scope-v5-correction-v1

| # | 决策 | 理由 | 时间 |
|---|---|---|---|
| D-01 | 全部工作直接在主仓 feat/nextgen-training-cycle-v2 分支进行；.claude/worktrees/upbeat-archimedes-158fe1 为过期 worktree，禁止读取 | 任务基线指定该分支 HEAD；worktree 落后且 git 不允许同分支双 worktree | 2026-08-13 |
| D-02 | 不新建 AGENTS.md；以 CODEX-PROJECT-HANDBOOK.md + 本轮文档为连续性入口 | 仓库历史上不存在 AGENTS.md，临时新建会造成两套权威入口 | 2026-08-13 |
| D-03 | quarantine 批次 dry-run 一并禁止（409），只读分析产物写入独立追加式裁决证据表 | dry-run 会覆写原批次 dry_run_json 证据，违反“不得修改原始导入证据” | 2026-08-13 |
| D-04 | release_to_operational 采用“新批次 revision + supersedes”，不原地改 quarantine 行 | 保留隔离历史不可篡改；双人在新旧两批上分别留痕 | 2026-08-13 |
| D-05 | 17 批血缘回填采用确定性 test_run_id→registry 单客户绑定；3 个 quarantine 批次保持未绑定/待裁决 | 审计要求不得名称模糊猜测；quarantine 候选 Test Run 数=0 | 2026-08-13 |
| D-06 | 历史漂移报告以“更正附录”方式修正，不改写历史文件内容 | 证据不可回写；保持审计链完整 | 2026-08-13 |
| D-07 | imp-bf333d101db6 重放事件只追加 QA_REPLAY_DETECTED 证据（supersedes 语义指向重放产生的 evid-dca91a51476a），不回写 commit_json 原始值 | 任务明令不得静默回写历史；对账靠事件+审计+备份 | 2026-08-13 |
| D-08 | 并行引擎压力测试定 100 轮为门槛（可配置环境变量提高），纳入 hermetic 套件但控制单轮耗时 | 任务要求至少 100 轮无漂移；同时避免套件时长失控 | 2026-08-13 |
| D-09 | test_report.json 改为脚本生成（带绑定块），手写 JSON 废止 | C-6/C-8 单一事实源要求 | 2026-08-13 |
| D-10 | 本轮证据目录沿用 .eval/scope_v5/（不新建 scope_v51 目录），gate.json 由修复后的评估器覆写 | 实时端点按 .eval/*/gate.json mtime 选取；新建目录会造成双 gate 并存 | 2026-08-13 |
| D-11 | 证据级 DB fingerprint 比对豁免 scope_graph 一项 | 证据运行自身的 fixture 生命周期（uat_fixture/archived 行累积）合法移动 scope_graph 聚合，多份证据先后生成必然漂移，任何排序都无法全绿；运营完整性由 Gate 全量评估的直接重算检查族（leakage/residue/lineage/quarantine 归因）+ gate.json 自身完整 fingerprint 的实时复评双重保证。event_watermark/outbox_pending/projection_hash/counts 仍逐项比对 | 2026-08-13 |
