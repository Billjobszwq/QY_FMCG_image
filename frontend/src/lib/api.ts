/* eslint-disable @typescript-eslint/no-explicit-any --
   契约类型自 web/src/api.ts 原样移植（同路径同类型），
   弹性载荷字段保持 any，不做本地收窄以免与后端契约漂移。 */
/**
 * 同源 typed API client（v3 基础层）。
 *
 * —— 一切业务数据走同源 /api/v1/*，禁止样本/假数据进入 UI；
 * —— 从 web/src/api.ts 全量移植：路径与类型一一对应，函数统一 fetchXxx；
 * —— credentials 固定 "same-origin"（session 由 HttpOnly cookie 承载）；
 * —— mutations 按 src/platform/auth.py 契约携带 CSRF：
 *      session cookie 为 platform_session（HttpOnly，JS 不可读），
 *      CSRF token 由 /api/v1/auth/login 与 /api/v1/auth/me 响应体的
 *      csrf_token 字段下发，写操作放入请求头 X-CSRF-Token。
 *      csrfToken() 优先读内存缓存，其次兼容扫描 document.cookie 中
 *      可能存在的 csrf_token（后端未来若下发 cookie 形态即可生效）。
 * —— 错误统一抛 ApiError（携带 HTTP status）：
 *      status === 401 → 页面展示“需要登录”状态；
 *      status === 0   → 网络错误（ErrorState + 重试）。
 */

/** 携带 HTTP 状态的接口错误；status=0 表示网络层失败。 */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/* ============================================================================
   CSRF helper（src/platform/auth.py：SESSION_COOKIE=platform_session，
   CSRF_HEADER=X-CSRF-Token；token 经登录/me 响应体下发）
   ========================================================================== */

let _csrfToken: string | null = null;

/** 当前可用 CSRF token：内存缓存优先，回退扫描 document.cookie。 */
export function csrfToken(): string | null {
  if (_csrfToken) return _csrfToken;
  const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** 写操作统一附加的 CSRF 头。 */
function csrfHeaders(): Record<string, string> {
  const t = csrfToken();
  return t ? { "X-CSRF-Token": t } : {};
}

/* ============================================================================
   底层请求封装
   ========================================================================== */

async function rawFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "网络错误：无法连接平台服务，请检查后端是否启动");
  }
}

/** 将非 2xx 响应转为 ApiError：优先解析后端 detail / error 字段。 */
async function toApiError(r: Response, fallback: string): Promise<ApiError> {
  let detail: unknown;
  let error: unknown;
  try {
    const d = (await r.json()) as { detail?: unknown; error?: unknown };
    detail = d.detail;
    error = d.error;
  } catch {
    /* 非 JSON 错误体，保留兜底文案 */
  }
  const msg =
    typeof detail === "string" && detail
      ? detail
      : typeof error === "string" && error
        ? error
        : fallback || `HTTP ${r.status}`;
  return new ApiError(r.status, msg);
}

async function request<T>(
  url: string,
  init: RequestInit,
  fallback = "",
): Promise<T> {
  const r = await rawFetch(url, init);
  if (!r.ok) throw await toApiError(r, fallback);
  return (await r.json()) as T;
}

async function requestVoid(
  url: string,
  init: RequestInit,
  fallback = "",
): Promise<void> {
  const r = await rawFetch(url, init);
  if (!r.ok) throw await toApiError(r, fallback);
}

function get<T>(url: string, fallback = ""): Promise<T> {
  return request<T>(url, { method: "GET" }, fallback);
}

/** POST JSON（mutation）：自动附加 X-CSRF-Token。 */
function postJson<T>(
  url: string,
  body: unknown,
  extra?: Record<string, string>,
  fallback = "",
): Promise<T> {
  return request<T>(
    url,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...csrfHeaders(),
        ...extra,
      },
      body: JSON.stringify(body),
    },
    fallback,
  );
}

/** PUT JSON（mutation）：自动附加 X-CSRF-Token。 */
function putJson<T>(
  url: string,
  body: unknown,
  fallback = "",
): Promise<T> {
  return request<T>(
    url,
    {
      method: "PUT",
      headers: { "content-type": "application/json", ...csrfHeaders() },
      body: JSON.stringify(body),
    },
    fallback,
  );
}

/** 问卷：保存答卷草稿（PUT，自动附加 X-CSRF-Token）。 */
export function fetchSaveSurveyAnswers(
  responseId: string,
  answers: unknown,
): Promise<unknown> {
  return putJson(
    `/api/v1/survey/responses/${responseId}/answers`,
    answers,
    "保存答卷失败",
  );
}

/** DELETE（mutation）：自动附加 X-CSRF-Token。 */
function delVoid(url: string, fallback = ""): Promise<void> {
  return requestVoid(url, { method: "DELETE", headers: csrfHeaders() }, fallback);
}

/** POST 表单（multipart，不手动设置 content-type）。 */
function postForm<T>(
  url: string,
  form: FormData,
  extra?: Record<string, string>,
  fallback = "",
): Promise<T> {
  return request<T>(
    url,
    { method: "POST", headers: { ...csrfHeaders(), ...extra }, body: form },
    fallback,
  );
}

