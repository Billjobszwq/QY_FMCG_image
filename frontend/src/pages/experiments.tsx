/**
 * 实验与发布门（Experiments）
 *
 * 内容：
 * 1) 实验台账表格 —— 编号 / 被测 bundle / 评估集 / accepted precision /
 *    端到端召回 / 阶段裁决（StatusBadge）；E0 行锚定真实基线
 * 2) 错误账本（E0）—— HBars 横向条，无序类目 single 同色，条右直接标签
 * 3) 脚注 —— 发布门阈值与停止条件指引 + 样本数据声明
 *
 * 设计红线：
 * —— 颜色一律走 @theme 令牌；橙色仅 hover/focus/选中（本页无静态橙色）
 * —— 状态色只通过 StatusBadge（图标+文字）出现
 * —— 细边框、小圆角、高密度；文本只用 text-primary / text-secondary
 */
import { ChartCard, HBars, StatusBadge } from "@/components/charts/primitives";
import type { StatusTone } from "@/components/charts/primitives";
import { BASELINE, ERROR_LEDGER, EXPERIMENTS } from "@/data/sample";
import type { ExperimentStage } from "@/data/sample";

/* ============================================================================
   页面级映射（展示口径）
   ========================================================================== */

/** 阶段 → 裁决徽章：baseline=muted 基线 / iterate=warn 迭代 / promote=good 提升 */
const STAGE_META: Record<ExperimentStage, { tone: StatusTone; label: string }> = {
  baseline: { tone: "muted", label: "基线" },
  iterate: { tone: "warn", label: "迭代" },
  promote: { tone: "good", label: "提升" },
};

/**
 * 各实验评估集标注（样本数据未单列字段；与 E0 note 及 RUNS 记录口径一致：
 * 三个实验均在 dev_v1 上评测）
 */
const EVAL_SET: Record<string, string> = {
  E0: "dev_v1 · n=800",
  E1: "dev_v1 · n=800",
  E2: "dev_v1 · n=800",
};

/** 百分比展示（保留一位小数） */
function pct(v: number): string {
  return `${v.toFixed(1)}%`;
}

/* ============================================================================
   页面内容（不含窗口壳）
   ========================================================================== */

export default function ExperimentsContent() {
  return (
    <div className="space-y-4 p-5">
      {/* ---- 1) 实验台账 ---- */}
      <section>
        <header className="mb-2 flex items-baseline justify-between gap-3">
          <h2 className="font-display text-sm font-bold text-text-primary">实验台账</h2>
          <div className="text-xs text-text-secondary">
            E0 阈值 conf {BASELINE.confThreshold} / margin {BASELINE.marginThreshold}
          </div>
        </header>
        {/* 高密度表格：odd 行底色，细边框分隔 */}
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-text-secondary">
                <th className="px-3 py-2 font-medium">实验</th>
                <th className="px-3 py-2 font-medium">Bundle</th>
                <th className="px-3 py-2 font-medium">评估集</th>
                <th className="px-3 py-2 text-right font-medium">Accepted precision</th>
                <th className="px-3 py-2 text-right font-medium">端到端召回</th>
                <th className="px-3 py-2 font-medium">裁决</th>
                <th className="px-3 py-2 font-medium">备注</th>
              </tr>
            </thead>
            <tbody>
              {EXPERIMENTS.map((e) => {
                const meta = STAGE_META[e.stage];
                return (
                  <tr
                    key={e.id}
                    className="border-b border-border odd:bg-background/50 last:border-b-0"
                  >
                    {/* 编号 font-mono，实验名次级一行 */}
                    <td className="px-3 py-1.5 align-top">
                      <div className="font-mono text-xs font-semibold text-text-primary">{e.id}</div>
                      <div className="text-xs text-text-secondary">{e.name}</div>
                    </td>
                    <td className="px-3 py-1.5 align-top font-mono text-xs whitespace-nowrap text-text-secondary">
                      {e.bundle}
                    </td>
                    <td className="px-3 py-1.5 align-top text-xs whitespace-nowrap text-text-secondary">
                      {EVAL_SET[e.id] ?? "—"}
                    </td>
                    <td className="px-3 py-1.5 text-right align-top font-mono text-xs whitespace-nowrap text-text-primary">
                      {pct(e.precisionPct)}
                    </td>
                    <td className="px-3 py-1.5 text-right align-top font-mono text-xs whitespace-nowrap text-text-primary">
                      {pct(e.recallPct)}
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      <StatusBadge tone={meta.tone}>{meta.label}</StatusBadge>
                    </td>
                    <td className="px-3 py-1.5 align-top text-xs text-text-secondary">{e.note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- 2) 错误账本（E0）：横向条 + 条右直接标签 ---- */}
      <ChartCard
        title="错误账本（E0）"
        aside={`评测集 ${BASELINE.evalSet} · 按数量降序`}
      >
        {/* 7 类错误为无序类目：single 同色，数值大小只由条长表达 */}
        <HBars
          data={ERROR_LEDGER.map((entry) => ({ label: entry.label, value: entry.count }))}
          unit="条"
          mode="single"
        />
      </ChartCard>

      {/* ---- 3) 脚注：发布门指引 + 样本声明 ---- */}
      <p className="text-xs text-text-secondary">
        发布门阈值与停止条件见 docs/runbook.md · 样本数据
      </p>
    </div>
  );
}
