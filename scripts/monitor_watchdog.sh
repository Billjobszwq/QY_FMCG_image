#!/bin/bash
# 监控看门狗：常驻守护，确保监控服务(:8092)永不挂。
# 每 10 秒探活一次；若监控无响应则自动清理端口并重启。
# 启动方式：nohup bash scripts/monitor_watchdog.sh >/dev/null 2>&1 & disown
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1
PYTHON_BIN="${PYTHON_BIN:-python3}"
WDLOG=.models/monitor_watchdog.log

echo "[$(date '+%F %T')] watchdog 启动 (PID $$)" >> "$WDLOG"

while true; do
  # 探活：3 秒内能返回即视为存活
  if ! curl -s --max-time 3 -o /dev/null http://127.0.0.1:8092/; then
    echo "[$(date '+%F %T')] 监控无响应，重启..." >> "$WDLOG"
    lsof -ti:8092 | xargs kill -9 2>/dev/null
    sleep 1
    nohup "$PYTHON_BIN" -m src.training.monitor --port 8092 >> .models/monitor.log 2>&1 &
    echo "[$(date '+%F %T')] 已拉起监控 PID $!" >> "$WDLOG"
    sleep 8
  fi
  sleep 10
done
