/**
 * 识别任务（/vision/tasks，v3 瘦版）。
 *
 * 数据源（真实接口，无样本数据）—— 级联统一任务表（VLM-016，shadow 默认）：
 *   GET  /api/v1/cascade/tasks               任务列表（五入口共用同一任务表）
 *   GET  /api/v1/cascade/tasks/{id}          详情（契约 / SLA / 成本账本）
 *   GET  /api/v1/cascade/tasks/{id}/trail    阶段轨迹（为何走到这一步）
 *   GET  /api/v1/cascade/tasks/{id}/regions  检测区域
 *   POST /api/v1/cascade/tasks/{id}/cancel   取消（真实 mutation，仅未终态可点）
 *
 * 状态纪律：401 → NeedLoginState；404 → 级联服务未启用（诚实态）；
 * 其余错误 → ErrorState + 重试。技术字段（模型哈希/risk/token）折叠展示。
 */
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  fetchCancelCascadeTask,
  fetchCascadeRegions,
  fetchCascadeTask,
  fetchCascadeTasks,
  fetchCascadeTrail,
  type CascadeTaskDetail,
  type CascadeTaskRow,
  type CascadeTrailItem,
} from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  errorMessageOf,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  type StatusKind,
} from "@/components/data";
import { Button } from "@/components/ui/button";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   业务语言映射（页面一律业务语言，技术字段折叠）
   ========================================================================== */

const ENTRY_CN: Record<string, string> = {
  single_file: "单文件",
  batch_file: "批量文件",
  url: "URL",
  api: "API",
  agent: "Agent",
};

const TIER_CN: Record<string, string> = {
  fast: "fast（快速）",
  standard: "standard（标准）",
  deep: "deep（深度）",
  expert: "expert（专家）",
};

/** 节点 → 业务阶段。 */
const STAGE_OF_NODE: Record<string, string> = {
  quality: "S0 照片检查",
  scene: "S0 照片检查",
  detect: "S1 检测+快分类",
  classify_fast: "S1 检测+快分类",
  risk_s1: "S1 检测+快分类",
  segment: "S2 SAM 精修",
  reclassify: "S2 SAM 精修",
  risk_s2: "S2 SAM 精修",
  retrieve: "S3 召回",
  risk_s3: "S3 召回",
  vlm_rerank: "S4 VLM 裁决",
  risk_s4: "S4 VLM 裁决",
  human_review: "S5 人工审核",
  finalize: "已完成",
};

const DECISION_CN: Record<string, string> = {
  next: "顺行",
  escalate: "升级下一阶段",
  accept: "自动接受",
  human: "转人工",
  abstain: "拒识（unknown）",
  on_fail: "失败分支",
  terminal: "终点",
};

/** 任务状态 → 中文 + 徽章类别。 */
function statusOf(status: string): { label: string; kind: StatusKind } {
  switch (status) {
    case "completed":
      return { label: "已完成", kind: "good" };
    case "failed":
      return { label: "失败", kind: "serious" };
    case "waiting_human":
      return { label: "待人工", kind: "warn" };
    default:
      return { label: status || "进行中", kind: "neutral" };
  }
}