/* ============================================================================
   平台健康 / 版本 / 能力 / 监控
   ========================================================================== */

export type HealthStatus = "healthy" | "degraded" | "unavailable";

export interface ServiceStatus {
  name: string;
  status: HealthStatus;
  latency_ms: number | null;
  detail: string | null;
  critical: boolean;
  description: string;
}

export interface HealthBody {
  status: HealthStatus;
  generated_at: string;
  services: ServiceStatus[];
}

export async function fetchHealth(): Promise<HealthBody> {
  return get("/api/v1/health", "health");
}

export async function fetchVersion(): Promise<{
  platform: string;
  version: string;
}> {
  return get("/api/v1/version", "version");
}

export interface CapabilityInfo {
  capability_id: string;
  module_id: string;
  module_name: string;
  module_version: string;
  kind: string;
  description: string;
}

export async function fetchCapabilities(): Promise<{
  count: number;
  capabilities: CapabilityInfo[];
}> {
  return get("/api/v1/capabilities", "capabilities");
}

export async function fetchMonitorLive(): Promise<Record<string, unknown>> {
  return get("/api/v1/monitor/live", "monitor");
}

export async function fetchMonitorOverview(): Promise<Record<string, unknown>> {
  return get("/api/v1/monitor/overview", "monitor");
}

/* ============================================================================
   图运行（runs）
   ========================================================================== */

