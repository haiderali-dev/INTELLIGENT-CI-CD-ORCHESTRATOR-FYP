import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import {
  analyticsApi,
  analyticsKeys,
  type Evaluation,
  type EvaluationAblationRow,
  type EvaluationEndToEndRow,
  type EvaluationPlanRow,
  type EvaluationRow,
} from "@/api/analyticsApi";
import { useApi } from "@/api/apiClientContext";
import { DataTable, type Column } from "@/components/DataTable";
import { Empty, Loading, LoadFailed, PageSection } from "@/components/PageStates";

const NOT_MEASURED = "Not measured";

/** A rate from 0 to 1 as a percentage to one decimal, or "Not measured" for null. */
function rate(value: number | null): string {
  return value === null ? NOT_MEASURED : `${(value * 100).toFixed(1)}%`;
}

function count(value: number | null): string {
  return value === null ? NOT_MEASURED : String(value);
}

/** "rules" is the rule baseline; a model run is named by its model. */
function parserName(parser: string): string {
  if (parser === "rules") {
    return "Rule baseline";
  }
  return parser.startsWith("groq:") ? parser.slice("groq:".length) : parser;
}

function withState(name: string, complete: boolean): string {
  return complete ? name : `${name} (incomplete)`;
}

/**
 * The chatbot evaluation (4.7.3, T8.2): the report `python -m eval report` wrote, as the backend
 * serves it. Its provenance comes first. When a machine wrote the gold labels (D-081), every
 * figure below measures agreement with those labels, and the page says so before any number.
 */
