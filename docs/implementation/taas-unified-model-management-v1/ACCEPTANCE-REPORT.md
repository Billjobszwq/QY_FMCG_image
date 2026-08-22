# ACCEPTANCE-REPORT — TaaS 统一模型管理 V1

> 生成时间：2026-08-22（Asia/Shanghai）。仅含实测值；未测项明确标注。
> 状态判定见文末；`READY_FOR_UAT` ≠ 上线 ≠ 验收通过。

## 1. 基线与资产保护（G0）

| 项 | 实测 |
|---|---|
| 分支 / HEAD | `codex/taas-agent-operation-v1` / `5bbbf898…`（未变） |
| live DB SHA-256 | `2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109`（M1 与 M10 两次复核一致，全程只读） |
| live integrity / 迁移 | `ok` / 68（069–074 未应用于 live） |
| 新迁移 | 072/073/074 纯追加；001–071 未改写（合同测试锁定） |
| stage/commit/push | 无（未获授权） |
| Round 2 资产 | 未清理、未覆盖、未提交 |

## 2. Gate 实测表（G0–G9）

| Gate | 状态 | 关键实测证据 |
|---|---|---|
| G0 基线/资产/迁移预检 | PASS | 副本 068→074 幂等、integrity ok、live hash 不变（E-MM-1） |
| G1 合同/SecretStore/EndpointPolicy | PASS | 33 项：明文零落盘（字节级断言）、错误 KEK/AAD/revoke fail-closed、SSRF/DNS/redirect 负例（E-MM-2） |
| G2 Provider 协议 | PASS | 20 项 hermetic fake server：401/429+Retry-After/超时/非 JSON/部分响应/usage 缺失/维度错/密钥净化；OpenAI-compatible + Anthropic 原生（E-MM-3） |
| G3 Repository/Resolver/CAS | PASS | 解析优先级、跨租户零泄漏、并发单赢家、测试失败不动 active、空 scope canary 拒绝、404/409/422/503 语义（E-MM-4） |
| G4 IAM/模块投影 | PASS | 8 scope 注册；员工/管理员/审批人/审计/财务正负矩阵；maker≠checker 双层；平台角色 whoami 投影修复；导航零泄漏（E-MM-5） |
| G5 计量/预算/监控 | PASS | 9 类诚实单位、归属到行、预算硬 429/软 80% 告警、重复结算拒绝、finalize 失败→MODEL_METERING_INCOMPLETE+对账（E-MM-6） |
| G6 真实语义链路 | PASS | 见 §3（真实 OMLX，非 mock） |
| G7 消费者迁移 | PASS | Agent Definition 字节等价保留、审批发布+投影重建、回滚、受管调用落账本、legacy_env 可观测（E-MM-8） |
| G8 UI/浏览器 | PASS | build/lint/34 组件测试；真实浏览器 1024/1280/1440：图标/五页签/员工 403/密钥 DOM 无明文/无溢出（E-MM-9） |
| G9 全量回归/演练/对账 | 见 §5 | 全量 pytest、迁移恢复演练、reconcile、报告哈希 |

## 3. G6 真实语义链路（非 mock）

- Provider：本机 OMLX（`/health=healthy`，池 11 模型），鉴权经
  SecretStore 注入（DEC-M016 通道；密钥未出现在任何日志/证据/报告/
  DB 明文字段，产出前做字节级卫生断言）。
- 身份冻结：`managed:local-omlx@v1/Qwen3-Embedding-0.6B-8bit:dim=1024:norm=l2-normalized@v1`
  （维度与归一化为真实探测值）。
- 金标准（--suite v1-release --frozen --managed-omlx，12 类）：
  - **13/13 gate 通过**；`paraphrase.recall_at_10 = 1.0`（阈值 0.90）；
    exact_rule/temporal/conflict/abstention/citation precision/recall = 1.0；
    acl_leakage=0、injection_success=0、forbidden_source_hits=0；
    resume_success=1.0；lookup p95=29.9ms（<2s）。
  - 证据：`runtime/platform/evidence/model-management-rag-eval.json`
    sha256 `8aea2f285898f3238b7b66f43f426d678a0fa09f7ec0412d970aabc630cbf917`；
    内嵌 report_hash `f14b6234…`（覆盖全部判定产物、剔除易变时延），
    gold_hash `9b3467e3…`。
  - 引导证据：`model-management-omlx-bootstrap.json`
    sha256 `12e5ccc7ea7fb189bdf559da3aa9e7b2c08039756383764d77378d7ecfff98a4`
    （11 条 model.* 审计；演练库，未触 live）。
  - 诚实修复记录：首轮真实 dense 暴露 ACL 泄漏 6/注入 1/forbidden 4/
    弃权 0.72；根因“稠密腿恒返回 top-k”；以分布测量确定冻结下限
    `DENSE_HYBRID_STRONG_SIM=0.60`（DEC-M017，锁定测试），复评 13/13。
    未放宽任何阈值/负例。

