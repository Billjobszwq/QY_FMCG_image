/**
 * 运行中心（/workflow/runs）—— GraphRun 与 Loop v2 运行台账（瘦版重实现）。
 *
 * 数据源（同源 /api/v1，全部真实数据，禁止样本）：
 * —— GET  /api/v1/runs、/api/v1/runs/{id}（节点时间线 / Evidence / 输出）
 * —— POST /api/v1/runs（system_health_v1）、/api/v1/assets/upload + FMCG 级联启动
 * —— POST /api/v1/runs/{id}/approve（人工门批准 / 拒绝）
 * —— GET  /api/v1/loops/runs、/api/v1/loops/runs/{id}（trail / 成本 / 停止原因）
 * —— POST /api/v1/loops/runs/{id}/gate（Loop 人工门）
 *
 * 状态纪律：状态一律 StatusBadge（图标+文字）；加载走 ApiTable 内置
 * HedgehogLoader；401 → NeedLoginState；网络错误 → ErrorState + 重试。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ApiError,
  fetchApproveRun,
  fetchGateLoop,
  fetchLoopRun,
  fetchLoopRuns,
  fetchRun,
  fetchRuns,
  fetchStartRun,
  fetchUploadAsset,
} from "@/lib/api";
import type { LoopRunRow, LoopRunView, RunRow, RunView } from "@/lib/api";
import {
  ApiTable,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";
import { Button } from "@/components/ui/button";
import { HedgehogLoader } from "@/components/ui/loader";

/* ============================================================================
   小工具（页面内私有；中文文案）
   ========================================================================== */

/** 请求桌面层打开登录窗口（登录窗口由桌面层统一管理）。 */
const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));

/** 401 判定：未登录 → “需要登录”状态。 */
const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

/** 时间显示：ISO 截取到秒、去 T。 */
const fmtAt = (s: string | null | undefined) =>
  s ? s.slice(0, 19).replace("T", " ") : "—";

