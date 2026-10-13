import {
  Boxes,
  ChartColumn,
  History,
  LayoutDashboard,
  Link2,
  ListOrdered,
  ShieldCheck,
  Workflow,
  type LucideIcon,
} from "lucide-react";

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
}

/** The sidebar, in order. The two assistants are separate entries (4.7.4, Identity). */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    to: "/",
    label: "Overview",
    icon: LayoutDashboard,
    description: "What is running, waiting and finished, and whether the AI provider is answering.",
    task: "T6.7",
  },
  {
    to: "/assistants/freestyle",
    label: "Freestyle Assistant",
    icon: Link2,
    accent: "spruce",
    description: "Creates chained freestyle jobs on staging, from plain English.",
    task: "T6.5",
  },
  {
    to: "/assistants/pipeline",
    label: "Pipeline Assistant",
    icon: Workflow,
    accent: "plum",
    description: "Creates Pipeline jobs on staging, from plain English.",
    task: "T6.5",
  },
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
    description: "The Milestone 2 series, the experiment's results and the chatbot evaluation.",
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
    description: "Users and roles, the HIGH quota, rate limits and the audit log.",
    task: "T6.7",
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
