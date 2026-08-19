/**
 * 主管 Agent · 命令审批（/agent/commands，主管 Agent 组）。
 *
 * 数据源（同源 /api，全部真实数据，禁止样本）：
 * —— GET  /api/v1/workitems?projection=current（fetchWorkItems：统一任务中心
 *    投影；本页取「待批准」条目 stage=approval / kind 含 approval，
 *    与 web 主管工作台同一过滤口径——后端对 Agent 命令不提供独立列表
 *    端点，命令计数只随主管对话回答返回）
 * —— POST /api/agent/v1/commands/{id}/approve（fetchApproveAgentCommand）
 * —— POST /api/agent/v1/commands/{id}/reject （fetchRejectAgentCommand）
 *
 * 审计留痕：批准 / 拒绝均由服务端持久化到 agent_command_v1
 * （status + decided_by + decided_at，身份取登录会话），批准后领域执行
 * 失败会改记 approved_failed，不冒充成功。
 *
 * 数据红线：401 → NeedLoginState；网络错误 → ErrorState；加载中 = 刺猬。
 */
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  fetchApproveAgentCommand,
  fetchRejectAgentCommand,
  fetchWorkItems,
} from "@/lib/api";
import type { WorkItem } from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";
import { Button } from "@/components/ui/button";

/** 请求桌面层打开登录窗口（与既有页面同源约定）。 */
const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));

const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

/** 与 web 主管工作台同一口径：需要批准的条目。 */
const isApproval = (w: WorkItem) =>
  w.stage === "approval" || w.kind.includes("approval");

const str = (v: unknown) => (typeof v === "string" && v ? v : "");

type Msg = { kind: "good" | "serious"; text: string };

function ActionMsg({ msg }: { msg: Msg | null }) {
  if (!msg) return null;
  return (
    <div className="flex items-center gap-2">
      <StatusBadge kind={msg.kind}>
        {msg.kind === "good" ? "操作成功" : "操作失败"}
      </StatusBadge>
      <p className="min-w-0 truncate text-xs text-text-secondary">{msg.text}</p>
    </div>
  );
}

