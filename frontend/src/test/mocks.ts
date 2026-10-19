import { vi } from "vitest";

/** next/navigation stand-ins; tests read `navigation.push` to assert navigation. */
export const navigation = {
  push: vi.fn(),
  replace: vi.fn(),
  pathname: "/",
  search: new URLSearchParams(),
  params: {} as Record<string, string>,
};

export function resetNavigation() {
  navigation.push.mockReset();
  navigation.replace.mockReset();
  navigation.pathname = "/";
  navigation.search = new URLSearchParams();
  navigation.params = {};
}

export const nextNavigationMock = () => ({
  useRouter: () => ({ push: navigation.push, replace: navigation.replace, back: vi.fn() }),
  usePathname: () => navigation.pathname,
  useSearchParams: () => navigation.search,
  useParams: () => navigation.params,
});

export const user = {
  id: 1,
  username: "alice",
  github_id: 1,
  github_login: "alice",
  email: "",
  avatar_url: "",
};

export const organizations = [
  { id: 10, name: "alice", slug: "alice", is_personal: true, role: "owner" as const, created_at: "" },
  { id: 20, name: "acme", slug: "acme", is_personal: false, role: "member" as const, created_at: "" },
];
