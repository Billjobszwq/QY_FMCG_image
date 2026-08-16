/**
 * 识别控制台：评测运行列表 + 拟物终端日志。
 *
 * —— 上半：运行列表表格（选中行高亮 bg-surface，默认选中第一条）
 * —— 下半：拟物终端面板（近黑底 button-bg 令牌），展示选中 run 的样本日志
 * —— 日志样本为本文件内置常量（不污染 sample.ts 契约），明显标注"样本"
 * —— 设计红线：无硬编码色值；accent 仅交互态；文本只穿 text 令牌；
 *    终端内文本只穿 button-text / background 两枚令牌（#fdfdf8 系走 background）
 */
import { useState } from "react";
import { RUNS, type RunStatus } from "@/data/sample";
import { StatusBadge } from "@/components/charts/primitives";
import { HedgehogLoader, PulseDots } from "@/components/ui/loader";
import { cn } from "@/lib/utils";

/* ============================================================================
   样本日志（内置常量，仅 UI 演示；时间戳与各 run 的 startedAt 对齐）
   ========================================================================== */

interface LogLine {
  /** 时间戳（HH:mm:ss） */
  ts: string;
  /** 管道环节标签，如 [cascade] */
  tag: string;
  /** 日志正文 */
  msg: string;
}

/** 按 run id 索引的样本日志（8–10 行/条） */
const RUN_LOGS: Record<string, LogLine[]> = {
  "run-0815-04": [
    { ts: "09:42:02", tag: "[loader]", msg: "加载评测集 dev_v1 完成：800 张照片，GT 框 9,214 个" },
    { ts: "09:42:03", tag: "[detector]", msg: "检测头载入 exp_e1_margin008_r1，阈值 conf=0.60 / margin=0.08" },
    { ts: "09:42:04", tag: "[cascade]", msg: "P-0815-03241 conf=0.71 margin=0.03 < 0.08 → review" },
    { ts: "09:42:04", tag: "[cascade]", msg: "P-0815-03242 conf=0.83 margin=0.21 → accepted sku=SKU-1001" },
    { ts: "09:42:05", tag: "[cascade]", msg: "P-0815-03243 conf=0.54 < 0.60 → unknown_review" },
    { ts: "09:42:06", tag: "[cascade]", msg: "P-0815-03244 conf=0.66 margin=0.12 → accepted sku=SKU-1003" },
    { ts: "09:42:07", tag: "[review]", msg: "margin=0.03 < 0.08 → review RV-20260815-014（统一 100 老坛酸菜）" },
    { ts: "09:42:08", tag: "[progress]", msg: "已处理 312/800 张（39.0%），预计剩余 23 分钟…" },
  ],
  "run-0815-03": [
    { ts: "07:10:02", tag: "[loader]", msg: "加载评测集 dev_v1 完成：800 张照片，GT 框 9,214 个" },
    { ts: "07:10:04", tag: "[detector]", msg: "检测头载入 prod_20260804_v4_r2，阈值 conf=0.60 / margin=0.05" },
    { ts: "07:10:06", tag: "[cascade]", msg: "conf=0.62 margin=0.11 → accepted sku=SKU-1007" },
    { ts: "07:18:41", tag: "[review]", msg: "margin=0.03 < 0.05 → review RV-20260815-014" },
    { ts: "07:25:12", tag: "[cascade]", msg: "conf=0.58 < 0.60 → unknown_review（疑似新品）" },
    { ts: "07:33:47", tag: "[llm]", msg: "裁决 P-0815-02187：候选红牛 250ml 罐成立 → accepted" },
    { ts: "07:47:55", tag: "[metric]", msg: "accepted precision=89.0%，端到端召回=20.3%，review 比例=10.5%" },
    { ts: "07:48:01", tag: "[gate]", msg: "与基线 E0 对比无回退（precision Δ=0.0pt）→ 门禁通过" },
  ],
  "run-0814-02": [
    { ts: "22:31:04", tag: "[loader]", msg: "加载评测集 dev_v1 完成：800 张照片，GT 框 9,214 个" },
    { ts: "22:31:06", tag: "[detector]", msg: "检测头载入 exp_e0_conf055_r1，阈值 conf=0.55 / margin=0.05" },
    { ts: "22:31:09", tag: "[cascade]", msg: "conf=0.57 margin=0.09 → accepted sku=SKU-1010" },
    { ts: "22:31:09", tag: "[cascade]", msg: "conf=0.56 margin=0.07 → accepted sku=SKU-1012（GT 不符，误报直收）" },
    { ts: "22:44:33", tag: "[review]", msg: "margin=0.02 < 0.05 → review RV-20260814-071" },
    { ts: "23:02:18", tag: "[metric]", msg: "accepted precision=84.1%，端到端召回=18.9%，review 比例=9.1%" },
    { ts: "23:12:07", tag: "[gate]", msg: "precision 84.1% < 基线 89.0% − 1.0pt 门槛 → gate-failed" },
    { ts: "23:12:07", tag: "[gate]", msg: "exact-set 0.0% < 门槛 → 不推全，bundle 已隔离" },
  ],
  "run-0813-01": [
    { ts: "08:05:03", tag: "[loader]", msg: "加载评测集 dev_v1 完成：800 张照片，GT 框 9,214 个" },
    { ts: "08:05:05", tag: "[detector]", msg: "检测头载入 prod_20260804_v4_r2，阈值 conf=0.60 / margin=0.05" },
    { ts: "08:05:08", tag: "[cascade]", msg: "conf=0.79 margin=0.24 → accepted sku=SKU-1002" },
    { ts: "08:11:26", tag: "[cascade]", msg: "conf=0.61 margin=0.04 < 0.05 → review" },
    { ts: "08:19:02", tag: "[llm]", msg: "裁决 P-0813-01052：库内无匹配 → unknown_review（疑似新品）" },
    { ts: "08:31:44", tag: "[cascade]", msg: "conf=0.49 < 0.60 → rejected（背景货架误检）" },
    { ts: "08:41:17", tag: "[metric]", msg: "accepted precision=89.2%，端到端召回=20.1%，review 比例=10.4%" },
    { ts: "08:42:03", tag: "[gate]", msg: "与基线 E0 对比无回退（precision Δ=+0.2pt）→ 门禁通过" },
  ],
  "run-0812-02": [
    { ts: "15:47:02", tag: "[loader]", msg: "加载评测集 canary_v1 完成：200 张照片，GT 框 2,305 个" },
    { ts: "15:47:03", tag: "[detector]", msg: "检测头载入 prod_20260804_v4_r2，阈值 conf=0.60 / margin=0.05" },
    { ts: "15:47:05", tag: "[cascade]", msg: "conf=0.74 margin=0.16 → accepted sku=SKU-1004" },
    { ts: "15:50:21", tag: "[review]", msg: "conf=0.58 < 0.60 → review RV-20260812-022" },
    { ts: "15:53:08", tag: "[cascade]", msg: "conf=0.88 margin=0.31 → accepted sku=SKU-1005" },
    { ts: "15:56:40", tag: "[metric]", msg: "accepted precision=90.4%，端到端召回=21.6%，review 比例=9.7%" },
    { ts: "15:58:12", tag: "[gate]", msg: "canary 子集无回退（precision Δ=+1.4pt）→ 门禁通过" },
    { ts: "15:58:12", tag: "[runner]", msg: "评测结束，耗时 12 分钟，产物已归档" },
  ],
};

