# 当前项目、平台定位与 UI 审计

审计日期：2026-08-11
现场分支：`feat/nextgen-training-cycle-v2`
现场 HEAD：`1a6f0aeebaaf48618bce4f34530bcec8fd496215`

## 一、结论

当前实现已经拥有 Graph、Capability、审核、训练、模型、Agent 和 Web 的大量基础代码，但“系统重新定位”主要停留在首页文字和色块上。它尚未形成真正的智能业务操作系统工作台：导航、模块、Agent、API、数据产品和页面仍存在多个平行事实源；识别页面的模型选择没有进入识别请求；主管 Agent 返回 UIIntent 却没有前端执行；大量样式类和变量已失效；当前四个本地服务也全部处于未运行状态。

因此本轮不能继续做表面美化。必须同时完成三件事：

1. 将产品壳层从 SKU 识别系统纠正为通用 Agentic Business OS；
2. 让 Module Manifest 成为导航、Agent、API、权限和 UI 槽位的统一事实源；
3. 以识别首域完成一条 Web/API/Agent 同源、服务可启动、任务可追踪的端到端纵向切片。

## 二、P0/P1 问题清单

### P0-01 产品定位仍被写死为 SKU 识别系统

证据：

- `web/src/App.tsx:71` 登录页显示 `qy · sku recognition`；
- `web/src/App.tsx:142-145` 页脚仍为 `qy·sku` 和“SKU 识别系统”；
- `src/platform/agents/supervisor.py` 的大模型 system prompt 仍把自己定义为 SKU 识别系统主管；
- `docs/README.md` 的主标题与大量当前入口仍围绕通用 SKU 图像识别。

影响：用户、Agent、路由和未来开发都会继续把识别当中心，问卷、地理、BI、财务等被错误做成识别页面的附属卡片。

### P0-02 一级模块存在三个并行注册表

证据：

- `web/src/App.tsx:21-30` 硬编码 `RAIL`；
- `src/platform/api/modules_api.py:6-40` 又硬编码一份 `MODULES`；
- `src/platform/registry.py` 已有正式 `ModuleManifest/CapabilityRegistry`，但前两者没有消费它；
- `src/platform/agents/kernel.py` 另有独立 AgentManifest 列表。

影响：模块名称、颜色、状态、Agent、API 和功能范围必然漂移；新增模块仍要同时改前端、API、Agent 和数据库代码，不符合积木式架构。

### P0-03 “三级菜单”只是重复链接，不是真实信息架构

证据：

- `web/src/pages/ModuleTabs.tsx:8` 用 `to` 作为 key；
- Recognition、Assets、Training、Label Studio 多个二级项指向完全相同的 URL；
- Recognition 的四个页签都为 `/recognition`，因此全部会同时被判定 active；
- `/biz/api`、`/biz/alert`、`/biz/cfg` 都渲染同一组件，而组件每次初始化为默认 `bi` tab。

影响：菜单看似存在，用户却无法通过 URL、刷新、前进后退或深链接稳定到达某个功能。

### P0-04 识别模型选择没有进入识别请求

证据：

- `web/src/pages/Recognition.tsx:71-110` 只在 `ProfilesPanel` 的局部 state 中保存 `sel`；
- `web/src/pages/Recognition.tsx:158` 调用 `recognizeFile(f)` 时没有传 `recognition_profile_id`；
- 批量和 URL 入口同样不传 profile；
- `src/platform/api/recognition_tasks.py` 的请求契约只有 `conf`，没有 profile；
- 当前页面文案还写着旧 bundle `prod_20260804_v4_r2`，与现行 `prod_20260805_v5_r1` 不一致。

影响：用户看到“模型已选择”，实际仍使用默认 legacy 路径，属于高风险的虚假控制。

### P0-05 主管 Agent 不是可操控全局的主管

证据：