export interface RunRow {
  run_id: string;
  graph_name: string;
  graph_version: string;
  status: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface NodeRow {
  node_name: string;
  seq: number;
  attempt: number;
  status: string;
  started_at: string;
  ended_at: string | null;
  error: string | null;
  output_json: string | null;
}

export interface RunView {
  run: RunRow & { input_json?: unknown; output_json?: unknown };
  nodes: NodeRow[];
  evidence: { evidence_id: string; kind: string; manifest_json: string }[];
}

export async function fetchRuns(): Promise<{ count: number; runs: RunRow[] }> {
  return get("/api/v1/runs", "runs");
}

export async function fetchRun(runId: string): Promise<RunView> {
  return get(`/api/v1/runs/${runId}`, "run");
}

export async function fetchUploadAsset(
  file: File,
): Promise<{ sha256: string; size_bytes: number }> {
  const form = new FormData();
  form.append("file", file);
  return postForm("/api/v1/assets/upload", form, undefined, "upload");
}

export async function fetchStartRun(body: {
  graph_name: string;
  graph_version?: string;
  input: Record<string, unknown>;
  idempotency_key?: string;
}): Promise<RunView> {
  return postJson("/api/v1/runs", body, undefined, "runs");
}

export async function fetchApproveRun(
  runId: string,
  approved: boolean,
  actor = "web-operator",
): Promise<RunView> {
  return postJson(`/api/v1/runs/${runId}/approve`, { approved, actor }, undefined, "approve");
}

/* ============================================================================
   workitems（U2-1）
   ========================================================================== */

export interface WorkItem {
  id: string;
  kind: string;
  status: string;
  status_text: string;
  stage: string;
  title: string;
  owner: string;
  detail: Record<string, unknown>;
  superseded?: boolean;
}

export interface WorkItemsBody {
  count: number;
  items: WorkItem[];
  projection?: "current" | "history" | "all";
  summary: {
    pending_review: number;
    todos: number;
    active: number;
    superseded?: number;
    blocked: string[];
    next_steps: string[];
  };
}

export async function fetchWorkItems(
  projection: "current" | "history" | "all" = "current",
): Promise<WorkItemsBody> {
  return get(`/api/v1/workitems?projection=${projection}`, "workitems");
}

/* ============================================================================
   goals 快速目标（ABOSV2-P0-002，服务端持久化）
   ========================================================================== */

export interface GoalDraft {
  goal_id: string;
  text: string;
  status: "open" | "confirmed" | "cancelled";
  created_by: string;
  created_at: string;
  updated_at: string;
  version: number;
  result: Record<string, any>;
}

export async function fetchCreateGoal(text: string): Promise<GoalDraft> {
  const d = await postJson<{ goal: GoalDraft }>(
    "/api/v1/goals",
    { text },
    undefined,
    "goal 保存失败",
  );
  return d.goal;
}

export async function fetchGoals(status?: string): Promise<{
  count: number;
  goals: GoalDraft[];
}> {
  return get(`/api/v1/goals${status ? `?status=${status}` : ""}`, "goals");
}

export async function fetchGoal(goalId: string): Promise<GoalDraft> {
  const d = await get<{ goal: GoalDraft }>(`/api/v1/goals/${goalId}`, "goal");
  return d.goal;
}

export async function fetchConfirmGoal(goalId: string): Promise<GoalDraft> {
  const d = await postJson<{ goal: GoalDraft }>(
    `/api/v1/goals/${goalId}/confirm`,
    {},
    undefined,
    "goal 确认失败",
  );
  return d.goal;
}

/* ============================================================================
   ABOSV3 T2：首页总控（真实 API，不得硬编码数字）
   ========================================================================== */

export interface HomeCalendarEvent {
  event_id: string;
  title: string;
  kind: string;
  source?: string;
  starts_at: string;
  ends_at?: string | null;
  all_day?: boolean;
  location?: string;
  ref_type?: string;
  ref_id?: string;
  customer_id?: string;
  project_id?: string;
  when?: string;
}

export interface HomeNote {
  note_id: string;
  actor: string;
  content: string;
  pinned: number | boolean;
  created_at: string;
  updated_at: string;
}

export interface HomeActivityRow {
  seq: number;
  type: string;
  text: string;
  at: string;
  run_id: string;
  work_id: string;
  actor: string;
  subject_type: string;
  subject_id: string;
  error: string;
}

export interface HomeWorkItem {
  work_id: string;
  status: string;
  title?: string;
  owner_id?: string;
  due_at?: string | null;
  run_id?: string;
  subject_type?: string;
  subject_id?: string;
  customer_id?: string;
  project_id?: string;
  blockers?: string[];
}

export interface HomeDashboard {
  actor: string;
  todos: Record<string, number>;
  work_items: HomeWorkItem[];
  calendar: HomeCalendarEvent[];
  progress: {
    projects: {
      project_id: string;
      customer_id: string;
      total: number;
      done: number;
      running: number;
      blocked: number;
      waiting: number;
      completion: number;
    }[];
    runs_by_status: Record<string, number>;
    work_total: number;
  };
  activity: HomeActivityRow[];
  capacity: {
    db_bytes: number;
    tables: number;
    platform_dir_bytes: number;
    disk: { total_gb?: number; used_gb?: number; free_gb?: number };
    outbox_pending: number;
    jobs: Record<string, number>;
    migrations: number;
  };
  agent_alerts: {
    kind: string;
    title: string;
    ref_type: string;
    ref_id: string;
    blockers?: string[];
  }[];
  recent: Record<string, Record<string, unknown>[]>;
  notes: HomeNote[];
}

export async function fetchHomeDashboard(): Promise<HomeDashboard> {
  return get("/api/v1/home/dashboard", "home dashboard");
}

export async function fetchCalendarEvents(): Promise<{
  count: number;
  events: HomeCalendarEvent[];
}> {
  return get("/api/v1/calendar/events", "calendar");
}

export async function fetchCreateCalendarEvent(body: {
  title: string;
  starts_at: string;
  ends_at?: string;
  all_day?: boolean;
  location?: string;
  kind?: string;
}): Promise<HomeCalendarEvent> {
  const d = await postJson<{ event: HomeCalendarEvent }>(
    "/api/v1/calendar/events",
    body,
    undefined,
    "日程保存失败",
  );
  return d.event;
}

export async function fetchDeleteCalendarEvent(eventId: string): Promise<void> {
  return delVoid(`/api/v1/calendar/events/${eventId}`, "日程删除失败");
}

export async function fetchNotes(): Promise<{
  count: number;
  notes: HomeNote[];
}> {
  return get("/api/v1/notes", "notes");
}

export async function fetchCreateNote(
  content: string,
  pinned = false,
): Promise<HomeNote> {
  const d = await postJson<{ note: HomeNote }>(
    "/api/v1/notes",
    { content, pinned },
    undefined,
    "便签保存失败",
  );
  return d.note;
}

export async function fetchUpdateNote(
  noteId: string,
  body: { content?: string; pinned?: boolean },
): Promise<HomeNote> {
  const d = await putJson<{ note: HomeNote }>(
    `/api/v1/notes/${noteId}`,
    body,
    "便签更新失败",
  );
  return d.note;
}

export async function fetchDeleteNote(noteId: string): Promise<void> {
  return delVoid(`/api/v1/notes/${noteId}`, "便签删除失败");
}

export async function fetchCurrentWork(): Promise<{
  count: number;
  items: Record<string, unknown>[];
  hash: string;
}> {
  return get("/api/v1/control/current-work", "current-work");
}

/* ============================================================================
   assets 数据中心（U2-2，真实台账）
   ========================================================================== */

export interface AssetsSummary {
  total_refs: number;
  unique_sha: number;
  exact_dup_groups: number;
  rows_without_sha: number;
  purposes: Record<string, number>;
  rows_without_purpose: number;
  leak_frozen_into_training: number;
  sources: string[];
  immutable: boolean;
  note: string;
}

export interface AssetRow {
  asset_id: string;
  source_id: string;
  source_type: string;
  source_uri: string;
  photo_id: string;
  sha256: string;
  registered_at: string;
  purposes: string[];
}

export async function fetchAssetsSummary(): Promise<AssetsSummary> {
  return get("/api/v1/assets/summary", "assets summary");
}

export async function fetchAssetsList(opts?: {
  source_id?: string;
  limit?: number;
  offset?: number;
}): Promise<{ count: number; items: AssetRow[]; purposes_vocab: string[] }> {
  const p = new URLSearchParams();
  if (opts?.source_id) p.set("source_id", opts.source_id);
  p.set("limit", String(opts?.limit ?? 50));
  p.set("offset", String(opts?.offset ?? 0));
  return get(`/api/v1/assets?${p.toString()}`, "assets list");
}

/* ============================================================================
   quality gold 人工金标准（U3-6）
   ========================================================================== */

export interface GoldItem {
  sha256: string;
  source_uri: string;
  stratum: string;
  status: string;
  human_verdict: string | null;
}

export interface GoldStatusBody {
  waiting_human: number;
  done: number;
  items: GoldItem[];
  note?: string;
}

export async function fetchGoldStatus(): Promise<GoldStatusBody> {
  return get("/api/v1/quality/gold/status", "gold status");
}

export async function fetchGoldConfusion(): Promise<Record<string, number>> {
  return get("/api/v1/quality/gold/confusion", "gold confusion");
}

/* ============================================================================
   labeling（M4）
   ========================================================================== */

export interface LabelingBatch {
  batch_id: string;
  name: string;
  assisted_project_id: number | null;
  blind_project_id: number | null;
  task_count: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ReconcileProject {
  project_id: number | null;
  tasks: number;
  annotations_api: number;
  predictions_api: number;
  inbox_events: number;
  inbox_annotation_events: number;
  consistent: boolean;
}

export interface ReconcileReport {
  batch_id: string;
  projects: { assisted: ReconcileProject; blind: ReconcileProject };
  consistent: boolean;
  blind_no_predictions: boolean;
}

export async function fetchLabelingBatches(): Promise<{
  count: number;
  batches: LabelingBatch[];
}> {
  return get("/api/v1/labeling/batches", "labeling batches");
}

export async function fetchCreateLabelingBatch(
  name: string,
): Promise<{ batch: LabelingBatch }> {
  return postJson("/api/v1/labeling/batches", { name }, undefined, "create batch");
}

export async function fetchImportLabelingFiles(
  batchId: string,
  files: File[],
): Promise<Record<string, unknown>> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return postForm(
    `/api/v1/labeling/batches/${batchId}/import`,
    form,
    undefined,
    "import",
  );
}

export async function fetchLabelingReconcile(
  batchId: string,
): Promise<ReconcileReport> {
  return get(`/api/v1/labeling/batches/${batchId}/reconcile`, "reconcile");
}

export async function fetchLabelingInbox(): Promise<{ count: number }> {
  return get("/api/v1/labeling/inbox", "inbox");
}

/* ============================================================================
   training governance（M5）
   ========================================================================== */

export interface TrainingGates {
  training_authorized: boolean;
  registered_snapshots: number;
  reasons: string[];
  can_dry_run: boolean;
  can_train: boolean;
}

export interface TrainingRunRow {
  run_id: string;
  snapshot_id: string | null;
  kind: string;
  status: string;
  publish_status: string;
  plan_json: string;
  command_json: string;
  budget_json: string;
  stop_lines_json: string;
  approved_by: string | null;
  job_id: string;
  created_at: string;
}

export async function fetchTrainingGates(): Promise<TrainingGates> {
  return get("/api/v1/training/gates", "gates");
}

export async function fetchTrainingRuns(): Promise<{
  count: number;
  runs: TrainingRunRow[];
}> {
  return get("/api/v1/training/runs", "training runs");
}

export async function fetchTrainingSnapshots(): Promise<{
  count: number;
  snapshots: Array<Record<string, unknown>>;
}> {
  return get("/api/v1/training/snapshots", "snapshots");
}

export async function fetchDryRunTraining(
  snapshotId: string,
): Promise<{ run: TrainingRunRow }> {
  return postJson(
    "/api/v1/training/runs/dry-run",
    { snapshot_id: snapshotId },
    undefined,
    "dry-run",
  );
}

export async function fetchApproveTrainingPlan(
  runId: string,
): Promise<{ run: TrainingRunRow }> {
  return postJson(
    `/api/v1/training/runs/${runId}/approve-plan`,
    {},
    undefined,
    "approve-plan",
  );
}

export async function fetchEnqueueTraining(
  runId: string,
): Promise<{ run: TrainingRunRow & { job_id: string } }> {
  return postJson(
    `/api/v1/training/runs/${runId}/enqueue`,
    {},
    undefined,
    "enqueue",
  );
}

export async function fetchJobs(): Promise<{
  stats: Record<string, number>;
  count: number;
  jobs: Array<Record<string, unknown>>;
}> {
  return get("/api/v1/jobs", "jobs");
}

export async function fetchBuildGoldQueue(
  size = 500,
): Promise<{ added: number; total_queue: number }> {
  return postJson("/api/v1/quality/gold/build", { size }, undefined, "gold build");
}

export async function fetchSubmitGoldVerdict(
  sha256: string,
  verdict: "pass" | "fail",
): Promise<{ accepted: boolean }> {
  return postJson(
    "/api/v1/quality/gold/verdict",
    { sha256, verdict },
    undefined,
    "gold verdict",
  );
}

/* ============================================================================
   review flow（U4-2）
   ========================================================================== */

export interface ReviewTaskRow {
  task_id: string;
  photo_id: string;
  sha256: string;
  review_mode: string;
  status: string;
  claimed_by: string | null;
  n_reviews: number;
  final_box: number[] | null;
  claim_token: string;
}

export async function fetchReviewStatus(): Promise<{
  n_tasks: number;
  status_distribution: Record<string, number>;
  batch_plan: {
    stage?: string;
    status: string;
    n_total?: number;
    n_finalized?: number;
    agreement_rate?: number | null;
    next_size?: number | null;
    note?: string;
  };
  note: string;
}> {
  return get("/api/v1/review/status", "review status");
}

export async function fetchReviewTasks(): Promise<{
  n_tasks: number;
  tasks: ReviewTaskRow[];
}> {
  return get("/api/v1/review/tasks", "review tasks");
}

export async function fetchClaimReviewTask(claim_token: string): Promise<{
  claimed: boolean;
  task_id: string;
}> {
  return postJson("/api/v1/review/claim", { claim_token }, undefined, "review claim");
}

export async function fetchSubmitReview(
  taskId: string,
  verdict: string,
  box: number[],
  role = "annotator",
): Promise<Record<string, unknown>> {
  return postJson(
    "/api/v1/review/submit",
    { task_id: taskId, verdict, box, role },
    undefined,
    "review submit",
  );
}

export async function fetchExportReview(): Promise<{
  path: string;
  sha256: string;
  n_tasks: number;
  n_finalized: number;
}> {
  return postJson("/api/v1/review/export", {}, undefined, "review export");
}

/* ============================================================================
   Loop v2（U5-2/U5-3）
   ========================================================================== */

export interface LoopTrailItem {
  round: number;
  node: string;
  decision: string;
  reason: string;
  next: string | null;
}

export interface LoopRunRow {
  run_id: string;
  status: string;
  error: string | null;
  stop_reason?: string | null;
  rounds_used?: number;
  waiting_for?: string | null;
  next_node?: string | null;
  cost_nodes?: number;
  created_at: string;
  updated_at: string;
}

export interface LoopRunView extends LoopRunRow {
  trail: LoopTrailItem[];
  cost_detail?: { node_executions: number; quality_evals: number };
}

export async function fetchLoopRuns(): Promise<{
  n_runs: number;
  runs: LoopRunRow[];
}> {
  return get("/api/v1/loops/runs", "loop runs");
}

export async function fetchLoopRun(runId: string): Promise<LoopRunView> {
  return get(`/api/v1/loops/runs/${runId}`, "loop run");
}

export async function fetchStartLoop(body: {
  source_id: string;
  batch_size: number;
  max_rounds: number;
}): Promise<LoopRunView> {
  return postJson("/api/v1/loops/start", body, undefined, "loop start");
}

export async function fetchGateLoop(
  runId: string,
  approved: boolean,
): Promise<LoopRunView> {
  return postJson(
    `/api/v1/loops/runs/${runId}/gate`,
    { approved },
    undefined,
    "loop gate",
  );
}

/* ============================================================================
   auth（UMT-006）
   —— session cookie：platform_session（HttpOnly）；
   —— CSRF：login/me 响应体下发 csrf_token，写操作放 X-CSRF-Token 头。
   ========================================================================== */

export interface AuthMe {
  actor: string;
  role: string;
}

export async function fetchAuthLogin(
  username: string,
  password: string,
): Promise<AuthMe> {
  const d = await request<AuthMe & { csrf_token?: string }>(
    "/api/v1/auth/login",
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password }),
    },
    "login",
  );
  if (d.csrf_token) _csrfToken = d.csrf_token;
  return { actor: d.actor, role: d.role };
}

