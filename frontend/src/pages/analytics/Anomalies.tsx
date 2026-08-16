/**
 * 分析与 BI · 异常检测（P7）。
 *
 * 数据源（同源 /api/v1/*，禁假数据）：
 * —— /api/v1/monitor/live：训练监控实时快照（legacy.training.monitor 8092 只读代理，
 *    返回当前活跃的 YOLO 检测训练或级联分类器实时进度）。
 *
 * 视角：从 live 快照推导异常信号（无活跃训练 / 数据过期 / 早停候选 / 权重口径），
 * 每条规则口径写在卡片上；只读页面，无 mutation。
 */
import { useCallback, useEffect, useState } from "react";
import { fetchMonitorLive } from "@/lib/api";
import {
  ErrorState,
  KV,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import { Button } from "@/components/ui/button";
import { HedgehogLoader } from "@/components/ui/loader";
import { HedgehogMascot } from "@/components/ui/mascot";

/* ============================================================================
   monitor/live 载荷类型（YOLO 与分类器两种形态的并集，字段按存在性读取）
   ========================================================================== */

interface MonitorLive {
  /** "yolo" | "classifier" */
  type: string;
  active?: boolean;
  /* ---- YOLO 字段 ---- */
  name?: string;
  epoch?: number;
  total_epochs?: number;
  batch?: number;
  total_batches?: number;
  epoch_progress?: number;
  box_loss?: number;
  cls_loss?: number;
  eta_epoch_sec?: number;
  age_sec?: number;
  last_map50?: number;
  last_recall?: number;
  last_precision?: number;
  last_done_epoch?: number;
  best_map50?: number;
  best_epoch?: number;
  epochs_since_best?: number;
  /* ---- 分类器字段 ---- */
  finished?: boolean;
  best_acc?: number | null;
  history_best_acc?: number;
  best_source?: string;
  final_epochs?: number;
}

/* ============================================================================
   异常推导（观察值均来自实时快照；口径逐条标注）
   ========================================================================== */

interface AnomalyItem {
  id: string;
  tone: "good" | "warn" | "serious" | "neutral";
  title: string;
  detail: string;
  observed: string;
  rule: string;
}

function deriveAnomalies(live: MonitorLive): AnomalyItem[] {
  const out: AnomalyItem[] = [];

  if (live.type === "yolo") {
    if (!live.active) {
      out.push({
        id: "yolo-inactive",
        tone: "warn",
        title: "无活跃 YOLO 检测训练",
        detail:
          "训练进程未运行或日志超过 10 分钟未更新；若为计划内停机可忽略。",
        observed: live.name ? `轮次 ${live.name}` : "未检测到训练日志",
        rule: "active = false",
      });
    }
    if (live.age_sec != null && live.age_sec > 600) {
      out.push({
        id: "yolo-stale",
        tone: "warn",
        title: "监控数据过期",
        detail: "训练日志长时间未更新，实时指标可能不再反映当前状态。",
        observed: `age_sec = ${live.age_sec}s`,
        rule: "age_sec > 600",
      });
    }
    if (live.epochs_since_best != null && live.epochs_since_best >= 10) {
      out.push({
        id: "yolo-patience",
        tone: "warn",
        title: "距最佳轮次已达 patience，候选早停",
        detail:
          "继续训练的边际收益有限，建议核对验证集后决定是否提前结束本轮。",
        observed: `距第 ${live.best_epoch ?? "—"} 轮最佳已过 ${live.epochs_since_best} 轮`,
        rule: "epochs_since_best ≥ 10（patience = 10 口径）",
      });
    }
  }

  if (live.type === "classifier") {
    if (live.finished) {
      out.push({
        id: "clf-finished",
        tone: "neutral",
        title: "分类器训练已结束",
        detail: "训练进程已收敛退出；展示的 best 以当前生产 best.pt 为准。",
        observed:
          live.best_acc != null
            ? `val_acc = ${(live.best_acc * 100).toFixed(2)}%（第 ${live.best_epoch ?? "—"} 轮）`
            : "无 best 元数据",
        rule: "finished = true",
      });
    } else if (!live.active) {
      out.push({
        id: "clf-inactive",
        tone: "warn",
        title: "无活跃分类器训练",
        detail: "live_progress 超过 2 分钟未更新且训练未标记结束。",
        observed: live.age_sec != null ? `age_sec = ${live.age_sec}s` : "无更新时间",
        rule: "active = false 且 finished = false",
      });
    }
    if (live.best_source === "history_file") {
      out.push({
        id: "clf-best-source",
        tone: "warn",
        title: "best 值取自历史文件",
        detail:
          "当前 best.pt 缺少 val_acc 元数据，展示的 best 退化为训练历史最佳，勿当作线上权重的真实精度。",
        observed:
          live.history_best_acc != null
            ? `history_best_acc = ${(live.history_best_acc * 100).toFixed(2)}%`
            : "无历史最佳值",
        rule: "best_source = history_file",
      });
    }
  }

  return out;
}

/** ISO 秒级时间戳 → HH:mm:ss。 */
function clock(ts?: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}

/* ============================================================================
   页面
   ========================================================================== */

export default function Anomalies() {
  const [live, setLive] = useState<MonitorLive | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const d = await fetchMonitorLive();
      setLive(d as unknown as MonitorLive);
    } catch (e) {
      setLive(null);
      setErr(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const anomalies = live ? deriveAnomalies(live) : [];

  /* 实时快照键值（按 type 取并集字段，缺省显示破折号） */
  const snapshot: { label: string; value: string | number }[] = live
    ? live.type === "yolo"
      ? [
          { label: "训练轮次", value: live.name ?? "—" },
          {
            label: "当前轮",
            value:
              live.epoch != null
                ? `${live.epoch} / ${live.total_epochs ?? "—"}`
                : "—",
          },
          {
            label: "批进度",
            value:
              live.batch != null
                ? `${live.batch} / ${live.total_batches ?? "—"}（${(
                    (live.epoch_progress ?? 0) * 100
                  ).toFixed(0)}%）`
                : "—",
          },
          {
            label: "损失",
            value:
              live.box_loss != null
                ? `box ${live.box_loss.toFixed(3)} · cls ${live.cls_loss?.toFixed(3) ?? "—"}`
                : "—",
          },
          {
            label: "本轮剩余",
            value:
              live.eta_epoch_sec != null
                ? `约 ${Math.ceil(live.eta_epoch_sec / 60)} 分钟`
                : "—",
          },
          {
            label: "最近指标",
            value:
              live.last_map50 != null
                ? `mAP50 ${(live.last_map50 * 100).toFixed(1)}% · Recall ${(
                    (live.last_recall ?? 0) * 100
                  ).toFixed(1)}%（第 ${live.last_done_epoch ?? "—"} 轮）`
                : "—",
          },
          {
            label: "最佳",
            value:
              live.best_map50 != null
                ? `mAP50 ${(live.best_map50 * 100).toFixed(1)}% @ 第 ${live.best_epoch ?? "—"} 轮`
                : "—",
          },
          { label: "数据更新时间", value: clock(live.age_sec != null ? Date.now() / 1000 - live.age_sec : undefined) },
        ]
      : [
          { label: "训练类型", value: "级联分类器" },
          {
            label: "best val_acc",
            value:
              live.best_acc != null
                ? `${(live.best_acc * 100).toFixed(2)}%（第 ${live.best_epoch ?? "—"} 轮）`
                : "—",
          },
          {
            label: "历史最佳",
            value:
              live.history_best_acc != null
                ? `${(live.history_best_acc * 100).toFixed(2)}%`
                : "—",
          },
          { label: "best 口径", value: live.best_source ?? "—" },
          {
            label: "累计轮数",
            value: live.final_epochs ?? "—",
          },
          {
            label: "数据更新时间",
            value: clock(live.age_sec != null ? Date.now() / 1000 - live.age_sec : undefined),
          },
        ]
    : [];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="异常检测"
        desc="训练监控实时快照（monitor/live）推导的异常信号；口径逐条标注，只读"
        aside={
          <div className="flex items-center gap-2">
            {live && (
              <StatusBadge
                kind={live.active ? "good" : live.finished ? "neutral" : "warn"}
              >
                {live.type === "yolo"
                  ? live.active
                    ? "YOLO 训练中"
                    : "YOLO 未活跃"
                  : live.finished
                    ? "分类器已结束"
                    : live.active
                      ? "分类器训练中"
                      : "分类器未活跃"}
              </StatusBadge>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void load()}
              disabled={loading}
            >
              刷新
            </Button>
          </div>
        }
      />

      {loading && !live && !err ? (
        <div className="flex justify-center py-12">
          <HedgehogLoader className="h-10 w-auto" />
        </div>
      ) : err ? (
        <ErrorState
          message={errorMessageOf(err)}
          onRetry={() => void load()}
        />
      ) : live ? (
        <>
          {/* 异常信号列表 */}
          {anomalies.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-lg border border-border bg-surface py-10">
              <HedgehogMascot className="h-20 w-auto" />
              <p className="text-sm font-medium text-text-primary">
                暂无异常信号
              </p>
              <p className="text-xs text-text-secondary">
                训练数据新鲜且进度正常；出现活跃训练停滞 / 早停候选时将在此列出
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {anomalies.map((a) => (
                <article
                  key={a.id}
                  className="rounded-md border border-border bg-surface px-3 py-2.5"
                >
                  <div className="flex items-center gap-2">
                    <StatusBadge kind={a.tone}>
                      {a.tone === "warn"
                        ? "需关注"
                        : a.tone === "serious"
                          ? "严重"
                          : a.tone === "good"
                            ? "正常"
                            : "提示"}
                    </StatusBadge>
                    <h3 className="text-[13px] font-bold text-text-primary">
                      {a.title}
                    </h3>
                  </div>
                  <p className="mt-1 text-xs text-text-secondary">{a.detail}</p>
                  <KV
                    className="mt-2"
                    items={[
                      { label: "观察值", value: a.observed },
                      { label: "规则口径", value: a.rule },
                    ]}
                  />
                </article>
              ))}
            </div>
          )}

          {/* 实时训练快照 */}
          <section className="space-y-2">
            <h3 className="font-display text-sm font-bold text-text-primary">
              实时训练快照
            </h3>
            <KV items={snapshot} />
          </section>
        </>
      ) : null}
    </div>
  );
}
