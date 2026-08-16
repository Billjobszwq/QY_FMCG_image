/**
 * 问卷中心（P8）：设计 / 分配与填写 / 报表输入 三页签。
 *
 * 数据源（同源 /api/v1/survey/*，与 web/src/pages/Survey.tsx 一致）：
 * —— GET  survey/definitions            问卷定义列表（含 spec/lint_report）
 * —— POST survey/definitions            从样板模板实例化草稿
 * —— POST survey/definitions/{id}/lint | publish | new-version
 * —— GET  survey/assignments            分配列表
 * —— POST survey/assignments            新建分配
 * —— POST survey/responses              开始填写（开卷）
 * —— PUT  survey/responses/{id}/answers 保存草稿（api.ts 暂未提供通用 PUT
 *         通道，按 web 原实现本地封装，仍走同源 + CSRF）
 * —— POST survey/responses/{id}/submit  提交（自动评分）
 * —— POST survey/responses/{id}/media   照片证据（识别建议需人工终审）
 * —— POST survey/media/{id}/review      建议终审（accepted/rejected）
 * —— GET  survey/report?survey_id=      报表输入（final 答案 + 评分版本聚合）
 */
import { useEffect, useState } from "react";
import {
  ApiError,
  fetchIamGet,
  fetchIamPost,
  fetchSaveSurveyAnswers,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  ApiTable,
  errorMessageOf,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { HedgehogLoader } from "@/components/ui/loader";
import { HedgehogMascot } from "@/components/ui/mascot";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   类型（与后端弹性契约对齐，字段均按 web 实际消费面声明）
   ========================================================================== */

interface SurveyOption {
  value: string;
  label?: string;
  sku_ref?: string;
}

interface SurveyQuestion {
  id: string;
  type: string;
  title?: string;
  required?: boolean;
  options?: SurveyOption[];
  input_type?: string;
  min?: number;
  max?: number;
  capture_role?: string;
  require_storefront?: boolean;
}

interface SurveyDefinition {
  survey_id: string;
  name?: string;
  version: number;
  status: string;
  spec?: { questions?: SurveyQuestion[]; logic_edges?: unknown[] };
  lint_report?: { level: string; code: string; message: string }[];
}

interface SurveyAssignment {
  assignment_id: string;
  survey_id: string;
  survey_version: number;
  customer_id?: string;
  assignee?: string;
  status: string;
}

interface SurveyMedia {
  media_id: string;
  capture_role?: string;
  status?: string;
  suggestion_status?: string;
  suggestion?: { task_id?: string };
}

interface SurveyResponse {
  response_id: string;
  survey_id: string;
  survey_version: number;
  status: string;
  scores?: { total?: number; scoring_version?: string | number };
  score_version?: string | number;
}

interface SurveyReportItem {
  response_id: string;
  respondent?: string;
  status: string;
  scores?: { total?: number; scoring_version?: string | number };
}

interface SurveyReportBody {
  responses: number;
  submitted: number;
  total_score: number;
  avg_score?: number;
  score_version_max: string | number;
  items?: SurveyReportItem[];
}

/* ============================================================================
   本地小件：加载钩子 / 401 判定 / 页签 / 状态映射 / PUT 通道
   ========================================================================== */

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: unknown;
}

/** 通用加载态：data/loading/error/reload；fetcher 传 null 表示暂不请求。 */
function useApi<T>(
  fetcher: (() => Promise<T>) | null,
  deps: readonly unknown[] = [],
): ApiState<T> & { reload: () => void } {
  const [st, setSt] = useState<ApiState<T>>({
    data: null,
    loading: fetcher !== null,
    error: null,
  });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!fetcher) {
      setSt({ data: null, loading: false, error: null });
      return;
    }
    let alive = true;
    setSt((s) => ({ data: s.data, loading: true, error: null }));
    fetcher().then(
      (d) => {
        if (alive) setSt({ data: d, loading: false, error: null });
      },
      (e: unknown) => {
        if (alive) setSt((s) => ({ data: s.data, loading: false, error: e }));
      },
    );
    return () => {
      alive = false;
    };
    // 依赖由调用方显式给出（含客户/页签等），闭包不参与比较
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);
  return { ...st, reload: () => setTick((t) => t + 1) };
}

