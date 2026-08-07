# NextGen 四模型数据与训练闭环 V2

> 版本：V2.0-frozen，2026-08-08  
> 基线：`feat/unified-workbench-training-readiness@ce6f614`  
> 性质：实施设计、执行计划与 Agent 任务书；不是生产发布授权。  
> 当前结论：**交付报告部分可信，但尚不具备直接启动四模型真实训练的完整控制链。**

## 阅读顺序

1. `01-CURRENT-STATE-AUDIT.md`：交付报告复核、Label Studio 标签核验、真实缺口。
2. `02-DATA-SAM-FOUR-MODEL-DESIGN.md`：三批照片、去重、严格过滤、点提示 SAM、四类数据集与模型训练方法。
3. `03-GRAPH-LOOP-EXECUTION-PLAN.md`：Graph+Loop 状态机、实施顺序、算力调度、Web/API。
4. `04-ACCEPTANCE-GATES-AND-REPORT.md`：门禁、完成状态、停止线、最终汇报格式。
5. `AGENT-EXECUTION-PROMPT.md`：可直接交给实施 Agent 的一次性任务书。

## 本轮目标

本轮不是再造第二套训练系统，而是在现有 Graph+Loop Foundation 上把以下链路真正闭合：

```text
三批原始照片与坐标
  -> 资产身份与全量去重
  -> 严格质量筛选与证据链
  -> 点提示 SAM 生成候选 mask
  -> 人工抽检/校准与伪标签分级
  -> 四类不可变 DatasetSnapshot
  -> 四条训练 Lane
  -> 统一评估与 Candidate Registry
  -> 识别 Profile 选择、API/Agent/Web 同口径
```

四条 Lane 为：

1. YOLO 商品检测器；
2. YOLO segmentation 学生模型，学习经过审核门的 SAM mask；
3. ResNet18/轻量 SKU 分类器；
4. `qwen3-vl:4b` 的 MLX QLoRA 闭集裁决器。

SAM 在本轮首先是冻结的数据教师与在线精修能力，**不允许用自己的伪 mask 反向宣称完成 SAM 微调**。只有真实人工 mask gold 达标后，才可另行开启 SAM mask-decoder/adapter 微调。

## 权威边界

- 总体架构仍以 `docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md` 为 L0。
- 识别级联以 `docs/superpowers/specs/2026-08-06-qwen3-vl-4b-graph-loop-cascade-design.md` 为专项契约。
- 本目录取代 `graph-loop-training-control-v1` 作为**下一轮实施入口**，但不删除旧目录。
- `.platform/platform.sqlite`、原始照片、历史模型与审核记录仍是不可覆盖事实/证据。
- 当前生产 `prod_20260805_v5_r1` 继续服务；训练完成只登记 candidate，production switch=false。