/** 读取当前会话；401 时抛 ApiError(status=401)，由调用方映射为未登录。 */
export async function fetchAuthMe(): Promise<AuthMe> {
  const d = await request<AuthMe & { csrf_token?: string }>(
    "/api/v1/auth/me",
    { method: "GET" },
    "me",
  );
  // 页面刷新后从服务端恢复 CSRF token（session 已验证，返回安全）
  if (d.csrf_token) _csrfToken = d.csrf_token;
  return { actor: d.actor, role: d.role };
}

export async function fetchAuthLogout(): Promise<void> {
  try {
    await requestVoid(
      "/api/v1/auth/logout",
      { method: "POST", headers: csrfHeaders() },
      "logout",
    );
  } finally {
    _csrfToken = null;
  }
}

/* ============================================================================
   recognition tasks（U2-3）
   ========================================================================== */

export interface RecognitionTaskRow {
  task_id: string;
  entry: string;
  status: string;
  file_count: number;
  sku_count: number;
  created_by: string;
  created_at: string;
  error: string;
  recognition_profile_id?: string;
  service_tier?: string;
  source?: string;
  project_id?: string;
  trace_id?: string;
}

export interface RecognitionTaskDetail {
  task: RecognitionTaskRow;
  contract: {
    recognition_profile_id: string;
    service_tier: string;
    source: string;
    project_id: string;
    trace_id: string;
    idempotency_key: string | null;
  };
  inputs: { entry: string; file_count: number };
  outputs: { status: string; sku_count: number; results: any[] };
  errors: string[];
  timeline: Array<{ at: string; event: string; detail: string }>;
  usage: { events: any[]; note: string };
  evidence: { refs: any[]; note: string };
  relations: {
    work_id: string | null;
    run_id: string | null;
    parent_task_id: string | null;
    child_task_ids: string[];
    note: string;
  };
  next_actions: string[];
}

