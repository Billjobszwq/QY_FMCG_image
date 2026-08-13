=== BEFORE-STATE 2026-08-13T08:26:35Z ===
--- git ---
8e31708d584459fb38fedefe21b070bede36db57
feat/nextgen-training-cycle-v2
untracked_count=32
--- worktrees ---
/Users/zhangweiqi/Documents/QY/项目/LLM-Image                                               8e31708d [feat/nextgen-training-cycle-v2]
/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.claude/worktrees/upbeat-archimedes-158fe1    3f559911 [claude/upbeat-archimedes-158fe1]
--- services ---
[abos] recognize: UP
[abos] monitor: UP
[abos] label_studio: UP
[abos] app: UP
[abos] recognize pid=16511（本脚本管理）
[abos] production: prod_v4_best_r1
[abos] 训练进程：无
[abos] 看门狗：未运行
--- training procs ---
zhangweiqi        5480   0.9  0.2 439081584 253920   ??  S    Mon10PM 260:18.49 omlx-server       
zhangweiqi       16515   0.0  0.2 412631232 260752   ??  S     1:42PM   0:02.74 /Users/zhangweiqi/miniconda3/bin/python -m src.training.monitor --port 8092
zhangweiqi        5478   0.0  0.2 435780992 210016   ??  S    Mon10PM  60:34.21 /Applications/oMLX.app/Contents/MacOS/oMLX
--- CURRENT bundle ---
app.pid
label_studio.pid
monitor.pid
recognize.pid
--- baseline_hashes ---
{
  "generated_at": "2026-08-04 00:25:46",
  "purpose": "修复前只读基线（ISSUE 修复路线阶段A-4）",
  "files": {
    ".models/sku_v1/weights/best.pt": {
      "sha256": "e01c53bb9745fcea40a155cb8a8fc4eb095cd427adac8ba2000c2dd45931586f",
      "size": 44684983
    },
    ".models/sku_v2/weights/best.pt": {
      "sha256": "b83b0f5e1fee2192c70322fbc642c66b9aba1ee6ea0fe153e08a92f8bc5eb4b0",
      "size": 177609391
    },
    ".models/sku_v3/weights/best.pt": {
      "sha256": "1b081f12f84186c3b948bf2c153d6135c3bda646941a4f24cbed8a1dcb44f08c",
      "size": 177611951
    },
    ".models/sku_v4/weights/best.pt": {
      "sha256": "84bf9936189377007898c942a3c9a87f605d52c2afe01b7db2a66269e5554975",
      "size": 133135871
    },
    ".models/sku_v5/weights/best.pt": {
      "sha256": "cee60a761a9e2841397ad3aa4c3ae1c9c86a21d598ba63cf8fcb38782268c821",
      "size": 133132095
    },
    ".models/sku_v6/weights/best.pt": {
      "sha256": "b662182d71a34057c3a665020110b1b223812a52d91d6fb77c56c1589590ce32",
      "size": 177616303
    },
    ".models/sku_v6_p1/weights/best.pt": {
      "sha256": "8c25bd8e1bbd2a2f5387a6139e618967e63998d1fa2231886167dccd086f90a4",
      "size": 177616943
    },
    ".models/classifier/best.pt": {
      "sha256": "8a7a7f4cb5c19238261e7002e5ae870fd0d6b4958145116c34993480bd06863f",
      "size": 45214603
    },
    ".warehouse/db.sqlite": {
      "sha256": "5304fa2a37389e0f1d26513684446ab14c493763e7a04626f5bde65a430c3708",
      "size": 90112
    },
--- sqlite batch counts ---
import_batch_v1
import_batch_customer_scope_v1
12
--- gate summary ---
READY_FOR_REAL_DATA_UAT 52 8e31708d584459fb38fedefe21b070bede36db57 2026-08-13T14:14:35+0800