/** result_json 容错解析（档位等元信息）。 */
function resultMeta(task: CascadeTaskRow): Record<string, unknown> {
  try {
    return (JSON.parse(task.result_json ?? "{}") ?? {}) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** 轨迹 → 当前业务阶段（取最后一个可映射节点）。 */
function currentStage(trail: CascadeTrailItem[]): string {
  for (let i = trail.length - 1; i >= 0; i--) {
    const s = STAGE_OF_NODE[trail[i].node];
    if (s) return s;
  }
  return "尚未开始";
}

/** 轨迹 → 升级原因（最近一次 escalate / human）。 */
function upgradeReason(trail: CascadeTrailItem[]): string {
  const esc = [...trail]
    .reverse()
    .find((t) => t.decision === "escalate" || t.decision === "human");
  return esc ? esc.reason : "无升级：在当前阶段直接得出结论";
}

/** 自动 / 待人工。 */
function pendingHuman(task: CascadeTaskRow, trail: CascadeTrailItem[]): string {
  if (task.status === "waiting_human") return "待人工";
  if (trail.some((t) => t.decision === "human")) return "待人工";
  return "自动";
}

/* ============================================================================
   页面主体
   ========================================================================== */

export default function Tasks() {
  const [tasks, setTasks] = useState<CascadeTaskRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [disabled, setDisabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  /* ---- 详情（含轨迹 / 区域） ---- */
  const [detail, setDetail] = useState<CascadeTaskDetail | null>(null);
  const [trail, setTrail] = useState<CascadeTrailItem[]>([]);
  const [regions, setRegions] = useState<Array<Record<string, unknown>>>([]);

  /** 打开登录窗口（窗口管理器幂等）。 */
  const openWindow = useWindowManager((s) => s.openWindow);
  const closeWindow = useWindowManager((s) => s.closeWindow);
  const openLogin = useCallback(() => {
    openWindow({
      id: "login",
      title: "平台登录",
      content: <LoginWindow onLoggedIn={() => closeWindow("login")} />,
      defaultPosition: { x: 320, y: 180 },
      defaultSize: { width: 360, height: 420 },
    });
  }, [openWindow, closeWindow]);

  const reload = useCallback(async () => {
    setError(null);
    setNeedLogin(false);
    setDisabled(false);
    try {
      const d = await fetchCascadeTasks();
      setTasks(d.tasks);
    } catch (e) {
      setTasks(null);
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else if (e instanceof ApiError && e.status === 404) setDisabled(true);
      else setError(e);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** 打开任务详情：详情 + 轨迹 + 区域 并发（轨迹/区域失败不阻塞）。 */
  const openDetail = async (taskId: string) => {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const [d, t, r] = await Promise.all([
        fetchCascadeTask(taskId),
        fetchCascadeTrail(taskId).catch(() => ({ trail: [] as CascadeTrailItem[] })),
        fetchCascadeRegions(taskId).catch(() => ({
          regions: [] as Array<Record<string, unknown>>,
        })),
      ]);
      setDetail(d);
      setTrail(t.trail);
      setRegions(r.regions);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  /** 取消任务（真实 mutation；仅未终态任务显示）。 */
  const cancel = async (taskId: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fetchCancelCascadeTask(taskId);
      setMsg("已提交取消请求");
      setDetail(null);
      await reload();
    } catch (e) {
      setMsg(`取消失败：${errorMessageOf(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const billingTotal = (detail?.billing ?? []).reduce(
    (s, b) => s + (Number(b.billed_cost) || 0),
    0,
  );

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="识别任务"
        desc="单文件 / 批量 / URL / API / Agent 五入口共用同一级联任务表（shadow 默认）；详情可查阶段轨迹与成本"
        aside={
          <Button variant="secondary" size="sm" onClick={() => void reload()}>
            刷新
          </Button>
        }
      />

      {needLogin && <NeedLoginState onOpenLogin={openLogin} />}
      {disabled && (
        <ErrorState
          message="级联 API 未启用：当前平台进程尚未注入 cascade service（shadow 阶段诚实状态）。旧识别入口仍可用。"
          onRetry={() => void reload()}
        />
      )}
      {!needLogin && !disabled && (
        <ApiTable<CascadeTaskRow>
          rows={tasks ?? []}
          loading={tasks === null && error === null}
          error={error}
          onRetry={() => void reload()}
          emptyText="暂无级联任务（空队列是诚实状态，不是错误）"
          rowKey={(t) => t.task_id}
          cols={[
            { key: "task_id", label: "任务", render: (t) => t.task_id.slice(0, 8) + "…" },
            { key: "entry", label: "入口", render: (t) => ENTRY_CN[t.entry] ?? t.entry },
            {
              key: "tier",
              label: "档位",
              render: (t) => TIER_CN[String(resultMeta(t).tier ?? "")] ?? "—",
            },
            {
              key: "status",
              label: "状态",
              render: (t) => {
                const s = statusOf(t.status);
                return <StatusBadge kind={s.kind}>{s.label}</StatusBadge>;
              },
            },
            { key: "file_count", label: "文件数", align: "right" },
            { key: "sku_count", label: "检出", align: "right" },
            { key: "created_by", label: "发起人" },
            { key: "created_at", label: "时间" },
            {
              key: "op",
              label: "操作",
              render: (t) => (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  disabled={busy}
                  onClick={() => void openDetail(t.task_id)}
                >
                  详情
                </Button>
              ),
            },
          ]}
        />
      )}

      {msg && <p className="text-xs text-text-secondary">{msg}</p>}

      {/* 任务详情（内联卡片，不另开窗） */}
      {detail && (
        <section className="space-y-3 rounded-md border border-border bg-surface p-3">
          <header className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-medium text-text-primary">
              任务详情 · {detail.task.task_id.slice(0, 8)}…
            </h2>
            <div className="flex items-center gap-2">
              {detail.task.status !== "completed" &&
                detail.task.status !== "failed" && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy}
                    onClick={() => void cancel(detail.task.task_id)}
                  >
                    取消任务
                  </Button>
                )}
              <Button variant="ghost" size="sm" onClick={() => setDetail(null)}>
                关闭
              </Button>
            </div>
          </header>

          <KV
            items={[
              {
                label: "档位",
                value: TIER_CN[String(resultMeta(detail.task).tier ?? "")] ?? "—",
              },
              { label: "当前阶段", value: currentStage(trail) },
              { label: "自动/待人工", value: pendingHuman(detail.task, trail) },
              {
                label: "剩余 SLA",
                value: detail.remaining_sla
                  ? detail.remaining_sla.expired
                    ? "已到期（转人工）"
                    : `${detail.remaining_sla.remaining_hours}h / ${detail.remaining_sla.sla_hours}h`
                  : "—",
              },
              { label: "成本（rate-card）", value: `${billingTotal.toFixed(2)} 单位` },
              { label: "为何升级", value: upgradeReason(trail) },
            ]}
          />

          <div>
            <h3 className="mb-1.5 text-xs font-medium text-text-secondary">
              阶段轨迹（为何走到这一步）
            </h3>
            <ApiTable<CascadeTrailItem>
              rows={trail}
              rowKey={(t, i) => `${t.node}-${i}`}
              emptyText="暂无轨迹"
              cols={[
                {
                  key: "node",
                  label: "阶段",
                  render: (t) => STAGE_OF_NODE[t.node] ?? t.node,
                },
                {
                  key: "decision",
                  label: "决策",
                  render: (t) => (
                    <StatusBadge
                      kind={
                        t.decision === "human" || t.decision === "escalate"
                          ? "warn"
                          : t.decision === "abstain"
                            ? "serious"
                            : "good"
                      }
                    >
                      {DECISION_CN[t.decision] ?? t.decision}
                    </StatusBadge>
                  ),
                },
                { key: "reason", label: "为何" },
              ]}
            />
          </div>

          <details className="rounded-md border border-border bg-background px-3 py-2">
            <summary className="cursor-pointer text-xs text-text-secondary">
              检测区域（{regions.length}）/ 成本明细 / 技术字段
            </summary>
            <div className="mt-2 space-y-2">
              {regions.length === 0 ? (
                <p className="text-xs text-text-secondary">
                  无区域（可能尚未到检测阶段）。
                </p>
              ) : (
                <pre className="overflow-x-auto rounded border border-border bg-surface p-2 text-[11px] text-text-secondary">
                  {JSON.stringify(regions, null, 2)}
                </pre>
              )}
              {(detail.billing ?? []).length === 0 ? (
                <p className="text-xs text-text-secondary">暂无成本账本。</p>
              ) : (
                <ApiTable
                  rows={(detail.billing ?? []).map((b, i) => ({
                    i,
                    capability: String(b.capability ?? "—"),
                    cost: String(b.billed_cost ?? "—"),
                    evidence: String(b.evidence_id ?? "—"),
                  }))}
                  rowKey={(r) => String(r.i)}
                  cols={[
                    { key: "capability", label: "能力" },
                    { key: "cost", label: "成本", align: "right" },
                    { key: "evidence", label: "证据" },
                  ]}
                />
              )}
              {trail.map((t, i) => (
                <p key={i} className="text-[11px] text-text-secondary">
                  {t.node}：policy={String(t.detail?.policy_version ?? "—")}，risk=
                  {String(t.detail?.risk ?? "—")}，tokens=
                  {String(t.detail?.tokens ?? "—")}，模型哈希=
                  {String(t.detail?.model_hash ?? t.detail?.model ?? "—")}
                </p>
              ))}
              {detail.result && (
                <pre className="overflow-x-auto rounded border border-border bg-surface p-2 text-[11px] text-text-secondary">
                  {JSON.stringify(detail.result, null, 2)}
                </pre>
              )}
            </div>
          </details>
        </section>
      )}
    </div>
  );
}
