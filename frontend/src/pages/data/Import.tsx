/**
 * 导入中心（P4）：平台作业队列台账 + 结果查看。
 *
 * 数据源（同源 /api/v1/*，src/lib/api.ts）：
 * —— fetchJobs(): GET /api/v1/jobs → {stats, count, jobs}；
 *    行数据自带 payload_json / result_json / error，结果查看直接取自行；
 * —— fetchIamPost(`jobs/{id}/cancel`): POST /api/v1/jobs/{id}/cancel
 *    （api.ts 通用写通道，自动携带 CSRF）；后端仅允许取消 queued，
 *    running 靠 lease 过期回收，取消留审计痕迹。
 *
 * 自 web/src/pages/ImportCenter.tsx 瘦版重实现：保留“状态过滤 +
 * 逐行错误 + 结果查看”核心交互；模板上传/dry-run/隔离裁决等重流程
 * 不在本页承载。
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, fetchIamPost, fetchJobs } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useWindowManager } from "@/store/windowStore";
import LoginWindow from "@/components/ui/LoginWindow";
import { Button } from "@/components/ui/button";
import { StatTile } from "@/components/charts/primitives";
import {
  ApiTable,
  ErrorState,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";
import { cn } from "@/lib/utils";

/* ============================================================================
   类型与常量
   ========================================================================== */

/** /api/v1/jobs 的 job 行（job 表冻结列 + 迁移增列弹性处理）。 */
interface JobRow {
  job_id: string;
  kind: string;
  status: string;
  payload_json: string | null;
  result_json: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

/** 状态 → StatusBadge（图标 + 文字，状态呈现的唯一方式）。 */
const STATUS_META: Record<string, { kind: StatusKind; label: string }> = {
  queued: { kind: "neutral", label: "排队中" },
  running: { kind: "neutral", label: "运行中" },
  succeeded: { kind: "good", label: "已成功" },
  failed: { kind: "serious", label: "已失败" },
  cancelled: { kind: "warn", label: "已取消" },
};

/** 状态过滤页签（计数取自 stats）。 */
const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "queued", label: "排队中" },
  { key: "running", label: "运行中" },
  { key: "succeeded", label: "已成功" },
  { key: "failed", label: "已失败" },
  { key: "cancelled", label: "已取消" },
];

/** stats 指标块（数值键；worker_id 等字符串键不展示）。 */
const STAT_TILES: [string, string][] = [
  ["queued", "排队中"],
  ["running", "运行中"],
  ["succeeded", "已成功"],
  ["failed", "已失败"],
  ["cancelled", "已取消"],
  ["dead_letters", "死信"],
];

/* ============================================================================
   小工具
   ========================================================================== */

/** unknown → 字符串（空值归一为空串）。 */
function text(v: unknown): string {
  if (typeof v === "string") return v;
  if (v === null || v === undefined) return "";
  return String(v);
}

