/**
 * 主管 Agent · 目标拆解（/agent/goals，主管 Agent 组）。
 *
 * 数据源（同源 /api/v1，全部真实数据，禁止样本）：
 * —— GET  /api/v1/goals               （fetchGoals：目标草稿台账）
 * —— POST /api/v1/goals               （fetchCreateGoal：登记目标）
 * —— POST /api/v1/goals/{id}/confirm  （fetchConfirmGoal：确认拆解 →
 *    Supervisor 形成计划 / 命令并留痕）
 * —— GET  /api/v1/taskboard           （fetchTaskboard：五列任务状态投影）
 *
 * 数据红线：401 → NeedLoginState；网络错误 → ErrorState；加载中 = 刺猬。
 */
import { useCallback, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ApiError,
  fetchConfirmGoal,
  fetchCreateGoal,
  fetchGoals,
  fetchTaskboard,
} from "@/lib/api";
import type { GoalDraft } from "@/lib/api";
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
import { Input } from "@/components/ui/input";
import { HedgehogLoader } from "@/components/ui/loader";

/** 请求桌面层打开登录窗口（与既有页面同源约定）。 */
const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));

const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

const fmtAt = (s: string | null | undefined) =>
  s ? s.slice(0, 19).replace("T", " ") : "—";

const truncate = (s: string, n: number) =>
  s.length > n ? `${s.slice(0, n)}…` : s;

/** 目标状态 → StatusBadge。 */
const GOAL_CN: Record<string, { kind: StatusKind; text: string }> = {
  open: { kind: "warn", text: "待确认" },
  confirmed: { kind: "good", text: "已确认" },
  cancelled: { kind: "serious", text: "已取消" },
};

function goalBadge(status: string): ReactNode {
  const m = GOAL_CN[status] ?? { kind: "neutral" as StatusKind, text: status };
  return <StatusBadge kind={m.kind}>{m.text}</StatusBadge>;
}

/** 任务板五列列序与中文。 */
const BOARD_ORDER = ["todo", "running", "waiting", "review", "done"] as const;
const BOARD_CN: Record<string, string> = {
  todo: "待办",
  running: "运行中",
  waiting: "等待 / 阻塞",
  review: "待验收",
  done: "完成",
};

/** 任务板卡片（后端投影行）。 */
interface TaskCard {
  logical_task_key: string;
  title: string;
  current_status: string;
  owner: string;
  blocker: string;
  acceptance: string;
  updated_at: string;
}

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

/** 从 goal.result 提取可展示的确认结果（诚实呈现，不臆造）。 */
function goalResultText(g: GoalDraft): string {
  const r = g.result as Record<string, unknown> | null;
  if (!r || Object.keys(r).length === 0) return "";
  const message = typeof r.message === "string" ? r.message : "";
  const needApproval = r.requires_approval === true ? "（含待批准命令）" : "";
  return message ? `${message}${needApproval}` : needApproval;
}

