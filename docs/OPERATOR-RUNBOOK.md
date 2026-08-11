# Agentic Business OS · 本机运维 Runbook

> 面向开发/运营。所有命令 2026-08-11 在本机实测通过。
> 核心工具：`bin/abos`（幂等、只操作本项目精确进程、不启动训练、不谎报健康）。

## 1. 服务拓扑

| 端口 | 服务 | 职责 | 日志 |
|---|---|---|---|
| 8091 | `src.recognize.service` | 级联识别（production_legacy adapter 后端） | `.platform/logs/recognize.log` |
| 8092 | `src.training.monitor` | 训练/平台只读监控 | `.platform/logs/monitor.log` |
| 8300 | Label Studio（SQLite 模式） | 标注/审核；数据目录 `.label-studio/` | `.platform/logs/label_studio.log` |
| 8400 | `src.composition.serve` | 统一 API + Web Shell + Agent Runtime | `.platform/logs/app.log` |
| 8301 | `src.ls_ml_backend.yolo_backend`（可选） | LS ML backend proposal | — |

事实源：`.platform/platform.sqlite`（WAL；迁移幂等、篡改校验）。
production：`.models/bundles/CURRENT.json`（只读核验，本轮不切换）。

## 2. 日常操作

```bash
./bin/abos status    # 四服务健康 + production + 训练进程 + 看门狗
./bin/abos doctor    # Python/DB integrity/dist/端口/LLM key/训练进程
./bin/abos start     # 幂等启动（已在运行则跳过），等待健康探测
./bin/abos stop      # 先停 monitor 看门狗，再按 PID/精确命令行停四服务
./bin/abos restart   # stop + start
```

注意：
- `stop` 只终止本项目四服务的精确进程（PID 文件或精确命令行匹配），
  不使用宽泛 kill；历史遗留的 `scripts/monitor_watchdog.sh` 守护会先被停止，
  否则 8092 会被自动拉起。
- Label Studio 冷启动较慢（最多等 90s）；启动失败时 `start` 会明确报
  “启动失败（见日志）”，不会谎报成功。
- 8400 重启会自动执行幂等迁移（含本轮 `030_recognition_task_profile_contract`）。

## 3. 冷启动演示流程

1. `./bin/abos stop`（全部 DOWN，`status` 返回非 0）。
2. `./bin/abos start` → 四服务 UP。
3. 浏览器打开 http://127.0.0.1:8400 → admin 登录（`.env`
   `PLATFORM_ADMIN_PASSWORD`）。
4. 智能识别 → 即时识别 → 选 production_legacy → 上传货架照片 →
   叠框结果或诚实 0 检出。
5. 识别任务页可见同一任务（profile/source/trace 回显）。

## 4. 数据与模型核验（只读）

```bash
sqlite3 .platform/platform.sqlite "PRAGMA integrity_check;"   # 期望 ok
sqlite3 .platform/platform.sqlite "SELECT name FROM schema_migrations ORDER BY id DESC LIMIT 3;"
cat .models/bundles/CURRENT.json        # 当前 production（不修改）
./bin/abos status | grep 训练           # 必须“无”
```

备份：`.platform/backups/`（历史）；建议定期 `sqlite3 .platform/platform.sqlite ".backup ..."`（先停写或接受 WAL 一致性）。

## 5. 故障排查

| 故障 | 排查 |
|---|---|
| `start` 后某服务 DOWN | 看对应 `.platform/logs/*.log`；`doctor` 查端口占用 |
| 8400 起不来（迁移错） | 迁移带 sha256 校验：不要手改历史迁移；新增需求加新编号迁移 |
| 8091 健康但识别 502/超时 | 8091 进程在但模型未加载：查 recognize.log；必要时 `./bin/abos restart` |
| LS 8300 无响应 | LS 冷启动慢；等 90s；仍失败看 label_studio.log（数据目录权限） |
| Agent 无智能回答 | DEEPSEEK_API_KEY 未配置/网络受限 → 自动规则降级（属诚实行为） |
| 页面旧样式 | 重新 `cd web && npm run build`，确认 `web/dist` 更新 |
| 端口冲突 | `lsof -iTCP:<port> -sTCP:LISTEN` 定位；只处理明确进程 |

## 6. 安全停止与边界

- 禁止：宽泛 `pkill python`、删除 `.platform/`、切换 CURRENT.json、启动训练。
- 训练进程若真实存在（`status` 会警告），本脚本不启停它，需人工按训练门禁处理。
- 本轮红线：不重新训练、不切 production、不删除历史资产、不 merge/push/deploy。
