# EXECUTION LOG（追加式）

## 2026-08-12 · T0 现场复核与红测试

- 阅读完成：GLOBAL_AGENT_ROUTING、CODEX-HANDBOOK、USER-HANDBOOK、
  OPERATOR-RUNBOOK、MODULE-AGENT-DEV-GUIDE、V3 目录全部（04/05/ISSUES/
  STATUS/EXECUTION-LOG 重点）、survey/workflow/runtime/usage_api/
  rehearsal/shadow 实现、近 30 commits、DB schema/迁移/服务/CURRENT/制品 hash。
- 现场：HEAD e45af4eb 与预期一致；四服务 UP；prod_v4_best_r1；
  detector sha 84bf9936…；integrity ok；118 表；迁移 046。
- 断点核验：agent_call 12/12 无 run_id；shadow products 全 '?'；
  门头 min_count=0 绕过；parallel 串行扇出；rate limit 缺失。
- 红测试：tests/platform/test_uatcc_red_contracts.py 10 failed + 1 守卫绿。
