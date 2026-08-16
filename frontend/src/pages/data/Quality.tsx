/**
 * 质量金标准（P4）：资产质量台账视角的 quality/gold/*。
 *
 * 数据源（同源 /api/v1/*，src/lib/api.ts；与证据链页同源、视角不同）：
 * —— fetchGoldStatus():      GET  /api/v1/quality/gold/status → 队列与条目；
 * —— fetchGoldConfusion():   GET  /api/v1/quality/gold/confusion → 混淆矩阵；
 * —— fetchBuildGoldQueue():  POST /api/v1/quality/gold/build（分层建队）；
 * —— fetchSubmitGoldVerdict(): POST /api/v1/quality/gold/verdict（人工结论）。
 *
 * 纪律：人工结论以服务端 session 身份落库，追加式不可变；
 * SAM/自动结论永远不是最终结论，未完成任务不得伪造完成。
 */
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  fetchBuildGoldQueue,
  fetchGoldConfusion,
  fetchGoldStatus,
  fetchSubmitGoldVerdict,
} from "@/lib/api";
import type { GoldStatusBody } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useWindowManager } from "@/store/windowStore";
import LoginWindow from "@/components/ui/LoginWindow";
import { Button } from "@/components/ui/button";
import { StatTile } from "@/components/charts/primitives";
import {
  ApiTable,
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";

/** 明细表最大行数（信息密度优先，超出部分以说明提示）。 */
const MAX_ROWS = 200;

/** 分层 → 中文（web 端原样保留）。 */
const STRATUM_CN: Record<string, string> = {
  fail: "自动判 fail 层",
  pass: "自动判 pass 层",
  waiting_human: "无自动结论层",
};

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

export default function Quality() {
  const me = useAuth((s) => s.me);
  const [gold, setGold] = useState<GoldStatusBody | null>(null);
  const [confusion, setConfusion] = useState<Record<string, number> | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  /** mutation 触发 401 时展示“需要登录”入口（数据仍可继续浏览）。 */
  const [needLogin, setNeedLogin] = useState(false);
  const [actionMsg, setActionMsg] = useState<{
    kind: StatusKind;
    text: string;
  } | null>(null);
  const [busySha, setBusySha] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [st, cm] = await Promise.all([
        fetchGoldStatus(),
        fetchGoldConfusion(),
      ]);
      setGold(st);
      setConfusion(cm);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  /* 401 → 需要登录；登录成功（me 变化）后自动重试并复位登录提示 */
  const unauthorized = error instanceof ApiError && error.status === 401;
  useEffect(() => {
    if (me) {
      setNeedLogin(false);
      if (unauthorized) void reload();
    }
  }, [me, unauthorized, reload]);

  /** 分层建队（500）：mutation，可调即调；401 映射为“需要登录”。 */
  async function build() {
    setBuilding(true);
    setActionMsg(null);
    try {
      const r = await fetchBuildGoldQueue(500);
      setActionMsg({
        kind: "good",
        text: `建队完成：新增 ${r.added}，队列共 ${r.total_queue}`,
      });
      await reload();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else setActionMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setBuilding(false);
    }
  }

  /** 人工结论：pass/fail 以 session 身份追加式落库，不可改。 */
  async function verdict(sha256: string, v: "pass" | "fail") {
    setBusySha(sha256);
    setActionMsg(null);
    try {
      await fetchSubmitGoldVerdict(sha256, v);
      await reload();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else setActionMsg({ kind: "serious", text: errorMessageOf(e) });
    } finally {
      setBusySha(null);
    }
  }

  const cols: ApiTableCol<GoldStatusBody["items"][number]>[] = [
    {
      key: "sha256",
      label: "SHA",
      render: (r) => (
        <span className="whitespace-nowrap" title={r.sha256}>
          {r.sha256.slice(0, 12)}…
        </span>
      ),
    },
    {
      key: "source_uri",
      label: "引用",
      render: (r) => (
        <span className="block max-w-[260px] truncate" title={r.source_uri}>
          {r.source_uri || "—"}
        </span>
      ),
    },
    {
      key: "stratum",
      label: "层",
      render: (r) => STRATUM_CN[r.stratum] ?? r.stratum,
    },
    {
      key: "status",
      label: "状态",
      render: (r) =>
        r.status === "waiting_human" ? (
          <StatusBadge kind="warn">等待人工</StatusBadge>
        ) : (
          <StatusBadge kind="good">已完成</StatusBadge>
        ),
    },
    {
      key: "human_verdict",
      label: "人工结论",
      render: (r) =>
        r.human_verdict === "pass" ? (
          <StatusBadge kind="good">通过</StatusBadge>
        ) : r.human_verdict === "fail" ? (
          <StatusBadge kind="serious">不通过</StatusBadge>
        ) : (
          <span className="text-text-secondary">—</span>
        ),
    },
    {
      key: "actions",
      label: "操作",
      render: (r) =>
        r.status === "waiting_human" ? (
          <span className="flex gap-1.5">
            <Button
              variant="secondary"
              size="sm"
              disabled={busySha === r.sha256}
              onClick={() => void verdict(r.sha256, "pass")}
            >
              通过
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={busySha === r.sha256}
              onClick={() => void verdict(r.sha256, "fail")}
            >
              不通过
            </Button>
          </span>
        ) : (
          <span className="text-xs text-text-secondary">不可改</span>
        ),
    },
  ];

  const confusionRows = confusion
    ? [
        {
          auto: "fail",
          fail: confusion.auto_fail_human_fail ?? 0,
          pass: confusion.auto_fail_human_pass ?? 0,
        },
        {
          auto: "pass",
          fail: confusion.auto_pass_human_fail ?? 0,
          pass: confusion.auto_pass_human_pass ?? 0,
        },
        {
          auto: "无结论",
          fail: confusion.auto_none_human_fail ?? 0,
          pass: confusion.auto_none_human_pass ?? 0,
        },
      ]
    : [];

  const confusionCols: ApiTableCol<{
    auto: string;
    fail: number;
    pass: number;
  }>[] = [
    { key: "auto", label: "自动 \\ 人工" },
    {
      key: "fail",
      label: "人工 fail",
      align: "right",
      render: (r) => r.fail.toLocaleString("zh-CN"),
    },
    {
      key: "pass",
      label: "人工 pass",
      align: "right",
      render: (r) => r.pass.toLocaleString("zh-CN"),
    },
  ];

  const items = gold?.items ?? [];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="质量金标准"
        desc="分层抽样的人工金标准台账：人工结论以 session 身份落库，追加式不可变；自动结论永远不是最终结论"
        aside={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={building || loading}
              onClick={() => void build()}
            >
              分层建队（500）
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={loading}
              onClick={() => void reload()}
            >
              刷新
            </Button>
          </div>
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
          {gold && (
            <div className="grid grid-cols-2 gap-2 sm:w-96">
              <StatTile
                label="等待人工（waiting_human）"
                value={gold.waiting_human.toLocaleString("zh-CN")}
              />
              <StatTile
                label="人工已完成"
                value={gold.done.toLocaleString("zh-CN")}
              />
            </div>
          )}

          {needLogin && <NeedLoginState onOpenLogin={openLoginWindow} />}

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

          {gold?.note && (
            <p className="text-xs text-text-secondary">{gold.note}</p>
          )}

          <ApiTable
            rows={items.slice(0, MAX_ROWS)}
            cols={cols}
            loading={loading}
            rowKey={(r) => r.sha256}
            emptyText="队列为空；点击「分层建队」从本地真实照片抽样（manifest-only 不入队）"
          />
          {items.length > MAX_ROWS && (
            <p className="text-xs text-text-secondary">
              仅展示前 {MAX_ROWS} 条，共 {items.length} 条
            </p>
          )}

          {confusion && (confusion.pairs ?? 0) > 0 && (
            <section className="space-y-1.5">
              <h2 className="font-display text-sm font-bold text-text-primary">
                混淆矩阵（仅对有人工结论的 {confusion.pairs} 对）
              </h2>
              <ApiTable
                rows={confusionRows}
                cols={confusionCols}
                rowKey={(r) => r.auto}
                className="max-w-md"
              />
            </section>
          )}
        </>
      )}
    </div>
  );
}
