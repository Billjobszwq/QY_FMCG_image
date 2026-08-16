/**
 * 证据链（/vision/evidence）—— 人工金标准队列、裁决与混淆矩阵。
 *
 * 数据源（同源 /api/v1/*，真实计数，不硬编码）：
 * —— GET  /quality/gold/status：队列与 waiting_human / done 进度
 *    （人工未完成只能显示 waiting_human，禁止伪造通过）；
 * —— GET  /quality/gold/confusion：仅对有人工结论的对计算混淆矩阵
 *    （无自动结论记为 auto=none）；
 * —— POST /quality/gold/verdict：人工裁决 pass / fail（登录 + CSRF，
 *    reviewer 取服务端 session 身份，禁止客户端自证；同一 SHA 仅一次）。
 */
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  fetchGoldConfusion,
  fetchGoldStatus,
  fetchSubmitGoldVerdict,
} from "@/lib/api";
import type { GoldItem, GoldStatusBody } from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";
import { StatTile } from "@/components/charts/primitives";
import { Button } from "@/components/ui/button";
import { HedgehogLoader } from "@/components/ui/loader";
import LoginWindow from "@/components/ui/LoginWindow";
import { getWindowManager } from "@/store/windowStore";

/** 打开登录窗口（幂等：已存在则置前；登录成功后自动关闭）。 */
function openLoginWindow() {
  getWindowManager().openWindow({
    id: "login",
    title: "平台登录",
    content: (
      <LoginWindow onLoggedIn={() => getWindowManager().closeWindow("login")} />
    ),
    defaultPosition: { x: 160, y: 120 },
    defaultSize: { width: 352, height: 420 },
    resizable: false,
  });
}

/* ============================================================================
   混淆矩阵（小矩阵表：行=自动结论 fail/pass/none，列=人工结论）
   ========================================================================== */

interface MatrixRow {
  auto: string;
  pass: number;
  fail: number;
}

function matrixRowsOf(m: Record<string, number>): MatrixRow[] {
  return [
    { auto: "自动 fail", pass: m.auto_fail_human_pass ?? 0, fail: m.auto_fail_human_fail ?? 0 },
    { auto: "自动 pass", pass: m.auto_pass_human_pass ?? 0, fail: m.auto_pass_human_fail ?? 0 },
    { auto: "自动缺失 (none)", pass: m.auto_none_human_pass ?? 0, fail: m.auto_none_human_fail ?? 0 },
  ];
}

const MATRIX_COLS: ApiTableCol<MatrixRow>[] = [
  { key: "auto", label: "自动结论" },
  { key: "pass", label: "人工 · 通过", align: "right" },
  { key: "fail", label: "人工 · 不通过", align: "right" },
];

/* ============================================================================
   页面
   ========================================================================== */

export default function Evidence() {
  const [gold, setGold] = useState<GoldStatusBody | null>(null);
  const [confusion, setConfusion] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needLogin, setNeedLogin] = useState(false);

  // ---- 裁决提交（逐行 busy + 错误提示） ----
  const [busySha, setBusySha] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNeedLogin(false);
    try {
      const [g, c] = await Promise.all([fetchGoldStatus(), fetchGoldConfusion()]);
      setGold(g);
      setConfusion(c);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else setError(errorMessageOf(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const submitVerdict = async (sha256: string, verdict: "pass" | "fail") => {
    setBusySha(sha256);
    setActionErr(null);
    try {
      await fetchSubmitGoldVerdict(sha256, verdict);
      await reload(); // 刷新队列进度与混淆矩阵
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else setActionErr(errorMessageOf(e));
    } finally {
      setBusySha(null);
    }
  };

  const goldCols: ApiTableCol<GoldItem>[] = [
    {
      key: "sha256",
      label: "样本",
      render: (g) => (
        <span title={g.sha256} className="text-text-secondary">
          {g.sha256.slice(0, 12)}…
        </span>
      ),
    },
    {
      key: "source_uri",
      label: "来源",
      render: (g) => (
        <span title={g.source_uri} className="block max-w-[240px] truncate">
          {g.source_uri}
        </span>
      ),
    },
    { key: "stratum", label: "层" },
    {
      key: "status",
      label: "状态",
      render: (g) =>
        g.status === "done" ? (
          <StatusBadge kind="good">已完成</StatusBadge>
        ) : (
          <StatusBadge kind="warn">等待人工</StatusBadge>
        ),
    },
    {
      key: "human_verdict",
      label: "人工裁决",
      render: (g) => {
        if (g.human_verdict === "pass") return <StatusBadge kind="good">通过</StatusBadge>;
        if (g.human_verdict === "fail") return <StatusBadge kind="serious">不通过</StatusBadge>;
        return <span className="text-text-secondary">—</span>;
      },
    },
    {
      key: "actions",
      label: "操作",
      render: (g) =>
        g.status === "waiting_human" ? (
          <div className="flex gap-1.5">
            <Button
              variant="secondary"
              size="sm"
              disabled={busySha !== null}
              onClick={() => submitVerdict(g.sha256, "pass")}
            >
              {busySha === g.sha256 ? "提交中…" : "通过"}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={busySha !== null}
              onClick={() => submitVerdict(g.sha256, "fail")}
            >
              不通过
            </Button>
          </div>
        ) : (
          <span className="text-xs text-text-secondary">追加式不可变</span>
        ),
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="证据链"
        desc="人工金标准队列、裁决与混淆矩阵 —— 真实计数，人工未完成只能显示 waiting_human"
        aside={
          <Button variant="secondary" size="sm" onClick={reload} disabled={loading}>
            刷新
          </Button>
        }
      />

      {needLogin && <NeedLoginState onOpenLogin={openLoginWindow} />}

      {error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !gold ? (
        <div className="flex justify-center py-8">
          <HedgehogLoader className="h-9 w-auto" />
        </div>
      ) : (
        <>
          {/* 进度计数（来自 quality_gold_v1 实时查询） */}
          <div className="grid max-w-md grid-cols-2 gap-3">
            <StatTile label="等待人工裁决" value={gold.waiting_human} note="waiting_human" />
            <StatTile label="已完成" value={gold.done} note="done（追加式不可变）" />
          </div>
          {gold.note && <p className="text-xs text-text-secondary">{gold.note}</p>}

          {/* 金标准队列 */}
          <ApiTable<GoldItem>
            rows={gold.items}
            cols={goldCols}
            loading={loading}
            emptyText="金标准队列为空"
            rowKey={(g) => g.sha256}
          />

          {actionErr && (
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge kind="serious">裁决提交失败</StatusBadge>
              <span className="text-xs text-text-secondary">{actionErr}</span>
            </div>
          )}

          {/* 混淆矩阵：仅对有人工结论的对计算 */}
          <section className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-display text-sm font-bold text-text-primary">
                混淆矩阵（仅有人工结论的对）
              </h2>
              <span className="text-xs text-text-secondary">
                共 {confusion?.pairs ?? 0} 对
              </span>
            </div>
            <ApiTable<MatrixRow>
              rows={confusion ? matrixRowsOf(confusion) : []}
              cols={MATRIX_COLS}
              loading={!confusion}
              emptyText="尚无人工结论，无法计算混淆矩阵"
              rowKey={(r) => r.auto}
              className="max-w-md"
            />
            <p className="text-xs text-text-secondary">
              口径：无自动结论 / waiting_human 记为 auto=none；对角（自动与人工一致）不额外着色，
              数字即事实。
            </p>
          </section>
        </>
      )}
    </div>
  );
}
