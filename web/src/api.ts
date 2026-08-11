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

export async function fetchHealth(): Promise<HealthBody> {
  const r = await fetch("/api/v1/health");
  if (!r.ok) throw new Error(`health HTTP ${r.status}`);
  return r.json();
}

export async function fetchVersion(): Promise<{ platform: string; version: string }> {
  const r = await fetch("/api/v1/version");
  return r.json();
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
  const r = await fetch("/api/v1/capabilities");
  if (!r.ok) throw new Error(`capabilities HTTP ${r.status}`);
  return r.json();
}

export async function fetchMonitorLive(): Promise<Record<string, unknown>> {
  const r = await fetch("/api/v1/monitor/live");
  if (!r.ok) throw new Error(`monitor HTTP ${r.status}`);
  return r.json();
}

export async function fetchMonitorOverview(): Promise<Record<string, unknown>> {
  const r = await fetch("/api/v1/monitor/overview");
  if (!r.ok) throw new Error(`monitor HTTP ${r.status}`);
  return r.json();
}

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
  const r = await fetch("/api/v1/runs");
  if (!r.ok) throw new Error(`runs HTTP ${r.status}`);
  return r.json();
}

export async function fetchRun(runId: string): Promise<RunView> {
  const r = await fetch(`/api/v1/runs/${runId}`);
  if (!r.ok) throw new Error(`run HTTP ${r.status}`);
  return r.json();
}

export async function uploadAsset(file: File): Promise<{ sha256: string; size_bytes: number }> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch("/api/v1/assets/upload", { method: "POST", body: form });
  if (!r.ok) throw new Error(`upload HTTP ${r.status}`);
  return r.json();
}

export async function startRun(body: {
  graph_name: string;
  graph_version?: string;
  input: Record<string, unknown>;
  idempotency_key?: string;
}): Promise<RunView> {
  const r = await fetch("/api/v1/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail ?? `runs HTTP ${r.status}`);
  }
  return r.json();
}

