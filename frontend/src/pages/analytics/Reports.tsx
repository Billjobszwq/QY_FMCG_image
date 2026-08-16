/**
 * 分析与 BI · 分析报告（P7）。
 *
 * 数据源（同源 /api/v1/*，禁假数据）：
 * —— /api/v1/monitor/overview：训练概览（YOLO 各轮 mAP50/Recall + 分类器 val_acc + 服务探活）；
 * —— /api/v1/home/dashboard：总控面板（runs 状态分布 / 项目进度 / 近期活动 / 容量）。
 *
 * 说明：charts 原语尚无折线组件，训练曲线在本文件内以手写 SVG 实现
 * （令牌色 / border 网格 / text-secondary 刻度 / hover 命中带，与原语同构）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  fetchHomeDashboard,
  fetchMonitorOverview,
} from "@/lib/api";
import type { HomeDashboard } from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import { ChartCard, StatTile, VBars } from "@/components/charts/primitives";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { HedgehogLoader } from "@/components/ui/loader";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   monitor/overview 载荷类型（legacy.training.monitor 8092 只读代理契约）
   ========================================================================== */

interface EpochPoint {
  epoch: number;
  map50: number;
  map50_95: number;
  precision: number;
  recall: number;
  box_loss: number;
  cls_loss: number;
  val_box: number;
  val_cls: number;
}

interface YoloRun {
  run: string;
  epochs: EpochPoint[];
  best: EpochPoint;
  n_epochs: number;
  meta: Record<string, unknown>;
}

interface ClassifierEpoch {
  epoch: number;
  val_acc: number;
  train_acc?: number;
  val_loss?: number;
}

interface ClassifierOverview {
  running: boolean;
  epochs: ClassifierEpoch[];
  best_acc: number;
  best_epoch: number;
  backbone: string | null;
  history_best_acc?: number;
  n_classes?: number;
}

interface MonitorOverview {
  yolo_runs: YoloRun[];
  best_yolo: { run: string; map50: number; epoch: number } | null;
  classifier: ClassifierOverview | null;
  services: Record<string, "up" | "down">;
  processes: Record<string, boolean>;
  timestamp: number;
}

/* ============================================================================
   登录窗口：401 → 打开登录窗口（桌面层幂等开窗）
   ========================================================================== */

function openLoginWindow(): void {
  const wm = useWindowManager.getState();
  wm.openWindow({
    id: "platform-login",
    title: "登录",
    content: (
      <LoginWindow
        onLoggedIn={() => useWindowManager.getState().closeWindow("platform-login")}
      />
    ),
    defaultPosition: { x: 240, y: 160 },
    defaultSize: { width: 380, height: 340 },
    resizable: false,
  });
}

/* ============================================================================
   折线图（手写 SVG；令牌色 + border 网格 + hover 命中带，与图表原语同构）
   ========================================================================== */

const VB_W = 640;
const VB_H = 200;
const PAD_L = 44;
const PAD_R = 8;
const PAD_T = 10;
const PAD_B = 22;
const PLOT_W = VB_W - PAD_L - PAD_R;
const PLOT_H = VB_H - PAD_T - PAD_B;

/** 向上取整到“好看”的最大刻度（1/2/2.5/5 × 10^k）。 */
function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(v));
  const f = v / exp;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nf * exp;
}

interface CurveSeriesDef {
  /** 系列名（图例文字） */
  name: string;
  /** 系列色令牌，如 var(--color-series-1) */
  color: string;
  /** 与 labels 等长的数值序列 */
  values: number[];
}

