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
