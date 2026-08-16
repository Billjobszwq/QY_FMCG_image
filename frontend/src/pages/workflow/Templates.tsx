/**
 * 工作流模板（/workflow/templates）—— 定义列表 + 模板实例化 + 节点库（瘦版重实现）。
 *
 * 数据源（同源 /api/v1，全部真实数据，禁止样本）：
 * —— GET  /api/v1/workflows（定义列表：生命周期 draft→lint→simulate→approve→publish）
 * —— GET  /api/v1/workflows/node-library（节点类型 / 命令节点 / 模板，fail-closed）
 * —— POST /api/v1/workflows（template_id 实例化为 draft）
 * —— POST /api/v1/workflows/{id}/{lint|simulate|approve|publish|new-version}
 *
 * 风险纪律：deprecate 为高风险操作，本页仅保留 UI 入口并标注，不直连后端。
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  ApiError,
  fetchCreateWorkflowDraft,
  fetchNodeLibrary,
  fetchWorkflowAction,
  fetchWorkflows,
} from "@/lib/api";
import type { WorkflowDefinition } from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";
import { Button } from "@/components/ui/button";
import { HedgehogMascot } from "@/components/ui/mascot";

/* ============================================================================
   小工具（页面内私有）
   ========================================================================== */

/** 请求桌面层打开登录窗口。 */
const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));

const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

const fmtAt = (s: string | null | undefined) =>
  s ? s.slice(0, 19).replace("T", " ") : "—";

/** 生命周期状态 → StatusBadge。 */
const LIFECYCLE_CN: Record<string, { kind: StatusKind; text: string }> = {
  draft: { kind: "neutral", text: "草稿" },
  linted: { kind: "neutral", text: "已校验" },
  simulated: { kind: "neutral", text: "已模拟" },
  approved: { kind: "warn", text: "已批准" },
  published: { kind: "good", text: "已发布" },
  deprecated: { kind: "serious", text: "已弃用" },
};

function lifecycleBadge(status: string): ReactNode {
  const m = LIFECYCLE_CN[status] ?? { kind: "neutral" as StatusKind, text: status };
  return <StatusBadge kind={m.kind}>{m.text}</StatusBadge>;
}

/** 各状态的“下一步”动作（生命周期单向前进）。 */
const NEXT_STEP: Record<
  string,
  { label: string; action: "lint" | "simulate" | "approve" | "publish" }
> = {
  draft: { label: "校验", action: "lint" },
  linted: { label: "模拟", action: "simulate" },
  simulated: { label: "批准", action: "approve" },
  approved: { label: "发布", action: "publish" },
};

type Msg = { kind: "good" | "serious" | "neutral"; text: string };

