# Execution Decisions（append-only）

- `E-001`（T0）现场四服务实际在运行（8091/8092/8300/8400 聚合 healthy），00 文档"全部未运行"为 8-11 上午快照；以现场为准，T11 仍需提供冷启动脚本并实测 stop/start。
- `E-002`（T0）HEAD 已前进到 7c2eab62（含本轮文档 commit）；基线测试数将以本轮 fresh run 为准，不引用旧报告数字。
- `E-003`（T3 计划）ModuleManifestV2 在 `src/platform/registry.py` 内扩展（新增类，不破坏 ModuleManifest/CapabilityRegistry 现有消费者）；目录投影放 `src/platform/module_catalog.py`；modules_api 改为纯投影消费。
- `E-004`（T5 计划）识别域二级路由为 /vision/{recognize,tasks,annotation,datasets,models,evidence}；旧 /recognition、/cascade、/labelstudio 等保留 redirect。
- `E-005`（T6 计划）Supervisor 响应统一契约字段：message/evidence_refs/ui_intents/command_previews/tasks/delegations/memory_updates/requires_approval/trace_id；旧 answer/commands 字段保留一个版本作兼容。
- `E-006`（T7 计划）Profile 白名单来自 DB recognition_profile_def_v1；请求传未知/disabled profile → 400 fail-closed；任务行新增列经幂等 migration。
