# AGENT-EXECUTION-PROMPT · Operational Scope V4

你是本项目的执行 Agent。按以下约束连续执行，不逐阶段询问用户。

## 目标
把 IAM/BI/Finance/Registry/Gate/浏览器六个运营面的 UAT 污染清零，
建立测试身份生命周期与 BI/Finance effective 口径，最终由机器 Gate
3.1 在稳定 HEAD 上给出可信结论。

## 循环
现场审计 → 稳定复现 → 根因 → 红测试 → 最小修复 → 模块验证 →
跨模块验证 → 浏览器验收 → Gate 负例 → 全量回归 → 再次审计。
发现新问题自动登记 ISSUES 并继续。

## 红线
- 不删历史（principal/membership/usage/evidence/audit 只追加式
  禁用/归档）；会话注销属运行时安全失效。
- 改库前 SQLite backup + 双向 integrity。
- 不碰未跟踪资产（.datasets_nextgen/.micro_gold_*/.sam_* 等）与
  其他 Agent 的 TaaS/架构文档。
- 禁 git add -A / reset --hard / merge / push / deploy / 切生产 /
  启训练；显式文件清单小步提交。
- 运行时禁止名称 LIKE 'uat%' 判定；一次性回填必须审计。
- 不得用 UI 隐藏代替后端隔离；不得用静态 gate.json 代替实时 Gate；
  不得为 READY 修改 Gate 结果；不得伪造证据。
- HEAD 若被外部推进：先审计新 commits 再继续。

## 验收
指令第十七节全部硬门槛 + 四视口 12 页浏览器语义验收 + UAT V6
（含归档后登录失败负例）+ ≥20 Gate 负例。全部通过前不得写
READY/ACCEPTED/COMPLETE/PRODUCTION_READY。

## 交付
治理目录 16 件持续更新；FINAL-REPORT 按 47 项顺序附证据；完成后
更新 docs/CODEX-PROJECT-HANDBOOK.md 方法论（物理表覆盖 ≠ 业务对象
隔离覆盖；global/reference 也需 UAT 生命周期；测试账号全生命周期；
BI effective 口径；Finance 默认上下文；浏览器覆盖与 Domain Pack
对齐；READY 绑定最终 HEAD/DB fingerprint/全应用语义证据；Agent
自动化保留人工备用入口；Domain Pack 必须声明 Test Run/归档/计费/
BI 影响）。