/** 401 → 需要登录（数据红线）。 */
function isNeedLogin(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** 请求打开登录窗口（桌面窗口管理器统一承接）。 */
function useOpenLogin(): () => void {
  const openWindow = useWindowManager((s) => s.openWindow);
  return () =>
    openWindow({
      id: "login",
      title: "平台登录",
      content: <LoginWindow />,
      defaultPosition: {
        x: Math.max(24, Math.round(window.innerWidth / 2 - 190)),
        y: Math.max(24, Math.round(window.innerHeight / 2 - 210)),
      },
      defaultSize: { width: 380, height: 420 },
      minWidth: 320,
      minHeight: 380,
    });
}

function TabBar<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { key: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div role="tablist" className="flex items-center gap-1 border-b border-border">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={value === t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "-mb-px cursor-pointer border-b-2 px-3 py-1.5 text-[13px]",
            "transition-colors duration-200 ease-out",
            value === t.key
              ? "border-accent font-medium text-accent"
              : "border-transparent text-text-secondary hover:text-accent",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** 后端状态 → StatusBadge 语义。 */
function statusKindOf(status: string): StatusKind {
  switch (status) {
    case "published":
    case "submitted":
    case "accepted":
    case "completed":
    case "active":
      return "good";
    case "deprecated":
    case "rejected":
    case "failed":
    case "cancelled":
      return "serious";
    case "blocked":
    case "degraded":
    case "waiting_human":
      return "warn";
    default:
      return "neutral";
  }
}

/* ============================================================================
   页签一：问卷设计
   ========================================================================== */

function DesignTab({ openLogin }: { openLogin: () => void }) {
  const defs = useApi<{ definitions?: SurveyDefinition[] }>(
    () => fetchIamGet("survey/definitions"),
    [],
  );
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const PAGE = 10;

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg(`${label}成功`);
      defs.reload();
    } catch (e) {
      setMsg(`${label}失败：${errorMessageOf(e)}`);
    } finally {
      setBusy(false);
    }
  }

  if (isNeedLogin(defs.error)) return <NeedLoginState onOpenLogin={openLogin} />;

  const all = defs.data?.definitions ?? [];
  const hit = all.filter(
    (d) => !q || d.name?.includes(q) || d.survey_id.includes(q),
  );
  const pages = Math.max(1, Math.ceil(hit.length / PAGE));
  const cur = Math.min(page, pages - 1);
  const shown = hit.slice(cur * PAGE, cur * PAGE + PAGE);

  return (
    <div className="space-y-3">
      {/* 从样板模板实例化 */}
      <section className="space-y-1.5 rounded-md border border-border bg-background p-3">
        <h3 className="text-[13px] font-semibold text-text-primary">
          从样板模板创建草稿（含全部首批题型）
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              act("创建", () =>
                fetchIamPost("survey/definitions", {
                  template_id: "tpl_store_visit_v1",
                }),
              )
            }
          >
            实例化门店巡检样板
          </Button>
          {msg && <p className="text-xs text-text-secondary">{msg}</p>}
        </div>
      </section>

      {/* 搜索与分页 */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="搜索问卷名称 / ID"
          aria-label="搜索问卷"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(0);
          }}
          className="w-60"
        />
        <span className="text-xs text-text-secondary">
          共 {hit.length} 条 · 第 {cur + 1}/{pages} 页（后端默认只返回
          operational，测试问卷请在“测试与证据中心”查看）
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={cur === 0}
          onClick={() => setPage(cur - 1)}
        >
          上一页
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={cur >= pages - 1}
          onClick={() => setPage(cur + 1)}
        >
          下一页
        </Button>
      </div>

      {/* 定义列表 */}
      {defs.error && !isNeedLogin(defs.error) ? (
        <div className="rounded-md border border-border bg-background">
          <ErrorBlock message={errorMessageOf(defs.error)} onRetry={defs.reload} />
        </div>
      ) : null}
      {defs.loading && !defs.data && (
        <div className="flex justify-center py-6">
          <HedgehogLoader className="h-8 w-auto" />
        </div>
      )}
      {shown.map((d) => (
        <section
          key={`${d.survey_id}@${d.version}`}
          className="space-y-1.5 rounded-md border border-border bg-background p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-text-primary">
              {d.name ?? d.survey_id}
            </h3>
            <StatusBadge kind={statusKindOf(d.status)}>{d.status}</StatusBadge>
            <span className="text-xs text-text-secondary">
              {d.survey_id} · v{d.version}
            </span>
          </div>
          <p className="text-xs text-text-secondary">
            题目：
            {(d.spec?.questions ?? [])
              .map((qq) => `${qq.id}(${qq.type})`)
              .join("、") || "—"}
            {" "}· 跳题边 {(d.spec?.logic_edges ?? []).length} 条
          </p>
          {(d.lint_report ?? []).length > 0 && (
            <ul className="space-y-1">
              {(d.lint_report ?? []).map((i, k) => (
                <li key={k} className="flex items-start gap-1.5">
                  <StatusBadge kind={i.level === "error" ? "serious" : "warn"}>
                    {i.level}
                  </StatusBadge>
                  <span className="text-xs text-text-secondary">
                    {i.code}: {i.message}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-1.5 pt-1">
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() =>
                act("lint", () =>
                  fetchIamPost(`survey/definitions/${d.survey_id}/lint`, {}),
                )
              }
            >
              lint
            </Button>
            <Button
              size="sm"
              disabled={busy}
              onClick={() =>
                act("发布", () =>
                  fetchIamPost(`survey/definitions/${d.survey_id}/publish`, {}),
                )
              }
            >
              发布
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() =>
                act("新版本", () =>
                  fetchIamPost(
                    `survey/definitions/${d.survey_id}/new-version`,
                    {},
                  ),
                )
              }
            >
              新版本
            </Button>
          </div>
        </section>
      ))}
      {!defs.loading && !defs.error && hit.length === 0 && (
        <div className="flex flex-col items-center gap-1.5 rounded-md border border-border bg-background py-6">
          <HedgehogMascot className="h-16 w-auto" />
          <p className="text-xs text-text-secondary">
            暂无问卷定义：点击上方“实例化门店巡检样板”创建草稿
          </p>
        </div>
      )}
    </div>
  );
}

/** 设计页签的错误块（非 401）：serious 徽章 + 重试。 */
function ErrorBlock({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 py-6">
      <StatusBadge kind="serious">加载失败</StatusBadge>
      <p className="text-xs text-text-secondary">{message}</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}

/* ============================================================================
   页签二：分配与填写
   ========================================================================== */

type AnswerValue = string | number | string[];

function FieldTab({ openLogin }: { openLogin: () => void }) {
  const defs = useApi<{ definitions?: SurveyDefinition[] }>(
    () => fetchIamGet("survey/definitions"),
    [],
  );
  const asgs = useApi<{ assignments?: SurveyAssignment[] }>(
    () => fetchIamGet("survey/assignments"),
    [],
  );
  const [sel, setSel] = useState<SurveyResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, { value: AnswerValue }>>(
    {},
  );
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    survey_id: "",
    customer_id: "",
    assignee: "",
  });

  const needLogin =
    isNeedLogin(asgs.error) || isNeedLogin(defs.error);

  async function openResponse(assignmentId: string) {
    setMsg(null);
    try {
      const out = (await fetchIamPost("survey/responses", {
        assignment_id: assignmentId,
      })) as { response: SurveyResponse };
      setSel(out.response);
      setAnswers({});
    } catch (e) {
      setMsg(`开始填写失败：${errorMessageOf(e)}`);
    }
  }

  const setAnswer = (qid: string, value: AnswerValue) =>
    setAnswers((a) => ({ ...a, [qid]: { value } }));

  const spec = (defs.data?.definitions ?? []).find(
    (d) =>
      sel &&
      d.survey_id === sel.survey_id &&
      d.version === sel.survey_version,
  )?.spec;

  const asgCols: ApiTableCol<SurveyAssignment>[] = [
    { key: "assignment_id", label: "assignment" },
    {
      key: "survey_id",
      label: "问卷",
      render: (a) => (
        <span>
          {a.survey_id}@v{a.survey_version}
        </span>
      ),
    },
    { key: "customer_id", label: "客户" },
    {
      key: "status",
      label: "状态",
      render: (a) => <StatusBadge kind={statusKindOf(a.status)}>{a.status}</StatusBadge>,
    },
    {
      key: "op",
      label: "操作",
      render: (a) => (
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          onClick={() => openResponse(a.assignment_id)}
        >
          开始填写
        </Button>
      ),
    },
  ];

  if (needLogin) return <NeedLoginState onOpenLogin={openLogin} />;

  return (
    <div className="space-y-3">
      {/* 新建分配 */}
      <section className="space-y-1.5 rounded-md border border-border bg-background p-3">
        <h3 className="text-[13px] font-semibold text-text-primary">新建分配</h3>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={form.survey_id}
            aria-label="问卷"
            className="w-64"
            onChange={(e) => setForm({ ...form, survey_id: e.target.value })}
          >
            <option value="">选择已发布问卷…</option>
            {(defs.data?.definitions ?? [])
              .filter((d) => d.status === "published")
              .map((d) => (
                <option key={`${d.survey_id}@${d.version}`} value={d.survey_id}>
                  {d.name ?? d.survey_id}（{d.survey_id}）
                </option>
              ))}
          </Select>
          <Input
            placeholder="customer_id"
            aria-label="客户"
            className="w-40"
            value={form.customer_id}
            onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
          />
          <Input
            placeholder="assignee"
            aria-label="执行人"
            className="w-36"
            value={form.assignee}
            onChange={(e) => setForm({ ...form, assignee: e.target.value })}
          />
          <Button
            size="sm"
            disabled={busy || !form.survey_id}
            onClick={async () => {
              setBusy(true);
              setMsg(null);
              try {
                await fetchIamPost("survey/assignments", {
                  ...form,
                  project_id: "",
                });
                setMsg("分配成功");
                asgs.reload();
              } catch (e) {
                setMsg(`分配失败：${errorMessageOf(e)}`);
              } finally {
                setBusy(false);
              }
            }}
          >
            分配
          </Button>
        </div>
      </section>

      {/* 分配列表 */}
      <ApiTable
        rows={asgs.data?.assignments ?? []}
        cols={asgCols}
        loading={asgs.loading}
        error={asgs.error}
        onRetry={asgs.reload}
        emptyText="暂无分配：先发布问卷再分配"
        rowKey={(a) => a.assignment_id}
      />

      {/* 填写面板 */}
      {sel && (
        <section className="space-y-3 rounded-md border border-border bg-background p-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[13px] font-semibold text-text-primary">
              填写：{sel.response_id}
            </h3>
            <StatusBadge kind={statusKindOf(sel.status)}>{sel.status}</StatusBadge>
          </div>
          {!spec && (
            <p className="text-xs text-text-secondary">
              未在定义列表中找到 {sel.survey_id}@v{sel.survey_version}
              的题目规格，无法渲染题目
            </p>
          )}
          {(spec?.questions ?? []).map((qq) => (
            <div key={qq.id} className="space-y-1">
              <p className="text-[13px] font-medium text-text-primary">
                {qq.id} · {qq.title ?? ""}（{qq.type}）
                {qq.required ? " *" : ""}
              </p>
              {qq.type === "single_choice" && (
                <Select
                  aria-label={qq.id}
                  className="w-64"
                  onChange={(e) => setAnswer(qq.id, e.target.value)}
                >
                  <option value="">选择…</option>
                  {(qq.options ?? []).map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label ?? o.value}
                    </option>
                  ))}
                </Select>
              )}
              {qq.type === "multi_choice" && (
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {(qq.options ?? []).map((o) => {
                    const prev = answers[qq.id]?.value;
                    const checked = Array.isArray(prev) && prev.includes(o.value);
                    return (
                      <label
                        key={o.value}
                        className="inline-flex items-center gap-1 text-xs text-text-secondary"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const cur = Array.isArray(prev) ? prev : [];
                            setAnswer(
                              qq.id,
                              e.target.checked
                                ? [...cur, o.value]
                                : cur.filter((v) => v !== o.value),
                            );
                          }}
                        />
                        {o.label ?? o.value}
                        {o.sku_ref ? "（SKU 库引用）" : ""}
                      </label>
                    );
                  })}
                </div>
              )}
              {qq.type === "text" && (
                <Input
                  aria-label={qq.id}
                  className="w-64"
                  type={qq.input_type === "number" ? "number" : "text"}
                  onChange={(e) =>
                    setAnswer(
                      qq.id,
                      qq.input_type === "number"
                        ? Number(e.target.value)
                        : e.target.value,
                    )
                  }
                />
              )}
              {qq.type === "rating" && (
                <Select
                  aria-label={qq.id}
                  className="w-40"
                  onChange={(e) => setAnswer(qq.id, Number(e.target.value))}
                >
                  <option value="">评分…</option>
                  {Array.from(
                    { length: (qq.max ?? 5) - (qq.min ?? 1) + 1 },
                    (_, i) => (qq.min ?? 1) + i,
                  ).map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </Select>
              )}
              {qq.type === "photo" && (
                <PhotoPanel key={sel.response_id} responseId={sel.response_id} q={qq} />
              )}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setMsg(null);
                try {
                  await fetchSaveSurveyAnswers(sel.response_id, {
                    answers,
                  });
                  setMsg("草稿已保存");
                } catch (e) {
                  setMsg(`保存失败：${errorMessageOf(e)}`);
                } finally {
                  setBusy(false);
                }
              }}
            >
              保存草稿
            </Button>
            <Button
              size="sm"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setMsg(null);
                try {
                  await fetchSaveSurveyAnswers(sel.response_id, {
                    answers,
                  });
                  const out = (await fetchIamPost(
                    `survey/responses/${sel.response_id}/submit`,
                    {},
                  )) as { response: SurveyResponse };
                  setSel(out.response);
                  setMsg(
                    `已提交：总分 ${out.response.scores?.total ?? "—"}（评分版本 ${out.response.score_version ?? "—"}）`,
                  );
                  asgs.reload();
                } catch (e) {
                  setMsg(`提交失败：${errorMessageOf(e)}`);
                } finally {
                  setBusy(false);
                }
              }}
            >
              提交（自动评分）
            </Button>
            {msg && <p className="text-xs text-text-secondary">{msg}</p>}
          </div>
        </section>
      )}
      {!sel && msg && <p className="text-xs text-text-secondary">{msg}</p>}
    </div>
  );
}