function CurveChart({
  labels,
  series,
  formatValue = (v) => String(Math.round(v * 1000) / 1000),
}: {
  labels: string[];
  series: CurveSeriesDef[];
  /** 刻度与 tooltip 的数值格式（训练指标默认百分比） */
  formatValue?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = labels.length;
  if (n === 0 || series.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center text-xs text-text-secondary">
        暂无数据
      </div>
    );
  }

  const max = niceCeil(Math.max(...series.flatMap((s) => s.values), 1e-6));
  const colW = PLOT_W / Math.max(n - 1, 1);
  const baseY = PAD_T + PLOT_H;
  const labelSkip = Math.ceil(n / 16);
  const xAt = (i: number) => PAD_L + colW * i;
  const yAt = (v: number) => baseY - (v / max) * PLOT_H;

  return (
    <div className="relative">
      {/* ≥2 系列：顶部图例行（12px 色块 + text-secondary 文字） */}
      {series.length >= 2 && (
        <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          {series.map((s) => (
            <span
              key={s.name}
              className="inline-flex items-center gap-1.5 text-xs text-text-secondary"
            >
              <span
                className="inline-block h-3 w-3 rounded-[2px]"
                style={{ background: s.color }}
              />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="h-auto w-full"
        role="img"
        onMouseLeave={() => setHover(null)}
      >
        {/* 网格 + 左侧刻度（border 退隐；刻度 text-secondary 10px） */}
        {[0.25, 0.5, 0.75, 1].map((f) => {
          const y = PAD_T + PLOT_H * (1 - f);
          return (
            <g key={f}>
              <line
                x1={PAD_L}
                x2={VB_W - PAD_R}
                y1={y}
                y2={y}
                stroke="var(--color-border)"
                strokeWidth="1"
              />
              <text
                x={PAD_L - 6}
                y={y + 3.5}
                textAnchor="end"
                fontSize="10"
                fill="var(--color-text-secondary)"
              >
                {formatValue(max * f)}
              </text>
            </g>
          );
        })}
        <line
          x1={PAD_L}
          x2={VB_W - PAD_R}
          y1={baseY}
          y2={baseY}
          stroke="var(--color-border)"
          strokeWidth="1"
        />
        {/* X 轴刻度（epoch 标签；过多时隔列显示） */}
        {labels.map((label, i) =>
          i % labelSkip === 0 || i === n - 1 ? (
            <text
              key={`label-${i}`}
              x={xAt(i)}
              y={VB_H - 6}
              textAnchor="middle"
              fontSize="10"
              fill="var(--color-text-secondary)"
            >
              {label}
            </text>
          ) : null,
        )}
        {/* 系列折线 + 数据点（细线 1.6px，点 r=2） */}
        {series.map((s) => (
          <g key={s.name}>
            <path
              d={s.values
                .map((v, i) => `${i === 0 ? "M" : "L"}${xAt(i)},${yAt(v)}`)
                .join(" ")}
              fill="none"
              stroke={s.color}
              strokeWidth="1.6"
              strokeLinejoin="round"
              strokeLinecap="round"
              opacity={hover === null ? 1 : 0.7}
            />
            {s.values.map((v, i) => (
              <circle
                key={`pt-${i}`}
                cx={xAt(i)}
                cy={yAt(v)}
                r={hover === i ? 3 : 2}
                fill={s.color}
              />
            ))}
          </g>
        ))}
        {/* hover 参考线 */}
        {hover !== null && (
          <line
            x1={xAt(hover)}
            x2={xAt(hover)}
            y1={PAD_T}
            y2={baseY}
            stroke="var(--color-border-strong)"
            strokeWidth="1"
            strokeDasharray="3 3"
          />
        )}
        {/* 透明命中带：逐列触发 hover；键盘焦点与 hover 等价 */}
        {labels.map((label, i) => (
          <rect
            key={`hit-${i}`}
            x={xAt(i) - colW / 2}
            y={PAD_T}
            width={colW}
            height={PLOT_H}
            fill="transparent"
            tabIndex={0}
            aria-label={`${label}：${series
              .map((s) => `${s.name} ${formatValue(s.values[i] ?? 0)}`)
              .join("，")}`}
            className="outline-none"
            onMouseEnter={() => setHover(i)}
            onFocus={() => setHover(i)}
            onBlur={() => setHover(null)}
          />
        ))}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute z-10 rounded bg-button-bg px-2 py-1 text-xs leading-relaxed whitespace-nowrap text-button-text"
          style={{
            left: `${(xAt(hover) / VB_W) * 100}%`,
            top: `${(PAD_T / VB_H) * 100}%`,
            transform: "translateX(-50%)",
          }}
        >
          <div className="font-medium">第 {labels[hover]} 轮</div>
          {series.map((s) => (
            <div key={s.name} className="flex items-center gap-1.5">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: s.color }}
              />
              {s.name} {formatValue(s.values[hover] ?? 0)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================================
   格式化小工具
   ========================================================================== */

/** 0~1 指标 → 一位小数百分比。 */
const pct = (v: number): string => `${(v * 100).toFixed(1)}%`;

/** 字节数 → 可读单位。 */
function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u += 1;
  }
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[u]}`;
}

/** ISO 时间 → MM-DD HH:mm。 */
function shortTime(iso: string): string {
  return iso.length >= 16 ? `${iso.slice(5, 10)} ${iso.slice(11, 16)}` : iso;
}

/* ============================================================================
   页面
   ========================================================================== */

export default function Reports() {
  const [overview, setOverview] = useState<MonitorOverview | null>(null);
  const [home, setHome] = useState<HomeDashboard | null>(null);
  const [overviewErr, setOverviewErr] = useState<unknown>(null);
  const [homeErr, setHomeErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [selRun, setSelRun] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setOverviewErr(null);
    setHomeErr(null);
    const [ov, hd] = await Promise.allSettled([
      fetchMonitorOverview(),
      fetchHomeDashboard(),
    ]);
    if (ov.status === "fulfilled") {
      setOverview(ov.value as unknown as MonitorOverview);
    } else {
      setOverview(null);
      setOverviewErr(ov.reason);
    }
    if (hd.status === "fulfilled") {
      setHome(hd.value);
    } else {
      setHome(null);
      setHomeErr(hd.reason);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /* 当前选中的 YOLO 轮次（默认取最佳 mAP50 所在轮） */
  const runs = useMemo(() => overview?.yolo_runs ?? [], [overview]);
  const currentRun = useMemo(() => {
    if (runs.length === 0) return null;
    return (
      runs.find((r) => r.run === selRun) ??
      runs.reduce((a, b) => (b.best.map50 > a.best.map50 ? b : a))
    );
  }, [runs, selRun]);

  const classifier = overview?.classifier ?? null;
  const bestYolo = overview?.best_yolo ?? null;
  const servicesUp = overview
    ? Object.values(overview.services).filter((s) => s === "up").length
    : 0;

  /* 训练指标统一百分比刻度 */
  const pctTick = (v: number) => `${Math.round(v * 100)}%`;

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="分析报告"
        desc="训练监控（8092 只读代理）× 总控仪表盘：真实指标实时求值，无静态假图"
        aside={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
          >
            刷新
          </Button>
        }
      />

      {/* ---- 训练概览区（monitor/overview） ---- */}
      {loading && !overview && !overviewErr ? (
        <div className="flex justify-center py-12">
          <HedgehogLoader className="h-10 w-auto" />
        </div>
      ) : overviewErr ? (
        <ErrorState
          message={errorMessageOf(overviewErr)}
          onRetry={() => void load()}
        />
      ) : overview ? (
        <>
          {/* KPI 行 */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="最佳 YOLO mAP50"
              value={bestYolo ? pct(bestYolo.map50) : "—"}
              note={
                bestYolo ? `${bestYolo.run} · 第 ${bestYolo.epoch} 轮` : "暂无训练轮次"
              }
            />
            <StatTile
              label="分类器 val_acc"
              value={classifier?.best_acc != null ? pct(classifier.best_acc) : "—"}
              note={
                classifier
                  ? `第 ${classifier.best_epoch} 轮${
                      classifier.backbone ? ` · ${classifier.backbone}` : ""
                    }`
                  : "暂无分类器数据"
              }
            />
            <StatTile
              label="YOLO 训练轮次"
              value={runs.length}
              note={`累计 ${runs.reduce((acc, r) => acc + r.n_epochs, 0)} 轮 epoch`}
            />
            <StatTile
              label="训练进程"
              value={
                overview.processes.yolo_training ||
                overview.processes.classifier_training
                  ? "活跃"
                  : "空闲"
              }
              note={`服务探活 ${servicesUp}/${Object.keys(overview.services).length} 在线`}
            />
          </div>

          {/* 训练曲线：mAP50 / Recall 按 epoch */}
          <ChartCard
            title="训练曲线 · mAP50 / Recall（按 epoch）"
            aside={
              runs.length > 0 ? (
                <Select
                  className="h-7 w-40 text-xs"
                  aria-label="选择训练轮次"
                  value={currentRun?.run ?? ""}
                  onChange={(e) => setSelRun(e.target.value)}
                >
                  {runs.map((r) => (
                    <option key={r.run} value={r.run}>
                      {r.run}（{r.n_epochs} 轮）
                    </option>
                  ))}
                </Select>
              ) : undefined
            }
          >
            {currentRun ? (
              <CurveChart
                labels={currentRun.epochs.map((e) => String(e.epoch))}
                series={[
                  {
                    name: "mAP50",
                    color: "var(--color-series-1)",
                    values: currentRun.epochs.map((e) => e.map50),
                  },
                  {
                    name: "Recall",
                    color: "var(--color-series-2)",
                    values: currentRun.epochs.map((e) => e.recall),
                  },
                ]}
                formatValue={pctTick}
              />
            ) : (
              <div className="flex h-24 items-center justify-center text-xs text-text-secondary">
                暂无训练轮次数据
              </div>
            )}
          </ChartCard>

          {/* 分类器曲线（如有） */}
          {classifier && classifier.epochs.length > 0 && (
            <ChartCard
              title="分类器训练曲线 · val_acc（按 epoch）"
              aside={
                classifier.running ? (
                  <StatusBadge kind="good">训练中</StatusBadge>
                ) : (
                  <StatusBadge kind="neutral">已收敛</StatusBadge>
                )
              }
            >
              <CurveChart
                labels={classifier.epochs.map((e) => String(e.epoch))}
                series={[
                  {
                    name: "val_acc",
                    color: "var(--color-series-1)",
                    values: classifier.epochs.map((e) => e.val_acc),
                  },
                ]}
                formatValue={pctTick}
              />
            </ChartCard>
          )}
        </>
      ) : null}

      {/* ---- 总控仪表盘区（home/dashboard，需登录会话） ---- */}
      {homeErr ? (
        homeErr instanceof ApiError && homeErr.status === 401 ? (
          <NeedLoginState onOpenLogin={openLoginWindow} />
        ) : (
          <section className="rounded-lg border border-border bg-surface p-4">
            <h3 className="mb-1 font-display text-sm font-bold text-text-primary">
              总控仪表盘
            </h3>
            <ErrorState
              message={errorMessageOf(homeErr)}
              onRetry={() => void load()}
            />
          </section>
        )
      ) : home ? (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <ChartCard title="运行状态分布" aside="runs_by_status">
              <VBars
                data={Object.entries(home.progress.runs_by_status).map(
                  ([status, count]) => ({ label: status, value: count }),
                )}
                unit=" 次"
              />
            </ChartCard>
            <ChartCard title="项目完成率" aside={`${home.progress.projects.length} 个项目`}>
              <VBars
                data={home.progress.projects.map((p) => ({
                  label: p.project_id,
                  value: Math.round(p.completion * 100),
                }))}
                unit="%"
              />
            </ChartCard>
          </div>

          <section className="space-y-2">
            <h3 className="font-display text-sm font-bold text-text-primary">
              近期活动
            </h3>
            <ApiTable
              rows={home.activity.slice(0, 10)}
              rowKey={(r) => String(r.seq)}
              cols={[
                {
                  key: "at",
                  label: "时间",
                  render: (r) => (
                    <span className="text-text-secondary tabular-nums">
                      {shortTime(r.at)}
                    </span>
                  ),
                },
                {
                  key: "type",
                  label: "类型",
                  render: (r) => (
                    <span className="text-text-secondary">{r.type}</span>
                  ),
                },
                { key: "text", label: "事件" },
                {
                  key: "actor",
                  label: "执行者",
                  render: (r) => (
                    <span className="text-text-secondary">{r.actor}</span>
                  ),
                },
              ]}
              emptyText="暂无活动记录"
            />
          </section>

          <section className="space-y-2">
            <h3 className="font-display text-sm font-bold text-text-primary">
              平台容量
            </h3>
            <KV
              items={[
                { label: "数据库体积", value: formatBytes(home.capacity.db_bytes) },
                { label: "数据表数", value: home.capacity.tables },
                {
                  label: "平台目录体积",
                  value: formatBytes(home.capacity.platform_dir_bytes),
                },
                {
                  label: "磁盘余量",
                  value:
                    home.capacity.disk.free_gb != null
                      ? `${home.capacity.disk.free_gb} GB（共 ${home.capacity.disk.total_gb ?? "—"} GB）`
                      : "—",
                },
                { label: "Outbox 待投递", value: home.capacity.outbox_pending },
                { label: "已应用迁移", value: home.capacity.migrations },
              ]}
            />
          </section>
        </>
      ) : loading ? (
        <div className="flex justify-center py-8">
          <HedgehogLoader className="h-8 w-auto" />
        </div>
      ) : null}
    </div>
  );
}
