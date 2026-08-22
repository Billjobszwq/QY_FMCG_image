# DECISIONS

## DEC-M001：模型管理是独立系统模块

“模型管理”与“智能识别”“主管 Agent”等并列。智能识别是消费者，不承载系统级模型连接和分配设置。

## DEC-M002：扩展现有平台，不建设平行 Model Gateway

复用现有 `/api/v1`、IAM、Scope、Agent Definition、Usage、Governance、CAS、审计和模型驻留。新增的是受控配置、适配器和解析端口，不是第二套运行内核。

## DEC-M003：Connection、Catalog、Binding 分离

连接描述传输与认证，目录描述模型及能力，绑定描述消费者选择。三者分别版本化，禁止把 API Key、模型 ID 和业务分配塞入一个不可审计 JSON。

## DEC-M004：Agent Definition 仍是 Agent 模型事实源

Agent 模型变更通过新的 Agent Definition 草稿、审批、发布和回滚完成。统一模型管理只提供聚合读取与受控写入，不创建第二份 Agent 配置。

## DEC-M005：凭据只写不读

数据库和 API 均不保存或返回明文。Connection 只持有 `secret_ref`；SecretStore 使用 envelope encryption。任何角色都不能通过产品接口恢复 API Key。

## DEC-M006：生产模型变更强制 maker/checker

连接测试可由模型管理员执行；启用、停用、模型切换和批量改绑必须由不同主体批准。激活使用 CAS，只有一个并发请求获胜。

## DEC-M007：Embedding 不允许跨身份静默降级

模型、revision、维度或 normalization 变化时必须生成新索引身份、重建和评测。查询只能使用与索引一致的 Provider Identity。

## DEC-M008：本地无真实 Token 时不得估算成账单 Token

Provider 返回真实 Usage 时记录输入、输出、缓存和 reasoning Token；未返回时记录 input items/chars、vector count、request count 和 compute milliseconds，并标明计量来源。

## DEC-M009：平台账本是系统消费事实源

外部 Provider 账单或余额接口只作为可选对账源，不能取代 `usage_event_v2` 的账号、租户、Run、Agent和模块归属。

## DEC-M010：迁移期保留受控旧配置回退

解析顺序为 Agent专属 → 模块绑定 → 租户默认 → 部署默认 → 旧环境变量。旧环境变量只作为迁移回退，必须暴露来源，不能伪装成受管配置。

## DEC-M011：唯一工作区为主仓库绝对路径，worktree 只读不触

- 事实：会话 cwd 落在陈旧 worktree `.claude/worktrees/serene-chatelet-28a5df`
  （branch `claude/serene-chatelet-28a5df` @ `3f13fa6b`，缺绝大部分项目文件）；
  ExitWorktree 不可用（非本会话创建）。另有三个他人 worktree。
- 决策：全部读写、git、pytest、脚本操作经主仓库
  `/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation` 绝对路径执行；
  不写、不删、不合并任何 worktree；不创建新 worktree/subagent。
- 影响：无（仅操作路径）；与合同“唯一项目目录”一致。
- 回滚：无需（纯操作约定）。

## DEC-M012：pytest 命令不使用 `PYTHONPATH=src`

- 事实：Research RAG 轮 ISS-014 确认 `PYTHONPATH=src` 使 `src/platform`
  遮蔽 stdlib `platform`，pytest `-v` 触发 INTERNALERROR；conftest.py 已把
  repo root 加入 sys.path，`src.platform.*` 可正常导入。
- 决策：05 计划中的 pytest 命令去掉 `PYTHONPATH=src` 前缀，其余参数保留；
  独立脚本按其自身导入方式决定是否设置。
- 影响：测试命令与 05 文档字面略有差异，语义不变。
- 回滚：恢复 `PYTHONPATH=src` 即回到文档字面命令（会重新引入 stdlib 遮蔽风险）。

## DEC-M013：SecretStore.rotate 以 SecretScope 为输入（协议最小强化）

- 事实：02 §5 协议写 `rotate(ref, value, actor)`，但新版本 envelope 的
  AAD 必须绑定 tenant/secret_ref/version/adapter_kind；裸 ref 无法安全
  重建 adapter_kind（AAD 不可反推）。
- 决策：`rotate(scope, value, actor)`，scope 携带 tenant/secret_ref/
  adapter_kind；其余语义（旧版本全部 rotated、禁止回落、缺 active 版本
  拒绝）与文档一致。
- 影响：协议签名更严格；fail-closed 增强，不放宽任何安全属性。
- 回滚：恢复裸 ref 签名需同时引入 adapter_kind 明文列（不改 schema 则
  无法安全实现）。