/* ============================================================================
   状态徽章映射（finished=成功 / running=运行中+刺猬 / gate-failed=未过门）
   ========================================================================== */

function RunStatusBadge({ status }: { status: RunStatus }) {
  if (status === "running") {
    return (
      <StatusBadge tone="muted">
        <HedgehogLoader className="h-3.5 w-auto" />
        运行中
      </StatusBadge>
    );
  }
  if (status === "gate-failed") {
    return <StatusBadge tone="serious">未过门</StatusBadge>;
  }
  return <StatusBadge tone="good">成功</StatusBadge>;
}

/* ============================================================================
   页面主体（窗口壳由桌面接线提供，此处只输出内容）
   ========================================================================== */

export default function ConsoleContent() {
  // 选中行状态：默认选中第一条
  const [selectedId, setSelectedId] = useState(RUNS[0].id);
  const selected = RUNS.find((r) => r.id === selectedId) ?? RUNS[0];
  const logs = RUN_LOGS[selected.id] ?? [];

  return (
    <div className="flex h-full flex-col gap-4 p-5">
      {/* ---- 上半：运行列表 ---- */}
      <section className="flex-none" aria-label="运行列表">
        <header className="mb-2 flex items-baseline justify-between gap-3">
          <h3 className="font-display text-sm font-bold text-text-primary">运行列表</h3>
          <span className="text-xs text-text-secondary">
            共 {RUNS.length} 次运行 · 样本数据
          </span>
        </header>
        <div className="overflow-auto rounded-lg border border-border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-text-secondary">
                <th className="px-3 py-2 font-medium">运行编号</th>
                <th className="px-3 py-2 font-medium">识别包</th>
                <th className="px-3 py-2 text-right font-medium">照片</th>
                <th className="px-3 py-2 text-right font-medium">耗时（分）</th>
                <th className="px-3 py-2 font-medium">开始时间</th>
                <th className="px-3 py-2 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {RUNS.map((run) => {
                const active = run.id === selectedId;
                return (
                  <tr
                    key={run.id}
                    tabIndex={0}
                    aria-selected={active}
                    onClick={() => setSelectedId(run.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedId(run.id);
                      }
                    }}
                    className={cn(
                      "cursor-pointer border-b border-border transition-colors duration-200 ease-out last:border-b-0 outline-none",
                      "hover:bg-surface/60 focus-visible:bg-surface/60",
                      active && "bg-surface",
                    )}
                  >
                    <td className="px-3 py-2 font-mono text-xs text-text-primary">{run.id}</td>
                    <td className="px-3 py-2 font-mono text-xs text-text-secondary">{run.bundle}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-text-primary">
                      {run.n.toLocaleString("zh-CN")}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
                      {run.durationMin === null ? "—" : run.durationMin}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-text-secondary">{run.startedAt}</td>
                    <td className="px-3 py-2">
                      <RunStatusBadge status={run.status} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- 下半：终端面板（拟物终端，克制） ---- */}
      <section className="flex min-h-0 flex-1 flex-col" aria-label="运行日志">
        <header className="mb-2 flex items-baseline justify-between gap-3">
          <h3 className="font-display text-sm font-bold text-text-primary">运行日志</h3>
          <span className="font-mono text-xs text-text-secondary">{selected.id}</span>
        </header>
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-button-bg p-3 font-mono text-xs leading-relaxed">
          {/* 命令行：拟物终端起手式（$ 用 background 令牌提亮） */}
          <div>
            <span className="text-background">$</span>{" "}
            <span className="text-button-text/80">
              taas eval --bundle {selected.bundle} --set {selected.evalSet} --n {selected.n}
            </span>
          </div>
          {/* 样本日志：静态列表，index 作 key（同秒同标签行可并存） */}
          {logs.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              <span className="text-button-text/80">{line.ts}</span>{" "}
              <span className="text-background">{line.tag}</span>{" "}
              <span className="text-button-text/80">{line.msg}</span>
            </div>
          ))}
          {/* running 的 run：末尾脉冲点表示仍在产出 */}
          {selected.status === "running" && (
            <div className="mt-1 flex items-center gap-2 text-button-text/80">
              <PulseDots className="[&_span]:bg-background" />
              <span>评测进行中…</span>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
