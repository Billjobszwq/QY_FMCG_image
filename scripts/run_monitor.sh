#!/bin/bash
# 监控服务包装脚本（供 launchd 守护调用）
# launchd 会在进程退出时自动重启（KeepAlive），实现"永不挂"。
cd "/Users/zhangweiqi/Documents/QY/项目/LLM-Image" || exit 1
exec /Users/zhangweiqi/miniconda3/bin/python -m src.training.monitor --port 8092
