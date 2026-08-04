"""SAM 辅助标注模块（隔离 Worker，不持有业务事实）。

契约与纯逻辑部分可在主环境测试；SAM 2.1 权重加载与推理在隔离 venv
中由 runtime/service 执行（手册§一.8）。"""