export async function approveRun(
  runId: string,
  approved: boolean,
  actor = "web-operator"
): Promise<RunView> {
  const r = await fetch(`/api/v1/runs/${runId}/approve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ approved, actor }),
  });
  if (!r.ok) throw new Error(`approve HTTP ${r.status}`);
  return r.json();
}

// ---------- workitems (U2-1) ----------

export interface WorkItem {
  id: string;
  kind: string;
  status: string;
  status_text: string;
  stage: string;
  title: string;
  owner: string;
  detail: Record<string, unknown>;
}

export interface WorkItemsBody {
  count: number;
  items: WorkItem[];
  summary: {
    pending_review: number;
    todos: number;
    active: number;
    blocked: string[];
    next_steps: string[];
  };
}

export async function fetchWorkItems(): Promise<WorkItemsBody> {
  const r = await fetch("/api/v1/workitems");
  if (!r.ok) throw new Error(`workitems HTTP ${r.status}`);
  return r.json();
}

// ---------- assets 数据中心（U2-2，真实台账） ----------

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
  const r = await fetch("/api/v1/assets/summary");
  if (!r.ok) throw new Error(`assets summary HTTP ${r.status}`);
  return r.json();
}

export async function fetchAssetsList(opts?: {
  source_id?: string; limit?: number; offset?: number;
}): Promise<{ count: number; items: AssetRow[]; purposes_vocab: string[] }> {
  const p = new URLSearchParams();
  if (opts?.source_id) p.set("source_id", opts.source_id);
  p.set("limit", String(opts?.limit ?? 50));
  p.set("offset", String(opts?.offset ?? 0));
  const r = await fetch(`/api/v1/assets?${p.toString()}`);
  if (!r.ok) throw new Error(`assets list HTTP ${r.status}`);
  return r.json();
}

// ---------- quality gold 人工金标准（U3-6） ----------

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
  const r = await fetch("/api/v1/quality/gold/status");
  if (!r.ok) throw new Error(`gold status HTTP ${r.status}`);
  return r.json();
}

export async function fetchGoldConfusion(): Promise<Record<string, number>> {
  const r = await fetch("/api/v1/quality/gold/confusion");
  if (!r.ok) throw new Error(`gold confusion HTTP ${r.status}`);
  return r.json();
}

// ---------- labeling (M4) ----------

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

export async function fetchLabelingBatches(): Promise<{ count: number; batches: LabelingBatch[] }> {
  const r = await fetch("/api/v1/labeling/batches");
  if (!r.ok) throw new Error(`labeling batches HTTP ${r.status}`);
  return r.json();
}

export async function createLabelingBatch(name: string): Promise<{ batch: LabelingBatch }> {
  const r = await fetch("/api/v1/labeling/batches", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail ?? `create batch HTTP ${r.status}`);
  }
  return r.json();
}

export async function importLabelingFiles(
  batchId: string,
  files: File[]
): Promise<Record<string, unknown>> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const r = await fetch(`/api/v1/labeling/batches/${batchId}/import`, {
    method: "POST",
    body: form,
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail ?? `import HTTP ${r.status}`);
  }
  return r.json();
}

export async function fetchReconcile(batchId: string): Promise<ReconcileReport> {
  const r = await fetch(`/api/v1/labeling/batches/${batchId}/reconcile`);
  if (!r.ok) throw new Error(`reconcile HTTP ${r.status}`);
  return r.json();
}

export async function fetchLabelingInbox(): Promise<{ count: number }> {
  const r = await fetch("/api/v1/labeling/inbox");
  if (!r.ok) throw new Error(`inbox HTTP ${r.status}`);
  return r.json();
}

// ---------- training governance (M5) ----------

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
  const r = await fetch("/api/v1/training/gates");
  if (!r.ok) throw new Error(`gates HTTP ${r.status}`);
  return r.json();
}

export async function fetchTrainingRuns(): Promise<{ count: number; runs: TrainingRunRow[] }> {
  const r = await fetch("/api/v1/training/runs");
  if (!r.ok) throw new Error(`training runs HTTP ${r.status}`);
  return r.json();
}

export async function fetchTrainingSnapshots(): Promise<{
  count: number;
  snapshots: Array<Record<string, unknown>>;
}> {
  const r = await fetch("/api/v1/training/snapshots");
  if (!r.ok) throw new Error(`snapshots HTTP ${r.status}`);
  return r.json();
}

async function postJson(url: string, body: unknown, extra?: Record<string, string>): Promise<Response> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (_csrfToken) headers["X-CSRF-Token"] = _csrfToken;
  if (extra) Object.assign(headers, extra);
  return fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
}

async function parseError(r: Response, fallback: string): Promise<Error> {
  const d = await r.json().catch(() => ({}));
  return new Error(`${d.detail ?? fallback}（HTTP ${r.status}）`);
}

export async function dryRunTraining(snapshotId: string): Promise<{ run: TrainingRunRow }> {
  const r = await postJson("/api/v1/training/runs/dry-run", { snapshot_id: snapshotId });
  if (!r.ok) throw await parseError(r, "dry-run");
  return r.json();
}

export async function approveTrainingPlan(runId: string): Promise<{ run: TrainingRunRow }> {
  const r = await postJson(`/api/v1/training/runs/${runId}/approve-plan`, {});
  if (!r.ok) throw await parseError(r, "approve-plan");
  return r.json();
}

export async function enqueueTraining(runId: string): Promise<{ run: TrainingRunRow & { job_id: string } }> {
  const r = await postJson(`/api/v1/training/runs/${runId}/enqueue`, {});
  if (!r.ok) throw await parseError(r, "enqueue");
  return r.json();
}

export async function fetchJobs(): Promise<{
  stats: Record<string, number>;
  count: number;
  jobs: Array<Record<string, unknown>>;
}> {
  const r = await fetch("/api/v1/jobs");
  if (!r.ok) throw new Error(`jobs HTTP ${r.status}`);
  return r.json();
}

export async function buildGoldQueue(size = 500): Promise<{ added: number; total_queue: number }> {
  const r = await postJson("/api/v1/quality/gold/build", { size });
  if (!r.ok) throw await parseError(r, "gold build");
  return r.json();
}

export async function submitGoldVerdict(
  sha256: string, verdict: "pass" | "fail",
): Promise<{ accepted: boolean }> {
  const r = await postJson("/api/v1/quality/gold/verdict", { sha256, verdict });
  if (!r.ok) throw await parseError(r, "gold verdict");
  return r.json();
}

// ---------- review flow (U4-2) ----------

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
  const r = await fetch("/api/v1/review/status");
  if (!r.ok) throw new Error(`review status HTTP ${r.status}`);
  return r.json();
}

export async function fetchReviewTasks(): Promise<{
  n_tasks: number;
  tasks: ReviewTaskRow[];
}> {
  const r = await fetch("/api/v1/review/tasks");
  if (!r.ok) throw await parseError(r, "review tasks");
  return r.json();
}

export async function claimReviewTask(claim_token: string): Promise<{
  claimed: boolean;
  task_id: string;
}> {
  const r = await postJson("/api/v1/review/claim", { claim_token });
  if (!r.ok) throw await parseError(r, "review claim");
  return r.json();
}

export async function submitReview(
  taskId: string, verdict: string, box: number[], role = "annotator",
): Promise<Record<string, unknown>> {
  const r = await postJson("/api/v1/review/submit", {
    task_id: taskId, verdict, box, role,
  });
  if (!r.ok) throw await parseError(r, "review submit");
  return r.json();
}

export async function exportReview(): Promise<{
  path: string;
  sha256: string;
  n_tasks: number;
  n_finalized: number;
}> {
  const r = await postJson("/api/v1/review/export", {});
  if (!r.ok) throw await parseError(r, "review export");
  return r.json();
}

// ---------- Loop v2（U5-2/U5-3） ----------

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
  const r = await fetch("/api/v1/loops/runs");
  if (!r.ok) throw await parseError(r, "loop runs");
  return r.json();
}

export async function fetchLoopRun(runId: string): Promise<LoopRunView> {
  const r = await fetch(`/api/v1/loops/runs/${runId}`);
  if (!r.ok) throw await parseError(r, "loop run");
  return r.json();
}

export async function startLoop(body: {
  source_id: string;
  batch_size: number;
  max_rounds: number;
}): Promise<LoopRunView> {
  const r = await postJson("/api/v1/loops/start", body);
  if (!r.ok) throw await parseError(r, "loop start");
  return r.json();
}

export async function gateLoop(
  runId: string,
  approved: boolean,
): Promise<LoopRunView> {
  const r = await postJson(`/api/v1/loops/runs/${runId}/gate`, { approved });
  if (!r.ok) throw await parseError(r, "loop gate");
  return r.json();
}

// ---------- auth (UMT-006) ----------

export interface AuthMe {
  actor: string;
  role: string;
}

let _csrfToken: string | null = null;

export function csrfToken(): string | null {
  return _csrfToken;
}

export async function login(username: string, password: string): Promise<AuthMe> {
  const r = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) throw await parseError(r, "login");
  const d = await r.json();
  _csrfToken = d.csrf_token ?? null;
  return { actor: d.actor, role: d.role };
}

export async function fetchMe(): Promise<AuthMe> {
  const r = await fetch("/api/v1/auth/me");
  if (!r.ok) throw new Error(`me HTTP ${r.status}`);
  const d = await r.json();
  if (d.csrf_token) _csrfToken = d.csrf_token;
  return { actor: d.actor, role: d.role };
}

export async function logout(): Promise<void> {
  await fetch("/api/v1/auth/logout", { method: "POST" });
  _csrfToken = null;
}

// ---------- recognition tasks (U2-3) ----------

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
  const r = await fetch("/api/v1/recognition/profiles");
  if (!r.ok) throw new Error(`recognition profiles HTTP ${r.status}`);
  return r.json();
}

async function postFormWithCsrf(url: string, form: FormData, extra?: Record<string, string>): Promise<Response> {
  const headers: Record<string, string> = {};
  if (_csrfToken) headers["X-CSRF-Token"] = _csrfToken;
  if (extra) Object.assign(headers, extra);
  return fetch(url, { method: "POST", headers, body: form });
}

export async function uploadRecognitionFiles(
  files: File[], opts?: RecognitionRequestOpts,
): Promise<RecognitionTaskView> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  form.append("recognition_profile_id",
    opts?.recognition_profile_id ?? "production_legacy");
  form.append("service_tier", opts?.service_tier ?? "standard");
  form.append("source", opts?.source ?? "web");
  if (opts?.project_id) form.append("project_id", opts.project_id);
  // 幂等键（UMT-109）：同一次提交重试不会重复创建任务
  const idem = { "Idempotency-Key": crypto.randomUUID() };
  const r = await postFormWithCsrf("/api/v1/recognition/tasks/upload", form, idem);
  if (!r.ok) throw await parseError(r, "recognition upload");
  return r.json();
}

export async function recognizeByUrl(
  url: string, opts?: RecognitionRequestOpts,
): Promise<RecognitionTaskView> {
  const idem = { "Idempotency-Key": crypto.randomUUID() };
  const r = await postJson("/api/v1/recognition/tasks/url", {
    url,
    recognition_profile_id:
      opts?.recognition_profile_id ?? "production_legacy",
    service_tier: opts?.service_tier ?? "standard",
    source: opts?.source ?? "web",
    project_id: opts?.project_id ?? "",
  }, idem);
  if (!r.ok) throw await parseError(r, "recognition url");
  return r.json();
}

export async function fetchRecognitionTasks(opts?: {
  limit?: number;
  offset?: number;
  status?: string;
}): Promise<{
  count: number;
  tasks: RecognitionTaskRow[];
}> {
  const q = new URLSearchParams();
  q.set("limit", String(opts?.limit ?? 100));
  if (opts?.offset) q.set("offset", String(opts.offset));
  if (opts?.status) q.set("status", opts.status);
  const r = await fetch(`/api/v1/recognition/tasks?${q}`);
  if (!r.ok) throw new Error(`recognition tasks HTTP ${r.status}`);
  return r.json();
}

export async function recognizeFile(file: File, conf = 0.25): Promise<RecognitionResult> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`/api/v1/recognition/recognize?conf=${conf}`, {
    method: "POST",
    body: form,
  });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try {
      const body = await r.json();
      detail = `${body.error ?? "error"}: ${body.detail ?? ""}`;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return r.json();
}

// ---------- cascade 统一级联任务（VLM-016，shadow 默认） ----------

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
  const r = await fetch("/api/v1/cascade/tasks");
  if (!r.ok) throw await parseError(r, "cascade tasks");
  return r.json();
}

export async function fetchCascadeTask(taskId: string): Promise<CascadeTaskDetail> {
  const r = await fetch(`/api/v1/cascade/tasks/${taskId}`);
  if (!r.ok) throw await parseError(r, "cascade task");
  return r.json();
}

export async function fetchCascadeRegions(taskId: string): Promise<{
  regions: Array<Record<string, unknown>>;
}> {
  const r = await fetch(`/api/v1/cascade/tasks/${taskId}/regions`);
  if (!r.ok) throw await parseError(r, "cascade regions");
  return r.json();
}

export async function fetchCascadeTrail(taskId: string): Promise<{
  trail: CascadeTrailItem[];
}> {
  const r = await fetch(`/api/v1/cascade/tasks/${taskId}/trail`);
  if (!r.ok) throw await parseError(r, "cascade trail");
  return r.json();
}

export async function cancelCascadeTask(taskId: string): Promise<{ status: string }> {
  const r = await postJson(`/api/v1/cascade/tasks/${taskId}/cancel`, {});
  if (!r.ok) throw await parseError(r, "cascade cancel");
  return r.json();
}

// ---------- models/runtime 模型驻留（VLM-016） ----------

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
  const r = await fetch("/api/v1/models/runtime");
  if (!r.ok) throw await parseError(r, "models runtime");
  return r.json();
}

// ---------- packaging 新包装裁决（VLM-016） ----------

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
  const r = await fetch(`/api/v1/packaging/decisions?${q}`);
  if (!r.ok) throw await parseError(r, "packaging decisions");
  return r.json();
}

export async function finalizePackageDecision(
  decisionId: string,
  body: {
    status: string;
    name_choice?: string | null;
    new_sku_id?: string | null;
    display_name?: string | null;
  },
): Promise<{ decision: PackageDecisionRow }> {
  const r = await postJson(
    `/api/v1/packaging/decisions/${decisionId}/finalize`, body,
  );
  if (!r.ok) throw await parseError(r, "packaging finalize");
  return r.json();
}

export async function supersedePackageDecision(body: {
  older_id: string;
  newer_id: string;
  reason?: string;
}): Promise<{ superseded: boolean }> {
  const r = await postJson("/api/v1/packaging/supersede", body);
  if (!r.ok) throw await parseError(r, "packaging supersede");
  return r.json();
}

// ---------- GLTC：四训练通道统一控制面 ----------

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
  const r = await fetch("/api/v1/training/lanes");
  if (!r.ok) throw new Error(`training lanes HTTP ${r.status}`);
  return r.json();
}

export async function fetchTrainingOverview(): Promise<TrainingOverviewBody> {
  const r = await fetch("/api/v1/training/overview");
  if (!r.ok) throw new Error(`training overview HTTP ${r.status}`);
  return r.json();
}

export async function fetchLegacyModels(): Promise<{
  count: number;
  models: LegacyModelRow[];
}> {
  const r = await fetch("/api/v1/training/legacy-models");
  if (!r.ok) throw new Error(`legacy models HTTP ${r.status}`);
  return r.json();
}

export async function fetchTrainingRunsV2(): Promise<{
  count: number;
  runs: Record<string, unknown>[];
}> {
  const r = await fetch("/api/v1/training/runs-v2");
  if (!r.ok) throw new Error(`training runs-v2 HTTP ${r.status}`);
  return r.json();
}

// ---------- SLTF：Agent / Blackboard / TaskBoard ----------
export interface AgentInfo {
  agent_id: string;
  version: string;
  domain: string;
  risk_level: string;
}
export async function fetchAgents(): Promise<{ count: number; agents: AgentInfo[] }> {
  const r = await fetch("/api/v1/agents");
  if (!r.ok) throw new Error(`agents HTTP ${r.status}`);
  return r.json();
}
export async function fetchBlackboard(): Promise<{ count: number; events: any[] }> {
  const r = await fetch("/api/v1/blackboard");
  if (!r.ok) throw new Error(`blackboard HTTP ${r.status}`);
  return r.json();
}
export async function fetchTaskboard(): Promise<{ states: Record<string, any[]> }> {
  const r = await fetch("/api/v1/taskboard");
  if (!r.ok) throw new Error(`taskboard HTTP ${r.status}`);
  return r.json();
}

// ---------- ABOS T6：Agent 命令审批（服务端持久化 + 审计） ----------
export async function approveAgentCommand(commandId: string): Promise<any> {
  const r = await postJson(
    `/api/agent/v1/commands/${commandId}/approve`, {});
  if (!r.ok) throw await parseError(r, "command approve");
  return r.json();
}
export async function rejectAgentCommand(commandId: string): Promise<any> {
  const r = await postJson(
    `/api/agent/v1/commands/${commandId}/reject`, {});
  if (!r.ok) throw await parseError(r, "command reject");
  return r.json();
}
export async function createAgentSession(title: string): Promise<string> {
  const r = await postJson("/api/agent/v1/sessions", { title });
  if (!r.ok) throw await parseError(r, "agent session");
  return (await r.json()).session_id;
}
export async function agentChat(sessionId: string, text: string): Promise<any> {
  const r = await postJson("/api/agent/v1/chat",
    { session_id: sessionId, text });
  if (!r.ok) throw await parseError(r, "agent chat");
  return r.json();
}