export async function fetchRecognitionTaskDetail(
  taskId: string,
): Promise<RecognitionTaskDetail> {
  return get(`/api/v1/recognition/tasks/${taskId}`, "recognition task detail");
}

/* ============================================================================
   Workflow Studio（ABOSV2 Phase C）
   ========================================================================== */

export interface WorkflowDefinition {
  definition_id: string;
  version: number;
  name: string;
  status: string;
  spec: Record<string, any>;
  lint_report: Array<{ level: string; code: string; message: string }>;
  published_at: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export async function fetchWorkflows(): Promise<{
  count: number;
  definitions: WorkflowDefinition[];
}> {
  return get("/api/v1/workflows", "workflows");
}

export async function fetchWorkflow(
  definitionId: string,
  version?: number,
): Promise<{ definition: WorkflowDefinition }> {
  const q = version ? `?version=${version}` : "";
  return get(`/api/v1/workflows/${definitionId}${q}`, "workflow");
}

export async function fetchCreateWorkflowDraft(opts: {
  name?: string;
  spec?: Record<string, any>;
  template_id?: string;
}): Promise<{ definition: WorkflowDefinition }> {
  return postJson("/api/v1/workflows", opts, undefined, "创建草稿失败");
}

export async function fetchUpdateWorkflowDraft(
  definitionId: string,
  opts: { name?: string; spec?: Record<string, any> },
): Promise<{ definition: WorkflowDefinition }> {
  // FastAPI 路由为 PUT
  return putJson(`/api/v1/workflows/${definitionId}`, opts, "更新草稿失败");
}

export async function fetchWorkflowAction(
  definitionId: string,
  action:
    | "lint"
    | "simulate"
    | "approve"
    | "publish"
    | "deprecate"
    | "new-version",
  inputs?: Record<string, any>,
): Promise<any> {
  return postJson(
    `/api/v1/workflows/${definitionId}/${action}`,
    action === "simulate" ? { inputs: inputs ?? {} } : {},
    undefined,
    `${action} 失败`,
  );
}

export async function fetchStartWorkflowRun(
  definitionId: string,
  inputs: Record<string, any>,
  version?: number,
): Promise<any> {
  return postJson(
    `/api/v1/workflows/${definitionId}/runs`,
    { inputs, version: version ?? null },
    undefined,
    "启动运行失败",
  );
}

export async function fetchWorkflowRunAction(
  runId: string,
  action: "approve" | "pause" | "resume" | "cancel" | "retry",
  body?: Record<string, any>,
): Promise<any> {
  return postJson(
    `/api/v1/workflows/runs/${runId}/${action}`,
    body ?? (action === "approve" ? { decision: "approved" } : {}),
    undefined,
    `${action} 失败`,
  );
}

export async function fetchWorkflowRun(runId: string): Promise<any> {
  return get(`/api/v1/workflows/runs/${runId}`, "workflow run");
}

export async function fetchNodeLibrary(): Promise<{
  node_types: string[];
  command_nodes: Array<{
    node_type: string;
    capability: string;
    module: string;
    kind: string;
  }>;
  connectors: Record<string, { available: boolean; reason: string }>;
  templates: Array<{ template_id: string; name: string }>;
}> {
  return get("/api/v1/workflows/node-library", "node-library");
}

export async function fetchWorkflowAgentDraft(text: string): Promise<any> {
  return postJson(
    "/api/v1/workflows/agent-draft",
    { text },
    undefined,
    "Agent 草稿失败",
  );
}

export async function fetchControlProjection(): Promise<{
  count: number;
  items: any[];
  hash: string;
}> {
  return get("/api/v1/control/projection", "projection");
}

export async function fetchControlReconcile(): Promise<{
  consistent: boolean;
  projection: { count: number; hash: string };
  event_count: number;
  outbox: Record<string, number>;
}> {
  return get("/api/v1/control/reconcile", "reconcile");
}

/* ============================================================================
   IAM 与主数据（ABOSV2 Phase D）
   ========================================================================== */

export async function fetchIamWhoami(): Promise<{
  actor: string;
  session_role: string;
  roles: string[];
  scopes: string[];
  memberships: Array<{
    role: string;
    customer_id: string;
    project_id: string;
  }>;
  visible_customer: string | null;
}> {
  return get("/api/v1/iam/whoami", "whoami");
}

/** IAM / 主数据写操作的通用通道（路径自动补 /api/v1 前缀）。 */
export async function fetchIamPost(path: string, body: unknown): Promise<any> {
  return postJson(`/api/v1/${path.replace(/^\/+/, "")}`, body, undefined, path);
}

/** IAM / 主数据读操作的通用通道（路径自动补 /api/v1 前缀）。 */
export async function fetchIamGet(path: string): Promise<any> {
  return get(`/api/v1/${path.replace(/^\/+/, "")}`, path);
}

/* ============================================================================
   recognition 识别（含 Profile 冻结契约 T7）
   ========================================================================== */

export interface RecognitionProduct {
  box: number[];
  sku_id: string;
  name: string;
  confidence: number;
  margin: number | null;
  yolo_name: string | null;
  yolo_confidence: number | null;
  source: string;
  needs_review: boolean;
}

export interface RecognitionResult {
  capability: string;
  run_id: string;
  products: RecognitionProduct[];
  count: number;
  elapsed_ms: number;
  bridge_elapsed_ms: number;
  model: string;
}

export interface RecognitionTaskView {
  task: RecognitionTaskRow;
  results: Array<Record<string, unknown> & { name?: string }>;
  errors: string[];
  elapsed_ms: number;
  // ABOS T7：冻结契约回显
  recognition_profile_id?: string;
  profile_components?: string[];
  profile_status?: string;
  service_tier?: string;
  source?: string;
  trace_id?: string;
  idempotent_replay?: boolean;
}

// ABOS T7：识别请求选项（Profile 必须真正进入请求）
export interface RecognitionRequestOpts {
  recognition_profile_id: string;
  service_tier?: string;
  source?: "web" | "api" | "agent";
  project_id?: string;
}

export interface RecognitionProfileRow {
  profile_id: string;
  display_name?: string;
  frozen_mapping?: string;
  status: "enabled" | "disabled";
  blockers: string[];
  tags: string[];
  components: string[];
  scopes: string[];
}

export async function fetchRecognitionProfiles(): Promise<{
  count: number;
  profiles: RecognitionProfileRow[];
}> {
  return get("/api/v1/recognition/profiles", "recognition profiles");
}

export async function fetchUploadRecognitionFiles(
  files: File[],
  opts?: RecognitionRequestOpts,
): Promise<RecognitionTaskView> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  form.append(
    "recognition_profile_id",
    opts?.recognition_profile_id ?? "production_legacy",
  );
  form.append("service_tier", opts?.service_tier ?? "standard");
  form.append("source", opts?.source ?? "web");
  if (opts?.project_id) form.append("project_id", opts.project_id);
  // 幂等键（UMT-109）：同一次提交重试不会重复创建任务
  const idem = { "Idempotency-Key": crypto.randomUUID() };
  return postForm("/api/v1/recognition/tasks/upload", form, idem, "recognition upload");
}

