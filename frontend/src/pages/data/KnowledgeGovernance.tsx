/**
 * 知识治理（/data/knowledge）—— 知识/记忆/Skill 检索 + 治理告警。
 *
 * 数据源（同源 /api/v1，全部真实数据，禁止样本）：
 * —— GET /api/v1/cognition/knowledge/search  知识检索（ACL 前置过滤）
 * —— GET /api/v1/cognition/memory/search     记忆检索（L2/L3）
 * —— GET /api/v1/cognition/skills/search     Skill 发现（命中≠可执行）
 * —— GET /api/v1/cognition/skills/{id}/can-execute  执行面独立判定
 * —— GET /api/v1/governance/alerts           治理告警
 *
 * 只读：发布/废止等高风险写操作走审批队列，不在本页直连。
 */
import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import {
  ApiError,
  fetchGovernanceAlerts,
  fetchKnowledgeSearch,
  fetchMemorySearch,
  fetchSkillCanExecute,
  fetchSkillsSearch,
} from "@/lib/api";
import type { CognitionCandidate, CognitionSearchResult } from "@/lib/api";
import {
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import { Button } from "@/components/ui/button";

const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));
const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

type Tab = "knowledge" | "memory_l2" | "memory_l3" | "skill";

const TAB_LABEL: Record<Tab, string> = {
  knowledge: "知识",
  memory_l2: "记忆 L2（案例）",
  memory_l3: "记忆 L3（方法论）",
  skill: "Skill",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-[13px] font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

function CandidateCard({ c }: { c: CognitionCandidate }) {
  const [expanded, setExpanded] = useState(false);
  const lex = c.score_breakdown.lexical;
  const dense = c.score_breakdown.dense;
  return (
    <li className="rounded-md border border-border bg-bg-secondary p-2.5 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[13px] text-text-primary">{c.target_id}</span>
        <StatusBadge kind="neutral">{c.target_kind}</StatusBadge>
        <span className="text-xs text-text-secondary">v{c.version}</span>
        <span className="text-xs text-text-secondary">
          分：lexical {lex == null ? "—" : lex.toFixed(3)}
          {dense != null ? ` · dense ${dense.toFixed(3)}` : ""}
        </span>
      </div>
      {c.summary && <p className="text-[13px] text-text-primary">{c.summary}</p>}
      {c.spans.length > 0 && (
        <button
          className="text-xs text-accent hover:underline"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "收起证据片段" : `证据片段（${c.spans.length}）`}
        </button>
      )}
      {expanded &&
        c.spans.map((s) => (
          <blockquote
            key={s.span_id}
            className="border-l-2 border-accent pl-2 text-xs text-text-secondary"
          >
            {s.normalized_quote || "（空片段）"}
            <span className="block font-mono mt-0.5">
              span={s.span_id}
              {typeof s.locator.char_start === "number" &&
                ` · char ${s.locator.char_start}–${s.locator.char_end}`}
            </span>
          </blockquote>
        ))}
    </li>
  );
}

export default function KnowledgeGovernance() {
  const [tab, setTab] = useState<Tab>("knowledge");
  const [q, setQ] = useState("");
  const [result, setResult] = useState<CognitionSearchResult | null>(null);
  const [skillExec, setSkillExec] = useState<{ id: string; allowed: boolean; gate: boolean } | null>(null);
  const [alerts, setAlerts] = useState<Array<Record<string, unknown>>>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [is401State, setIs401] = useState(false);

  const fail = useCallback((e: unknown) => {
    if (is401(e)) setIs401(true);
    else setErr(e);
  }, []);

  const search = useCallback(async () => {
    setBusy(true);
    setErr(null);
    setIs401(false);
    setSkillExec(null);
    try {
      let r: CognitionSearchResult;
      if (tab === "knowledge") r = await fetchKnowledgeSearch(q);
      else if (tab === "skill") r = await fetchSkillsSearch(q);
      else r = await fetchMemorySearch(q, tab);
      setResult(r);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [q, tab, fail]);

  const checkExec = useCallback(async (skillId: string) => {
    try {
      const d = await fetchSkillCanExecute(skillId);
      setSkillExec({ id: skillId, allowed: d.allowed, gate: d.requires_human_gate });
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  const loadAlerts = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      setAlerts((await fetchGovernanceAlerts()).alerts);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [fail]);

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="知识治理"
        desc="知识/记忆/Skill 联邦检索（ACL 前置过滤）+ 治理告警；命中≠可执行"
        aside={
          <Button variant="secondary" size="sm" onClick={() => void loadAlerts()}>
            刷新告警
          </Button>
        }
      />

      {/* ---- 检索 ---- */}
      <Section title="检索">
        <div className="flex gap-1.5 mb-2">
          {(Object.keys(TAB_LABEL) as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-2.5 py-1 rounded-md text-xs border ${
                tab === t
                  ? "border-accent text-accent bg-bg-secondary"
                  : "border-border text-text-secondary"
              }`}
            >
              {TAB_LABEL[t]}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-border bg-bg-secondary px-3 py-1.5 text-[13px] text-text-primary placeholder:text-text-secondary"
            placeholder={`检索${TAB_LABEL[tab]}…`}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void search();
            }}
          />
          <Button variant="primary" size="sm" onClick={() => void search()} disabled={busy}>
            {busy ? "检索中…" : "检索"}
          </Button>
        </div>
      </Section>

      {is401State && <NeedLoginState onOpenLogin={openLogin} />}
      {err != null && !is401State && (
        <ErrorState message={errorMessageOf(err)} onRetry={() => void search()} />
      )}

      {/* ---- 检索结果 ---- */}
      {result && (
        <Section title={`结果（${result.candidates.length}）`}>
          {result.degraded && (
            <p className="text-xs text-warn">
              degraded：稠密向量不可用，仅词法检索（不返回假向量）。
            </p>
          )}
          {result.candidates.length === 0 ? (
            <p className="text-[13px] text-text-secondary">无命中（ACL/生命周期过滤后）。</p>
          ) : (
            <ul className="space-y-2">
              {result.candidates.map((c) => (
                <li key={`${c.target_kind}:${c.target_id}`}>
                  <CandidateCard c={c} />
                  {c.target_kind === "skill" && (
                    <div className="mt-1 flex items-center gap-2">
                      <Button variant="secondary" size="sm"
                        onClick={() => void checkExec(c.target_id)}>
                        校验可执行性
                      </Button>
                      {skillExec?.id === c.target_id && (
                        <StatusBadge kind={skillExec.allowed ? "good" : skillExec.gate ? "warn" : "serious"}>
                          {skillExec.allowed ? "可执行" : skillExec.gate ? "需人工 gate" : "不可执行"}
                        </StatusBadge>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {/* ---- 治理告警 ---- */}
      <Section title={`治理告警（${alerts.length}）`}>
        {alerts.length === 0 ? (
          <p className="text-[13px] text-text-secondary">暂无告警。</p>
        ) : (
          <ul className="space-y-1.5">
            {alerts.map((a, i) => (
              <li key={i} className="rounded-md border border-border bg-bg-secondary p-2.5">
                <div className="flex items-center gap-2">
                  <StatusBadge kind={a.severity === "critical" ? "serious" : "warn"}>
                    {String(a.severity)}
                  </StatusBadge>
                  <span className="text-xs text-text-secondary">
                    {String(a.status)} · {String(a.created_at)}
                  </span>
                </div>
                <p className="text-[13px] text-text-primary mt-1">{String(a.content)}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
