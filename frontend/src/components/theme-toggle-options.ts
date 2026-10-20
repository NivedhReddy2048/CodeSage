import { Monitor, Moon, Sun } from "lucide-react";

/** The three theme choices, shared by the shell's menu and the public pages' switch. */
export const THEME_OPTIONS = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;