export default function AgentCommands() {
  const [items, setItems] = useState<WorkItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState<unknown>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setListErr(null);
    setNeedLogin(false);
    try {
      const d = await fetchWorkItems("current");
      setItems(d.items.filter(isApproval));
    } catch (e) {
      setItems(null);
      if (is401(e)) setNeedLogin(true);
      else setListErr(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** 批准 Agent 命令（仅 subject_type=agent_command 的行可行）。 */
  async function approve(w: WorkItem) {
    const commandId = str(w.detail?.subject_id);
    if (!commandId || busyId) return;
    setBusyId(w.id);
    setMsg(null);
    try {
      const d = await fetchApproveAgentCommand(commandId);
      const taskNote = d?.execution?.task_id ? `，已创建任务 ${d.execution.task_id}` : "";
      setMsg({ kind: "good", text: `命令 ${commandId} 已批准${taskNote}` });
      await load();
    } catch (err) {
      if (is401(err)) setNeedLogin(true);
      else setMsg({ kind: "serious", text: errorMessageOf(err) });
    } finally {
      setBusyId(null);
    }
  }

  /** 拒绝 Agent 命令（同样落服务端留痕）。 */
  async function reject(w: WorkItem) {
    const commandId = str(w.detail?.subject_id);
    if (!commandId || busyId) return;
    setBusyId(w.id);
    setMsg(null);
    try {
      await fetchRejectAgentCommand(commandId);
      setMsg({ kind: "good", text: `命令 ${commandId} 已拒绝` });
      await load();
    } catch (err) {
      if (is401(err)) setNeedLogin(true);
      else setMsg({ kind: "serious", text: errorMessageOf(err) });
    } finally {
      setBusyId(null);
    }
  }

  /** 操作列：Agent 命令 → 批准 / 拒绝；其余待批准工作给出诚实指引。 */
  function renderOps(w: WorkItem) {
    if (str(w.detail?.subject_type) === "agent_command" && str(w.detail?.subject_id)) {
      return (
        <span className="flex gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-1.5 text-xs"
            disabled={busyId === w.id}
            onClick={() => void approve(w)}
          >
            批准
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-1.5 text-xs"
            disabled={busyId === w.id}
            onClick={() => void reject(w)}
          >
            拒绝
          </Button>
        </span>
      );
    }
    if (str(w.detail?.subject_type) === "workflow_run") {
      return (
        <span className="text-xs text-text-secondary">
          在工作流「运行中心」批准
        </span>
      );
    }
    return <span className="text-text-secondary">—</span>;
  }

  const cols: ApiTableCol<WorkItem>[] = [
    {
      key: "title",
      label: "待批准事项",
      render: (w) => <span className="text-[13px]">{w.title}</span>,
    },
    {
      key: "kind",
      label: "类型",
      render: (w) => (
        <span className="text-xs text-text-secondary">{w.kind}</span>
      ),
    },
    {
      key: "status",
      label: "状态",
      render: (w) => <StatusBadge kind="warn">{w.status_text || w.status}</StatusBadge>,
    },
    {
      key: "owner",
      label: "负责人",
      render: (w) => (
        <span className="text-xs text-text-secondary">{w.owner || "—"}</span>
      ),
    },
    {
      key: "subject",
      label: "对象",
      render: (w) => {
        const st = str(w.detail?.subject_type);
        const sid = str(w.detail?.subject_id);
        if (!st && !sid) return <span className="text-text-secondary">—</span>;
        return (
          <span className="text-xs text-text-secondary" title={`${st} · ${sid}`}>
            {st || "未知"}{sid ? ` · ${sid.slice(0, 16)}…` : ""}
          </span>
        );
      },
    },
    { key: "ops", label: "操作", render: renderOps },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="命令审批"
        desc="主管 Agent 生成的写命令先进待批准账本，人工批准后才执行；批准与拒绝均服务端留痕"
        aside={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            刷新
          </Button>
        }
      />
      <ActionMsg msg={msg} />

      {/* ---- 待审批命令表 ---- */}
      <section className="space-y-2" aria-label="待审批命令">
        {needLogin ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : listErr ? (
          <ErrorState
            message={errorMessageOf(listErr)}
            onRetry={() => void load()}
          />
        ) : (
          <ApiTable
            rows={items ?? []}
            cols={cols}
            rowKey={(w) => w.id}
            loading={loading}
            emptyText="暂无待批准事项：主管生成写命令后会出现在这里"
          />
        )}
      </section>

      {/* ---- 审计留痕说明 ---- */}
      <section
        className="space-y-1.5 rounded-md border border-border bg-surface/60 p-3"
        aria-label="审计留痕说明"
      >
        <h2 className="text-[13px] font-semibold text-text-primary">
          审计留痕说明
        </h2>
        <ul className="list-disc space-y-1 pl-4 text-xs leading-relaxed text-text-secondary">
          <li>
            批准 / 拒绝由服务端写入命令账本（agent_command_v1）：状态
            approved / rejected，连同决策人（登录身份）与决策时间，前端不自证身份。
          </li>
          <li>
            批准后领域执行失败会被诚实标记 approved_failed（HTTP 502），
            不会冒充成功；命令状态非待批准时重复决策返回 409。
          </li>
          <li>
            Agent 命令没有独立的列表端点：本页与 web 主管工作台同源，
            消费统一任务中心投影（stage = approval）；命令号通常随主管
            对话的 command_previews 一并返回。
          </li>
          <li>
            目标确认（目标拆解标签）后由 Supervisor 形成的计划与命令，
            同样进入本账本等待批准。
          </li>
        </ul>
      </section>
    </div>
  );
}
