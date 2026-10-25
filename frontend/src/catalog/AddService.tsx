import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useFieldArray, useForm, type FieldPath } from "react-hook-form";
import { z } from "zod";

import { adminKeys } from "@/api/adminApi";
import { useApi } from "@/api/apiClientContext";
import { catalogApi, type NewCatalogService } from "@/api/catalogApi";
import { failureMessage } from "@/api/errors";
import { failureOf } from "@/api/request";
import { button } from "@/components/button";
import { Sheet } from "@/components/Sheet";
import { useToast } from "@/components/toast/toastContext";
import { cn } from "@/lib/cn";
import { keys } from "@/workspace/assistantApiContext";

const identifier = z.string().trim().regex(/^[a-z][a-z0-9-]{0,63}$/, "Use lowercase letters, numbers and hyphens, starting with a letter (up to 64 characters).");
const command = z.string().trim().min(1, "Enter the command to run.").max(512).regex(/^[^;&|`$><\r\n\0]+$/, "Use a single command without shell operators, pipes or substitutions.");
const optionalCommand = z.union([command, z.literal("")]);
const stages = [
  ["lint", "Lint"],
  ["security_scan", "Security scan"],
  ["integration_tests", "Integration tests"],
  ["smoke_test", "Smoke test"],
] as const;
const schema = z.object({
  name: identifier,
  repo: z.string().trim().regex(/^(https:\/\/|git@)[^\s]+\.git$/, "Enter an HTTPS or SSH clone URL ending in .git."),
  default_branch: z.string().trim().regex(/^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$/, "Enter a branch name such as main or release/v1."),
  agent_label: z.string().trim().min(1, "Enter an agent label.").max(255),
  build_command: command,
  test_suites: z.array(z.object({
    name: identifier,
    command,
    approx_seconds: z.number().int().min(1, "Enter 1 to 3600 seconds.").max(3600, "Enter 1 to 3600 seconds."),
  })).min(1).max(30).superRefine((suites, ctx) => {
    const names = new Set<string>();
    suites.forEach((suite, index) => {
      if (names.has(suite.name)) {
        ctx.addIssue({ code: "custom", path: [index, "name"], message: "Each test suite needs a unique name." });
      }
      names.add(suite.name);
    });
  }),
  deploy_command: command,
  deploy_url: z.url("Enter the staging URL.").regex(/^https?:\/\//, "Use an HTTP or HTTPS URL."),
  lint: optionalCommand,
  security_scan: optionalCommand,
  integration_tests: optionalCommand,
  smoke_test: optionalCommand,
});
type Values = z.infer<typeof schema>;
const defaults: Values = {
  name: "", repo: "", default_branch: "main", agent_label: "linux", build_command: "",
  test_suites: [{ name: "unit", command: "", approx_seconds: 10 }],
  deploy_command: "", deploy_url: "", lint: "", security_scan: "", integration_tests: "", smoke_test: "",
};
const inputClass = "h-11 w-full min-w-0 rounded-control border border-graphite bg-panel px-3 text-base text-ink aria-invalid:border-2 aria-invalid:border-ink";

export function AddService({ existingNames }: { existingNames: string[] }) {
  const [open, setOpen] = useState(false);
  const ids = useId();
  const api = useApi(catalogApi);
  const queryClient = useQueryClient();
  const toast = useToast();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: defaults });
  const suites = useFieldArray({ control: form.control, name: "test_suites" });
  const { errors } = form.formState;
  const create = useMutation({
    mutationFn: (values: Values) => {
      const extra_stages: NewCatalogService["extra_stages"] = {};
      for (const [stage] of stages) {
        if (values[stage]) extra_stages[stage] = values[stage];
      }
      return api.create({
        name: values.name, repo: values.repo, default_branch: values.default_branch,
        agent_label: values.agent_label, build_command: values.build_command,
        test_suites: values.test_suites, deploy: { staging: { command: values.deploy_command, url: values.deploy_url } },
        allowed_environments: ["staging"], extra_stages,
      });
    },
    onSuccess: async (service) => {
      toast(`${service.name} was added to the catalog`);
      form.reset(defaults);
      setOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.services }),
        queryClient.invalidateQueries({ queryKey: adminKeys.audits }),
      ]);
    },
    onError: (error) => {
      const failure = failureOf(error);
      if (failure.kind !== "api") return;
      const fields = failure.error.details.fields;
      if (typeof fields !== "object" || fields === null) return;
      const aliases: Record<string, string> = { "deploy.staging.command": "deploy_command", "deploy.staging.url": "deploy_url" };
      for (const [field, message] of Object.entries(fields)) {
        const name = aliases[field] ?? field.replace(/^extra_stages\./, "");
        if (typeof message === "string" && (name in defaults || /^test_suites\.\d+\.(name|command|approx_seconds)$/.test(name))) {
          form.setError(name as FieldPath<Values>, { message }, { shouldFocus: true });
        }
      }
    },
  });
  const control = (name: keyof Values, label: string, hint?: string, placeholder?: string) => (
    <Field id={`${ids}-${name}`} label={label} hint={hint} error={errors[name]?.message}>
      <input id={`${ids}-${name}`} {...form.register(name)} placeholder={placeholder}
        autoComplete="off" spellCheck={false} className={inputClass}
        aria-invalid={errors[name] ? true : undefined}
        aria-describedby={`${ids}-${name}-help`} />
    </Field>
  );

  return (
    <Sheet side="right" title="Add Service" open={open}
      onOpenAutoFocus={(event) => { event.preventDefault(); form.setFocus("name"); }}
      onOpenChange={(next) => {
        if (!create.isPending) {
          setOpen(next);
          if (next) create.reset();
        }
      }}
      trigger={<button type="button" className={button({ variant: "primary" })}><Plus aria-hidden="true" className="size-4" />Add Service</button>}
    >
      <form noValidate aria-label="Add service" className="flex flex-col gap-5 p-4"
        onSubmit={(event) => {
          if (create.isPending) { event.preventDefault(); return; }
          void form.handleSubmit((values) => {
            if (existingNames.includes(values.name)) {
              form.setError("name", { message: "A service with this name already exists." }, { shouldFocus: true });
              return;
            }
            create.mutate(values);
          })(event);
        }}
      >
        <p className="text-sm text-graphite">Connect a repository and define the commands the assistants can use. Deployments are limited to staging.</p>
        {create.isError ? <p role="alert" className="border-l-4 border-ink bg-ground p-3 text-sm">The service was not added. {failureMessage(failureOf(create.error))}</p> : null}
        <fieldset disabled={create.isPending} className="flex min-w-0 flex-col gap-4">
          <legend className="mb-3 font-semibold">Repository</legend>
          {control("name", "Service name", "Lowercase letters, numbers and hyphens.", "orders-service")}
          {control("repo", "Repository URL", "Use the repository’s clone URL.", "https://github.com/team/orders-service.git")}
          {control("default_branch", "Default branch")}
          {control("agent_label", "Agent label", "Use a label available on your Jenkins agents.")}
          {control("build_command", "Build command", undefined, "./scripts/build.sh")}
        </fieldset>
        <fieldset disabled={create.isPending} className="flex min-w-0 flex-col gap-4 border-t border-rule pt-4">
          <legend className="pr-2 font-semibold">Test suites</legend>
          {suites.fields.map((suite, index) => (
            <div key={suite.id} className="flex flex-col gap-3 border border-rule p-3">
              <p className="text-sm font-semibold">Suite {index + 1}</p>
              <Field id={`${ids}-suite-${index}-name`} label={`Suite ${index + 1} name`} error={errors.test_suites?.[index]?.name?.message}>
                <input id={`${ids}-suite-${index}-name`} {...form.register(`test_suites.${index}.name`)} className={inputClass} aria-invalid={Boolean(errors.test_suites?.[index]?.name)} aria-describedby={`${ids}-suite-${index}-name-help`} />
              </Field>
              <Field id={`${ids}-suite-${index}-command`} label={`Suite ${index + 1} command`} error={errors.test_suites?.[index]?.command?.message}>
                <input id={`${ids}-suite-${index}-command`} {...form.register(`test_suites.${index}.command`)} className={inputClass} placeholder="./scripts/test.sh unit" aria-invalid={Boolean(errors.test_suites?.[index]?.command)} aria-describedby={`${ids}-suite-${index}-command-help`} />
              </Field>
              <Field id={`${ids}-suite-${index}-seconds`} label={`Suite ${index + 1} duration (seconds)`} hint="Estimated duration, from 1 to 3600 seconds." error={errors.test_suites?.[index]?.approx_seconds?.message}>
                <input id={`${ids}-suite-${index}-seconds`} type="number" min={1} max={3600} {...form.register(`test_suites.${index}.approx_seconds`, { valueAsNumber: true })} className={inputClass} aria-invalid={Boolean(errors.test_suites?.[index]?.approx_seconds)} aria-describedby={`${ids}-suite-${index}-seconds-help`} />
              </Field>
              {suites.fields.length > 1 ? <button type="button" className={cn(button(), "self-start")} onClick={() => { suites.remove(index); }}>Remove suite {index + 1}</button> : null}
            </div>
          ))}
          {suites.fields.length < 30 ? <button type="button" className={cn(button(), "self-start")} onClick={() => { suites.append({ name: "", command: "", approx_seconds: 10 }); }}>Add test suite</button> : null}
        </fieldset>
        <fieldset disabled={create.isPending} className="flex min-w-0 flex-col gap-4 border-t border-rule pt-4">
          <legend className="pr-2 font-semibold">Staging deployment</legend>
          {control("deploy_command", "Deploy command", undefined, "./deploy.sh staging")}
          {control("deploy_url", "Staging URL", "Where the staging service will be available.", "http://localhost:9003")}
        </fieldset>
        <fieldset disabled={create.isPending} className="flex min-w-0 flex-col gap-4 border-t border-rule pt-4">
          <legend className="pr-2 font-semibold">Extra stages (optional)</legend>
          {stages.map(([stage, label]) => <div key={stage}>{control(stage, `${label} command`)}</div>)}
        </fieldset>
        <div className="flex flex-wrap gap-2 border-t border-rule pt-4">
          <button type="submit" aria-disabled={create.isPending} className={button({ variant: "primary" })}>{create.isPending ? "Adding service…" : "Add service"}</button>
          <button type="button" aria-disabled={create.isPending} className={button()} onClick={() => { if (!create.isPending) setOpen(false); }}>Cancel</button>
        </div>
      </form>
    </Sheet>
  );
}

function Field({ id, label, hint, error, children }: { id: string; label: string; hint?: string; error?: string; children: ReactNode }) {
  return <div className="flex min-w-0 flex-col gap-1">
    <label htmlFor={id} className="text-sm font-semibold">{label}</label>
    {children}
    <div id={`${id}-help`} className="text-sm">
      {hint ? <p className="text-graphite">{hint}</p> : null}
      {error ? <p className="font-semibold">{error}</p> : null}
    </div>
  </div>;
}