export function ChatbotEvaluation() {
  const api = useApi(analyticsApi);
  const evaluation = useQuery({ queryKey: analyticsKeys.evaluation, queryFn: () => api.evaluation() });

  let body: ReactNode;
  if (evaluation.data) {
    body = evaluation.data.available ? (
      <EvaluationFigures report={evaluation.data} />
    ) : (
      <Empty>
        <p>{evaluation.data.detail ?? "No evaluation results can be shown yet."}</p>
      </Empty>
    );
  } else if (evaluation.isError) {
    body = (
      <LoadFailed
        what="The chatbot evaluation"
        error={evaluation.error}
        onRetry={() => {
          void evaluation.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the chatbot evaluation</Loading>;
  }

  return (
    <PageSection title="Chatbot evaluation" className="border-t border-rule">
      <p className="max-w-[68ch] px-6 text-graphite">
        How well each parser turns a message into the right intent and the right response, on the
        evaluation dataset, as the evaluation harness measured it.
      </p>
      {body}
    </PageSection>
  );
}

function EvaluationFigures({ report }: { report: Evaluation }) {
  const { dataset, provenance } = report;
  return (
    <div className="flex flex-col gap-6">
      {provenance?.statement ? (
        <p role="note" className="mx-6 max-w-[68ch] border-l-2 border-ink pl-3">
          <span className="font-semibold">Who wrote the answers: </span>
          {provenance.statement}
        </p>
      ) : null}
      {dataset ? (
        <p className="max-w-[68ch] px-6 text-sm text-graphite">
          {`Dataset ${dataset.name}: ${String(dataset.items)} items, ${count(dataset.splits.dev ?? null)} for development and ${count(dataset.splits.test ?? null)} for test. Reviewed by a person: ${String(dataset.reviewed_by_a_person)}.`}
        </p>
      ) : null}
      <Part title="Comparison on the test split">
        <p className="max-w-[68ch] px-6 text-sm text-graphite">
          Unanswered items are reported separately and excluded from accuracy, clarification and
          refusal percentages.
        </p>
        {report.comparison.length === 0 ? (
          <Empty>
            <p>No parser has been scored on the test split yet.</p>
          </Empty>
        ) : (
          <DataTable
            label="Parsers compared on the test split"
            rows={report.comparison}
            columns={COMPARISON_COLUMNS}
            rowKey={({ run }) => run}
          />
        )}
      </Part>
      {report.plans.length > 0 ? (
        <Part title="Plan validity before and after repair">
          <p className="max-w-[68ch] px-6 text-sm text-graphite">
            Each model plans the test items that should generate jobs, from the correct intent, so
            a parsing error never counts against the plan.
          </p>
          <DataTable
            label="Plan validity on the test split"
            rows={report.plans}
            columns={PLAN_COLUMNS}
            rowKey={({ run }) => run}
          />
        </Part>
      ) : null}
      {report.ablations && report.ablations.rows.length > 0 ? (
        <Part title="Ablations">
          <p className="max-w-[68ch] px-6 text-sm text-graphite">
            {`On the 75-item stratified subset of the test split, with ${parserName(report.ablations.parser)}.`}
          </p>
          <DataTable
            label="Ablations on the 75-item subset"
            rows={report.ablations.rows}
            columns={ABLATION_COLUMNS}
            rowKey={({ configuration }) => configuration}
          />
        </Part>
      ) : null}
      {report.e2e.length > 0 ? (
        <Part title="End to end against jenkins-dev">
          <p className="max-w-[68ch] px-6 text-sm text-graphite">
            Each command through the real system: understood, planned, generated as asked, run to
            success on the agents, and for a deploy, answering on staging.
          </p>
          <DataTable
            label="End-to-end success"
            rows={report.e2e}
            columns={E2E_COLUMNS}
            rowKey={({ run }) => run}
          />
        </Part>
      ) : null}
    </div>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="px-6 font-semibold">{title}</h3>
      {children}
    </div>
  );
}

const COMPARISON_COLUMNS: readonly Column<EvaluationRow>[] = [
  {
    header: "Parser",
    rowHeader: true,
    nowrap: true,
    cell: ({ parser, complete }) => withState(parserName(parser), complete),
  },
  {
    header: "Items",
    align: "right",
    cell: ({ n, errors }) => (errors > 0 ? `${String(n)}, ${String(errors)} unanswered` : n),
  },
  { header: "Action", align: "right", cell: ({ action_accuracy: value }) => rate(value) },
  { header: "Exact match", align: "right", cell: ({ exact_match: value }) => rate(value) },
  { header: "Response", align: "right", cell: ({ behavior_accuracy: value }) => rate(value) },
  {
    header: "Questions: precision, recall",
    align: "right",
    nowrap: true,
    cell: ({ clarification_precision: precision, clarification_recall: recall }) =>
      `${rate(precision)}, ${rate(recall)}`,
  },
  { header: "Refusals", align: "right", cell: ({ refusal_rate: value }) => rate(value) },
  {
    header: "Latency, median and 95th",
    align: "right",
    nowrap: true,
    cell: ({ latency_p50_ms: median, latency_p95_ms: p95 }) =>
      median === null || p95 === null ? NOT_MEASURED : `${String(median)} ms, ${String(p95)} ms`,
  },
  {
    header: "Tokens a command",
    align: "right",
    cell: ({ tokens_per_command: tokens }) => (tokens === null ? NOT_MEASURED : String(tokens)),
  },
];

const PLAN_COLUMNS: readonly Column<EvaluationPlanRow>[] = [
  { header: "Parser", rowHeader: true, nowrap: true, cell: ({ parser }) => parserName(parser) },
  {
    header: "Planned by the model",
    align: "right",
    cell: ({ n, plannable_items: plannable }) => `${String(n)} of ${String(plannable)}`,
  },
  {
    header: "Valid first time",
    align: "right",
    cell: ({ valid_before_repair: value }) => rate(value),
  },
  {
    header: "Valid after repair",
    align: "right",
    cell: ({ valid_after_repair: value }) => rate(value),
  },
  { header: "Repaired", align: "right", cell: ({ repaired }) => repaired },
  { header: "Still invalid", align: "right", cell: ({ still_invalid: invalid }) => invalid },
];

const ABLATION_COLUMNS: readonly Column<EvaluationAblationRow>[] = [
  {
    header: "Configuration",
    rowHeader: true,
    cell: ({ label, complete }) => withState(label.charAt(0).toUpperCase() + label.slice(1), complete),
  },
  {
    header: "Items",
    align: "right",
    cell: ({ n, errors }) => (errors > 0 ? `${String(n)}, ${String(errors)} unanswered` : n),
  },
  { header: "Action", align: "right", cell: ({ action_accuracy: value }) => rate(value) },
  { header: "Exact match", align: "right", cell: ({ exact_match: value }) => rate(value) },
  { header: "Response", align: "right", cell: ({ behavior_accuracy: value }) => rate(value) },
  { header: "Refusals", align: "right", cell: ({ refusal_rate: value }) => rate(value) },
  {
    header: "Plans valid, first and after repair",
    align: "right",
    nowrap: true,
    cell: ({ plan_valid_before_repair: first, plan_valid_after_repair: after }) =>
      `${rate(first)}, ${rate(after)}`,
  },
];

const STEPS: Record<string, string> = {
  understood: "not understood",
  planned: "not planned",
  "as asked": "not as asked",
  ran: "did not run to success",
  deployed: "not answering on staging",
};

const E2E_COLUMNS: readonly Column<EvaluationEndToEndRow>[] = [
  {
    header: "Model",
    rowHeader: true,
    nowrap: true,
    cell: ({ model, complete }) => withState(model ?? "Not recorded", complete),
  },
  {
    header: "Succeeded",
    align: "right",
    cell: ({ succeeded, n }) =>
      succeeded === null || n === null ? NOT_MEASURED : `${String(succeeded)} of ${String(n)}`,
  },
  { header: "Rate", align: "right", cell: ({ success_rate: value }) => rate(value) },
  {
    header: "Failures",
    cell: ({ failed_at: failed }) => {
      const parts = Object.entries(failed ?? {}).map(
        ([step, times]) => `${String(times)} ${STEPS[step] ?? step}`,
      );
      return parts.length > 0 ? parts.join(", ") : "None";
    },
  },
  {
    header: "Freestyle",
    align: "right",
    cell: ({ by_assistant: cells }) => assistantCell(cells?.freestyle),
  },
  {
    header: "Pipeline",
    align: "right",
    cell: ({ by_assistant: cells }) => assistantCell(cells?.pipeline),
  },
];

function assistantCell(cell: { n: number; succeeded: number } | undefined): string {
  return cell ? `${String(cell.succeeded)} of ${String(cell.n)}` : NOT_MEASURED;
}
