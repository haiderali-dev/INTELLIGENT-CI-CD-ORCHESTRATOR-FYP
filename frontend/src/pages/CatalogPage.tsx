import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plug, Unplug } from "lucide-react";
import type { ReactNode } from "react";

import { useApi } from "@/api/apiClientContext";
import { catalogApi, type CatalogService } from "@/api/catalogApi";
import { failureMessage } from "@/api/errors";
import { failureOf } from "@/api/request";
import type { NavItem } from "@/app/shell/nav";
import { isAdmin } from "@/auth/roles";
import { useSignedInUser } from "@/auth/sessionContext";
import { button } from "@/components/button";
import { ExternalLink } from "@/components/ExternalLink";
import { PageHeader } from "@/components/PageHeader";
import { Empty, Loading, LoadFailed, PageSection, StatusWord } from "@/components/PageStates";
import { useToast } from "@/components/toast/toastContext";
import { describeBranches, describeSuites, readable } from "@/catalog/catalogModel";
import { AddService } from "@/catalog/AddService";
import { cn } from "@/lib/cn";
import { keys } from "@/workspace/assistantApiContext";

/**
 * The service catalog (4.7.3): each service's repository, branches, suites, environments and
 * reachability, read from `catalog/services.yaml` through the API. The branches are the
 * repository's live ones, and whether they could be listed is whether the repository answered.
 */
export function CatalogPage({ item }: { item: Pick<NavItem, "label" | "description"> }) {
  const api = useApi(catalogApi);
  const services = useQuery({ queryKey: keys.services, queryFn: () => api.services() });
  const admin = isAdmin(useSignedInUser());

  let body: ReactNode;
  if (services.data) {
    const { items } = services.data;
    body =
      items.length === 0 ? (
        <Empty>
          <p>
            The catalog has no services. {admin ? "Use Add Service to connect your first repository." : "Ask an Admin to add a service."}
          </p>
        </Empty>
      ) : (
        <ul aria-label="Services" className="flex flex-col">
          {items.map((service) => (
            <ServiceEntry key={service.name} service={service} />
          ))}
        </ul>
      );
  } else if (services.isError) {
    body = (
      <LoadFailed
        what="The service catalog"
        error={services.error}
        onRetry={() => {
          void services.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the service catalog</Loading>;
  }

  return (
    <>
      <PageHeader title={item.label} description={item.description}
        aside={admin ? <AddService existingNames={services.data?.items.map(({ name }) => name) ?? []} /> : undefined} />
      <div className="py-5">{body}</div>
      {admin ? <Resync /> : null}
    </>
  );
}

function ServiceEntry({ service }: { service: CatalogService }) {
  return (
    <li className="border-b border-rule px-6 py-5 first:pt-0">
      <section aria-label={service.name} className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">{service.name}</h2>
        <dl className="grid max-w-[80ch] grid-cols-[minmax(9rem,auto)_1fr] gap-x-6 gap-y-2 max-md:grid-cols-1 max-md:gap-y-0">
          <Fact term="Repository">
            <ExternalLink href={service.repo} className="break-all">
              {service.repo}
            </ExternalLink>
          </Fact>
          <Fact term="Reachability">
            <Reachability service={service.name} defaultBranch={service.default_branch} />
          </Fact>
          <Fact term="Default branch">{service.default_branch}</Fact>
          <Fact term="Agent label">{service.agent_label}</Fact>
          <Fact term="Test suites">{describeSuites(service.test_suites)}</Fact>
          <Fact term="Environments">
            {service.allowed_environments.map(readable).join(", ") || "None"}
          </Fact>
          <Fact term="Extra stages">{service.extra_stages.map(readable).join(", ") || "None"}</Fact>
        </dl>
      </section>
    </li>
  );
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-graphite max-md:mt-2">{term}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  );
}

/**
 * Whether the repository answered, and its branches when it did. Health is a word and an icon, not
 * a state colour (DESIGN.md section 2).
 */
function Reachability({ service, defaultBranch }: { service: string; defaultBranch: string }) {
  const api = useApi(catalogApi);
  const branches = useQuery({ queryKey: keys.branches(service), queryFn: () => api.branches(service) });

  if (branches.isError) {
    return (
      <span>
        <span className="font-semibold">Not checked. </span>
        <span className="text-graphite">{failureMessage(failureOf(branches.error))}</span>
      </span>
    );
  }
  if (!branches.data) {
    return <span className="text-graphite">Checking the repository</span>;
  }
  if (!branches.data.available) {
    return (
      <span className="flex flex-col gap-1">
        <StatusWord icon={Unplug} word="Not reachable" quiet />
        <span className="text-graphite">
          {`${branches.data.unavailable_reason ?? "The repository did not answer."} The assistants offer only the default branch, ${defaultBranch}, until it answers.`}
        </span>
      </span>
    );
  }
  return (
    <span className="flex flex-col gap-1">
      <StatusWord icon={Plug} word="Reachable" />
      <span>{describeBranches(branches.data.branches, defaultBranch)}</span>
    </span>
  );
}

/** Re-read the catalog after a direct file edit and mirror it into the database. */
function Resync() {
  const api = useApi(catalogApi);
  const queryClient = useQueryClient();
  const toast = useToast();
  const resync = useMutation({
    mutationFn: () => api.resync(),
    onSuccess: async ({ created, updated }) => {
      toast(`Catalog resynced: ${String(created)} added, ${String(updated)} updated`);
      await queryClient.invalidateQueries({ queryKey: keys.services });
    },
  });

  return (
    <PageSection title="Resync">
      <div className="flex max-w-[68ch] flex-col gap-3 px-6">
        <p className="text-graphite">
          Reads <code>catalog/services.yaml</code> again and mirrors it into the database. The file
          remains the source of truth for every service.
        </p>
        {resync.isError ? (
          <p role="alert">
            <span className="font-semibold">The resync did not finish. </span>
            {failureMessage(failureOf(resync.error))}
          </p>
        ) : null}
        <button
          type="button"
          aria-disabled={resync.isPending}
          onClick={() => {
            if (!resync.isPending) {
              resync.mutate();
            }
          }}
          className={cn(button(), "self-start")}
        >
          {resync.isPending ? "Resyncing" : "Resync the catalog"}
        </button>
      </div>
    </PageSection>
  );
}
