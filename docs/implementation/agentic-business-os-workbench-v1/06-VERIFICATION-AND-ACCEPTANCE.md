# 验证与验收规范

## 一、自动化测试

### 后端

```bash
PYTHONDONTWRITEBYTECODE=1 XONSH_HISTORY_BACKEND=dummy \
python3 -m pytest \
-q -p no:cacheprovider -m "not host_mps"
```

Host MPS 单独执行并单独报告，不把 deselected 当 pass：

```bash
PYTHONDONTWRITEBYTECODE=1 XONSH_HISTORY_BACKEND=dummy \
python3 -m pytest \
-q -p no:cacheprovider -m host_mps
```

新增测试至少覆盖：

- Module Manifest schema、重复、依赖、route、agent、permission、health；
- 前端导航投影与 Registry 一致；
- UIIntent 白名单和实际执行；
- command preview/approve/reject/audit；
- Profile 进入所有识别入口；
- Web/API/Agent 同一任务和幂等；
- disabled profile、服务中断、0 检出、URL 错误和 overloading；
- reference non-vision module 证明内核通用；
- 旧 route 兼容和 deprecated；
- 文档和状态端点不含过期硬编码。

### 前端

```bash
cd web
npm run typecheck
npm run build
```

应补充前端单元/集成测试，覆盖导航、Agent response rendering、Profile 请求、状态组件、权限和 error boundary。构建必须零 TypeScript error；console warning 进入缺陷清单。

## 二、静态 UI 完整性

- CSS variable 使用集合减定义集合为空；
- 关键 class/component 不存在孤儿引用；
- 不存在多个二级菜单同 route；
- 不存在 `App.tsx`/API/Agent 三份模块常量；
- 不存在 `sku recognition`、`SKU 识别系统` 的平台级文案；
- 不存在硬编码项目 ID、Gate、完成数或 production 作为当前事实；
- 所有图片有 alt，按钮有 accessible name，表单有 label；
- focus-visible、reduced-motion、对比度和响应式规则有测试。

## 三、服务与数据验证

- SQLite `PRAGMA integrity_check=ok`；
- Migration 全部成功且可在副本重跑；
- 8091、8092、8300、8400 健康；
- 8400 聚合健康与各服务一致；
- production bundle 从运行态查询且未切换；
- 没有 YOLO/SAM/Classifier/Qwen/QLoRA 训练进程；
- Module Registry/Agent Registry/API/Web 四方数量和 ID 一致；
- 识别任务、Graph Run、审计、证据和用量可按 trace_id 串联。

## 四、浏览器验收矩阵

| 场景 | 必验内容 |
|---|---|
| 登录 | 品牌定位正确、错误可读、键盘可用 |
| 一级导航 | 模块来自 Registry、色系清晰但不过度、active 唯一 |
| 二/三级导航 | 深链接、刷新、返回、权限、planned/degraded |
| 首页 | 待办/审批/运行/异常/完成/笔记均为真实数据或诚实空态 |
| 主管 Agent | 回答、证据、UIIntent、命令预览、批准/拒绝、委派回执 |
| 识别 | Profile 选择、上传、批量、URL、历史、叠框、证据、导出 |
| 故障 | 8091 停止、URL 失败、超限、0 检出、权限不足 |
| 系统 | 模块、Agent、API、服务、版本、日志与手册入口 |

每个场景在 1440、1280、1024、768 至少检查一次；无内容遮挡、不可达操作或水平滚动。保存有日期、route、viewport、commit 的截图清单。

## 五、识别真实验收

使用至少：

- 3 张正常货架/冰柜图；
- 1 张反光或模糊图；
- 1 张近景/非货架图；
- 1 个 URL；
- 1 个 batch；
- 1 次 Agent 发起。

验收不是要求每张识别正确，而是要求系统诚实：正常返回有证据，不能识别就拒识/转人工，服务失败有恢复路径。不得使用测试 mock 或预写静态 JSON 代替真实 8091 调用。

## 六、性能门

- App Shell 首次可交互、路由切换和大表格加载记录实测；
- 主管 Agent 有发送、等待、超时和取消反馈；
- 识别任务异步时页面可离开并恢复；
- 轮询退到后台时降频；
- 1000 行表格使用分页或虚拟化；
- 大图预览不把原图同步塞进全局 state；
- 报告 p50/p95，不写“感觉很快”。

## 七、安全与审计门

- Web 身份不能由 `X-Actor` 客户端自证；
- URL 下载防 SSRF、重定向和超大响应；
- Agent tools 按 capability scope；
- 高风险命令两阶段批准；
- API 有 idempotency、rate limit、input size；
- evidence 不暴露密钥或跨租户路径；
- production switch 继续拒绝，除非用户另行授权。

## 八、最终通过条件

以下任一为假都不得交付“完成”：

1. 用户可以按手册从冷启动进入系统；
2. 新工作台没有透明/无样式模块；
3. 三级菜单均为真实路由/操作；
4. Supervisor 能真实弹出/定位内容并管理命令；
5. 识别 Web/API/Agent 端到端同源；
6. Module/Agent/API/Web 单一事实源；
7. 全量测试、构建、DB、服务、浏览器 QA 有新鲜证据；
8. production 未切换且未启动训练；
9. 系统手册和扩展指南可操作；
10. 最终报告如实列出未完成项和下一步。
