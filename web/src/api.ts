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

export async function dryRunTraining(snapshotId: string): Promise<{ run: TrainingRunRow }> {
  const r = await fetch("/api/v1/training/runs/dry-run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ snapshot_id: snapshotId }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail ?? `dry-run HTTP ${r.status}`);
  }
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
