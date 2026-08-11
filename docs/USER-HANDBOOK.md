# Agentic Business OS · 用户使用手册

> 版本：v2（2026-08-11，随 `agentic-business-os-workbench-v1` 重构发布）
> 本手册所有命令均已在本机实测。会变化的事实（production、Gate、任务数、项目 ID）
> 一律不在手册里写死，请在“系统与开发者 → 系统状态”页或 API 实时查看。

## 0. 这是什么 / 不是什么

- **是**：以 Graph+Loop 为智能执行内核、以模块化 Domain Pack 为业务能力、
  由主管 Agent 与领域 Agent 协作完成工作的**智能业务操作系统**。
- **不是**：单一 SKU 识别工具，也不是传统 SaaS。图像识别/标注/训练只是
  **第一个已实现的 Domain Pack（智能识别）**；数据仓库、问卷、地理外勤、
  BI、财务等模块按同一契约接入，当前标记为 planned（只有规格与插槽，无假数据）。

## 1. Quick Start（冷启动到识别一张照片）

前置条件：macOS（Apple Silicon）、miniconda Python、Node 已安装；仓库已克隆。

```bash
cd /Users/zhangweiqi/Documents/QY/项目/LLM-Image
./bin/abos doctor      # 环境体检：Python/DB/dist/端口/无训练进程
./bin/abos start       # 启动 8091/8092/8300/8400（幂等，已运行则跳过）
./bin/abos status      # 四服务应全部 UP
```

预期结果：`status` 输出四行 UP，production 显示当前 bundle（实时读取）。
失败处理：见第 9 节故障排查矩阵。

打开 http://127.0.0.1:8400 → 用 admin 登录（口令见 `.env` 的
`PLATFORM_ADMIN_PASSWORD`；首次部署请先设置该项再 `./bin/abos restart`）。

## 2. 登录与工作台布局

- 登录页品牌为 Agentic Business OS；身份由服务端 session 校验，
  不信任任何客户端 header。
- 布局：顶栏（品牌/环境/用户/实时 production）+ 左侧一级模块导航
  （来自 Module Registry 实时投影，带 live/planned 状态徽章）+
  中间页面（二级导航为真实 URL，可深链接/刷新/前进后退）+
  右侧主管工作台（任务板 + 主管 Agent，窄屏可收起，✦ 按钮展开）。

## 3. 三级导航

| 层级 | 含义 | 示例 |
|---|---|---|
| 一级 | 业务域（Module Manifest） | 智能识别、数据与资产、工作流与 Agent |
| 二级 | 独立路由功能页 | `/vision/recognize`、`/vision/tasks` |
| 三级 | 页内工具栏/操作 | 上传照片、URL 输入、批准命令、导出 |

旧链接（如 `/#/recognition`）自动重定向到新路由，历史收藏不会失效。

## 4. 首页（主管指挥中心）

今日待办 / 需要批准 / 正在运行 / 异常与告警 / 最近完成五张便签卡片、
运行概览与模块健康表，全部来自实时 API；没有数据时显示诚实空态。
“快速目标”输入框点击“交给主管”会打开右侧主管 Agent 对话。

## 5. 主管 Agent 与审批

- 右侧“主管 Agent”可问：识别任务、候选模型、训练进度、阻塞等，
  回答全部来自实时事实源；LLM 不可用时明确降级为规则回答，不伪装。
- Agent 可能返回：**证据引用**（evidence）、**UIIntent**（自动打开/定位
  页面，白名单受控）、**命令预览**（黄色卡片：参数/影响/成本/幂等键/回滚）。
- 高风险命令（识别批量、训练相关）必须点击“批准并执行”才会真实落库执行；
  “拒绝”同样记录审计。production 切换、删除、发布永远要求人工独立批准，
  Agent 无权自行执行。

## 6. 智能识别（首个 Domain Pack）

二级入口：即时识别 / 识别任务 / 标注与审核 / 数据集 / 模型与训练 / 质量与证据。