## 4. 安全与授权实测

- Secret：AES-256-GCM envelope（每版本独立 DEK/nonce；AAD 绑定
  tenant/ref/version/adapter_kind）；KEK 仅运行时注入；无默认 key；
  全部 API/日志/repr/DB 无明文（含浏览器网络响应扫描）。
- EndpointPolicy：保存/测试/调用三处复用；SSRF 负例（userinfo/
  fragment/loopback-api/RFC1918/link-local/metadata/multicast/
  DNS rebinding/私网重定向）全部拒绝；pinned-IP 直连。
- IAM：8 个 models.* scope fail-closed；受限角色端点级正负矩阵；
  maker≠checker（decide 层 + verify 层双拒）；跨主体统一 404 零泄漏；
  CAS 并发单赢家（2 线程 1 胜 1 败）。
- 计量：无免费调用/重复计费（usage_id 派生 + INSERT OR IGNORE +
  状态机）；预算硬阈值调用前 429；软阈值治理告警。

## 5. 回归与演练实测

- 全量 Python：见 §7（执行于 M10，填入实测计数）。
- 前端：34 tests passed / lint clean / build 成功（M9 fresh）。
- 迁移/恢复演练（`/var/folders/…/taas-mm-m10-drill-1so3uaxx`，保留）：
  068 副本→074 幂等（integrity ok）；全新库→074；备份→破坏→恢复
  （integrity ok）；reconcile 升级副本 gate_ok=True；live reconcile
  gate_ok=True（新表 absent 如实处理）；live hash 复验不变。
- 词法基线诚实性：无受管 provider 时 `paraphrase` 仍如实 FAIL（0.0），
  其余 gate 通过（不伪造）。

## 6. 未决项 / 需用户行动

1. **人工真实 UAT**：`READY_FOR_UAT` 之后由用户执行业务验收并明确
   确认，方可进入 `ACCEPTED`。
2. **commit/push 授权**：本轮全部成果保留在工作树（未获授权不提交）。
3. **生产化凭据通道**：上线时经部署工具/`TAAS_MODEL_SECRET_KEK`
   （base64 32B）与 `TAAS_OMLX_API_KEY` 注入（DEC-M015/016）；
   live DB 的 069–074 应用由平台下次启动自动完成（需先备份）。
4. **Playwright 依赖**：`@playwright/test`+chromium 未安装（与 R2-09
   一致）；e2e 规格已落地，本轮以预览浏览器真实验收替代。
5. **ISS-MM-003**：VLM/OCR 独立 CLI 仍走受控 legacy env 通道
   （V1 无受管 VLM 连接，如实登记）。

## 7. 实测计数（M10）

- Python 全量（hermetic，`pytest -p no:cacheprovider -q`，424s）：
  **2242 passed, 6 skipped（既有 host_mps 宿主探针，非 hermetic）,
  6 deselected, 0 failed**。
  - 过程如实：首轮 2239 passed/3 failed（三方路由镜像合同，M9 新增
    模块暴露）→ 按 DEC-M018 修复 → 复跑 2241/1（结构文档页数）→
    更新结构文档 → 终跑全绿。无放宽断言。
  - tests/models 套件 135 项（迁移/合同/密钥/SSRF/Adapter/Resolver/
    API 安全/IAM 矩阵/计量预算/Agent 绑定/OMLX e2e/dense floor）。
- 前端：34 tests passed / eslint clean / `tsc -b && vite build` 成功；
  web 树 `tsc --noEmit` 通过。
- 浏览器：1024/1280/1440 三档真实浏览器实测通过（E-MM-9 明细：
  图标/五页签/员工 403/密钥 DOM 与网络零明文/无横向溢出/空态诚实）。
- 评测：13/13 gate（§3）；词法基线无 provider 时语义门如实 FAIL。

## 8. 结论

G0–G9 全部 fresh PASS；live hash 未变（2306a030…，M1/M7/M10 三次
复核一致）；全量回归绿。本地可安全完成的工作已全部完成；仅剩
§6 的人工 UAT 与授权类动作。

**总体状态：`READY_FOR_UAT`** —— 不是上线，也不是验收通过；
`ACCEPTED` 只在用户完成并明确确认真实人工 UAT 后写入。
