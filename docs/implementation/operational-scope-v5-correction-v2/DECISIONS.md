# DECISIONS — operational-scope-v5-correction-v2

| # | 决策 | 理由 | 日期 |
|---|---|---|---|
| E-01 | 哈希/尺寸/内容不符 → BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT；缺失/路径越界/符号链接逃逸/JSON 不可解析 → STALE_GATE_EVIDENCE；两者并存时 STALE 优先 | 篡改是安全事件需专名阻断码；缺失/不可解析是新鲜度失效；与任务书第二节对齐 | 2026-08-14 |
| E-02 | 证据 manifest 存绝对/根相对路径 + SHA256 + 大小 + 生成时间；路径解析拒绝绝对路径越界、.. 穿越、符号链接逃逸 | 任务书第二节第 1/6 条；防证据被移花接木 | 2026-08-14 |
| E-03 | 分层校验：整文件哈希（manifest sha）、binding 块（source_commit/树/迁移）、result_hash（按 kind 重建载荷）三层分别报告 | 任务书第二节第 5 条；任一层独立可诊断 | 2026-08-14 |
| E-04 | gate_run_v1：append-only（禁 DELETE 触发器），状态迁移仅 CAS 条件 UPDATE（candidate→active→superseded）；激活需平台角色 + approved=true + expected_protocol 匹配 | 显式 Active Gate；旧 scope 重跑不得接管；人工批准留痕 activated_by/at | 2026-08-14 |
| E-05 | 实时端点 fail-closed：无 active run / gate 文件缺失 / 文件哈希与 registry 不符 → BLOCKED_BY_GATE_EVIDENCE | 任务书第三节第 6 条 | 2026-08-14 |
| E-06 | Import Center 视图以 URL ?view= 为单一事实源；页签点击 PUSH 新历史项（支持前进/后退）；未知 view REPLACE 规范化 operational | 任务书第四节；刷新/直链/导航一致 | 2026-08-14 |
| E-07 | 测试质量门禁：runner 强制 -W error::pytest.PytestReturnNotNoneWarning；测试函数禁止返回业务值，复用走模块级 helper | 任务书第五节；不得过滤/降级 | 2026-08-14 |
| E-08 | OSV51-013 以条件 UPDATE/CAS 结构性关闭（不选“文档声明不可达”路线）：所有调用方均在 workflow/控制面/agent 域内，但函数为公共 store 方法，未来调用不可限；竞态已实证（1500 轮 1301 覆盖） | 任务书第七节第 5 条：不能只写文档 | 2026-08-14 |
| E-09 | MapLibre 大包仅登记 P2（OSV52-007），本轮不重构 | 任务书第七节末段 | 2026-08-14 |
| E-10 | 治理文档在证据链之前提交（最终 HEAD 即文档 HEAD）；FINAL-REPORT 数字一律引用 machine_facts.json，避免“文档提交在 gate 之后 → HEAD 漂移 → STALE”的收尾悖论 | V5.1 收尾教训 | 2026-08-14 |
