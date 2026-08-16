/**
 * 识别工作台（/vision/recognize，v3 瘦版）。
 *
 * 数据源（真实接口，无样本数据）：
 * —— 照片库：直连本机 orchestrator :8304（CORS 已开）
 *      GET  http://127.0.0.1:8304/recognize/photos       照片清单 {id, sname, typename}
 *      GET  http://127.0.0.1:8304/recognize/photo/{id}   照片字节（缩略/预览）
 *      POST http://127.0.0.1:8304/recognize/run          {asset_id, conf} → {products, count, elapsed_ms}
 *      （写入口鉴权：未设 ORCHESTRATOR_ADMIN_TOKEN 时仅本机回环可用）
 * —— 同源识别服务（src/lib/api.ts）：
 *      fetchRecognitionProfiles  /api/v1/recognition/profiles（Profile 冻结契约）
 *      fetchRecognizeByUrl       /api/v1/recognition/tasks/url（URL 识别，写统一任务表）
 *
 * 结果框渲染：SVG 叠加（viewBox=图片原始尺寸），与审核页同一手法；
 * 框色取类目序列令牌 series-1/2/3 循环，无硬编码色值。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  fetchRecognitionProfiles,
  fetchRecognizeByUrl,
  type RecognitionProfileRow,
  type RecognitionTaskView,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  ApiTable,
  ErrorState,
  errorMessageOf,
  NeedLoginState,
  PageHeader,
} from "@/components/data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { HedgehogLoader } from "@/components/ui/loader";
import { HedgehogMascot } from "@/components/ui/mascot";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   orchestrator 直连契约（:8304）
   ========================================================================== */

/** 本机 orchestrator 基址（CORS 白名单已开，直连）。 */
const ORCH_BASE = "http://127.0.0.1:8304";

/** /recognize/photos 清单条目（_list_photos：manifest-only，不入训练）。 */
interface OrchPhoto {
  id: string;
  sname: string;
  typename: string;
}

/** 检出项（旧契约 box/name/sku_id/confidence + needs_review 显式标记）。 */
interface OrchProduct {
  box: number[];
  sku_id?: string;
  name?: string;
  confidence?: number;
  source?: string;
  needs_review?: boolean;
}

/** /recognize/run 响应。 */
interface OrchRunResult {
  products: OrchProduct[];
  count: number;
  elapsed_ms: number;
}

/* ============================================================================
   序列色令牌（框线循环用；禁止硬编码十六进制）
   ========================================================================== */

const SERIES_TOKENS = [
  "var(--color-series-1)",
  "var(--color-series-2)",
  "var(--color-series-3)",
];

/* ============================================================================
   结果框叠加（SVG viewBox=图片原始像素，随容器等比缩放）
   ========================================================================== */