export async function fetchRecognizeByUrl(
  url: string,
  opts?: RecognitionRequestOpts,
): Promise<RecognitionTaskView> {
  const idem = { "Idempotency-Key": crypto.randomUUID() };
  return postJson(
    "/api/v1/recognition/tasks/url",
    {
      url,
      recognition_profile_id: opts?.recognition_profile_id ?? "production_legacy",
      service_tier: opts?.service_tier ?? "standard",
      source: opts?.source ?? "web",
      project_id: opts?.project_id ?? "",
    },
    idem,
    "recognition url",
  );
}

export async function fetchRecognitionTasks(opts?: {
  limit?: number;
  offset?: number;
  status?: string;
}): Promise<{ count: number; tasks: RecognitionTaskRow[] }> {
  const q = new URLSearchParams();
  q.set("limit", String(opts?.limit ?? 100));
  if (opts?.offset) q.set("offset", String(opts.offset));
  if (opts?.status) q.set("status", opts.status);
  return get(`/api/v1/recognition/tasks?${q}`, "recognition tasks");
}

export async function fetchRecognizeFile(
  file: File,
  conf = 0.25,
): Promise<RecognitionResult> {
  const form = new FormData();
  form.append("file", file);
  return postForm(`/api/v1/recognition/recognize?conf=${conf}`, form, undefined, "recognize");
}

