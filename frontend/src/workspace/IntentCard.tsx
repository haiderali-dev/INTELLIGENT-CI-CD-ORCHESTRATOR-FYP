import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState, type ReactNode } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import type { components } from "@/api/schema";
import { button } from "@/components/button";
import { cn } from "@/lib/cn";

import { URGENCIES, type IntentFields } from "./intent";

type Service = components["schemas"]["ServiceResponse"];
type IntentEdit = components["schemas"]["IntentEdit"];

const NOT_SET = "Not set";

/**
 * The intent card (4.7.4): what the assistant understood, as labelled chips, with Generate and
 * Edit. Editing offers only catalog values: the catalog's services, the chosen service's branches
 * and allowed environments, and the three urgency levels. Production is never among them; the
 * catalog cannot hold it.
 */
export function IntentCard({
  intent,
  services,
  branches = {},
  onGenerate,
  onEdit,
  generating = false,
}: {
  intent: IntentFields;
  services: readonly Service[];
  /** Branches per service, from GET /api/services/{name}/branches. A service without a list yet
   * offers its default branch. */
  branches?: Readonly<Record<string, readonly string[]>>;
  onGenerate: () => void;
  /** Called with only the fields that changed. */
  onEdit: (changes: IntentEdit) => Promise<void> | void;
  generating?: boolean;
}) {
  const [editing, setEditing] = useState(false);

  return (
    <section aria-label="Intent" className="flex flex-col gap-4 border border-rule p-4">
      {editing ? (
        <IntentEditor
          intent={intent}
          services={services}
          branches={branches}
          onCancel={() => {
            setEditing(false);
          }}
          onSave={async (changes) => {
            if (Object.keys(changes).length > 0) {
              await onEdit(changes);
            }
            setEditing(false);
          }}
        />
      ) : (
        <>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2">
            <Row label="Service" value={intent.service} />
            <Row label="Branch" value={intent.branch} />
            <Row label="Environment" value={intent.environment} />
            <Row label="Urgency" value={intent.urgency} />
          </dl>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              aria-disabled={generating}
              onClick={() => {
                if (!generating) {
                  onGenerate();
                }
              }}
              className={button({ variant: "primary" })}
            >
              {generating ? "Generating" : "Generate"}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(true);
              }}
              className={button()}
            >
              Edit
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      <dt className="text-sm text-graphite">{label}</dt>
      <dd>
        <span
          className={cn(
            "inline-block max-w-full truncate rounded-control border px-2 py-0.5 text-sm",
            value ? "border-graphite" : "border-rule text-graphite",
          )}
        >
          {value ?? NOT_SET}
        </span>
      </dd>
    </>
  );
}

const editSchema = z.object({
  service: z.string().min(1, "Choose a service."),
  branch: z.string().min(1, "Choose a branch."),
  environment: z.string(),
  urgency: z.enum(URGENCIES),
});
type EditValues = z.infer<typeof editSchema>;

function IntentEditor({
  intent,
  services,
  branches,
  onCancel,
  onSave,
}: {
  intent: IntentFields;
  services: readonly Service[];
  branches: Readonly<Record<string, readonly string[]>>;
  onCancel: () => void;
  onSave: (changes: IntentEdit) => Promise<void>;
}) {
  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      service: intent.service ?? "",
      branch: intent.branch ?? "",
      environment: intent.environment ?? "",
      urgency: intent.urgency ?? "MEDIUM",
    },
  });
  const { errors, isSubmitting } = form.formState;
  const chosen = useWatch({ control: form.control, name: "service" });
  const service = services.find(({ name }) => name === chosen);

  const branchOptions = useMemo(() => {
    const known = service ? (branches[service.name] ?? [service.default_branch]) : [];
    // The branch the request named stays on offer: the backend already resolved it in Git.
    const current = chosen === intent.service ? intent.branch : null;
    return current && !known.includes(current) ? [current, ...known] : [...known];
  }, [service, branches, chosen, intent.service, intent.branch]);

  const environmentOptions = service?.allowed_environments ?? [];

  const submit = form.handleSubmit(async (values) => {
    const changes: IntentEdit = {};
    if (values.service !== (intent.service ?? "")) {
      changes.service = values.service;
    }
    if (values.branch !== (intent.branch ?? "")) {
      changes.branch = values.branch;
    }
    if (values.environment !== (intent.environment ?? "")) {
      changes.environment = values.environment || null;
    }
    if (values.urgency !== intent.urgency) {
      changes.urgency = values.urgency;
    }
    await onSave(changes);
  });

  const serviceField = form.register("service", {
    onChange: () => {
      // A new service has its own branches and environments: start from its defaults.
      const next = services.find(({ name }) => name === form.getValues("service"));
      form.setValue("branch", next?.default_branch ?? "");
      form.setValue(
        "environment",
        next?.allowed_environments.includes(form.getValues("environment"))
          ? form.getValues("environment")
          : "",
      );
    },
  });

  return (
    <form
      noValidate
      aria-label="Edit the intent"
      onSubmit={(event) => {
        void submit(event);
      }}
      className="flex flex-col gap-4"
    >
      <Field id="intent-service" label="Service" error={errors.service?.message}>
        <select id="intent-service" className={selectClass} {...serviceField}>
          {intent.service ? null : <option value="">Choose a service</option>}
          {services.map(({ name }) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </Field>
      <Field id="intent-branch" label="Branch" error={errors.branch?.message}>
        <select id="intent-branch" className={selectClass} {...form.register("branch")}>
          {branchOptions.length === 0 ? <option value="">Choose a service first</option> : null}
          {branchOptions.map((branch) => (
            <option key={branch} value={branch}>
              {branch}
            </option>
          ))}
        </select>
      </Field>
      <Field id="intent-environment" label="Environment">
        <select id="intent-environment" className={selectClass} {...form.register("environment")}>
          <option value="">{NOT_SET}</option>
          {environmentOptions.map((environment) => (
            <option key={environment} value={environment}>
              {environment}
            </option>
          ))}
        </select>
      </Field>
      <Field id="intent-urgency" label="Urgency">
        <select id="intent-urgency" className={selectClass} {...form.register("urgency")}>
          {URGENCIES.map((urgency) => (
            <option key={urgency} value={urgency}>
              {urgency}
            </option>
          ))}
        </select>
      </Field>
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          aria-disabled={isSubmitting}
          className={button({ variant: "primary" })}
        >
          {isSubmitting ? "Saving" : "Save changes"}
        </button>
        <button type="button" onClick={onCancel} className={button()}>
          Cancel
        </button>
      </div>
    </form>
  );
}

const selectClass =
  "h-10 w-full rounded-control border border-graphite bg-panel px-2 text-base text-ink max-md:h-11";

function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string | undefined;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      {children}
      {error ? <p className="text-sm">{error}</p> : null}
    </div>
  );
}
