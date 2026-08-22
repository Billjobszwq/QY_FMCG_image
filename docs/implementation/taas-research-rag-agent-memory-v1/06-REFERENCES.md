# 参考资料与设计映射

## 1. 本项目权威材料

### 一级方案

- `/Users/zhangweiqi/Documents/Obsidian Vault/TaaS/TaaS 原生智能体操作系统：统一架构设计规范.md`
  - 采用：Graph+Loop 唯一执行内核、治理/执行/认知三层、三权分立、L1/L2/L3、知识“应然”与记忆“实然”分离、Skill RAG 和人类最终裁决。

### 原始分案

- `/Users/zhangweiqi/Documents/Obsidian Vault/TaaS/企业知识库与 Skill RAG 体系提示词.md`
  - 采用：知识/Skill 生命周期、混合检索、权限/有效期过滤、Knowledge Agent、抽象 Skill 来源闭环。
- `/Users/zhangweiqi/Documents/Obsidian Vault/TaaS/Agents与记忆体系.md`
  - 采用：Agent 通用边界、记忆五阶段、输入缓冲、紧急协商、注入防御、员工保护、原始数据不可变。

### 当前项目证据

- `src/platform/agents/kernel.py`：12 个内置 Manifest 与 capability/UIIntent 边界。
- `src/platform/agents/runtime.py`：7 个 Runtime Definition、关键词规划、`kb.search`、资产和 L0-L4 记忆。
- `src/platform/agents/supervisor.py`：第二条 Supervisor 运行路径。
- `src/platform/agents/blackboard.py`：append-only Blackboard 与另一套 MemoryService。
- `src/platform/data/store.py`：迁移和 Agent/Memory/Knowledge/Workflow/Evidence 表。
- `src/platform/workflow.py`：当前最完整的通用 Workflow runtime。
- `tests/platform/test_abos_v3_agent_runtime.py`：当前 Agent/KB/Memory 能力的真实测试边界。
- `docs/architecture.md`、`docs/PROJECT-STRUCTURE.md`、`docs/LOCAL-ASSETS.md`：迁移项目的平台结构、源码边界和本地资产事实。
- `docs/implementation/agentic-business-os-operational-workbench-v3/02-WORKFLOW-AGENT-RUNTIME-DECISION.md`：现有 Workflow/Agent Runtime 决策背景。

## 2. Research RAG 一手资料

### 动态检索、纠正与多步研究

- [Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511)
  - 设计映射：不是每个问题固定检索；Research Critic 判断是否需要检索及证据是否相关。
- [Corrective Retrieval Augmented Generation](https://arxiv.org/abs/2401.15884)
  - 设计映射：检索质量低时触发 rewrite/expand/switch-source，而不是直接综合。
- [Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions](https://arxiv.org/abs/2212.10509)
  - 设计映射：多跳问题中，下一次检索取决于已得到的证据；Research Graph 允许 evidence-driven query iteration。
- [Search-o1: Agentic Search-Enhanced Large Reasoning Models](https://arxiv.org/abs/2501.05366)
  - 设计映射：把检索文档交给独立 Reader 深读后再注入 Claim Graph，减少整篇文档噪声。

### 全局和长文档检索

- [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://www.microsoft.com/en-us/research/publication/from-local-to-global-a-graph-rag-approach-to-query-focused-summarization/)
  - 设计映射：为 corpus-global 问题提供 entity/community 层索引；不把 GraphRAG 当所有 local query 的默认路径。
- [RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval](https://openreview.net/pdf?id=GN921JHCRw)
  - 设计映射：长文档在不同抽象层检索；hierarchical index 由评测决定是否启用。
- [Introducing DRIFT Search](https://www.microsoft.com/en-us/research/blog/introducing-drift-search-combining-global-and-local-search-methods-to-improve-quality-and-efficiency/)
  - 设计映射：Research Router 可在 local/global 之间动态选择和下钻，而不是固定单一 community level。

### 引证和评测

- [Enabling Large Language Models to Generate Text with Citations (ALCE)](https://aclanthology.org/2023.emnlp-main.398/)
  - 设计映射：报告拆成 Claim，并评估 citation correctness、completeness 和质量。
- [RAGAS: Automated Evaluation of Retrieval Augmented Generation](https://arxiv.org/abs/2309.15217)
  - 设计映射：检索和生成分层评估，reference-free 指标只作快速反馈，不替代金标准。
- [RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation](https://arxiv.org/abs/2408.08067)
  - 设计映射：指标要能判断失败来自 retrieval 还是 generation，不只给一个总分。
- [Deep Research Bench: A Comprehensive Benchmark for Deep Research Agents](https://arxiv.org/abs/2506.11763)
  - 设计映射：深研究除了报告质量，还要衡量有效引用数量、准确性和信息收集能力。

### 安全和深研究产品行为

- [OpenAI Deep Research System Card](https://openai.com/index/deep-research-system-card/)
  - 设计映射：多步浏览、文件/代码能力带来 prompt injection、隐私、幻觉和工具权限风险；外部内容必须是 untrusted data，研究和行动要分权。

## 3. 采用边界

这些论文提供设计模式和评测方法，不是直接复制的实现授权：

- 不假设某论文阈值适合企业数据；
- 不因为 GraphRAG/RAPTOR 在论文数据上有效就默认全量启用；
- 不把模型自反思当成安全边界；
- 不把 LLM-as-judge 当唯一发布 Gate；
- 不把开放 Web 的检索策略直接用于机密企业查询；
- 任何模型、索引、阈值和 source adapter 都必须在本项目固定语料和权限负例上重新评测。
