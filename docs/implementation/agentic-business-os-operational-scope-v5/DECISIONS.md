# DECISIONS · Operational Scope V5

| ID | 决策 | 理由 |
|---|---|---|
| DEC-OSV5-001 | import_batch_v1 不加单列 customer_id；多客户走 import_batch_customer_scope_v1 关联表 | 指令 5.1：多客户批次不得压成单 customer_id；原 Registry 声明的 customer_id 列不存在（OSV5-006） |
| DEC-OSV5-002 | 新增 data_scope 值 quarantine（DATA_SCOPES 扩展），不可判定批次 fail-closed 落 quarantine | 指令 5.3：不得继续计入 operational；只允许管理员历史纠偏页可见 |
| DEC-OSV5-003 | 权限矩阵：客户域模板=master.manage+逐客户授权；users/roles/memberships=iam.manage；rate card=finance.manage；知识库=master.manage；问卷=survey.manage；新增 scope data.import.audit（原始预览/历史/隔离区） | 指令 5.2 全局模板规则；permission bundle 版本化注册 |
| DEC-OSV5-004 | 授权时机：upload 解析后即对全部涉及客户执行整批 fail-closed 校验（未过不落库） | 指令 5.2"任意一行无权访问整批拒绝，不得悄悄跳过" |
| DEC-OSV5-005 | DTO 白名单制：批次响应只回显式字段；原始 payload 一律走 /preview（创建者或 data.import.audit，脱敏+50 行上限） | 指令第六节详情契约 |
| DEC-OSV5-006 | Registry 类型化：tenant 策略改 not_applicable（本地单租户）；pk 允许 composite:/none 显式声明；validator 在启动测试与 Gate 运行 | 指令 7.2/7.3；消除 _e() 默认 tenant_id 幻影列 |
| DEC-OSV5-007 | scanner/archiver/Test Center/Gate 的表集合全部由 Registry 派生函数提供（leak_scan_tables/archivable_tables）；_SCOPED_TABLES/_SCOPED_DOMAIN_TABLES 保留为派生别名供兼容 | 指令 7.1 |
| DEC-OSV5-008 | 历史 20 条证据优先级：mapping_json 客户 ↔ test_run 客户集 > commit receipts 对象 > 时间窗；名称仅作辅助；不可唯一判定 → quarantine | 指令 5.3 |
| DEC-OSV5-009 | evaluator_version=3.2.0 一处定义，gate.json/API/Web/文档/validator/负例全引用 | 指令 P1-004 |
| DEC-OSV5-010 | Session 清理：登录时 purge_expired_sessions（有界、只删过期、审计、bill 锁定身份不因不在 iam_principal_v1 而误删） | 指令第十二节 |
| DEC-OSV5-011 | read_only（无任何 data/import scope）对 Import API 一律 403；列表不做"部分可见"折中 | 指令第六节"read_only 不得看到无权批次" |