function ActionMsg({ msg }: { msg: Msg | null }) {
  if (!msg) return null;
  const label = msg.kind === "good" ? "操作成功" : msg.kind === "serious" ? "操作失败" : "提示";
  return (
    <div className="flex items-center gap-2">
      <StatusBadge kind={msg.kind}>{label}</StatusBadge>
      <p className="min-w-0 truncate text-xs text-text-secondary">{msg.text}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-[13px] font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

/* ============================================================================
   页面
   ========================================================================== */

export default function Templates() {
  const [defs, setDefs] = useState<WorkflowDefinition[]>([]);
  const [defsLoading, setDefsLoading] = useState(true);
  const [defsErr, setDefsErr] = useState<unknown>(null);
  const [defs401, setDefs401] = useState(false);

  const [lib, setLib] = useState<Awaited<ReturnType<typeof fetchNodeLibrary>> | null>(null);
  const [libErr, setLibErr] = useState<unknown>(null);
  const [lib401, setLib401] = useState(false);

  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg | null>(null);

  const loadDefs = useCallback(async () => {
    setDefsLoading(true);
    setDefsErr(null);
    setDefs401(false);
    try {
      const d = await fetchWorkflows();
      // 最近更新的排前面，便于定位当前工作对象
      setDefs([...d.definitions].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
    } catch (e) {
      if (is401(e)) setDefs401(true);
      else setDefsErr(e);
    } finally {
      setDefsLoading(false);
    }
  }, []);

  const loadLib = useCallback(async () => {
    setLibErr(null);
    setLib401(false);
    try {
      setLib(await fetchNodeLibrary());
    } catch (e) {
      if (is401(e)) setLib401(true);
      else setLibErr(e);
    }
  }, []);

  useEffect(() => {
    void loadDefs();
    void loadLib();
  }, [loadDefs, loadLib]);

  /** 生命周期动作（lint / simulate / approve / publish / new-version）：可调即调。 */
  async function act(
    d: WorkflowDefinition,
    action: "lint" | "simulate" | "approve" | "publish" | "new-version",
    label: string,
  ) {
    if (busy) return;
    setBusy(true);
    setMsg(null);
    try {
      await fetchWorkflowAction(d.definition_id, action);
      setMsg({ kind: "good", text: `${d.name}：${label}完成` });
      await loadDefs();
    } catch (e) {
      setMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setBusy(false);
    }
  }

  /** 模板实例化为 draft（仍需 lint / 模拟 / 人工批准后发布）。 */
  async function instantiate(templateId: string) {
    if (busy) return;
    setBusy(true);
    setMsg(null);
    try {
      const out = await fetchCreateWorkflowDraft({ template_id: templateId });
      setMsg({
        kind: "good",
        text: `已实例化为 draft：${out.definition.definition_id}（仍需校验与人工批准后发布）`,
      });
      await loadDefs();
    } catch (e) {
      setMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setBusy(false);
    }
  }

  const defCols: ApiTableCol<WorkflowDefinition>[] = [
    { key: "name", label: "名称" },
    {
      key: "definition_id",
      label: "ID",
      render: (d) => (
        <span className="font-mono text-xs text-text-secondary">{d.definition_id}</span>
      ),
    },
    { key: "version", label: "版本", align: "right", render: (d) => `v${d.version}` },
    { key: "status", label: "状态", render: (d) => lifecycleBadge(d.status) },
    {
      key: "lint_report",
      label: "校验",
      render: (d) => {
        const report = d.lint_report ?? [];
        const errors = report.filter((i) => i.level === "error").length;
        const warns = report.length - errors;
        if (errors > 0) return <StatusBadge kind="serious">{errors} 错误</StatusBadge>;
        if (warns > 0) return <StatusBadge kind="warn">{warns} 提示</StatusBadge>;
        return <span className="text-text-secondary">—</span>;
      },
    },
    {
      key: "updated_at",
      label: "更新",
      render: (d) => <span className="text-xs text-text-secondary">{fmtAt(d.updated_at)}</span>,
    },
    {
      key: "ops",
      label: "操作",
      render: (d) => (
        <div className="flex items-center gap-1">
          {NEXT_STEP[d.status] && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-xs"
              disabled={busy}
              onClick={() => void act(d, NEXT_STEP[d.status].action, NEXT_STEP[d.status].label)}
            >
              {NEXT_STEP[d.status].label}
            </Button>
          )}
          {d.status !== "draft" && d.status !== "deprecated" && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-xs"
              disabled={busy}
              onClick={() => void act(d, "new-version", "新版本")}
            >
              新版本
            </Button>
          )}
          {d.status !== "deprecated" && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-xs"
              title="高风险操作：本页仅保留入口，不直连后端"
              onClick={() =>
                setMsg({
                  kind: "neutral",
                  text: "弃用为高风险操作：本页仅保留 UI 入口，请通过 API/CLI 执行并留痕",
                })
              }
            >
              弃用*
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="工作流模板"
        desc="模板实例化为 draft；生命周期 draft→校验→模拟→人工批准→发布，发布必须人工批准、修改必须新版本"
        aside={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void loadDefs();
              void loadLib();
            }}
          >
            刷新
          </Button>
        }
      />
      <ActionMsg msg={msg} />

      {/* ---- 模板库（node-library.templates） ---- */}
      <Section title="模板库">
        {lib401 ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : libErr ? (
          <ErrorState
            message={libErr instanceof Error ? libErr.message : undefined}
            onRetry={() => void loadLib()}
          />
        ) : !lib ? (
          <p className="text-xs text-text-secondary">模板库加载中…</p>
        ) : lib.templates.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 rounded-md border border-border bg-background py-6">
            <HedgehogMascot className="h-16 w-auto" />
            <p className="text-xs text-text-secondary">暂无模板</p>
          </div>
        ) : (
          <div className="space-y-2">
            {lib.templates.map((t) => (
              <div
                key={t.template_id}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="text-[13px] text-text-primary">{t.name}</p>
                  <p className="mt-0.5 font-mono text-xs text-text-secondary">{t.template_id}</p>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() => void instantiate(t.template_id)}
                >
                  实例化为 draft
                </Button>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* ---- 工作流定义列表 ---- */}
      <Section title={`工作流定义（${defsLoading ? "…" : defs.length}）`}>
        {defs401 ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : (
          <ApiTable
            rows={defs}
            cols={defCols}
            rowKey={(d) => `${d.definition_id}@${d.version}`}
            loading={defsLoading}
            error={defsErr}
            onRetry={() => void loadDefs()}
            emptyText="暂无工作流定义：从上方模板实例化为 draft 开始"
          />
        )}
      </Section>

      {/* ---- 节点库（来自已注册 Capability / Gateway 命令，fail-closed） ---- */}
      <Section title="节点库">
        {lib ? (
          <div className="space-y-2">
            <p className="text-xs text-text-secondary">
              节点类型：
              <span className="text-text-primary">{lib.node_types.join(" · ") || "—"}</span>
            </p>
            <ApiTable
              rows={lib.command_nodes}
              rowKey={(c) => `${c.node_type}:${c.capability}`}
              cols={[
                { key: "node_type", label: "节点类型" },
                {
                  key: "capability",
                  label: "capability",
                  render: (c) => (
                    <span className="font-mono text-xs text-text-secondary">{c.capability}</span>
                  ),
                },
                { key: "module", label: "模块" },
                { key: "kind", label: "kind" },
              ]}
              emptyText="暂无可用命令 / 模型节点（fail-closed）"
            />
          </div>
        ) : libErr || lib401 ? (
          <p className="text-xs text-text-secondary">节点库随模板库加载，暂不可用。</p>
        ) : (
          <p className="text-xs text-text-secondary">节点库加载中…</p>
        )}
      </Section>
    </div>
  );
}
