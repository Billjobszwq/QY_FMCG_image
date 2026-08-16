/**
 * 模型管理（/vision/models）—— 驻留、训练门禁与注册模型。
 *
 * 数据源（同源 /api/v1/*，禁样本数据）：
 * —— GET /training/gates：训练门禁（授权 / 能否 dry-run / 能否训练 + 原因）；
 * —— GET /models/runtime：模型驻留（hot/warm/cold、内存状态、租约队列）；
 * —— GET /training/legacy-models：只读登记的历史模型（不移动、不删除）。
 *
 * 本页只读：不发起任何训练；批准计划与提交 Job 为两步独立操作，
 * 均不在本页提供入口（训练治理的写操作属高风险，留在专用流程）。
 */
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  fetchLegacyModels,
  fetchModelsRuntime,
  fetchTrainingGates,
} from "@/lib/api";
import type {
  LegacyModelRow,
  ModelRuntimeRow,
  TrainingGates,
} from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";
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
   模型驻留（VLM-016：hot/warm/cold + sleeping guardian 诚实状态）
   ========================================================================== */

const RESIDENCY_CN: Record<string, string> = {
  hot: "hot（常驻）",
  warm: "warm（按需保活）",
  cold: "cold（按需加载）",
};

/** 内存状态 → StatusBadge（failed=熔断 serious；cold=未加载 neutral）。 */
function ModelStateBadge({ state }: { state: string }) {
  switch (state) {
    case "hot":
      return <StatusBadge kind="good">在内存中</StatusBadge>;
    case "loading":
      return <StatusBadge kind="warn">加载到内存中…</StatusBadge>;
    case "unloading":
      return <StatusBadge kind="warn">卸载中…</StatusBadge>;
    case "failed":
      return <StatusBadge kind="serious">加载失败（熔断）</StatusBadge>;
    default:
      return <StatusBadge kind="neutral">未加载（冷启动）</StatusBadge>;
  }
}

const RUNTIME_COLS: ApiTableCol<ModelRuntimeRow>[] = [
  { key: "model_id", label: "模型" },
  {
    key: "residency",
    label: "驻留档位",
    render: (m) => RESIDENCY_CN[m.residency] ?? m.residency,
  },
  { key: "state", label: "内存状态", render: (m) => <ModelStateBadge state={m.state} /> },
  {
    key: "queue",
    label: "租约 / 并发上限",
    align: "right",
    render: (m) => `${m.active_leases}/${m.max_concurrency}`,
  },
  {
    key: "idle_ttl_s",
    label: "空闲卸载",
    align: "right",
    render: (m) => `${m.idle_ttl_s}s`,
  },
  {
    key: "last_used_at",
    label: "最近使用",
    render: (m) =>
      m.last_used_at ?? <span className="text-text-secondary">从未</span>,
  },
];

/* ============================================================================
   历史模型（legacy-models：只读登记）
   ========================================================================== */

/** 权重配置（weights_json 字符串）压缩展示，悬浮看全文。 */
function shortWeights(w: string): string {
  try {
    return JSON.stringify(JSON.parse(w));
  } catch {
    return w;
  }
}

const LEGACY_COLS: ApiTableCol<LegacyModelRow>[] = [
  { key: "model_id", label: "模型" },
  {
    key: "status",
    label: "状态",
    render: (m) => (
      <StatusBadge kind={m.status === "production" ? "good" : "neutral"}>
        {m.status}
      </StatusBadge>
    ),
  },
  { key: "path", label: "路径" },
  {
    key: "weights_json",
    label: "权重配置",
    render: (m) => {
      const s = shortWeights(m.weights_json);
      return (
        <span title={s} className="block max-w-[200px] truncate text-text-secondary">
          {s || "—"}
        </span>
      );
    },
  },
  {
    key: "git_commit",
    label: "git commit",
    render: (m) =>
      m.git_commit ? (
        <span className="text-text-secondary">{m.git_commit.slice(0, 8)}</span>
      ) : (
        <span className="text-text-secondary">—</span>
      ),
  },
  { key: "registered_at", label: "登记时间" },
];

/* ============================================================================
   页面
   ========================================================================== */

