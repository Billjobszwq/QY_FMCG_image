# ISSUES

## P0：已全部关闭

| ID | 问题 | 状态 | 关闭证据 |
|---|---|---|---|
| ABOSV3-P0-001 | `workflow.succeeded` 未被投影器识别 | CLOSED | 投影器识别 workflow.*/run.waiting_human/retried（a94cdc82）；红测试绿；事件重建后 done 不回退 |
| ABOSV3-P0-002 | 首页/WorkItemV2/Taskboard 平行真相 | CLOSED | /control/current-work 统一端点；/workitems 消费 WorkItemV2 主线；同一 work 状态一致（测试覆盖） |
| ABOSV3-P0-003 | 成功 run 残留旧 error | CLOSED | succeeded 清除 current error 与 blockers；旧错误留在事件（测试覆盖） |
| ABOSV3-P0-004 | BI 版本列表重复 latest | CLOSED | list 按 spec 去重取最新；versions 端点保留 v1/v2（测试+现场） |
| ABOSV3-P0-005 | 无可运营首页 | CLOSED | T2：dashboard 八段真实 API+UI；浏览器 5/5 |
| ABOSV3-P0-006 | Supervisor 关键词路由/Domain Agent ok=true | CLOSED | T4：真实工具循环+有界目录；invoke 落 run/event/usage；现场 8 意图 |
| ABOSV3-P0-007 | 工作流非可视化/wait/parallel/join 假实现 | CLOSED | T5：React Flow 画布；wait 持久化 timer（重启恢复）；join all/any/quorum；现场 E2E |

## P1：已全部关闭

| ID | 问题 | 状态 | 关闭证据 |
|---|---|---|---|
| ABOSV3-P1-001 | 主管工作台遮挡/视口 | CLOSED | 桌面 360–480 可调宽不覆盖；≤1024 底部可关闭；≤768 全屏（CSS+浏览器验证） |
| ABOSV3-P1-002 | 数据与资产定位不清 | CLOSED | Import Center + 数据产品/血缘端点 + 容量卡片（首页） |
| ABOSV3-P1-003 | 问卷只有样板 | CLOSED | T6 Builder：空白→发布→响应→计分 |
| ABOSV3-P1-004 | 外勤无地址导入/地理编码/地图 | CLOSED | T7：模板导入+Provider SPI+手工坐标+地图/路线 |
| ABOSV3-P1-005 | 识别模型状态难懂 | CLOSED | T8：v4_best_standard 默认可用+回滚；实验 profile 诚实 blocker |
| ABOSV3-P1-006 | BI 无可操作工作台 | CLOSED | T9：指标/公式/画布/下钻/看板 |
| ABOSV3-P1-007 | Agent 无配置工作台 | CLOSED | T4：Agent Center（Soul/Prompt/资产/记忆/健康/回滚） |
| ABOSV3-P1-008 | 账号权限不可自定义 | CLOSED | 自定义角色+权限模拟器+最后管理员保护（V2 既有） |
| ABOSV3-P1-009 | 主数据不完整 | CLOSED | 客户/项目/SKU CRUD+导入+停用+合并建议 |
| ABOSV3-P1-010 | 财务范围不符 | CLOSED | T10：客户 Usage 工作台（不伪装完整会计） |
| ABOSV3-P1-011 | 系统与开发者含义不清 | CLOSED | T11：帮助与文档（全员）+系统管理（仅管理员） |
| ABOSV3-P1-012 | 缺全局 CSV/XLSX 导入 | CLOSED | T3：14 模板统一 Import Center |
| ABOSV3-P1-013 | 人工路径被遮蔽 | CLOSED | 每域人工入口齐备（导入/问卷/坐标/识别/看板/Usage/批准） |
| ABOSV3-P1-014 | live 缺健康/E2E | CLOSED | integration ok=true（36 路由交叉验证）；agent health 有界探针 |
| ABOSV3-P1-015 | IAM 多客户只取第一个 | CLOSED | visible_customers 返回列表；跨客户 403（测试覆盖） |
| ABOSV3-P1-016 | rate limit 未实现 | CLOSED_PARTIAL→见残留 | 登录失败 401、CSRF 403、作用域 403 已强制；按主体限流列入 P2 残留（不影响 UAT，诚实记录） |

## P2：保留（不阻断 UAT）

- 便签跨浏览器恢复（已服务端持久化，跨设备同步待后续）；
- 事件 SSE/WebSocket 升级（当前轮询）；
- 地图离线缓存与国产坐标系转换；
- BI 导出 PDF/PPT、定时发送；
- Node-RED 可选执行 Adapter 实际接入；
- 完整 WCAG AA 审计与移动端原生适配；
- 按主体/租户的精细 rate limit（当前为认证+CSRF+作用域强制）。
