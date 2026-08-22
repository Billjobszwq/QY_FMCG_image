/**
 * 研究工作台（/research/workbench）—— Research RAG 受控入口。
 *
 * 数据源（同源 /api/v1，全部真实数据，禁止样本）：
 * —— POST /api/v1/research/runs              启动研究（lookup/case/...）
 * —— GET  /api/v1/research/runs/{id}         状态/预算/停止原因
 * —— GET  /api/v1/research/runs/{id}/claims  Claim 列表
 * —— GET  /api/v1/research/runs/{id}/citations 引证核验（gate_ok）
 * —— POST .../resume | /cancel | /decide-conflict | /synthesize
 *
 * 只读+受控写：启动/恢复/取消/裁决/综合均走受控端点（CSRF）。
 */
import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import {
  ApiError,
  fetchResearchCancel,
  fetchResearchCitations,
  fetchResearchClaims,
  fetchResearchDecideConflict,
  fetchResearchResume,
  fetchResearchStart,
  fetchResearchStatus,
  fetchResearchSynthesize,
} from "@/lib/api";
import type {
  CitationVerdict,
  ResearchClaim,
  ResearchReport,
  ResearchRun,
} from "@/lib/api";
import {
  ErrorState,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { StatusKind } from "@/components/data";
import { Button } from "@/components/ui/button";

const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));
const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

/** run 状态 → StatusBadge。 */
const RUN_STATUS: Record<string, { kind: StatusKind; text: string }> = {
  planned: { kind: "neutral", text: "已计划" },
  running: { kind: "neutral", text: "运行中" },
  waiting_human: { kind: "warn", text: "等待人工" },
  succeeded: { kind: "good", text: "成功" },
  failed: { kind: "serious", text: "失败" },
  cancelled: { kind: "neutral", text: "已取消" },
};

function runStatusBadge(status: string): ReactNode {
  const m = RUN_STATUS[status] ?? { kind: "neutral" as StatusKind, text: status };
  return <StatusBadge kind={m.kind}>{m.text}</StatusBadge>;
}

const CLAIM_SUPPORT: Record<string, { kind: StatusKind; text: string }> = {
  supported: { kind: "good", text: "有证据" },
  partially_supported: { kind: "warn", text: "部分证据" },
  contradicted: { kind: "serious", text: "存在反证" },
  unsupported: { kind: "serious", text: "无证据" },
};

