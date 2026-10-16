import {
  Boxes,
  ChartColumn,
  History,
  LayoutDashboard,
  ListOrdered,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { ASSISTANTS } from "@/workspace/assistants";

export const PRODUCT_NAME = "CI/CD Orchestrator";

/** The two assistants' colours (DESIGN.md: Spruce and Plum mark identity, and nothing else). */
export type Accent = "spruce" | "plum";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  accent?: Accent;
  /** One sentence for the page header. */
  description: string;
  /** The task that builds the page (PROGRESS.md, Phase 6). */
  task: string;
  /** Listed only for Admins, because the backend refuses everyone else every request it makes. */
  adminOnly?: boolean;
}

/** The sidebar, in order. The two assistants are separate entries (4.7.4, Identity). */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    to: "/",
    label: "Overview",
    icon: LayoutDashboard,
    description: "What is running, waiting and finished, and how the AI provider is set up.",
    task: "T6.7",
  },
  ...(["freestyle", "pipeline"] as const).map((kind) => {
    // One source for each assistant's name, glyph, colour and sentence (src/workspace).
    const { name, icon, accent, description } = ASSISTANTS[kind];
    return { to: `/assistants/${kind}`, label: name, icon, accent, description, task: "T6.5" };
  }),
  {
    to: "/queue",
    label: "Queue",
    icon: ListOrdered,
    description: "Ranked by score, highest first. Each bar shows what its score is made of.",
    task: "T6.6",
  },
  {
    to: "/runs",
    label: "Jobs and runs",
    icon: History,
    description: "Every run by service, assistant and result, with its stages and log.",
    task: "T6.7",
  },
  {
    to: "/analytics",
    label: "Analytics",
    icon: ChartColumn,
    description: "Run statistics, the experiments with the Milestone 2 series, and the chatbot evaluation.",
    task: "T6.7",
  },
  {
    to: "/catalog",
    label: "Service catalog",
    icon: Boxes,
    description: "Each service's repository, branches, suites, environments and reachability.",
    task: "T6.7",
  },
  {
    to: "/admin",
    label: "Admin",
    icon: ShieldCheck,
    description: "Users and roles, the HIGH quota and the rules in force, and the audit log.",
    task: "T6.7",
    adminOnly: true,
  },
];

export const ACCENT_TEXT: Record<Accent, string> = {
  spruce: "text-spruce",
  plum: "text-plum",
};

export const ACCENT_BORDER: Record<Accent, string> = {
  spruce: "border-l-spruce",
  plum: "border-l-plum",
};