- `src/platform/agents/supervisor.py` 包含大量硬编码、过期且互相矛盾的回答；
- 同一文件存在前置的通用 `M4` 分支，导致后面的 `qwen/M4` 分支结构上不可达；读取新项目 ID 时引用 `Path` 却没有导入，异常又被宽泛捕获为“待导入”；
- 返回的 `ui_intents` 和 `commands` 没有在 `web/src/pages/AgentChat.tsx` 中消费、渲染或执行；
- `SupervisorDrawer.tsx` 已成为孤儿组件，没有挂载；
- AgentChat 只展示文本，没有证据卡、命令预览、批准/拒绝、待办置顶、页面弹出或跨模块调度反馈。

影响：Agent 只能聊天，不能成为系统主控；更严重的是它可能根据过期常量给出错误状态。

### P0-06 当前本地系统不可直接使用

2026-08-11 现场探测：`8091/8092/8300/8400` 全部连接失败。当前没有一个从冷启动到健康、登录、识别、任务历史、证据查看的统一操作入口。

影响：即使页面代码存在，用户仍无法完成演示和下一阶段业务开发。

### P1-01 样式系统断裂导致透明/无样式组件

证据：

- 使用但未定义的 CSS variables：`--border`、`--card-coral`、`--card-orange`、`--card-yellow`、`--surface`；
- JSX 使用但 `styles.css` 未定义的主要类：`card-lg`、`grid`、`tile`、`upload`、`rec-grid`、`k`、`v`、`table`、`pill-healthy`、`pill-unavailable`、`tint-lavender`；
- 当前 `web/dist` 构建产物中上述主要类同样不存在，不是仅源码与旧构建不一致；
- `styles.css` 没有响应式 media query、`focus-visible`、跳转主内容或 reduced-motion 策略。

影响：用户看到透明模块、布局散落、状态颜色丢失；键盘、窄屏和无障碍体验不可接受。

### P1-02 第三方视觉语言被机械复制

当前跑马灯、超大标题、92px 彩虹色左轨、巨型 footer 和大面积高饱和拼贴被应用到后台操作系统。这些元素可用于品牌首页，但不适合高密度、长时间操作的管理工作台。

影响：信息密度和可读性下降，重要状态、操作和告警被装饰抢夺注意力。

### P1-03 “经营智能”使用训练模型指标冒充 BI 数据

`/api/v1/biz/m3bars` 直接读取 M3 模型训练报告；`BizIntel` 用它展示经营图表。模型实验指标不是经营数据产品。

影响：未来数据仓库、问卷和财务接入会继续被识别域污染，商业口径无法建立。

### P1-04 使用手册存在但不足以操作系统

`docs/USER-HANDBOOK.md` 只有简短页面说明，缺少：一键启动、角色与权限、任务操作、Agent 命令与审批、识别输入输出、失败恢复、证据链、API 示例、常见错误、升级与回滚。且其中项目 ID、production 和当前 Gate 被硬编码，容易过期。

## 三、已有可复用资产

- `src/platform/registry.py`：已有最小 Capability Registry，可扩展而不是重建第二套。
- `src/platform/kernel/*`：Graph/Loop/Checkpoint 基础。
- `src/platform/agents/*`：Agent Manifest、Blackboard、Memory、UIIntent 白名单基础。
- `src/platform/data/store.py`：本地事实与审计基础；本机阶段可继续使用，但领域服务与接口需保持未来 PostgreSQL 可迁移。
- `src/modules/fmcg/cascade/*`：识别首域 S0-S5 能力和适配器。
- `src/platform/api/recognition_tasks.py`、`src/recognize/service.py`：统一任务和 legacy production 兼容路径。
- `web/src/pages/*`：多数专业页面可逐步迁移到新壳层，不需要全部推倒。

## 四、不得采用的修复方式

- 只补几个 CSS 变量、改几句标题后宣称完成；
- 再找一套第三方 UI 全量照抄；
- 在前端继续硬编码菜单和模块状态；
- 为每个新业务模块建立独立数据库、登录、Agent、任务表或计费表；
- 用空卡片、模型指标或假数据冒充问卷、BI、地理和财务模块已完成；
- 让 Agent 直接写数据库或执行高风险命令；
- 为了让演示通过而绕过识别 Profile、审计、失败关闭或人工审批。