const VERDICT_CN: Record<string, string> = {
  pass: "通过",
  narrow: "需收窄",
  relabel: "需改标",
  remove: "移除",
  research_more: "需补研究",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-[13px] font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

export default function ResearchWorkbench() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("lookup");
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [claims, setClaims] = useState<ResearchClaim[]>([]);
  const [verdicts, setVerdicts] = useState<CitationVerdict[]>([]);
  const [gateOk, setGateOk] = useState<boolean | null>(null);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [is401State, setIs401] = useState(false);

  const fail = useCallback((e: unknown) => {
    if (is401(e)) setIs401(true);
    else setErr(e);
  }, []);

  const refresh = useCallback(async (runId: string) => {
    try {
      const r = await fetchResearchStatus(runId);
      setRun(r);
      const [cl, ci] = await Promise.all([
        fetchResearchClaims(runId),
        fetchResearchCitations(runId),
      ]);
      setClaims(cl.claims);
      setVerdicts(ci.verdicts);
      setGateOk(ci.gate_ok);
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  const start = useCallback(async () => {
    if (!question.trim()) return;
    setBusy(true);
    setErr(null);
    setIs401(false);
    setReport(null);
    try {
      const r = await fetchResearchStart({ question: question.trim(), mode });
      setRun(r);
      await refresh(r.research_run_id);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [question, mode, refresh, fail]);

  const act = useCallback(
    async (fn: (id: string) => Promise<ResearchRun>) => {
      if (!run) return;
      setBusy(true);
      setErr(null);
      try {
        const r = await fn(run.research_run_id);
        setRun(r);
        await refresh(run.research_run_id);
      } catch (e) {
        fail(e);
      } finally {
        setBusy(false);
      }
    },
    [run, refresh, fail],
  );

  const synthesize = useCallback(async () => {
    if (!run) return;
    setBusy(true);
    setErr(null);
    try {
      setReport(await fetchResearchSynthesize(run.research_run_id));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [run, fail]);

  const verdictOf = (claimId: string) =>
    verdicts.find((v) => v.claim_id === claimId);

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="研究工作台"
        desc="Research RAG：多轮检索、证据引证、冲突人工裁决、证据不足时拒答（abstain）"
      />

      {/* ---- 启动 ---- */}
      <Section title="发起研究">
        <div className="flex gap-2 items-center">
          <input
            className="flex-1 rounded-md border border-border bg-bg-secondary px-3 py-1.5 text-[13px] text-text-primary placeholder:text-text-secondary"
            placeholder="输入研究问题，例如：差旅报销的机票上限是多少？"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <select
            className="rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-[13px] text-text-primary"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="lookup">lookup（查规则）</option>
            <option value="case_analysis">case_analysis（查案例）</option>
            <option value="methodology">methodology（查方法）</option>
            <option value="deep_research">deep_research（深研究）</option>
          </select>
          <Button variant="primary" size="sm" onClick={() => void start()} disabled={busy}>
            {busy ? "运行中…" : "启动"}
          </Button>
        </div>
      </Section>

      {is401State && <NeedLoginState onOpenLogin={openLogin} />}
      {err != null && !is401State && (
        <ErrorState message={errorMessageOf(err)} onRetry={() => void start()} />
      )}

      {/* ---- 运行状态 ---- */}
      {run && (
        <Section title="运行状态">
          <KV
            items={[
              { label: "问题", value: run.question },
              { label: "模式", value: run.mode },
              { label: "状态", value: run.status },
              { label: "停止原因", value: run.stop_reason ?? "—" },
              {
                label: "Scope（服务端固化）",
                value:
                  `customer=${run.customer_id || "平台级"} · project=` +
                  `${run.project_id || "—"} · ${run.data_scope ?? "operational"}`,
              },
              {
                label: "查询消耗",
                value: `${run.consumed?.queries ?? 0} / ${run.budget?.max_queries ?? "—"}`,
              },
              {
                label: "迭代",
                value: `${(run.state as Record<string, number>)?.iteration ?? 0} / ${run.budget?.max_iterations ?? "—"}`,
              },
            ]}
          />
          {Boolean((run.state as Record<string, unknown>)?.planner_degraded) && (
            <p className="text-xs text-text-secondary" data-testid="planner-degraded">
              ⚠ planner 不可用：deep_research 已降级（abstain），未用单问题冒充规划。
            </p>
          )}
          {typeof (run.state as Record<string, unknown>)?.stop_rule === "string" && (
            <p className="text-xs text-text-secondary" data-testid="stop-rule">
              停止规则：{String((run.state as Record<string, unknown>)?.stop_rule)}
            </p>
          )}
          <div className="flex gap-2 items-center flex-wrap">
            <span>{runStatusBadge(run.status)}</span>
            {run.status === "waiting_human" && (
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() =>
                  void act((id) => fetchResearchDecideConflict(id, "人工裁决：以权威来源为准"))
                }
              >
                裁决冲突
              </Button>
            )}
            {(run.status === "failed" || run.status === "running") && (
              <Button variant="secondary" size="sm" disabled={busy}
                onClick={() => void act(fetchResearchResume)}>
                恢复
              </Button>
            )}
            {run.status !== "succeeded" && run.status !== "cancelled" && (
              <Button variant="secondary" size="sm" disabled={busy}
                onClick={() => void act(fetchResearchCancel)}>
                取消
              </Button>
            )}
            {run.status === "succeeded" && (
              <Button variant="primary" size="sm" disabled={busy}
                onClick={() => void synthesize()}>
                综合报告（过引证门）
              </Button>
            )}
          </div>
          {gateOk != null && (
            <p className="text-xs text-text-secondary">
              引证门：{gateOk ? "通过（gate_ok）" : "未通过（存在高重要性无证据/冲突 Claim）"}
            </p>
          )}
        </Section>
      )}

      {/* ---- 计划与子问题（deep_research typed plan / R2-06） ---- */}
      {run &&
        Array.isArray(
          ((run.state as Record<string, unknown>)?.plan as
            | { subquestions?: unknown[] }
            | undefined)?.subquestions,
        ) && (
          <Section
            title={`计划与子问题（${
              (
                (run.state as Record<string, unknown>)?.plan as {
                  subquestions: Array<Record<string, unknown>>;
                }
              ).subquestions.length
            }）`}
          >
            <ul className="space-y-1">
              {(
                (run.state as Record<string, unknown>)?.plan as {
                  subquestions: Array<Record<string, unknown>>;
                }
              ).subquestions.map((sq) => (
                <li
                  key={String(sq.sq_id)}
                  className="text-[13px] text-text-primary"
                  data-testid="subquestion"
                >
                  [{String(sq.kind ?? "primary")}] {String(sq.text)}
                  <span className="text-xs text-text-secondary">
                    {" "}
                    · 依赖 {((sq.depends_on as string[]) || []).join(",") || "—"}
                    {" "}· 停止：{String(sq.stop_condition ?? "—")}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

      {/* ---- 冲突（仅互斥命题；多来源≠冲突 / R2-06） ---- */}
      {run &&
        Array.isArray((run.state as Record<string, unknown>)?.conflicts) &&
        ((run.state as Record<string, unknown>)?.conflicts as unknown[])
          .length > 0 && (
          <Section title="冲突（需人工裁决）">
            <ul className="space-y-1">
              {(
                (run.state as Record<string, unknown>)?.conflicts as Array<
                  Record<string, unknown>
                >
              ).map((c, i) => (
                <li key={i} className="text-[13px] text-text-primary"
                    data-testid="conflict">
                  命题「{String(c.proposition)}」取值互斥：
                  {((c.values as number[]) || []).join(" / ")}
                  {String(c.unit ?? "")}
                  <span className="text-xs text-text-secondary">
                    {" "}
                    · 来源 {((c.sources as string[]) || []).join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

      {/* ---- Claims ---- */}
      {run && claims.length > 0 && (
        <Section title={`Claims（${claims.length}）`}>
          <ul className="space-y-1.5">
            {claims.map((c) => {
              const v = verdictOf(c.claim_id);
              const sup = CLAIM_SUPPORT[c.support_status] ?? {
                kind: "neutral" as StatusKind,
                text: c.support_status,
              };
              return (
                <li key={c.claim_id}
                  className="rounded-md border border-border bg-bg-secondary p-2.5 space-y-1">
                  <div className="flex items-center gap-2">
                    <StatusBadge kind={sup.kind}>{sup.text}</StatusBadge>
                    <span className="text-xs text-text-secondary">
                      {c.claim_type} · {c.importance} · 置信 {c.confidence.toFixed(2)}
                    </span>
                    {v && (
                      <span className="text-xs text-text-secondary">
                        核验：{VERDICT_CN[v.verdict] ?? v.verdict}
                      </span>
                    )}
                  </div>
                  <p className="text-[13px] text-text-primary">{c.text}</p>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {/* ---- 综合报告 ---- */}
      {report && (
        <Section title="综合报告">
          {report.abstain ? (
            <p className="text-[13px] text-text-secondary">
              证据不足，系统拒绝给出结论（abstain）。不编造。
            </p>
          ) : (
            <ul className="space-y-1">
              {report.claims.map((c) => (
                <li key={c.claim_id} className="text-[13px] text-text-primary">
                  [{c.claim_type}] {c.text}
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-text-secondary">
            引证 {report.citations.length} 条 · report_id=
            <span className="font-mono">{report.report_id}</span>
          </p>
          {report.citations.length > 0 && (
            <ul className="space-y-0.5" data-testid="citation-locators">
              {report.citations.map((c, i) => (
                <li key={i} className="text-xs text-text-secondary font-mono">
                  {c.claim_id} ← span {c.span_id}（{c.relation}）
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </div>
  );
}