/** 拍照题：证据上传 + 识别建议人工终审。 */
function PhotoPanel({
  responseId,
  q,
}: {
  responseId: string;
  q: SurveyQuestion;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [metas, setMetas] = useState({
    lat: "31.23",
    lng: "121.47",
    device: "web-browser",
  });
  const [role, setRole] = useState(q.capture_role ?? "other");
  const [medias, setMedias] = useState<SurveyMedia[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toB64 = (f: File) =>
    new Promise<string>((resolve, reject) => {
      const rd = new FileReader();
      rd.onload = () => resolve(String(rd.result).split(",")[1]);
      rd.onerror = reject;
      rd.readAsDataURL(f);
    });

  return (
    <div className="space-y-2 rounded-md border border-dashed border-border-strong p-2.5">
      {q.require_storefront && (
        <p className="text-xs text-text-secondary">
          门头必拍：必须上传至少 1 张 capture_role=storefront 的照片；缺门头照无法提交
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="file"
          accept="image/*"
          aria-label={`${q.id} 照片`}
          className="text-xs text-text-secondary"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Select
          aria-label="拍摄角色"
          className="w-44"
          value={role}
          onChange={(e) => setRole(e.target.value)}
        >
          <option value="storefront">storefront 门头</option>
          <option value="shelf">shelf 货架</option>
          <option value="employee_selfie">employee_selfie 自拍</option>
          <option value="product">product 商品</option>
          <option value="other">other 其他</option>
        </Select>
        <Input
          aria-label="纬度"
          className="w-24"
          value={metas.lat}
          onChange={(e) => setMetas({ ...metas, lat: e.target.value })}
        />
        <Input
          aria-label="经度"
          className="w-24"
          value={metas.lng}
          onChange={(e) => setMetas({ ...metas, lng: e.target.value })}
        />
        <Input
          aria-label="设备"
          className="w-36"
          value={metas.device}
          onChange={(e) => setMetas({ ...metas, device: e.target.value })}
        />
        <Button
          variant="secondary"
          size="sm"
          disabled={!file || busy}
          onClick={async () => {
            if (!file) return;
            setBusy(true);
            setMsg(null);
            try {
              const out = (await fetchIamPost(
                `survey/responses/${responseId}/media`,
                {
                  question_id: q.id,
                  location: { lat: Number(metas.lat), lng: Number(metas.lng) },
                  taken_at: new Date().toISOString(),
                  device: metas.device,
                  quality: { width: 0, note: "web 上传无质量探测" },
                  image_b64: await toB64(file),
                  capture_role: role,
                },
              )) as { media: SurveyMedia };
              setMedias((m) => [...m, out.media]);
              setMsg(
                `照片已入库（${out.media.capture_role ?? role}）：识别建议 ${out.media.suggestion_status ?? "—"}（需人工终审）`,
              );
            } catch (e) {
              setMsg(`照片上传失败：${errorMessageOf(e)}`);
            } finally {
              setBusy(false);
            }
          }}
        >
          上传（位置/时间/设备证据）
        </Button>
      </div>
      {medias.map((m) => (
        <div
          key={m.media_id}
          className="flex flex-wrap items-center gap-2 text-xs text-text-secondary"
        >
          <span>
            {m.media_id} · 角色 {m.capture_role ?? "other"} · 状态{" "}
            {m.status ?? "active"}
          </span>
          <StatusBadge
            kind={
              m.suggestion_status === "accepted"
                ? "good"
                : m.suggestion_status === "rejected"
                  ? "serious"
                  : "warn"
            }
          >
            建议 {m.suggestion_status ?? "—"}
          </StatusBadge>
          {m.suggestion?.task_id ? `识别任务 ${m.suggestion.task_id}` : ""}
          {m.suggestion_status === "pending" && (
            <span className="flex gap-1.5">
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const out = (await fetchIamPost(
                      `survey/media/${m.media_id}/review`,
                      { decision: "accepted" },
                    )) as { media: SurveyMedia };
                    setMedias((ms) =>
                      ms.map((x) => (x.media_id === m.media_id ? out.media : x)),
                    );
                    setMsg("已接受建议（final answer 生效）");
                  } catch (e) {
                    setMsg(`终审失败：${errorMessageOf(e)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                接受建议
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const out = (await fetchIamPost(
                      `survey/media/${m.media_id}/review`,
                      { decision: "rejected" },
                    )) as { media: SurveyMedia };
                    setMedias((ms) =>
                      ms.map((x) => (x.media_id === m.media_id ? out.media : x)),
                    );
                    setMsg("已拒绝建议（反馈进评估链，training_truth=false）");
                  } catch (e) {
                    setMsg(`终审失败：${errorMessageOf(e)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                拒绝
              </Button>
            </span>
          )}
        </div>
      ))}
      {msg && <p className="text-xs text-text-secondary">{msg}</p>}
      <p className="text-[11px] text-text-secondary">
        识别结果只是 suggestion：接受/拒绝/修改后才成为 final
        answer；反馈进入报表与模型评估链，但不会自动成为训练真值
      </p>
    </div>
  );
}

/* ============================================================================
   页签三：报表输入
   ========================================================================== */

function ReportTab({ openLogin }: { openLogin: () => void }) {
  const defs = useApi<{ definitions?: SurveyDefinition[] }>(
    () => fetchIamGet("survey/definitions"),
    [],
  );
  const [sid, setSid] = useState("");
  const [rep, setRep] = useState<SurveyReportBody | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (isNeedLogin(defs.error) || isNeedLogin(err)) {
    return <NeedLoginState onOpenLogin={openLogin} />;
  }

  const itemCols: ApiTableCol<SurveyReportItem>[] = [
    { key: "response_id", label: "response" },
    { key: "respondent", label: "作答人" },
    {
      key: "status",
      label: "状态",
      render: (it) => (
        <StatusBadge kind={statusKindOf(it.status)}>{it.status}</StatusBadge>
      ),
    },
    {
      key: "total",
      label: "总分",
      align: "right",
      render: (it) => it.scores?.total ?? "—",
    },
    {
      key: "ver",
      label: "评分版本",
      render: (it) => `v${it.scores?.scoring_version ?? "—"}`,
    },
  ];

  return (
    <div className="space-y-3">
      <section className="space-y-2 rounded-md border border-border bg-background p-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={sid}
            aria-label="选择问卷"
            className="w-72"
            onChange={(e) => setSid(e.target.value)}
          >
            <option value="">选择问卷…</option>
            {(defs.data?.definitions ?? []).map((d) => (
              <option key={d.survey_id} value={d.survey_id}>
                {d.name ?? d.survey_id}（{d.survey_id}）
              </option>
            ))}
          </Select>
          <Button
            variant="secondary"
            size="sm"
            disabled={!sid || busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                setRep(
                  (await fetchIamGet(
                    `survey/report?survey_id=${encodeURIComponent(sid)}`,
                  )) as SurveyReportBody,
                );
              } catch (e) {
                setErr(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            生成报表输入
          </Button>
        </div>
        {err ? (
          <ErrorBlock
            message={errorMessageOf(err)}
            onRetry={() => setErr(null)}
          />
        ) : null}
        {rep && (
          <KV
            items={[
              { label: "响应", value: rep.responses },
              { label: "已提交", value: rep.submitted },
              { label: "总分", value: rep.total_score },
              { label: "均分", value: rep.avg_score ?? "—" },
              { label: "评分版本最高", value: rep.score_version_max },
            ]}
          />
        )}
      </section>
      {rep && (
        <ApiTable
          rows={rep.items ?? []}
          cols={itemCols}
          emptyText="该问卷暂无报表条目"
          rowKey={(it) => it.response_id}
        />
      )}
      <p className="text-[11px] text-text-secondary">
        口径：final 答案 + 评分版本聚合；BI 只读消费本端点
      </p>
    </div>
  );
}

/* ============================================================================
   页面入口
   ========================================================================== */

type SurveyTab = "design" | "field" | "report";

export default function SurveyPage() {
  const [tab, setTab] = useState<SurveyTab>("design");
  const openLogin = useOpenLogin();
  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="问卷中心"
        desc="设计（题型/跳题 DAG/评分规则/版本）→ 分配与填写（拍照证据·识别建议人工终审）→ 报表输入；发布后不可原地修改"
      />
      <TabBar<SurveyTab>
        tabs={[
          { key: "design", label: "问卷设计" },
          { key: "field", label: "分配与填写" },
          { key: "report", label: "报表输入" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "design" && <DesignTab openLogin={openLogin} />}
      {tab === "field" && <FieldTab openLogin={openLogin} />}
      {tab === "report" && <ReportTab openLogin={openLogin} />}
    </div>
  );
}
