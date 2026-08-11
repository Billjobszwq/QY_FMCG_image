# Acceptance（逐节点验收记录）

| 节点 | 验收命令/方式 | 结果 | 证据 |
|---|---|---|---|
| T1 | pytest tests/contract/test_business_os_workbench_contracts.py | 先 12 失败 → 13 passed | git 5bb41228 |
| T3 | pytest tests/platform/test_module_manifest_v2.py | 16 passed | git 83036521 |
| T6 | pytest tests/platform/test_supervisor_runtime_v2.py | 10 passed | git 83036521 |
| T7 | pytest tests/platform/test_abos_recognition_profile_contract.py | 11 passed | git 83036521 |
| T8 | 实测 curl（单图/批量/URL/Agent/幂等/disabled/故障恢复） | 全部诚实返回 | evidence/T8-*.json/.txt |
| T11 | ./bin/abos stop→start→status→doctor | 冷启动四服务 UP | evidence/T11-cold-start.log |
| T12 | pytest hermetic / host_mps / npm typecheck+build / DB / 对账 | 全绿 | evidence/T12-*.txt |
| T13 | Browser agent 12 场景 | pass（视口 partial） | evidence/browser/*.png |