/** unknown → string | null（后端 TEXT 列可为 NULL）。 */
function textOrNull(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

/** 弹性收敛 Record<string, unknown> 为 JobRow。 */
function toJobRow(raw: Record<string, unknown>): JobRow {
  return {
    job_id: text(raw.job_id),
    kind: text(raw.kind),
    status: text(raw.status),
    payload_json: textOrNull(raw.payload_json),
    result_json: textOrNull(raw.result_json),
    error: textOrNull(raw.error),
    created_at: text(raw.created_at),
    updated_at: text(raw.updated_at),
  };
}

/** JSON 字符串 → 美化文本（解析失败原样返回，绝不吞数据）。 */
function prettyJson(raw: string | null): string {
  if (!raw) return "";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

/** 时间 ISO → “YYYY-MM-DD HH:mm”（只读台账，秒级不展示）。 */
function fmtTime(v: string): string {
  return v ? v.slice(0, 16).replace("T", " ") : "—";
}

/** 打开登录窗口（桌面层窗口管理器全局单例，幂等 id）。 */
function openLoginWindow(): void {
  const wm = useWindowManager.getState();
  wm.openWindow({
    id: "login",
    title: "平台登录",
    content: (
      <LoginWindow
        onLoggedIn={() => useWindowManager.getState().closeWindow("login")}
      />
    ),
    defaultPosition: { x: 160, y: 120 },
    defaultSize: { width: 360, height: 320 },
    resizable: false,
  });
}

/** JSON 块：标题 + 美化 pre（空值破折号）。 */
function JsonBlock({ title, raw }: { title: string; raw: string | null }) {
  const body = prettyJson(raw);
  return (
    <div className="min-w-0 space-y-1.5">
      <h3 className="text-xs text-text-secondary">{title}</h3>
      {body ? (
        <pre className="max-h-56 overflow-auto rounded-md border border-border bg-surface p-3 text-xs leading-relaxed text-text-primary">
          {body}
        </pre>
      ) : (
        <p className="text-xs text-text-secondary">—</p>
      )}
    </div>
  );
}

/* ============================================================================
   页面
   ========================================================================== */

export default function Import() {
  const me = useAuth((s) => s.me);
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [actionMsg, setActionMsg] = useState<{
    kind: StatusKind;
    text: string;
  } | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await fetchJobs();
      const numeric: Record<string, number> = {};
      for (const [k, v] of Object.entries(d.stats)) {
        if (typeof v === "number") numeric[k] = v;
      }
      setStats(numeric);
      setJobs(d.jobs.map(toJobRow));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  /* 401 → 需要登录；登录成功（me 变化）后自动重试 */
  const unauthorized = error instanceof ApiError && error.status === 401;
  useEffect(() => {
    if (me && unauthorized) void reload();
  }, [me, unauthorized, reload]);

  /** 取消作业：仅 queued 可取消（后端 409 拦截其他状态，留审计）。 */
  async function cancelJob(jobId: string) {
    setActing(true);
    setActionMsg(null);
    try {
      await fetchIamPost(`jobs/${jobId}/cancel`, {});
      setActionMsg({ kind: "good", text: `已取消 ${jobId}，审计留痕` });
      await reload();
    } catch (e) {
      setActionMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setActing(false);
    }
  }

  const selected = jobs.find((j) => j.job_id === selectedId) ?? null;
  const visible =
    filter === "all" ? jobs : jobs.filter((j) => j.status === filter);

  const cols: ApiTableCol<JobRow>[] = [
    {
      key: "job_id",
      label: "作业 ID",
      render: (r) => (
        <span className="whitespace-nowrap" title={r.job_id}>
          {r.job_id.slice(0, 8)}…
        </span>
      ),
    },
    { key: "kind", label: "类型" },
    {
      key: "status",
      label: "状态",
      render: (r) => {
        const m = STATUS_META[r.status] ?? {
          kind: "neutral" as StatusKind,
          label: r.status || "未知",
        };
        return <StatusBadge kind={m.kind}>{m.label}</StatusBadge>;
      },
    },
    {
      key: "created_at",
      label: "创建时间",
      render: (r) => fmtTime(r.created_at),
    },
    {
      key: "updated_at",
      label: "更新时间",
      render: (r) => fmtTime(r.updated_at),
    },
    {
      key: "error",
      label: "错误",
      render: (r) =>
        r.error ? (
          <span className="block max-w-[240px] truncate" title={r.error}>
            {r.error}
          </span>
        ) : (
          <span className="text-text-secondary">—</span>
        ),
    },
    {
      key: "actions",
      label: "操作",
      render: (r) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            setSelectedId(r.job_id === selectedId ? null : r.job_id)
          }
        >
          {r.job_id === selectedId ? "收起" : "查看"}
        </Button>
      ),
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="导入中心"
        desc="平台作业队列台账：提交 → 排队 → 执行 → 结果/错误留痕；失败作业进入死信，取消留审计"
        aside={
          <Button
            variant="secondary"
            size="sm"
            disabled={loading}
            onClick={() => void reload()}
          >
            刷新
          </Button>
        }
      />

      {unauthorized ? (
        <NeedLoginState onOpenLogin={openLoginWindow} />
      ) : error ? (
        <ErrorState
          message={errorMessageOf(error)}
          onRetry={() => void reload()}
        />
      ) : (
        <>
          {stats && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
              {STAT_TILES.map(([k, label]) => (
                <StatTile
                  key={k}
                  label={label}
                  value={(stats[k] ?? 0).toLocaleString("zh-CN")}
                />
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-1.5" aria-label="按状态过滤">
            {FILTERS.map((f) => {
              const active = filter === f.key;
              const n =
                f.key === "all" ? jobs.length : (stats?.[f.key] ?? 0);
              return (
                <button
                  key={f.key}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setFilter(f.key)}
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs transition-colors duration-200",
                    active
                      ? "border-accent bg-background text-accent"
                      : "border-border bg-surface text-text-secondary hover:border-accent hover:text-accent",
                  )}
                >
                  {f.label} {n}
                </button>
              );
            })}
          </div>

          <ApiTable
            rows={visible}
            cols={cols}
            loading={loading}
            rowKey={(r) => r.job_id}
            emptyText="当前视图暂无作业"
          />

          {actionMsg && (
            <div className="flex items-center gap-2">
              <StatusBadge kind={actionMsg.kind}>
                {actionMsg.kind === "good" ? "操作成功" : "操作失败"}
              </StatusBadge>
              <span className="text-xs text-text-secondary">
                {actionMsg.text}
              </span>
            </div>
          )}

          {selected && (
            <section className="space-y-3 rounded-md border border-border bg-background p-4">
              <header className="flex items-center justify-between gap-3">
                <h2 className="font-display text-sm font-bold text-text-primary">
                  结果查看 · {selected.kind || "未知类型"}
                </h2>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedId(null)}
                >
                  收起
                </Button>
              </header>

              <KV
                items={[
                  { label: "作业 ID", value: selected.job_id },
                  { label: "类型", value: selected.kind || "—" },
                  {
                    label: "状态",
                    value: (
                      <StatusBadge
                        kind={
                          STATUS_META[selected.status]?.kind ?? "neutral"
                        }
                      >
                        {STATUS_META[selected.status]?.label ??
                          selected.status}
                      </StatusBadge>
                    ),
                  },
                  { label: "创建时间", value: fmtTime(selected.created_at) },
                  { label: "更新时间", value: fmtTime(selected.updated_at) },
                  { label: "错误", value: selected.error ?? "—" },
                ]}
              />

              {selected.status === "queued" && (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={acting}
                    onClick={() => void cancelJob(selected.job_id)}
                  >
                    取消作业
                  </Button>
                  <span className="text-xs text-text-secondary">
                    仅排队中（queued）可取消；运行中靠 lease 过期回收，
                    取消操作留审计痕迹
                  </span>
                </div>
              )}

              <div className="grid gap-3 lg:grid-cols-2">
                <JsonBlock title="提交载荷 payload" raw={selected.payload_json} />
                <JsonBlock title="执行结果 result" raw={selected.result_json} />
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