/** 超长文本截断。 */
const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n)}…` : s);

/** run / loop 状态 → StatusBadge（状态保留色纪律）。 */
const RUN_STATUS_CN: Record<string, { kind: StatusKind; text: string }> = {
  completed: { kind: "good", text: "完成" },
  failed: { kind: "serious", text: "失败" },
  waiting_human: { kind: "warn", text: "等待人工" },
  running: { kind: "neutral", text: "运行中" },
  pending: { kind: "neutral", text: "待启动" },
  cancelled: { kind: "neutral", text: "已取消" },
};

function statusBadgeOf(status: string): ReactNode {
  const m = RUN_STATUS_CN[status] ?? { kind: "neutral" as StatusKind, text: status };
  return <StatusBadge kind={m.kind}>{m.text}</StatusBadge>;
}

/** Loop 停止原因中文映射。 */
const STOP_CN: Record<string, string> = {
  budget_rounds: "轮次预算超限",
  no_edge: "路由未定义",
  no_router: "缺少路由器",
};

/** Loop 决策中文映射与徽章语义。 */
const DECISION_CN: Record<string, string> = {
  next: "顺行",
  on_fail: "失败分支",
  feedback: "误差回流",
  human_gate: "人工门",
  terminal: "终点",
  no_edge: "无匹配路由",
};

function decisionBadge(d: string): ReactNode {
  const kind: StatusKind =
    d === "no_edge" ? "serious" : d === "feedback" || d === "human_gate" ? "warn" : "good";
  return <StatusBadge kind={kind}>{DECISION_CN[d] ?? d}</StatusBadge>;
}

/** 操作反馈条（成功 / 失败 / 提示）。 */
type Msg = { kind: "good" | "serious"; text: string };

function ActionMsg({ msg }: { msg: Msg | null }) {
  if (!msg) return null;
  return (
    <div className="flex items-center gap-2">
      <StatusBadge kind={msg.kind}>{msg.kind === "good" ? "操作成功" : "操作失败"}</StatusBadge>
      <p className="min-w-0 truncate text-xs text-text-secondary">{msg.text}</p>
    </div>
  );
}

/** 页内分区标题。 */
function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold text-text-primary">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/* ============================================================================
   页面
   ========================================================================== */

export default function Runs() {
  // GraphRun 列表
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsErr, setRunsErr] = useState<unknown>(null);
  const [runs401, setRuns401] = useState(false);
  // Loop v2 列表（该端点要求登录会话）
  const [loops, setLoops] = useState<LoopRunRow[]>([]);
  const [loopsLoading, setLoopsLoading] = useState(true);
  const [loopsErr, setLoopsErr] = useState<unknown>(null);
  const [loops401, setLoops401] = useState(false);
  // 详情与操作
  const [runDetail, setRunDetail] = useState<RunView | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loopDetail, setLoopDetail] = useState<LoopRunView | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsErr(null);
    setRuns401(false);
    try {
      setRuns((await fetchRuns()).runs);
    } catch (e) {
      if (is401(e)) setRuns401(true);
      else setRunsErr(e);
    } finally {
      setRunsLoading(false);
    }
  }, []);

  const loadLoops = useCallback(async () => {
    setLoopsLoading(true);
    setLoopsErr(null);
    setLoops401(false);
    try {
      setLoops((await fetchLoopRuns()).runs);
    } catch (e) {
      if (is401(e)) setLoops401(true);
      else setLoopsErr(e);
    } finally {
      setLoopsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
    void loadLoops();
  }, [loadRuns, loadLoops]);

  /* ---- mutation：可调即调 ---- */

  /** 上传照片 → 资产登记 → 启动 FMCG 级联图。 */
  async function inspect(file: File) {
    setBusy(true);
    setMsg(null);
    try {
      const asset = await fetchUploadAsset(file);
      const view = await fetchStartRun({
        graph_name: "fmcg_photo_inspection_v1",
        input: { photo_sha256: asset.sha256 },
        idempotency_key: `web-${asset.sha256}`,
      });
      setRunDetail(view);
      setMsg({ kind: "good", text: `照片 ${file.name} 已提交 FMCG 级联流程` });
      await loadRuns();
    } catch (e) {
      setMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  /** 启动 system_health_v1 健康图。 */
  async function runHealth() {
    setBusy(true);
    setMsg(null);
    try {
      const view = await fetchStartRun({ graph_name: "system_health_v1", input: {} });
      setRunDetail(view);
      setMsg({ kind: "good", text: "system_health_v1 已启动" });
      await loadRuns();
    } catch (e) {
      setMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setBusy(false);
    }
  }

  async function openRun(runId: string) {
    setMsg(null);
    setDetailLoading(true);
    setLoopDetail(null);
    try {
      setRunDetail(await fetchRun(runId));
    } catch (e) {
      setRunDetail(null);
      setMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setDetailLoading(false);
    }
  }

  /** GraphRun 人工门：批准 / 拒绝。 */
  async function decide(approved: boolean) {
    if (!runDetail) return;
    setBusy(true);
    setMsg(null);
    try {
      setRunDetail(await fetchApproveRun(runDetail.run.run_id, approved));
      setMsg({ kind: "good", text: approved ? "已批准人工门" : "已拒绝人工门" });
      await loadRuns();
    } catch (e) {
      setMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setBusy(false);
    }
  }

  async function openLoop(runId: string) {
    setMsg(null);
    setDetailLoading(true);
    setRunDetail(null);
    try {
      setLoopDetail(await fetchLoopRun(runId));
    } catch (e) {
      setLoopDetail(null);
      setMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setDetailLoading(false);
    }
  }

  /** Loop v2 人工门：批准并继续 / 拒绝（终态）。 */
  async function gate(approved: boolean) {
    if (!loopDetail) return;
    setBusy(true);
    setMsg(null);
    try {
      setLoopDetail(await fetchGateLoop(loopDetail.run_id, approved));
      setMsg({ kind: "good", text: approved ? "已批准，Loop 继续推进" : "已拒绝，Loop 进入终态" });
      await loadLoops();
    } catch (e) {
      setMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setBusy(false);
    }
  }

  /* ---- 列定义 ---- */

  const runCols: ApiTableCol<RunRow>[] = [
    {
      key: "run_id",
      label: "run",
      render: (r) => (
        <span className="font-mono text-xs text-text-secondary">{r.run_id.slice(0, 8)}…</span>
      ),
    },
    {
      key: "graph_name",
      label: "图",
      render: (r) => (
        <>
          {r.graph_name}
          <span className="text-text-secondary">@{r.graph_version}</span>
        </>
      ),
    },
    { key: "status", label: "状态", render: (r) => statusBadgeOf(r.status) },
    {
      key: "error",
      label: "错误",
      render: (r) =>
        r.error ? (
          <span className="text-xs text-text-secondary">{truncate(r.error, 40)}</span>
        ) : (
          <span className="text-text-secondary">—</span>
        ),
    },
    {
      key: "created_at",
      label: "创建时间",
      render: (r) => <span className="text-xs text-text-secondary">{fmtAt(r.created_at)}</span>,
    },
    {
      key: "ops",
      label: "操作",
      render: (r) => (
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-xs"
          onClick={() => void openRun(r.run_id)}
        >
          详情
        </Button>
      ),
    },
  ];

  const loopCols: ApiTableCol<LoopRunRow>[] = [
    {
      key: "run_id",
      label: "run",
      render: (r) => (
        <span className="font-mono text-xs text-text-secondary">{r.run_id.slice(0, 8)}…</span>
      ),
    },
    { key: "status", label: "状态", render: (r) => statusBadgeOf(r.status) },
    { key: "rounds_used", label: "轮次", align: "right", render: (r) => r.rounds_used ?? 0 },
    {
      key: "stop_reason",
      label: "停止原因",
      render: (r) => (
        <span className="text-xs text-text-secondary">
          {r.stop_reason ? (STOP_CN[r.stop_reason] ?? r.stop_reason) : "—"}
        </span>
      ),
    },
    {
      key: "waiting_for",
      label: "等待项 / 下一节点",
      render: (r) => (
        <span className="text-xs">
          {r.waiting_for ?? "—"}
          {r.next_node ? <span className="text-text-secondary"> → {r.next_node}</span> : null}
        </span>
      ),
    },
    { key: "cost_nodes", label: "成本（节点）", align: "right", render: (r) => r.cost_nodes ?? 0 },
    {
      key: "created_at",
      label: "创建时间",
      render: (r) => <span className="text-xs text-text-secondary">{fmtAt(r.created_at)}</span>,
    },
    {
      key: "ops",
      label: "操作",
      render: (r) => (
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-xs"
          onClick={() => void openLoop(r.run_id)}
        >
          详情
        </Button>
      ),
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="运行中心"
        desc="GraphRun 与 Loop v2 运行台账；人工门批准、轮次决策与成本全部留痕"
        aside={
          <>
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png"
              className="hidden"
              aria-label="识别照片输入"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void inspect(f);
              }}
            />
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
            >
              上传照片跑级联
            </Button>
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => void runHealth()}>
              运行 system_health_v1
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                void loadRuns();
                void loadLoops();
              }}
            >
              刷新
            </Button>
          </>
        }
      />
      <ActionMsg msg={msg} />

      {/* ---- GraphRun 运行列表 ---- */}
      <Section title={`GraphRun 运行（${runsLoading ? "…" : runs.length}）`}>
        {runs401 ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : (
          <ApiTable
            rows={runs}
            cols={runCols}
            loading={runsLoading}
            error={runsErr}
            onRetry={() => void loadRuns()}
            emptyText="暂无 Run：上传一张照片或运行 system_health_v1 开始第一条真实流程"
          />
        )}
      </Section>

      {/* ---- Loop v2 运行列表 ---- */}
      <Section title={`Loop v2 运行（${loopsLoading ? "…" : loops.length}）`}>
        {loops401 ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : (
          <ApiTable
            rows={loops}
            cols={loopCols}
            loading={loopsLoading}
            error={loopsErr}
            onRetry={() => void loadLoops()}
            emptyText="暂无 Loop v2 运行（照片→质量→人工→数据集→识别→误差回流）"
          />
        )}
      </Section>

      {/* ---- 详情面板 ---- */}
      {detailLoading && (
        <div className="flex justify-center py-6">
          <HedgehogLoader />
        </div>
      )}

      {runDetail && !detailLoading && (
        <Section
          title={`Run 详情 ${runDetail.run.run_id.slice(0, 8)}…（${runDetail.run.graph_name}@${runDetail.run.graph_version}）`}
        >
          <KV
            items={[
              { label: "状态", value: statusBadgeOf(runDetail.run.status) },
              ...(runDetail.run.error
                ? [{ label: "错误", value: runDetail.run.error }]
                : []),
              { label: "创建时间", value: fmtAt(runDetail.run.created_at) },
              { label: "更新时间", value: fmtAt(runDetail.run.updated_at) },
            ]}
          />
          {runDetail.run.status === "waiting_human" && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-secondary">该 Run 停在人工门：</span>
              <Button size="sm" disabled={busy} onClick={() => void decide(true)}>
                批准人工门
              </Button>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => void decide(false)}>
                拒绝
              </Button>
            </div>
          )}
          <ApiTable
            rows={runDetail.nodes}
            rowKey={(n) => `${n.node_name}#${n.seq}-${n.attempt}`}
            cols={[
              { key: "seq", label: "#", align: "right" },
              { key: "node_name", label: "节点" },
              { key: "attempt", label: "尝试", align: "right" },
              { key: "status", label: "状态", render: (n) => statusBadgeOf(n.status) },
              {
                key: "started_at",
                label: "开始",
                render: (n) => (
                  <span className="text-xs text-text-secondary">{fmtAt(n.started_at)}</span>
                ),
              },
              {
                key: "ended_at",
                label: "结束",
                render: (n) => (
                  <span className="text-xs text-text-secondary">{fmtAt(n.ended_at)}</span>
                ),
              },
              {
                key: "error",
                label: "错误",
                render: (n) =>
                  n.error ? (
                    <span className="text-xs text-text-secondary">{truncate(n.error, 40)}</span>
                  ) : (
                    <span className="text-text-secondary">—</span>
                  ),
              },
            ]}
            emptyText="暂无节点记录"
          />
          {runDetail.evidence.length > 0 && (
            <ul className="space-y-1 rounded-md border border-border bg-background px-3 py-2">
              {runDetail.evidence.map((ev) => (
                <li key={ev.evidence_id} className="text-xs text-text-secondary">
                  证据 <span className="text-text-primary">{ev.kind}</span> ·{" "}
                  <span className="font-mono">{ev.evidence_id.slice(0, 8)}…</span>
                </li>
              ))}
            </ul>
          )}
          {runDetail.run.output_json != null && (
            <pre className="max-h-48 overflow-auto rounded-md border border-border bg-surface p-2.5 font-mono text-xs text-text-secondary">
              {JSON.stringify(runDetail.run.output_json, null, 2)}
            </pre>
          )}
        </Section>
      )}

      {loopDetail && !detailLoading && (
        <Section
          title={`Loop 详情 ${loopDetail.run_id.slice(0, 8)}…（轮次 ${loopDetail.rounds_used ?? 0}${
            loopDetail.stop_reason
              ? `，停止：${STOP_CN[loopDetail.stop_reason] ?? loopDetail.stop_reason}`
              : ""
          }）`}
        >
          <KV
            items={[
              { label: "状态", value: statusBadgeOf(loopDetail.status) },
              ...(loopDetail.error ? [{ label: "错误", value: loopDetail.error }] : []),
              ...(loopDetail.cost_detail
                ? [
                    {
                      label: "成本",
                      value: `节点执行 ${loopDetail.cost_detail.node_executions} 次 · 质量评估 ${loopDetail.cost_detail.quality_evals} 轮`,
                    },
                  ]
                : []),
            ]}
          />
          {loopDetail.waiting_for && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-secondary">
                等待人工：{loopDetail.waiting_for}
              </span>
              <Button size="sm" disabled={busy} onClick={() => void gate(true)}>
                批准并继续
              </Button>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => void gate(false)}>
                拒绝（终态）
              </Button>
            </div>
          )}
          <ApiTable
            rows={loopDetail.trail}
            rowKey={(t, i) => `${t.round}-${t.node}-${i}`}
            cols={[
              { key: "round", label: "轮次", align: "right" },
              { key: "node", label: "节点" },
              { key: "decision", label: "决策", render: (t) => decisionBadge(t.decision) },
              {
                key: "reason",
                label: "决策原因",
                render: (t) => <span className="text-xs text-text-secondary">{t.reason}</span>,
              },
              { key: "next", label: "下一节点", render: (t) => t.next ?? "—" },
            ]}
            emptyText="暂无决策轨迹"
          />
        </Section>
      )}
    </div>
  );
}