/* ============================================================================
   cascade 统一级联任务（VLM-016，shadow 默认）
   ========================================================================== */

export interface CascadeTaskRow {
  task_id: string;
  entry: string;
  status: string;
  file_count: number;
  sku_count: number;
  created_by: string;
  created_at: string;
  result_json: string | null;
}

export interface CascadeSla {
  sla_hours: number;
  remaining_hours: number;
  expired: boolean;
}

export interface CascadeTaskDetail {
  task: CascadeTaskRow;
  run_id: string | null;
  result: Record<string, unknown> | null;
  billing: Array<Record<string, unknown>>;
  remaining_sla: CascadeSla | null;
}

export interface CascadeTrailItem {
  round?: number;
  node: string;
  decision: string;
  reason: string;
  detail?: Record<string, unknown>;
}

export async function fetchCascadeTasks(): Promise<{
  count: number;
  tasks: CascadeTaskRow[];
}> {
  return get("/api/v1/cascade/tasks", "cascade tasks");
}

export async function fetchCascadeTask(taskId: string): Promise<CascadeTaskDetail> {
  return get(`/api/v1/cascade/tasks/${taskId}`, "cascade task");
}

export async function fetchCascadeRegions(taskId: string): Promise<{
  regions: Array<Record<string, unknown>>;
}> {
  return get(`/api/v1/cascade/tasks/${taskId}/regions`, "cascade regions");
}

export async function fetchCascadeTrail(taskId: string): Promise<{
  trail: CascadeTrailItem[];
}> {
  return get(`/api/v1/cascade/tasks/${taskId}/trail`, "cascade trail");
}

export async function fetchCancelCascadeTask(
  taskId: string,
): Promise<{ status: string }> {
  return postJson(
    `/api/v1/cascade/tasks/${taskId}/cancel`,
    {},
    undefined,
    "cascade cancel",
  );
}

/* ============================================================================
   models/runtime 模型驻留（VLM-016）
   ========================================================================== */