export default function AgentGoals() {
  // 目标台账（需登录会话）
  const [goals, setGoals] = useState<GoalDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [goalsErr, setGoalsErr] = useState<unknown>(null);
  const [needLogin, setNeedLogin] = useState(false);
  // 任务板投影
  const [board, setBoard] = useState<Record<string, TaskCard[]> | null>(null);
  const [boardErr, setBoardErr] = useState<unknown>(null);
  // 表单与操作
  const [goalText, setGoalText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg | null>(null);

  const loadGoals = useCallback(async () => {
    setLoading(true);
    setGoalsErr(null);
    setNeedLogin(false);
    try {
      const d = await fetchGoals();
      setGoals(
        [...d.goals].sort((a, b) => b.created_at.localeCompare(a.created_at)),
      );
    } catch (e) {
      if (is401(e)) setNeedLogin(true);
      else setGoalsErr(e);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadBoard = useCallback(async () => {
    setBoardErr(null);
    try {
      const d = await fetchTaskboard();
      setBoard(d.states as Record<string, TaskCard[]>);
    } catch (e) {
      setBoard(null);
      setBoardErr(e);
    }
  }, []);

  useEffect(() => {
    void loadGoals();
    void loadBoard();
  }, [loadGoals, loadBoard]);

  /** 登记目标：先落服务端，再可确认拆解。 */
  async function createGoal(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = goalText.trim();
    if (!text || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      await fetchCreateGoal(text);
      setGoalText("");
      setMsg({ kind: "good", text: "目标已登记：确认拆解后由 Supervisor 形成计划与命令" });
      await loadGoals();
    } catch (err) {
      if (is401(err)) setNeedLogin(true);
      else setMsg({ kind: "serious", text: errorMessageOf(err) });
    } finally {
      setBusy(false);
    }
  }

  /** 确认拆解 → Supervisor 形成计划 / 命令（可能耗时）。 */
  async function confirmGoal(g: GoalDraft) {
    if (busy) return;
    setBusy(true);
    setMsg(null);
    try {
      await fetchConfirmGoal(g.goal_id);
      setMsg({ kind: "good", text: `已确认拆解：${truncate(g.text, 30)}` });
      await Promise.all([loadGoals(), loadBoard()]);
    } catch (err) {
      if (is401(err)) setNeedLogin(true);
      else setMsg({ kind: "serious", text: errorMessageOf(err) });
    } finally {
      setBusy(false);
    }
  }

  const goalCols: ApiTableCol<GoalDraft>[] = [
    {
      key: "text",
      label: "目标",
      render: (g) => <span className="text-[13px]">{g.text}</span>,
    },
    { key: "status", label: "状态", render: (g) => goalBadge(g.status) },
    {
      key: "result",
      label: "拆解结果",
      render: (g) => {
        const t = goalResultText(g);
        return t ? (
          <span className="text-xs text-text-secondary" title={t}>
            {truncate(t, 48)}
          </span>
        ) : (
          <span className="text-text-secondary">—</span>
        );
      },
    },
    {
      key: "created_by",
      label: "提交人",
      render: (g) => (
        <span className="text-xs text-text-secondary">{g.created_by}</span>
      ),
    },
    {
      key: "created_at",
      label: "提交时间",
      render: (g) => (
        <span className="text-xs text-text-secondary">{fmtAt(g.created_at)}</span>
      ),
    },
    {
      key: "ops",
      label: "操作",
      render: (g) =>
        g.status === "open" ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-1.5 text-xs"
            disabled={busy}
            onClick={() => void confirmGoal(g)}
          >
            确认拆解
          </Button>
        ) : (
          <span className="text-text-secondary">—</span>
        ),
    },
  ];

  const boardTotal = board
    ? BOARD_ORDER.reduce((n, s) => n + (board[s]?.length ?? 0), 0)
    : 0;

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="目标拆解"
        desc="登记目标并确认拆解：Supervisor 形成计划与命令，含待批准命令会进入命令审批"
        aside={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void loadGoals();
              void loadBoard();
            }}
          >
            刷新
          </Button>
        }
      />
      <ActionMsg msg={msg} />

      {/* ---- 目标列表 / 新建 ---- */}
      <section className="space-y-2" aria-label="目标列表">
        <h2 className="text-[13px] font-semibold text-text-primary">
          目标列表（{loading ? "…" : goals.length}）
        </h2>
        {needLogin ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : goalsErr ? (
          <ErrorState
            message={errorMessageOf(goalsErr)}
            onRetry={() => void loadGoals()}
          />
        ) : (
          <div className="space-y-2">
            <form className="flex gap-2" onSubmit={(e) => void createGoal(e)}>
              <Input
                value={goalText}
                placeholder="例如：把昨天上传的照片跑一遍识别并加人工复核"
                aria-label="目标文本"
                className="flex-1"
                onChange={(e) => setGoalText(e.target.value)}
              />
              <Button
                type="submit"
                size="sm"
                className="h-8"
                disabled={busy || !goalText.trim()}
              >
                新建目标
              </Button>
            </form>
            <ApiTable
              rows={goals}
              cols={goalCols}
              rowKey={(g) => g.goal_id}
              loading={loading}
              emptyText="暂无目标：新建一条目标，确认拆解后形成计划与命令"
            />
          </div>
        )}
      </section>

      {/* ---- 任务板（五列状态投影） ---- */}
      <section className="space-y-2" aria-label="任务板">
        <h2 className="text-[13px] font-semibold text-text-primary">
          任务板（{board ? boardTotal : "…"}）
        </h2>
        {boardErr ? (
          <ErrorState
            message={errorMessageOf(boardErr)}
            onRetry={() => void loadBoard()}
          />
        ) : !board ? (
          <div className="flex justify-center py-8">
            <HedgehogLoader />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <div className="grid min-w-[880px] grid-cols-5 gap-2">
              {BOARD_ORDER.map((s) => {
                const cards = board[s] ?? [];
                return (
                  <div
                    key={s}
                    className="rounded-md border border-border bg-surface/60 p-2"
                  >
                    <p className="mb-2 text-xs font-medium text-text-secondary">
                      {BOARD_CN[s]}（{cards.length}）
                    </p>
                    <div className="space-y-1.5">
                      {cards.length === 0 ? (
                        <p className="text-xs text-text-secondary">—</p>
                      ) : (
                        cards.map((c) => (
                          <div
                            key={c.logical_task_key}
                            className="rounded-md border border-border bg-background p-2"
                          >
                            <p className="text-[13px] leading-snug text-text-primary">
                              {c.title || c.logical_task_key}
                            </p>
                            <p className="mt-1 text-xs text-text-secondary">
                              负责人 {c.owner || "—"} · 验收{" "}
                              {c.acceptance || "pending"}
                            </p>
                            {c.blocker && (
                              <div className="mt-1">
                                <StatusBadge kind="warn">
                                  阻塞：{truncate(c.blocker, 20)}
                                </StatusBadge>
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
