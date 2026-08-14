# app-v0.3.0-taas.1

## 目的与范围

本版本冻结截至迁移时点的 TaaS by Agent Operation 干净开发基线，用于在独立目录继续本地开发，并在现有私有 Git 仓库中建立后续可持续更新的版本起点。

- 源基线：`046e7da0e97522a8898a4d45efd78a56f27168ca`
- 冻结对象：本标签所指向的最终提交
- 代码结构：20 个 Python 一级包、29 个 Web 页面、4 类测试套件
- 覆盖范围：系统源码、开发入口、结构说明、本地资产约定、发布树审计和相关测试

## 验证结果

- Python 默认测试套件：1815 passed、6 skipped、6 deselected、4 warnings，235.17 秒
- Web 依赖安装与生产构建：成功；Vite 转换 822 modules，构建耗时 2.74 秒
- 发布树审计：0 findings
- 训练资产符号链接：92,905 个；绝对、损坏、越界均为 0
- 兼容入口：13 个仓库内相对链接，全部健康

## 本地资产边界

本地静态资产仅记录聚合验证结果：476,063 个普通文件及符号链接，逻辑大小 36,280,701,593 bytes。验证清单摘要为 `c22fe5a83fd609e20be6b16acad971aafe7c99c39cbdfcf64c051f994724abda`。

训练数据、识别模型和用户数据均未被 Git 跟踪或上传；可变运行状态未迁移。实际资产仅保存在被忽略的 `training-data/`、`recognition-models/` 和 `runtime/` 本地区域。

## 模型指针

- current：`prod_v4_best_r1`
- previous：`prod_20260805_v5_r1`
- 两个 bundle 均完成 5/5 文件验证

本次冻结未切换模型。

## 操作声明

- 源仓库未改动
- 未合并 main
- 未创建 Pull Request
- 未部署
- 未上传训练数据、模型或用户数据

## 已知事项

- 项目的 `.[dev]` 尚未完整声明默认测试套件所需的全部依赖；本次在隔离验证环境中补齐依赖后完成测试。
- npm production audit 为 3 high、0 critical，均位于 React Router 依赖链；可升级到 6.30.4。本冻结快照未执行依赖升级。