export default function Models() {
  // ---- 训练门禁 ----
  const [gates, setGates] = useState<TrainingGates | null>(null);
  const [gatesErr, setGatesErr] = useState<string | null>(null);

  // ---- 模型驻留（404 = API 未启用的诚实状态，不当错误处理） ----
  const [runtime, setRuntime] = useState<ModelRuntimeRow[] | null>(null);
  const [runtimeErr, setRuntimeErr] = useState<string | null>(null);
  const [runtimeDown, setRuntimeDown] = useState(false);

  // ---- 历史模型 ----
  const [legacy, setLegacy] = useState<LegacyModelRow[] | null>(null);
  const [legacyErr, setLegacyErr] = useState<string | null>(null);

  const [needLogin, setNeedLogin] = useState(false);

  const loadGates = useCallback(async () => {
    setGatesErr(null);
    try {
      setGates(await fetchTrainingGates());
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else setGatesErr(errorMessageOf(e));
    }
  }, []);

  const loadRuntime = useCallback(async () => {
    setRuntimeErr(null);
    setRuntimeDown(false);
    try {
      const d = await fetchModelsRuntime();
      setRuntime(d.models);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // shadow 阶段诚实状态：进程未注入 cascade service
        setRuntime(null);
        setRuntimeDown(true);
      } else if (e instanceof ApiError && e.status === 401) {
        setNeedLogin(true);
      } else {
        setRuntimeErr(errorMessageOf(e));
      }
    }
  }, []);

  const loadLegacy = useCallback(async () => {
    setLegacyErr(null);
    try {
      const d = await fetchLegacyModels();
      setLegacy(d.models);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else setLegacyErr(errorMessageOf(e));
    }
  }, []);

  const reload = useCallback(async () => {
    setNeedLogin(false);
    await Promise.all([loadGates(), loadRuntime(), loadLegacy()]);
  }, [loadGates, loadRuntime, loadLegacy]);

  useEffect(() => {
    reload();
  }, [reload]);

  const failedModels = (runtime ?? []).filter((m) => m.state === "failed");

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="模型管理"
        desc="模型驻留（hot / warm / cold）、训练门禁与历史模型登记（本页只读，不发起训练）"
        aside={
          <Button variant="secondary" size="sm" onClick={reload}>
            刷新
          </Button>
        }
      />

      {needLogin && <NeedLoginState onOpenLogin={openLoginWindow} />}

      {/* ---- 训练门禁（M5） ---- */}
      <section className="space-y-2">
        <h2 className="font-display text-sm font-bold text-text-primary">训练门禁</h2>
        {gatesErr ? (
          <ErrorState message={gatesErr} onRetry={loadGates} />
        ) : !gates ? (
          needLogin ? null : (
            <div className="flex justify-center py-4">
              <HedgehogLoader className="h-8 w-auto" />
            </div>
          )
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <StatusBadge kind={gates.training_authorized ? "good" : "serious"}>
                {gates.training_authorized ? "训练已获显式授权" : "当前无训练授权"}
              </StatusBadge>
              <StatusBadge kind={gates.can_train ? "good" : "neutral"}>
                {gates.can_train ? "可训练" : "不可训练"}
              </StatusBadge>
              <StatusBadge kind={gates.can_dry_run ? "good" : "neutral"}>
                {gates.can_dry_run ? "允许 dry-run" : "不允许 dry-run"}
              </StatusBadge>
            </div>
            <KV
              items={[
                { label: "已注册快照", value: gates.registered_snapshots },
                ...(gates.reasons.length > 0
                  ? [{ label: "为什么不能训练", value: gates.reasons.join("；") }]
                  : []),
              ]}
            />
            <p className="text-xs text-text-secondary">
              {!gates.training_authorized
                ? "training_authorized=false：平台不消耗训练算力。"
                : "training_authorized=true：批准计划与提交 Job 仍为两步独立操作。"}
              训练完成只产生 candidate，发布需独立审批。
            </p>
          </>
        )}
      </section>

      {/* ---- 模型驻留 ---- */}
      <section className="space-y-2">
        <h2 className="font-display text-sm font-bold text-text-primary">
          模型驻留（hot / warm / cold）
        </h2>
        {runtimeDown && (
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge kind="warn">驻留 API 未启用</StatusBadge>
            <span className="text-xs text-text-secondary">
              当前进程未注入 cascade service（shadow 阶段诚实状态）。
            </span>
          </div>
        )}
        {failedModels.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge kind="serious">模型熔断</StatusBadge>
            <span className="text-xs text-text-secondary">
              {failedModels.map((m) => m.model_id).join("、")}{" "}
              加载失败已熔断；级联会自动回落上一阶段或转人工，不会静默接受。
            </span>
          </div>
        )}
        {!runtimeDown && (needLogin && runtime === null && !runtimeErr ? (
          <p className="text-xs text-text-secondary">
            需要登录后读取（见页首“需要登录”状态）。
          </p>
        ) : (
          <ApiTable<ModelRuntimeRow>
            rows={runtime ?? []}
            cols={RUNTIME_COLS}
            loading={runtime === null && !runtimeErr}
            error={runtimeErr}
            onRetry={loadRuntime}
            emptyText="暂无注册模型（空注册表是诚实状态）"
            rowKey={(m) => m.model_id}
          />
        ))}
        <p className="text-xs text-text-secondary">
          档位纪律：YOLO/ResNet=hot，SAM/OCR/检索=warm，大参数 VLM=cold
          （sleeping guardian：并发上限 1、空闲 TTL 卸载、加载失败熔断）。
        </p>
      </section>

      {/* ---- 历史模型（只读登记） ---- */}
      <section className="space-y-2">
        <h2 className="font-display text-sm font-bold text-text-primary">
          历史模型（legacy，只读登记）
        </h2>
        {needLogin && legacy === null && !legacyErr ? (
          <p className="text-xs text-text-secondary">
            需要登录后读取（见页首“需要登录”状态）。
          </p>
        ) : (
          <ApiTable<LegacyModelRow>
            rows={legacy ?? []}
            cols={LEGACY_COLS}
            loading={legacy === null && !legacyErr}
            error={legacyErr}
            onRetry={loadLegacy}
            emptyText="暂无历史模型登记"
            rowKey={(m) => m.model_id}
          />
        )}
        <p className="text-xs text-text-secondary">
          只读登记：旧模型不移动、不删除、不作 nextgen parent。
        </p>
      </section>
    </div>
  );
}