function BoxOverlay({
  src,
  alt,
  products,
}: {
  src: string;
  alt: string;
  products: OrchProduct[];
}) {
  const [dim, setDim] = useState<{ w: number; h: number } | null>(null);
  return (
    <div className="relative inline-block w-full overflow-hidden rounded-md border border-border bg-background">
      <img
        src={src}
        alt={alt}
        className="block h-auto w-full"
        onLoad={(e) =>
          setDim({
            w: e.currentTarget.naturalWidth,
            h: e.currentTarget.naturalHeight,
          })
        }
      />
      {dim && dim.w > 0 && (
        <svg
          viewBox={`0 0 ${dim.w} ${dim.h}`}
          className="pointer-events-none absolute inset-0 h-full w-full"
          aria-hidden="true"
        >
          {products.map((p, i) => {
            const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = p.box ?? [];
            const c = SERIES_TOKENS[i % SERIES_TOKENS.length];
            return (
              <g key={i}>
                <rect
                  x={x1}
                  y={y1}
                  width={Math.max(0, x2 - x1)}
                  height={Math.max(0, y2 - y1)}
                  fill="none"
                  stroke={c}
                  strokeWidth={Math.max(2, dim.w / 400)}
                />
                <text
                  x={x1 + dim.w / 200}
                  y={Math.max(dim.w / 45, y1 - dim.w / 120)}
                  fill="var(--color-surface)"
                  stroke={c}
                  strokeWidth={Math.max(3, dim.w / 160)}
                  paintOrder="stroke"
                  fontSize={Math.max(12, dim.w / 60)}
                  fontWeight={700}
                >
                  {i + 1}. {p.name || p.sku_id || "unknown"}
                  {typeof p.confidence === "number"
                    ? ` ${Math.round(p.confidence * 100)}%`
                    : ""}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

/* ============================================================================
   识别结果统一视图（直连结果 与 URL 任务结果 共用叠框与明细表）
   ========================================================================== */

type Outcome =
  | {
      kind: "直连 orchestrator";
      src: string;
      caption: string;
      products: OrchProduct[];
      count: number;
      elapsedMs: number;
      note?: string;
    }
  | {
      kind: "同源任务表";
      src: string;
      caption: string;
      products: OrchProduct[];
      view: RecognitionTaskView;
    };

/** 检出明细列。 */
const PRODUCT_COLS = [
  { key: "idx", label: "#", align: "right" as const },
  { key: "name", label: "名称" },
  { key: "confidence", label: "置信度", align: "right" as const },
  { key: "source", label: "来源" },
];

function outcomeRows(products: OrchProduct[]) {
  return products.map((p, i) => ({
    idx: i + 1,
    name: p.name || p.sku_id || "unknown",
    confidence:
      typeof p.confidence === "number"
        ? `${Math.round(p.confidence * 100)}%`
        : "—",
    source: p.source ?? "—",
  }));
}

/* ============================================================================
   页面主体
   ========================================================================== */

export default function Recognize() {
  /* ---- 照片库（orchestrator 直连） ---- */
  const [photos, setPhotos] = useState<OrchPhoto[] | null>(null);
  const [photosErr, setPhotosErr] = useState<unknown>(null);
  const [selectedId, setSelectedId] = useState<string>("");

  /* ---- 识别参数 ---- */
  const [conf, setConf] = useState("0.25");
  const [profiles, setProfiles] = useState<RecognitionProfileRow[] | null>(null);
  const [profilesErr, setProfilesErr] = useState<unknown>(null);
  const [profileId, setProfileId] = useState("production_legacy");
  const [url, setUrl] = useState("");

  /* ---- 执行与结果 ---- */
  const [busy, setBusy] = useState<"direct" | "url" | null>(null);
  const [runErr, setRunErr] = useState<unknown>(null);
  const [runNeedLogin, setRunNeedLogin] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  /** 打开登录窗口（窗口管理器幂等）。 */
  const openWindow = useWindowManager((s) => s.openWindow);
  const closeWindow = useWindowManager((s) => s.closeWindow);
  const openLogin = useCallback(() => {
    openWindow({
      id: "login",
      title: "平台登录",
      content: <LoginWindow onLoggedIn={() => closeWindow("login")} />,
      defaultPosition: { x: 320, y: 180 },
      defaultSize: { width: 360, height: 420 },
    });
  }, [openWindow, closeWindow]);

  /* ---- 照片库加载 ---- */
  const loadPhotos = useCallback(async () => {
    setPhotosErr(null);
    setPhotos(null);
    try {
      const r = await fetch(`${ORCH_BASE}/recognize/photos`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { photos: OrchPhoto[] };
      setPhotos(d.photos ?? []);
    } catch (e) {
      setPhotosErr(
        new Error(
          `${errorMessageOf(e)}（orchestrator ${ORCH_BASE} 未启动或 CORS 被拦截）`,
        ),
      );
    }
  }, []);

  /* ---- Profile 加载（同源；禁用项不进选择器） ---- */
  const loadProfiles = useCallback(async () => {
    setProfilesErr(null);
    try {
      const d = await fetchRecognitionProfiles();
      setProfiles(d.profiles);
      const enabled = d.profiles.filter((p) => p.status === "enabled");
      if (enabled.length > 0 && !enabled.some((p) => p.profile_id === profileId)) {
        setProfileId(enabled[0].profile_id);
      }
    } catch (e) {
      setProfilesErr(e);
    }
  }, [profileId]);

  useEffect(() => {
    void loadPhotos();
    void loadProfiles();
    // 仅在挂载时各拉一次；重试走按钮回调
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const enabledProfiles = useMemo(
    () => (profiles ?? []).filter((p) => p.status === "enabled"),
    [profiles],
  );
  const selectedPhoto = useMemo(
    () => (photos ?? []).find((p) => p.id === selectedId) ?? null,
    [photos, selectedId],
  );

  /* ---- 直连识别（选中照片 → POST /recognize/run） ---- */
  const runDirect = async () => {
    if (!selectedId) return;
    setBusy("direct");
    setRunErr(null);
    setRunNeedLogin(false);
    setOutcome(null);
    try {
      const r = await fetch(`${ORCH_BASE}/recognize/run`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ asset_id: selectedId, conf: Number(conf) }),
      });
      const d = (await r.json().catch(() => ({}))) as Partial<OrchRunResult> & {
        error?: string;
        detail?: string;
      };
      if (!r.ok) {
        throw new Error(
          r.status === 429
            ? `推理队列已满（429），请稍后重试`
            : d.error || d.detail || `HTTP ${r.status}`,
        );
      }
      setOutcome({
        kind: "直连 orchestrator",
        src: `${ORCH_BASE}/recognize/photo/${selectedId}`,
        caption: selectedPhoto ? selectedPhoto.sname || selectedPhoto.id : selectedId,
        products: d.products ?? [],
        count: d.count ?? 0,
        elapsedMs: d.elapsed_ms ?? 0,
        note:
          (d.products ?? []).length === 0
            ? "0 检出：近景/非货架图或不在 registry 内的商品会诚实返回 0（fail-closed），不是故障。"
            : undefined,
      });
    } catch (e) {
      setRunErr(e);
    } finally {
      setBusy(null);
    }
  };

  /* ---- URL 识别（同源统一任务表，Profile 进入请求） ---- */
  const runUrl = async () => {
    const target = url.trim();
    if (!target) return;
    setBusy("url");
    setRunErr(null);
    setRunNeedLogin(false);
    setOutcome(null);
    try {
      const view = await fetchRecognizeByUrl(target, {
        recognition_profile_id: profileId,
        service_tier: "standard",
        source: "web",
      });
      const r0 = (view.results?.[0] ?? {}) as { products?: OrchProduct[] };
      setOutcome({
        kind: "同源任务表",
        src: target,
        caption: `任务 ${view.task.task_id.slice(0, 8)}…`,
        products: r0.products ?? [],
        view,
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setRunNeedLogin(true);
      else setRunErr(e);
    } finally {
      setBusy(null);
    }
  };

  const working = busy !== null;

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="识别工作台"
        desc="本机照片库选图直连识别（orchestrator :8304），或经 URL 提交进统一任务表；结果框 SVG 叠加渲染"
      />

      {/* ① 照片库（orchestrator 直连 :8304/recognize/photos） */}
      <section className="rounded-md border border-border bg-surface p-3">
        <header className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium text-text-primary">
            照片库
            <span className="ml-2 text-xs font-normal text-text-secondary">
              {photos ? `${photos.length} 张 · manifest-only` : "orchestrator 直连"}
            </span>
          </h2>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void loadPhotos()}
            disabled={working}
          >
            刷新
          </Button>
        </header>
        {photos === null && photosErr === null && (
          <div className="flex justify-center py-6">
            <HedgehogLoader className="h-8 w-auto" />
          </div>
        )}
        {photosErr !== null && (
          <ErrorState
            message={errorMessageOf(photosErr)}
            onRetry={() => void loadPhotos()}
          />
        )}
        {photos !== null && photos.length === 0 && (
          <div className="flex flex-col items-center gap-1.5 py-6">
            <HedgehogMascot className="h-16 w-auto" />
            <p className="text-xs text-text-secondary">
              照片库为空（.training_data/manifest.json 无照片）
            </p>
          </div>
        )}
        {photos !== null && photos.length > 0 && (
          <div className="grid max-h-64 grid-cols-[repeat(auto-fill,minmax(96px,1fr))] gap-2 overflow-y-auto pr-1">
            {photos.map((p) => {
              const active = p.id === selectedId;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setSelectedId(active ? "" : p.id)}
                  aria-pressed={active}
                  className={cn(
                    "group cursor-pointer overflow-hidden rounded-md border bg-background text-left",
                    "transition-colors duration-200 ease-out outline-none",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                    active
                      ? "border-accent"
                      : "border-border hover:border-accent",
                  )}
                >
                  <img
                    src={`${ORCH_BASE}/recognize/photo/${p.id}`}
                    alt={p.sname || p.id}
                    loading="lazy"
                    className="aspect-[4/3] w-full object-cover"
                  />
                  <span className="block truncate px-1.5 py-1 text-[11px] text-text-secondary">
                    {p.sname || p.id}
                    {p.typename ? ` · ${p.typename}` : ""}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* ② 触发识别：直连（选中照片） / 同源（URL + Profile） */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="space-y-2 rounded-md border border-border bg-surface p-3">
          <h2 className="text-sm font-medium text-text-primary">
            ① 选中照片直连识别
          </h2>
          <p className="text-xs text-text-secondary">
            POST :8304/recognize/run（asset_id）；本机回环鉴权，推理队列满时返回 429
          </p>
          <div className="flex items-center gap-2">
            <Select
              aria-label="置信度阈值"
              className="w-32"
              value={conf}
              onChange={(e) => setConf(e.target.value)}
            >
              <option value="0.15">conf 0.15（宽松）</option>
              <option value="0.25">conf 0.25（默认）</option>
              <option value="0.4">conf 0.40（严格）</option>
            </Select>
            <Button
              size="sm"
              disabled={!selectedId || working}
              onClick={() => void runDirect()}
            >
              {busy === "direct" ? "识别中…" : "开始识别"}
            </Button>
            <span className="min-w-0 truncate text-xs text-text-secondary">
              {selectedPhoto
                ? `${selectedPhoto.sname || selectedPhoto.id}${
                    selectedPhoto.typename ? ` · ${selectedPhoto.typename}` : ""
                  }`
                : "未选择照片"}
            </span>
          </div>
        </section>

        <section className="space-y-2 rounded-md border border-border bg-surface p-3">
          <h2 className="text-sm font-medium text-text-primary">
            ② URL 识别（写入统一任务表）
          </h2>
          <p className="text-xs text-text-secondary">
            同源 /api/v1/recognition/tasks/url；Profile 随请求提交，服务端只接受已注册且启用的 Profile
          </p>
          {profilesErr !== null ? (
            <ErrorState
              message={`Profile 加载失败：${errorMessageOf(profilesErr)}`}
              onRetry={() => void loadProfiles()}
            />
          ) : (
            <div className="flex items-center gap-2">
              <Input
                aria-label="图片 URL"
                placeholder="http(s)://…/photo.jpg"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !working && url.trim()) void runUrl();
                }}
              />
              <Select
                aria-label="识别 Profile"
                className="w-44"
                value={profileId}
                onChange={(e) => setProfileId(e.target.value)}
                disabled={profiles === null}
              >
                {profiles === null && <option value={profileId}>加载中…</option>}
                {enabledProfiles.map((p) => (
                  <option key={p.profile_id} value={p.profile_id}>
                    {p.display_name || p.profile_id}
                  </option>
                ))}
              </Select>
              <Button
                size="sm"
                disabled={working || !url.trim()}
                onClick={() => void runUrl()}
              >
                {busy === "url" ? "提交中…" : "识别"}
              </Button>
            </div>
          )}
        </section>
      </div>

      {/* 执行反馈：需要登录 / 错误 */}
      {runNeedLogin && <NeedLoginState onOpenLogin={openLogin} />}
      {runErr !== null && (
        <ErrorState message={`识别失败：${errorMessageOf(runErr)}`} />
      )}
      {working && (
        <div className="flex justify-center py-4">
          <HedgehogLoader className="h-8 w-auto" />
        </div>
      )}

      {/* ③ 结果：叠框渲染 + 摘要 + 检出明细 */}
      {outcome && !working && (
        <section className="space-y-3 rounded-md border border-border bg-surface p-3">
          <header className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium text-text-primary">
              结果 · {outcome.caption}
            </h2>
            <p className="text-xs text-text-secondary">
              {outcome.kind === "直连 orchestrator" ? (
                <>
                  检出 {outcome.count} 个 · 耗时 {outcome.elapsedMs} ms
                </>
              ) : (
                <>
                  检出 {outcome.view.task.sku_count} 个 · 耗时{" "}
                  {outcome.view.elapsed_ms} ms · profile{" "}
                  {outcome.view.recognition_profile_id ?? "—"} · trace{" "}
                  {outcome.view.trace_id ?? "—"}
                  {outcome.view.idempotent_replay && " · 幂等重放"}
                </>
              )}
            </p>
          </header>

          {outcome.kind === "同源任务表" && outcome.view.errors.length > 0 && (
            <ul className="space-y-0.5 rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
              {outcome.view.errors.map((e) => (
                <li key={e} className="text-xs text-text-secondary">
                  {e}
                </li>
              ))}
            </ul>
          )}

          <BoxOverlay
            src={outcome.src}
            alt={`识别结果叠框图：${outcome.caption}`}
            products={outcome.products}
          />

          {outcome.kind === "直连 orchestrator" && outcome.note && (
            <p className="text-xs text-text-secondary">{outcome.note}</p>
          )}
          {outcome.kind === "同源任务表" && outcome.products.length === 0 && (
            <p className="text-xs text-text-secondary">
              0 检出：近景/非货架图或不在 registry 内的商品会诚实返回 0（fail-closed），不是故障。
            </p>
          )}

          {outcome.products.length > 0 && (
            <ApiTable
              rows={outcomeRows(outcome.products)}
              cols={PRODUCT_COLS}
              rowKey={(r) => String(r.idx)}
              emptyText="无检出"
            />
          )}
        </section>
      )}
    </div>
  );
}
