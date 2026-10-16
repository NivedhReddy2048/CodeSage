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