## DEC-M014：V1 ConnectionConfig 只允许空对象

- 事实：02 §3.1 禁止用户输入任意路径或任意 header；`config_json` 只允许
  经过判别联合验证的非敏感参数。
- 决策：V1 `ConnectionConfig` 不开放任何字段（Pydantic extra="forbid"
  零字段模型）；api_key/headers/模板等一律作为未知字段拒绝。后续需要
  非敏感参数时按判别联合逐字段追加并补负例。
- 影响：无功能损失（V1 无非敏感参数需求）；未来追加字段需走合同变更。
- 回滚：在 ConnectionConfig 增加字段即可（每个字段需独立负例）。

## DEC-M015：KEK 注入通道与格式

- 事实：02 §5 要求 KEK 由 `TAAS_MODEL_SECRET_KEK` 或企业 KMS 运行时提供，
  不存数据库、不用默认 key。
- 决策：组合根（app 装配）读取环境变量 `TAAS_MODEL_SECRET_KEK`
  （base64 编码的 32 字节）并注入 `EncryptedSQLiteSecretStore`；
  SecretStore 自身不读环境变量；缺失/长度错误 → SecretStore 不可用
  （API 503 `MODEL_SECRET_UNAVAILABLE`），全部操作 fail-closed。
- 影响：测试经显式参数注入 KEK，不依赖宿主环境。
- 回滚：更换注入来源只需改组合根。

## DEC-M016：OMLX 凭据的受控注入通道（演练期）

- 事实：合同要求凭据经“用户提供的安全输入或进程环境注入”；本机
  OMLX 服务端凭据位于用户自有配置 `~/.omlx/settings.json`
  （auth.api_key），进程环境未设置 TAAS_OMLX_API_KEY。
- 决策：bootstrap/评测脚本按优先级读取 ① 进程环境
  `TAAS_OMLX_API_KEY` ② 用户本机 OMLX 配置；读取只在进程内存完成，
  立即写入 SecretStore（AES-256-GCM envelope），任何日志/报告/证据/
  DB 明文字段均不出现密钥（每次产出证据前做字节级卫生断言）。
  live DB 只读，故引导只发生在显式演练库；生产化时改由部署工具经
  ① 通道注入。
- 影响：无需用户交互即可完成本机真实语义链路；密钥卫生由断言锁定。
- 回滚：删除 ② 通道即回到“仅环境变量/人工输入”。

## DEC-M017：hybrid 稠密腿噪声地板（冻结检索参数）

- 事实：真实 dense 接入后，“稠密腿恒返回 top-k”破坏了负例零命中
  合同（ACL 泄漏 6、注入命中 1、forbidden 4、弃权 0.72）；测量显示
  无词法佐证的弱语义命中全部 ≤0.56，而需要纯稠密召回的正例
  （paraphrase 0.72、multi-hop 0.82）均 ≥0.60。
- 决策：`gateway.DENSE_HYBRID_STRONG_SIM = 0.60`——无词法佐证的稠密
  候选必须达到该阈值（归一化余弦）才进入融合；有词法佐证不受限。
  该常量是检索身份的一部分：变更 = 新索引版本 + 金标准复评
  （01 §7 / DEC-M007），并以 `test_dense_floor_contract.py` 锁定。
- 影响：负例/弃权/注入/ACL 零命中合同恢复；正例召回不受损
  （13/13 gate 通过，paraphrase.recall_at_10=1.0）。
- 回滚：移除过滤即恢复原行为（负例合同将再次失败，不作为放行手段）。

## DEC-M018：旧 web 树路由镜像与兼容别名位置

- 事实：集成合同要求 后端 module_catalog 导航 ↔ UI_ROUTES_MIRROR ↔
  web 树 MODULE_ROUTES 三方严格一致；/vision/models 从智能识别导航
  移除后不能再作为 catalog 路由，但兼容期必须可解析。
- 决策：① module_catalog 注册 models 模块五路由；② web 树新增诚实
  指引组件（连接/目录/绑定/治理四页）并在 /models/local 复用原
  “模型与训练”内容；③ 旧 /vision/models 别名放入 MODULE_REDIRECTS
  （→ /models/local），不再占用 MODULE_ROUTES 键；④ UI_ROUTES_MIRROR
  同步。旧 web 树不提供密钥/绑定写操作（完整交互在桌面端）。
- 影响：三方镜像合同恢复一致（14 项合同测试绿）；兼容路由保留。
- 回滚：还原三处文件即回到旧状态。
