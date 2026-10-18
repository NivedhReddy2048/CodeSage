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
  error: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  duration_seconds: number | null;
};

export type IngestionState = {
  job: IngestionJob | null;
  chunk_count: number;
  indexed_files: number;
};

export type ReviewStatus = "pending" | "running" | "done" | "failed";

export type ReviewFinding = {
  id: number;
  agent: string;
  severity: "blocking" | "nit";
  category: string;
  file_path: string;
  line: number;
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
};

export type Review = {
  id: number;
  repository: string;
  pr_number: number;
  pr_title: string;
  status: ReviewStatus;
  head_sha: string;
  model_used: string;
  used_fallback: boolean;
  total_input_tokens: number;
  total_output_tokens: number;
  duration_ms: number;
  estimated_cost_usd: string;
  estimated_cost_inr: string;
  truncated: boolean;
  skipped_files: string[];
  error: string;
  created_at: string;
  finished_at: string | null;
  findings: ReviewFinding[];
  calls: ReviewCall[];
};

export type ReviewSummary = {
  id: number;
  pr_number: number;
  pr_title: string;
  status: ReviewStatus;
  head_sha: string;
  model_used: string;
  used_fallback: boolean;
  duration_ms: number;
  estimated_cost_inr: string;
  finding_count: number;
  created_at: string;
};
