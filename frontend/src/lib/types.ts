export type User = {
  id: number;
  username: string;
  github_id: number | null;
  github_login: string;
  email: string;
  avatar_url: string;
};

export type OrganizationRole = "owner" | "admin" | "member";

export type Organization = {
  id: number;
  name: string;
  slug: string;
  is_personal: boolean;
  role: OrganizationRole | null;
  created_at: string;
};

export type GitHubStartResponse = {
  authorize_url: string;
  state: string;
};

export type LoginResponse = {
  access: string;
  refresh: string;
  user: User;
  created: boolean;
};

export type ConnectedRepository = {
  id: number;
  github_id: number;
  full_name: string;
  owner: string;
  name: string;
  default_branch: string;
  private: boolean;
  installation_id: number | null;
  connected_by_login: string;
  created_at: string;
};

export type InstallableRepository = {
  github_id: number;
  full_name: string;
  owner: string;
  name: string;
  default_branch: string;
  private: boolean;
  connected: boolean;
};

export type InstallableResponse = {
  installed: boolean;
  install_url: string;
  repositories: InstallableRepository[];
};

export type IngestionStatus = "pending" | "running" | "done" | "failed";

export type IngestionJob = {
  id: number;
  status: IngestionStatus;
  is_active: boolean;
  commit_sha: string;
  files_discovered: number;
  files_indexed: number;
  files_skipped: number;
  chunks_created: number;
  chunks_reused: number;
  embedding_api_calls: number;
  /** Raw error text: only populated for owners and admins. */
  error: string;
  /** A short reason safe to show anyone. */
  error_summary: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  duration_seconds: number | null;
};

export type IngestionState = {
  job: IngestionJob | null;
  chunk_count: number;
  indexed_files: number;
  can_manage: boolean;
};

export type ReviewStatus = "pending" | "running" | "done" | "failed";

export type ReviewFinding = {
  id: number;
  agent: string;
  severity: "blocking" | "nit";
  category: string;
  file_path: string;
  line: number;
  /** inline: on an added line; existing: about unchanged code; general: no honest line. */
  placement: "inline" | "existing" | "general";
  message: string;
  citation: string;
  dismissed: boolean;
};

export type ReviewCall = {
  id: number;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  succeeded: boolean;
  is_fallback: boolean;
  error: string;
  error_summary: string;
};

export type AgentRun = {
  id: number;
  name: string;
  /** The model that actually served the call. */
  model: string;
  /** The model asked for; differs from `model` only after a failover. */
  requested_model: string;
  provider: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  succeeded: boolean;
  used_fallback: boolean;
  findings_count: number;
  skipped_reason: string;
  error: string;
  error_summary: string;
  detail: string;
};

export type AgentState = "pending" | "running" | "ok" | "failed" | "skipped";

export type Review = {
  id: number;
  repository: string;
  repository_id: number;
  pr_number: number;
  pr_title: string;
  pr_url: string;
  /** Owner/admin: may re-run, and sees raw error text. */
  can_manage: boolean;
  status: ReviewStatus;
  /** Pending or running past the backend's STALE_AFTER: no worker has it. */
  stalled: boolean;
  /** "rerun" when a person asked for it, else "webhook". */
  trigger: "webhook" | "rerun";
  head_sha: string;
  model_used: string;
  used_fallback: boolean;
  total_input_tokens: number;
  total_output_tokens: number;
  duration_ms: number;
  estimated_cost_usd: string;
  estimated_cost_inr: string;
  degraded: boolean;
  truncated: boolean;
  skipped_files: string[];
  error: string;
  error_summary: string;
  progress: Partial<Record<string, AgentState>>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  findings: ReviewFinding[];
  calls: ReviewCall[];
  agent_runs: AgentRun[];
};

export type ReviewSummary = {
  id: number;
  pr_number: number;
  pr_title: string;
  status: ReviewStatus;
  /** Pending or running past the backend's STALE_AFTER: no worker has it. */
  stalled: boolean;
  /** "rerun" when a person asked for it, else "webhook". */
  trigger: "webhook" | "rerun";
  head_sha: string;
  model_used: string;
  used_fallback: boolean;
  duration_ms: number;
  estimated_cost_inr: string;
  finding_count: number;
  created_at: string;
};

export type Paginated<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type ReviewListItem = {
  id: number;
  repository: string;
  repository_id: number;
  pr_number: number;
  pr_title: string;
  status: ReviewStatus;
  /** Pending or running past the backend's STALE_AFTER: no worker has it. */
  stalled: boolean;
  /** "rerun" when a person asked for it, else "webhook". */
  trigger: "webhook" | "rerun";
  degraded: boolean;
  used_fallback: boolean;
  head_sha: string;
  model_used: string;
  duration_ms: number;
  estimated_cost_inr: string;
  finding_count: number;
  blocking_count: number;
  nit_count: number;
  created_at: string;
};

export type Member = {
  id: number;
  user: User;
  role: OrganizationRole;
  created_at: string;
};

export type AuditEntry = {
  id: number;
  action: string;
  action_label: string;
  actor_login: string;
  target_type: string;
  target_id: string;
  target_label: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

/** The socket's snapshot / progress / finished events, and the status endpoint. */
export type ReviewProgress = {
  type: "review.snapshot" | "review.progress" | "review.finished";
  review_id: number;
  status: ReviewStatus;
  degraded?: boolean;
  agents: Record<string, AgentState>;
  completed: number;
  total: number;
  agent?: string;
  state?: AgentState;
};

export type ReviewDiff = {
  diff: string;
  source: "stored" | "github";
  truncated: boolean;
  head_sha: string;
};

export type BreakdownRow = { key: string; count: number; blocking: number };

export type AnalyticsOverview = {
  range: { days: number; since: string; until: string };
  cost_basis: string;
  summary: {
    prs_reviewed: number;
    reviews: number;
    completed_reviews: number;
    degraded_reviews: number;
    failed_reviews: number;
    fallback_reviews: number;
    findings: number;
    blocking: number;
    nits: number;
    blocking_ratio: number | null;
    avg_findings_per_pr: number | null;
    avg_latency_ms: number | null;
    est_cost_inr_total: string;
    est_cost_inr_avg: string | null;
  };
  timeseries: {
    date: string;
    reviews: number;
    findings: number;
    blocking: number;
    nits: number;
    avg_latency_ms: number | null;
    est_cost_inr: string;
  }[];
  by_category: BreakdownRow[];
  by_agent: BreakdownRow[];
};

export type AppNotification = {
  id: number;
  kind: "review.finished" | "review.degraded" | "review.failed" | "indexing.failed";
  title: string;
  body: string;
  link: string;
  /** For reviews: full repository name (the title shortens it), head SHA, trigger. */
  meta: { repository?: string; pr_number?: number; head_sha?: string; trigger?: string };
  read: boolean;
  read_at: string | null;
  created_at: string;
};