export interface ModelRuntimeRow {
  model_id: string;
  residency: string;
  state: string;
  max_concurrency: number;
  idle_ttl_s: number;
  last_used_at: string | null;
  active_leases: number;
  leases: Array<Record<string, unknown>>;
}

export async function fetchModelsRuntime(): Promise<{
  count: number;
  models: ModelRuntimeRow[];
}> {
  return get("/api/v1/models/runtime", "models runtime");
}

/* ============================================================================
   packaging 新包装裁决（VLM-016）
   ========================================================================== */

export interface PackageDecisionRow {
  decision_id: string;
  sku_id: string;
  display_name: string;
  package_version_id: string;
  status: string;
  source: string;
  run_id: string | null;
  evidence_json: string | null;
  name_choice: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export async function fetchPackageDecisions(opts?: {
  status?: string;
  sku_id?: string;
}): Promise<{ count: number; decisions: PackageDecisionRow[] }> {
  const q = new URLSearchParams();
  if (opts?.status) q.set("status", opts.status);
  if (opts?.sku_id) q.set("sku_id", opts.sku_id);
  return get(`/api/v1/packaging/decisions?${q}`, "packaging decisions");
}

export async function fetchFinalizePackageDecision(
  decisionId: string,
  body: {
    status: string;
    name_choice?: string | null;
    new_sku_id?: string | null;
    display_name?: string | null;
  },
): Promise<{ decision: PackageDecisionRow }> {
  return postJson(
    `/api/v1/packaging/decisions/${decisionId}/finalize`,
    body,
    undefined,
    "packaging finalize",
  );
}

export async function fetchSupersedePackageDecision(body: {
  older_id: string;
  newer_id: string;
  reason?: string;
}): Promise<{ superseded: boolean }> {
  return postJson("/api/v1/packaging/supersede", body, undefined, "packaging supersede");
}

/* ============================================================================
   GLTC：四训练通道统一控制面
   ========================================================================== */

export interface LaneBlocker {
  code: string;
  detail: string;
}

export interface LaneReadiness {
  lane: string;
  lineage_family: string;
  ready: boolean;
  blockers: LaneBlocker[];
  gold_regions: number;
  runs?: unknown[];
  latest_candidate?: unknown;
}

export interface TrainingLanesBody {
  production: {
    bundle_id: string;
    status: string;
    serving: boolean;
    lineage: string;
  };
  lanes: Record<string, LaneReadiness>;
  note: string;
}

export interface TrainingOverviewBody {
  production: TrainingLanesBody["production"];
  lanes: Record<string, boolean>;
  gold: { usable_regions: number; statuses: string[] };
  leases: { run_id: string; resource: string; mode: string }[];
  training_authorized: boolean;
}

export interface LegacyModelRow {
  model_id: string;
  path: string;
  status: string;
  weights_json: string;
  git_commit: string;
  registered_at: string;
}

export async function fetchTrainingLanes(): Promise<TrainingLanesBody> {
  return get("/api/v1/training/lanes", "training lanes");
}

export async function fetchTrainingOverview(): Promise<TrainingOverviewBody> {
  return get("/api/v1/training/overview", "training overview");
}

export async function fetchLegacyModels(): Promise<{
  count: number;
  models: LegacyModelRow[];
}> {
  return get("/api/v1/training/legacy-models", "legacy models");
}

export async function fetchTrainingRunsV2(): Promise<{
  count: number;
  runs: Record<string, unknown>[];
}> {
  return get("/api/v1/training/runs-v2", "training runs-v2");
}

/* ============================================================================
   SLTF：Agent / Blackboard / TaskBoard
   ========================================================================== */

export interface AgentInfo {
  agent_id: string;
  version: string;
  domain: string;
  risk_level: string;
}

export async function fetchAgents(): Promise<{
  count: number;
  agents: AgentInfo[];
}> {
  return get("/api/v1/agents", "agents");
}

export async function fetchBlackboard(): Promise<{
  count: number;
  events: any[];
}> {
  return get("/api/v1/blackboard", "blackboard");
}

export async function fetchTaskboard(): Promise<{
  states: Record<string, any[]>;
}> {
  return get("/api/v1/taskboard", "taskboard");
}

/* ============================================================================
   ABOS T6：Agent 命令审批（服务端持久化 + 审计）
   ========================================================================== */

export async function fetchApproveAgentCommand(commandId: string): Promise<any> {
  return postJson(
    `/api/agent/v1/commands/${commandId}/approve`,
    {},
    undefined,
    "command approve",
  );
}

export async function fetchRejectAgentCommand(commandId: string): Promise<any> {
  return postJson(
    `/api/agent/v1/commands/${commandId}/reject`,
    {},
    undefined,
    "command reject",
  );
}

export async function fetchCreateAgentSession(title: string): Promise<string> {
  const d = await postJson<{ session_id: string }>(
    "/api/agent/v1/sessions",
    { title },
    undefined,
    "agent session",
  );
  return d.session_id;
}

export async function fetchAgentChat(sessionId: string, text: string): Promise<any> {
  return postJson(
    "/api/agent/v1/chat",
    { session_id: sessionId, text },
    undefined,
    "agent chat",
  );
}