1. 在“即时识别”选择 **Recognition Profile**（只有 enabled 的可提交；
   禁用项显示原因，服务端二次校验 fail-closed）与服务档位。
2. 单图 / 批量（≤32 张）/ URL 三种输入全部写入**同一任务历史**，
   响应回显冻结的 profile、tier、source、trace_id。
3. “识别任务”页查看历史（含来源 web/api/agent、profile 列）。
4. 0 检出是诚实结果（近景/非货架/registry 外商品 fail-closed），不是故障。
5. 识别服务（8091）停止时：系统状态显示 degraded，识别请求诚实报错
   `unreachable`；`./bin/abos start` 恢复后可重试。

API 同源（Web/API/Agent 三入口同一服务层）：

```bash
# 登录拿 cookie 与 CSRF（admin 口令见 .env）
curl -c jar -X POST http://127.0.0.1:8400/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<口令>"}'
CSRF=<响应中的 csrf_token>

# 创建识别任务（Idempotency-Key 幂等；profile 必须是已注册 ID）
curl -b jar -X POST http://127.0.0.1:8400/api/v1/recognition/tasks/upload \
  -H "X-CSRF-Token: $CSRF" -H "Idempotency-Key: demo-1" \
  -F "files=@照片.jpg" -F "recognition_profile_id=production_legacy" \
  -F "service_tier=standard" -F "source=api"

# 查询任务 / Profile 列表 / 平台身份 / 实时 production
curl http://127.0.0.1:8400/api/v1/recognition/tasks
curl http://127.0.0.1:8400/api/v1/recognition/profiles
curl http://127.0.0.1:8400/api/v1/platform/identity
curl http://127.0.0.1:8400/api/v1/platform/production
# OpenAPI：http://127.0.0.1:8400/api/v1/docs
```

## 7. planned / degraded / disabled 是什么意思

- **planned**：只有规格和插槽，尚无真实后端；页面会说明目标、依赖、
  可接入 Data Product 与下一实施包；**不展示模拟数据**。
- **degraded**：模块已启用但依赖服务异常（如识别服务离线）。
- **disabled**：被策略或管理员关闭；历史数据仍只读可查。

## 8. 权限与高风险审批

- 身份=服务端 session；写操作需 CSRF token；角色由服务端决定。
- Agent 与用户都不能：直接切 production、删除数据、发布模型、
  终结财务账目——这些一律要求人工独立批准或拒绝。

## 9. 故障排查矩阵（Troubleshooting Matrix）

| 症状 | 可能原因 | 处理 |
|---|---|---|
| 页面打不开 | 8400 未启动 | `./bin/abos start`；看 `.platform/logs/app.log` |
| 登录 401 | 口令错误/未设置 | 在 `.env` 设置 `PLATFORM_ADMIN_PASSWORD` 后 `./bin/abos restart` |
| 识别失败 `unreachable` | 8091 掉线 | `./bin/abos status` → `./bin/abos start`；重试任务 |
| 识别 400 `profile_rejected` | 选了禁用/未注册 Profile | 按返回的 blockers 处理；改用 production_legacy |
| 页面显示旧内容 | 浏览器缓存 | HTML 已 no-store；强制刷新即可 |
| Agent 回答“LLM 暂不可用” | DEEPSEEK_API_KEY 未配置/网络受限 | 规则回答仍可用；配置 `.env` 后重启 app |
| 端口被占用 | 其他进程占端口 | `./bin/abos doctor` 查看；手动处理占用进程 |
| DB 报错 | 迁移未完成 | `./bin/abos doctor` 检查 integrity；迁移幂等可重跑 |

## 10. 更多文档

- 本机运维 Runbook：`docs/OPERATOR-RUNBOOK.md`
- 模块与 Agent 开发指南：`docs/MODULE-AGENT-DEV-GUIDE.md`
- 本轮实施记录：`docs/implementation/agentic-business-os-workbench-v1/execution/`
